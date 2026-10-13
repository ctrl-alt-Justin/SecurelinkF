import asyncio
import io
import json
import logging
import os
import socket
import struct
import time
import wave
from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import uvicorn

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
os.makedirs("recordings/audio", exist_ok=True)
os.makedirs("recordings/snapshots", exist_ok=True)

# Mount recordings directory so dashboard and client devices can fetch/replay audio and snapshots
app.mount("/recordings", StaticFiles(directory="recordings"), name="recordings")

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

def load_tagalog_vocabulary(filepath: str = "tagalog_words.txt"):
    """
    Loads categorized Tagalog words and phrases from text file.
    Returns:
        (initial_prompt, hotwords_str)
    """
    default_prompt = (
        "Usapan sa wikang Tagalog at Filipino ng mga estudyante sa paaralan. "
        "Mga karaniwang salita: anong ginagawa mo, malong ginagawa mo, pangit ka, "
        "walang kwenta, walang kuenta, kumusta ka, tara na kain tayo, bakit ganyan, "
        "saan ka pupunta, kailan pa, ano ba yan, pre pakiusap, tanga ka talaga, "
        "bobo, bugbugin kita, suntukan, baon, pera, palamunin, gago, "
        "hiwain, patayin kita, upakan kita, pahiram ng ballpen, resbak, yari ka na, "
        "kupal, bwisit ka, ambag mo, ilabas mo ang gamit mo, sasapakin kita, "
        "wag ka maingay, putangina, inutil, duwag, takot ka, lumayas ka, "
        "pabibo, mayabang, pakialamero, nagmamataas, sinungaling."
    )
    if not os.path.exists(filepath):
        print(f"[SYS] {filepath} not found. Using default Tagalog prompt.")
        return default_prompt, ""

    words = []
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("["):
                    words.append(line)
        print(f"[SYS] Successfully loaded {len(words)} Tagalog words/phrases from {filepath}")
        
        prompt = (
            "Usapan sa wikang Tagalog at Filipino. Mga karaniwang salita: "
            "anong meron diyan, anong meron doon, anong ginagawa mo, mic check, "
            "kumusta ka, saan ka pupunta, bakit ganyan, ano ba yan, sandali, "
            "pakiusap, teka, pakinggan mo, tulong, baon, pera, ambag, walang kwenta."
        )
        return prompt, ""
    except Exception as e:
        print(f"[WARN] Failed to load prompt ({e}).")
        return default_prompt, ""

INITIAL_TAGALOG_PROMPT, _ = load_tagalog_vocabulary()

# =========================================================================
# 2. SERVER-SIDE ACOUSTIC DENOISING SETUP (DEEPFILTERNET + NOISEREDUCE)
# =========================================================================
print("\n[SYS] Initializing Server-side Acoustic Denoising...")
has_deepfilternet = False
df_model = None
df_state = None

try:
    from df.enhance import enhance, init_df  # type: ignore
    df_model, df_state, _ = init_df()
    # The AI guide suggested DeepFilterNet3, but it was trained on English voice profiles.
    # It aggressively destroys Tagalog consonants (causing "mincent", "ndip", "Well on Cuenta").
    has_deepfilternet = False
    print("[SYS] DeepFilterNet3 disabled (distorts Tagalog). Falling back to NoiseReduce.")
except Exception:
    pass

try:
    import noisereduce as nr  # type: ignore
    has_noisereduce = True
    print("[SYS] NoiseReduce Spectral Gating loaded! Classroom AC/Fan suppression ACTIVE.")
except Exception:
    has_noisereduce = False

# =========================================================================
# 3. TAGALOG BERT THREAT CLASSIFIER SETUP
# =========================================================================
print("\n[SYS] Loading fine-tuned TagalogBERT into memory...")
MODEL_PATH = "./securelink_final_model"
try:
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
        self.target_pronouns = {"ikaw", "ka", "mo", "sayo", "sa'yo", "kita", "niyo", "ninyo"}
        self.hard_threats = ["patayin", "suntukin", "bugbugin", "tumba", "sasapakin", "tadyakan", "upakan", "hiwain", "basagin", "resbakan"]
        self.hard_extort = ["pera", "bayad", "ambag", "ilabas", "bigyan", "baon", "tax", "allowance"]
        self.hard_harass = ["pangit", "bobo", "kuwenta", "kwenta", "tanga", "ewan", "inutil", "kadiri", "baho", "palamunin", "pabigat"]

    def evaluate(self, text: str):
        if not text or len(text.strip()) < 3:
            return 0.0, "Conversational"

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

            if confidence < 0.40:
                predicted_class = 0

            if predicted_class == 0:
                base_score = 1.0
                category = "Conversational"
            elif predicted_class == 1:
                base_score = 2.0 + (confidence * 1.9)
                category = "Verbal Harassment"
            elif predicted_class == 2:
                base_score = 4.0 + (confidence * 2.0)
                category = "Extortion / Demand"
            elif predicted_class == 3:
                base_score = 7.0 + (confidence * 2.0)
                category = "Physical Threat"
            else:
                base_score = 1.0
                category = "Conversational"
        else:
            base_score = 1.0
            category = "Conversational"

        # 2. Targetedness & Heuristic Safety Net
        text_lower = text.lower()
        words = text_lower.split()
        
        is_targeted = any(p in words for p in self.target_pronouns)
        targetedness_multiplier = 1.3 if is_targeted else 1.0

        has_threat = any(t in text_lower for t in self.hard_threats)
        has_extort = any(e in text_lower for e in self.hard_extort)
        has_harass = any(h in text_lower for h in self.hard_harass)

        if has_threat:
            base_score = max(base_score, 8.5)
            category = "Physical Threat"
        elif has_extort and is_targeted and base_score < 4.0:
            base_score = max(base_score, 4.5)
            category = "Extortion / Demand"
        elif has_harass and is_targeted and base_score < 2.0:
            base_score = max(base_score, 2.5)
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
    }

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
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }))

    # Send current device states on dashboard connect
    for dev in registered_devices.values():
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
            except Exception as e:
                print(f"[UI] Error processing message: {e}")
    except WebSocketDisconnect:
        ui_clients.remove(websocket)
        print("\n[UI] Dashboard disconnected gracefully.")
    except Exception:
        if websocket in ui_clients:
            ui_clients.remove(websocket)

# =========================================================================
# 6. UDP AUTO-DISCOVERY (PORT 8888)
# =========================================================================
def get_primary_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class DiscoveryProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        print("[UDP] Auto-discovery service listening on port 8888...")

    def datagram_received(self, data, addr):
        message = data.decode('utf-8', errors='ignore')
        if "SECURELINK_PIN_V1" in message:
            true_ip = get_primary_ip()
            print(f"\n[UDP] Discovery broadcast from Pin at {addr}. Replying with server IP: {true_ip}...")
            self.transport.sendto(f"ACK:{true_ip}".encode('utf-8'), addr)

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
    print("[SYS] WebSocket Server active on port 8080 (UI: /ui | Pins: /)")
    print("[SYS] Ready for connections!\n")

# =========================================================================
# 7. AUDIO PROCESSING PIPELINE (DENOISING + WHISPER STT)
# =========================================================================
def process_audio_buffer(pcm_bytes: bytes) -> str:
    """Applies DeepFilterNet denoising and Faster-Whisper Tagalog ASR."""
    if len(pcm_bytes) < 3200: # Less than 100ms
        return ""
    
    # 1. Convert raw 16kHz 16-bit Mono PCM bytes to float32 NumPy array [-1.0, 1.0]
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0

    # Soft automatic gain boost if user speaks softly or mic is distant
    peak = float(np.max(np.abs(audio_float)))
    if 0.01 < peak < 0.40:
        boost = min(4.0, 0.75 / peak)
        audio_float = audio_float * boost

    # 2. Server-side Denoising (DeepFilterNet3 or NoiseReduce Spectral Gating)
    if has_deepfilternet and df_model is not None:
        try:
            audio_tensor = torch.from_numpy(audio_float).unsqueeze(0)
            enhanced = enhance(df_model, df_state, audio_tensor)
            audio_float = enhanced.squeeze(0).cpu().numpy()
        except Exception as e:
            print(f"[WARN] DeepFilterNet error: {e}")
    elif has_noisereduce:
        try:
            # Light stationary noise reduction (0.20) to avoid eating Tagalog vowels/formants
            audio_float = nr.reduce_noise(y=audio_float, sr=16000, prop_decrease=0.20, stationary=True)
        except Exception as e:
            print(f"[WARN] NoiseReduce error: {e}")

    # 3. Faster-Whisper Speech Recognition with Silero VAD Trimming & Beam 5 Search
    if has_whisper and whisper_model is not None:
        try:
            transcribe_kwargs = {
                "language": "tl",
                "initial_prompt": INITIAL_TAGALOG_PROMPT,
                "beam_size": 5, # Beam 5 provides high accuracy for nuanced Tagalog vocabulary
                "temperature": [0.0, 0.2], # Only 2 temperatures max: fast on GPU without infinite fallback loops
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.6, 
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
                "word_timestamps": False,
                "vad_parameters": dict(min_speech_duration_ms=150, speech_pad_ms=250),
            }

            # Silero VAD trims leading/trailing silence, ensuring clean voice frames
            segments, info = whisper_model.transcribe(
                audio_float,
                vad_filter=True,
                **transcribe_kwargs
            )
            transcript = " ".join([seg.text for seg in segments]).strip()

            # Ignore typical Whisper silence hallucinations on faint background noise
            clean_t = transcript.lower().strip().rstrip(".")
            if clean_t in ["thank you", "you", "thanks", "salamat", "maraming salamat"]:
                return ""

            return transcript
        except Exception as e:
            print(f"[ERR] Whisper transcription error: {e}")
            return ""
    
    return ""

def save_wav(pcm_bytes: bytes, filepath: str):
    """Saves raw 16kHz 16-bit PCM bytes to standard WAV format."""
    with wave.open(filepath, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_bytes)

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
    pending_cfg = pending_wifi_configs.get(device_id) or pending_wifi_configs.get("ALL")
    if pending_cfg:
        print(f"[CFG] Pushing queued Wi-Fi checkpoint '{pending_cfg.get('checkpoint_name')}' to {device_id}...")
        try:
            await websocket.send_text(f"CONFIG:WIFI:{pending_cfg['ssid']}:{pending_cfg['pass']}:{pending_cfg['server_ip']}:{pending_cfg['server_port']}")
        except Exception as e:
            print(f"[CFG] Error pushing queued config: {e}")

    prev_net = registered_devices.get(device_id, {}).get("network", "Campus Wi-Fi")
    registered_devices[device_id] = {
        "id": device_id,
        "online": True,
        "battery": 92,
        "state": "VAD ARMED",
        "network": pending_cfg["ssid"] if pending_cfg else prev_net,
        "lastSeen": "Just now",
        "cpuMhz": 80,
        "rssi": -60,
        "estRuntime": "6h 45m"
    }
    
    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})
    print(f"\n[WS] {device_id} Connected! Audio stream established.")
    
    audio_accumulator = bytearray()
    last_audio_chunk_time = time.time()
    next_expected_snapshot = False
    
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=12.0)
            except asyncio.TimeoutError:
                print(f"\n[WS] {device_id} silence timeout. Closing session.")
                break
            except Exception as wsock_err:
                print(f"\n[WS] {device_id} stream ended.")
                break

            if "text" in message:
                text_msg = message["text"]
                if text_msg.startswith("SNAP:"):
                    print(f"\n[CAM] Incoming camera frame snapshot from {device_id}...")
                    next_expected_snapshot = True
                elif "ARCHIVE_START" in text_msg:
                    print(f"\n[SYS] {device_id} syncing stored offline incident from LittleFS.")
                elif "ARCHIVE_END" in text_msg:
                    print(f"\n[SYS] {device_id} offline incident sync complete.")

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

                # Normal 16kHz PCM audio stream
                audio_accumulator.extend(binary_data)
                last_audio_chunk_time = time.time()

                # Reflect STREAMING AUDIO immediately on UI so dashboard is in sync with voice
                if registered_devices.get(device_id, {}).get("state") != "STREAMING AUDIO":
                    registered_devices[device_id]["state"] = "STREAMING AUDIO"
                    registered_devices[device_id]["online"] = True
                    registered_devices[device_id]["lastSeen"] = "Streaming voice..."
                    await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

                # No rigid mid-speech chunking! Wait for the device to send silence timeout (disconnect).
                # Fallback safeguard: Process if buffer hits 30 seconds (960,000 bytes) to prevent memory issues.
                if len(audio_accumulator) >= 960000:
                    pcm_chunk = bytes(audio_accumulator)
                    audio_accumulator.clear()

                    transcript = await asyncio.to_thread(process_audio_buffer, pcm_chunk)
                    if transcript:
                        print(f"\n[TRANSCRIPT] ({device_id}) -> \"{transcript}\"")
                        score, category = await asyncio.to_thread(context_engine.evaluate, transcript)
                        is_danger = score >= 8.0

                        if is_danger:
                            print(f"🚨 [DANGER ALERT] Severity: {score}/10 | Category: {category}")
                            print("⚡ [CAM] Dispatching TRIGGER:DANGER to pin for OV2640 snapshot!")
                            try:
                                await websocket.send_text("TRIGGER:DANGER")
                            except Exception as e:
                                print(f"[ERR] Failed to send trigger to pin: {e}")
                        elif score >= 4.0:
                            print(f"⚠️ [THREAT] Severity: {score}/10 | Category: {category}")
                        elif score >= 2.0:
                            print(f"🟡 [WARNING] Severity: {score}/10 | Category: {category}")
                        else:
                            print(f"🟢 [SAFE] Severity: {score}/10 | Category: {category}")

                        # Save evidence audio as WAV
                        incident_id = f"EVT-{int(time.time() * 1000) % 1000000}"
                        wav_filename = f"{incident_id}.wav"
                        wav_path = os.path.join("recordings/audio", wav_filename)
                        await asyncio.to_thread(save_wav, pcm_chunk, wav_path)

                        # Broadcast incident to Flutter Dashboard UI
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
                            "duration": "00:03"
                        })

    except (WebSocketDisconnect, RuntimeError, OSError):
        print(f"\n[WS] {device_id} Disconnected.")
    finally:
        # Process voice stream ONCE upon stream completion
        if len(audio_accumulator) >= 16000:
            final_pcm = bytes(audio_accumulator)
            audio_accumulator.clear() # Clear immediately to prevent any re-processing

            if device_id in registered_devices:
                registered_devices[device_id]["state"] = "ANALYZING SPEECH"
                registered_devices[device_id]["online"] = True
                registered_devices[device_id]["lastSeen"] = "Whisper inferencing..."
                await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

            t_infer_start = time.time()
            final_transcript = await asyncio.to_thread(process_audio_buffer, final_pcm)
            infer_dur = time.time() - t_infer_start

            if final_transcript:
                print(f"[FINAL TRANSCRIPT] ({device_id} in {infer_dur:.2f}s) -> \"{final_transcript}\"")
                score, category = context_engine.evaluate(final_transcript)
                is_danger = score >= 8.0
                if is_danger:
                    try:
                        await websocket.send_text("TRIGGER:DANGER")
                    except Exception:
                        pass

                incident_id = f"EVT-{int(time.time() * 1000) % 1000000}"
                wav_filename = f"{incident_id}.wav"
                wav_path = os.path.join("recordings/audio", wav_filename)
                await asyncio.to_thread(save_wav, final_pcm, wav_path)

                await broadcast_to_ui({
                    "event_type": "incident",
                    "id": incident_id,
                    "device_id": device_id,
                    "score": float(score),
                    "category": category,
                    "transcript": final_transcript,
                    "audio": True,
                    "audio_url": f"http://127.0.0.1:8080/recordings/audio/{wav_filename}",
                    "audio_file": wav_filename,
                    "video": is_danger,
                    "duration": f"00:{max(1, len(final_pcm) // 32000):02d}"
                })

        if websocket in active_pins:
            del active_pins[websocket]

        if device_id in registered_devices:
            now_str = datetime.now().strftime("%H:%M:%S")
            registered_devices[device_id]["online"] = True
            registered_devices[device_id]["state"] = "VAD ARMED (STANDBY)"
            registered_devices[device_id]["lastSeen"] = f"Active at {now_str}"
            await broadcast_to_ui({"event_type": "device_update", "device": registered_devices[device_id]})

if __name__ == "__main__":
    print("=======================================================")
    print(" SECURELINK AI INFERENCE SERVER V7.0 (WHISPER + DENOISE)")
    print("=======================================================")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
