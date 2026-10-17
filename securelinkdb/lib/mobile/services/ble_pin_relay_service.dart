import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
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
  StreamSubscription? _txSubscription;
  StreamSubscription? _connectionStateSub;

  WebSocketChannel? _relayWsChannel;
  bool _isRelayWsConnected = false;

  BleRelayState _state = BleRelayState.disconnected;
  String _statusMessage = 'BLE Bridge Disconnected';
  String _pinnedDeviceId = '';
  int _relayedBytesTotal = 0;
  int _relayedPacketsTotal = 0;

  List<ScanResult> _scanResults = [];
  bool _isScanning = false;

  // Getters
  BleRelayState get state => _state;
  bool get isConnected => _connectedDevice != null && _state != BleRelayState.disconnected;
  bool get isScanning => _isScanning;
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

      // Scan broadly without restrictive UUID filters so all Android/iOS OEM stacks discover the device
      await FlutterBluePlus.startScan(
        timeout: timeout,
        androidUsesFineLocation: true,
      );

      await Future.delayed(timeout);
      await FlutterBluePlus.stopScan();
      scanSub.cancel();
    } catch (e) {
      debugPrint('[BLE] Scan error: $e');
      _statusMessage = 'Scan error: $e';
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
        if (s.uuid.toString().toLowerCase() == nordicUartServiceUuid) {
          for (final c in s.characteristics) {
            final uuid = c.uuid.toString().toLowerCase();
            if (uuid == nordicUartTxUuid) foundTx = c;
            if (uuid == nordicUartRxUuid) foundRx = c;
          }
        }
      }

      if (foundTx == null) {
        throw Exception('Nordic UART TX characteristic not found on device');
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

      // Ensure relay WebSocket is connected to Central System
      _ensureRelayWebSocket();

      return true;
    } catch (e) {
      debugPrint('[BLE] Connection error: $e');
      _statusMessage = 'Failed to connect: $e';
      _handleBleDisconnect();
      return false;
    }
  }

  void _ensureRelayWebSocket() {
    if (_isRelayWsConnected && _relayWsChannel != null) return;

    try {
      final s = MobileServerService();
      final targetId = _pinnedDeviceId.isNotEmpty ? _pinnedDeviceId : 'PIN-BLE';
      final uri = s.getPinWsUri(targetId);
      debugPrint('[BLE-RELAY] Connecting Pin WebSocket to: $uri');
      _relayWsChannel = WebSocketChannel.connect(uri);

      _relayWsChannel!.ready.then((_) {
        _isRelayWsConnected = true;
        debugPrint('[BLE-RELAY] Pin WebSocket connected for $targetId!');
      }).catchError((e) {
        _isRelayWsConnected = false;
        debugPrint('[BLE-RELAY] Pin WebSocket connection refused: $e');
      });

      _relayWsChannel!.stream.listen(
        (msg) {
          debugPrint('[BLE-RELAY] Server response: $msg');
        },
        onError: (err) {
          _isRelayWsConnected = false;
        },
        onDone: () {
          _isRelayWsConnected = false;
        },
      );
    } catch (e) {
      debugPrint('[BLE-RELAY] Socket setup error: $e');
    }
  }

  void _handleIncomingBleData(List<int> bytes) {
    if (bytes.isEmpty) return;

    // Check if packet is a text command (e.g. STREAM_END or PING:...)
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

    _ensureRelayWebSocket();

    if (isAsciiText) {
      debugPrint('[BLE-RELAY] Forwarding Command: $textMsg');
      if (textMsg.startsWith('STREAM_END') || textMsg.startsWith('STREAM_STOP')) {
        _state = BleRelayState.connected;
        _statusMessage = 'Relayed Incident Audio Stream Complete';
        notifyListeners();
      } else if (textMsg.startsWith('PING:')) {
        final parts = textMsg.split(':');
        int? rssi;
        int? batt;
        int? mv;
        if (parts.length >= 2) rssi = int.tryParse(parts[1]);
        if (parts.length >= 3) batt = int.tryParse(parts[2]);
        if (parts.length >= 4) mv = int.tryParse(parts[3]);
        if (_pinnedDeviceId.isNotEmpty) {
          MobileServerService().updatePinTelemetryFromBle(
            pinId: _pinnedDeviceId,
            rssi: rssi ?? -55,
            battery: batt,
            batteryMv: mv,
          );
        }
      }
      try {
        _relayWsChannel?.sink.add(textMsg);
      } catch (e) {
        debugPrint('[BLE-RELAY] Error sending text to CS: $e');
      }
    } else {
      // Binary PCM Audio chunk from ESP32
      _relayedBytesTotal += bytes.length;
      _relayedPacketsTotal++;
      _state = BleRelayState.streaming;
      _statusMessage = 'Relaying Voice to Server (${(_relayedBytesTotal / 1024).toStringAsFixed(1)} KB)';
      notifyListeners();

      try {
        _relayWsChannel?.sink.add(Uint8List.fromList(bytes));
      } catch (e) {
        debugPrint('[BLE-RELAY] Error forwarding audio to CS: $e');
      }
    }
  }

  void _handleBleDisconnect() {
    _txSubscription?.cancel();
    _connectionStateSub?.cancel();
    _connectedDevice = null;
    _txCharacteristic = null;
    _rxCharacteristic = null;
    _relayWsChannel?.sink.close();
    _relayWsChannel = null;
    _isRelayWsConnected = false;
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
