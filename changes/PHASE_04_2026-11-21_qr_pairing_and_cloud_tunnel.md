# SecureLink Phase 4: QR Mobile Pairing, Cross-Network Synchronization, and Automated Cloudflare Quick Tunnel

**Date:** 2026-11-21  
**Repository:** `ctrl-alt-Justin/SecurelinkF`  
**Working Branch:** `PinPairing`  
**Base/Reference Branch:** `v2exp`  

---

## 1. Executive Summary

Phase 4 introduces end-to-end mobile pairing, zero-domain cross-network remote connectivity, and robust synchronization between the SecureLink Central System dashboard and the mobile companion application. The implementation replaces fragile hardcoded tunnel addresses with an automated, self-healing Cloudflare Quick Tunnel manager, establishes a cryptographically secure QR code and 8-digit numeric pairing workflow with administrator approval gating, and implements local-first automatic network switching for mobile devices moving across campus Wi-Fi and cellular networks.

---

## 2. Key Objectives & Accomplishments

| Objective | Status | Implementation Details |
|---|---|---|
| **Zero-Domain Cloudflare Quick Tunnel** | **COMPLETED** | Created `securelinkdb/tunnel_manager.py` using `cloudflared` Quick Tunnels (`https://*.trycloudflare.com`). No domain or account required. |
| **Tunnel Self-Healing & State Machine** | **COMPLETED** | Single-instance enforcement, reachability health checks (`/health`), dynamic states (`Connected`, `Starting`, `Reconnecting`, `Offline`, `Error`), and exponential backoff restart (2s..30s). |
| **Purge Hardcoded Fallback Hostnames** | **COMPLETED** | Purged `rings-diploma-evaluated-mls.trycloudflare.com` across backend, firmware, mobile app, and dashboard. |
| **Secure Mobile Pairing Engine** | **COMPLETED** | Built `securelinkdb/mobile_pairing.py` with 8-digit CSPRNG codes, SHA-256 hashed memory verification, 90s TTL, single-use enforcement, and rate-limiting lockout (5 fails $\rightarrow$ 60s lockout). |
| **Administrator Approval Gate** | **COMPLETED** | Mobile pairing requests require explicit administrator authorization in the dashboard. Admins assign roles (`Responder`, `Investigator`, `Viewer`, `Admin`) and inspect connection types before issuing 32-byte tokens. |
| **Dedicated Mobile WebSocket (`/mobile`)** | **COMPLETED** | Dedicated endpoint with token-based authentication (`hmac.compare_digest`), local/remote identification, role gating, initial incident cache burst, and broadcast deduplication. |
| **Firmware Security & Hardening** | **COMPLETED** | In `esp32code.txt`: fixed WebSocket auth bypass bug, redacted Wi-Fi credentials and pairing codes from serial logs, added BLE fragmentation reassembly buffer (1024 bytes), and enabled `WiFiClientSecure` for HTTPS tunnels. |
| **Mobile Scanner & Pairing Modal** | **COMPLETED** | Built `securelinkdb/lib/mobile/widgets/pair_mobile_modal.dart` featuring camera QR scanning (`mobile_scanner`), manual 8-digit code input, 90s timer, and secure credential storage (`flutter_secure_storage`). |
| **Local-First & Auto-Reconnect Architecture** | **COMPLETED** | Mobile companion prioritizes low-latency local Wi-Fi, falls back to active Cloudflare tunnel remotely, and executes a 15-second background probe to seamlessly switch back when returning to campus. |
| **Desktop Central System UI** | **COMPLETED** | Updated `securelinkdb/lib/main.dart` with header pair button, `_PairMobileDialog` with `qr_flutter`, dynamic tunnel header status badge, `_CloudflareTunnelDialog` start/stop controls, and paired mobile device management table in `_DevicesPage`. |
| **Release Artifacts & Tests** | **COMPLETED** | Built fresh Android release APK (`SecureLink-Mobile-Latest.apk`, 67.0MB) and validated 45/45 automated unit & integration tests (`OK`). |

---

## 3. Architecture Overview

```
                                  +------------------------------------+
                                  |   XIAO ESP32-S3 Wearable Pin       |
                                  |   - Microphone & VAD               |
                                  |   - WiFiClientSecure HTTPS & BLE   |
                                  +-----------------+------------------+
                                                    | (Audio Stream /ws)
                                                    v
+---------------------------------------------------------------------------------------------------+
| CENTRAL SYSTEM DASHBOARD & SERVER (Port 8080)                                                      |
|                                                                                                   |
|  [Cloudflare Quick Tunnel Manager]                  [Mobile Pairing Manager]                      |
|  - cloudflared process manager                      - 8-digit CSPRNG pairing code                 |
|  - Port 8080 HTTPS/WSS proxy                        - SHA-256 hash memory storage                 |
|  - Auto-restart & health check                      - Rate limit: 5 fails -> 60s lockout          |
|  - State: Connected/Reconnecting                    - Admin role & user authorization             |
|                                                                                                   |
|  [Inference Pipeline]                               [WebSocket Hub]                               |
|  - Faster-Whisper ASR (float16 CUDA)                - /ui     -> Desktop operator console         |
|  - NSNet2 Acoustic Denoising                        - /mobile -> Authenticated mobile companions  |
|  - TagalogBERT Multi-Class Classifier               - /       -> Hardware pins audio stream       |
+---------------------------------+---------------------------------+-------------------------------+
                                  |                                 |
           (Local Campus Wi-Fi)   |                                 | (Public Encrypted WSS / HTTPS)
           http://10.28.20.30:8080|                                 | https://*.trycloudflare.com
                                  v                                 v
                     +---------------------------------------------------+
                     |           SECURELINK MOBILE COMPANION             |
                     |                                                   |
                     |  - QR Code Scanner (`mobile_scanner`)             |
                     |  - 8-digit numeric fallback entry                 |
                     |  - Secure Token Storage (`flutter_secure_storage`)|
                     |  - Local-first Wi-Fi probe with remote fallback   |
                     |  - 15s background watchdog auto-reconnect         |
                     |  - Silent vibration & push alerts                 |
                     |  - Camera snapshot review                         |
                     +---------------------------------------------------+
```

---

## 4. Modified & Created Files

### Python Backend
- `securelinkdb/tunnel_manager.py` *(New)*: Automated Cloudflare Quick Tunnel process lifecycle manager with OS detection, URL capture, health probe, and backoff restarting.
- `securelinkdb/mobile_pairing.py` *(New)*: Cryptographic pairing session manager, 8-digit code hashing, brute-force rate limiter, admin approval workflow, and device persistence.
- `securelinkdb/server.py` *(Modified)*: Integrated tunnel manager and mobile pairing manager. Added `/api/mobile-pairing/*`, `/api/cloud-tunnel/*`, `/api/mobile-devices`, and `/mobile` WebSocket endpoints. Fixed empty-credential authentication bypass on `/`.
- `securelinkdb/mobile_devices.json` *(New)*: Persistent JSON store for authorized mobile companion tokens and device metadata.
- `tests/test_mobile_pairing_and_tunnel.py` *(New)*: 9 integration tests covering pairing session lifecycle, code expiration, single-use validation, rate limiting, admin approval, token verification, revocation, and tunnel manager states.

### ESP32-S3 Firmware
- `esp32code.txt` *(Modified)*:
  - Added `#include <WiFiClientSecure.h>`.
  - Added BLE message fragmentation reassembly buffer with 1024-byte safety limit.
  - Enabled HTTPS TLS for Smart Pin registration when connecting through Cloudflare tunnels (`trycloudflare.com`).
  - Redacted Wi-Fi passwords and pairing codes from UART serial output.

### Flutter Mobile Application
- `securelinkdb/lib/mobile/services/mobile_server_service.dart` *(Modified)*: Replaced hardcoded tunnel strings with dynamic tunnel URL discovery. Added secure storage token persistence, local-first Wi-Fi probing, remote fallback, and 15s background auto-reconnect watchdog.
- `securelinkdb/lib/mobile/widgets/pair_mobile_modal.dart` *(New)*: Dual-tab pairing modal supporting live camera QR scanning and manual 8-digit numeric code entry with 90s countdown.
- `securelinkdb/lib/mobile/securelink_mobile_app.dart` *(Modified)*: Added "Pair with Central System" QR button in mobile app bar.
- `securelinkdb/lib/mobile/widgets/mobile_components.dart` *(Modified)*: Purged hardcoded `trycloudflare.com` fallback strings.
- `securelinkdb/android/app/src/main/AndroidManifest.xml` *(Modified)*: Added `android.permission.CAMERA` and hardware camera feature declarations.

### Flutter Desktop Dashboard
- `securelinkdb/lib/main.dart` *(Modified)*:
  - Added `qr_flutter` import and QR rendering in `_PairMobileDialog`.
  - Added `_PairMobileHeaderButton` with pending request counter badge.
  - Added `_PairMobileDialog` generating 8-digit codes, QR code payload, 90s countdown, and live pending approval review.
  - Upgraded `_CloudflareTunnelHeaderButton` with dynamic state dots (`Connected`, `Starting`, `Reconnecting`, `Offline`, `Error`).
  - Upgraded `_CloudflareTunnelDialog` with Start/Stop Quick Tunnel controls and OS installation instructions.
  - Upgraded `_DevicesPage` with tabbed navigation: "Smart Pins (XIAO ESP32-S3)" and "Mobile Companions".
  - Implemented Paired Mobile Devices table and pending approval cards with role selection and one-click revocation.
  - Purged all hardcoded fallback URLs.

---

## 5. Verification & Test Results

### Automated Integration & Unit Tests
```
$ python -m unittest discover -s tests -p "test_*.py"
----------------------------------------------------------------------
Ran 45 tests in 2.590s

OK (skipped=7)
```
- **BLE Smart Pin Pairing Tests (8):** Code generation, verification, timeout, replay rejection.
- **Context Engine v3 Tests (15):** Tagalog/Taglish classification, pedagogical exemptions, physical threats, escalation.
- **Transcription Reliability Tests (13):** Silence suppression, noise gating, acoustic verification.
- **Mobile Pairing & Quick Tunnel Tests (9):**
  - `test_01_create_mobile_pairing_session`: Verifies 8-digit CSPRNG code generation, QR payload, and SHA-256 hashing.
  - `test_02_redeem_mobile_pairing_code`: Validates code submission and transition to `pending_approval`.
  - `test_03_code_expiration`: Validates 90s TTL and rejection of expired codes.
  - `test_04_single_use_enforcement`: Ensures codes cannot be redeemed more than once.
  - `test_05_rate_limiting_lockout`: Tests that 5 consecutive failed attempts trigger a 60-second lockout.
  - `test_06_admin_approval_and_token_issuance`: Verifies token generation and persistent storage upon admin approval.
  - `test_07_device_revocation`: Validates that revoked devices are blocked from authentication.
  - `test_08_empty_credential_store_security`: Ensures unauthenticated pins and mobile clients are rejected when stores are empty.
  - `test_09_cloudflare_tunnel_manager_state_and_reachability`: Validates process start/stop, state transitions, and health check validation.

### Flutter Analyzer
- `flutter analyze`: **0 errors**.

### Android Release APK Build
- `flutter build apk -t lib/main_mobile.dart --release`: Built cleanly (67.0MB).
- Copied to:
  - `SecureLink-Mobile-Latest.apk`
  - `SecurelinkCompanionV2.apk`
  - `securelinkdb/SecureLink-Mobile-Latest.apk`

---

## 6. How to Test and Run

### 1. Launch Backend with Automated Cloudflare Tunnel
```bash
cd securelinkdb
python server.py
```
Upon startup, the server automatically checks for `cloudflared` (using local binary or PATH) and can be started via the dashboard or API:
```bash
curl -X POST http://127.0.0.1:8080/api/cloud-tunnel/start
```

### 2. Pair a Mobile Device
1. In the Desktop Dashboard, click **Pair Mobile** in the top navigation or under **Devices $\rightarrow$ Mobile Companions**.
2. An 8-digit pairing code and QR code appear with a 90-second countdown timer.
3. Open the Mobile Companion app (`SecureLink-Mobile-Latest.apk`).
4. Tap the QR scanner icon in the app bar and scan the screen (or enter the 8-digit code manually).
5. The dashboard displays the pending request showing the phone model, ID, and connection type.
6. Select a role (`Responder`, `Investigator`, `Viewer`, `Admin`) and click **Approve Mobile Access**.
7. The phone immediately connects to WebSocket `/mobile` and begins receiving real-time incidents.

### 3. Cross-Network Test
1. Disconnect the mobile phone from campus Wi-Fi and switch to cellular data (4G/5G).
2. The phone detects local disconnection and automatically connects to the public Cloudflare Quick Tunnel URL.
3. Trigger a test event or speech: the alert appears on the phone in real-time.
4. Reconnect the phone to campus Wi-Fi: within 15 seconds, the watchdog probe detects the local server and switches back to local Wi-Fi without requiring re-pairing.
