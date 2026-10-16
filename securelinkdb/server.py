import asyncio
import io
import json
import logging
import os
import re
import socket
import struct
import time
import wave
from datetime import datetime

import numpy as np
import scipy.signal as signal
import torch
import torch.nn.functional as F
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import uvicorn

import sys

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

app = FastAPI(title="SecureLink AI Inference Server")

# Ensure required storage directories exist
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
os.makedirs(os.path.join(RECORDINGS_DIR, "audio"), exist_ok=True)
os.makedirs(os.path.join(RECORDINGS_DIR, "snapshots"), exist_ok=True)

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
TAGALOG_HOTWORDS = "pangit gago tanga bobo tarantado bastos suntukan sapakan bugbog holdap nakaw pera bawal bully patayin layuan"

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
# 4. CONTEXT ENGINE (NLP CLASSIFICATION + PRONOUN TARGETING + ESCALATION)
# =========================================================================
class ContextEngine:
    def __init__(self):
        self.history = []
        self.target_pronouns = {"ikaw", "ka", "mo", "sayo", "sa'yo", "kita", "niyo", "ninyo", "you", "your", "u"}
        self.hard_threats = [
            # Tagalog violence verbs & conjugations (patay, suntok, sapak, bugbog, tadyak, etc.)
            "patayin", "papatayin", "ipapatay", "ipapapatay", "pinatay", "katayin", "kakatayin",
            "pupugutan", "pugutan", "mamatay", "mamatay ka", "patay ka", "patay ka sakin", "patay ka sa akin",
            "suntukin", "susuntukin", "sinuntok", "suntukan", "masuntok",
            "sasapakin", "sapakin", "sinapak", "sapakan", "masapak",
            "bugbugin", "bubugbugin", "binugbog", "bugbugan", "mabugbog",
            "tadyakan", "tatadyakan", "tinadyakan",
            "upakan", "uupakan", "inupakan", "upakan kita",
            "saksakin", "sasaksakin", "sinaksak", "saksakan",
            "hiwain", "hihiwain", "hiniwa",
            "tumbahin", "tutumbahin", "tinumba", "itumba", "itatumba", "tumba",
            "barilin", "babarilin", "binaril", "ipabaril",
            "gulpihin", "gugulpihin", "ginulpi", "gulpihan",
            "laslasin", "lalaslasin", "laslas",
            "basagin", "babasagin", "binasag",
            "resbakan", "reresbakan", "niresbakan",
            "sasaktan", "saktan", "sinaktan", "masaktan",
            "abangan", "aabangan", "inabangan", "abangan kita",
            "yari ka", "yari ka sakin", "yari ka sa akin",
            # English physical threats
            "kill", "murder", "stab", "shoot", "beat you up", "i will kill you",
            "threat", "attack", "die", "hurt you", "punch"
        ]
        self.hard_extort = [
            "pera", "bayad", "ambag", "ilabas", "bigyan", "baon", "tax", "allowance",
            "akin na", "ibigay mo", "labas mo pera", "holdap", "snatch", "nakaw",
            "give me money", "pay up", "hand it over", "give your money", "extort", "rob"
        ]
        self.hard_harass = [
            # Filipino bullying, ableist slurs, & psychological harassment
            "mongoloid", "mong guloid", "mongol", "abnoy", "autistic", "retard", "retarded",
            "sinto-sinto", "sintosinto", "may sayad", "sayad", "baliw", "luka-luka", "lukaluka",
            "buang", "amaw", "timang", "kulang-kulang", "kulangkulang", "may tama", "may sira",
            "siraulo", "sira ulo", "unggoy", "aswang",
            # Appearance, body-shaming, & social bullying
            "tabatoy", "baboy", "balyena", "tingting", "kalansay", "ngongo", "ngiwi",
            "panget", "pangit", "chaka", "mukhang paa", "dugyot", "mabaho", "baho",
            "amoy lupa", "amoy araw", "uling",
            # Social degradation & poverty insults
            "squatter", "skwater", "isquatter", "pulubi", "hampaslupa", "hampas lupa",
            "patay gutom", "patay-gutom", "alipin", "palamunin", "pabigat", "salot",
            "patapon", "basura", "walang kwenta", "walang silbi", "ampaw", "inutil",
            # Homophobic / gender insults & sexual harassment
            "bakla", "bading", "bayot", "tibo", "pokpok", "malandi", "kiri", "higad", "hitad", "puday", "bastos",
            # Tagalog profanities, vulgarities, & verbal abuse
            "gago", "gaga", "tarantado", "tarantada", "ulol", "tangina", "tang ina", "tanginamo", "tang ina mo",
            "putangina", "putang ina", "putanginamoka", "puta", "pakshet", "pakyu", "kupal",
            "leche", "letse", "bwisit", "bwiset", "hayop", "hayup", "walanghiya", "walang hiya",
            "taragis", "hudas", "bobo", "tanga", "ungas", "punyeta", "lintik", "demonyo",
            "kingina", "king ina", "pota", "yawa", "kuwenta", "kwenta",
            # English profanities, bullying & hate speech
            "fuck", "fucking", "fucked", "shit", "bitch", "asshole", "bastard", "dick", "cunt",
            "idiot", "stupid", "ugly", "loser", "shut up", "worthless", "freak", "fool",
            "pig", "gross", "trash", "drop dead"
        ]

    def _matches_any(self, text_lower: str, keywords: list) -> bool:
        for k in keywords:
            if " " in k or "-" in k:
                if k in text_lower:
                    return True
            else:
                if re.search(r'\b' + re.escape(k) + r'\b', text_lower):
                    return True
        return False

    def evaluate(self, text: str):
        if not text or len(text.strip()) < 3:
            return 0.0, "Conversational"

        text_lower = text.lower()
        words = text_lower.split()

        # 1. Base Deep Learning Inference
        if bert_model and tokenizer:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
            if device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
            with torch.no_grad():
                outputs = bert_model(**inputs)
            
            logits = outputs.logits
            probabilities = F.softmax(logits, dim=-1)
            predicted_class = logits.argmax(-1).item()
            confidence = probabilities[0][predicted_class].item()

            if confidence < 0.60:
                predicted_class = 0

            if predicted_class == 0:
                base_score = 1.0
                category = "Conversational"
            elif predicted_class == 1:
                base_score = 4.5 + (confidence * 2.0)
                category = "Verbal Harassment"
            elif predicted_class == 2:
                # Extortion requires confidence >= 0.70 or presence of hard extortion keywords
                has_extort_check = self._matches_any(text_lower, self.hard_extort)
                if confidence >= 0.70 or has_extort_check:
                    base_score = 5.0 + (confidence * 2.0)
                    category = "Extortion / Demand"
                else:
                    base_score = 1.0
                    category = "Conversational"
            elif predicted_class == 3:
                # Physical threat requires confidence >= 0.70 or presence of hard threat keywords
                has_threat_check = self._matches_any(text_lower, self.hard_threats)
                if confidence >= 0.70 or has_threat_check:
                    base_score = 7.0 + (confidence * 2.0)
                    category = "Physical Threat"
                else:
                    base_score = 1.0
                    category = "Conversational"
            else:
                base_score = 1.0
                category = "Conversational"
        else:
            base_score = 1.0
            category = "Conversational"

        # 2. Targetedness & Heuristic Safety Net
        is_targeted = any(p in words for p in self.target_pronouns)
        targetedness_multiplier = 1.3 if is_targeted else 1.0

        has_threat = self._matches_any(text_lower, self.hard_threats)
        has_extort = self._matches_any(text_lower, self.hard_extort)
        has_harass = self._matches_any(text_lower, self.hard_harass)

        if has_threat:
            base_score = max(base_score, 8.5)
            category = "Physical Threat"
        elif has_extort:
            base_score = max(base_score, 6.0 if is_targeted else 4.5)
            category = "Extortion / Demand"
        elif has_harass:
            # Bullying words, hate speech, & profanities are serious violations:
            # Untargeted: 4.8 (triggers THREAT level and visual alert)
            # Targeted (e.g. "mongoloid ka", "gago ka", "tangina mo"): 6.5 (severe THREAT)
            base_score = max(base_score, 6.5 if is_targeted else 4.8)
            category = "Verbal Harassment"

        current_score = base_score * targetedness_multiplier if category != "Conversational" else base_score

        # 3. Rolling Window Aggregation (Threat Escalation)
        self.history.append(current_score)
        if len(self.history) > 4:
            self.history.pop(0)

        consecutive_friction = sum(1 for s in self.history if s >= 2.0)
        
        if consecutive_friction >= 2 and current_score >= 2.0:
            final_score = min(current_score * 1.25, 10.0)
        else:
            final_score = min(current_score, 10.0)

        return round(final_score, 1), category

context_engine = ContextEngine()

# =========================================================================
# 5. WEBSOCKET & DEVICE FLEET ORCHESTRATION
# =========================================================================
ui_clients = set()
registered_devices = {}
active_pins = {} # Map of websocket -> device_id
harmful_words_only = False # Default False so all speech during testing is visible on the dashboard!

async def broadcast_to_ui(payload: dict):
    if not ui_clients:
        return
    dead_clients = set()
    message = json.dumps(payload)
    for client in ui_clients:
        try:
            await client.send_text(message)
        except Exception:
            dead_clients.add(client)
    ui_clients.difference_update(dead_clients)

@app.get("/health")
@app.get("/")
async def health_check():
    return {
        "status": "online",
        "app": "SecureLink AI Server",
        "whisper": has_whisper,
        "classifier": bert_model is not None,
    }

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
    password = str(payload.get("pass", "")).strip()
    server_ip = str(payload.get("server_ip", get_primary_ip())).strip()
    try:
        server_port = int(payload.get("server_port", 8080))
    except (ValueError, TypeError):
        server_port = 8080

    if not port:
        return {"status": "error", "message": "No USB COM port selected."}
    if not ssid:
        return {"status": "error", "message": "Wi-Fi SSID cannot be empty."}

    import serial
    try:
        print(f"\n[PROVISION] Opening serial port {port} at 115200 baud...")
        ser = serial.Serial(port, 115200, timeout=1.5)
        time.sleep(0.3)
        ser.reset_input_buffer()

        cmd = f"SET_WIFI:{ssid}:{password}:{server_ip}:{server_port}\n"
        print(f"[PROVISION] Sending command to Pin: SET_WIFI:{ssid}:****:{server_ip}:{server_port}")
        ser.write(cmd.encode("utf-8"))
        ser.flush()

        logs = []
        start_t = time.time()
        while time.time() - start_t < 2.5:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    logs.append(line)
                    print(f"[PIN-SERIAL] {line}")
                    if "OK:CONFIG_SAVED" in line:
                        break
            time.sleep(0.04)

        ser.close()
        return {
            "status": "success",
            "message": f"Wi-Fi credentials flashed to {port}! Pin is connecting to '{ssid}'...",
            "logs": logs
        }
    except Exception as e:
        print(f"[PROVISION] Error on {port}: {e}")
        return {"status": "error", "message": f"Could not communicate with {port}: {str(e)}"}


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
    return {
        "status": "online",
        "cs_id": "CS-CAMPUS-01",
        "name": "SecureLink Campus Central System",
        "server_ip": true_ip,
        "server_port": 8080,
        "priority_level": "PRIMARY (Priority 1: Central System, Priority 2: Mobile App)",
        "active_pins_count": len(active_pins),
        "registered_pins": list(registered_devices.keys()),
        "ui_clients_count": len(ui_clients),
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

async def pin_liveness_watchdog():
    """Runs every 3 seconds. Forces any device without an active socket to OFFLINE."""
    while True:
        await asyncio.sleep(3.0)
        try:
            for dev_id, dev in list(registered_devices.items()):
                is_active = any(d_id == dev_id for d_id in active_pins.values())
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
            for folder in ["recordings/audio", "recordings/snapshots"]:
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

    print("[SYS] WebSocket Server active on port 8080 (UI: /ui | Pins: /)")
    print("[SYS] Ready for connections!\n")

# =========================================================================
# 7. AUDIO PROCESSING PIPELINE (DENOISING + WHISPER STT)
# =========================================================================
def process_audio_buffer(pcm_bytes: bytes) -> tuple[str, bytes]:
    """Applies 4th-order fan filter, NoiseReduce spectral gating, and Faster-Whisper Tagalog ASR."""
    if len(pcm_bytes) < 3200: # Less than 100ms
        return "", pcm_bytes
    
    # 1. Convert raw 16kHz 16-bit Mono PCM bytes to float32 NumPy array [-1.0, 1.0]
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0

    # 2. Strip infrasonic fan blade chop & motor rumble (< 85Hz) while preserving vocal formants (90Hz-3400Hz)
    try:
        sos_hp = signal.butter(2, 85 / (16000 / 2), btype='high', output='sos')
        audio_float = signal.sosfilt(sos_hp, audio_float).astype(np.float32)
    except Exception as e:
        pass

    rms = float(np.sqrt(np.mean(audio_float**2)))
    peak = float(np.max(np.abs(audio_float)))

    # Only drop pure electrical silence or dead mic line (peak < 0.003, raw ADC peak < 100)
    if peak < 0.003:
        print(f"[ASR] Dropped pure digital silence (RMS={rms:.4f}, Peak={peak:.4f})")
        return "", pcm_bytes

    # Scale speech dynamically so it enters Whisper at optimal operating level (~0.55 peak)
    # This ensures soft speech and normal distance speech are recognized crystal-clearly
    # without squashing or clipping loud words!
    target_peak = 0.55
    gain_scale = min(target_peak / (peak + 1e-6), 6.0) # Up to 6x clean linear boost
    if gain_scale > 1.0:
        audio_float = audio_float * gain_scale

    # 3. Server-side Denoising (Microsoft NSNet2 Neural Speech Isolation with Balanced Strength)
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

    # Ensure float32 for Whisper/Silero VAD ONNX models
    audio_float = np.asarray(audio_float, dtype=np.float32)

    # Do NOT artificially boost gain on fan hiss; keep speech dynamics natural
    audio_float = np.clip(audio_float, -0.99, 0.99)

    # 4. Convert clean audio float back to 16-bit PCM bytes for playback in recordings
    clean_int16 = np.clip(audio_float * 32767.0, -32768, 32767).astype(np.int16)
    clean_pcm_bytes = clean_int16.tobytes()

    # 5. Faster-Whisper Speech Recognition with Tightened Speech Knobs
    if has_whisper and whisper_model is not None:
        try:
            transcribe_kwargs = {
                "language": "tl", # Set primary language to Tagalog (Whisper handles Taglish & English seamlessly without phoneme confusion)
                "initial_prompt": INITIAL_TAGALOG_PROMPT if INITIAL_TAGALOG_PROMPT else None,
                "hotwords": TAGALOG_HOTWORDS if TAGALOG_HOTWORDS else None,
                "beam_size": 5, # Beam size 5: explores top candidate paths, greatly improving recognition accuracy
                "temperature": [0.0], # 0.0 only: kills fallback hallucinations like 'ae, taray, taray'
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.65,
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
                "word_timestamps": False,
                "vad_parameters": dict(threshold=0.40, min_speech_duration_ms=250, speech_pad_ms=300),
            }

            # Silero VAD isolates genuine human speech segments from noise
            segments, info = whisper_model.transcribe(
                audio_float,
                vad_filter=True,
                **transcribe_kwargs
            )

            # Silero Gate: if vad_filter returned zero speech segments, return empty immediately
            valid_segments = [seg.text.strip() for seg in segments if getattr(seg, 'no_speech_prob', 0.0) < 0.5 and seg.text.strip()]
            if not valid_segments:
                return "", clean_pcm_bytes

            # Fallback Rule: only force 'tl' if duration >= 2.5s and detected language is non-Philippine
            dur_sec = len(audio_float) / 16000.0
            detected_lang = getattr(info, 'language', 'tl')
            if detected_lang not in ('tl', 'en'):
                if dur_sec >= 2.5:
                    print(f"[ASR] Auto-detected '{detected_lang}' on {dur_sec:.1f}s clip. Re-running with forced Tagalog ('tl')...")
                    fallback_kwargs = dict(transcribe_kwargs)
                    fallback_kwargs["language"] = "tl"
                    segments, info = whisper_model.transcribe(
                        audio_float,
                        vad_filter=True,
                        **fallback_kwargs
                    )
                    valid_segments = [seg.text.strip() for seg in segments if getattr(seg, 'no_speech_prob', 0.0) < 0.5 and seg.text.strip()]
                else:
                    print(f"[ASR] Discarded short noisy clip ({dur_sec:.1f}s) misdetected as '{detected_lang}'")
                    return "", clean_pcm_bytes

            transcript = " ".join(valid_segments).strip()

            # Word-level tokenization for human-style loop & prompt-echo detection
            words = [re.sub(r'[^a-zA-Z0-9ñÑ]', '', w.lower()) for w in transcript.split()]
            words = [w for w in words if w]

            if not words:
                return "", clean_pcm_bytes

            # Reject standard mic-check & silence hallucinations
            clean_t = transcript.lower().strip().rstrip(".!?,")
            if clean_t in [
                "hello my check", "hello mic check", "mic check", "my check", 
                "thank you", "you", "thanks", "salamat", "maraming salamat"
            ]:
                return "", clean_pcm_bytes

            # Check 1: The same word (length >= 3) appears >= 4 times consecutively
            streak = 1
            max_streak = 1
            for idx in range(1, len(words)):
                if len(words[idx]) >= 3 and words[idx] == words[idx - 1]:
                    streak += 1
                    if streak > max_streak:
                        max_streak = streak
                else:
                    streak = 1
            if max_streak >= 4:
                print(f"[ASR] Dropped consecutive word repetition loop (streak={max_streak}): \"{transcript[:50]}...\"")
                return "", clean_pcm_bytes

            # Check 2: Lexical diversity (unique words / total words < 0.35 on clips with >= 6 words)
            if len(words) >= 6:
                lexical_diversity = len(set(words)) / len(words)
                if lexical_diversity < 0.35:
                    print(f"[ASR] Dropped low-diversity loop (diversity={lexical_diversity:.2f}): \"{transcript[:50]}...\"")
                    return "", clean_pcm_bytes

            # Check 3: Token concentration (> 40% of words are identical in clip with >= 5 words)
            if len(words) >= 5:
                from collections import Counter
                word_counts = Counter(words)
                most_common_word, count = word_counts.most_common(1)[0]
                if len(most_common_word) >= 3 and (count / len(words)) > 0.40:
                    print(f"[ASR] Dropped word-concentrated loop ('{most_common_word}' is {count}/{len(words)} tokens): \"{transcript[:50]}...\"")
                    return "", clean_pcm_bytes

            # Check 4: Prompt-echo filter (if >= 50% of words match prompt echo vocabulary)
            if PROMPT_ECHO_WORDS and len(words) >= 2:
                echo_count = sum(1 for w in words if w in PROMPT_ECHO_WORDS)
                if (echo_count / len(words)) >= 0.50:
                    print(f"[ASR] Dropped prompt-echo hallucination ({echo_count}/{len(words)} prompt words): \"{transcript[:50]}...\"")
                    return "", clean_pcm_bytes

            return transcript, clean_pcm_bytes
        except Exception as e:
            print(f"[ERR] Whisper transcription error: {e}")
            return "", clean_pcm_bytes
    
    return "", clean_pcm_bytes

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

async def handle_completed_audio(device_id: str, pcm_bytes: bytes, websocket: WebSocket):
    """Processes accumulated speech audio buffer, runs Faster-Whisper + BERT, and updates UI."""
    if len(pcm_bytes) < 6400: # Less than 200ms
        if device_id in registered_devices:
            now_str = datetime.now().strftime("%H:%M:%S")
            is_still_connected = any(d_id == device_id for d_id in active_pins.values())
            registered_devices[device_id]["online"] = is_still_connected
            registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
            registered_devices[device_id]["lastSeen"] = f"Active at {now_str}" if is_still_connected else f"Disconnected at {now_str}"
            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
        return

    dur_sec = len(pcm_bytes) / 32000.0
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_peak = float(np.max(np.abs(audio_int16))) / 32768.0

    if device_id in registered_devices:
        registered_devices[device_id]["state"] = "ANALYZING SPEECH"
        registered_devices[device_id]["online"] = True
        registered_devices[device_id]["lastSeen"] = "Whisper inferencing..."
        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

    async with ai_inference_lock:
        t_infer_start = time.time()
        transcript, clean_pcm = await asyncio.to_thread(process_audio_buffer, pcm_bytes)
        infer_dur = time.time() - t_infer_start

        if transcript:
            print(f"[FINAL TRANSCRIPT] ({device_id} in {infer_dur:.2f}s, dur={dur_sec:.2f}s, peak={audio_peak:.2f}) -> \"{transcript}\"")
            score, category = context_engine.evaluate(transcript)
            is_danger = score >= 8.0

            # --- HARMFUL WORDS ONLY FILTER ---
            # When active, ignore benign/conversational speech and do not save WAV or log incident
            is_harmful = (category != "Conversational") or (score >= 2.0)
            if harmful_words_only and not is_harmful:
                print(f"[FILTER] Ignored conversational speech under 'Harmful Words Only' mode: \"{transcript}\" (cat={category}, score={score})")
                if device_id in registered_devices:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    is_still_connected = any(d_id == device_id for d_id in active_pins.values())
                    registered_devices[device_id]["online"] = is_still_connected
                    registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
                    registered_devices[device_id]["lastSeen"] = f"Filtered benign speech at {now_str}" if is_still_connected else f"Disconnected at {now_str}"
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
                return

            if is_danger:
                try:
                    await websocket.send_text("TRIGGER:DANGER")
                except Exception:
                    pass

            incident_id = f"EVT-{int(time.time() * 1000) % 1000000}"
            wav_filename = f"{incident_id}.wav"
            wav_path = os.path.join("recordings/audio", wav_filename)
            # Save the clean, denoised audio to WAV so playback is crystal-clear and fan-free
            await asyncio.to_thread(save_wav, clean_pcm, wav_path)

            await broadcast_to_ui({
                "event_type": "incident",
                "id": incident_id,
                "device_id": device_id,
                "score": float(score),
                "category": category,
                "transcript": transcript,
                "audio": True,
                "audio_url": f"http://127.0.0.1:8080/recordings/audio/{wav_filename}",
                "audio_file": wav_filename,
                "video": is_danger,
                "duration": f"00:{max(1, int(dur_sec)):02d}"
            })
        else:
            print(f"[ASR] ({device_id} in {infer_dur:.2f}s) Audio received ({dur_sec:.2f}s, peak={audio_peak:.2f}) -> No speech recognized (faint noise/silence)")

    if device_id in registered_devices:
        now_str = datetime.now().strftime("%H:%M:%S")
        is_still_connected = any(d_id == device_id for d_id in active_pins.values())
        registered_devices[device_id]["online"] = is_still_connected
        registered_devices[device_id]["state"] = "VAD ARMED" if is_still_connected else "OFFLINE"
        if is_still_connected:
            registered_devices[device_id]["lastSeen"] = f'Heard: "{transcript[:25]}..."' if transcript else f"Active at {now_str}"
        else:
            registered_devices[device_id]["lastSeen"] = f"Disconnected at {now_str}"
        await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

# =========================================================================
# 8. PHYSICAL PIN WEBSOCKET ENDPOINT (AUDIO STREAM & DANGER TRIGGER)
# =========================================================================
@app.websocket("/")
async def pin_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Consistent device ID based on client IP so reconnects do not create duplicate phantom pins
    client_host = websocket.client.host if (websocket.client and websocket.client.host) else "001"
    pin_suffix = client_host.split(".")[-1].zfill(3) if "." in client_host else "001"
    device_id = f"PIN-{pin_suffix}"
    active_pins[websocket] = device_id
    
    # Check if there is a pending Wi-Fi config queued for this pin or fleet-wide
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
        "battery": prev_batt,
        "state": "VAD ARMED",
        "network": pending_cfg["ssid"] if pending_cfg else prev_net,
        "lastSeen": "Just now",
        "cpuMhz": 160,
        "rssi": -60,
        "estRuntime": prev_runtime
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

    # Streaming audio chunking: Process 15-second blocks with 1-second overlap
    # Prevents huge latency on continuous speech and avoids mid-word truncations
    CHUNK_LIMIT_BYTES = 480000 # 15s @ 16kHz 16-bit mono
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
                    if len(audio_accumulator) >= 6400:
                        final_pcm = bytes(audio_accumulator)
                        audio_accumulator.clear()
                        await handle_completed_audio(device_id, final_pcm, websocket)
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
                    if len(audio_accumulator) >= 6400:
                        final_pcm = bytes(audio_accumulator)
                        audio_accumulator.clear()
                        await handle_completed_audio(device_id, final_pcm, websocket)
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
                    snap_id = f"snap_{device_id}_{int(time.time())}.jpg"
                    snap_path = os.path.join("recordings/snapshots", snap_id)
                    with open(snap_path, "wb") as snap_file:
                        snap_file.write(binary_data)
                    print(f"📸 [CAM] DANGER Snapshot saved to {snap_path} ({len(binary_data)} bytes)")
                    
                    await broadcast_to_ui({
                        "event_type": "snapshot_ready",
                        "device_id": device_id,
                        "snapshot_file": snap_id,
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
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

                # Continuous speech chunking: Process in 15-second blocks with 1-second overlap
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
        if len(audio_accumulator) >= 6400:
            final_pcm = bytes(audio_accumulator)
            audio_accumulator.clear()
            await handle_completed_audio(device_id, final_pcm, websocket)

        if websocket in active_pins:
            del active_pins[websocket]

        # MARK PIN AS OFFLINE IMMEDIATELY UPON DISCONNECT OR TIMEOUT
        if device_id in registered_devices:
            now_str = datetime.now().strftime("%H:%M:%S")
            registered_devices[device_id]["online"] = False
            registered_devices[device_id]["state"] = "OFFLINE"
            registered_devices[device_id]["lastSeen"] = f"Disconnected at {now_str}"
            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
            print(f"[WS] {device_id} marked OFFLINE on dashboard.")

if __name__ == "__main__":
    print("=======================================================")
    print(" SECURELINK AI INFERENCE SERVER V7.0 (WHISPER + DENOISE)")
    print("=======================================================")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info", ws_ping_interval=None, ws_ping_timeout=None)
