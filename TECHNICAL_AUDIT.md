# Comprehensive Technical Audit: SecureLink IoT Safety & Threat-Detection Platform

**Audit Date:** November 2026  
**Repository Path:** `D:\Flutter Securelink Dashboard`  
**Target Environment:** Windows 10/11 x64, Seeed Studio XIAO ESP32-S3 Sense, Android Handheld Devices  
**Audit Scope:** Firmware (`esp32code.txt`), AI Inference Backend (`server.py`, `nsnet2.py`), Desktop Checkpoint Application (`securelinkdb/lib/main.dart`), Mobile Companion (`securelinkdb/lib/mobile/*`), AI Models & Training Pipelines (`train.py`, `dataset.csv`), Packaging & Deployment Scripts (`windows_installer.iss`, `package_zip.py`, `build_script.py`).

---

## 1. Executive Technical Summary & System Architecture

### 1.1 Project Identity & Domain Purpose
**SecureLink** is an automated, real-time edge IoT and on-premise AI safety monitoring platform engineered specifically for school and campus environments, with specialized linguistic modeling for Philippine educational institutions (Tagalog, English, and Taglish code-switching).

The system addresses school violence, extortion (*"panghihingi ng baon"*), and verbal harassment by deploying wearable smart pins (badges) to students and faculty. These edge nodes capture acoustic and visual telemetry, streaming audio bursts over local Wi-Fi or Bluetooth Low Energy (BLE) to an on-premise AI inference workstation. The workstation executes deep neural noise reduction (Microsoft NSNet2), speech-to-text transcription (Faster-Whisper), and multi-class sequence classification (fine-tuned TagalogBERT with heuristic escalation), broadcasting telemetry, waveform audio, and photographic snapshots to administrative desktop stations and mobile companion devices.

### 1.2 System Topology & Architecture

```
+---------------------------------------------------------------------------------------------------+
|                                  WEARABLE EDGE HARDWARE (SMART PIN)                               |
| Seeed Studio XIAO ESP32S3 Sense (160MHz Dual Core, 8MB PSRAM, PDM Mic, OV2640/OV3660 Camera)     |
|   - Core 1: I2S PDM Sampling (16kHz 16-bit Mono) -> 2nd-order Butterworth HPF (100Hz)            |
|             -> SpeexDSP VAD + Ambient Floor Tracking -> 128KB PSRAM Ring Buffer (1000ms Pre-Roll) |
|   - Core 0: Network & Transport State Machine                                                     |
|             [Tier A: Local Wi-Fi WebSocket] <---> [Tier B: BLE Nordic UART] <---> [Tier C: LittleFS]|
+---------------------------------------------------------------------------------------------------+
         | (Tier A: Direct WS /)                    | (Tier B: BLE MTU 512)            | (Tier C)
         |                                          v                                  v
         |                         +----------------------------------+        Offline Sync
         |                         |     MOBILE COMPANION DEVICE      |        to Server on
         |                         |  SecureLink Android Application  |        Reconnection
         |                         |   - BlePinRelayService           |
         |                         |   - Cellular 4G/5G / Cloudflare  |
         |                         +----------------------------------+
         |                                          | (WSS / Cloudflare Tunnel)
         +--------------------+---------------------+
                              |
                              v
+---------------------------------------------------------------------------------------------------+
|                                   CENTRAL SYSTEM AI INFERENCE ENGINE                              |
| FastAPI / Uvicorn Server (Port 8080)                                                              |
|   - UDP Auto-Discovery Daemon (Port 8888)                                                         |
|   - Infrasonic 85Hz HPF + Dynamic Peak Scaler (<=6.0x)                                            |
|   - Microsoft NSNet2 Deep Noise Suppression (ONNX Runtime, 20ms Frame / 10ms Hop)                 |
|   - Faster-Whisper ASR (CTranslate2, large-v3-turbo on CUDA / medium INT8 on CPU)                  |
|     + Silero VAD + Anti-Hallucination Repetition & Echo Filters                                   |
|   - TagalogBERT Threat Classifier (Fine-tuned RoBERTa Base, 4 Classes)                            |
|   - ContextEngine: Pronoun Targetedness (1.3x) + 5-Turn FIFO Threat Escalation                    |
|   - Static Media Server: /recordings/audio/*.wav, /recordings/snapshots/*.jpg                     |
+---------------------------------------------------------------------------------------------------+
                              |
                   (WebSocket /ui & REST API)
                              v
+---------------------------------------------------------------------------------------------------+
|                                  CHECKPOINT SECURITY DASHBOARD                                    |
| Cross-Platform Flutter Desktop (Windows Runner: securelinkdb.exe)                                 |
|   - ServerManager: Auto-supervises & monitors server.py / server.exe child process                |
|   - Tactical Glassmorphic GUI Engine: Custom particle simulation, grid rendering, ambient glow    |
|   - Real-time Incident Monitor, Audio Waveform Replay (audioplayers), Snapshot Visualizer         |
|   - Fleet Telemetry Grid (Battery %, VAD State, RSSI, Clock Rate, Runtime Heuristics)              |
|   - Network Provisioning Suite (OTA Wi-Fi Checkpoint Push + USB Serial Baud 115200 Flasher)       |
+---------------------------------------------------------------------------------------------------+
```

### 1.3 Tech Stack & Runtime Matrix

| Layer | Component | Implementation Language / Framework | Key Dependencies / Models |
|---|---|---|---|
| **Firmware** | Smart Pin Wearable | C++ / Arduino ESP32 Framework | `ESP_I2S`, `ESP32-SpeexDSP`, `WebSocketsClient`, `LittleFS`, `BLEDevice`, `esp_camera` |
| **Edge Compute** | Seeed XIAO ESP32S3 | Xtensa LX7 Dual-Core (160MHz) | FreeRTOS, PSRAM Memory Allocation, OV2640/OV3660 CMOS sensor |
| **Backend AI** | Inference Server | Python 3.10+ / FastAPI / Uvicorn | `torch`, `transformers`, `faster-whisper`, `onnxruntime`, `scipy`, `noisereduce`, `pyserial` |
| **Speech Denoise**| Neural Isolator | Microsoft NSNet2 ONNX Runtime | `models/nsnet2/nsnet2-20ms-baseline.onnx` (LogPow STFT/ISTFT) |
| **Speech-to-Text**| Multilingual ASR | Faster-Whisper (CTranslate2) | `large-v3-turbo` (CUDA float16) / `medium` (CPU int8), Silero VAD |
| **Threat NLP** | Text Classifier | Hugging Face Transformers | Fine-Tuned `jcblaise/roberta-tagalog-base` (`securelink_final_model`) |
| **Desktop GUI** | Admin Sentinel Station| Dart 3.12 / Flutter 3.44 (Desktop) | `window_manager`, `web_socket_channel`, `audioplayers`, `fl_chart`, `shared_preferences` |
| **Mobile App** | Security Companion | Dart 3.12 / Flutter 3.44 (Mobile) | `flutter_blue_plus`, `shared_preferences`, `web_socket_channel` |
| **Remote Access**| WAN Gateway | Cloudflare Quick Tunnels | `cloudflared.exe` (HTTPS / WSS tunneling) |
| **Distribution** | Installer & Packaging | Inno Setup 6 / Python scripts | `windows_installer.iss`, `package_zip.py`, `build_script.py` |

---

## 2. Hardware & Firmware Layer Deep Dive (`esp32code.txt`)

### 2.1 Hardware Configuration & Power Budget
The firmware is customized for the **Seeed Studio XIAO ESP32S3 Sense**, incorporating an onboard PDM digital microphone and an OV2640/OV3660 camera module mounted on the expansion shield.

*   **Processor Clocking:** Fixed to **160 MHz** (`setCpuFrequencyMhz(160)`) via `setup()`. This operates below the 240 MHz maximum to control thermal output within a shirt-mounted badge enclosure and conserve LiPo battery capacity.
*   **Battery Telemetry:**
    *   *Hardware ADC:* Reads GPIO 1 (A0) via 12-bit ADC with 11dB attenuation (`ADC_11db`), averaging 8 samples. An assumed external 1:2 voltage divider translates raw values into mV:
        $$\text{mV} = \left(\frac{\text{raw}}{4095.0}\right) \times 3100.0 \times 2.0$$
        Calculates percentage mapped between 3300 mV (0%) and 4200 mV (100%):
        $$\text{Pct} = \left[\frac{\text{mV} - 3300}{4200 - 3300}\right] \times 100$$
    *   *Coulomb Discharge Model Fallback:* If GPIO 1 does not measure a battery within $3.0\text{V} - 4.35\text{V}$, it falls back to a software integration model modeling a **200mAh LiPo**:
        *   Standby (160 MHz CPU, Wi-Fi modem sleep, camera powerdown): $\approx 35\text{ mA}$
        *   Active Voice Streaming (Wi-Fi awake, continuous transmission): $\approx 115\text{ mA}$
        $$\text{Consumed mAh} = \left(\frac{\text{standbyMs}}{3,600,000}\right) \times 35.0 + \left(\frac{\text{activeStreamMs}}{3,600,000}\right) \times 115.0$$
*   **Idle Power Conservation:** When not streaming or uploading flash archives, the Core 0 network loop introduces `delay(10)`, relinquishing CPU cycles to the FreeRTOS idle task (`waiti`), reducing Core 0 execution load from 100% to $\approx 2\%$.

### 2.2 Audio Acquisition & Digital Signal Processing
Acoustic capture runs deterministically on **FreeRTOS Core 1** within `audioRecordTask(void* pvParameters)` pinned at Priority 5:
*   **I2S Configuration:** Initialized via `ESP_I2S.h` in PDM RX mode (`I2S_MODE_PDM_RX`) sampling at 16,000 Hz, 16-bit mono. Pins are assigned to standard XIAO ESP32S3 Sense connections: CLK = GPIO 42, DATA = GPIO 41.
*   **2nd-Order Butterworth High-Pass Filter (HPF):** A direct form II filter executes per sample at 100 Hz cutoff:
    $$y[n] = 0.972614 \cdot x[n] - 1.945228 \cdot x[n-1] + 0.972614 \cdot x[n-2] + 1.944478 \cdot y[n-1] - 0.945978 \cdot y[n-2]$$
    This strips body handling vibrations, convective turbulence, and low-frequency classroom fan rumble without disturbing vocal fundamental frequencies ($100\text{Hz} - 3400\text{Hz}$).
*   **Voice Activity Detection (SpeexDSP VAD):** Executes `speex_preprocess_run(speex_st, vadBuffer)` over 20ms frames (320 samples).
    *   *Multi-condition Trigger:*
        1. Speex confirms vocal harmonics (`isSpeech != 0`)
        2. Filtered peak exceeds adaptive ambient floor by 50 (`currentPeak > ambientFloor + 50`)
        3. Absolute peak $\ge 220$ (ignores PDM idling noise)
        4. Amplitude hard bypass: `currentPeak >= 450` overrides Speex to eliminate silence lockups on loud shouts.
    *   *Hangover Engine:* Requires 2 consecutive frames of speech to assert `speechArmed`. On voice cessation, a 400ms (20 frames) hangover bridges natural pauses between words.
    *   *Adaptive Ambient Noise Floor Tracking:* Background baseline floats dynamically:
        $$\text{ambientFloor} = \frac{\text{ambientFloor} \times 31 + \text{currentPeak}}{32} \quad (\text{clamped between } 20 \text{ and } 200)$$

### 2.3 Memory Management & Dual-Core Ring Buffer
Audio passing VAD is routed to external PSRAM:
*   **PSRAM Buffer Size:** `RING_BUFFER_SIZE = 128,000` bytes ($\approx 4.0\text{ seconds}$ of 16kHz 16-bit mono audio).
*   **Pre-Roll Headroom:** `PRE_ROLL_BYTES = 32,000` bytes ($1,000\text{ ms}$). While idling, the reader pointer (`ringTail`) continuously tracks $32,000$ bytes behind the writer pointer (`ringHead`), guaranteeing the initial consonant of a threat is never truncated.
*   **Batching:** Packets are batched in 5 frames ($100\text{ ms} = 3,200\text{ bytes}$) reducing Wi-Fi transmission frequency from 50 packets/s to 10 packets/s.

### 2.4 Three-Tier Fallback Transport Architecture
When `speechArmed` triggers, the firmware evaluates a 3-tier transmission hierarchy:
1.  **Tier A (Direct Campus Wi-Fi):** If `ws.isConnected()`, radio sleep is disabled (`WiFi.setSleep(false)`), and binary frames are pushed directly to the central server's WebSocket `/`.
2.  **Tier B (Nordic UART BLE Bridge):** If Wi-Fi is disconnected but a mobile companion phone is connected over BLE (`bleClientConnected`), audio is packetized into sub-chunks ($\le 500$ bytes, respecting negotiated MTU 512) and pushed via characteristic notifications.
3.  **Tier C (LittleFS Offline Blackbox):** If neither Wi-Fi nor BLE is available, audio is written directly to SPI flash (`/inc_<timestamp>.pcm`). When Wi-Fi connectivity returns, an asynchronous uploader streams the archive between `ARCHIVE_START` and `ARCHIVE_END` markers.

### 2.5 Optical Forensic Evidence Capture Subsystem
*   **Camera Sensor:** Initialized via `esp_camera.h` targeting the onboard OV2640/OV3660 sensor.
*   **Frame Format:** QVGA ($320 \times 240$) JPEG compression (`FRAMESIZE_QVGA`, quality 12), double-buffered in PSRAM (`CAMERA_FB_IN_PSRAM`, `fb_count = 2`).
*   **Decoupled Worker Task:** Invocations of `captureIncidentSnapshot()` launch `snapshotWorkerTask` pinned to a separate task. This discards stale frames from the FIFO, retrieves a fresh frame, and transmits it via `SNAP:<length>` followed by raw binary JPEG payload, preventing camera bus latency from blocking audio sampling on Core 1.

---

## 3. Backend Server & AI Inference Pipeline (`server.py` & `nsnet2.py`)

### 3.1 Server Architecture & Network Endpoints
Implemented in Python using **FastAPI** running on **Uvicorn** (Port 8080):
*   **Dual WebSocket Channels:**
    *   `/`: Dedicated bidirectional endpoint for ESP32 smart pins (accepts binary PCM, JPEG snapshots, ping telemetry; dispatches Wi-Fi reconfiguration and `TRIGGER:DANGER` alerts).
    *   `/ui`: Real-time JSON broadcast channel for desktop and mobile dashboard clients.
*   **RESTful Management API:**
    *   `GET /health`, `GET /`: Health status, model readiness, active tunnel URL.
    *   `GET /api/devices`: Fleet state, battery %, RSSI, and online status.
    *   `GET /api/checkpoints` & `POST /api/checkpoints`: Persistent campus Wi-Fi AP registry.
    *   `POST /api/checkpoints/deploy`: Broadcasts configuration over OTA WebSocket or USB Serial.
    *   `POST /api/provision-pin`: Dedicated baud 115200 serial flasher.
    *   `GET /api/cloud-tunnel` & `POST /api/cloud-tunnel`: Registers Cloudflare tunnel URLs.
    *   `GET /api/denoise-settings` & `POST /api/denoise-settings`: Configures NSNet2 strength.
    *   `GET /recordings/*`: Static file mount serving audio WAVs and JPEG snapshots.
*   **UDP Auto-Discovery Service:** Operates on port **8888** via `DiscoveryProtocol(asyncio.DatagramProtocol)`. Broadcast packets matching `"SECURELINK"` receive a direct reply with the server's primary LAN IP (`ACK:<ip>` for pins, JSON payload for mobile companions).

### 3.2 Server-Side Acoustic Denoising (`nsnet2.py`)
Incoming 16-bit PCM bytes are converted to float32 normalized to $[-1.0, 1.0]$:
1.  **Infrasonic IIR Filter:** 2nd-order Butterworth filter attenuating low rumble below 85 Hz (`signal.butter(2, 85 / 8000, btype='high', output='sos')`).
2.  **Dynamic Peak Normalization:** Analyzes peak amplitude; if audio is intelligible but quiet, an automatic linear gain boost up to 6.0x scales speech toward a target peak of $0.55$:
    $$\text{gain\_scale} = \min\left(\frac{0.55}{\text{peak} + 10^{-6}}, 6.0\right)$$
3.  **Microsoft NSNet2 Neural Speech Isolator:**
    *   Model: `models/nsnet2/nsnet2-20ms-baseline.onnx` executed via ONNX Runtime (using `CUDAExecutionProvider` when available, falling back to `CPUExecutionProvider`).
    *   Computes 20ms Short-Time Fourier Transform (STFT) with 50% overlap (10ms hop) using a square-root Hanning window.
    *   Feeds Log-Power Spectrum features into the neural recurrent model to estimate spectral gain masks.
    *   Applies a $-12\text{dB}$ gain floor (`mingain = 0.251`) to avoid spectral bubbling on decaying phonemes.
    *   Blends clean and noisy spectra via `DENOISE_STRENGTH = 0.50`:
        $$\text{Gain}_{\text{blended}} = (1.0 - s) + s \cdot \text{Gain}_{\text{network}}$$
    *   Reconstructs the time-domain waveform using Inverse STFT (ISTFT).
4.  **Spectral Gating Fallback:** If NSNet2 fails or is unavailable, `noisereduce.reduce_noise` executes non-stationary spectral gating.

### 3.3 Speech-to-Text Pipeline (Faster-Whisper)
*   **Engine:** CTranslate2-based `WhisperModel`. Automatically selects `large-v3-turbo` on NVIDIA CUDA (FP16 compute) or falls back to `medium` with INT8 quantization on CPU.
*   **Decoding Configuration:**
    *   `language="tl"`: Default language set to Tagalog (accurately decodes English and Taglish without dialect drift).
    *   `temperature=[0.0]`: Deterministic greedy decoding eliminating hallucination loops.
    *   `beam_size=5`: Retains top 5 candidate hypotheses for optimal decoding accuracy.
    *   `condition_on_previous_text=False`: Prevents hallucination cascades across successive utterances.
    *   `vad_filter=True` (Silero VAD): Discards acoustic segments lacking human speech formants.
    *   `hotwords`: Biased with threat terminology (`"pangit gago tanga bobo tarantado bastos suntukan sapakan bugbog holdap nakaw pera bawal bully patayin layuan"`).
*   **Anti-Hallucination Guardrails:**
    1.  *Streak Filter:* Rejects transcripts where any word ($\ge 3$ characters) repeats consecutively $\ge 4$ times.
    2.  *Lexical Diversity:* Rejects clips with $\ge 6$ words where $\frac{\text{unique words}}{\text{total words}} < 0.35$.
    3.  *Token Concentration:* Drops transcripts where any single word constitutes $> 40\%$ of all tokens.
    4.  *Prompt Echo Filter:* Rejects transcripts where $\ge 50\%$ of words match prompt echo vocabulary.

### 3.4 NLP Sequence Classification & ContextEngine

```
[ Clean Transcript ]
        |
        v
+-----------------------------------------------------------------------------------+
| STEP 1: BASE TagalogBERT INFERENCE (securelink_final_model)                       |
|   Outputs 4 logits -> Softmax probabilities:                                      |
|     - Class 0: Conversational     -> Base Score = 1.0                             |
|     - Class 1: Verbal Harassment  -> Base Score = 4.5 + (conf * 2.0) [5.7 - 6.5]   |
|     - Class 2: Extortion / Demand -> Base Score = 5.0 + (conf * 2.0) [6.4 - 7.0]   |
|     - Class 3: Physical Threat    -> Base Score = 7.0 + (conf * 2.0) [8.4 - 9.0]   |
|   Gating: If confidence < 0.60, or Extortion/Threat lack keywords & conf < 0.70,   |
|           prediction is demoted to Class 0 (Conversational).                      |
+-----------------------------------------------------------------------------------+
        |
        v
+-----------------------------------------------------------------------------------+
| STEP 2: HEURISTIC SAFETY NETS & TARGETEDNESS MULTIPLIER                           |
|   - Targeted Pronouns: {ikaw, ka, mo, sayo, sa'yo, kita, niyo, ninyo, you, ...}   |
|     If targeted: Multiplier = 1.3x                                                |
|   - Hard Threat Keywords (patay, suntok, bugbog, upak, kill, stab, hurt you, ...):|
|     Forces Base Score = max(base, 8.5) -> "Physical Threat"                       |
|   - Hard Extortion Keywords (pera, bayad, ambag, baon, give me money, ...):       |
|     Forces Base Score = max(base, 6.0 if targeted else 4.5) -> "Extortion"        |
|   - Hard Harassment Keywords (pangit, bobo, tanga, inutil, gago, idiot, ...):     |
|     Forces Base Score = max(base, 6.5 if targeted else 4.8) -> "Verbal Harassment"|
|   Current Score = Base Score * 1.3 (if targeted and not Conversational)           |
+-----------------------------------------------------------------------------------+
        |
        v
+-----------------------------------------------------------------------------------+
| STEP 3: 5-TURN ROLLING WINDOW ESCALATION                                          |
|   Maintains FIFO queue of last 5 scores. Counts hostile events (score >= 4.5):    |
|     - Hostile Count >= 3: Final Score = max(current, 8.5) -> "Escalated Harassment"|
|     - Hostile Count == 2: Final Score = min(current * 1.5, 7.9) -> "Hostile Escal."|
|     - Otherwise: Final Score = min(current, 10.0)                                 |
+-----------------------------------------------------------------------------------+
        |
        v
[ Final Threat Score (1.0 - 10.0) & Threat Category ]
```

### 3.5 Incident Creation & Camera Trigger
When an evaluation completes:
1.  **DANGER Rating:** If `score >= 8.0`, the server transmits `TRIGGER:DANGER` over WebSocket `/` to the originating smart pin, instructing it to capture and transmit an OV2640/OV3660 snapshot.
2.  **Audio Archiving:** Denoised PCM is written to `recordings/audio/EVT-<id>.wav` via Python's `wave` module.
3.  **UI Event Broadcast:** Dispatches `incident` event to all connected `/ui` clients with audio playback URLs (local, LAN, and Cloudflare tunnel).

---

## 4. Desktop Sentinel Dashboard (`lib/main.dart`)

### 4.1 Architecture & Process Lifecycle Management
*   **File Metric:** Single monolithic file containing **7,631 lines of Dart code**.
*   **Subprocess Supervisor (`ServerManager`):** Upon launch on Windows/macOS/Linux, `ServerManager.startServerIfNeeded()` probes `http://127.0.0.1:8080/health`. If offline, it searches the file tree for `server.exe` or `server.py` and spawns the backend process asynchronously, monitoring stdout/stderr streams and polling `/health` for up to 75 seconds during model loading.
*   **Window Management:** Configures `window_manager` for frameless, transparent presentation with custom window controls (minimize, maximize, close).

### 4.2 UI Design System & Rendering Engines
The desktop application utilizes a custom dark tactical interface:
*   `_TacticalGridPainter`: Draws coordinate grid lines, subtle dotted intersections, and radar sweep aesthetics.
*   `_SplashParticlesPainter`: Custom particle physics simulation animating glowing particles across the splash screen and backdrop.
*   `_Glass`: Custom container implementing `BackdropFilter` with Gaussian blur (`sigmaX: 16, sigmaY: 16`), semi-transparent fills, and rounded borders.

### 4.3 Workspace Modules
1.  **Overview Workspace:** Real-time threat gauge, active device counters, network health diagnostics, rolling incident marquee, and immediate playback of recent incidents.
2.  **Incidents Workspace:** Filterable audit log (All, Normal, Warning, Threat, Danger). Includes full speech transcripts, audio player controls (`audioplayers`), and visual snapshot inspection modal.
3.  **Devices Workspace:** Grid cards for all registered smart pins displaying connection state (Online, Offline, VAD Armed, Streaming Audio, Analyzing), battery gauges, RSSI meters, and active Wi-Fi AP.
4.  **Analytics Workspace:** Incident frequency bar graphs, threat score distribution, category breakdown pie charts, and temporal frequency heatmaps powered by `fl_chart`.
5.  **Configuration Workspace:** DSP threshold sliders, silence timeout modifiers, and a full Wi-Fi Checkpoint manager supporting OTA deployment and USB COM port flashing.

---

## 5. Mobile Companion Ecosystem (`lib/mobile/*`)

### 5.1 Architecture & Role
Engineered for school resource officers and teachers patrolling areas without desktop access. The mobile companion focuses on monitoring, battery tracking, and hardware bridging:
*   **Entry Points:** `lib/main_mobile.dart` (dedicated mobile entrypoint) and dynamic routing in `lib/main.dart` that detects mobile platforms.
*   **Design Tokens (`MobileDesignSystem`):** Mobile palette using dark backgrounds (`#070A12`), emerald accents (`#109C6D`, `#55E2C0`), and danger indicators (`#FF4D67`).

### 5.2 BLE Audio Bridge & Cellular Data Relay (`BlePinRelayService`)
The smart pin may operate in Wi-Fi blind spots or on enterprise networks with AP client isolation preventing direct connections to port 8080.
*   `BlePinRelayService` connects to the smart pin's **Nordic UART Service (NUS)**:
    *   Service UUID: `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
    *   RX Characteristic: `6E400002-B5A3-F393-E0A9-E50E24DCCA9E`
    *   TX Characteristic: `6E400003-B5A3-F393-E0A9-E50E24DCCA9E`
*   Negotiates 512-byte MTU.
*   Subscribes to TX notifications. When the pin streams PCM audio, the phone reassembles chunks and relays them via WebSocket over cellular data (4G/5G) or phone Wi-Fi to the central system's Cloudflare tunnel endpoint.
*   Supports reassembling sliced JPEG snapshots received over BLE before forwarding.

### 5.3 Central System Synchronization (`MobileServerService`)
Maintains continuous synchronization with the Central System:
*   Dynamic fallback switching between primary LAN IP (`http://10.28.20.11:8080`) and Cloudflare Quick Tunnel (`https://*.trycloudflare.com`).
*   Listens to `/ui` WebSocket events, updating device states, incident reports, and snapshot image URLs.

---

## 6. Machine Learning Training Pipeline & Model Audit

### 6.1 NLP Sequence Classification (`train.py`)
*   **Base Pretrained Model:** `jcblaise/roberta-tagalog-base` (RoBERTa architecture pre-trained on Tagalog text).
*   **Target Classes:** 4 output classes (0: Conversational, 1: Verbal Harassment, 2: Extortion / Demand, 3: Physical Threat).
*   **Training Setup:** Hugging Face `Trainer` API with an 80/20 train/eval split, learning rate $2 \times 10^{-5}$, batch size 8, weight decay 0.01, 5 epochs, saving to `./securelink_final_model`.

### 6.2 Critical Dataset Audit (`dataset.csv`)
An inspection of `dataset.csv` reveals a critical architectural constraint:
*   **Total Dataset Size:** Exactly **66 lines / examples** total!
    *   Class 0 (Conversational): 20 examples
    *   Class 1 (Verbal Harassment): 16 examples
    *   Class 2 (Extortion / Demand): 14 examples
    *   Class 3 (Physical Threat): 16 examples
*   **80/20 Split Breakdown:** $\approx 53$ training sentences and $\approx 13$ evaluation sentences.
*   **Engineering Impact:** Fine-tuning a 110-million parameter RoBERTa model on 53 examples leads to extreme overfitting.
*   **Compensating Architecture:** The developers recognized this limitation and implemented extensive heuristic keyword safety nets, regex boundary filters, pronoun multipliers, and confidence threshold gates in `server.py` (`ContextEngine`). In practice, **the heuristic rule engine carries the primary classification workload**, while the BERT model acts as a secondary confidence scoring layer.

---

## 7. DevOps, Packaging & Distribution Pipeline

### 7.1 Windows Installer (`windows_installer.iss`)
Built using Inno Setup 6:
*   Packages `build\windows\x64\runner\Release\securelinkdb.exe`, Flutter engine DLLs, and asset bundles into `SecureLink_Desktop_Setup_v2.0.exe`.
*   *Dependency Omission:* The installer packages only the Flutter frontend. It does **not** bundle Python, CUDA libraries, CTranslate2, PyTorch, or the 450MB model weights. If executed on a client machine lacking Python and runtime packages, `ServerManager` cannot launch the AI engine.

### 7.2 Cloudflare Tunnel Gateway (`start_tunnel.py`)
*   Automates remote connectivity for cellular mobile phones.
*   Downloads portable `cloudflared.exe` from GitHub releases if missing.
*   Executes `cloudflared tunnel --url http://127.0.0.1:8080`, parses the dynamically generated `trycloudflare.com` URL via regex, writes it to `tunnel_config.json`, and notifies `server.py` via `POST /api/cloud-tunnel`.

### 7.3 Diagnostics & Diagnostics Script (`test_pipeline.py`)
Provides a 5-step automated self-test:
1. Python & PyTorch CUDA check.
2. NoiseReduce spectral suppression verification.
3. TagalogBERT model loading and 4-phrase inference test.
4. Faster-Whisper ASR load and transcribing benchmark.
5. Port availability probes (TCP 8080 and UDP 8888).

---

## 8. Security & Vulnerability Assessment

### 8.1 Findings Matrix

| Finding ID | Severity | Category | Description | Affected Components |
|---|---|---|---|---|
| **SEC-01** | **CRITICAL** | Hardcoded Secrets & Credentials | Plaintext Wi-Fi SSIDs and WPA2 Passwords (`"9945SUmaxx!"`) hardcoded in firmware source, configuration JSON, and python scripts. | `esp32code.txt`, `checkpoints.json`, `server.py` |
| **SEC-02** | **HIGH** | Authentication Deficiency | WebSocket endpoints (`/` and `/ui`) and administrative REST APIs (`/api/checkpoints`, `/api/provision-pin`) have zero authentication or token checks. | `server.py` |
| **SEC-03** | **HIGH** | Plaintext Communications | HTTP and WebSocket connections over LAN operate unencrypted (cleartext PCM audio and metadata). | `server.py`, `esp32code.txt`, Android App |
| **SEC-04** | **MEDIUM** | Identity Spoofing & NAT Collision | Smart Pin ID is determined by client IP suffix or easily spoofed `?device_id=` parameter. Multiple pins behind NAT collide on `PIN-001`. | `server.py` (`pin_websocket_endpoint`) |
| **SEC-05** | **MEDIUM** | Insecure Captive Portal | ESP32 fallback DNS and HTTP captive portal has no administrative password protection. | `esp32code.txt` (`setupAP()`) |

### 8.2 Detailed Security Findings

#### SEC-01: Hardcoded Wi-Fi Credentials & Secrets
*   In `esp32code.txt`:
    ```cpp
    String wifi_ssid = "SLTYMTBLLS";
    String wifi_pass = "9945SUmaxx!";
    String server_host = "10.28.20.28";
    ```
*   In `checkpoints.json`:
    ```json
    {
      "ssid": "SLTYMTBLLS",
      "pass": "9945SUmaxx!",
      "server_ip": "10.28.20.4"
    }
    ```
*   *Risk:* Plaintext network credentials committed to source control and distributed in binary builds compromise the campus network infrastructure.

#### SEC-02: Complete Lack of API & WebSocket Authentication
*   Any device connected to the campus Wi-Fi subnet can:
    *   Connect to `ws://<server>:8080/ui` and receive live transcripts, threat classifications, student device IDs, and photographic evidence.
    *   Send POST requests to `/api/checkpoints/deploy` to alter network settings across all deployed pins.
    *   Send `CMD:FORGET_WIFI` or `TRIGGER:DANGER` commands to trigger camera captures or disconnect pins.

#### SEC-04: Device ID Deduction & NAT Collision Vulnerability
*   In `server.py` (lines 1332–1340):
    ```python
    cf_ip = websocket.headers.get("cf-connecting-ip") or websocket.headers.get("x-forwarded-for")
    if cf_ip:
        pin_suffix = ip_clean.split(".")[-1].zfill(3)
        device_id = f"PIN-{pin_suffix}"
    else:
        client_host = websocket.client.host
        pin_suffix = client_host.split(".")[-1].zfill(3)
        device_id = f"PIN-{pin_suffix}"
    ```
*   *Risk:* When pins connect via mobile data through Cloudflare Quick Tunnels, all incoming connections share Cloudflare proxy IP blocks or common NAT gateway addresses, causing multiple physical badges to overwrite one another under the same `device_id`.

---

## 9. Concurrency, Scalability & Architectural Bottlenecks

### 9.1 Multi-Device State Collision in ContextEngine (`server.py`)
In `server.py`:
```python
class ContextEngine:
    def __init__(self):
        self.history = []
...
context_engine = ContextEngine() # SINGLETON
```
*   **The Bug:** `context_engine` is instantiated once globally. When `handle_completed_audio` runs, it calls `context_engine.evaluate(transcript)`, appending threat scores to `self.history` across **all** smart pins concurrently.
*   **Failure Scenario:** If Student A on Pin 1 experiences a mild dispute (score 4.8), and Student B on Pin 2 has a minor disagreement (score 4.6), and Student C on Pin 3 speaks another hostile phrase, `hostile_count` reaches 3 across the shared history. Pin C is falsely flagged for **Severe Escalation / DANGER (Score 8.5+)**, triggering a false camera capture and high-priority alarm because interaction histories from distinct individuals were aggregated together.

### 9.2 Global Inference Mutex Serialization
In `server.py`:
```python
ai_inference_lock = asyncio.Lock()
...
async def handle_completed_audio(...):
    ...
    async with ai_inference_lock:
        transcript, clean_pcm = await asyncio.to_thread(process_audio_buffer, pcm_bytes)
```
*   All audio processing (NSNet2, Faster-Whisper, BERT) across every smart pin is serialized behind a single global asynchronous lock.
*   *Performance Impact:* While this prevents PyTorch and CUDA memory corruption, if 10 pins transmit audio bursts simultaneously (e.g., during hallway class transitions), each taking $\approx 350\text{ ms}$, the 10th pin experiences over $3.5\text{ seconds}$ of Head-of-Line blocking delay before speech processing even begins.

### 9.3 Absence of Persistent Database
*   All active device registries (`registered_devices`), connected sockets (`active_pins`), and incident lists are stored purely in volatile Python memory dictionaries and sets.
*   *Impact:* Restarting `server.py` purges all active session states and device telemetry. The incident stream is preserved only as raw `.wav` and `.jpg` files on disk without relational metadata, search indexing, or historical incident query capabilities.

### 9.4 Monolithic Flutter Frontend Architecture
*   `lib/main.dart` spans **7,631 lines** in a single file, containing models (`DeviceStatus`, `Incident`, `WifiCheckpoint`), background process management (`ServerManager`), custom painter graphics, stateful dialogs, and 5 distinct workspace views.
*   *Impact:* Significantly hinders maintainability, cross-developer collaboration, unit testing, and modular upgrades.

---

## 10. Prioritized Actionable Recommendations

### Priority 0: Immediate Critical Fixes
1.  **Isolate ContextEngine State Per Device:** Refactor `ContextEngine` to maintain isolated interaction histories per device ID (e.g., `self.histories: dict[str, list[float]]`) so friction events on one badge do not trigger false escalation alarms on another.
2.  **Sanitize Secrets from Source Control:** Remove hardcoded Wi-Fi passwords from `esp32code.txt` and `checkpoints.json`. Load credentials via encrypted NVS flash on ESP32 and environment variables (`.env`) or secure local storage on the server.
3.  **Enforce Cryptographic Pin Identification:** Require pins to identify using unique MAC addresses (`WiFi.macAddress()`) transmitted via headers or handshake tokens, rather than relying on IP address split parsing.

### Priority 1: High Priority (Architecture & Reliability)
1.  **Implement Structured Persistence (SQLite):** Add a lightweight SQLite database (via SQLAlchemy or Tortoise-ORM in Python) to index incidents (ID, device ID, timestamp, transcript, threat score, category, WAV path, snapshot path). Expose a `GET /api/incidents` pagination endpoint so newly connected dashboards can retrieve history.
2.  **Synchronize Python Dependencies (`requirements.txt`):** Update `requirements.txt` to include all runtime dependencies:
    ```
    fastapi>=0.100.0
    uvicorn[standard]>=0.23.0
    websockets>=11.0.3
    torch>=2.0.0
    transformers>=4.30.0
    faster-whisper>=1.0.0
    onnxruntime>=1.15.0
    scipy>=1.10.0
    numpy>=1.24.0
    soundfile>=0.12.1
    pyserial>=3.5
    noisereduce>=3.0.0
    ```
3.  **Modularize `lib/main.dart`:** Decompose the 7,631-line desktop codebase into dedicated directories matching the mobile application's clean architecture:
    *   `lib/core/models/` (Incident, DeviceStatus, Checkpoint)
    *   `lib/core/services/` (ServerManager, WebSocketService)
    *   `lib/ui/views/` (Overview, Incidents, Devices, Analytics, Configuration)
    *   `lib/ui/widgets/` (TacticalGlass, WaveformPlayer, CustomPainters)

### Priority 2: Medium Priority (AI Pipeline & Dataset Enhancement)
1.  **Expand Filipino School Threat Dataset:** The current 66-sentence dataset is insufficient for generalizable deep sequence classification. Expand to $\ge 1,500$ annotated Tagalog/Taglish samples covering campus slang, regional variations, and nuanced conversational context to reduce reliance on hardcoded keyword heuristics.
2.  **Batch Inference Optimization:** Replace the global `ai_inference_lock` with an asynchronous worker queue that batches short audio segments or supports multi-stream CUDA inference using PyTorch CUDA streams.

### Priority 3: Long-Term Enhancements
1.  **Zero-Trust Fleet Authentication:** Introduce pre-shared HMAC keys or mTLS certificates between smart pins, mobile companion apps, and the central inference engine.
2.  **Self-Contained Installer Bundle:** Update `windows_installer.iss` to package an embedded Python runtime environment (or PyInstaller compiled `server.exe`) and pre-downloaded model checkpoints so the platform installs and runs out-of-the-box on standard campus hardware without manual dependency setup.

---
*Report compiled autonomously by Antigravity Technical Auditor following inspection of codebase `d:\Flutter Securelink Dashboard`.*

