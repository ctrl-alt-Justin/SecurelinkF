import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/device_model.dart';
import 'ble_pin_relay_service.dart';

enum MobileConnectionState {
  notPaired,
  pairingPending,
  paired,
  connecting,
  connected,
  disconnected,
  authenticationFailed,
  revoked,
}

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
  final String? snapshotUrl;

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
    this.snapshotUrl,
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
    String? snapshotUrl,
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
      snapshotUrl: snapshotUrl ?? this.snapshotUrl,
    );
  }

  factory IncidentReport.fromJson(Map<String, dynamic> json, {String? host, int? port}) {
    final af = json['audio_file'] as String?;
    final explicitUrl = json['audio_url'] as String?;
    final sf = json['snapshot_file'] as String?;
    final explicitSnapUrl = json['snapshot_url'] as String?;
    final s = MobileServerService();
    String? computedUrl;
    if (af != null && af.isNotEmpty) {
      computedUrl = '${s.baseHttpUrl}/recordings/audio/$af';
    } else if (explicitUrl != null && explicitUrl.isNotEmpty) {
      if (explicitUrl.contains('127.0.0.1') || explicitUrl.contains('localhost')) {
        final path = explicitUrl.replaceFirst(RegExp(r'https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?'), '');
        computedUrl = '${s.baseHttpUrl}$path';
      } else if (explicitUrl.startsWith('/')) {
        computedUrl = '${s.baseHttpUrl}$explicitUrl';
      } else {
        computedUrl = explicitUrl;
      }
    }

    String? computedSnapUrl;
    if (explicitSnapUrl != null && explicitSnapUrl.isNotEmpty) {
      if (explicitSnapUrl.contains('127.0.0.1') || explicitSnapUrl.contains('localhost')) {
        final path = explicitSnapUrl.replaceFirst(RegExp(r'https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?'), '');
        computedSnapUrl = '${s.baseHttpUrl}$path';
      } else if (explicitSnapUrl.startsWith('/')) {
        computedSnapUrl = '${s.baseHttpUrl}$explicitSnapUrl';
      } else {
        computedSnapUrl = explicitSnapUrl;
      }
    } else if (sf != null && sf.isNotEmpty) {
      computedSnapUrl = '${s.baseHttpUrl}/recordings/snapshots/$sf';
    }

    return IncidentReport(
      id: json['id'] as String? ?? 'INC-${DateTime.now().millisecondsSinceEpoch}',
      deviceId: json['device_id'] as String? ?? 'PIN-001',
      timestamp: json['timestamp'] as String? ?? DateTime.now().toString(),
      transcript: json['transcript'] as String? ?? 'Speech detected',
      threatScore: (json['threat_score'] is num) ? (json['threat_score'] as num).toDouble() : (json['score'] is num ? (json['score'] as num).toDouble() : 1.0),
      threatLabel: json['threat_label'] as String? ?? (json['category'] as String? ?? 'Conversational'),
      audioFile: af,
      audioUrl: computedUrl,
      snapshotFile: sf,
      snapshotUrl: computedSnapUrl,
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

  // --- Cloudflare Tunnel (Global Routing for Cellular 4G/5G & AP Isolation) ---
  String? _cloudTunnelUrl; // No hardcoded hostname; dynamic trycloudflare.com tunnel
  bool _useCloudTunnel = false;

  // --- Mobile Device Profile & Cryptographic Auth Token ---
  String _mobileId = 'MOBILE-USER-01';
  String _userName = 'Teacher / Student';
  String _userRole = 'Teacher'; // 'Teacher' or 'Student'
  String? _authToken;
  static const FlutterSecureStorage _secureStorage = FlutterSecureStorage();

  // --- Connection State ---
  MobileConnectionState _connectionState = MobileConnectionState.notPaired;
  WebSocketChannel? _channel;
  Timer? _pingTimer;
  Timer? _reconnectTimer;
  Timer? _networkFallbackTimer;
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
  final Set<String> _seenIncidentIds = {}; // Deduplication across reconnects

  // --- Paired Pins for this specific Mobile Device ---
  final Set<String> _pairedPinIds = {};
  final Map<String, String> _pinAliases = {}; // e.g. "PIN-001" -> "Student: Juan Dela Cruz"

  // Getters
  String get host => _host;
  int get port => _port;
  String get csId => _csId;
  String get csName => _csName;
  String get cloudTunnelUrl => _cloudTunnelUrl ?? '';
  bool get useCloudTunnel => _useCloudTunnel;
  String get mobileId => _mobileId;
  String get userName => _userName;
  String get userRole => _userRole;
  bool get isPaired => _authToken != null && _authToken!.isNotEmpty;
  String? get authToken => _authToken;
  MobileConnectionState get connectionState => _connectionState;

  bool get isConnected => _isConnected;
  bool get isConnecting => _isConnecting;
  bool get isSearchingPins => _isSearchingPins;
  bool get isAutoDiscoveringCS => _isAutoDiscoveringCS;
  String get statusMessage => _statusMessage;
  bool get harmfulWordsOnly => _harmfulWordsOnly;

  /// Whether current connection routes through Cloudflare Tunnel
  bool get isDirectCloudTunnel =>
      _host.contains('trycloudflare.com') ||
      (_useCloudTunnel && _cloudTunnelUrl != null && _cloudTunnelUrl!.isNotEmpty);

  String get activeTunnelHost {
    String raw = (_useCloudTunnel && _cloudTunnelUrl != null && _cloudTunnelUrl!.isNotEmpty)
        ? _cloudTunnelUrl!
        : _host;
    raw = raw.trim();
    if (raw.startsWith('https://')) raw = raw.substring(8);
    if (raw.startsWith('http://')) raw = raw.substring(7);
    if (raw.startsWith('wss://')) raw = raw.substring(6);
    if (raw.startsWith('ws://')) raw = raw.substring(5);
    if (raw.contains('/')) raw = raw.substring(0, raw.indexOf('/'));
    return raw;
  }

  String get baseHttpUrl {
    if (isDirectCloudTunnel) {
      final th = activeTunnelHost;
      return 'https://$th';
    }
    return 'http://$_host:$_port';
  }

  String get baseWsUrl {
    if (isDirectCloudTunnel) {
      final th = activeTunnelHost;
      return 'wss://$th';
    }
    return 'ws://$_host:$_port';
  }

  Uri getUiWsUri() => Uri.parse('$baseWsUrl/ui');
  Uri getMobileWsUri() {
    final devId = Uri.encodeComponent(_mobileId);
    return Uri.parse('$baseWsUrl/mobile?device_id=$devId');
  }
  Uri getApiUri(String path) => Uri.parse('$baseHttpUrl/api$path');

  void setCloudTunnelUrl(String? url, {bool enable = true}) {
    _cloudTunnelUrl = url?.trim();
    _useCloudTunnel = enable && _cloudTunnelUrl != null && _cloudTunnelUrl!.isNotEmpty;
    _savePreferences();
    notifyListeners();
    reconnect();
  }

  void toggleCloudTunnel(bool enabled) {
    _useCloudTunnel = enabled;
    _savePreferences();
    notifyListeners();
    reconnect();
  }

  void setCloudTunnelEnabled(bool enable) => toggleCloudTunnel(enable);

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
      _host = prefs.getString('cs_host') ?? (kIsWeb || (!Platform.isAndroid && !Platform.isIOS) ? '127.0.0.1' : '10.28.20.30');
      _port = prefs.getInt('cs_port') ?? 8080;
      _csId = prefs.getString('cs_id') ?? 'CS-CAMPUS-01';
      _csName = prefs.getString('cs_name') ?? 'SecureLink Campus Central System';
      _cloudTunnelUrl = prefs.getString('cloud_tunnel_url');
      _useCloudTunnel = prefs.getBool('use_cloud_tunnel') ?? false;
      String? savedMobId = prefs.getString('mobile_id');
      if (savedMobId == null || savedMobId.isEmpty) {
        final randSuffix = (DateTime.now().millisecondsSinceEpoch % 9000 + 1000).toString();
        _mobileId = 'MOB-$randSuffix';
        await prefs.setString('mobile_id', _mobileId);
      } else {
        _mobileId = savedMobId;
      }
      _userName = prefs.getString('user_name') ?? 'Teacher / Student';
      _userRole = prefs.getString('user_role') ?? 'Teacher';

      // Load cryptographic mobile authentication token exclusively from FlutterSecureStorage
      try {
        _authToken = await _secureStorage.read(key: 'mobile_auth_token');
      } catch (_) {}
      // Migrate legacy plaintext token if present
      if (_authToken == null || _authToken!.isEmpty) {
        final legacyTok = prefs.getString('mobile_auth_token');
        if (legacyTok != null && legacyTok.isNotEmpty) {
          _authToken = legacyTok;
          try {
            await _secureStorage.write(key: 'mobile_auth_token', value: legacyTok);
          } catch (_) {}
          await prefs.remove('mobile_auth_token');
        }
      }

      if (_authToken != null && _authToken!.isNotEmpty) {
        _connectionState = MobileConnectionState.paired;
      } else {
        _connectionState = MobileConnectionState.notPaired;
      }

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
      if (_cloudTunnelUrl != null) {
        await prefs.setString('cloud_tunnel_url', _cloudTunnelUrl!);
      }
      await prefs.setBool('use_cloud_tunnel', _useCloudTunnel);
      await prefs.setString('mobile_id', _mobileId);
      await prefs.setString('user_name', _userName);
      await prefs.setString('user_role', _userRole);
      await prefs.setStringList('paired_pins', _pairedPinIds.toList());
      await prefs.setString('pin_aliases', jsonEncode(_pinAliases));

      // Persist authentication token exclusively in FlutterSecureStorage (never plaintext SharedPreferences)
      if (_authToken != null && _authToken!.isNotEmpty) {
        try {
          await _secureStorage.write(key: 'mobile_auth_token', value: _authToken!);
        } catch (_) {}
      }
      await prefs.remove('mobile_auth_token');

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

  Future<void> saveAuthCredentials({
    required String token,
    required String deviceId,
    required String csId,
    String? serverIp,
    int? serverPort,
    String? cloudTunnelUrl,
  }) async {
    _authToken = token.trim();
    _mobileId = deviceId.trim();
    _csId = csId.trim();
    _connectionState = MobileConnectionState.paired;
    if (serverIp != null && serverIp.isNotEmpty) _host = serverIp.trim();
    if (serverPort != null && serverPort > 0) _port = serverPort;
    if (cloudTunnelUrl != null && cloudTunnelUrl.isNotEmpty) {
      _cloudTunnelUrl = cloudTunnelUrl.trim();
    }
    await _savePreferences();
    notifyListeners();
    reconnect();
  }

  Future<void> clearAuthCredentials() async {
    _authToken = null;
    _connectionState = MobileConnectionState.notPaired;
    _channel?.sink.close();
    _channel = null;
    _isConnected = false;
    _isConnecting = false;
    try {
      await _secureStorage.delete(key: 'mobile_auth_token');
    } catch (_) {}
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('mobile_auth_token');
    notifyListeners();
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
      '10.28.20.30', // Laptop current active Wi-Fi IP
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
        if (json['cloud_tunnel_url'] != null) {
          final t = (json['cloud_tunnel_url'] as String).trim();
          if (t.isNotEmpty) {
            _cloudTunnelUrl = t;
            _savePreferences();
          }
        }
        client.close();
        return true;
      }
      client.close();
    } catch (_) {}
    return false;
  }

  /// Explicitly queries Central System for active Cloudflare Tunnel URL across candidate hosts
  Future<String?> fetchCloudTunnel() async {
    final candidateHosts = [_host, '10.28.20.30', '10.28.20.11', '10.28.20.28', '127.0.0.1'];
    for (final h in candidateHosts) {
      try {
        final client = HttpClient()..connectionTimeout = const Duration(milliseconds: 1500);
        final req = await client.getUrl(Uri.parse('http://$h:$_port/api/cloud-tunnel'));
        final res = await req.close();
        if (res.statusCode == 200) {
          final body = await res.transform(utf8.decoder).join();
          final json = jsonDecode(body);
          if (json['cloud_tunnel_url'] != null) {
            final tunnel = (json['cloud_tunnel_url'] as String).trim();
            if (tunnel.isNotEmpty) {
              _cloudTunnelUrl = tunnel;
              _savePreferences();
              notifyListeners();
              client.close();
              return tunnel;
            }
          }
        }
        client.close();
      } catch (_) {}
    }

    // Fallback: try /api/cs-info
    for (final h in candidateHosts) {
      try {
        final client = HttpClient()..connectionTimeout = const Duration(milliseconds: 1500);
        final req = await client.getUrl(Uri.parse('http://$h:$_port/api/cs-info'));
        final res = await req.close();
        if (res.statusCode == 200) {
          final body = await res.transform(utf8.decoder).join();
          final json = jsonDecode(body);
          if (json['cloud_tunnel_url'] != null) {
            final tunnel = (json['cloud_tunnel_url'] as String).trim();
            if (tunnel.isNotEmpty) {
              _cloudTunnelUrl = tunnel;
              _savePreferences();
              notifyListeners();
              client.close();
              return tunnel;
            }
          }
        }
        client.close();
      } catch (_) {}
    }

    return _cloudTunnelUrl;
  }

  // --------------------------------------------------------------------------
  // WEBSOCKET LIFECYCLE & LOCAL-FIRST/REMOTE-FALLBACK CONNECTION ARCHITECTURE
  // --------------------------------------------------------------------------
  void reconnect() {
    _channel?.sink.close();
    _pingTimer?.cancel();
    _reconnectTimer?.cancel();
    _networkFallbackTimer?.cancel();
    _isConnected = false;
    _isConnecting = false;
    connect();
  }

  Future<bool> _probeHttp(String url, {int timeoutMs = 1500}) async {
    try {
      final client = HttpClient()..connectionTimeout = Duration(milliseconds: timeoutMs);
      final req = await client.getUrl(Uri.parse(url));
      final res = await req.close();
      final ok = (res.statusCode == 200);
      client.close();
      return ok;
    } catch (_) {
      return false;
    }
  }

  Future<void> connect() async {
    if (_isConnecting) return;
    if (!isPaired) {
      _isConnecting = false;
      _isConnected = false;
      _connectionState = MobileConnectionState.notPaired;
      _statusMessage = 'Not paired. Please pair with Central System.';
      notifyListeners();
      return;
    }

    _isConnecting = true;
    _connectionState = MobileConnectionState.connecting;
    _statusMessage = 'Resolving connection to Central System...';
    notifyListeners();

    // 1. Automatic Local-First vs Remote-Fallback selection:
    bool localOk = false;
    if (_host.isNotEmpty && _host != '0.0.0.0') {
      localOk = await _probeHttp('http://$_host:$_port/health', timeoutMs: 1200);
    }

    if (localOk) {
      _useCloudTunnel = false;
    } else if (_cloudTunnelUrl != null && _cloudTunnelUrl!.isNotEmpty) {
      final cleanTunnel = _cloudTunnelUrl!.startsWith('http') ? _cloudTunnelUrl! : 'https://$_cloudTunnelUrl';
      bool remoteOk = await _probeHttp('$cleanTunnel/health', timeoutMs: 2000);
      if (remoteOk) {
        _useCloudTunnel = true;
      }
    }

    final wsUri = getMobileWsUri();
    _statusMessage = 'Connecting to Central System (${_useCloudTunnel ? "Remote Tunnel" : "Local Wi-Fi"})...';
    notifyListeners();

    _fetchDevicesRest();
    _fetchCheckpointsRest();
    _fetchCloudTunnelRest();

    try {
      _channel = WebSocketChannel.connect(wsUri);

      _channel!.ready.then((_) {
        debugPrint('[MOBILE-WS] Socket connected. Transmitting authentication frame...');
        // Send initial auth frame with mobileId and authToken (not in URL)
        try {
          _channel?.sink.add(jsonEncode({
            'type': 'auth',
            'device_id': _mobileId,
            'token': _authToken,
          }));
        } catch (_) {}
        _startHeartbeat();
        _startNetworkSwitchWatchdog();
      }).catchError((err) {
        _connectionState = MobileConnectionState.disconnected;
        _handleDisconnect('Connection refused by CS ($err)');
      });

      _channel!.stream.listen(
        (data) {
          _onMessageReceived(data);
        },
        onError: (err) {
          _connectionState = MobileConnectionState.disconnected;
          _handleDisconnect('Socket error: $err');
        },
        onDone: () {
          _connectionState = MobileConnectionState.disconnected;
          _handleDisconnect('Central System disconnected');
        },
      );
    } catch (e) {
      _connectionState = MobileConnectionState.disconnected;
      _handleDisconnect('Failed: $e');
    }
  }

  void _startNetworkSwitchWatchdog() {
    _networkFallbackTimer?.cancel();
    // Every 15 seconds, check if network environment changed
    _networkFallbackTimer = Timer.periodic(const Duration(seconds: 15), (_) async {
      if (!_isConnected) return;
      if (_useCloudTunnel && _host.isNotEmpty) {
        // We are currently on remote tunnel; check if local campus Wi-Fi became available
        bool localAvailable = await _probeHttp('http://$_host:$_port/health', timeoutMs: 1200);
        if (localAvailable) {
          debugPrint('[NET] Local campus Wi-Fi detected! Seamlessly switching to local connection...');
          _useCloudTunnel = false;
          _savePreferences();
          reconnect();
        }
      }
    });
  }

  void _handleDisconnect(String reason) {
    _isConnected = false;
    _isConnecting = false;
    if (_connectionState != MobileConnectionState.authenticationFailed &&
        _connectionState != MobileConnectionState.revoked &&
        _connectionState != MobileConnectionState.notPaired) {
      _connectionState = MobileConnectionState.disconnected;
    }
    _statusMessage = reason;
    _pingTimer?.cancel();
    _networkFallbackTimer?.cancel();
    notifyListeners();

    if (isPaired &&
        _connectionState != MobileConnectionState.authenticationFailed &&
        _connectionState != MobileConnectionState.revoked &&
        _connectionState != MobileConnectionState.notPaired) {
      _reconnectTimer?.cancel();
      _reconnectTimer = Timer(const Duration(seconds: 4), () {
        if (!_isConnected) connect();
      });
    }
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
  // MOBILE PAIRING CREDENTIAL SUBMISSION & POLLING (QR / 8-DIGIT MANUAL CODE)
  // --------------------------------------------------------------------------
  Future<Map<String, dynamic>> submitPairingRequest({
    required String pairingCode,
    String? sessionId,
    String? serverIp,
    int? serverPort,
    String? cloudTunnelUrl,
    String? preferredRole,
    String? customDeviceName,
  }) async {
    _connectionState = MobileConnectionState.pairingPending;
    notifyListeners();
    final cleanCode = pairingCode.replaceAll(RegExp(r'[\s-]'), '').trim();
    final targetHost = (serverIp != null && serverIp.isNotEmpty) ? serverIp.trim() : _host;
    final targetPort = (serverPort != null && serverPort > 0) ? serverPort : _port;
    final targetTunnel = (cloudTunnelUrl != null && cloudTunnelUrl.isNotEmpty) ? cloudTunnelUrl.trim() : _cloudTunnelUrl;

    // Check candidate URLs in order: local first, then remote tunnel
    final candidateBases = <String>[];
    if (targetHost.isNotEmpty) {
      candidateBases.add('http://$targetHost:$targetPort');
    }
    if (targetTunnel != null && targetTunnel.isNotEmpty) {
      final cleanTunnel = targetTunnel.startsWith('http') ? targetTunnel : 'https://$targetTunnel';
      candidateBases.add(cleanTunnel);
    }
    if (candidateBases.isEmpty) {
      candidateBases.add('http://$_host:$_port');
    }

    final payload = {
      'pairing_code': cleanCode,
      if (sessionId != null && sessionId.isNotEmpty) 'session_id': sessionId,
      'device_id': _mobileId,
      'device_name': customDeviceName ?? 'Mobile Companion (${_mobileId.substring(_mobileId.length > 6 ? _mobileId.length - 6 : 0)})',
      'user_name': _userName,
      'role': preferredRole ?? _userRole,
    };

    String? lastError;
    for (final base in candidateBases) {
      try {
        final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
        final req = await client.postUrl(Uri.parse('$base/api/mobile-pairing/redeem'));
        req.headers.contentType = ContentType.json;
        req.write(jsonEncode(payload));
        final res = await req.close();
        final bodyStr = await res.transform(utf8.decoder).join();
        client.close();

        final parsed = jsonDecode(bodyStr) as Map<String, dynamic>;
        if (res.statusCode == 200) {
          // Update host/tunnel if this candidate succeeded
          if (base.contains('trycloudflare.com')) {
            _cloudTunnelUrl = base;
            _useCloudTunnel = true;
          } else {
            _host = targetHost;
            _port = targetPort;
            _useCloudTunnel = false;
          }
          _savePreferences();
          return parsed;
        } else {
          lastError = parsed['message'] ?? 'Pairing request rejected (${res.statusCode})';
          return parsed;
        }
      } catch (e) {
        lastError = 'Could not reach server at $base: $e';
      }
    }

    return {
      'status': 'error',
      'code': 'ERR_NETWORK',
      'message': lastError ?? 'Failed to reach Central System.',
    };
  }

  Future<Map<String, dynamic>> pollPairingStatus(String sessionId, {String? targetBaseUrl}) async {
    final candidateBases = <String>[];
    if (targetBaseUrl != null && targetBaseUrl.isNotEmpty) {
      candidateBases.add(targetBaseUrl);
    }
    if (_host.isNotEmpty) candidateBases.add('http://$_host:$_port');
    if (_cloudTunnelUrl != null && _cloudTunnelUrl!.isNotEmpty) {
      final t = _cloudTunnelUrl!.startsWith('http') ? _cloudTunnelUrl! : 'https://$_cloudTunnelUrl';
      candidateBases.add(t);
    }

    for (final base in candidateBases) {
      try {
        final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
        final req = await client.getUrl(Uri.parse('$base/api/mobile-pairing/status/$sessionId'));
        final res = await req.close();
        final bodyStr = await res.transform(utf8.decoder).join();
        client.close();

        if (res.statusCode == 200) {
          final parsed = jsonDecode(bodyStr) as Map<String, dynamic>;
          if (parsed['status'] == 'success' && parsed['state'] == 'approved' && parsed['auth_token'] != null) {
            final tok = parsed['auth_token'] as String;
            final devId = parsed['device_id'] as String? ?? _mobileId;
            final cs = parsed['cs_id'] as String? ?? _csId;
            final sIp = parsed['server_ip'] as String?;
            final sPort = parsed['server_port'] as int?;
            final cTun = parsed['cloud_tunnel_url'] as String?;
            await saveAuthCredentials(
              token: tok,
              deviceId: devId,
              csId: cs,
              serverIp: sIp,
              serverPort: sPort,
              cloudTunnelUrl: cTun,
            );
          }
          return parsed;
        }
      } catch (_) {}
    }

    return {'status': 'error', 'message': 'Unable to poll pairing status'};
  }

  // --------------------------------------------------------------------------
  // MESSAGE RECEIVER & INCIDENT STREAM
  // --------------------------------------------------------------------------
  void _onMessageReceived(dynamic rawData) {
    try {
      final json = jsonDecode(rawData.toString());
      final eventType = json['event_type'] ?? json['type'];

      if (eventType == 'auth_ok') {
        _isConnected = true;
        _isConnecting = false;
        _connectionState = MobileConnectionState.connected;
        _statusMessage = 'Authenticated with $csId';
        _fetchDevicesRest();
        _fetchCheckpointsRest();
        _fetchCloudTunnelRest();
        _syncWithCentralSystem();
        notifyListeners();
        return;
      }

      if (eventType == 'unauthorized' || json['type'] == 'unauthorized') {
        _connectionState = MobileConnectionState.authenticationFailed;
        _handleDisconnect('Authorization rejected: Device token invalid');
        return;
      }

      if (eventType == 'device_revoked' || json['type'] == 'device_revoked') {
        _connectionState = MobileConnectionState.revoked;
        clearAuthCredentials();
        return;
      }

      if (eventType == 'trigger_danger') {
        BlePinRelayService().sendCommandToPin('TRIGGER:DANGER');
      }

      if (eventType == 'mobile_sync_init') {
        _isConnected = true;
        _isConnecting = false;
        _connectionState = MobileConnectionState.connected;
        _csId = json['cs_id'] ?? _csId;
        _csName = json['name'] ?? _csName;
        if (json['role'] != null) _userRole = json['role'];
        if (json['cloud_tunnel_url'] != null) {
          final t = (json['cloud_tunnel_url'] as String).trim();
          if (t.isNotEmpty && t != _cloudTunnelUrl) {
            _cloudTunnelUrl = t;
            _savePreferences();
          }
        }
        if (json['devices'] != null) {
          for (final d in (json['devices'] as List)) {
            final dev = DeviceStatus.fromJson(d as Map<String, dynamic>);
            _devices[dev.id.toUpperCase()] = dev;
          }
        }
        if (json['recent_incidents'] != null) {
          for (final rawInc in (json['recent_incidents'] as List)) {
            final inc = IncidentReport.fromJson(rawInc as Map<String, dynamic>, host: _host, port: _port);
            if (!_seenIncidentIds.contains(inc.id)) {
              _seenIncidentIds.add(inc.id);
              if (_pairedPinIds.isEmpty || _pairedPinIds.contains(inc.deviceId.toUpperCase())) {
                _recentIncidents.add(inc);
              }
            }
          }
        }
        _statusMessage = 'Synced with $csId (${isDirectCloudTunnel ? "Remote" : "Local LAN"})';
        notifyListeners();
        return;
      }

      if (eventType == 'pin_registered' && json['device'] != null) {
        final dev = DeviceStatus.fromJson(json['device']);
        _devices[dev.id.toUpperCase()] = dev;
        notifyListeners();
        return;
      }

      if (eventType == 'device_update' && json['device'] != null) {
        final dev = DeviceStatus.fromJson(json['device']);
        _devices[dev.id.toUpperCase()] = dev;
        if (_pairedPinIds.contains(dev.id.toUpperCase())) {
          _savePreferences();
        }
        notifyListeners();
      } else if (eventType == 'cloud_tunnel_update' && json['cloud_tunnel_url'] != null) {
        final newUrl = json['cloud_tunnel_url'] as String?;
        if (newUrl != null && newUrl.isNotEmpty && newUrl != _cloudTunnelUrl) {
          _cloudTunnelUrl = newUrl;
          _savePreferences();
          notifyListeners();
        }
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
        if (json['cloud_tunnel_url'] != null) {
          final newUrl = json['cloud_tunnel_url'] as String?;
          if (newUrl != null && newUrl.isNotEmpty && newUrl != _cloudTunnelUrl) {
            _cloudTunnelUrl = newUrl;
            _savePreferences();
          }
        }
        notifyListeners();
      } else if (eventType == 'incident' || (eventType == 'incident_detected' && json['incident'] != null)) {
        final rawIncident = eventType == 'incident' ? json : json['incident'];
        final inc = IncidentReport.fromJson(rawIncident, host: _host, port: _port);
        // Deduplicate incidents across reconnects
        if (_seenIncidentIds.contains(inc.id)) {
          return;
        }
        _seenIncidentIds.add(inc.id);
        if (_pairedPinIds.isEmpty || _pairedPinIds.contains(inc.deviceId.toUpperCase())) {
          _recentIncidents.insert(0, inc);
          if (_recentIncidents.length > 50) _recentIncidents.removeLast();
          if (inc.isFlagged) {
            _latestAlert = inc;
          }
          notifyListeners();
        }
      } else if (eventType == 'snapshot_ready') {
        final targetIncId = json['incident_id'] as String?;
        final devId = json['device_id'] as String?;
        final rawSnapUrl = json['snapshot_url'] as String?;
        final sf = json['snapshot_file'] as String?;
        String? finalSnapUrl = (sf != null && sf.isNotEmpty)
            ? '$baseHttpUrl/recordings/snapshots/$sf'
            : rawSnapUrl;

        final idx = _recentIncidents.indexWhere((i) =>
          (targetIncId != null && targetIncId.isNotEmpty && i.id == targetIncId) ||
          (devId != null && i.deviceId.toUpperCase() == devId.toUpperCase() && (i.snapshotUrl == null || i.snapshotUrl!.isEmpty))
        );
        if (idx >= 0) {
          _recentIncidents[idx] = _recentIncidents[idx].copyWith(
            snapshotUrl: finalSnapUrl,
            snapshotFile: sf,
          );
          if (_latestAlert?.id == _recentIncidents[idx].id) {
            _latestAlert = _recentIncidents[idx];
          }
          notifyListeners();
        }
      }
    } catch (e) {
      debugPrint('[MOBILE_WS] Parse error: $e');
    }
  }

  Future<void> _fetchCloudTunnelRest() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(getApiUri('/cloud-tunnel'));
      final res = await req.close();
      if (res.statusCode == 200) {
        final body = await res.transform(utf8.decoder).join();
        final json = jsonDecode(body);
        if (json['cloud_tunnel_url'] != null) {
          final tunnel = json['cloud_tunnel_url'] as String;
          if (tunnel.isNotEmpty && tunnel != _cloudTunnelUrl) {
            _cloudTunnelUrl = tunnel;
            _savePreferences();
            notifyListeners();
          }
        }
      }
      client.close();
    } catch (_) {}
  }

  Future<void> _fetchCheckpointsRest() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.getUrl(getApiUri('/checkpoints'));
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
      final req = await client.getUrl(getApiUri('/devices'));
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

    // If device doesn't exist yet in cache, create registered entry awaiting real telemetry
    if (!_devices.containsKey(cleanId)) {
      _devices[cleanId] = DeviceStatus(
        id: cleanId,
        online: false,
        battery: 0,
        state: 'STANDBY',
        network: method.contains('Bluetooth') ? 'BLE Audio Bridge' : (_checkpoints.isNotEmpty ? _checkpoints.first.ssid : 'Campus Wi-Fi'),
        lastSeen: 'Paired just now ($method)',
        cpuMhz: 160,
        rssi: 0,
        estRuntime: '--',
      );
    }

    await _savePreferences();
    _syncWithCentralSystem();
    notifyListeners();
    return true;
  }

  void updatePinTelemetryFromBle({
    required String pinId,
    required int rssi,
    int? battery,
    int? batteryMv,
  }) {
    final cleanId = pinId.trim().toUpperCase();
    if (cleanId.isEmpty) return;

    final existing = _devices[cleanId];
    final bat = battery ?? existing?.battery ?? 0;
    final remMins = (bat / 100.0) * 315;
    final hours = remMins ~/ 60;
    final mins = (remMins % 60).toInt();

    _devices[cleanId] = DeviceStatus(
      id: cleanId,
      online: existing?.online ?? false, // Preserve direct Wi-Fi online status strictly
      battery: bat,
      state: existing?.state ?? 'VAD ARMED',
      network: existing?.network ?? 'BLE Audio Bridge',
      lastSeen: existing?.lastSeen ?? 'Active over BLE',
      cpuMhz: existing?.cpuMhz ?? 160,
      rssi: rssi,
      estRuntime: bat > 0 ? '${hours}h ${mins.toString().padLeft(2, '0')}m' : '--',
      bleProximity: true,
      relayedBy: _mobileId,
      lastBleSeen: 'Active over BLE just now',
    );
    notifyListeners();
  }

  void reportBleProximity({
    required String pinId,
    required int rssi,
    int? battery,
    int? batteryMv,
  }) {
    updatePinTelemetryFromBle(
      pinId: pinId,
      rssi: rssi,
      battery: battery,
      batteryMv: batteryMv,
    );

    if (_isConnected && _channel != null) {
      try {
        _channel!.sink.add(jsonEncode({
          'event_type': 'ble_relay_presence',
          'pin_id': pinId.trim().toUpperCase(),
          'mobile_id': _mobileId,
          'rssi': rssi,
          'battery': ?battery,
          'battery_mv': ?batteryMv,
          'timestamp': DateTime.now().toIso8601String(),
        }));
      } catch (e) {
        debugPrint('[RELAY-ERR] Failed to send ble_relay_presence: $e');
      }
    }
  }

  void relayBleAudio(String pinId, List<int> pcmBytes) {
    if (!_isConnected || _channel == null || pcmBytes.isEmpty) return;
    try {
      _channel!.sink.add(jsonEncode({
        'event_type': 'ble_relay_audio',
        'pin_id': pinId.trim().toUpperCase(),
        'mobile_id': _mobileId,
        'pcm_base64': base64Encode(pcmBytes),
      }));
    } catch (e) {
      debugPrint('[RELAY-ERR] Failed to relay audio: $e');
    }
  }

  void relayBleSnapshot(String pinId, Uint8List jpegBytes) {
    if (!_isConnected || _channel == null || jpegBytes.isEmpty) return;
    try {
      _channel!.sink.add(jsonEncode({
        'event_type': 'ble_relay_snapshot',
        'pin_id': pinId.trim().toUpperCase(),
        'mobile_id': _mobileId,
        'jpeg_base64': base64Encode(jpegBytes),
        'byte_length': jpegBytes.length,
        'timestamp': DateTime.now().toIso8601String(),
      }));
    } catch (e) {
      debugPrint('[RELAY-ERR] Failed to relay snapshot: $e');
    }
  }

  void relayBleCommand(String pinId, String command) {
    if (!_isConnected || _channel == null) return;
    try {
      _channel!.sink.add(jsonEncode({
        'event_type': 'ble_relay_command',
        'pin_id': pinId.trim().toUpperCase(),
        'mobile_id': _mobileId,
        'command': command,
      }));
    } catch (e) {
      debugPrint('[RELAY-ERR] Failed to relay command: $e');
    }
  }

  void reportBleDisconnected(String pinId) {
    final cleanId = pinId.trim().toUpperCase();
    if (_devices.containsKey(cleanId)) {
      _devices[cleanId] = _devices[cleanId]!.copyWith(
        bleProximity: false,
        lastBleSeen: 'BLE Disconnected',
      );
      notifyListeners();
    }
    if (_isConnected && _channel != null) {
      try {
        _channel!.sink.add(jsonEncode({
          'event_type': 'ble_relay_disconnect',
          'pin_id': cleanId,
          'mobile_id': _mobileId,
          'timestamp': DateTime.now().toIso8601String(),
        }));
      } catch (_) {}
    }
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

  /// Connects & pairs a pin over Bluetooth
  Future<bool> pairPinViaBluetooth({
    required String pinId,
    String? alias,
  }) async {
    final cleanId = pinId.trim().toUpperCase();
    return pairPin(cleanId, alias: alias, method: 'Bluetooth Low Energy');
  }

  /// Verifies if a Smart Pin is confirmed paired and registered with the Central System
  Future<bool> verifyPinPairingWithServer(String cleanCode, String devId) async {
    try {
      final upperId = devId.toUpperCase();
      // 1. In-memory devices check
      if (_devices.containsKey(upperId)) {
        return true;
      }
      // 2. Query code status REST endpoint
      if (cleanCode.isNotEmpty) {
        final codeUri = getApiUri('/pairing-code/status/$cleanCode');
        final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
        final req = await client.getUrl(codeUri);
        final res = await req.close();
        if (res.statusCode == 200) {
          final bodyStr = await res.transform(utf8.decoder).join();
          final data = jsonDecode(bodyStr);
          if (data['paired'] == true && (data['device_id'] == null || data['device_id'].toString().toUpperCase() == upperId)) {
            return true;
          }
        }
      }
      // 3. Query paired devices list
      final listUri = getApiUri('/devices/paired');
      final listClient = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final listReq = await listClient.getUrl(listUri);
      final listRes = await listReq.close();
      if (listRes.statusCode == 200) {
        final listBody = await listRes.transform(utf8.decoder).join();
        final listData = jsonDecode(listBody);
        if (listData['devices'] is List) {
          for (final d in listData['devices']) {
            if (d['device_id']?.toString().toUpperCase() == upperId) {
              return true;
            }
          }
        }
      }
    } catch (e) {
      debugPrint('[BLE-PROV] Error verifying pairing status with server: $e');
    }
    return false;
  }

  /// Complete button-free BLE onboarding & cryptographic provisioning workflow
  Future<Map<String, dynamic>> provisionPinViaBle({
    required BluetoothDevice device,
    required String ssid,
    required String password,
    required String pairingCode,
    String? alias,
    void Function(String stepMessage, double progress)? onProgress,
  }) async {
    final relay = BlePinRelayService();
    onProgress?.call('Connecting to Pin over BLE...', 0.15);

    final connected = await relay.connectToPin(device);
    if (!connected) {
      return {'success': false, 'error': 'Failed to connect to Smart Pin over BLE.'};
    }

    onProgress?.call('Connected! Querying pin identity...', 0.30);
    await relay.requestDeviceInfo();
    await Future.delayed(const Duration(milliseconds: 350));

    // Provide the active Central System base URL (Cloudflare HTTPS or LAN HTTP)
    final targetServerUrl = baseHttpUrl;
    debugPrint('[BLE-PROV] Using Central System URL for Pin: $targetServerUrl');
    onProgress?.call('Transmitting Wi-Fi & Pairing Code to Pin...', 0.45);

    final completer = Completer<Map<String, dynamic>>();
    final cleanCode = pairingCode.replaceAll(RegExp(r'[\s-]'), '').trim();

    StreamSubscription? sub;
    Timer? timeoutTimer = Timer(const Duration(seconds: 60), () async {
      if (!completer.isCompleted) {
        sub?.cancel();
        final devId = relay.pinnedDeviceId.toUpperCase();
        final isPaired = await verifyPinPairingWithServer(cleanCode, devId);
        if (isPaired) {
          await pairPin(devId, alias: alias, method: 'BLE Cryptographic Pairing');
          completer.complete({
            'success': true,
            'device_id': devId,
            'message': 'Smart Pin $devId successfully paired and authenticated with Central System!',
          });
          return;
        }
        completer.complete({
          'success': false,
          'error': 'Provisioning timed out after 60 seconds. Check Wi-Fi credentials or pairing code.',
        });
      }
    });

    sub = relay.provisioningEvents.listen((event) async {
      final type = event['type'];
      debugPrint('[BLE-WIZARD] Provisioning event: $event');

      if (type == 'provision_received') {
        onProgress?.call('Smart Pin received parameters. Initializing...', 0.50);
      } else if (type == 'wifi_connecting') {
        onProgress?.call('Smart Pin connecting to "${event['ssid'] ?? ssid}"...', 0.60);
      } else if (type == 'wifi_connected') {
        onProgress?.call('Wi-Fi connected (${event['ip'] ?? 'LAN'}). Validating pairing code with Central System...', 0.75);
      } else if (type == 'registration_pending' || type == 'pairing_pending') {
        onProgress?.call('Central System verifying single-use code...', 0.85);
      } else if (type == 'pairing_success') {
        timeoutTimer.cancel();
        sub?.cancel();
        final devId = (event['device_id'] ?? relay.pinnedDeviceId).toString().toUpperCase();
        await pairPin(devId, alias: alias, method: 'BLE Cryptographic Pairing');
        onProgress?.call('Pairing successful! Pin authenticated with Central System.', 1.0);
        if (!completer.isCompleted) {
          completer.complete({
            'success': true,
            'device_id': devId,
            'message': 'Smart Pin $devId successfully paired and authenticated!',
          });
        }
      } else if (type == 'provision_error') {
        final errCode = event['code'] as String? ?? 'ERR_UNKNOWN';
        String errMsg = event['message'] as String? ?? 'Provisioning failed';
        final devId = (event['device_id'] ?? relay.pinnedDeviceId).toString().toUpperCase();

        // If the error was WebSocket auth or timeout, verify if Central System already accepted & paired the device!
        if (errCode == 'ERR_WS_AUTH' || errCode == 'ERR_WS_TIMEOUT') {
          onProgress?.call('Verifying pairing confirmation with Central System...', 0.95);
          final isConfirmedOnServer = await verifyPinPairingWithServer(cleanCode, devId);
          if (isConfirmedOnServer) {
            timeoutTimer.cancel();
            sub?.cancel();
            await pairPin(devId, alias: alias, method: 'BLE Cryptographic Pairing');
            onProgress?.call('Pairing successful! Pin authenticated with Central System.', 1.0);
            if (!completer.isCompleted) {
              completer.complete({
                'success': true,
                'device_id': devId,
                'message': 'Smart Pin $devId successfully paired and authenticated!',
              });
            }
            return;
          }
        }

        timeoutTimer.cancel();
        sub?.cancel();
        if (errCode == 'ERR_AUTH_REJECTED' || errCode == 'ERR_WIFI_AUTH') {
          errMsg = 'Wi-Fi Authentication Failed: Password rejected by access point "${event['ssid'] ?? ssid}". Please check your Wi-Fi password.';
        } else if (errCode == 'ERR_AP_NOT_FOUND') {
          errMsg = 'Network Not Found: Access point "${event['ssid'] ?? ssid}" was not detected. Ensure it is a 2.4 GHz network in range.';
        } else if (errCode == 'ERR_DHCP_TIMEOUT') {
          errMsg = 'IP Assignment Failed: Associated with "${event['ssid'] ?? ssid}", but DHCP failed to assign an IP address. Check router DHCP settings.';
        } else if (errCode == 'ERR_WIFI_TIMEOUT') {
          errMsg = 'Wi-Fi Connection Timed Out: Unable to establish link with "${event['ssid'] ?? ssid}".';
        } else if (errCode == 'ERR_WIFI_UNSUPPORTED') {
          errMsg = 'Unsupported Network: ESP32-S3 supports 2.4 GHz Wi-Fi only (5 GHz-only is not supported).';
        } else if (errCode == 'ERR_PROVISIONING_INVALID') {
          errMsg = 'Invalid Provisioning: ${event['message'] ?? 'SSID or credentials missing.'}';
        } else if (errCode == 'ERR_SERVER_UNREACHABLE') {
          errMsg = 'Server Unreachable: Smart Pin connected to Wi-Fi, but could not contact Central System. Verify server IP/tunnel.';
        } else if (errCode == 'ERR_TUNNEL_DOWN') {
          errMsg = 'Cloudflare Tunnel Unreachable: Remote tunnel is down (HTTP 502/503). Ensure Cloudflare tunnel is active.';
        } else if (errCode == 'ERR_PAIRING_CODE' || errCode == 'ERR_INVALID_CODE') {
          errMsg = 'Pairing Code Rejected: ${event['message'] ?? 'Invalid or expired code.'}';
        } else if (errCode == 'ERR_NVS_FAILED') {
          errMsg = 'Hardware Storage Error: Smart Pin failed to save credentials to flash memory.';
        } else if (errCode == 'ERR_WS_AUTH') {
          errMsg = 'WebSocket Authentication Failed: Central System rejected pin credentials.';
        } else if (errCode == 'ERR_WS_TIMEOUT') {
          errMsg = 'WebSocket Connection Timed Out: Smart Pin connected to Wi-Fi but timed out contacting Central System.';
        }
        if (!completer.isCompleted) {
          completer.complete({
            'success': false,
            'code': errCode,
            'error': errMsg,
          });
        }
      }
    });

    // Send provisioning JSON command over BLE RX
    final sendResult = await relay.sendProvisioningCommand(
      ssid: ssid,
      password: password,
      pairingCode: pairingCode,
      serverUrl: targetServerUrl,
    );

    if (!sendResult.success) {
      timeoutTimer.cancel();
      sub.cancel();
      return {
        'success': false,
        'code': sendResult.errorCode ?? 'ERR_BLE_WRITE',
        'error': 'BLE Transmission Failed: ${sendResult.errorMessage ?? "Could not write to RX characteristic"}',
      };
    }

    return completer.future;
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
      final req = await client.postUrl(getApiUri('/checkpoints/deploy'));
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
      final req = await client.postUrl(getApiUri('/checkpoints'));
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
      final req = await client.deleteUrl(getApiUri('/checkpoints/$chkId'));
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
      client.postUrl(getApiUri('/toggle-harmful-only')).then((req) {
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
