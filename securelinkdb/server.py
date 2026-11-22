import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets
import socket
import struct
import subprocess
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import collections

import numpy as np
import scipy.signal as signal
import torch
import torch.nn.functional as F
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.staticfiles import StaticFiles
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import uvicorn

from tunnel_manager import CloudflareTunnelManager, TunnelState
from mobile_pairing import MobilePairingManager, PairingState

import sys

# Prevent Windows CP1252 UnicodeEncodeError crashes on emojis/special characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ensure Windows locates cuBLAS and cuDNN DLLs from PyTorch package for CTranslate2 / Faster-Whisper
if torch.cuda.is_available():
    torch_lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(torch_lib_dir):
        try:
            os.add_dll_directory(torch_lib_dir)
        except Exception:
            pass
        os.environ["PATH"] = torch_lib_dir + os.path.pathsep + os.environ.get("PATH", "")

# Suppress verbose websocket protocol logs
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
logging.getLogger("websockets.protocol").setLevel(logging.CRITICAL)


class TranscriptionStatus(str, Enum):
    NO_SPEECH = "NO_SPEECH"
    SPEECH_DETECTED = "SPEECH_DETECTED"
    TRANSCRIBED = "TRANSCRIBED"
    UNCERTAIN_TRANSCRIPTION = "UNCERTAIN_TRANSCRIPTION"
    TRANSCRIPTION_REJECTED = "TRANSCRIPTION_REJECTED"


@dataclass
class TranscriptionResult:
    status: TranscriptionStatus
    transcript: str = ""
    reason: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    audio_quality: Dict[str, Any] = field(default_factory=dict)
    processing_info: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.transcript

    def __bool__(self) -> bool:
        return bool(self.transcript)

app = FastAPI(title="SecureLink AI Inference Server")

# Ensure required storage directories exist
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
AUDIO_RECORDINGS_DIR = os.path.join(RECORDINGS_DIR, "audio")
SNAPSHOTS_RECORDINGS_DIR = os.path.join(RECORDINGS_DIR, "snapshots")
os.makedirs(AUDIO_RECORDINGS_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_RECORDINGS_DIR, exist_ok=True)

# Mount recordings directory so dashboard and client devices can fetch/replay audio and snapshots
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR), name="recordings")

# =========================================================================
# 1. FASTER-WHISPER SPEECH-TO-TEXT SETUP
# =========================================================================
print("\n[SYS] Initializing Faster-Whisper ASR Engine...")
try:
    from faster_whisper import WhisperModel  # type: ignore
    # Auto-detect CUDA GPU, otherwise use multi-threaded CPU INT8
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "int8" if device == "cpu" else "float16"
    model_size = "large-v3-turbo" if device == "cuda" else "medium"
    
    print(f"[SYS] Loading Faster-Whisper ({model_size}) on {device.upper()} ({compute_type})...")
    whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    has_whisper = True
    print(f"[SYS] Faster-Whisper ({model_size}) loaded successfully on {device.upper()}!")
except Exception as e:
    print(f"[WARN] Failed to load Faster-Whisper: {e}")
    print("[WARN] Running with fallback transcription stub.")
    has_whisper = False
    whisper_model = None

# =========================================================================
# 1.1 ANTI-HALLUCINATION CONFIGURATION
# =========================================================================
# Whisper treats initial_prompt as fake preceding conversation history.
# Paragraph prompts trigger endless repetition loops ("magandang magandang...").
# Keeping it empty or tiny ("Hello.") completely starves Whisper of hallucination seeds.
INITIAL_TAGALOG_PROMPT = ""

# Hotwords: strictly true safety threats & physical violence terms (15-20 words max).
# Never include conversational slang like 'taray' or 'ganda' which Whisper hallucinates from fan noise.
TAGALOG_HOTWORDS = None

# Content words from common prompt-echo regurgitations to discard immediately
PROMPT_ECHO_WORDS = {
    "magandang", "araw", "umaga", "hapon", "gabi", "kumusta", "usapan",
    "tagalog", "filipino", "paaralan", "silid-aralan", "sandali", "opo", "tara"
}

# =========================================================================
# 2. SERVER-SIDE ACOUSTIC DENOISING SETUP (MICROSOFT NSNet2 + NOISEREDUCE)
# =========================================================================
print("\n[SYS] Initializing Server-side Acoustic Denoising (Microsoft NSNet2)...")
has_nsnet2 = False
nsnet2_denoiser = None

try:
    from nsnet2 import NSNet2Denoiser
    nsnet2_denoiser = NSNet2Denoiser()
    has_nsnet2 = True
    print("[SYS] Microsoft NSNet2 Neural Noise Suppression loaded! Fan/AC isolation ACTIVE.")
except Exception as e:
    print(f"[WARN] Failed to initialize NSNet2 ({e}).")
    has_nsnet2 = False

# Adjustable noise reduction strength (0.0 = transparent/off, 1.0 = maximum suppression)
# 0.50 is the balanced sweet spot: fan noise is eliminated while trailing syllables decay smoothly
DENOISE_STRENGTH = 0.50

try:
    import noisereduce as nr  # type: ignore
    has_noisereduce = True
except Exception:
    has_noisereduce = False

# =========================================================================
# 3. TAGALOG BERT THREAT CLASSIFIER SETUP
# =========================================================================
print("\n[SYS] Loading fine-tuned TagalogBERT into memory...")
MODEL_PATH = os.path.join(BASE_DIR, "securelink_final_model")
if not os.path.exists(MODEL_PATH):
    alt_path = os.path.join(BASE_DIR, "securelink_tagalogbert")
    if os.path.exists(alt_path):
        MODEL_PATH = alt_path

try:
    if os.path.isdir(MODEL_PATH):
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
        bert_model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH, local_files_only=True)
    else:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        bert_model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
    if torch.cuda.is_available():
        bert_model = bert_model.to("cuda")
        print("[SYS] TagalogBERT loaded successfully on CUDA!")
    else:
        print("[SYS] TagalogBERT loaded successfully on CPU.")
    bert_model.eval()
except Exception as e:
    print(f"[ERR] Failed to load fine-tuned model from {MODEL_PATH}: {e}")
    tokenizer = None
    bert_model = None

# =========================================================================
# 4. CONTEXT ENGINE (NLP CLASSIFICATION + INTENT & SEVERITY ASSESSMENT V3)
# =========================================================================
from context_engine import (
    ContextEngine,
    ThreatIntent,
    ThreatType,
    Targetedness,
    Imminence,
    EvidenceReliability,
    IncidentLevel,
    ContextExtraction,
    SeverityAssessment,
    context_engine,
)

# Connect fine-tuned TagalogBERT and tokenizer to the ContextEngine instance
context_engine.bert_model = bert_model
context_engine.tokenizer = tokenizer

# =========================================================================
# 5. WEBSOCKET & DEVICE FLEET ORCHESTRATION & AUTHENTICATION
# =========================================================================
ui_clients = set()
registered_devices = {}
active_pins = {} # Map of websocket -> device_id
pin_active_sockets = {} # Authoritative map of device_id -> newest active websocket
harmful_words_only = False # Default False so all speech during testing is visible on the dashboard!

# --- SECURE DEVICE PAIRING & TOKEN PERSISTENCE ---
DEVICE_CREDENTIALS_FILE = os.path.join(BASE_DIR, "device_credentials.json")
ACTIVE_PAIRING_CODES_FILE = os.path.join(BASE_DIR, "active_pairing_codes.json")

def load_active_pairing_codes() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(ACTIVE_PAIRING_CODES_FILE):
        try:
            with open(ACTIVE_PAIRING_CODES_FILE, "r", encoding="utf-8") as f:
                codes = json.load(f)
                now = time.time()
                return {k: v for k, v in codes.items() if now <= v.get("expires_at", 0)}
        except Exception:
            pass
    return {}

def save_active_pairing_codes():
    try:
        now = time.time()
        valid = {k: v for k, v in active_pairing_codes.items() if now <= v.get("expires_at", 0)}
        with open(ACTIVE_PAIRING_CODES_FILE, "w", encoding="utf-8") as f:
            json.dump(valid, f, indent=2)
    except Exception as e:
        print(f"[PAIRING] Error saving active pairing codes: {e}")

active_pairing_codes: Dict[str, Dict[str, Any]] = load_active_pairing_codes()
pairing_code_rate_limit: Dict[str, List[float]] = {}  # ip -> list of timestamps

class PinRegistrationState:
    UNPROVISIONED = "UNPROVISIONED"
    PROVISIONING = "PROVISIONING"
    WIFI_CONNECTED = "WIFI_CONNECTED"
    REGISTERING = "REGISTERING"
    AUTHENTICATING = "AUTHENTICATING"
    PAIRED = "PAIRED"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"

    # Compatibility aliases
    UNREGISTERED = "UNREGISTERED"
    PENDING = "PENDING"

PENDING_REGISTRATION_TIMEOUT = 180.0  # seconds (3 minutes)
pending_registrations: Dict[str, Dict[str, Any]] = {}  # in-memory pending registrations awaiting WS authentication
pin_registration_lock = asyncio.Lock()

def cleanup_expired_pending_registrations():
    now = time.time()
    expired = [k for k, v in list(pending_registrations.items()) if now > v.get("expires_at", 0)]
    for k in expired:
        print(f"[PAIRING] Pending registration for '{k}' expired after {int(PENDING_REGISTRATION_TIMEOUT)}s without WebSocket authentication.")
        pending_registrations.pop(k, None)

def get_device_registration_state(device_id: str) -> str:
    clean_id = device_id.strip().upper()
    if clean_id in registered_devices and registered_devices[clean_id].get("paired", False):
        if any(d_id == clean_id for d_id in active_pins.values()):
            return PinRegistrationState.PAIRED
        return PinRegistrationState.OFFLINE
    cleanup_expired_pending_registrations()
    if clean_id in pending_registrations:
        return PinRegistrationState.PENDING
    creds = load_device_credentials()
    if clean_id in creds:
        return PinRegistrationState.OFFLINE
    return PinRegistrationState.UNREGISTERED

def load_device_credentials() -> Dict[str, Any]:
    if os.path.exists(DEVICE_CREDENTIALS_FILE):
        try:
            with open(DEVICE_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[AUTH] Error reading device credentials: {e}")
    return {}

def save_device_credentials(creds: Dict[str, Any]):
    try:
        with open(DEVICE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(creds, f, indent=2)
    except Exception as e:
        print(f"[AUTH] Error saving device credentials: {e}")

def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def verify_device_token(device_id: str, token: str) -> bool:
    if not device_id or not token:
        return False
    creds = load_device_credentials()
    dev_entry = creds.get(device_id)
    if not dev_entry:
        return False
    expected_hash = dev_entry.get("token_hash", "")
    actual_hash = hash_device_token(token)
    return secrets.compare_digest(expected_hash, actual_hash)

def init_registered_devices_from_credentials():
    creds = load_device_credentials()
    for dev_id, info in creds.items():
        if dev_id not in registered_devices:
            registered_devices[dev_id] = {
                "id": dev_id,
                "online": False,
                "battery": 100,
                "state": "OFFLINE",
                "network": "Campus Wi-Fi",
                "lastSeen": info.get("registered_at", "Registered"),
                "cpuMhz": 160,
                "rssi": -70,
                "estRuntime": "--",
                "paired": True,
            }


# --- CLOUDFLARE QUICK TUNNEL & MOBILE PAIRING MANAGERS ---
TUNNEL_CONFIG_FILE = os.path.join(BASE_DIR, "tunnel_config.json")
current_cloud_tunnel_url: Optional[str] = None
active_mobile_clients: Dict[WebSocket, dict] = {}
relayed_audio_accumulators: Dict[str, bytearray] = {}
recent_incidents: collections.deque = collections.deque(maxlen=50)

async def _on_tunnel_url_changed(new_url: Optional[str]):
    global current_cloud_tunnel_url
    current_cloud_tunnel_url = new_url
    await broadcast_to_clients({
        "event_type": "cloud_tunnel_update",
        "cloud_tunnel_url": new_url
    })

tunnel_mgr = CloudflareTunnelManager(port=8080, on_url_change=_on_tunnel_url_changed)
mobile_pairing_mgr = MobilePairingManager(cs_id="CS-CAMPUS-01", cs_name="SecureLink Campus Central System")

def get_active_tunnel_url() -> Optional[str]:
    return tunnel_mgr.active_url or current_cloud_tunnel_url

# Load existing tunnel_config if available
if os.path.exists(TUNNEL_CONFIG_FILE):
    try:
        with open(TUNNEL_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            t_url = cfg.get("cloud_tunnel_url")
            if t_url:
                current_cloud_tunnel_url = t_url
                tunnel_mgr.active_url = t_url
                tunnel_mgr.state = TunnelState.CONNECTED
                print(f"[TUNNEL] Loaded active Cloudflare Tunnel: {current_cloud_tunnel_url}")
    except Exception:
        pass

async def broadcast_to_clients(payload: dict):
    message = json.dumps(payload)
    # 1. UI Clients (Desktop Dashboard)
    dead_ui = set()
    for client in list(ui_clients):
        try:
            await client.send_text(message)
        except Exception:
            dead_ui.add(client)
    ui_clients.difference_update(dead_ui)

    # 2. Mobile Companion Clients (/mobile)
    dead_mobile = set()
    for mclient, minfo in list(active_mobile_clients.items()):
        try:
            await mclient.send_text(message)
        except Exception:
            dead_mobile.add(mclient)
    for dm in dead_mobile:
        active_mobile_clients.pop(dm, None)

# Alias for backwards compatibility
broadcast_to_ui = broadcast_to_clients

@app.get("/health")
@app.get("/")
async def health_check():
    return {
        "status": "online",
        "app": "SecureLink AI Server",
        "whisper": has_whisper,
        "classifier": bert_model is not None,
        "cloud_tunnel_url": get_active_tunnel_url(),
        "tunnel_state": tunnel_mgr.state,
    }

@app.get("/api/cloud-tunnel")
async def get_cloud_tunnel():
    st = tunnel_mgr.get_status()
    # Ensure backwards compatibility for callers expecting cloud_tunnel_url string
    st["cloud_tunnel_url"] = st.get("cloud_tunnel_url") or current_cloud_tunnel_url
    return st

@app.post("/api/cloud-tunnel/start")
async def start_cloud_tunnel_api():
    """Starts the Cloudflare Quick Tunnel forwarding to port 8080."""
    res = await tunnel_mgr.start()
    return res

@app.post("/api/cloud-tunnel/stop")
async def stop_cloud_tunnel_api():
    """Cleanly terminates the Cloudflare Quick Tunnel."""
    res = await tunnel_mgr.stop()
    return res

@app.post("/api/cloud-tunnel")
async def set_cloud_tunnel(payload: dict):
    """Compatibility endpoint to manually register or notify the server of an active tunnel URL."""
    global current_cloud_tunnel_url
    url = payload.get("cloud_tunnel_url")
    if url:
        current_cloud_tunnel_url = str(url).strip()
        tunnel_mgr.active_url = current_cloud_tunnel_url
        tunnel_mgr.state = TunnelState.CONNECTED
        tunnel_mgr._save_config(current_cloud_tunnel_url)
        print(f"[TUNNEL] Cloudflare Tunnel URL updated: {current_cloud_tunnel_url}")
        await broadcast_to_clients({
            "event_type": "cloud_tunnel_update",
            "cloud_tunnel_url": current_cloud_tunnel_url
        })
    return {"status": "success", "cloud_tunnel_url": current_cloud_tunnel_url}

@app.get("/api/network-info")
async def get_network_info():
    import serial.tools.list_ports as lp
    ports = []
    try:
        for p in lp.comports():
            hw = (p.hwid or "").upper()
            desc = (p.description or "")
            is_esp = ("303A" in hw or "ESP" in desc.upper() or "CH340" in desc.upper() or "CP210" in desc.upper() or "SERIAL" in desc.upper())
            ports.append({
                "port": p.device,
                "description": desc,
                "hwid": hw,
                "is_esp": is_esp
            })
    except Exception as e:
        print(f"[SERIAL] Error enumerating ports: {e}")
    
    return {
        "server_ip": get_primary_ip(),
        "server_port": 8080,
        "serial_ports": ports,
        "active_pins": len(active_pins),
        "harmful_words_only": harmful_words_only,
    }

@app.get("/api/devices")
async def get_devices():
    """Returns all currently registered and active smart pins on the network."""
    devices_list = []
    for dev_id, dev in registered_devices.items():
        is_active = any(d_id == dev_id for d_id in active_pins.values())
        dev_copy = dict(dev)
        dev_copy["online"] = is_active
        if not is_active and dev_copy.get("state") != "OFFLINE":
            dev_copy["state"] = "OFFLINE"
        devices_list.append(dev_copy)
    return {
        "status": "success",
        "devices": devices_list,
        "active_count": len([d for d in devices_list if d.get("online")]),
        "total_count": len(devices_list),
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }

@app.post("/api/toggle-harmful-only")
async def toggle_harmful_only(payload: dict = None):
    global harmful_words_only
    payload = payload or {}
    if "enabled" in payload:
        harmful_words_only = bool(payload["enabled"])
    else:
        harmful_words_only = not harmful_words_only
    print(f"[FILTER] Harmful Words Only Mode toggled to: {harmful_words_only}")
    await broadcast_to_ui({
        "event_type": "harmful_only_update",
        "enabled": harmful_words_only
    })
    return {"status": "success", "harmful_words_only": harmful_words_only}

@app.get("/api/filter-mode")
async def get_filter_mode():
    return {"status": "success", "harmful_words_only": harmful_words_only}

@app.get("/api/denoise-settings")
async def get_denoise_settings():
    return {
        "status": "success",
        "strength": DENOISE_STRENGTH,
        "mingain_db": -18.0,
        "engine": "Microsoft NSNet2" if has_nsnet2 else "NoiseReduce",
        "description": "0.0 (off) to 1.0 (max). 0.60 protects vowels, nasal consonants ('ng','n','m') and pauses."
    }

@app.post("/api/denoise-settings")
async def set_denoise_settings(payload: dict):
    global DENOISE_STRENGTH
    if "strength" in payload:
        try:
            val = float(payload["strength"])
            DENOISE_STRENGTH = float(np.clip(val, 0.0, 1.0))
            print(f"[DENOISE] Noise reduction strength updated to: {DENOISE_STRENGTH:.2f}")
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "success", "strength": DENOISE_STRENGTH}

# =========================================================================
# CHECKPOINTS PERSISTENCE & FLEET WI-FI MANAGEMENT
# =========================================================================
CHECKPOINTS_FILE = "checkpoints.json"
pending_wifi_configs = {} # target ("ALL" or "PIN-001") -> dict

def load_checkpoints() -> list:
    if os.path.exists(CHECKPOINTS_FILE):
        try:
            with open(CHECKPOINTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CFG] Error reading {CHECKPOINTS_FILE}: {e}")
    
    server_ip = get_primary_ip()
    default_chks = [
        {
            "id": "chk_main",
            "name": "Main Campus / Admin Office",
            "ssid": "SLTYMTBLLS",
            "pass": "9945SUmaxx!",
            "server_ip": server_ip,
            "server_port": 8080,
            "is_default": True,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_deployed": None
        },
        {
            "id": "chk_library",
            "name": "Library & Study Hub",
            "ssid": "Campus-Library-Secure",
            "pass": "LibraryPass2026",
            "server_ip": server_ip,
            "server_port": 8080,
            "is_default": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_deployed": None
        },
        {
            "id": "chk_gate",
            "name": "Security Gate & Perimeter",
            "ssid": "Security-Gate-AP01",
            "pass": "SecureGate99!",
            "server_ip": server_ip,
            "server_port": 8080,
            "is_default": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_deployed": None
        }
    ]
    save_checkpoints(default_chks)
    return default_chks

def save_checkpoints(chks: list):
    try:
        with open(CHECKPOINTS_FILE, "w", encoding="utf-8") as f:
            json.dump(chks, f, indent=2)
    except Exception as e:
        print(f"[CFG] Error saving {CHECKPOINTS_FILE}: {e}")

@app.get("/api/checkpoints")
async def get_checkpoints_api():
    chks = load_checkpoints()
    return {
        "status": "success",
        "checkpoints": chks,
        "server_ip": get_primary_ip(),
        "server_port": 8080,
        "registered_pins": list(registered_devices.keys()),
        "active_pins": list(active_pins.values()),
        "pending_configs": pending_wifi_configs
    }

@app.post("/api/checkpoints")
async def save_checkpoint_api(payload: dict):
    chks = load_checkpoints()
    chk_id = payload.get("id") or f"chk_{int(time.time()*1000)}"
    name = str(payload.get("name", "Campus AP")).strip()
    ssid = str(payload.get("ssid", "")).strip()
    password = str(payload.get("pass", "")).strip()
    server_ip = str(payload.get("server_ip") or get_primary_ip()).strip()
    try:
        server_port = int(payload.get("server_port") or 8080)
    except (ValueError, TypeError):
        server_port = 8080
    is_default = bool(payload.get("is_default", False))

    if not ssid:
        return {"status": "error", "message": "Wi-Fi SSID cannot be empty."}

    if is_default:
        for c in chks:
            c["is_default"] = False

    updated = False
    for c in chks:
        if c.get("id") == chk_id:
            c["name"] = name
            c["ssid"] = ssid
            c["pass"] = password
            c["server_ip"] = server_ip
            c["server_port"] = server_port
            c["is_default"] = is_default
            updated = True
            break
    
    if not updated:
        chks.append({
            "id": chk_id,
            "name": name,
            "ssid": ssid,
            "pass": password,
            "server_ip": server_ip,
            "server_port": server_port,
            "is_default": is_default,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_deployed": None
        })

    save_checkpoints(chks)
    await broadcast_to_ui({"event_type": "checkpoints_updated", "checkpoints": chks})
    return {"status": "success", "checkpoints": chks}

@app.delete("/api/checkpoints/{chk_id}")
async def delete_checkpoint_api(chk_id: str):
    chks = load_checkpoints()
    chks = [c for c in chks if c.get("id") != chk_id]
    save_checkpoints(chks)
    await broadcast_to_ui({"event_type": "checkpoints_updated", "checkpoints": chks})
    return {"status": "success", "checkpoints": chks}

@app.post("/api/checkpoints/deploy")
async def deploy_checkpoint_api(payload: dict):
    chks = load_checkpoints()
    chk_id = payload.get("checkpoint_id")
    target = payload.get("target", "ALL") # "ALL" or specific PIN id e.g. "PIN-001"
    method = payload.get("method", "wifi") # "wifi" or "usb"

    chk = next((c for c in chks if c.get("id") == chk_id), None)
    if chk:
        ssid = chk["ssid"]
        pwd = chk["pass"]
        srv_ip = chk.get("server_ip") or get_primary_ip()
        srv_port = int(chk.get("server_port") or 8080)
        chk_name = chk["name"]
        chk["last_deployed"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_checkpoints(chks)
    else:
        ssid = str(payload.get("ssid", "")).strip()
        pwd = str(payload.get("pass", "")).strip()
        srv_ip = str(payload.get("server_ip") or get_primary_ip()).strip()
        try:
            srv_port = int(payload.get("server_port") or 8080)
        except (ValueError, TypeError):
            srv_port = 8080
        chk_name = str(payload.get("name") or ssid)

    if not ssid:
        return {"status": "error", "message": "No valid Wi-Fi SSID provided for deployment."}

    if method == "usb":
        port = payload.get("com_port") or payload.get("port")
        if not port:
            return {"status": "error", "message": "USB COM port is required for USB deployment."}
        import serial
        try:
            print(f"\n[PROVISION-USB] Flashing checkpoint '{chk_name}' to {port}...")
            ser = serial.Serial(port, 115200, timeout=1.2)
            time.sleep(0.3)
            ser.reset_input_buffer()
            cmd_line = f"SET_WIFI:{ssid}:{pwd}:{srv_ip}:{srv_port}\n"
            ser.write(cmd_line.encode("utf-8"))
            ser.flush()
            time.sleep(0.3)
            logs = []
            t_end = time.time() + 2.0
            while time.time() < t_end:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        logs.append(line)
                        if "OK:CONFIG_SAVED" in line:
                            break
                time.sleep(0.04)
            ser.close()
            return {
                "status": "success",
                "message": f"Checkpoint '{chk_name}' flashed to {port} via USB! Pin is connecting to '{ssid}'...",
                "logs": logs
            }
        except Exception as e:
            return {"status": "error", "message": f"USB error on {port}: {e}"}

    # Method == "wifi" (Live OTA WebSocket + Queued Sync)
    cfg_cmd = f"CONFIG:WIFI:{ssid}:{pwd}:{srv_ip}:{srv_port}"
    dispatched_count = 0

    # Save to pending queue so pins in modem sleep receive it immediately upon next transmission
    pending_wifi_configs[target] = {
        "ssid": ssid,
        "pass": pwd,
        "server_ip": srv_ip,
        "server_port": srv_port,
        "checkpoint_name": chk_name,
        "queued_at": datetime.now().strftime("%H:%M:%S")
    }

    # Dispatch to currently connected pins
    for pin_ws, dev_id in list(active_pins.items()):
        if target == "ALL" or target == dev_id:
            try:
                await pin_ws.send_text(cfg_cmd)
                dispatched_count += 1
                if dev_id in registered_devices:
                    registered_devices[dev_id]["network"] = ssid
                    registered_devices[dev_id]["state"] = "UPDATING WI-FI"
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[dev_id]})
            except Exception as e:
                print(f"[CFG] Failed to push Wi-Fi to {dev_id}: {e}")

    # Update network label on registered devices
    if target == "ALL":
        for dev in registered_devices.values():
            dev["network"] = ssid
            await broadcast_to_ui({"event_type": "device_update", "device": dev})
    elif target in registered_devices:
        registered_devices[target]["network"] = ssid
        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[target]})

    await broadcast_to_ui({
        "event_type": "checkpoint_deployed",
        "checkpoint_name": chk_name,
        "ssid": ssid,
        "target": target,
        "dispatched_count": dispatched_count,
        "message": f"Checkpoint '{chk_name}' sent to {dispatched_count} active pin(s). Queued for offline/sleep pins."
    })

    return {
        "status": "success",
        "target": target,
        "dispatched_count": dispatched_count,
        "message": f"Checkpoint '{chk_name}' sent to {dispatched_count} live pin(s). Queued for next connection."
    }

@app.post("/api/provision-pin")
async def provision_pin_serial(payload: dict):
    port = payload.get("port")
    ssid = str(payload.get("ssid", "")).strip()
    # Preserve exact password without stripping leading/trailing whitespace
    password = str(payload.get("pass", ""))
    raw_ip = str(payload.get("server_ip", "")).strip()
    if not raw_ip or raw_ip in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        server_ip = get_primary_ip()
    else:
        server_ip = raw_ip
    try:
        server_port = int(payload.get("server_port", 8080))
    except (ValueError, TypeError):
        server_port = 8080

    if not port:
        return {"status": "error", "stage": "serial_failed", "message": "No USB COM port selected."}
    if not ssid:
        return {"status": "error", "stage": "serial_failed", "message": "Wi-Fi SSID cannot be empty."}

    import serial
    ser = None
    try:
        print(f"\n[PROVISION] Stage 1: Opening serial port {port} at 115200 baud...")
        ser = serial.Serial(port, 115200, timeout=1.5)
        time.sleep(0.3)
        ser.reset_input_buffer()

        pcode = str(payload.get("pairing_code", "")).strip().replace(" ", "").replace("-", "")

        # Stage 2: Transmit JSON provisioning command
        json_cmd = json.dumps({
            "cmd": "provision",
            "ssid": ssid,
            "password": password,
            "server": server_ip,
            "port": server_port,
            "pairing_code": pcode
        }) + "\n"

        pcode_masked = f"{pcode[:2]}****" if len(pcode) >= 4 else "****"
        print(f"[PROVISION] Stage 2: Transmitting JSON provisioning command (SSID: '{ssid}', Server: {server_ip}:{server_port}, Pairing Code: {pcode_masked})")
        ser.write(json_cmd.encode("utf-8"))
        ser.flush()

        # Stage 3 & 4: Monitor ESP32 acknowledgments
        logs = []
        ack_received = False
        ack_saved = False
        start_ack_t = time.time()

        while time.time() - start_ack_t < 3.5:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    logs.append(line)
                    print(f"[PIN-SERIAL] {line}")
                    if '"status":"received"' in line:
                        ack_received = True
                    if '"status":"saved"' in line or "OK:CONFIG_SAVED" in line:
                        ack_saved = True
                        break
            time.sleep(0.04)

        # Fallback to legacy protocol if JSON was not acknowledged
        if not ack_saved and not ack_received:
            print("[PROVISION] JSON unacknowledged, transmitting legacy SET_WIFI fallback...")
            legacy_cmd = f"SET_WIFI:{ssid}:{password}:{server_ip}:{server_port}:{pcode}\n"
            ser.write(legacy_cmd.encode("utf-8"))
            ser.flush()
            fallback_t = time.time()
            while time.time() - fallback_t < 2.5:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        logs.append(line)
                        print(f"[PIN-SERIAL] {line}")
                        if "OK:CONFIG_SAVED" in line:
                            ack_saved = True
                            break
                time.sleep(0.04)

        if not ack_saved:
            ser.close()
            return {
                "status": "error",
                "stage": "serial_failed",
                "code": "ERR_SERIAL_NO_ACK",
                "message": f"Smart Pin on {port} did not acknowledge provisioning command.",
                "logs": logs
            }

        print("[PROVISION] Stages 3 & 4 Passed: ESP32 acknowledged command and confirmed credentials saved.")

        # Stage 5, 6, 7 & 8: Monitor reboot, Wi-Fi connection, and Central System authentication
        wifi_connected = False
        wifi_failed = False
        wifi_err_msg = ""
        pin_ip = ""
        authenticated = False
        paired_device_id = None

        monitor_start = time.time()
        while time.time() - monitor_start < 18.0:
            # Read serial output if available
            try:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        logs.append(line)
                        print(f"[PIN-SERIAL] {line}")
                        if "Got IP:" in line or "Smart Pin IP:" in line:
                            wifi_connected = True
                            parts = line.split(":")
                            if len(parts) >= 2:
                                pin_ip = parts[-1].strip().split(" ")[0]
                        if "ERR_AUTH_REJECTED" in line or "Authentication rejected" in line:
                            wifi_failed = True
                            wifi_err_msg = "Wi-Fi password rejected by access point."
                        elif "ERR_AP_NOT_FOUND" in line or "not found" in line:
                            wifi_failed = True
                            wifi_err_msg = f"Wi-Fi access point '{ssid}' not found (verify 2.4 GHz network)."
            except Exception:
                pass

            # Check if Central System verified the pairing code and authenticated the WebSocket
            if pcode:
                code_data = active_pairing_codes.get(pcode)
                if code_data:
                    dev_id = code_data.get("device_id")
                    if code_data.get("paired", False) or (dev_id and dev_id in registered_devices and registered_devices[dev_id].get("paired", False)):
                        authenticated = True
                        paired_device_id = dev_id
                        break

            if wifi_failed:
                break

            await asyncio.sleep(0.3)

        try:
            ser.close()
        except Exception:
            pass

        if authenticated:
            print(f"[PROVISION] Full Lifecycle Verified! Smart Pin '{paired_device_id}' authenticated with Central System.")
            return {
                "status": "success",
                "stage": "authenticated",
                "device_id": paired_device_id,
                "server_ip": server_ip,
                "server_port": server_port,
                "message": f"Smart Pin {paired_device_id} successfully provisioned, connected to Wi-Fi '{ssid}', and authenticated with Central System!",
                "logs": logs
            }

        if wifi_failed:
            return {
                "status": "error",
                "stage": "wifi_failed",
                "code": "ERR_WIFI_FAILED",
                "message": f"Credentials saved, but Smart Pin Wi-Fi connection failed: {wifi_err_msg}",
                "logs": logs
            }

        if wifi_connected:
            return {
                "status": "partial",
                "stage": "wifi_connected_unauthenticated",
                "message": f"Credentials saved and Smart Pin connected to Wi-Fi '{ssid}' (IP: {pin_ip}), but Central System WebSocket authentication did not complete within timeout. Verify server address and firewall.",
                "logs": logs
            }

        return {
            "status": "partial",
            "stage": "credentials_saved_pending_reboot",
            "server_ip": server_ip,
            "server_port": server_port,
            "message": f"Wi-Fi credentials flashed to {port}! Pin is rebooting to connect to '{ssid}'. Check Dashboard in a few seconds.",
            "logs": logs
        }
    except Exception as e:
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        print(f"[PROVISION] Error on {port}: {e}")
        return {"status": "error", "stage": "serial_failed", "message": f"Could not communicate with {port}: {str(e)}"}


@app.websocket("/ui")
async def ui_websocket_endpoint(websocket: WebSocket):
    global harmful_words_only
    await websocket.accept()
    ui_clients.add(websocket)
    print(f"\n[UI] Dashboard station connected! Active UI clients: {len(ui_clients)}")
    
    # Immediately send handshake confirmation so Dashboard transitions to ONLINE
    await websocket.send_text(json.dumps({
        "event_type": "server_status",
        "status": "online",
        "message": "SecureLink AI Server Online",
        "whisper": has_whisper,
        "classifier": bert_model is not None,
        "harmful_words_only": harmful_words_only,
        "cloud_tunnel_url": current_cloud_tunnel_url,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }))

    # Send current device states on dashboard connect (mark devices without active socket as OFFLINE)
    for dev_id, dev in registered_devices.items():
        is_active = any(d_id == dev_id for d_id in active_pins.values())
        if not is_active:
            dev["online"] = False
            dev["state"] = "OFFLINE"
        await websocket.send_text(json.dumps({"event_type": "device_update", "device": dev}))
        
    # Send saved checkpoints on connect
    await websocket.send_text(json.dumps({
        "event_type": "checkpoints_updated",
        "checkpoints": load_checkpoints()
    }))

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"event_type": "pong"}))
                continue
            if data in ("TRIGGER:DANGER", "CMD:CAPTURE_SNAPSHOT"):
                print(f"[UI] Relay camera snapshot command to all active pins: {data}")
                for pin_ws in list(active_pins.keys()):
                    try:
                        await pin_ws.send_text(data)
                    except Exception:
                        pass
                continue
            
            # Handle fleet configuration deployed from Flutter Configuration Tab
            try:
                msg = json.loads(data)
                ev_type = msg.get("event_type")
                if ev_type == "fleet_config":
                    print(f"[CFG] Received fleet configuration from dashboard: {msg}")
                    buf_sec = msg.get("buffer_duration", 4)
                    for pin_ws in list(active_pins.keys()):
                        try:
                            await pin_ws.send_text(f"CONFIG:BUFFER:{buf_sec}")
                        except Exception:
                            pass
                elif ev_type == "deploy_wifi_checkpoint":
                    # WebSocket deployment trigger
                    await deploy_checkpoint_api(msg)
                elif ev_type in ("forget_wifi", "pin_command"):
                    cmd = msg.get("command", "CMD:FORGET_WIFI")
                    print(f"[UI] Relay command to pins: {cmd}")
                    dispatched = 0
                    for pin_ws in list(active_pins.keys()):
                        try:
                            await pin_ws.send_text(cmd)
                            dispatched += 1
                        except Exception:
                            pass
                    await websocket.send_text(json.dumps({
                        "event_type": "cmd_acknowledgement",
                        "status": "success",
                        "command": cmd,
                        "dispatched_count": dispatched,
                        "message": f"Command {cmd} sent to {dispatched} active smart pin(s). Pin will enter Setup Portal."
                    }))
                elif ev_type == "set_harmful_only":
                    harmful_words_only = bool(msg.get("enabled", False))
                    print(f"\n[FILTER] Harmful Words Only Mode set to: {harmful_words_only}")
                    await broadcast_to_ui({
                        "event_type": "harmful_only_update",
                        "enabled": harmful_words_only
                    })
            except Exception as e:
                print(f"[UI] Error processing message: {e}")
    except WebSocketDisconnect:
        ui_clients.remove(websocket)
        print("\n[UI] Dashboard disconnected gracefully.")
    except Exception:
        if websocket in ui_clients:
            ui_clients.remove(websocket)

# =========================================================================
# 6. UDP AUTO-DISCOVERY (PORT 8888) & CENTRAL SYSTEM GATEWAY
# =========================================================================
def get_primary_ip():
    # Attempt 1: Standard public DNS route probe (doesn't send packets, just probes OS routing table)
    for test_target in [('8.8.8.8', 80), ('1.1.1.1', 80), ('10.255.255.255', 1)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(test_target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith('127.'):
                return ip
        except Exception:
            pass
    # Attempt 2: Local hostname resolution
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    return '127.0.0.1'

class DiscoveryProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        print("[UDP] Central System discovery service listening on port 8888...")

    def datagram_received(self, data, addr):
        message = data.decode('utf-8', errors='ignore')
        if "SECURELINK" in message:
            true_ip = get_primary_ip()
            print(f"\n[UDP] Discovery broadcast from {addr} ('{message.strip()}'). Replying with server IP: {true_ip}...")
            # 1. Plaintext format for ESP32 Smart Pins (Priority 1: Central System)
            self.transport.sendto(f"ACK:{true_ip}".encode('utf-8'), addr)
            # 2. JSON structured discovery payload for Mobile Companions
            cs_payload = json.dumps({
                "type": "CS_DISCOVERY_ACK",
                "cs_id": "CS-CAMPUS-01",
                "server_ip": true_ip,
                "server_port": 8080,
                "name": "SecureLink Campus Central System",
                "priority": "PRIMARY_CS_1"
            })
            self.transport.sendto(cs_payload.encode('utf-8'), addr)

@app.get("/api/cs-info")
async def get_cs_info():
    """Provides Central System gateway identification and routing information for mobile companions."""
    true_ip = get_primary_ip()
    active_tunnel = get_active_tunnel_url()
    return {
        "status": "online",
        "cs_id": "CS-CAMPUS-01",
        "name": "SecureLink Campus Central System",
        "cloud_tunnel_url": active_tunnel,
        "tunnel_state": tunnel_mgr.state,
        "server_ip": true_ip,
        "server_port": 8080,
        "priority_level": "PRIMARY (Priority 1: Central System, Priority 2: Mobile App)",
        "active_pins_count": len(active_pins),
        "registered_pins": list(registered_devices.keys()),
        "ui_clients_count": len(ui_clients),
        "mobile_clients_count": len(active_mobile_clients),
        "harmful_words_only": harmful_words_only,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.post("/api/mobile-sync")
async def sync_mobile_companion(payload: dict):
    """Registers and synchronizes a mobile companion device with the Central System."""
    mobile_id = str(payload.get("mobile_id", "MOBILE-APP-01")).strip()
    user_name = str(payload.get("user_name", "Teacher / Student")).strip()
    role = str(payload.get("role", "Teacher")).strip()
    paired_pins = payload.get("paired_pins", [])
    if not isinstance(paired_pins, list):
        paired_pins = [str(paired_pins)]

    print(f"\n[MOBILE-SYNC] Mobile Companion '{mobile_id}' ({user_name} [{role}]) paired with pins: {paired_pins}")
    return {
        "status": "success",
        "cs_id": "CS-CAMPUS-01",
        "cs_name": "SecureLink Campus Central System",
        "server_ip": get_primary_ip(),
        "server_port": 8080,
        "paired_pins": paired_pins,
        "message": f"Successfully synchronized with Central System. Pins will route priority updates to CS-1."
    }

# =========================================================================
# SMART PIN ONBOARDING & CRYPTOGRAPHIC PAIRING APIS
# =========================================================================
@app.post("/api/pairing-code/generate")
async def generate_pairing_code_api(payload: Optional[dict] = None):
    """Generates an ephemeral 6-digit pairing code with a 10-minute TTL for pin pairing."""
    now = time.time()
    # Purge expired codes
    expired_codes = [c for c, d in list(active_pairing_codes.items()) if (now > d.get("expires_at", 0) and not d.get("used", False))]
    for ec in expired_codes:
        active_pairing_codes.pop(ec, None)

    # Generate 6-digit cryptographic numeric string
    for _ in range(100):
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        if code not in active_pairing_codes:
            break

    ttl_seconds = 600  # 10 minutes for reliable onboarding
    active_pairing_codes[code] = {
        "created_at": now,
        "expires_at": now + ttl_seconds,
        "used": False,
        "device_id": None,
    }
    save_active_pairing_codes()
    # Security requirement: Never log raw pairing codes
    print(f"\n[PAIRING] New 6-digit smart pin pairing code generated (TTL: {ttl_seconds}s)")
    return {
        "status": "success",
        "pairing_code": code,
        "expires_in": ttl_seconds,
        "expires_at": int(now + ttl_seconds),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.get("/api/pairing-code/status/{code}")
async def get_pairing_code_status(code: str):
    """Pollable endpoint for dashboard to check pairing progress for a specific code."""
    cleanup_expired_pending_registrations()
    code_data = active_pairing_codes.get(code.strip())
    now = time.time()
    if not code_data:
        return {
            "status": "error",
            "code": "ERR_NOT_FOUND",
            "message": "Pairing code not found or expired.",
            "valid": False,
            "used": False,
            "paired": False,
            "pending": False,
            "device_id": None,
        }
    is_expired = now > code_data.get("expires_at", 0)
    dev_id = code_data.get("device_id")
    is_paired = bool(code_data.get("paired", False) or (dev_id and dev_id in registered_devices and registered_devices[dev_id].get("paired", False)))
    is_pending = bool(dev_id and dev_id in pending_registrations)

    return {
        "status": "success",
        "valid": not is_expired and not code_data.get("used", False),
        "expired": is_expired,
        "used": code_data.get("used", False),
        "paired": is_paired,
        "pending": is_pending,
        "device_id": dev_id,
        "remaining_seconds": max(0, int(code_data.get("expires_at", 0) - now))
    }

@app.post("/api/pin/register")
async def register_pin_api(payload: dict):
    """
    Validates single-use pairing code and creates a temporary pending registration.
    The device is NOT marked paired or added to registered_devices until it
    connects to the physical pin WebSocket endpoint and proves token ownership.
    """
    device_id = str(payload.get("device_id", "")).strip().upper()
    pairing_code = str(payload.get("pairing_code", "")).strip().replace(" ", "").replace("-", "")
    fw_version = str(payload.get("firmware_version", "2.1")).strip()
    mac = str(payload.get("mac", "")).strip()

    if not device_id or not pairing_code:
        return {
            "status": "error",
            "code": "ERR_MISSING_FIELDS",
            "message": "device_id and pairing_code are mandatory."
        }

    now = time.time()

    async with pin_registration_lock:
        cleanup_expired_pending_registrations()
        code_info = active_pairing_codes.get(pairing_code)
        
        # Check if code exists and is within TTL
        if not code_info or now > code_info.get("expires_at", 0):
            print(f"\n[PAIRING-ERR] Registration rejected for '{device_id}': Invalid or expired pairing code.")
            return {
                "status": "error",
                "code": "ERR_INVALID_CODE",
                "message": "Pairing code is invalid or expired."
            }

        # If code has already been consumed:
        if code_info.get("used", False):
            # Check for legitimate resumption by the SAME device
            if code_info.get("device_id") == device_id:
                if device_id in pending_registrations:
                    existing_entry = pending_registrations[device_id]
                    existing_token = existing_entry.get("device_token")
                    existing_entry["expires_at"] = now + PENDING_REGISTRATION_TIMEOUT
                else:
                    # In-memory pending timed out, but pairing code is still active for this device!
                    existing_token = secrets.token_hex(32)
                    pending_registrations[device_id] = {
                        "device_id": device_id,
                        "device_token": existing_token,
                        "token_hash": hash_device_token(existing_token),
                        "pairing_code": pairing_code,
                        "fw_version": fw_version,
                        "mac": mac,
                        "created_at": now,
                        "expires_at": now + PENDING_REGISTRATION_TIMEOUT,
                        "state": PinRegistrationState.PENDING,
                    }
                print(f"\n[PAIRING-RESUME] Smart Pin '{device_id}' safely resuming pending registration.")
                return {
                    "status": "success",
                    "registration_state": PinRegistrationState.PENDING,
                    "device_id": device_id,
                    "device_token": existing_token,
                    "cs_id": "CS-CAMPUS-01",
                    "server_ip": get_primary_ip(),
                    "server_port": 8080,
                    "message": f"Resumed pending registration for {device_id}. Connect to WebSocket to complete pairing."
                }

            # Check if device is already paired with this code
            if (code_info.get("device_id") == device_id and 
                device_id in registered_devices and 
                registered_devices[device_id].get("paired", False)):
                print(f"\n[PAIRING-INFO] Smart Pin '{device_id}' is already registered and paired.")
                return {
                    "status": "error",
                    "code": "ERR_ALREADY_PAIRED",
                    "message": "Device is already registered and paired."
                }

            # Code already used by another device or expired pending
            print(f"\n[PAIRING-ERR] Registration rejected for '{device_id}': Pairing code already used by another device.")
            return {
                "status": "error",
                "code": "ERR_INVALID_CODE",
                "message": "Pairing code has already been used by another device."
            }

        # Fresh code: ensure it's not bound to another device
        if code_info.get("device_id") and code_info.get("device_id") != device_id:
            print(f"\n[PAIRING-ERR] Registration rejected for '{device_id}': Code assigned to different device.")
            return {
                "status": "error",
                "code": "ERR_INVALID_CODE",
                "message": "Pairing code is bound to another device."
            }

        # Consume single-use code immediately
        code_info["used"] = True
        code_info["device_id"] = device_id
        code_info["used_at"] = now
        save_active_pairing_codes()

        # Generate cryptographically secure 32-byte hex credential token
        device_token = secrets.token_hex(32)
        token_hash = hash_device_token(device_token)

        # Store in pending registrations (in-memory ONLY with expiration)
        # Note: Do NOT add to registered_devices or device_credentials.json yet!
        # Do NOT broadcast pin_registered to the dashboard until authenticated WebSocket connection!
        pending_registrations[device_id] = {
            "device_id": device_id,
            "device_token": device_token,  # Kept in memory only for resumption before WS promotion
            "token_hash": token_hash,
            "pairing_code": pairing_code,
            "fw_version": fw_version,
            "mac": mac,
            "created_at": now,
            "expires_at": now + PENDING_REGISTRATION_TIMEOUT,
            "state": PinRegistrationState.PENDING,
        }

    print(f"\n[PAIRING-PENDING] Smart Pin '{device_id}' issued pending registration (expires in {int(PENDING_REGISTRATION_TIMEOUT)}s). Awaiting WebSocket authentication.")

    return {
        "status": "success",
        "registration_state": PinRegistrationState.PENDING,
        "device_id": device_id,
        "device_token": device_token,
        "cs_id": "CS-CAMPUS-01",
        "server_ip": get_primary_ip(),
        "server_port": 8080,
        "message": f"Pending registration issued for {device_id}. Connect to WebSocket to complete pairing."
    }

@app.get("/api/devices/paired")
async def get_paired_devices_api():
    """Lists all cryptographically paired devices."""
    creds = load_device_credentials()
    result = []
    for dev_id, info in creds.items():
        is_active = any(d_id == dev_id for d_id in active_pins.values())
        result.append({
            "device_id": dev_id,
            "mac": info.get("mac", ""),
            "fw_version": info.get("fw_version", ""),
            "registered_at": info.get("registered_at", ""),
            "online": is_active
        })
    return {"status": "success", "count": len(result), "devices": result}

@app.get("/api/pin/status/{device_id}")
async def get_pin_status(device_id: str):
    """
    Authoritative query endpoint for mobile companion & dashboard.
    Returns whether the device is permanently registered, paired, and currently online.
    """
    clean_id = device_id.strip().upper()
    creds = load_device_credentials()
    is_registered = clean_id in creds
    dev = registered_devices.get(clean_id)
    is_active = (clean_id in pin_active_sockets) or any(d_id == clean_id for d_id in active_pins.values())
    is_paired = bool(is_registered or (dev and dev.get("paired", False)))

    state_str = "OFFLINE"
    if is_active:
        state_str = dev.get("state", "ONLINE") if dev else "ONLINE"
    elif is_paired:
        state_str = "OFFLINE"
    else:
        state_str = "UNREGISTERED"

    return {
        "status": "success",
        "device_id": clean_id,
        "registered": is_registered,
        "paired": is_paired,
        "online": is_active,
        "state": state_str,
        "battery": dev.get("battery", 100) if dev else None,
        "rssi": dev.get("rssi", -60) if dev else None,
        "last_seen": dev.get("lastSeen", "") if dev else "",
    }

# =========================================================================
# MOBILE COMPANION PAIRING & SYNCHRONIZATION APIS (QR + 8-DIGIT CODE)
# =========================================================================
@app.post("/api/mobile-pairing/create")
async def create_mobile_pairing_session(payload: Optional[dict] = None):
    """Generates an ephemeral 8-digit numeric pairing code with a ~90-second TTL and QR payload."""
    primary_ip = get_primary_ip()
    active_tunnel = get_active_tunnel_url()
    ttl = int(payload.get("ttl_seconds", 90)) if payload else 90
    session_data = await mobile_pairing_mgr.create_session(
        server_ip=primary_ip,
        server_port=8080,
        cloud_tunnel_url=active_tunnel,
        ttl_seconds=ttl
    )
    return session_data

@app.post("/api/mobile-pairing/redeem")
async def redeem_mobile_pairing_code(request: Request, payload: dict):
    """Accepts QR payload or manual 8-digit code, verifies single-use & rate limits, and enqueues approval request."""
    client_ip = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for") or (request.client.host if request.client else "127.0.0.1")
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    pairing_code = str(payload.get("pairing_code", "")).strip()
    session_id = payload.get("session_id")
    device_id = str(payload.get("device_id", f"MOBILE-{secrets.token_hex(4)}")).strip().upper()
    device_name = str(payload.get("device_name", "")).strip()
    user_name = str(payload.get("user_name", "Teacher / Student")).strip()
    role = str(payload.get("role", "Teacher")).strip()

    host_hdr = request.headers.get("host", "").lower()
    cf_hdr = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    is_remote = bool(cf_hdr or "trycloudflare.com" in host_hdr)
    conn_type = "remote" if is_remote else "local"

    success, result = await mobile_pairing_mgr.redeem_code(
        pairing_code=pairing_code,
        device_id=device_id,
        device_name=device_name,
        user_name=user_name,
        role=role,
        client_ip=client_ip,
        session_id=session_id,
        connection_type=conn_type
    )

    if success:
        # Broadcast pending approval request to all Dashboard stations
        await broadcast_to_ui({
            "event_type": "mobile_pairing_request",
            "session_id": result.get("session_id"),
            "device": {
                "device_id": device_id,
                "device_name": device_name or f"Mobile Device ({device_id})",
                "user_name": user_name,
                "role": role,
                "connection_type": conn_type,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
        })
        return result
    else:
        status_code = 429 if result.get("code") == "ERR_RATE_LIMITED" else 400
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=status_code, content=result)

@app.get("/api/mobile-pairing/status/{session_id}")
async def get_mobile_pairing_status(session_id: str):
    """Pollable endpoint for mobile app and dashboard to monitor pairing session progress."""
    res = await mobile_pairing_mgr.get_session_status(session_id)
    if res.get("status") == "success" and res.get("state") == PairingState.APPROVED:
        res["server_ip"] = get_primary_ip()
        res["server_port"] = 8080
        res["cloud_tunnel_url"] = get_active_tunnel_url()
    return res

@app.post("/api/mobile-pairing/approve")
async def approve_mobile_pairing(payload: dict):
    """Dashboard administrator approves pending mobile device, issuing permanent 32-byte credential."""
    session_id = str(payload.get("session_id", "")).strip()
    role_override = payload.get("role")
    success, res = await mobile_pairing_mgr.approve_session(session_id, role_override)
    if success:
        dev_id = res.get("device_id")
        await broadcast_to_ui({
            "event_type": "mobile_device_approved",
            "device_id": dev_id,
            "role": res.get("role"),
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        return res
    else:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=res)

@app.post("/api/mobile-pairing/revoke")
async def revoke_mobile_device(payload: dict):
    """Revokes a previously paired mobile device, immediately closing any active WebSockets."""
    device_id = str(payload.get("device_id", "")).strip().upper()
    success, res = await mobile_pairing_mgr.revoke_device(device_id)
    if success:
        # Close any active WebSocket connection for this device
        to_close = [ws for ws, info in list(active_mobile_clients.items()) if info.get("device_id") == device_id]
        for ws in to_close:
            try:
                await ws.close(code=4403, reason="Device revoked by administrator")
            except Exception:
                pass
            active_mobile_clients.pop(ws, None)

        await broadcast_to_ui({
            "event_type": "mobile_device_revoked",
            "device_id": device_id,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        return res
    else:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=res)

@app.get("/api/mobile-devices")
async def get_mobile_devices():
    """Lists all paired mobile devices and any currently pending approval requests."""
    active_map = {info["device_id"]: info for info in active_mobile_clients.values() if "device_id" in info}
    devices = mobile_pairing_mgr.list_all_devices(active_map)
    pending = mobile_pairing_mgr.list_pending_requests()
    return {
        "status": "success",
        "devices": devices,
        "pending_requests": pending,
        "count": len(devices),
        "online_count": len([d for d in devices if d.get("online")])
    }

# =========================================================================
# DEDICATED AUTHENTICATED MOBILE WEBSOCKET ENDPOINT
# =========================================================================
@app.websocket("/mobile")
async def mobile_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Query param token & device_id or wait up to 3.0s for auth frame
    token = websocket.query_params.get("token")
    device_id = websocket.query_params.get("device_id")

    is_authenticated = False
    device_info = None

    if token and device_id:
        is_authenticated, device_info = mobile_pairing_mgr.verify_mobile_token(device_id.strip().upper(), token.strip())

    if not is_authenticated:
        try:
            auth_event = await asyncio.wait_for(websocket.receive(), timeout=3.0)
            if auth_event.get("type") == "websocket.disconnect":
                return
            raw_auth = auth_event.get("text")
            if raw_auth:
                try:
                    auth_data = json.loads(raw_auth)
                    if auth_data.get("type") == "auth":
                        device_id = auth_data.get("device_id", "").strip().upper()
                        token = auth_data.get("token", "").strip()
                        is_authenticated, device_info = mobile_pairing_mgr.verify_mobile_token(device_id, token)
                        if is_authenticated:
                            await websocket.send_text(json.dumps({"type": "auth_ok", "status": "authenticated"}))
                except Exception:
                    pass
        except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
            pass

    if not is_authenticated or not device_info:
        client_ip = websocket.client.host if websocket.client else "unknown"
        print(f"\n[WS-MOBILE-AUTH] Unauthorized mobile connection rejected for '{device_id}' from {client_ip}.")
        try:
            await websocket.close(code=4401, reason="Unauthorized mobile device")
        except Exception:
            pass
        return

    # Determine connection type (remote via Cloudflare tunnel vs local LAN)
    host_hdr = websocket.headers.get("host", "").lower()
    cf_hdr = websocket.headers.get("cf-connecting-ip") or websocket.headers.get("x-forwarded-for")
    is_remote = bool(cf_hdr or "trycloudflare.com" in host_hdr)
    conn_type = "remote" if is_remote else "local"

    mobile_pairing_mgr.update_device_presence(device_id, conn_type)
    active_mobile_clients[websocket] = {
        "device_id": device_id,
        "device_name": device_info.get("device_name", device_id),
        "user_name": device_info.get("user_name", "Teacher / Student"),
        "role": device_info.get("role", "Teacher"),
        "connection_type": conn_type,
        "connected_at": time.time()
    }

    print(f"\n[WS-MOBILE] Mobile Companion '{device_id}' ({device_info.get('user_name')} [{device_info.get('role')}]) connected via {conn_type.upper()}.")

    # Send initial state synchronization payload
    initial_sync = {
        "event_type": "mobile_sync_init",
        "cs_id": "CS-CAMPUS-01",
        "name": "SecureLink Campus Central System",
        "role": device_info.get("role", "Teacher"),
        "cloud_tunnel_url": get_active_tunnel_url(),
        "tunnel_state": tunnel_mgr.state,
        "server_ip": get_primary_ip(),
        "server_port": 8080,
        "harmful_words_only": harmful_words_only,
        "devices": list(registered_devices.values()),
        "checkpoints": load_checkpoints(),
        "recent_incidents": list(recent_incidents),
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    await websocket.send_text(json.dumps(initial_sync))

    # Notify dashboard of mobile connection
    await broadcast_to_ui({
        "event_type": "mobile_client_connected",
        "device_id": device_id,
        "user_name": device_info.get("user_name"),
        "role": device_info.get("role"),
        "connection_type": conn_type
    })

    try:
        while True:
            try:
                event_msg = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                break

            if event_msg.get("type") == "websocket.disconnect":
                break

            data = event_msg.get("text")
            if not data:
                continue

            if data == "ping":
                await websocket.send_text(json.dumps({"event_type": "pong"}))
                continue

            try:
                msg = json.loads(data)
                mtype = msg.get("event_type") or msg.get("type")

                # 1. BLE Relay: Presence and telemetry from nearby Smart Pins
                if mtype == "ble_relay_presence":
                    pin_id = str(msg.get("pin_id", "")).strip().upper()
                    # CRITICAL: Do NOT create or register a physical ESP32 from a mobile BLE relay!
                    # Only update proximity and telemetry if the pin is already legitimately registered.
                    if pin_id and pin_id in registered_devices:
                        dev_record = registered_devices[pin_id]
                        dev_record["ble_proximity"] = True
                        dev_record["relayed_by"] = device_id
                        dev_record["last_ble_seen"] = datetime.now().strftime("%H:%M:%S")
                        if "battery" in msg:
                            dev_record["battery"] = int(msg["battery"])
                        if "battery_mv" in msg:
                            dev_record["batteryMv"] = int(msg["battery_mv"])
                        if "rssi" in msg:
                            dev_record["rssi"] = int(msg["rssi"])

                        await broadcast_to_ui({
                            "event_type": "pin_ble_relayed",
                            "pin_id": pin_id,
                            "relayed_by": device_id,
                            "device": dev_record,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })

                # 2. BLE Relay: BLE Disconnection notification
                elif mtype == "ble_relay_disconnect":
                    pin_id = str(msg.get("pin_id", "")).strip().upper()
                    if pin_id in registered_devices:
                        registered_devices[pin_id]["ble_proximity"] = False
                        registered_devices[pin_id]["last_ble_seen"] = f"BLE Disconnected at {datetime.now().strftime('%H:%M:%S')}"
                        # Note: Direct Wi-Fi status online remains completely unaffected!
                        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[pin_id]})

                # 3. BLE Relay: Text command (e.g. STREAM_END, PING, etc.)
                elif mtype == "ble_relay_command":
                    pin_id = str(msg.get("pin_id", "")).strip().upper()
                    cmd = str(msg.get("command", "")).strip()
                    if pin_id and cmd:
                        if cmd in ("STREAM_END", "STREAM_STOP"):
                            acc = relayed_audio_accumulators.get(pin_id)
                            if acc and len(acc) >= 4800:
                                final_pcm = bytes(acc)
                                relayed_audio_accumulators[pin_id] = bytearray()
                                asyncio.create_task(handle_completed_audio(pin_id, final_pcm, websocket, source="MOBILE_BLE_RELAY", relayed_by=device_id))
                            elif acc:
                                relayed_audio_accumulators[pin_id] = bytearray()
                        elif cmd.startswith("PING:"):
                            parts = cmd.split(":")
                            if len(parts) >= 2 and pin_id in registered_devices:
                                try:
                                    registered_devices[pin_id]["rssi"] = int(parts[1])
                                except Exception:
                                    pass
                            if len(parts) >= 3 and pin_id in registered_devices:
                                try:
                                    registered_devices[pin_id]["battery"] = int(parts[2])
                                except Exception:
                                    pass

                # 4. BLE Relay: Raw PCM audio chunks
                elif mtype == "ble_relay_audio":
                    pin_id = str(msg.get("pin_id", "")).strip().upper()
                    b64_data = msg.get("pcm_base64", "")
                    if pin_id and b64_data:
                        raw_pcm = base64.b64decode(b64_data)
                        acc = relayed_audio_accumulators.setdefault(pin_id, bytearray())
                        acc.extend(raw_pcm)
                        if registered_devices.get(pin_id, {}).get("state") != "STREAMING AUDIO (BLE RELAY)":
                            if pin_id in registered_devices:
                                registered_devices[pin_id]["state"] = "STREAMING AUDIO (BLE RELAY)"
                                registered_devices[pin_id]["ble_proximity"] = True
                                registered_devices[pin_id]["relayed_by"] = device_id
                                await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[pin_id]})
                        if len(acc) >= 192000:
                            chunk = bytes(acc[:192000])
                            relayed_audio_accumulators[pin_id] = bytearray(acc[192000 - 32000:])
                            asyncio.create_task(handle_completed_audio(pin_id, chunk, websocket, source="MOBILE_BLE_RELAY", relayed_by=device_id))

                # 5. BLE Relay: Camera snapshot
                elif mtype == "ble_relay_snapshot":
                    pin_id = str(msg.get("pin_id", "")).strip().upper()
                    b64_jpeg = msg.get("jpeg_base64", "")
                    if pin_id and b64_jpeg:
                        jpeg_bytes = base64.b64decode(b64_jpeg)
                        snap_id = f"snap_relayed_{pin_id}_{int(time.time())}.jpg"
                        snap_path = os.path.join(SNAPSHOTS_RECORDINGS_DIR, snap_id)
                        with open(snap_path, "wb") as sf:
                            sf.write(jpeg_bytes)
                        latest_incident_id = registered_devices.get(pin_id, {}).get("latest_incident_id", "")
                        primary_ip = get_primary_ip()
                        active_tunnel = get_active_tunnel_url()
                        base_url = active_tunnel if active_tunnel else f"http://{primary_ip}:8080"
                        snapshot_url = f"{base_url}/recordings/snapshots/{snap_id}"
                        local_url = f"http://127.0.0.1:8080/recordings/snapshots/{snap_id}"
                        lan_url = f"http://{primary_ip}:8080/recordings/snapshots/{snap_id}"
                        await broadcast_to_ui({
                            "event_type": "snapshot_ready",
                            "device_id": pin_id,
                            "incident_id": latest_incident_id,
                            "snapshot_file": snap_id,
                            "snapshot_url": snapshot_url,
                            "local_url": local_url,
                            "lan_url": lan_url,
                            "source": "MOBILE_BLE_RELAY",
                            "relayed_by": device_id,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })

                # 6. Dashboard commands
                elif mtype in ("TRIGGER:DANGER", "CMD:CAPTURE_SNAPSHOT"):
                    user_role = device_info.get("role", "Teacher")
                    if user_role.lower() != "student":
                        print(f"[WS-MOBILE] Hardware command '{mtype}' authorized from {device_id} ({user_role}). Relaying to pins...")
                        for pin_ws in list(active_pins.keys()):
                            try:
                                await pin_ws.send_text(mtype)
                            except Exception:
                                pass
                    else:
                        print(f"[WS-MOBILE] Blocked unauthorized command '{mtype}' from student device {device_id}.")
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS-MOBILE] Connection error: {e}")
    finally:
        active_mobile_clients.pop(websocket, None)
        mobile_pairing_mgr.update_device_presence(device_id, conn_type)
        await broadcast_to_ui({
            "event_type": "mobile_client_disconnected",
            "device_id": device_id
        })
        print(f"[WS-MOBILE] Mobile device '{device_id}' disconnected.")


async def pin_liveness_watchdog():
    """Runs every 3 seconds. Forces any device without an active socket to OFFLINE."""
    while True:
        await asyncio.sleep(3.0)
        try:
            for dev_id, dev in list(registered_devices.items()):
                is_active = (dev_id in pin_active_sockets) or any(d_id == dev_id for d_id in active_pins.values())
                if not is_active and dev.get("online", False):
                    now_str = datetime.now().strftime("%H:%M:%S")
                    dev["online"] = False
                    dev["state"] = "OFFLINE"
                    dev["lastSeen"] = f"Disconnected at {now_str}"
                    await broadcast_to_ui({"event_type": "device_update", "device": dev})
                    print(f"[WATCHDOG] Pin {dev_id} has no active socket -> broadcasted OFFLINE")
        except Exception as e:
            print(f"[WATCHDOG] Error: {e}")

RECORDINGS_RETENTION_DAYS = int(os.getenv("RECORDINGS_RETENTION_DAYS", "30"))

async def periodic_recordings_cleanup():
    """Periodically purges audio recordings and snapshots older than RECORDINGS_RETENTION_DAYS."""
    while True:
        try:
            now = time.time()
            cutoff_sec = now - (RECORDINGS_RETENTION_DAYS * 86400)
            deleted_count = 0
            for folder in [AUDIO_RECORDINGS_DIR, SNAPSHOTS_RECORDINGS_DIR]:
                if os.path.exists(folder):
                    for fname in os.listdir(folder):
                        fpath = os.path.join(folder, fname)
                        if os.path.isfile(fpath):
                            try:
                                if os.path.getmtime(fpath) < cutoff_sec:
                                    os.remove(fpath)
                                    deleted_count += 1
                            except Exception:
                                pass
            if deleted_count > 0:
                print(f"[CLEANUP] Purged {deleted_count} recording files older than {RECORDINGS_RETENTION_DAYS} days.")
        except Exception as e:
            print(f"[CLEANUP] Error during recordings cleanup: {e}")
        # Run cleanup every 12 hours
        await asyncio.sleep(43200)

@app.on_event("startup")
async def startup_event():
    # Initialize previously paired devices from persistent credentials storage
    init_registered_devices_from_credentials()

    loop = asyncio.get_running_loop()
    try:
        await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(),
            local_addr=('0.0.0.0', 8888)
        )
        print("[UDP] Auto-discovery service listening on port 8888...")
    except Exception as udp_err:
        print(f"[WARN] UDP port 8888 busy or unavailable ({udp_err}). Continuing without UDP discovery...")
    
    # Launch background watchdog that monitors socket health and forces ghost pins OFFLINE
    asyncio.create_task(pin_liveness_watchdog())
    
    # Launch background recording retention cleaner (30-day default)
    asyncio.create_task(periodic_recordings_cleanup())

    # Launch Cloudflare Quick Tunnel automatically on startup for mobile synchronization
    print("[TUNNEL] Auto-starting Cloudflare Quick Tunnel for cellular/mobile sync...")
    asyncio.create_task(tunnel_mgr.start())

    print("[SYS] WebSocket Server active on port 8080 (UI: /ui | Pins: / | Mobile: /mobile)")
    print("[SYS] Ready for connections!\n")

@app.on_event("shutdown")
async def shutdown_event():
    print("\n[SYS] Server shutting down. Cleaning up Cloudflare Tunnel...")
    await tunnel_mgr.stop()

# =========================================================================
# 7. AUDIO PROCESSING PIPELINE (DENOISING + WHISPER STT)
# =========================================================================
def process_audio_buffer(pcm_bytes: bytes) -> tuple[TranscriptionResult, bytes]:
    """Applies 85Hz HPF, MS-NSNet2 noise suppression, gentle quiet-speech post-gain, and Faster-Whisper ASR with segment validation."""
    if len(pcm_bytes) < 3200:  # Less than 100ms
        return TranscriptionResult(
            status=TranscriptionStatus.NO_SPEECH,
            reason="Buffer shorter than 100ms"
        ), pcm_bytes
    
    # 1. Convert raw 16kHz 16-bit Mono PCM bytes to float32 NumPy array [-1.0, 1.0]
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0

    raw_peak = float(np.max(np.abs(audio_float)))
    raw_rms = float(np.sqrt(np.mean(audio_float**2)))

    # 2. Strip infrasonic fan blade chop & motor rumble (< 85Hz) while preserving vocal formants (90Hz-3400Hz)
    try:
        sos_hp = signal.butter(2, 85 / (16000 / 2), btype='high', output='sos')
        audio_float = signal.sosfilt(sos_hp, audio_float).astype(np.float32)
    except Exception:
        pass

    hpf_rms = float(np.sqrt(np.mean(audio_float**2)))
    hpf_peak = float(np.max(np.abs(audio_float)))

    # Drop pure electrical silence or dead mic line (peak < 0.003, raw ADC peak < 100)
    if hpf_peak < 0.003:
        return TranscriptionResult(
            status=TranscriptionStatus.NO_SPEECH,
            reason=f"Electrical silence below threshold (Peak={hpf_peak:.4f} < 0.003)",
            audio_quality={"raw_peak": round(raw_peak, 4), "raw_rms": round(raw_rms, 4), "hpf_peak": round(hpf_peak, 4), "hpf_rms": round(hpf_rms, 4)}
        ), pcm_bytes

    # 3. Server-side Denoising FIRST (Microsoft NSNet2 Neural Speech Isolation)
    # Neural suppression runs on natural SNR before applying any digital gain
    if has_nsnet2 and nsnet2_denoiser is not None:
        try:
            audio_float = nsnet2_denoiser.enhance(audio_float, fs=16000, strength=DENOISE_STRENGTH)
        except Exception as e:
            print(f"[WARN] NSNet2 inference error: {e}")
            if has_noisereduce:
                try:
                    audio_float = nr.reduce_noise(
                        y=audio_float,
                        sr=16000,
                        prop_decrease=0.65,
                        stationary=True,
                        n_std_thresh_stationary=1.5
                    )
                except Exception:
                    pass
    elif has_noisereduce:
        try:
            audio_float = nr.reduce_noise(
                y=audio_float,
                sr=16000,
                prop_decrease=0.65,
                stationary=True,
                n_std_thresh_stationary=1.5
            )
        except Exception as e:
            print(f"[WARN] NoiseReduce error: {e}")

    audio_float = np.asarray(audio_float, dtype=np.float32)
    denoised_peak = float(np.max(np.abs(audio_float)))
    denoised_rms = float(np.sqrt(np.mean(audio_float**2)))

    # 4. Gentle Post-Denoising Normalization (Preserves quiet genuine speech, avoids boosting noise)
    # Only scale when genuine acoustic energy is present (> 0.01) but soft (< 0.35)
    # Never boost when denoised peak is negligible (< 0.01) to avoid amplifying residual fan floor
    if 0.01 < denoised_peak < 0.35:
        gain_scale = min(0.45 / (denoised_peak + 1e-6), 3.0)
        audio_float = audio_float * gain_scale

    audio_float = np.clip(audio_float, -0.99, 0.99)

    # 5. Convert clean audio float back to 16-bit PCM bytes for playback in recordings
    clean_int16 = np.clip(audio_float * 32767.0, -32768, 32767).astype(np.int16)
    clean_pcm_bytes = clean_int16.tobytes()

    audio_quality = {
        "raw_peak": round(raw_peak, 4),
        "raw_rms": round(raw_rms, 4),
        "hpf_peak": round(hpf_peak, 4),
        "denoised_peak": round(denoised_peak, 4)
    }

    # 6. Faster-Whisper Speech Recognition
    if not (has_whisper and whisper_model is not None):
        return TranscriptionResult(
            status=TranscriptionStatus.NO_SPEECH,
            reason="Whisper model unavailable",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    transcribe_kwargs = {
        "language": "tl",
        "initial_prompt": INITIAL_TAGALOG_PROMPT if INITIAL_TAGALOG_PROMPT else None,
        "hotwords": TAGALOG_HOTWORDS if TAGALOG_HOTWORDS else None,
        "beam_size": 5,
        "temperature": [0.0],
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.60,
        "log_prob_threshold": -1.0,
        "compression_ratio_threshold": 2.4,
        "word_timestamps": False,
        "vad_parameters": dict(threshold=0.40, min_speech_duration_ms=250, speech_pad_ms=300),
    }

    try:
        segments_gen, info = whisper_model.transcribe(
            audio_float,
            vad_filter=True,
            **transcribe_kwargs
        )
        segments = list(segments_gen)
    except Exception as e:
        print(f"[ERR] Whisper transcription error: {e}")
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            reason=f"Whisper transcription error: {e}",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    if not segments:
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED if raw_peak >= 0.05 else TranscriptionStatus.NO_SPEECH,
            reason="No speech segments detected by VAD",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    # 7. Segment-Level Validation
    valid_segments = []
    seg_reject_reasons = []
    for s in segments:
        txt = s.text.strip()
        if not txt:
            continue
        nsp = getattr(s, 'no_speech_prob', 0.0)
        alp = getattr(s, 'avg_logprob', 0.0)
        cr = getattr(s, 'compression_ratio', 1.0)

        if nsp >= 0.60:
            seg_reject_reasons.append(f"no_speech_prob={nsp:.3f} >= 0.60")
            continue
        if cr > 2.4:
            seg_reject_reasons.append(f"compression_ratio={cr:.2f} > 2.4")
            continue
        if alp < -1.40:
            seg_reject_reasons.append(f"avg_logprob={alp:.3f} < -1.40")
            continue

        valid_segments.append(s)

    if not valid_segments:
        reason_msg = "; ".join(seg_reject_reasons) if seg_reject_reasons else "All segments filtered by quality checks"
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            reason=reason_msg,
            audio_quality=audio_quality
        ), clean_pcm_bytes

    # 8. Fallback Rule: only force 'tl' if duration >= 2.5s and detected language is non-Philippine
    dur_sec = len(audio_float) / 16000.0
    detected_lang = getattr(info, 'language', 'tl')
    if detected_lang not in ('tl', 'en'):
        if dur_sec >= 2.5:
            print(f"[ASR] Auto-detected '{detected_lang}' on {dur_sec:.1f}s clip. Re-running with forced Tagalog ('tl')...")
            fallback_kwargs = dict(transcribe_kwargs)
            fallback_kwargs["language"] = "tl"
            try:
                fb_segments_gen, _ = whisper_model.transcribe(
                    audio_float,
                    vad_filter=True,
                    **fallback_kwargs
                )
                fb_segs = list(fb_segments_gen)
                fb_valid = [s for s in fb_segs if s.text.strip() and getattr(s, 'no_speech_prob', 0.0) < 0.60 and getattr(s, 'compression_ratio', 1.0) <= 2.4 and getattr(s, 'avg_logprob', 0.0) >= -1.40]
                if fb_valid:
                    valid_segments = fb_valid
            except Exception:
                pass
        else:
            return TranscriptionResult(
                status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
                reason=f"Discarded short noisy clip ({dur_sec:.1f}s) misdetected as '{detected_lang}'",
                audio_quality=audio_quality
            ), clean_pcm_bytes

    transcript = " ".join(s.text.strip() for s in valid_segments).strip()

    # 9. Word-Level Validation (Repetition loops, diversity, prompt-echo)
    words = [re.sub(r'[^a-zA-Z0-9ñÑ]', '', w.lower()) for w in re.split(r'[\s\-]+', transcript)]
    words = [w for w in words if w]

    if not words:
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            reason="Empty transcript after punctuation normalization",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    # Filter standard mic-check & silence hallucinations
    clean_t = transcript.lower().strip().rstrip(".!?,")
    if clean_t in [
        "hello my check", "hello mic check", "mic check", "my check"
    ]:
        return TranscriptionResult(
            status=TranscriptionStatus.SPEECH_DETECTED,
            transcript=transcript,
            reason="Filtered benign mic-check phrase",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    HALLUCINATION_ARTIFACTS = {
        "thank you", "you", "thanks", "salamat", "maraming salamat",
        "okay", "outro", "subtitles", "subtitle", "bye", "goodbye"
    }
    if clean_t in HALLUCINATION_ARTIFACTS:
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            transcript="",
            reason=f"Filtered hallucination artifact ('{clean_t}')",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    # Check 1: Consecutive word repetition loop
    streak = 1
    max_streak = 1
    for idx in range(1, len(words)):
        if len(words[idx]) >= 3 and words[idx] == words[idx - 1]:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 1
    if max_streak >= 4 or (max_streak >= 3 and len(words) <= 5):
        return TranscriptionResult(
            status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
            transcript=transcript,
            reason=f"Consecutive word repetition loop (streak={max_streak})",
            audio_quality=audio_quality
        ), clean_pcm_bytes

    # Check 2: Lexical diversity (unique words / total words < 0.35 on clips with >= 6 words)
    if len(words) >= 6:
        lexical_diversity = len(set(words)) / len(words)
        if lexical_diversity < 0.35:
            return TranscriptionResult(
                status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
                transcript=transcript,
                reason=f"Low lexical diversity loop (diversity={lexical_diversity:.2f} < 0.35)",
                audio_quality=audio_quality
            ), clean_pcm_bytes

    # Check 3: Token concentration (> 50% of words identical in clip with >= 4 words)
    if len(words) >= 4:
        from collections import Counter
        word_counts = Counter(words)
        most_common_word, count = word_counts.most_common(1)[0]
        if len(most_common_word) >= 3 and (count / len(words)) > 0.50:
            return TranscriptionResult(
                status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
                transcript=transcript,
                reason=f"High token concentration ('{most_common_word}' is {count}/{len(words)} tokens)",
                audio_quality=audio_quality
            ), clean_pcm_bytes

    # Check 4: Prompt-echo filter (if >= 50% of words match prompt echo vocabulary)
    if PROMPT_ECHO_WORDS and len(words) >= 2:
        echo_count = sum(1 for w in words if w in PROMPT_ECHO_WORDS)
        if (echo_count / len(words)) >= 0.50:
            return TranscriptionResult(
                status=TranscriptionStatus.TRANSCRIPTION_REJECTED,
                transcript=transcript,
                reason=f"Prompt-echo filter triggered ({echo_count}/{len(words)} prompt words)",
                audio_quality=audio_quality
            ), clean_pcm_bytes

    # Metrics calculation
    mean_logprob = float(np.mean([getattr(s, 'avg_logprob', 0.0) for s in valid_segments]))
    max_no_speech = float(np.max([getattr(s, 'no_speech_prob', 0.0) for s in valid_segments]))
    mean_cr = float(np.mean([getattr(s, 'compression_ratio', 1.0) for s in valid_segments]))

    metrics = {
        "avg_logprob": round(mean_logprob, 3),
        "no_speech_prob": round(max_no_speech, 3),
        "compression_ratio": round(mean_cr, 2),
        "num_segments": len(valid_segments),
        "detected_language": detected_lang
    }

    # 10. Borderline acoustic confidence check
    if mean_logprob < -1.10:
        return TranscriptionResult(
            status=TranscriptionStatus.UNCERTAIN_TRANSCRIPTION,
            transcript=transcript,
            reason=f"Borderline acoustic confidence (avg_logprob={mean_logprob:.3f} < -1.10)",
            metrics=metrics,
            audio_quality=audio_quality
        ), clean_pcm_bytes

    return TranscriptionResult(
        status=TranscriptionStatus.TRANSCRIBED,
        transcript=transcript,
        reason="Speech transcribed with high confidence",
        metrics=metrics,
        audio_quality=audio_quality
    ), clean_pcm_bytes


def save_wav(pcm_bytes: bytes, filepath: str):
    """Saves 16kHz 16-bit PCM bytes to standard WAV format."""
    with wave.open(filepath, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_bytes)

# Global mutex for AI inference: guarantees single-pipeline execution for NSNet2, Whisper, and BERT
# Prevents concurrent thread race conditions, CUDA memory corruption, and out-of-memory errors
ai_inference_lock = asyncio.Lock()

async def handle_completed_audio(
    device_id: str,
    pcm_bytes: bytes,
    websocket: WebSocket,
    source: str = "ESP32_DIRECT",
    relayed_by: Optional[str] = None
):
    """Processes accumulated speech audio buffer, runs Faster-Whisper + BERT, and updates UI."""
    if len(pcm_bytes) < 4800: # Less than 150ms
        if device_id in registered_devices:
            now_str = datetime.now().strftime("%H:%M:%S")
            if source == "ESP32_DIRECT":
                is_still_connected = any(d_id == device_id for d_id in active_pins.values())
                registered_devices[device_id]["online"] = is_still_connected
                registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
                registered_devices[device_id]["lastSeen"] = f"Active at {now_str}" if is_still_connected else f"Disconnected at {now_str}"
            else:
                if registered_devices[device_id].get("state") in ("ANALYZING SPEECH", "STREAMING AUDIO (BLE RELAY)"):
                    registered_devices[device_id]["state"] = "STANDBY"
                registered_devices[device_id]["last_ble_seen"] = f"Relayed speech at {now_str}"
            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
        return

    dur_sec = len(pcm_bytes) / 32000.0
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_peak = float(np.max(np.abs(audio_int16))) / 32768.0

    if device_id in registered_devices:
        registered_devices[device_id]["state"] = "ANALYZING SPEECH"
        if source == "ESP32_DIRECT":
            registered_devices[device_id]["online"] = True
            registered_devices[device_id]["lastSeen"] = "Whisper inferencing..."
        else:
            registered_devices[device_id]["last_ble_seen"] = "Relayed Whisper inferencing..."
        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

    async with ai_inference_lock:
        t_infer_start = time.time()
        result, clean_pcm = await asyncio.to_thread(process_audio_buffer, pcm_bytes)
        infer_dur = time.time() - t_infer_start

        if result.status == TranscriptionStatus.TRANSCRIBED and result.transcript:
            transcript = result.transcript
            print(f"[FINAL TRANSCRIPT] ({device_id} via {source} in {infer_dur:.2f}s, dur={dur_sec:.2f}s, peak={audio_peak:.2f}) -> \"{transcript}\"")
            score, category = context_engine.evaluate(transcript, device_id=device_id, transcription_result=result)
            is_danger = score >= 8.0

            # --- HARMFUL WORDS ONLY FILTER ---
            # When active, ignore benign/conversational speech and do not save WAV or log incident
            is_harmful = (category != "Conversational") or (score >= 2.0)
            if harmful_words_only and not is_harmful:
                print(f"[FILTER] Ignored conversational speech under 'Harmful Words Only' mode: \"{transcript}\" (cat={category}, score={score})")
                if device_id in registered_devices:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    if source == "ESP32_DIRECT":
                        is_still_connected = any(d_id == device_id for d_id in active_pins.values())
                        registered_devices[device_id]["online"] = is_still_connected
                        registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
                        registered_devices[device_id]["lastSeen"] = f"Filtered benign speech at {now_str}" if is_still_connected else f"Disconnected at {now_str}"
                    else:
                        if registered_devices[device_id].get("state") == "ANALYZING SPEECH":
                            registered_devices[device_id]["state"] = "STANDBY"
                        registered_devices[device_id]["last_ble_seen"] = f"Filtered benign speech at {now_str}"
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
                return

            if is_danger:
                print(f"[THREAT] DANGER grade detected! Dispatching TRIGGER:DANGER to {device_id} (source: {source})...")
                if source == "MOBILE_BLE_RELAY":
                    try:
                        await websocket.send_text(json.dumps({
                            "event_type": "trigger_danger",
                            "type": "trigger_danger",
                            "pin_id": device_id
                        }))
                    except Exception as e:
                        print(f"[THREAT] Error notifying mobile relay: {e}")
                else:
                    try:
                        await websocket.send_text("TRIGGER:DANGER")
                    except Exception as e:
                        print(f"[THREAT] Error sending direct TRIGGER:DANGER: {e}")

                for pin_ws, p_id in list(active_pins.items()):
                    if p_id == device_id and pin_ws != websocket:
                        try:
                            await pin_ws.send_text("TRIGGER:DANGER")
                        except Exception:
                            pass

            incident_id = f"EVT-{int(time.time() * 1000) % 1000000}"
            if device_id in registered_devices:
                registered_devices[device_id]["latest_incident_id"] = incident_id
            else:
                registered_devices[device_id] = {
                    "latest_incident_id": incident_id,
                    "state": "ANALYZING SPEECH",
                    "online": (source == "ESP32_DIRECT")
                }

            wav_filename = f"{incident_id}.wav"
            wav_path = os.path.join(AUDIO_RECORDINGS_DIR, wav_filename)
            # Save the clean, denoised audio to WAV so playback is crystal-clear and fan-free
            await asyncio.to_thread(save_wav, clean_pcm, wav_path)

            primary_ip = get_primary_ip()
            active_tunnel = get_active_tunnel_url()
            base_audio = active_tunnel if active_tunnel else f"http://{primary_ip}:8080"

            incident_payload = {
                "event_type": "incident",
                "id": incident_id,
                "device_id": device_id,
                "score": float(score),
                "category": category,
                "transcript": transcript,
                "audio": True,
                "audio_url": f"{base_audio}/recordings/audio/{wav_filename}",
                "local_audio_url": f"http://127.0.0.1:8080/recordings/audio/{wav_filename}",
                "lan_audio_url": f"http://{primary_ip}:8080/recordings/audio/{wav_filename}",
                "audio_file": wav_filename,
                "video": is_danger,
                "duration": f"00:{max(1, int(dur_sec)):02d}",
                "source": source,
                "relayed_by": relayed_by,
            }
            recent_incidents.append(incident_payload)
            await broadcast_to_ui(incident_payload)
        else:
            transcript = ""
            print(f"[ASR] ({device_id} via {source} in {infer_dur:.2f}s) Audio ({dur_sec:.2f}s, peak={audio_peak:.2f}) -> Status: {result.status.value}, Reason: {result.reason}")

    if device_id in registered_devices:
        now_str = datetime.now().strftime("%H:%M:%S")
        if source == "ESP32_DIRECT":
            is_still_connected = any(d_id == device_id for d_id in active_pins.values())
            registered_devices[device_id]["online"] = is_still_connected
            if registered_devices[device_id].get("state") == "ANALYZING SPEECH":
                registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
            if is_still_connected:
                registered_devices[device_id]["lastSeen"] = f'Heard: "{transcript[:25]}..."' if transcript else f"Active at {now_str}"
            else:
                registered_devices[device_id]["lastSeen"] = f"Disconnected at {now_str}"
        else:
            if registered_devices[device_id].get("state") == "ANALYZING SPEECH":
                registered_devices[device_id]["state"] = "STANDBY"
            registered_devices[device_id]["last_ble_seen"] = f"Relayed speech finished at {now_str}"

        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

# =========================================================================
# 8. PHYSICAL PIN WEBSOCKET ENDPOINT (AUDIO STREAM & DANGER TRIGGER)
# =========================================================================
@app.websocket("/")
async def pin_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Consistent device ID: prioritize explicit query param (?device_id=PIN-001) or header (for Cloudflare Tunnel)
    explicit_dev_id = websocket.query_params.get("device_id") or websocket.headers.get("x-device-id")
    if explicit_dev_id:
        device_id = explicit_dev_id.strip().upper()
    else:
        cf_ip = websocket.headers.get("cf-connecting-ip") or websocket.headers.get("x-forwarded-for")
        if cf_ip:
            ip_clean = cf_ip.split(",")[0].strip()
            pin_suffix = ip_clean.split(".")[-1].zfill(3) if "." in ip_clean else "001"
            device_id = f"PIN-{pin_suffix}"
        else:
            client_host = websocket.client.host if (websocket.client and websocket.client.host) else "001"
            pin_suffix = client_host.split(".")[-1].zfill(3) if "." in client_host else "001"
            device_id = f"PIN-{pin_suffix}"
    
    # Authenticate device using cryptographically registered token
    device_token = websocket.query_params.get("token") or websocket.headers.get("x-device-token") or websocket.headers.get("X-Device-Token")
    now = time.time()
    is_authenticated = False
    is_pending_promotion = False
    pending_info = None

    async with pin_registration_lock:
        cleanup_expired_pending_registrations()
        if device_id in pending_registrations:
            pending_entry = pending_registrations[device_id]
            expected_hash = pending_entry.get("token_hash", "")
            if device_token and secrets.compare_digest(expected_hash, hash_device_token(device_token)):
                is_authenticated = True
                is_pending_promotion = True
                pending_info = pending_entry
        elif verify_device_token(device_id, device_token or ""):
            is_authenticated = True

    if not is_authenticated:
        # Prompt device with an auth challenge so it knows to transmit its token frame if query/headers were stripped
        try:
            await websocket.send_text(json.dumps({
                "type": "auth_challenge",
                "device_id": device_id,
                "message": "Authentication required. Please send auth frame with token."
            }))
        except Exception:
            pass

        # Allow up to 10.0 seconds and process incoming frames (ignoring early PINGs)
        t_auth_deadline = time.time() + 10.0
        while time.time() < t_auth_deadline and not is_authenticated:
            try:
                remaining = max(0.5, t_auth_deadline - time.time())
                auth_msg = await asyncio.wait_for(websocket.receive(), timeout=remaining)
                if auth_msg.get("type") == "websocket.disconnect":
                    return
                auth_raw = auth_msg.get("text")
                if not auth_raw:
                    continue
                # If device transmitted a heartbeat PING before auth frame, tolerate and continue waiting
                if auth_raw.startswith("PING"):
                    continue
                try:
                    auth_json = json.loads(auth_raw)
                    msg_type = auth_json.get("type", "")
                    if msg_type == "auth":
                        auth_tok = auth_json.get("token", "")
                        auth_dev = auth_json.get("device_id", "").strip().upper()
                        target_dev = auth_dev if auth_dev else device_id
                        async with pin_registration_lock:
                            cleanup_expired_pending_registrations()
                            if target_dev in pending_registrations:
                                expected_hash = pending_registrations[target_dev].get("token_hash", "")
                                if secrets.compare_digest(expected_hash, hash_device_token(auth_tok)):
                                    is_authenticated = True
                                    is_pending_promotion = True
                                    device_id = target_dev
                                    pending_info = pending_registrations[target_dev]
                                    break
                            elif verify_device_token(target_dev, auth_tok):
                                is_authenticated = True
                                device_id = target_dev
                                break
                    elif msg_type == "pair" or "pairing_code" in auth_json:
                        pcode = str(auth_json.get("pairing_code", "")).strip().replace(" ", "").replace("-", "")
                        now = time.time()
                        code_info = active_pairing_codes.get(pcode)
                        if code_info and not code_info.get("used", False) and now <= code_info.get("expires_at", 0):
                            code_info["used"] = True
                            code_info["device_id"] = device_id
                            save_active_pairing_codes()
                            new_token = secrets.token_hex(32)
                            creds = load_device_credentials()
                            creds[device_id] = {
                                "token_hash": hash_device_token(new_token),
                                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "fw_version": auth_json.get("firmware_version", "2.1"),
                                "mac": auth_json.get("mac", ""),
                                "pairing_code_used": pcode,
                            }
                            save_device_credentials(creds)
                            dev_record = registered_devices.get(device_id, {})
                            dev_record.update({
                                "id": device_id,
                                "online": True,
                                "connection_source": "ESP32_DIRECT",
                                "battery": dev_record.get("battery", 100),
                                "state": "CONNECTED",
                                "network": "Campus Wi-Fi",
                                "lastSeen": "Just paired",
                                "paired": True,
                            })
                            registered_devices[device_id] = dev_record
                            await broadcast_to_ui({
                                "event_type": "pin_registered",
                                "device_id": device_id,
                                "device": dev_record,
                                "timestamp": datetime.now().strftime("%H:%M:%S")
                            })
                            is_authenticated = True
                            await websocket.send_text(json.dumps({
                                "type": "pairing_success",
                                "status": "authenticated",
                                "device_id": device_id,
                                "device_token": new_token
                            }))
                            print(f"\n[WS-AUTH] Smart Pin '{device_id}' registered and paired live via WebSocket pairing handshake!")
                            break
                except Exception:
                    pass
            except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
                break

    if not is_authenticated:
        client_ip = websocket.client.host if websocket.client else "unknown"
        print(f"\n[WS-AUTH] Unauthorized connection rejected for '{device_id}' from {client_ip} (missing, unregistered, or invalid device token).")
        try:
            await websocket.send_text(json.dumps({
                "type": "auth_error",
                "code": "ERR_AUTH_FAILED",
                "state": PinRegistrationState.AUTHENTICATION_FAILED,
                "message": "Unauthorized or expired device token"
            }))
            await websocket.close(code=4401, reason="Unauthorized device token")
        except Exception:
            pass
        return

    # If this was promoted from pending registration, atomically promote now!
    if is_pending_promotion:
        async with pin_registration_lock:
            pending_entry = pending_registrations.pop(device_id, pending_info)
            if pending_entry:
                creds = load_device_credentials()
                pcode = pending_entry.get("pairing_code", "")
                creds[device_id] = {
                    "token_hash": pending_entry["token_hash"],
                    "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fw_version": pending_entry.get("fw_version", "2.1"),
                    "mac": pending_entry.get("mac", ""),
                    "pairing_code_used": pcode,
                }
                save_device_credentials(creds)

                if pcode and pcode in active_pairing_codes:
                    active_pairing_codes[pcode]["paired"] = True
                    active_pairing_codes[pcode]["device_id"] = device_id
                    save_active_pairing_codes()

                dev_record = registered_devices.get(device_id, {})
                dev_record.update({
                    "id": device_id,
                    "online": True,
                    "connection_source": "ESP32_DIRECT",
                    "battery": dev_record.get("battery", 100),
                    "state": "VAD ARMED",
                    "network": "Campus Wi-Fi",
                    "lastSeen": "Just paired & authenticated",
                    "cpuMhz": 160,
                    "rssi": -60,
                    "estRuntime": "--",
                    "paired": True,
                    "mac": pending_entry.get("mac", ""),
                    "fwVersion": pending_entry.get("fw_version", "2.1"),
                })
                registered_devices[device_id] = dev_record

                print(f"\n[PAIRING-PROMOTED] Smart Pin '{device_id}' PROMOTED to PAIRED! Verified via physical WebSocket.")

                # Broadcast real-time registration event to Dashboard & Mobile Companions
                await broadcast_to_ui({
                    "event_type": "pin_registered",
                    "device_id": device_id,
                    "mac": dev_record.get("mac", ""),
                    "fw_version": dev_record.get("fwVersion", "2.1"),
                    "device": dev_record,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })

    # Register into active_pins ONLY after authentication succeeds!
    old_ws = pin_active_sockets.get(device_id)
    if old_ws and old_ws != websocket:
        print(f"[WS] Superseding existing socket for '{device_id}' with newer authenticated connection.")
        try:
            active_pins.pop(old_ws, None)
            await old_ws.close(code=1000, reason="Superseded by newer connection")
        except Exception:
            pass
    pin_active_sockets[device_id] = websocket
    active_pins[websocket] = device_id
    print(f"[WS-AUTH] Smart Pin '{device_id}' authenticated successfully.")
    try:
        await websocket.send_text(json.dumps({
            "type": "auth_ok",
            "status": "authenticated",
            "device_id": device_id,
            "state": PinRegistrationState.PAIRED
        }))
    except Exception:
        pass

    pending_cfg = None
    if device_id in pending_wifi_configs:
        pending_cfg = pending_wifi_configs.pop(device_id)
    elif "ALL" in pending_wifi_configs:
        all_cfg = pending_wifi_configs["ALL"]
        delivered = all_cfg.setdefault("delivered_devices", set())
        if device_id not in delivered:
            pending_cfg = all_cfg
            delivered.add(device_id)

    if pending_cfg:
        print(f"[CFG] Pushing queued Wi-Fi checkpoint '{pending_cfg.get('checkpoint_name')}' to {device_id}...")
        try:
            await websocket.send_text(f"CONFIG:WIFI:{pending_cfg['ssid']}:{pending_cfg['pass']}:{pending_cfg['server_ip']}:{pending_cfg['server_port']}")
        except Exception as e:
            print(f"[CFG] Error pushing queued config: {e}")

    prev_dev = registered_devices.get(device_id, {})
    prev_net = prev_dev.get("network", "Campus Wi-Fi")
    prev_batt = prev_dev.get("battery", 100)
    prev_runtime = prev_dev.get("estRuntime", "--")
    registered_devices[device_id] = {
        "id": device_id,
        "online": True,
        "connection_source": "ESP32_DIRECT",
        "battery": prev_batt,
        "state": "VAD ARMED",
        "network": pending_cfg["ssid"] if pending_cfg else prev_net,
        "lastSeen": "Just now",
        "cpuMhz": 160,
        "rssi": -60,
        "estRuntime": prev_runtime,
        "paired": True,
    }
    
    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
    print(f"\n[WS] {device_id} Connected! Audio stream established.")
    
    audio_accumulator = bytearray()
    last_audio_chunk_time = time.time()
    next_expected_snapshot = False

    # Audio rate limiting per device (400 KB/s allows pre-roll drain bursts & LittleFS uploads without dropping audio)
    MAX_BYTES_PER_SECOND = 400000
    rate_window_start = time.time()
    bytes_in_window = 0

    # Streaming audio chunking: Process 6-second blocks with 1-second overlap
    # Prevents huge latency on continuous speech and avoids mid-word truncations
    CHUNK_LIMIT_BYTES = 192000 # 6s @ 16kHz 16-bit mono
    OVERLAP_BYTES = 32000      # 1s overlap

    try:
        while True:
            try:
                # 30-second timeout: With the ESP32 sending keepalive pings every 3.0s,
                # this gives a generous 10-retry safety buffer against transient Wi-Fi drops!
                message = await asyncio.wait_for(websocket.receive(), timeout=30.0)
            except asyncio.TimeoutError:
                print(f"\n[WS] {device_id} heartbeat timed out (no data for 15s, pin disconnected or unpowered).")
                break
            except (WebSocketDisconnect, RuntimeError, OSError):
                print(f"\n[WS] {device_id} disconnected.")
                break
            except Exception as wsock_err:
                print(f"\n[WS] {device_id} stream ended: {wsock_err}")
                break

            if "text" in message:
                text_msg = message["text"]
                if text_msg.startswith("PING:"):
                    # Standby keep-alive ping from ESP32: PING:<rssi>[:<battery_pct>[:<battery_mv>]]
                    parts = text_msg.split(":")
                    if len(parts) >= 2:
                        try:
                            rssi_val = int(parts[1])
                            registered_devices[device_id]["rssi"] = rssi_val
                        except Exception:
                            pass
                    if len(parts) >= 3:
                        try:
                            batt_pct = int(parts[2])
                            batt_pct = max(0, min(100, batt_pct))
                            registered_devices[device_id]["battery"] = batt_pct
                            # Realistic runtime estimation:
                            # 200mAh LiPo in 160MHz VAD Standby with modem sleep + camera sleep (~38mA avg):
                            # Total battery life is ~5.3h = ~315 minutes from 100% to 0%.
                            rem_mins = int((batt_pct / 100.0) * 315)
                            hours = rem_mins // 60
                            mins = rem_mins % 60
                            registered_devices[device_id]["estRuntime"] = f"{hours}h {mins:02d}m"
                        except Exception:
                            pass
                    if len(parts) >= 4:
                        try:
                            batt_mv = int(parts[3])
                            registered_devices[device_id]["batteryMv"] = batt_mv
                        except Exception:
                            pass
                    now_str = datetime.now().strftime("%H:%M:%S")
                    registered_devices[device_id]["online"] = True
                    registered_devices[device_id]["state"] = "VAD ARMED"
                    registered_devices[device_id]["lastSeen"] = f"Active at {now_str}"
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
                    try:
                        await websocket.send_text("PONG")
                    except Exception:
                        pass
                    continue
                elif text_msg in ("STREAM_END", "STREAM_STOP"):
                    print(f"\n[STREAM] {device_id} completed speech stream ({len(audio_accumulator)} bytes).")
                    if len(audio_accumulator) >= 4800:
                        final_pcm = bytes(audio_accumulator)
                        audio_accumulator.clear()
                        asyncio.create_task(handle_completed_audio(device_id, final_pcm, websocket))
                    else:
                        audio_accumulator.clear()
                        if device_id in registered_devices:
                            now_str = datetime.now().strftime("%H:%M:%S")
                            registered_devices[device_id]["state"] = "VAD ARMED"
                            registered_devices[device_id]["lastSeen"] = f"Active at {now_str}"
                            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
                elif text_msg.startswith("SNAP:"):
                    print(f"\n[CAM] Incoming camera frame snapshot from {device_id}...")
                    next_expected_snapshot = True
                elif "ARCHIVE_START" in text_msg:
                    print(f"\n[SYS] {device_id} syncing stored offline incident from LittleFS.")
                    # Clear accumulator before receiving offline archive to avoid mixing with previous audio
                    audio_accumulator.clear()
                elif "ARCHIVE_END" in text_msg:
                    print(f"\n[SYS] {device_id} offline incident sync complete ({len(audio_accumulator)} bytes).")
                    if len(audio_accumulator) >= 4800:
                        final_pcm = bytes(audio_accumulator)
                        audio_accumulator.clear()
                        asyncio.create_task(handle_completed_audio(device_id, final_pcm, websocket))
                    else:
                        audio_accumulator.clear()
                        if device_id in registered_devices:
                            now_str = datetime.now().strftime("%H:%M:%S")
                            registered_devices[device_id]["state"] = "VAD ARMED"
                            registered_devices[device_id]["lastSeen"] = f"Active at {now_str}"
                            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

            elif "bytes" in message:
                binary_data = message["bytes"]

                # If this payload is a JPEG camera snapshot
                if next_expected_snapshot:
                    next_expected_snapshot = False
                    try:
                        snap_id = f"snap_{device_id}_{int(time.time())}.jpg"
                        snap_path = os.path.join(SNAPSHOTS_RECORDINGS_DIR, snap_id)
                        with open(snap_path, "wb") as snap_file:
                            snap_file.write(binary_data)
                        print(f"[CAM] DANGER Snapshot saved to {snap_path} ({len(binary_data)} bytes)")
                        
                        latest_incident_id = registered_devices.get(device_id, {}).get("latest_incident_id", "")
                        primary_ip = get_primary_ip()
                        active_tunnel = get_active_tunnel_url()
                        base_url = active_tunnel if active_tunnel else f"http://{primary_ip}:8080"
                        snapshot_url = f"{base_url}/recordings/snapshots/{snap_id}"
                        local_url = f"http://127.0.0.1:8080/recordings/snapshots/{snap_id}"
                        lan_url = f"http://{primary_ip}:8080/recordings/snapshots/{snap_id}"

                        await broadcast_to_ui({
                            "event_type": "snapshot_ready",
                            "device_id": device_id,
                            "incident_id": latest_incident_id,
                            "snapshot_file": snap_id,
                            "snapshot_url": snapshot_url,
                            "local_url": local_url,
                            "lan_url": lan_url,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })
                        print(f"[CAM] Successfully broadcast snapshot_ready to UI: {snapshot_url} (local: {local_url})")
                    except Exception as snap_err:
                        print(f"[CAM] Error processing camera snapshot: {snap_err}")
                    continue

                # Rate limit protection against rogue flooding
                now = time.time()
                if now - rate_window_start >= 1.0:
                    rate_window_start = now
                    bytes_in_window = 0
                bytes_in_window += len(binary_data)
                if bytes_in_window > MAX_BYTES_PER_SECOND:
                    print(f"[WARN] {device_id} exceeded audio rate limit ({bytes_in_window} B/s > {MAX_BYTES_PER_SECOND} B/s). Dropping packet.")
                    continue

                # Normal 16kHz PCM audio stream
                audio_accumulator.extend(binary_data)
                last_audio_chunk_time = time.time()

                # Reflect STREAMING AUDIO immediately on UI so dashboard is in sync with voice
                if registered_devices.get(device_id, {}).get("state") != "STREAMING AUDIO":
                    registered_devices[device_id]["state"] = "STREAMING AUDIO"
                    registered_devices[device_id]["online"] = True
                    registered_devices[device_id]["lastSeen"] = "Streaming voice..."
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

                # Continuous speech chunking: Process in 6-second blocks with 1-second overlap
                if len(audio_accumulator) >= CHUNK_LIMIT_BYTES:
                    pcm_chunk = bytes(audio_accumulator[:CHUNK_LIMIT_BYTES])
                    # Retain 1-second overlap for boundary continuity
                    audio_accumulator = bytearray(audio_accumulator[CHUNK_LIMIT_BYTES - OVERLAP_BYTES:])
                    # Dispatch inference asynchronously so live socket reading never blocks
                    asyncio.create_task(handle_completed_audio(device_id, pcm_chunk, websocket))

    except (WebSocketDisconnect, RuntimeError, OSError):
        print(f"\n[WS] {device_id} Disconnected.")
    finally:
        # Process any remaining audio in accumulator before closing
        if len(audio_accumulator) >= 4800:
            final_pcm = bytes(audio_accumulator)
            audio_accumulator.clear()
            asyncio.create_task(handle_completed_audio(device_id, final_pcm, websocket))

        active_pins.pop(websocket, None)
        if pin_active_sockets.get(device_id) == websocket:
            del pin_active_sockets[device_id]

        # MARK PIN AS OFFLINE ONLY IF NO OTHER AUTHENTICATED DIRECT SOCKET EXISTS FOR THIS PIN
        is_still_online = (device_id in pin_active_sockets) or any(d_id == device_id for d_id in active_pins.values())
        if not is_still_online and device_id in registered_devices:
            now_str = datetime.now().strftime("%H:%M:%S")
            registered_devices[device_id]["online"] = False
            registered_devices[device_id]["connection_source"] = None
            registered_devices[device_id]["state"] = "OFFLINE"
            registered_devices[device_id]["lastSeen"] = f"Disconnected at {now_str}"
            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
            print(f"[WS] {device_id} marked OFFLINE on dashboard.")
        else:
            print(f"[WS] Disconnected socket for {device_id} was stale/superseded; active connection preserved.")

if __name__ == "__main__":
    print("=======================================================")
    print(" SECURELINK AI INFERENCE SERVER V7.0 (WHISPER + DENOISE)")
    print("=======================================================")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info", ws_ping_interval=None, ws_ping_timeout=None)
