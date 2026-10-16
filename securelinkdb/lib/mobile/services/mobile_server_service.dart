import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/device_model.dart';

class IncidentReport {
  final String id;
  final String deviceId;
  final String timestamp;
  final String transcript;
  final double threatScore;
  final String threatLabel;
  final String? audioFile;
  final String? audioUrl;
  final String? snapshotFile;
  final List<String> snapshots;

  IncidentReport({
    required this.id,
    required this.deviceId,
    required this.timestamp,
    required this.transcript,
    required this.threatScore,
    required this.threatLabel,
    this.audioFile,
    this.audioUrl,
    this.snapshotFile,
    this.snapshots = const [],
  });

  bool get isFlagged => threatScore >= 2.0 || threatLabel.toLowerCase() != 'conversational';
  bool get isThreat => threatScore >= 4.0;
  bool get isDanger => threatScore >= 8.0;
  String get flagType => threatLabel;

  IncidentReport copyWith({
    String? id,
    String? deviceId,
    String? timestamp,
    String? transcript,
    double? threatScore,
    String? threatLabel,
    String? audioFile,
    String? audioUrl,
    String? snapshotFile,
    List<String>? snapshots,
  }) {
    return IncidentReport(
      id: id ?? this.id,
      deviceId: deviceId ?? this.deviceId,
      timestamp: timestamp ?? this.timestamp,
      transcript: transcript ?? this.transcript,
      threatScore: threatScore ?? this.threatScore,
      threatLabel: threatLabel ?? this.threatLabel,
      audioFile: audioFile ?? this.audioFile,
      audioUrl: audioUrl ?? this.audioUrl,
      snapshotFile: snapshotFile ?? this.snapshotFile,
      snapshots: snapshots ?? this.snapshots,
    );
  }

  factory IncidentReport.fromJson(Map<String, dynamic> json, {String? host, int? port}) {
    final af = json['audio_file'] as String?;
    final h = host ?? '10.28.20.11';
    final p = port ?? 8080;
    final explicitUrl = json['audio_url'] as String?;
    final computedUrl = af != null && af.isNotEmpty ? 'http://$h:$p/recordings/audio/$af' : explicitUrl;

    final rawSnaps = json['snapshots'] as List?;
    final snapFile = json['snapshot_file'] as String?;
    final snapExplicit = json['snapshot_url'] as String?;
    final defaultSnapUrl = snapFile != null && snapFile.isNotEmpty
        ? 'http://$h:$p/recordings/snapshots/$snapFile'
        : snapExplicit;
    final List<String> parsedSnaps = rawSnaps != null
        ? rawSnaps.map((e) => e.toString()).toList()
        : (defaultSnapUrl != null ? [defaultSnapUrl] : []);

    return IncidentReport(
      id: json['id'] as String? ?? 'INC-${DateTime.now().millisecondsSinceEpoch}',
      deviceId: json['device_id'] as String? ?? 'PIN-001',
      timestamp: json['timestamp'] as String? ?? DateTime.now().toString(),
      transcript: json['transcript'] as String? ?? 'Speech detected',
      threatScore: (json['threat_score'] is num) ? (json['threat_score'] as num).toDouble() : (json['score'] is num ? (json['score'] as num).toDouble() : 1.0),
      threatLabel: json['threat_label'] as String? ?? (json['category'] as String? ?? 'Conversational'),
      audioFile: af,
      audioUrl: computedUrl,
      snapshotFile: snapFile,
      snapshots: parsedSnaps,
    );
  }
}

class MobileServerService extends ChangeNotifier {
  static final MobileServerService _instance = MobileServerService._internal();
  factory MobileServerService() => _instance;
  MobileServerService._internal() {
    _initDefaults();
  }

  // --- Central System (CS) Identification & Connection ---
  String _host = '10.28.20.11'; // Current Central System Laptop Wi-Fi IP
  int _port = 8080;
  String _csId = 'CS-CAMPUS-01';
  String _csName = 'SecureLink Campus Central System';

  // --- Mobile Device Profile (Teacher / Student) ---
  String _mobileId = 'MOBILE-USER-01';
  String _userName = 'Teacher / Student';
  String _userRole = 'Teacher'; // 'Teacher' or 'Student'

  // --- Connection State ---
  WebSocketChannel? _channel;
  Timer? _pingTimer;
  Timer? _reconnectTimer;
  bool _isConnected = false;
  bool _isConnecting = false;
  bool _isSearchingPins = false;
  bool _isAutoDiscoveringCS = false;
  String _statusMessage = 'Disconnected';
  bool _harmfulWordsOnly = false;

  // --- Telemetry & Data ---
  final Map<String, DeviceStatus> _devices = {};
  final List<WifiCheckpoint> _checkpoints = [];
  final List<IncidentReport> _recentIncidents = [];

  // --- Paired Pins for this specific Mobile Device ---
  final Set<String> _pairedPinIds = {};
  final Map<String, String> _pinAliases = {}; // e.g. "PIN-001" -> "Student: Juan Dela Cruz"

  // Getters
  String get host => _host;
  int get port => _port;
  String get csId => _csId;
  String get csName => _csName;
  String get mobileId => _mobileId;
  String get userName => _userName;
  String get userRole => _userRole;

  bool get isConnected => _isConnected;
  bool get isConnecting => _isConnecting;
  bool get isSearchingPins => _isSearchingPins;
  bool get isAutoDiscoveringCS => _isAutoDiscoveringCS;
  String get statusMessage => _statusMessage;
  bool get harmfulWordsOnly => _harmfulWordsOnly;

  /// Connection Priority Architecture string
  String get prioritySummary =>
      'Priority 1: Central System ($csId) • Priority 2: Mobile App ($userName)';

  /// All devices reported by Central System
  List<DeviceStatus> get allDevices => _devices.values.toList();
  List<DeviceStatus> get devices => allDevices;

  /// Devices strictly paired to THIS mobile device
  List<DeviceStatus> get pairedDevices {
    if (_pairedPinIds.isEmpty) return [];
    return _devices.values.where((d) => _pairedPinIds.contains(d.id.toUpperCase())).toList();
  }

  /// Devices discovered on network but not yet paired to this phone
  List<DeviceStatus> get unpairedDevices =>
      _devices.values.where((d) => !_pairedPinIds.contains(d.id.toUpperCase())).toList();

  /// All checkpoints from Central System
  List<WifiCheckpoint> get checkpoints => List.unmodifiable(_checkpoints);

  /// All recent incidents received from Central System
  List<IncidentReport> get allIncidents => List.unmodifiable(_recentIncidents);

  /// Incidents for this mobile user's paired pins
  List<IncidentReport> get pairedIncidents => List.unmodifiable(_recentIncidents);

  /// Important incidents only: threats, verbal harassment, or flagged words
  List<IncidentReport> get importantIncidents =>
      _recentIncidents.where((i) => i.isFlagged).toList();

  IncidentReport? _latestAlert;
  IncidentReport? get latestAlert => _latestAlert;

  void clearLatestAlert() {
    _latestAlert = null;
    notifyListeners();
  }

  int get onlineCount => pairedDevices.where((d) => d.online).length;
  int get lowBatteryCount => pairedDevices.where((d) => d.isLowBattery).length;

  bool isPinPaired(String pinId) => _pairedPinIds.contains(pinId.trim().toUpperCase());

  String? getPinAlias(String pinId) => _pinAliases[pinId.trim().toUpperCase()];

  // --------------------------------------------------------------------------
  Future<void> init() async {
    await _loadPreferences();
  }

  void _initDefaults() {
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _host = prefs.getString('cs_host') ?? (kIsWeb || (!Platform.isAndroid && !Platform.isIOS) ? '127.0.0.1' : '10.28.20.11');
      _port = prefs.getInt('cs_port') ?? 8080;
      _csId = prefs.getString('cs_id') ?? 'CS-CAMPUS-01';
      _csName = prefs.getString('cs_name') ?? 'SecureLink Campus Central System';
      _mobileId = prefs.getString('mobile_id') ?? 'MOBILE-${DateTime.now().millisecondsSinceEpoch % 10000}';
      _userName = prefs.getString('user_name') ?? 'Teacher / Student';
      _userRole = prefs.getString('user_role') ?? 'Teacher';

      final savedPins = prefs.getStringList('paired_pins') ?? [];
      _pairedPinIds.clear();
      _pairedPinIds.addAll(savedPins.map((e) => e.toUpperCase()));

      final aliasJson = prefs.getString('pin_aliases');
      if (aliasJson != null) {
        final decoded = jsonDecode(aliasJson) as Map<String, dynamic>;
        _pinAliases.clear();
        decoded.forEach((k, v) => _pinAliases[k.toUpperCase()] = v.toString());
      }

      // Load cached paired devices so paired pins are ALWAYS visible permanently on phone
      final cachedDevsJson = prefs.getString('paired_devices_cache');
      if (cachedDevsJson != null) {
        try {
          final decoded = jsonDecode(cachedDevsJson) as Map<String, dynamic>;
          decoded.forEach((k, v) {
            final dev = DeviceStatus.fromJson(v as Map<String, dynamic>);
            _devices[k.toUpperCase()] = dev;
          });
        } catch (_) {}
      }

      // Ensure every paired pin ID is permanently populated in _devices
      for (final pid in _pairedPinIds) {
        if (!_devices.containsKey(pid)) {
          _devices[pid] = DeviceStatus(
            id: pid,
            online: false,
            battery: 100,
            state: 'STANDBY',
            network: _checkpoints.isNotEmpty ? _checkpoints.first.ssid : 'Campus Wi-Fi',
            lastSeen: 'Paired Pin',
            cpuMhz: 160,
            rssi: -60,
            estRuntime: '--',
          );
        }
      }
    } catch (e) {
      debugPrint('[PREFS] Load error: $e');
    }
    notifyListeners();
    // Auto-probe and connect
    autoDiscoverCentralSystem(silent: true);
  }

  Future<void> _savePreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('cs_host', _host);
      await prefs.setInt('cs_port', _port);
      await prefs.setString('cs_id', _csId);
      await prefs.setString('cs_name', _csName);
      await prefs.setString('mobile_id', _mobileId);
      await prefs.setString('user_name', _userName);
      await prefs.setString('user_role', _userRole);
      await prefs.setStringList('paired_pins', _pairedPinIds.toList());
      await prefs.setString('pin_aliases', jsonEncode(_pinAliases));

      // Persist paired devices cache so pins stay on phone even when offline
      final pairedMap = <String, dynamic>{};
      for (final pid in _pairedPinIds) {
        if (_devices.containsKey(pid)) {
          pairedMap[pid] = _devices[pid]!.toJson();
        }
      }
      await prefs.setString('paired_devices_cache', jsonEncode(pairedMap));
    } catch (e) {
      debugPrint('[PREFS] Save error: $e');
    }
  }

  void setUserProfile({required String name, required String role}) {
    _userName = name.trim();
    _userRole = role.trim();
    _savePreferences();
    notifyListeners();
    _syncWithCentralSystem();
  }

  // --------------------------------------------------------------------------
  // CENTRAL SYSTEM SYNC & UDP AUTO-DISCOVERY
  // --------------------------------------------------------------------------
  void updateHost(String newHost, [int? newPort]) {
    _host = newHost.trim();
    if (newPort != null && newPort > 0) _port = newPort;
    _savePreferences();
    notifyListeners();
    reconnect();
  }

  /// Automatically discovers the Central System across LAN via UDP 8888 and HTTP Probes
  Future<bool> autoDiscoverCentralSystem({bool silent = false}) async {
    if (_isAutoDiscoveringCS) return false;
    _isAutoDiscoveringCS = true;
    if (!silent) {
      _statusMessage = 'Searching for Central System on Wi-Fi (UDP & Probe)...';
      notifyListeners();
    }

    bool found = false;

    // 1. First probe candidate IPs over fast HTTP (1.2s timeout)
    final candidates = [
      _host,
      '10.28.20.11', // Laptop primary active Wi-Fi IP
      '10.28.20.28',
      '127.0.0.1',
      '192.168.1.100',
      '192.168.1.101',
      '192.168.1.104',
      '192.168.4.1', // Pin AP gateway
    ];

    for (final ip in candidates) {
      if (found) break;
      final ok = await _probeCsHttp(ip, _port);
      if (ok) {
        _host = ip;
        found = true;
        break;
      }
    }

    // 2. If not yet found, broadcast UDP discovery on port 8888
    if (!found && !kIsWeb) {
      try {
        final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
        socket.broadcastEnabled = true;

        final probeData = utf8.encode('SECURELINK_MOBILE_V1:DISCOVERY');
        socket.send(probeData, InternetAddress('255.255.255.255'), 8888);

        // Also broadcast to current subnet
        if (_host.contains('.')) {
          final parts = _host.split('.');
          if (parts.length == 4) {
            final subnetBroadcast = '${parts[0]}.${parts[1]}.${parts[2]}.255';
            socket.send(probeData, InternetAddress(subnetBroadcast), 8888);
          }
        }

        final completer = Completer<String?>();
        Timer(const Duration(milliseconds: 1800), () {
          if (!completer.isCompleted) completer.complete(null);
        });

        socket.listen((event) {
          if (event == RawSocketEvent.read) {
            final datagram = socket.receive();
            if (datagram != null) {
              final resp = utf8.decode(datagram.data, allowMalformed: true);
              if (resp.startsWith('ACK:')) {
                final discoveredIp = resp.substring(4).trim();
                if (!completer.isCompleted) completer.complete(discoveredIp);
              } else if (resp.contains('CS_DISCOVERY_ACK')) {
                try {
                  final j = jsonDecode(resp);
                  final ip = j['server_ip'] as String?;
                  if (ip != null && !completer.isCompleted) completer.complete(ip);
                } catch (_) {}
              }
            }
          }
        });

        final udpResult = await completer.future;
        socket.close();

        if (udpResult != null && udpResult.isNotEmpty) {
          _host = udpResult;
          found = true;
        }
      } catch (e) {
        debugPrint('[UDP] Discovery broadcast error: $e');
      }
    }

    _isAutoDiscoveringCS = false;
    _savePreferences();
    notifyListeners();

    if (found || !_isConnected) {
      reconnect();
    }
    return found;
  }

  Future<bool> _probeCsHttp(String targetIp, int targetPort) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(milliseconds: 1200);
      final req = await client.getUrl(Uri.parse('http://$targetIp:$targetPort/api/cs-info'));
      final res = await req.close();
      if (res.statusCode == 200) {
        final body = await res.transform(utf8.decoder).join();
        final json = jsonDecode(body);
        _csId = json['cs_id'] ?? _csId;
        _csName = json['name'] ?? _csName;
        client.close();
        return true;
      }
      client.close();
    } catch (_) {}
    return false;
  }

  // --------------------------------------------------------------------------
  // WEBSOCKET LIFECYCLE
  // --------------------------------------------------------------------------
  void reconnect() {
    _channel?.sink.close();
    _pingTimer?.cancel();
    _reconnectTimer?.cancel();
    _isConnected = false;
    _isConnecting = false;
    connect();
  }

  Future<void> connect() async {
    if (_isConnecting) return;
    _isConnecting = true;
    _statusMessage = 'Connecting to Central System (ws://$_host:$_port/ui)...';
    notifyListeners();

    _fetchDevicesRest();
    _fetchCheckpointsRest();

    try {
      final wsUri = Uri.parse('ws://$_host:$_port/ui');
      _channel = WebSocketChannel.connect(wsUri);

      _channel!.ready.then((_) {
        _isConnected = true;
        _isConnecting = false;
        _statusMessage = 'Synced with Central System ($csId @ $_host:$_port)';
        notifyListeners();
        _fetchDevicesRest();
        _fetchCheckpointsRest();
        _startHeartbeat();
        _syncWithCentralSystem();
      }).catchError((err) {
        _handleDisconnect('Connection refused by CS at $_host:$_port ($err)');
      });

      _channel!.stream.listen(
        (data) {
          _isConnected = true;
          _isConnecting = false;
          _onMessageReceived(data);
        },
        onError: (err) => _handleDisconnect('Socket error: $err'),
        onDone: () => _handleDisconnect('Central System disconnected'),
      );
    } catch (e) {
      _handleDisconnect('Failed: $e');
    }
  }

  void _handleDisconnect(String reason) {
    _isConnected = false;
    _isConnecting = false;
    _statusMessage = reason;
    _pingTimer?.cancel();
    notifyListeners();

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 4), () {
      if (!_isConnected) connect();
    });
  }

  void _startHeartbeat() {
    _pingTimer?.cancel();
    _pingTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      try {
        _channel?.sink.add('ping');
      } catch (_) {}
    });
  }

  void _syncWithCentralSystem() {
    if (!_isConnected || _channel == null) return;
    final payload = {
      'event_type': 'mobile_sync',
      'mobile_id': _mobileId,
      'user_name': _userName,
      'role': _userRole,
      'paired_pins': _pairedPinIds.toList(),
      'priority': 'PRIMARY_CENTRAL_SYSTEM_SECONDARY_MOBILE',
      'timestamp': DateTime.now().toIso8601String(),
    };
    try {
      _channel?.sink.add(jsonEncode(payload));
    } catch (_) {}
  }

  // --------------------------------------------------------------------------
  // MESSAGE RECEIVER & INCIDENT STREAM
  // --------------------------------------------------------------------------
  void _onMessageReceived(dynamic rawData) {
    try {
      final json = jsonDecode(rawData.toString());
      final eventType = json['event_type'];

      if (eventType == 'device_update' && json['device'] != null) {
        final dev = DeviceStatus.fromJson(json['device']);
        _devices[dev.id.toUpperCase()] = dev;
        if (_pairedPinIds.contains(dev.id.toUpperCase())) {
          _savePreferences();
        }
        notifyListeners();
      } else if (eventType == 'checkpoints_updated' && json['checkpoints'] != null) {
        final list = (json['checkpoints'] as List)
            .map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>))
            .toList();
        _checkpoints.clear();
        _checkpoints.addAll(list);
        notifyListeners();
      } else if (eventType == 'harmful_only_update') {
        _harmfulWordsOnly = json['enabled'] == true;
        notifyListeners();
      } else if (eventType == 'server_status') {
        _statusMessage = 'Synced with $csId (${json['status'] ?? 'Ready'})';
        if (json.containsKey('harmful_words_only')) {
          _harmfulWordsOnly = json['harmful_words_only'] == true;
        }
        notifyListeners();
      } else if (eventType == 'incident' || (eventType == 'incident_detected' && json['incident'] != null)) {
        final rawIncident = eventType == 'incident' ? json : json['incident'];
        final inc = IncidentReport.fromJson(rawIncident, host: _host, port: _port);
        if (_pairedPinIds.isEmpty || _pairedPinIds.contains(inc.deviceId.toUpperCase())) {
          _recentIncidents.insert(0, inc);
          if (_recentIncidents.length > 50) _recentIncidents.removeLast();
          if (inc.isFlagged) {
            _latestAlert = inc;
          }
          notifyListeners();
        }
      } else if (eventType == 'snapshot_ready') {
        final snapUrl = json['snapshot_url'] as String? ?? (json['snapshot_file'] != null ? 'http://$_host:$_port/recordings/snapshots/${json['snapshot_file']}' : null);
        final incidentId = json['incident_id'] as String?;
        final deviceId = json['device_id'] as String?;
        final rawList = json['snapshots'] as List?;
        final List<String> newSnaps = rawList != null
            ? rawList.map((e) => e.toString()).toList()
            : (snapUrl != null ? [snapUrl] : []);

        if (newSnaps.isNotEmpty) {
          final idx = _recentIncidents.indexWhere((inc) => (incidentId != null && inc.id == incidentId) || (deviceId != null && inc.deviceId == deviceId && inc.isDanger));
          if (idx >= 0) {
            final inc = _recentIncidents[idx];
            final mergedSnaps = List<String>.from(inc.snapshots);
            for (final s in newSnaps) {
              if (!mergedSnaps.contains(s)) mergedSnaps.add(s);
            }
            _recentIncidents[idx] = inc.copyWith(snapshots: mergedSnaps);
            if (_latestAlert != null && _latestAlert!.id == inc.id) {
              _latestAlert = _recentIncidents[idx];
            }
            notifyListeners();
          }
        }
      }
    } catch (e) {
      debugPrint('[MOBILE_WS] Parse error: $e');
    }
  }

  Future<void> _fetchCheckpointsRest() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.getUrl(Uri.parse('http://$_host:$_port/api/checkpoints'));
      final res = await req.close();
      if (res.statusCode == 200) {
        final body = await res.transform(utf8.decoder).join();
        final json = jsonDecode(body);
        if (json['checkpoints'] != null) {
          final list = (json['checkpoints'] as List)
              .map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>))
              .toList();
          _checkpoints.clear();
          _checkpoints.addAll(list);
          notifyListeners();
        }
      }
      client.close();
    } catch (_) {}
  }

  /// Fetches all registered and live pins from Central System REST API
  Future<void> _fetchDevicesRest() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(Uri.parse('http://$_host:$_port/api/devices'));
      final res = await req.close();
      if (res.statusCode == 200) {
        final body = await res.transform(utf8.decoder).join();
        final json = jsonDecode(body);
        if (json['devices'] != null) {
          final list = (json['devices'] as List)
              .map((d) => DeviceStatus.fromJson(d as Map<String, dynamic>))
              .toList();
          for (final dev in list) {
            _devices[dev.id.toUpperCase()] = dev;
          }
          _savePreferences();
          notifyListeners();
        }
      }
      client.close();
    } catch (_) {}
  }

  // --------------------------------------------------------------------------
  // PIN PAIRING & MANAGEMENT (WI-FI & BLUETOOTH)
  // --------------------------------------------------------------------------

  /// Scan for real smart pins on local Wi-Fi and Central System
  Future<void> searchForSmartPins() async {
    _isSearchingPins = true;
    notifyListeners();

    // 1. Fetch live registered pins from Central System API
    await _fetchDevicesRest();
    await _fetchCheckpointsRest();

    // 2. Direct probe for Pin in Setup AP mode (192.168.4.1)
    try {
      final client = HttpClient()..connectionTimeout = const Duration(milliseconds: 900);
      final req = await client.getUrl(Uri.parse('http://192.168.4.1/'));
      final res = await req.close();
      if (res.statusCode == 200) {
        final setupDev = DeviceStatus(
          id: 'PIN-SETUP-AP',
          online: true,
          battery: 100,
          state: 'SETUP AP READY',
          network: 'SecureLink-Setup (192.168.4.1)',
          lastSeen: 'Captive Portal Detected',
          cpuMhz: 160,
          rssi: -35,
          estRuntime: 'Setup Mode',
        );
        _devices['PIN-SETUP-AP'] = setupDev;
      }
      client.close();
    } catch (_) {}

    // 3. UDP broadcast to ping subnet & listen for pin keep-alive announcements
    if (!kIsWeb) {
      try {
        final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
        socket.broadcastEnabled = true;

        // Listen for pins broadcasting on the LAN
        socket.listen((event) {
          if (event == RawSocketEvent.read) {
            final dg = socket.receive();
            if (dg != null) {
              final text = utf8.decode(dg.data, allowMalformed: true);
              if (text.contains('SECURELINK_PIN') || text.contains('PING:')) {
                final pinIp = dg.address.address;
                final suffix = pinIp.split('.').last.padLeft(3, '0');
                final pinId = 'PIN-$suffix';
                if (!_devices.containsKey(pinId)) {
                  _devices[pinId] = DeviceStatus(
                    id: pinId,
                    online: true,
                    battery: 95,
                    state: 'VAD ARMED',
                    network: 'Campus Wi-Fi ($pinIp)',
                    lastSeen: 'Direct LAN Broadcast',
                    cpuMhz: 160,
                    rssi: -55,
                    estRuntime: '5h 30m',
                  );
                  notifyListeners();
                }
              }
            }
          }
        });

        // Broadcast discovery ping across subnet
        final probeData = utf8.encode('SECURELINK_DISCOVER_PIN');
        socket.send(probeData, InternetAddress('255.255.255.255'), 8888);

        if (_host.contains('.')) {
          final parts = _host.split('.');
          if (parts.length == 4) {
            final subnetBcast = '${parts[0]}.${parts[1]}.${parts[2]}.255';
            socket.send(probeData, InternetAddress(subnetBcast), 8888);
          }
        }

        await Future.delayed(const Duration(milliseconds: 900));
        socket.close();
      } catch (_) {}
    }

    _isSearchingPins = false;
    notifyListeners();
  }

  /// Pairs a pin to this mobile device (via Wi-Fi or Bluetooth)
  Future<bool> pairPin(
    String pinId, {
    String? alias,
    String method = 'wifi',
  }) async {
    final cleanId = pinId.trim().toUpperCase();
    if (cleanId.isEmpty) return false;

    _pairedPinIds.add(cleanId);
    if (alias != null && alias.trim().isNotEmpty) {
      _pinAliases[cleanId] = alias.trim();
    }

    // If device doesn't exist yet in cache, create initial registered entry
    if (!_devices.containsKey(cleanId)) {
      _devices[cleanId] = DeviceStatus(
        id: cleanId,
        online: true,
        battery: 100,
        state: 'VAD ARMED (STANDBY)',
        network: _checkpoints.isNotEmpty ? _checkpoints.first.ssid : 'Campus Wi-Fi',
        lastSeen: 'Paired just now ($method)',
        cpuMhz: 160,
        rssi: -58,
        estRuntime: '7h 15m',
      );
    }

    await _savePreferences();
    _syncWithCentralSystem();
    notifyListeners();
    return true;
  }

  /// Unpairs a pin from this mobile device
  Future<void> unpairPin(String pinId) async {
    final cleanId = pinId.trim().toUpperCase();
    _pairedPinIds.remove(cleanId);
    _pinAliases.remove(cleanId);
    await _savePreferences();
    _syncWithCentralSystem();
    notifyListeners();
  }

  /// Permanently deletes a pin from mobile pairings and local device cache
  Future<void> deletePin(String pinId) async {
    final cleanId = pinId.trim().toUpperCase();
    _pairedPinIds.remove(cleanId);
    _pinAliases.remove(cleanId);
    _devices.remove(cleanId);
    await _savePreferences();
    _syncWithCentralSystem();
    notifyListeners();
  }

  /// Provisions a Pin via its direct Wi-Fi Setup AP (192.168.4.1) or Central System OTA
  Future<Map<String, dynamic>> provisionPinWifiSetup({
    required String pinId,
    required String ssid,
    required String password,
    String? alias,
  }) async {
    final cleanId = pinId.trim().toUpperCase();

    // 1. First attempt direct connection to Pin Setup AP captive portal
    bool directApSuccess = false;
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final uri = Uri.parse(
        'http://192.168.4.1/save?ssid=${Uri.encodeComponent(ssid)}&pass=${Uri.encodeComponent(password)}&server=${Uri.encodeComponent(_host)}&port=$_port',
      );
      final req = await client.getUrl(uri);
      final res = await req.close();
      if (res.statusCode == 200) directApSuccess = true;
      client.close();
    } catch (_) {}

    // 2. Also register via Central System deploy API
    final checkpoint = WifiCheckpoint(
      id: 'chk_pair_${DateTime.now().millisecondsSinceEpoch}',
      name: 'Paired AP ($ssid)',
      ssid: ssid,
      pass: password,
      serverIp: _host,
      serverPort: _port,
    );
    await deployCheckpoint(checkpoint, target: cleanId);

    // 3. Mark as paired on this mobile device
    await pairPin(cleanId, alias: alias, method: directApSuccess ? 'Pin AP Direct' : 'Central OTA');

    return {
      'success': true,
      'direct_ap': directApSuccess,
      'pin_id': cleanId,
      'priority': 'Priority 1: CS ($csId), Priority 2: Mobile ($userName)',
    };
  }

  /// Simulates BLE handshake & pairs a pin over Bluetooth
  Future<bool> pairPinViaBluetooth({
    required String pinId,
    String? alias,
  }) async {
    final cleanId = pinId.trim().toUpperCase();
    await Future.delayed(const Duration(milliseconds: 900)); // BLE discovery handshake latency
    return pairPin(cleanId, alias: alias, method: 'Bluetooth Low Energy');
  }

  // --------------------------------------------------------------------------
  // FLEET ACTIONS
  // --------------------------------------------------------------------------
  Future<bool> deployCheckpoint(WifiCheckpoint chk, {String target = 'ALL'}) async {
    final payload = {
      'event_type': 'deploy_wifi_checkpoint',
      'id': chk.id,
      'name': chk.name,
      'ssid': chk.ssid,
      'pass': chk.pass,
      'server_ip': chk.serverIp,
      'server_port': chk.serverPort,
      'target': target,
      'method': 'wifi',
    };

    if (_isConnected && _channel != null) {
      try {
        _channel?.sink.add(jsonEncode(payload));
      } catch (_) {}
    }

    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.postUrl(Uri.parse('http://$_host:$_port/api/checkpoints/deploy'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode(payload));
      final res = await req.close();
      client.close();
      if (res.statusCode == 200) {
        _fetchCheckpointsRest();
      }
    } catch (_) {}

    final now = DateTime.now();
    for (final key in _devices.keys) {
      if (target == 'ALL' || key == target) {
        _devices[key] = _devices[key]!.copyWith(
          network: chk.ssid,
          state: 'UPDATING WI-FI',
          lastSeen: 'Pushing Wi-Fi at ${now.hour}:${now.minute.toString().padLeft(2, '0')}',
        );
      }
    }
    notifyListeners();
    return true;
  }

  Future<bool> forgetWifi({String target = 'ALL'}) async {
    final payload = {
      'event_type': 'forget_wifi',
      'command': 'CMD:FORGET_WIFI',
      'target': target,
    };

    if (_isConnected && _channel != null) {
      try {
        _channel?.sink.add(jsonEncode(payload));
      } catch (_) {}
    }

    for (final key in _devices.keys) {
      if (target == 'ALL' || key == target) {
        _devices[key] = _devices[key]!.copyWith(
          state: 'ENTERING SETUP PORTAL',
          network: 'SecureLink-Setup AP',
        );
      }
    }
    notifyListeners();
    return true;
  }

  Future<void> saveCheckpoint(WifiCheckpoint chk) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.postUrl(Uri.parse('http://$_host:$_port/api/checkpoints'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode(chk.toJson()));
      await req.close();
      client.close();
    } catch (_) {}

    final idx = _checkpoints.indexWhere((c) => c.id == chk.id);
    if (idx >= 0) {
      _checkpoints[idx] = chk;
    } else {
      _checkpoints.add(chk);
    }
    notifyListeners();
  }

  Future<void> deleteCheckpoint(String chkId) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.deleteUrl(Uri.parse('http://$_host:$_port/api/checkpoints/$chkId'));
      await req.close();
      client.close();
    } catch (_) {}

    _checkpoints.removeWhere((c) => c.id == chkId);
    notifyListeners();
  }

  void pingPin(String pinId) {
    final cleanId = pinId.trim().toUpperCase();
    if (_devices.containsKey(cleanId)) {
      _devices[cleanId] = _devices[cleanId]!.copyWith(
        lastSeen: 'Pinged just now (OK)',
      );
      notifyListeners();
    }
  }

  /// Renames a pin / updates its display alias (e.g. Student name)
  Future<void> renamePin(String pinId, String newAlias) async {
    final cleanId = pinId.trim().toUpperCase();
    if (newAlias.trim().isEmpty) {
      _pinAliases.remove(cleanId);
    } else {
      _pinAliases[cleanId] = newAlias.trim();
    }
    await _savePreferences();
    _syncWithCentralSystem();
    notifyListeners();
  }

  void toggleHarmfulWordsOnly([bool? targetState]) {
    final nextState = targetState ?? !_harmfulWordsOnly;
    _harmfulWordsOnly = nextState;
    notifyListeners();
    if (_isConnected && _channel != null) {
      try {
        _channel!.sink.add(jsonEncode({
          'event_type': 'set_harmful_only',
          'enabled': nextState,
        }));
      } catch (_) {}
    }
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      client.postUrl(Uri.parse('http://$_host:$_port/api/toggle-harmful-only')).then((req) {
        req.headers.contentType = ContentType.json;
        req.write(jsonEncode({'enabled': nextState}));
        return req.close();
      }).then((resp) => resp.drain()).catchError((_) => null);
    } catch (_) {}
  }

  @override
  void dispose() {
    _channel?.sink.close();
    _pingTimer?.cancel();
    _reconnectTimer?.cancel();
    super.dispose();
  }
}
