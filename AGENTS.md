# SecureLink development guide

## Project map

- `securelinkdb/` is the Flutter package and Python backend directory. `lib/main.dart` runs the Central System dashboard and supervises the local backend. `lib/main_mobile.dart` starts the companion app. Mobile screens, models, BLE relay, and server connectivity live under `lib/mobile/`.
- `server.py` owns FastAPI routes, device presence, and audio processing. `usb_manager.py` handles COM discovery, authentication, heartbeats, and framed PCM audio on a worker thread. `mobile_pairing.py` handles companion approval and revocation. `tunnel_manager.py` manages the optional Cloudflare Quick Tunnel.
- `context_engine.py` evaluates transcript context and device-specific escalation after Faster-Whisper transcription. The pipeline also uses NumPy/SciPy, denoising (including optional NSNet2/ONNX), and a local TagalogBERT classifier. The root `esp32code.txt` is Arduino C++ firmware for the XIAO ESP32-S3 Sense. It uses I2S, Speex VAD, LittleFS, and USB serial. Check the running firmware before assuming that Wi-Fi or BLE flows described in older phase notes are active.
- Root `tests/` covers transcription, context scoring, pairing, and tunnels. `securelinkdb/tests/` covers USB, battery/VAD telemetry, provisioning, and backend lifecycle. `changes/` records historical decisions. Use the current source and tests to verify them.

## Contracts and local state

- FastAPI serves HTTP and WebSockets on TCP 8080, with optional LAN discovery on UDP 8888. WebSocket routes are `/ui` for the dashboard, `/mobile` for the companion, and `/` for network-connected pins. See the route decorators in `server.py` for the REST contract, including `/health`, `/api/system/info`, `/api/usb/*`, `/api/devices*`, `/api/pin/*`, `/api/provision-pin`, `/api/pairing-code/*`, `/api/mobile-pairing/*`, `/api/checkpoints*`, and `/api/cloud-tunnel*`.
- Persistence is file-based. Pin and mobile registrations, active PIN pairing codes, checkpoints, and tunnel settings use `device_credentials.json`, `mobile_devices.json`, `active_pairing_codes.json`, `checkpoints.json`, and `tunnel_config.json`. Audio and snapshots live under `securelinkdb/recordings/`. Live sockets, presence, and mobile pairing sessions are process-local. Checkpoint paths depend on the backend working directory.
- Preserve REST payloads, WebSocket event keys, stored JSON compatibility, and firmware framing across changes. Keep liveness, registration, and battery/VAD state distinct. The backend prefers authenticated USB over direct WebSocket and BLE relay. Preserve pairing approval/revocation behavior and transcription quality gates before incident escalation.

## Run, build, and test

- From `securelinkdb/`, use a Python virtual environment and install runtime dependencies with `python -m pip install -r requirements.txt pyserial scipy`. The last two are direct imports missing from the manifest. Add `onnxruntime` for NSNet2 and `httpx` for the HTTP tests. Verify model availability separately because weights are ignored by Git. Start the backend with `python server.py` and check `http://127.0.0.1:8080/health`.
- From `securelinkdb/`, run `flutter pub get` with a Flutter SDK satisfying the Dart constraint in `pubspec.yaml`. Use `flutter run -d windows` for the dashboard and `flutter run -d <device-id> -t lib/main_mobile.dart` for the companion. Windows builds require the Visual Studio C++ desktop toolchain. Android builds use the Android SDK and Java 17.
- Build with `flutter build windows --release` or `flutter build apk -t lib/main_mobile.dart --release`. The Android output is `build/app/outputs/flutter-apk/app-release.apk`. The Windows launcher expects the Release runner. Compile `windows_installer.iss` with Inno Setup after building the runner. Verify backend availability on the target computer because the installer script bundles the Flutter runner and its assets.
- Run `flutter analyze` from `securelinkdb/` after Dart changes. From the repository root, run both Python suites with `python -m unittest discover -s tests -p "test_*.py"` and `python -m unittest discover -s securelinkdb/tests -t . -p "test_*.py"`, or select the relevant modules. Tests importing `server.py` may initialize models and touch local data. Use disposable stores and mocked hardware for integration tests. Some transcription tests skip when local WAV fixtures are absent.

## Working conventions

- Investigate the root cause before editing. Trace the affected path from firmware, backend, or client to its normal entry point and reproduce the failure where feasible.
- Preserve existing behavior, reuse the owning module or service, and keep edits scoped. Follow nearby conventions and `analysis_options.yaml`. Use Dart naming conventions and typed models where the surrounding mobile code does, Python snake_case and existing type hints, and the existing firmware constants and protocol names.
- Keep credentials, tokens, pairing codes, Wi-Fi passwords, and incident recordings out of new files, logs, test fixtures, and summaries. Treat existing local state as user data.
- Run relevant tests after implementation. Summarize the changes, verification results and any gaps, and provide manual testing steps for the affected workflow. For USB changes, include a real PIN check for authentication, heartbeat, unplug/replug, and reconnect during or after audio.

## Engineering Standard: Correctness and Regression Prevention

Our primary development objective is reliable, complete, and maintainable implementations.

Quality takes priority over minimizing quota consumption, execution time, or reasoning effort. However, avoid unnecessary work outside the requested scope.

### Before implementation

- Understand the requested behavior and relevant product requirements.
- Inspect the affected code and its dependencies.
- Identify potential regressions and edge cases.
- Establish clear acceptance criteria.
- Investigate root causes rather than assuming them.

### During implementation

- Resolve the underlying problem rather than masking symptoms.
- Preserve existing functionality.
- Follow established project architecture and conventions.
- Avoid temporary workarounds and unnecessary abstractions.
- Consider interactions between Flutter, backend services, firmware, and communication protocols.

### After implementation

- Run relevant automated tests and static analysis.
- Add regression tests for discovered bugs where practical.
- Verify normal behavior, edge cases, and failure scenarios.
- Review your own changes for unintended side effects.
- Fix discovered regressions before handing the implementation back to me.
- Verify runtime behavior whenever the development environment permits it.

### Definition of done

An implementation is not complete merely because the code compiles.

Before declaring completion, report:
- What was implemented.
- What was tested.
- Which tests passed or failed.
- Which existing behaviors were checked for regressions.
- What remains unverified.
- What requires manual or physical hardware testing.

Never claim that functionality is fully working without supporting evidence.

### Recurring bugs

If a previous fix failed, do not blindly attempt another patch. Reassess the underlying assumptions, inspect the complete relevant execution path, and investigate why the previous solution failed.

The goal is to minimize repeated debugging cycles and deliver reliable implementations, even when doing so requires substantial reasoning and usage quota.
