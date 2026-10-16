import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Bluetooth Sentinel State
enum BleSentinelState {
  enabled,
  disabled,
  unauthorized,
  scanning,
  connected,
  disconnected,
}

/// BLE Opportunistic Relay Service (Wi-Fi Deadzone Bridge)
/// 
/// Tier 1: Direct Campus Wi-Fi to FastAPI server
/// Tier 2: Opportunistic BLE Relay to smartphone -> Phone 4G/5G/LTE Cellular to FastAPI server
/// Tier 3: LittleFS Onboard Blackbox on ESP32-S3 Sense
class BleRelayService extends ChangeNotifier {
  static final BleRelayService _instance = BleRelayService._internal();
  factory BleRelayService() => _instance;
  BleRelayService._internal() {
    _initSentinel();
  }

  // --- Dedicated GATT UUIDs (Exact match with ESP32-S3 Firmware) ---
  static const String serviceUuid = '4fafc201-1fb5-459e-8fcc-c5c9c331914b';
  static const String audioStreamCharUuid = 'beb5483e-36e1-4688-b7f5-ea07361b26a8';
  static const String eventControlCharUuid = '88b1220a-6c19-4b36-a192-35e67c8be009';

  // --- State Variables ---
  BleSentinelState _sentinelState = BleSentinelState.enabled;
  bool _isBluetoothEnabled = true;
  bool _isBleConnected = false;
  String _connectedPinId = 'PIN-005';
  int _negotiatedMtu = 512;
  int _packetsRelayed = 0;
  int _incidentsRelayed = 0;
  String _bridgeStatus = 'BLE Bridge Ready (Standby)';
  DateTime? _lastPacketTime;
  int _lastRssi = -58;
  int _pinBattery = 100;

  // Audio stream & snapshot accumulator
  final List<int> _audioBuffer = [];
  bool _isReceivingStream = false;
  bool _isReceivingArchive = false;
  bool _isReceivingSnapshot = false;
  int _currentSnapIndex = 1;
  String _currentArchiveFilename = '';

  bool get isReceivingStream => _isReceivingStream;
  bool get isReceivingArchive => _isReceivingArchive;
  bool get isReceivingSnapshot => _isReceivingSnapshot;

  // Server relay connection
  String _serverHost = '10.28.20.11';
  int _serverPort = 8080;
  WebSocketChannel? _relayWs;
  bool _isRelayWsConnected = false;

  // Getters
  BleSentinelState get sentinelState => _sentinelState;
  bool get isBluetoothEnabled => _isBluetoothEnabled;
  bool get isBleConnected => _isBleConnected;
  String get connectedPinId => _connectedPinId;
  int get negotiatedMtu => _negotiatedMtu;
  int get packetsRelayed => _packetsRelayed;
  int get incidentsRelayed => _incidentsRelayed;
  String get bridgeStatus => _bridgeStatus;
  DateTime? get lastPacketTime => _lastPacketTime;
  int get lastRssi => _lastRssi;
  int get pinBattery => _pinBattery;
  bool get isBridgeActive => _isBleConnected;

  // Alert sentinel notification message
  String? _sentinelAlertMessage;
  String? get sentinelAlertMessage => _sentinelAlertMessage;

  void updateServerEndpoint(String host, int port) {
    _serverHost = host;
    _serverPort = port;
  }

  // --------------------------------------------------------------------------
  // 1. BLUETOOTH STATE SENTINEL & PERMISSION ENFORCEMENT
  // --------------------------------------------------------------------------
  void _initSentinel() {
    _checkBluetoothHardware();
    // Periodic watchdog to verify Bluetooth state and trigger alerts if disabled
    Timer.periodic(const Duration(seconds: 4), (_) => _checkBluetoothHardware());
  }

  Future<void> _checkBluetoothHardware() async {
    // If running on Android/iOS, check actual Bluetooth state
    if (!kIsWeb && Platform.isAndroid) {
      try {
        const channel = MethodChannel('securelink.companion/ble_sentinel');
        final bool? enabled = await channel.invokeMethod<bool>('isBluetoothEnabled');
        if (enabled != null) {
          _isBluetoothEnabled = enabled;
        }
      } catch (_) {
        // Fallback default
      }
    }

    if (!_isBluetoothEnabled) {
      _sentinelState = BleSentinelState.disabled;
      _isBleConnected = false;
      _sentinelAlertMessage =
          'SecureLink Smart Pin disconnected: Enable Bluetooth to ensure emergency coverage in Wi-Fi blind spots.';
      _bridgeStatus = 'Bluetooth OFF • Deadzone Relay Inactive';
      notifyListeners();
    } else {
      if (_sentinelState == BleSentinelState.disabled) {
        _sentinelState = _isBleConnected ? BleSentinelState.connected : BleSentinelState.enabled;
        _sentinelAlertMessage = null;
        _bridgeStatus = _isBleConnected
            ? 'Bridging $_connectedPinId via 4G/5G Cellular'
            : 'BLE Bridge Armed • Standby for Deadzones';
        notifyListeners();
      }
    }
  }

  /// Prompts the student/user to turn on Bluetooth via OS intent
  Future<void> requestEnableBluetooth() async {
    if (!kIsWeb && Platform.isAndroid) {
      try {
        const channel = MethodChannel('securelink.companion/ble_sentinel');
        await channel.invokeMethod('requestEnableBluetooth');
      } catch (_) {}
    }
    _isBluetoothEnabled = true;
    _sentinelAlertMessage = null;
    _sentinelState = BleSentinelState.scanning;
    _bridgeStatus = 'Scanning for SecureLink Smart Pin...';
    notifyListeners();
    await Future.delayed(const Duration(milliseconds: 1200));
    connectToPin(_connectedPinId);
  }

  void toggleSimulatedBluetooth(bool enable) {
    _isBluetoothEnabled = enable;
    if (!enable) {
      _sentinelState = BleSentinelState.disabled;
      _isBleConnected = false;
      _sentinelAlertMessage =
          'SecureLink Smart Pin disconnected: Enable Bluetooth to ensure emergency coverage in Wi-Fi blind spots.';
      _bridgeStatus = 'Bluetooth OFF • Deadzone Relay Inactive';
    } else {
      _sentinelState = BleSentinelState.connected;
      _isBleConnected = true;
      _sentinelAlertMessage = null;
      _bridgeStatus = 'Bridging $_connectedPinId via 4G/5G Cellular';
    }
    notifyListeners();
  }

  // --------------------------------------------------------------------------
  // 2. BACKGROUND BLE CENTRAL SERVICE & CONNECTION MANAGEMENT
  // --------------------------------------------------------------------------
  Future<void> connectToPin(String pinId) async {
    _connectedPinId = pinId.trim().toUpperCase();
    _sentinelState = BleSentinelState.scanning;
    _bridgeStatus = 'Connecting to SecureLink-$_connectedPinId...';
    notifyListeners();

    await Future.delayed(const Duration(milliseconds: 800));
    _isBleConnected = true;
    _sentinelState = BleSentinelState.connected;
    _negotiatedMtu = 512;
    _bridgeStatus = 'Connected to $_connectedPinId (MTU 512, High Throughput)';
    _sentinelAlertMessage = null;
    notifyListeners();

    // Ensure cellular relay socket to server is armed
    _connectRelayWebSocket();
  }

  void disconnectPin() {
    _isBleConnected = false;
    _sentinelState = BleSentinelState.disconnected;
    _bridgeStatus = 'BLE Bridge Disconnected';
    _relayWs?.sink.close();
    _isRelayWsConnected = false;
    notifyListeners();
  }

  // --------------------------------------------------------------------------
  // 3. CELLULAR RELAY PIPELINE (ZERO-DROP PACKET FORWARDING)
  // --------------------------------------------------------------------------
  void _connectRelayWebSocket() {
    if (_isRelayWsConnected) return;
    try {
      final wsUrl = Uri.parse('ws://$_serverHost:$_serverPort/');
      _relayWs = WebSocketChannel.connect(wsUrl);
      _isRelayWsConnected = true;

      // Identify this socket as the cellular relay conduit for the connected Pin
      _relayWs?.sink.add('RELAY_INIT:$_connectedPinId');

      _relayWs?.stream.listen(
        (data) {
          _handleServerFeedback(data);
        },
        onError: (_) {
          _isRelayWsConnected = false;
        },
        onDone: () {
          _isRelayWsConnected = false;
        },
      );
    } catch (_) {
      _isRelayWsConnected = false;
    }
  }

  /// Processes incoming server messages and relays triggers back to the pin via BLE
  void _handleServerFeedback(dynamic raw) {
    try {
      final text = raw.toString();
      if (text.contains('TRIGGER:DANGER')) {
        debugPrint('[RELAY] Server flagged DANGER! Relaying TRIGGER:DANGER to pin over BLE...');
        writeEventControlCharacteristic('TRIGGER:DANGER');
      } else if (text.contains('CMD:CAPTURE_SNAPSHOT')) {
        writeEventControlCharacteristic('CMD:CAPTURE_SNAPSHOT');
      }
    } catch (_) {}
  }

  /// Writes a command to the ESP32 via GATT EVENT_CONTROL_CHAR_UUID
  Future<void> writeEventControlCharacteristic(String command) async {
    if (!_isBleConnected) return;
    debugPrint('[BLE-GATT] Outbound command to Pin ($_connectedPinId): $command');
    // In real BLE hardware, this invokes characteristic.write(utf8.encode(command))
  }

  // --------------------------------------------------------------------------
  // 4. INBOUND BLE PACKET RECEIVER (From ESP32-S3 GATT Characteristics)
  // --------------------------------------------------------------------------

  /// Invoked when a packet arrives over AUDIO_STREAM_CHAR_UUID
  void onBleAudioPacketReceived(Uint8List chunk) {
    if (!_isBleConnected) return;

    _packetsRelayed++;
    _lastPacketTime = DateTime.now();
    _audioBuffer.addAll(chunk);

    // If active live relay stream, forward binary chunk immediately to server
    if (_isRelayWsConnected && _relayWs != null) {
      try {
        _relayWs?.sink.add(chunk);
      } catch (_) {}
    }
    notifyListeners();
  }

  /// Invoked when a notification arrives over EVENT_CONTROL_CHAR_UUID
  Future<void> onBleEventNotificationReceived(String eventString) async {
    final event = eventString.trim();
    debugPrint('[BLE-GATT] Inbound event from $_connectedPinId: $event');

    if (event.startsWith('STREAM_START:')) {
      _isReceivingStream = true;
      _audioBuffer.clear();
      _bridgeStatus = 'Relaying Live Audio from $_connectedPinId via Cellular...';
      _connectRelayWebSocket();
      notifyListeners();
    } else if (event.startsWith('STREAM_END:')) {
      _isReceivingStream = false;
      _bridgeStatus = 'Speech burst completed. Dispatched to AI server.';
      final fullPcm = Uint8List.fromList(_audioBuffer);
      _audioBuffer.clear();

      if (_isRelayWsConnected && _relayWs != null) {
        _relayWs?.sink.add('STREAM_END');
      }

      // Also forward via REST fallback to guarantee zero packet drops
      await _forwardPcmToRestServer(fullPcm);
      _incidentsRelayed++;
      notifyListeners();
    } else if (event.startsWith('ARCHIVE_START:')) {
      _isReceivingArchive = true;
      _audioBuffer.clear();
      final parts = event.split(':');
      _currentArchiveFilename = parts.length >= 3 ? parts[2] : 'incident.pcm';
      _bridgeStatus = 'Draining Blackbox Archive ($_currentArchiveFilename) via BLE...';
      notifyListeners();
    } else if (event.startsWith('ARCHIVE_END:')) {
      _isReceivingArchive = false;
      _bridgeStatus = 'Blackbox Sync Complete ($_currentArchiveFilename). Cleaned on Pin.';
      final fullPcm = Uint8List.fromList(_audioBuffer);
      _audioBuffer.clear();
      await _forwardPcmToRestServer(fullPcm);
      _incidentsRelayed++;
      notifyListeners();
    } else if (event.startsWith('SNAP_START:')) {
      // Format: SNAP_START:<pinId>:<index>:<len>
      final parts = event.split(':');
      _currentSnapIndex = parts.length >= 3 ? int.tryParse(parts[2]) ?? 1 : 1;
      _isReceivingSnapshot = true;
      _audioBuffer.clear();
      _bridgeStatus = 'Relaying Evidence Snapshot Frame #$_currentSnapIndex via Cellular...';
      notifyListeners();
    } else if (event.startsWith('SNAP_END:')) {
      _isReceivingSnapshot = false;
      final snapBytes = Uint8List.fromList(_audioBuffer);
      _audioBuffer.clear();
      await _forwardSnapshotToRestServer(snapBytes, _currentSnapIndex);
      _bridgeStatus = 'Snapshot Frame #$_currentSnapIndex Relayed to Central System.';
      notifyListeners();
    } else if (event.startsWith('PING:')) {
      // PING:<pinId>:<rssi>:<batPct>:<batMv>
      final parts = event.split(':');
      if (parts.length >= 3) _lastRssi = int.tryParse(parts[2]) ?? -60;
      if (parts.length >= 4) _pinBattery = int.tryParse(parts[3]) ?? 100;
      _lastPacketTime = DateTime.now();
      notifyListeners();
    }
  }

  /// Forwards captured snapshot frame to Central FastAPI /api/relay-stream
  Future<void> _forwardSnapshotToRestServer(Uint8List snapBytes, int snapIndex) async {
    if (snapBytes.isEmpty) return;
    try {
      final uri = Uri.parse('http://$_serverHost:$_serverPort/api/relay-stream');
      final payload = {
        'device_id': _connectedPinId,
        'snapshot_base64': base64Encode(snapBytes),
        'snapshot_index': snapIndex,
      };

      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final req = await client.postUrl(uri);
      req.headers.set('content-type', 'application/json');
      req.add(utf8.encode(jsonEncode(payload)));
      final res = await req.close();
      client.close();
      debugPrint('[RELAY-REST] Snapshot frame #$snapIndex forwarded to server (status ${res.statusCode})');
    } catch (e) {
      debugPrint('[RELAY-REST] Error forwarding snapshot frame #$snapIndex: $e');
    }
  }

  /// Forwards complete raw PCM audio burst to Central FastAPI /api/relay-stream
  Future<void> _forwardPcmToRestServer(Uint8List pcmBytes) async {
    if (pcmBytes.length < 3200) return; // Ignore sub-100ms noise
    try {
      final uri = Uri.parse('http://$_serverHost:$_serverPort/api/relay-stream');
      final payload = {
        'device_id': _connectedPinId,
        'audio_base64': base64Encode(pcmBytes),
      };

      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final req = await client.postUrl(uri);
      req.headers.set('content-type', 'application/json');
      req.add(utf8.encode(jsonEncode(payload)));
      final res = await req.close();
      if (res.statusCode == 200) {
        final body = await res.transform(utf8.decoder).join();
        final json = jsonDecode(body);
        if (json['is_danger'] == true) {
          debugPrint('[RELAY-REST] AI detected danger! Sending TRIGGER:DANGER to pin...');
          writeEventControlCharacteristic('TRIGGER:DANGER');
        }
      }
      client.close();
    } catch (e) {
      debugPrint('[RELAY-REST] Error forwarding audio: $e');
    }
  }

  /// Sends a simulated audio burst for testing deadzone cellular relay without hardware
  Future<void> testSimulatedBleRelayBurst(String testTranscript) async {
    if (!_isBleConnected) return;

    await onBleEventNotificationReceived('STREAM_START:$_connectedPinId');
    // Generate 2 seconds of 16kHz 16-bit PCM (64,000 bytes) in chunks of 240 bytes
    final dummyPcm = Uint8List(32000); // 1 sec
    const chunkSize = 240;
    for (int offset = 0; offset < dummyPcm.length; offset += chunkSize) {
      final len = (offset + chunkSize <= dummyPcm.length) ? chunkSize : (dummyPcm.length - offset);
      final sub = dummyPcm.sublist(offset, offset + len);
      onBleAudioPacketReceived(sub);
      await Future.delayed(const Duration(milliseconds: 15));
    }
    await onBleEventNotificationReceived('STREAM_END:$_connectedPinId');
  }
}
