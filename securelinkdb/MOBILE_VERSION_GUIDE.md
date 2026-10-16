# SecureLink Mobile (Phone Edition)

A dedicated, lightweight mobile version of the SecureLink IoT Student Safety platform engineered specifically for smartphones (Android & iOS).

Unlike the desktop workstation (which runs local CUDA Faster-Whisper, BERT AI classification, and forensic incident audio players), **SecureLink Mobile** focuses strictly on the 3 core operations needed on campus patrol:
1. **Pin Overviews**: View paired and active Seeed Studio XIAO ESP32S3 smart pins, connection states (VAD Armed, Standby, Streaming, Offline), signal strength (RSSI), and ping pins.
2. **Battery Life Tracker**: Real-time 200mAh LiPo battery percentages, color-coded health gauges, estimated remaining runtimes (e.g., `~7h 05m`), voltage estimations (3.7V–4.2V), and low-battery warning alerts (<20%).
3. **Wi-Fi Configuration**: View active campus Wi-Fi networks, manage saved Wi-Fi Checkpoints (SSID, Password, Server Host IP:Port), deploy Wi-Fi credentials over-the-air (OTA) to individual pins or the entire fleet, and trigger emergency captive setup portal resets (`CMD:FORGET_WIFI`).

---

## Architecture & Code Structure

```
securelinkdb/
├── lib/
│   ├── main_mobile.dart                  <-- Dedicated Mobile entrypoint
│   ├── main.dart                         <-- Adaptive launcher (auto-switches to Mobile on Android/iOS + desktop preview button)
│   └── mobile/
│       ├── models/
│       │   └── device_model.dart         <-- DeviceStatus (battery heuristics, power profiles) & WifiCheckpoint
│       ├── services/
│       │   └── mobile_server_service.dart <-- WebSocket & REST client with dynamic server IP configuration
│       ├── screens/
│       │   ├── pins_overview_screen.dart <-- Connected/paired pin cards, fleet metrics & search
│       │   ├── battery_tracker_screen.dart<-- Dedicated battery percentage, runtime & power mode tracker
│       │   └── wifi_config_screen.dart   <-- Wi-Fi Checkpoints, OTA push & hotspot portal reset
│       ├── widgets/
│       │   └── mobile_components.dart    <-- Glass cards, status pills, battery meters & server modal
│       └── securelink_mobile_app.dart    <-- Root mobile UI shell & bottom navigation
└── android/
    └── app/src/main/AndroidManifest.xml  <-- Configured with Internet permissions & cleartext LAN support
```

---

## How to Run SecureLink Mobile

### 1. Preview Directly on Desktop (Without any extra setup)
If you already have `flutter run -d windows` running:
- Look at the top-right header in the dashboard.
- Click the **Phone Icon** (`Preview Mobile Companion`).
- A phone companion screen will open allowing you to test the mobile UI, interact with paired pins, test battery states, and deploy Wi-Fi checkpoints.

### 2. Run Standalone Mobile Edition on Desktop / Emulator
You can launch the dedicated mobile edition in a phone aspect ratio (440x880):
```bash
flutter run -t lib/main_mobile.dart -d windows
```

### 3. Run on an Android Phone or Emulator
1. Connect your Android phone via USB (with USB Debugging enabled) or start an Android Emulator.
2. Run:
```bash
flutter run -t lib/main_mobile.dart -d android
```
*(Or simply `flutter run -d android` — `lib/main.dart` will automatically detect Android and boot the mobile version).*

### 4. Build Android APK
To install the standalone APK directly onto security personnel or proctor smartphones:
```bash
flutter build apk -t lib/main_mobile.dart --release
```
The output APK will be generated at `build/app/outputs/flutter-apk/app-release.apk`.

---

## Connecting to the SecureLink AI Server from Mobile
On a physical smartphone, the app connects to the AI server over campus Wi-Fi:
1. Tap the **Server Status Pill** (`ONLINE` / `CONNECT`) in the top app bar.
2. Enter the host PC's Wi-Fi IP address (e.g. `10.28.20.28` or `192.168.1.100`) and Port (`8080`).
3. Tap **Connect & Apply**. The app will immediately establish live WebSocket and REST telemetry with the campus AI server and your fleet of pins.
