# SecureLink Dashboard & Mobile Companion

SecureLink is an AI-powered campus safety and threat-detection platform designed for Philippine educational institutions. It pairs wearable smart pins (XIAO ESP32-S3 Sense) with a central system inference server (Faster-Whisper + NSNet2 + fine-tuned TagalogBERT) and mobile companion applications.

## Key Capabilities (Phase 4)

- **QR & 8-Digit Mobile Companion Pairing:**
  - One-click pairing modal on dashboard with 90-second single-use pairing codes.
  - Camera QR scanner in mobile app with instant session negotiation.
  - Mandatory administrator approval gate with assigned roles (`Responder`, `Investigator`, `Viewer`, `Admin`).
  - Cryptographic 32-byte authorization tokens stored securely via `flutter_secure_storage`.
  - Device revocation with immediate WebSocket disconnect.
- **Automated Cloudflare Quick Tunnel:**
  - Zero-domain, zero-account remote access via dynamic `trycloudflare.com` tunnels.
  - Automated process management, health validation, and exponential backoff self-healing.
  - Purged all hardcoded fallback URLs.
- **Local-First Cross-Network Synchronization:**
  - Prioritizes fast local Wi-Fi when on campus.
  - Automatically fails over to active Cloudflare Quick Tunnel when on cellular/remote networks.
  - Background 15-second watchdog seamlessly switches back to local Wi-Fi without re-pairing.
- **BLE Smart Pin Onboarding:**
  - ESP32-S3 BLE GATT provisioning without physical buttons.
  - Redacted credential logging and `WiFiClientSecure` HTTPS support.

## Project Structure

- `server.py`: FastAPI server handling ASR, TagalogBERT classification, WebSocket channels (`/ui`, `/mobile`, `/`), and REST APIs.
- `tunnel_manager.py`: Cloudflare Quick Tunnel process manager.
- `mobile_pairing.py`: Mobile companion pairing session, hashing, and rate limiting manager.
- `lib/main.dart`: Central System Flutter Desktop Dashboard.
- `lib/main_mobile.dart`: Mobile Companion Flutter Application entrypoint.
- `lib/mobile/`: Mobile Companion application codebase and widgets.
- `esp32code.txt`: XIAO ESP32-S3 firmware with microphone capture, VAD, BLE, and camera streaming.
- `changes/`: Phase-by-phase implementation and architectural records.

## Automated Testing

Run the full test suite:
```bash
python -m unittest discover -s tests -p "test_*.py"
```
