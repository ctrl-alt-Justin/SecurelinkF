import 'package:flutter/material.dart';

class DeviceStatus {
  final String id;
  final bool online;
  final int battery;
  final String state;
  final String network;
  final String lastSeen;
  final int cpuMhz;
  final int rssi;
  final String estRuntime;
  final String? ipAddress;
  final String? connectionSource;
  final bool bleProximity;
  final String? relayedBy;
  final String? lastBleSeen;

  const DeviceStatus({
    required this.id,
    required this.online,
    required this.battery,
    required this.state,
    required this.network,
    required this.lastSeen,
    this.cpuMhz = 160,
    this.rssi = -62,
    this.estRuntime = '6h 30m',
    this.ipAddress,
    this.connectionSource,
    this.bleProximity = false,
    this.relayedBy,
    this.lastBleSeen,
  });

  factory DeviceStatus.fromJson(Map<String, dynamic> json) {
    int batt = -1;
    final rawBatt = json['battery'];
    if (rawBatt is int) {
      batt = rawBatt >= 0 ? rawBatt.clamp(0, 100) : -1;
    } else if (rawBatt != null) {
      final parsed = int.tryParse('$rawBatt');
      if (parsed != null) {
        batt = parsed >= 0 ? parsed.clamp(0, 100) : -1;
      }
    }

    String runtime = '--';
    if (batt >= 0) {
      final hours = (batt / 100.0 * 7.5);
      final h = hours.floor();
      final m = ((hours - h) * 60).round();
      runtime = '${h}h ${m}m';
    }

    return DeviceStatus(
      id: json['id'] as String? ?? 'PIN-001',
      online: json['online'] as bool? ?? false,
      battery: batt,
      state: json['state'] as String? ?? 'STANDBY',
      network: json['network'] as String? ?? 'Campus Wi-Fi',
      lastSeen: json['lastSeen'] as String? ?? 'Just now',
      cpuMhz: json['cpuMhz'] as int? ?? 160,
      rssi: json['rssi'] as int? ?? -62,
      estRuntime: json['estRuntime'] as String? ?? runtime,
      ipAddress: json['ip'] as String?,
      connectionSource: json['connection_source'] as String?,
      bleProximity: json['ble_proximity'] as bool? ?? false,
      relayedBy: json['relayed_by'] as String?,
      lastBleSeen: json['last_ble_seen'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'online': online,
    'battery': battery,
    'state': state,
    'network': network,
    'lastSeen': lastSeen,
    'cpuMhz': cpuMhz,
    'rssi': rssi,
    'estRuntime': estRuntime,
    'ip': ipAddress,
    'connection_source': connectionSource,
    'ble_proximity': bleProximity,
    'relayed_by': relayedBy,
    'last_ble_seen': lastBleSeen,
  };

  DeviceStatus copyWith({
    String? id,
    bool? online,
    int? battery,
    String? state,
    String? network,
    String? lastSeen,
    int? cpuMhz,
    int? rssi,
    String? estRuntime,
    String? ipAddress,
    String? connectionSource,
    bool? bleProximity,
    String? relayedBy,
    String? lastBleSeen,
  }) {
    return DeviceStatus(
      id: id ?? this.id,
      online: online ?? this.online,
      battery: battery ?? this.battery,
      state: state ?? this.state,
      network: network ?? this.network,
      lastSeen: lastSeen ?? this.lastSeen,
      cpuMhz: cpuMhz ?? this.cpuMhz,
      rssi: rssi ?? this.rssi,
      estRuntime: estRuntime ?? this.estRuntime,
      ipAddress: ipAddress ?? this.ipAddress,
      connectionSource: connectionSource ?? this.connectionSource,
      bleProximity: bleProximity ?? this.bleProximity,
      relayedBy: relayedBy ?? this.relayedBy,
      lastBleSeen: lastBleSeen ?? this.lastBleSeen,
    );
  }

  bool get isBatteryValid => battery >= 0;
  bool get isLowBattery => isBatteryValid && battery <= 20;
  bool get isCriticalBattery => isBatteryValid && battery <= 10;

  String get batteryFormatted => isBatteryValid ? '$battery%' : '--';
  String get batteryWithRuntime => isBatteryValid ? '$battery% ($estRuntime)' : 'Telemetry Pending';

  Color get batteryColor {
    if (!isBatteryValid) return const Color(0xFF9CA3AF);
    if (isCriticalBattery) return const Color(0xFFFF3B5C);
    if (isLowBattery) return const Color(0xFFFF5E72);
    if (battery <= 45) return const Color(0xFFFFB800);
    return const Color(0xFF55E2C0);
  }

  IconData get batteryIcon {
    if (!isBatteryValid) return Icons.battery_unknown_rounded;
    if (battery >= 90) return Icons.battery_full_rounded;
    if (battery >= 75) return Icons.battery_6_bar_rounded;
    if (battery >= 50) return Icons.battery_4_bar_rounded;
    if (battery >= 25) return Icons.battery_2_bar_rounded;
    if (battery >= 10) return Icons.battery_1_bar_rounded;
    return Icons.battery_alert_rounded;
  }

  Color get stateColor {
    if (!online) return const Color(0xFF6B7280);
    final upper = state.toUpperCase();
    if (upper.contains('STREAMING')) return const Color(0xFF00E5FF);
    if (upper.contains('ANALYZING') || upper.contains('WHISPER')) return const Color(0xFFA78BFA);
    if (upper.contains('UPDATING')) return const Color(0xFFFFB800);
    return const Color(0xFF55E2C0);
  }

  String get powerProfile {
    if (cpuMhz <= 80) return '80 MHz Eco Standby (~25mA)';
    if (cpuMhz <= 160) return '160 MHz Standard (~55mA)';
    return '240 MHz High Performance (~110mA)';
  }

  String get signalQuality {
    if (rssi >= -50) return 'Excellent';
    if (rssi >= -65) return 'Good';
    if (rssi >= -78) return 'Fair';
    return 'Weak';
  }

  double get voltageEstimate {
    if (!isBatteryValid) return 3.70;
    // 3.7V - 4.2V LiPo curve estimation
    final v = 3.45 + (battery / 100.0) * 0.75;
    return double.parse(v.toStringAsFixed(2));
  }

  String get voltageDisplay {
    if (!isBatteryValid) return '-- V';
    return '${voltageEstimate.toStringAsFixed(2)}V (LiPo)';
  }
}

class WifiCheckpoint {
  final String id;
  final String name;
  final String ssid;
  final String pass;
  final String serverIp;
  final int serverPort;
  final bool isDefault;
  final String? lastDeployed;

  const WifiCheckpoint({
    required this.id,
    required this.name,
    required this.ssid,
    required this.pass,
    required this.serverIp,
    this.serverPort = 8080,
    this.isDefault = false,
    this.lastDeployed,
  });

  factory WifiCheckpoint.fromJson(Map<String, dynamic> json) => WifiCheckpoint(
    id: json['id'] as String? ?? 'chk_${DateTime.now().millisecondsSinceEpoch}',
    name: json['name'] as String? ?? 'Campus AP',
    ssid: json['ssid'] as String? ?? '',
    pass: json['pass'] as String? ?? '',
    serverIp: json['server_ip'] as String? ?? '10.28.20.28',
    serverPort: json['server_port'] as int? ?? 8080,
    isDefault: json['is_default'] as bool? ?? false,
    lastDeployed: json['last_deployed'] as String?,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'ssid': ssid,
    'pass': pass,
    'server_ip': serverIp,
    'server_port': serverPort,
    'is_default': isDefault,
    if (lastDeployed != null) 'last_deployed': lastDeployed,
  };

  WifiCheckpoint copyWith({
    String? id,
    String? name,
    String? ssid,
    String? pass,
    String? serverIp,
    int? serverPort,
    bool? isDefault,
    String? lastDeployed,
  }) {
    return WifiCheckpoint(
      id: id ?? this.id,
      name: name ?? this.name,
      ssid: ssid ?? this.ssid,
      pass: pass ?? this.pass,
      serverIp: serverIp ?? this.serverIp,
      serverPort: serverPort ?? this.serverPort,
      isDefault: isDefault ?? this.isDefault,
      lastDeployed: lastDeployed ?? this.lastDeployed,
    );
  }
}
