import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'mobile_server_service.dart';

enum BleRelayState {
  disconnected,
  scanning,
  connecting,
  connected,
  streaming,
}

/// BLE Audio Bridge & Cellular Data Relay Service
///
class BleSendResult {
  final bool success;
  final String? errorCode;
  final String? errorMessage;
  final int negotiatedMtu;
  final int payloadLength;
  final int totalChunks;
  final int? failedChunkIndex;

  const BleSendResult({
    required this.success,
    this.errorCode,
    this.errorMessage,
    this.negotiatedMtu = 23,
    this.payloadLength = 0,
    this.totalChunks = 0,
    this.failedChunkIndex,
  });

  factory BleSendResult.ok({
    required int negotiatedMtu,
    required int payloadLength,
    required int totalChunks,
  }) => BleSendResult(
    success: true,
    negotiatedMtu: negotiatedMtu,
    payloadLength: payloadLength,
    totalChunks: totalChunks,
  );

  factory BleSendResult.error({
    required String code,
    required String message,
    int negotiatedMtu = 23,
    int payloadLength = 0,
    int totalChunks = 0,
    int? failedChunkIndex,
  }) => BleSendResult(
    success: false,
    errorCode: code,
    errorMessage: message,
    negotiatedMtu: negotiatedMtu,
    payloadLength: payloadLength,
    totalChunks: totalChunks,
    failedChunkIndex: failedChunkIndex,
  );
}

/// Connects to Seeed Studio XIAO ESP32S3 smart pins over Nordic UART Service (NUS).
/// When enterprise Wi-Fi or AP client isolation blocks the ESP32 from reaching the server,
/// this service receives raw 16kHz PCM audio chunks over BLE and transparently forwards
/// them through the phone's mobile data (4G/5G) or Wi-Fi via Cloudflare Tunnel / WSS to Central System.
class BlePinRelayService extends ChangeNotifier {
  static final BlePinRelayService _instance = BlePinRelayService._internal();
  factory BlePinRelayService() => _instance;
  BlePinRelayService._internal();

  // Nordic UART Service (NUS) Standard UUIDs
  static const String nordicUartServiceUuid = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
  static const String nordicUartRxUuid = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
  static const String nordicUartTxUuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";

  BluetoothDevice? _connectedDevice;
  BluetoothCharacteristic? _txCharacteristic;
  BluetoothCharacteristic? _rxCharacteristic;
  BleSendResult? lastSendResult;
  StreamSubscription? _txSubscription;
  StreamSubscription? _connectionStateSub;

  BleRelayState _state = BleRelayState.disconnected;
  String _statusMessage = 'BLE Bridge Disconnected';
  String _pinnedDeviceId = '';
  int _relayedBytesTotal = 0;
  int _relayedPacketsTotal = 0;

  // Snapshot assembly state over BLE
  bool _isReceivingSnapshot = false;
  int _expectedSnapshotBytes = 0;
  final BytesBuilder _snapshotBuilder = BytesBuilder();
  Timer? _snapshotTimeoutTimer;

  List<ScanResult> _scanResults = [];
  bool _isScanning = false;

  // Provisioning stream & device metadata
  final StreamController<Map<String, dynamic>> _provisioningEventsController =
      StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get provisioningEvents => _provisioningEventsController.stream;

  Map<String, dynamic>? _lastDeviceInfo;
  Map<String, dynamic>? get lastDeviceInfo => _lastDeviceInfo;

  // Getters
  BleRelayState get state => _state;
  bool get isConnected => _connectedDevice != null && _state != BleRelayState.disconnected;
  bool get isScanning => _isScanning;
  bool get isReceivingSnapshot => _isReceivingSnapshot;
  String get statusMessage => _statusMessage;
  String get pinnedDeviceId => _pinnedDeviceId;
  int get relayedBytesTotal => _relayedBytesTotal;
  int get relayedPacketsTotal => _relayedPacketsTotal;
  List<ScanResult> get scanResults => List.unmodifiable(_scanResults);
  String get formattedRelayedData {
    if (_relayedBytesTotal < 1024) return '$_relayedBytesTotal B';
    if (_relayedBytesTotal < 1024 * 1024) return '${(_relayedBytesTotal / 1024).toStringAsFixed(1)} KB';
    return '${(_relayedBytesTotal / (1024 * 1024)).toStringAsFixed(2)} MB';
  }
  BluetoothDevice? get connectedDevice => _connectedDevice;

  void setPinnedDeviceId(String id) {
    _pinnedDeviceId = id.trim().toUpperCase();
    notifyListeners();
  }

  // --- Scan for SecureLink Pins ---
  Future<void> startScan({Duration timeout = const Duration(seconds: 6)}) async {
    if (_isScanning) return;
    _scanResults.clear();
    _isScanning = true;
    _state = BleRelayState.scanning;
    _statusMessage = 'Scanning for SecureLink BLE pins...';
    notifyListeners();

    try {
      if (await FlutterBluePlus.isSupported == false) {
        _statusMessage = 'BLE not supported on this device';
        _isScanning = false;
        _state = BleRelayState.disconnected;
        notifyListeners();
        return;
      }

      // Check if Bluetooth adapter is turned on (Android can auto-prompt to turn on)
      if (Platform.isAndroid) {
        try {
          if (await FlutterBluePlus.adapterState.first != BluetoothAdapterState.on) {
            await FlutterBluePlus.turnOn();
          }
        } catch (_) {}
      }

      final scanSub = FlutterBluePlus.scanResults.listen((results) {
        _scanResults = results.where((r) {
          final advName = r.advertisementData.advName.toLowerCase();
          final devName = r.device.platformName.toLowerCase();
          final hasUart = r.advertisementData.serviceUuids.any(
            (u) => u.toString().toLowerCase() == nordicUartServiceUuid,
          );
          return advName.contains('securelink') ||
                 devName.contains('securelink') ||
                 advName.contains('pin') ||
                 devName.contains('pin') ||
                 hasUart;
        }).toList();
        notifyListeners();
      });

      // androidUsesFineLocation: false honors Android 12+ neverForLocation in manifest,
      // preventing "need location permission" errors!
      await FlutterBluePlus.startScan(
        timeout: timeout,
        androidUsesFineLocation: false,
      );

      await Future.delayed(timeout);
      await FlutterBluePlus.stopScan();
      scanSub.cancel();
    } catch (e) {
      debugPrint('[BLE] Scan error: $e');
      final errStr = e.toString().toLowerCase();
      if (errStr.contains('permission') || errStr.contains('location')) {
        _statusMessage = 'Permission notice: Please allow Nearby Devices / Location in Settings.';
      } else {
        _statusMessage = 'Scan notice: $e';
      }
    } finally {
      _isScanning = false;
      if (_connectedDevice == null) {
        _state = BleRelayState.disconnected;
      }
      notifyListeners();
    }
  }

  Future<void> stopScan() async {
    try {
      await FlutterBluePlus.stopScan();
    } catch (_) {}
    _isScanning = false;
    notifyListeners();
  }

  Future<bool> connectToDevice(BluetoothDevice device, MobileServerService serverService, {String? pinId}) =>
      connectToPin(device, pinId: pinId);

  // --- Connect to Pin & Establish Relay ---
  Future<bool> connectToPin(BluetoothDevice device, {String? pinId}) async {
    if (pinId != null && pinId.isNotEmpty) {
      _pinnedDeviceId = pinId.trim().toUpperCase();
    } else {
      String name = device.platformName.trim();
      if (name.isEmpty) name = device.advName.trim();
      if (name.isEmpty) {
        final clean = device.remoteId.str.replaceAll(':', '').toUpperCase();
        name = 'PIN-${clean.length > 4 ? clean.substring(clean.length - 4) : clean}';
      }
      _pinnedDeviceId = name.toUpperCase();
    }

    _state = BleRelayState.connecting;
    _statusMessage = 'Connecting to ${device.platformName.isEmpty ? device.remoteId.str : device.platformName}...';
    notifyListeners();

    try {
      await device.connect(
        license: License.nonprofit,
        timeout: const Duration(seconds: 10),
        mtu: 512,
        autoConnect: false,
      );
      _connectedDevice = device;

      // Negotiate maximum MTU (512 bytes) for high-throughput 16kHz PCM audio
      try {
        await device.requestMtu(512);
      } catch (e) {
        debugPrint('[BLE] MTU request error: $e');
      }

      // Discover Services & find Nordic UART characteristics
      final services = await device.discoverServices();
      BluetoothCharacteristic? foundTx;
      BluetoothCharacteristic? foundRx;

      for (final s in services) {
        if (_matchUuid(s.uuid, nordicUartServiceUuid)) {
          for (final c in s.characteristics) {
            if (_matchUuid(c.uuid, nordicUartTxUuid)) foundTx = c;
            if (_matchUuid(c.uuid, nordicUartRxUuid)) foundRx = c;
          }
        }
      }

      // Fallback: search across all discovered services
      if (foundTx == null || foundRx == null) {
        for (final s in services) {
          for (final c in s.characteristics) {
            if (foundTx == null && _matchUuid(c.uuid, nordicUartTxUuid)) foundTx = c;
            if (foundRx == null && _matchUuid(c.uuid, nordicUartRxUuid)) foundRx = c;
          }
        }
      }

      if (foundTx == null) {
        throw Exception('Nordic UART TX characteristic not found on device');
      }
      if (foundRx == null) {
        throw Exception('Nordic UART RX characteristic not found on device');
      }

      _txCharacteristic = foundTx;
      _rxCharacteristic = foundRx;

      // Enable BLE Notifications
      await _txCharacteristic!.setNotifyValue(true);
      _txSubscription?.cancel();
      _txSubscription = _txCharacteristic!.onValueReceived.listen(_handleIncomingBleData);

      // Listen for connection state changes
      _connectionStateSub?.cancel();
      _connectionStateSub = device.connectionState.listen((connState) {
        if (connState == BluetoothConnectionState.disconnected) {
          _handleBleDisconnect();
        }
      });

      _state = BleRelayState.connected;
      _statusMessage = 'BLE Audio Bridge ACTIVE with $_pinnedDeviceId';
      notifyListeners();

      // Notify MobileServerService of BLE connection presence
      MobileServerService().reportBleProximity(
        pinId: _pinnedDeviceId,
        rssi: -50,
      );

      return true;
    } catch (e) {
      debugPrint('[BLE] Connection error: $e');
      _statusMessage = 'Failed to connect: $e';
      _handleBleDisconnect();
      return false;
    }
  }

  void _handleIncomingBleData(List<int> bytes) {
    if (bytes.isEmpty) return;

    // 1. If currently in Snapshot Assembly mode, treat incoming packets as binary JPEG slices
    if (_isReceivingSnapshot) {
      _snapshotTimeoutTimer?.cancel();
      _snapshotBuilder.add(bytes);
      final currentLen = _snapshotBuilder.length;
      debugPrint('[BLE-SNAP] Receiving image chunk: ${bytes.length} bytes ($currentLen/$_expectedSnapshotBytes)');

      _statusMessage = 'Receiving BLE Snapshot ($currentLen/$_expectedSnapshotBytes B)';
      notifyListeners();

      if (currentLen >= _expectedSnapshotBytes) {
        final completedJpeg = _snapshotBuilder.takeBytes();
        _isReceivingSnapshot = false;
        _expectedSnapshotBytes = 0;
        debugPrint('[BLE-SNAP] Snapshot fully assembled (${completedJpeg.length} bytes). Relaying through Mobile Companion session...');

        try {
          MobileServerService().relayBleSnapshot(_pinnedDeviceId, completedJpeg);
          debugPrint('[BLE-SNAP] Completed JPEG relayed over Mobile Companion WebSocket!');
          _statusMessage = 'Relayed Incident Snapshot (${(completedJpeg.length / 1024).toStringAsFixed(1)} KB)';
          notifyListeners();
        } catch (e) {
          debugPrint('[BLE-SNAP] Error relaying JPEG to server: $e');
        }
      } else {
        // Set safety timeout in case BLE packets drop mid-transfer
        _snapshotTimeoutTimer = Timer(const Duration(seconds: 8), () {
          if (_isReceivingSnapshot) {
            debugPrint('[BLE-SNAP] Snapshot timeout reached. Resetting snapshot buffer.');
            _isReceivingSnapshot = false;
            _expectedSnapshotBytes = 0;
            _snapshotBuilder.clear();
            notifyListeners();
          }
        });
      }
      return;
    }

    // 2. Check if packet is a JSON message (Onboarding / Provisioning protocol)
    try {
      final decoded = utf8.decode(bytes);
      final trimmed = decoded.trim();
      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        final parsed = jsonDecode(trimmed);
        if (parsed is Map<String, dynamic> && parsed.containsKey('type')) {
          _handleBleJsonMessage(parsed);
          return;
        }
      }
    } catch (_) {}

    // 3. Check if packet is a text command (e.g. SNAP:<len>, STREAM_END, PING:...)
    bool isAsciiText = false;
    String textMsg = '';
    try {
      textMsg = utf8.decode(bytes);
      if (textMsg.startsWith('STREAM_END') ||
          textMsg.startsWith('STREAM_STOP') ||
          textMsg.startsWith('PING:') ||
          textMsg.startsWith('SNAP:')) {
        isAsciiText = true;
      }
    } catch (_) {}

    if (isAsciiText) {
      debugPrint('[BLE-RELAY] Relaying Command: $textMsg');
      if (textMsg.startsWith('SNAP:')) {
        // Enter Snapshot Receiving Mode
        final declaredLen = int.tryParse(textMsg.substring(5).trim()) ?? 0;
        _isReceivingSnapshot = true;
        _expectedSnapshotBytes = declaredLen;
        _snapshotBuilder.clear();
        debugPrint('[BLE-SNAP] Switched to Snapshot Mode! Expected: $declaredLen bytes');
        _statusMessage = 'Receiving Camera Snapshot ($declaredLen B)...';
        notifyListeners();

        // Forward SNAP command through Mobile Companion session
        MobileServerService().relayBleCommand(_pinnedDeviceId, textMsg);

        // Set safety timeout (8 seconds)
        _snapshotTimeoutTimer?.cancel();
        _snapshotTimeoutTimer = Timer(const Duration(seconds: 8), () {
          if (_isReceivingSnapshot) {
            debugPrint('[BLE-SNAP] Timeout waiting for snapshot bytes.');
            _isReceivingSnapshot = false;
            _expectedSnapshotBytes = 0;
            _snapshotBuilder.clear();
            notifyListeners();
          }
        });
        return;
      } else if (textMsg.startsWith('STREAM_END') || textMsg.startsWith('STREAM_STOP')) {
        _state = BleRelayState.connected;
        _statusMessage = 'Relayed Incident Audio Stream Complete';
        notifyListeners();
        MobileServerService().relayBleCommand(_pinnedDeviceId, textMsg);
      } else if (textMsg.startsWith('PING:')) {
        final parts = textMsg.split(':');
        int? rssi;
        int? batt;
        int? mv;
        if (parts.length >= 2) rssi = int.tryParse(parts[1]);
        if (parts.length >= 3) batt = int.tryParse(parts[2]);
        if (parts.length >= 4) mv = int.tryParse(parts[3]);
        if (_pinnedDeviceId.isNotEmpty) {
          MobileServerService().reportBleProximity(
            pinId: _pinnedDeviceId,
            rssi: rssi ?? -55,
            battery: batt,
            batteryMv: mv,
          );
        }
        MobileServerService().relayBleCommand(_pinnedDeviceId, textMsg);
      } else {
        MobileServerService().relayBleCommand(_pinnedDeviceId, textMsg);
      }
    } else {
      // Binary PCM Audio chunk from ESP32
      _relayedBytesTotal += bytes.length;
      _relayedPacketsTotal++;
      _state = BleRelayState.streaming;
      _statusMessage = 'Relaying Voice to Server (${(_relayedBytesTotal / 1024).toStringAsFixed(1)} KB)';
      notifyListeners();

      MobileServerService().relayBleAudio(_pinnedDeviceId, bytes);
    }
  }

  void _handleBleDisconnect() {
    _txSubscription?.cancel();
    _connectionStateSub?.cancel();
    _snapshotTimeoutTimer?.cancel();
    _isReceivingSnapshot = false;
    _expectedSnapshotBytes = 0;
    _snapshotBuilder.clear();
    _connectedDevice = null;
    _txCharacteristic = null;
    _rxCharacteristic = null;
    if (_pinnedDeviceId.isNotEmpty) {
      MobileServerService().reportBleDisconnected(_pinnedDeviceId);
    }
    _state = BleRelayState.disconnected;
    _statusMessage = 'BLE Bridge Disconnected';
    _pinnedDeviceId = '';
    notifyListeners();
  }

  Future<void> disconnect() async {
    try {
      await _connectedDevice?.disconnect();
    } catch (_) {}
    _handleBleDisconnect();
  }

  void _handleBleJsonMessage(Map<String, dynamic> msg) {
    debugPrint('[BLE-JSON] Received from pin: $msg');
    final type = msg['type'];
    if (type == 'device_info') {
      _lastDeviceInfo = msg;
      if (msg['device_id'] != null) {
        _pinnedDeviceId = msg['device_id'].toString().toUpperCase();
      }
    }
    _provisioningEventsController.add(msg);
    notifyListeners();
  }

  bool _matchUuid(dynamic guidObj, String target) {
    final s = guidObj.toString().toLowerCase().replaceAll('-', '');
    final t = target.toLowerCase().replaceAll('-', '');
    return s == t || (s.length >= 8 && t.length >= 8 && s.startsWith(t.substring(0, 8)));
  }

  Future<BleSendResult> sendBleJsonDetailed(Map<String, dynamic> jsonMap) async {
    if (_connectedDevice == null) {
      final res = BleSendResult.error(
        code: 'ERR_BLE_NOT_CONNECTED',
        message: 'Smart Pin is not connected over BLE.',
      );
      lastSendResult = res;
      return res;
    }
    if (_rxCharacteristic == null) {
      final res = BleSendResult.error(
        code: 'ERR_RX_CHAR_NOT_FOUND',
        message: 'Nordic UART RX characteristic was not discovered on the device.',
      );
      lastSendResult = res;
      return res;
    }

    final c = _rxCharacteristic!;
    final canWriteWithResp = c.properties.write;
    final canWriteWithoutResp = c.properties.writeWithoutResponse;

    if (!canWriteWithResp && !canWriteWithoutResp) {
      final res = BleSendResult.error(
        code: 'ERR_UNSUPPORTED_WRITE_PROPERTY',
        message: 'RX characteristic does not support write or writeWithoutResponse.',
      );
      lastSendResult = res;
      return res;
    }

    // Respect characteristic write properties.
    // Prefer write-with-response for reliable command reception if supported, otherwise write-without-response.
    final bool withoutResp = !canWriteWithResp;

    try {
      final jsonStr = jsonEncode(jsonMap);
      final bytes = utf8.encode(jsonStr);

      // Determine chunk size based on negotiated MTU (reserve 3 bytes for ATT header)
      int maxChunk = 20;
      final currentMtu = _connectedDevice!.mtuNow;
      if (currentMtu > 23) {
        maxChunk = (currentMtu - 3).clamp(20, 240);
      }
      final totalChunks = (bytes.length + maxChunk - 1) ~/ maxChunk;

      // Security requirement: Never log raw JSON or credentials
      debugPrint('[BLE-TX] Transmitting payload (${bytes.length} bytes in $totalChunks chunks, MTU=$currentMtu, withoutResp=$withoutResp)');

      for (int i = 0, chunkIdx = 0; i < bytes.length; i += maxChunk, chunkIdx++) {
        final end = (i + maxChunk < bytes.length) ? i + maxChunk : bytes.length;
        final chunk = bytes.sublist(i, end);
        try {
          await c.write(chunk, withoutResponse: withoutResp);
        } catch (e) {
          // Only attempt alternate mode if the characteristic property explicitly supports it!
          bool alternateSucceeded = false;
          if (canWriteWithResp && canWriteWithoutResp) {
            try {
              await c.write(chunk, withoutResponse: !withoutResp);
              alternateSucceeded = true;
            } catch (_) {}
          }
          if (!alternateSucceeded) {
            final errMsg = 'BLE write failed at chunk $chunkIdx/$totalChunks (bytes $i..$end of ${bytes.length}, MTU: $currentMtu): $e';
            debugPrint('[BLE-TX] $errMsg');
            final res = BleSendResult.error(
              code: 'ERR_BLE_WRITE_FAILED',
              message: errMsg,
              negotiatedMtu: currentMtu,
              payloadLength: bytes.length,
              totalChunks: totalChunks,
              failedChunkIndex: chunkIdx,
            );
            lastSendResult = res;
            return res;
          }
        }
        if (end < bytes.length) {
          await Future.delayed(const Duration(milliseconds: 25));
        }
      }

      final res = BleSendResult.ok(
        negotiatedMtu: currentMtu,
        payloadLength: bytes.length,
        totalChunks: totalChunks,
      );
      lastSendResult = res;
      return res;
    } catch (e) {
      final res = BleSendResult.error(
        code: 'ERR_BLE_TX_EXCEPTION',
        message: 'Exception transmitting BLE payload: $e',
      );
      lastSendResult = res;
      return res;
    }
  }

  Future<bool> sendBleJson(Map<String, dynamic> jsonMap) async {
    final res = await sendBleJsonDetailed(jsonMap);
    return res.success;
  }

  Future<bool> requestDeviceInfo() async {
    return sendBleJson({'type': 'get_device_info'});
  }

  Future<BleSendResult> sendProvisioningCommand({
    required String ssid,
    required String password,
    required String pairingCode,
    required String serverUrl,
  }) async {
    return sendBleJsonDetailed({
      'type': 'provision',
      'version': 1,
      'ssid': ssid,
      'password': password,
      'pairing_code': pairingCode,
      'server_url': serverUrl,
    });
  }

  Future<void> sendCommandToPin(String cmd) async {
    if (_rxCharacteristic != null && _connectedDevice != null) {
      try {
        await _rxCharacteristic!.write(utf8.encode(cmd));
      } catch (e) {
        debugPrint('[BLE] Write error: $e');
      }
    }
  }
}
