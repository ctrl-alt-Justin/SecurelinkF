import 'package:flutter/material.dart';
import '../models/device_model.dart';
import '../services/mobile_server_service.dart';
import '../widgets/mobile_components.dart';

class BatteryTrackerScreen extends StatefulWidget {
  final MobileServerService service;

  const BatteryTrackerScreen({super.key, required this.service});

  @override
  State<BatteryTrackerScreen> createState() => _BatteryTrackerScreenState();
}

class _BatteryTrackerScreenState extends State<BatteryTrackerScreen> {
  String _sortMode = 'LOWEST_FIRST';

  List<DeviceStatus> get _targetPool {
    if (widget.service.pairedDevices.isNotEmpty) {
      return widget.service.pairedDevices;
    }
    return widget.service.allDevices;
  }

  List<DeviceStatus> get _sortedDevices {
    final list = List<DeviceStatus>.from(_targetPool);
    if (_sortMode == 'LOWEST_FIRST') {
      list.sort((a, b) => a.battery.compareTo(b.battery));
    } else if (_sortMode == 'HIGHEST_FIRST') {
      list.sort((a, b) => b.battery.compareTo(a.battery));
    } else {
      list.sort((a, b) => a.id.compareTo(b.id));
    }
    return list;
  }

  double get _fleetAverageBattery {
    final pool = _targetPool;
    if (pool.isEmpty) return 0.0;
    final total = pool.fold<int>(0, (sum, d) => sum + d.battery);
    return total / pool.length;
  }

  @override
  Widget build(BuildContext context) {
    final devices = _sortedDevices;
    final hasDevices = devices.isNotEmpty;
    final avgBatt = _fleetAverageBattery;
    final lowBattPins = devices.where((d) => d.isLowBattery).toList();

    return RefreshIndicator(
      color: MobileDesignSystem.primaryGreen,
      backgroundColor: const Color(0xFF0E151A),
      onRefresh: () async {
        widget.service.reconnect();
      },
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        children: [
          // Fleet Power Summary Banner
          MobileGlassCard(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(7),
                          decoration: BoxDecoration(
                            color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.16),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(Icons.battery_charging_full_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
                        ),
                        const SizedBox(width: 8),
                        const Text(
                          'Fleet Battery Telemetry',
                          style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w800),
                        ),
                      ],
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.06),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        '250mAh LiPo Cell',
                        style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 10, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    // Average Circular Ring Indicator
                    Stack(
                      alignment: Alignment.center,
                      children: [
                        SizedBox(
                          width: 68,
                          height: 68,
                          child: CircularProgressIndicator(
                            value: hasDevices ? (avgBatt / 100.0).clamp(0.0, 1.0) : 0.0,
                            strokeWidth: 6,
                            backgroundColor: Colors.white.withValues(alpha: 0.08),
                            color: !hasDevices
                                ? Colors.white24
                                : avgBatt <= 20
                                    ? MobileDesignSystem.statusDanger
                                    : avgBatt <= 45
                                        ? MobileDesignSystem.statusWarning
                                        : MobileDesignSystem.primaryGreen,
                          ),
                        ),
                        Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              hasDevices ? '${avgBatt.round()}%' : '--',
                              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: Colors.white),
                            ),
                            Text(
                              'AVG',
                              style: TextStyle(fontSize: 8.5, color: Colors.white.withValues(alpha: 0.45), fontWeight: FontWeight.w700),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Active Fleet Lifespan',
                            style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontSize: 11),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            hasDevices ? '~6 to 8 Hours Continuous' : 'Awaiting Connected Pins',
                            style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '160MHz Balanced Low-Power VAD (~45mA Standby)',
                            style: TextStyle(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.85), fontSize: 10),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          // Low Battery Alert Card (if any real pin <= 20%)
          if (lowBattPins.isNotEmpty) ...[
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: MobileDesignSystem.statusDanger.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: MobileDesignSystem.statusDanger.withValues(alpha: 0.35)),
              ),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: MobileDesignSystem.statusDanger.withValues(alpha: 0.2),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.warning_amber_rounded, color: MobileDesignSystem.statusDanger, size: 20),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${lowBattPins.length} Pin(s) Require Charging',
                          style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          'Pins ${lowBattPins.map((p) => p.id).join(', ')} are below 20% battery. Recharge before campus deployment.',
                          style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 10.5),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: 18),

          // Section Header & Sort Mode
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Tracked Pins (${devices.length})',
                style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w800),
              ),
              if (hasDevices)
                DropdownButton<String>(
                  value: _sortMode,
                  dropdownColor: const Color(0xFF141923),
                  icon: const Icon(Icons.sort_rounded, color: MobileDesignSystem.accentMint, size: 18),
                  underline: const SizedBox(),
                  style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600),
                  items: const [
                    DropdownMenuItem(value: 'LOWEST_FIRST', child: Text('Lowest Battery')),
                    DropdownMenuItem(value: 'HIGHEST_FIRST', child: Text('Highest Battery')),
                    DropdownMenuItem(value: 'NAME', child: Text('Pin ID')),
                  ],
                  onChanged: (v) {
                    if (v != null) setState(() => _sortMode = v);
                  },
                ),
            ],
          ),

          const SizedBox(height: 10),

          // Zero-State or Individual Real Pin Battery Cards
          if (!hasDevices)
            MobileGlassCard(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
              child: Column(
                children: [
                  Container(
                    width: 60,
                    height: 60,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Colors.white.withValues(alpha: 0.05),
                    ),
                    child: const Icon(
                      Icons.battery_unknown_rounded,
                      color: Colors.white38,
                      size: 28,
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'No Battery Telemetry Yet',
                    style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Real battery life percentages and estimated runtimes will update continuously once smart pins connect to this server.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11.5, height: 1.4),
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton.icon(
                    onPressed: () {
                      showModalBottomSheet(
                        context: context,
                        isScrollControlled: true,
                        backgroundColor: const Color(0xFF0E151A),
                        shape: const RoundedRectangleBorder(
                          borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
                        ),
                        builder: (ctx) => PairPinModal(
                          service: widget.service,
                          onPaired: () => setState(() {}),
                        ),
                      );
                    },
                    icon: const Icon(Icons.add_link_rounded, size: 16),
                    label: const Text('Pair Smart Pin', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: MobileDesignSystem.primaryGreen,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                ],
              ),
            )
          else
            ...devices.map(
              (dev) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: MobileGlassCard(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 44,
                            height: 44,
                            decoration: BoxDecoration(
                              color: dev.batteryColor.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: dev.batteryColor.withValues(alpha: 0.3)),
                            ),
                            child: Icon(dev.batteryIcon, color: dev.batteryColor, size: 24),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  dev.id,
                                  style: const TextStyle(color: Colors.white, fontSize: 15.5, fontWeight: FontWeight.w800),
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  dev.powerProfile,
                                  style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10),
                                ),
                              ],
                            ),
                          ),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                '${dev.battery}%',
                                style: TextStyle(
                                  color: dev.batteryColor,
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                              Text(
                                dev.estRuntime,
                                style: TextStyle(color: Colors.white.withValues(alpha: 0.45), fontSize: 10, fontWeight: FontWeight.w600),
                              ),
                            ],
                          ),
                        ],
                      ),

                      const SizedBox(height: 14),

                      // Multi-segmented Battery Level Indicator
                      ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: LinearProgressIndicator(
                          value: (dev.battery.clamp(0, 100)) / 100.0,
                          minHeight: 8,
                          backgroundColor: Colors.white.withValues(alpha: 0.06),
                          valueColor: AlwaysStoppedAnimation<Color>(dev.batteryColor),
                        ),
                      ),

                      const SizedBox(height: 14),

                      // Diagnostic telemetry metrics
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.03),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            _specMetric('Voltage', '${dev.voltageEstimate}V'),
                            _specMetric('Hardware', 'ESP32S3'),
                            _specMetric('Wi-Fi RSSI', '${dev.rssi} dBm'),
                            _specMetric('Power Health', dev.isLowBattery ? 'Low Battery' : 'Optimal'),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _specMetric(String label, String value) {
    return Column(
      children: [
        Text(label, style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 9)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(color: Colors.white, fontSize: 10.5, fontWeight: FontWeight.w700)),
      ],
    );
  }
}
