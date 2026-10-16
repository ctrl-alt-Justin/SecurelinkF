import 'package:flutter/material.dart';
import '../models/device_model.dart';
import '../services/mobile_server_service.dart';
import '../widgets/mobile_components.dart';

class PinsOverviewScreen extends StatefulWidget {
  final MobileServerService service;
  final Function(WifiCheckpoint chk, String target) onDeployCheckpoint;

  const PinsOverviewScreen({
    super.key,
    required this.service,
    required this.onDeployCheckpoint,
  });

  @override
  State<PinsOverviewScreen> createState() => _PinsOverviewScreenState();
}

class _PinsOverviewScreenState extends State<PinsOverviewScreen> {
  String _filter = 'ALL';
  String _searchQuery = '';
  bool _viewAllFleet = false;

  @override
  void initState() {
    super.initState();
    // At first open, actively look for smart pins
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (widget.service.pairedDevices.isEmpty) {
        widget.service.searchForSmartPins();
      }
    });
  }

  List<DeviceStatus> get _targetDevicePool {
    if (_viewAllFleet) {
      return widget.service.allDevices;
    }
    // Auto-show discovered devices if none are explicitly paired yet
    if (widget.service.pairedDevices.isEmpty && widget.service.allDevices.isNotEmpty) {
      return widget.service.allDevices;
    }
    return widget.service.pairedDevices;
  }

  List<DeviceStatus> get _filteredDevices {
    return _targetDevicePool.where((d) {
      if (_filter == 'ONLINE' && !d.online) return false;
      if (_filter == 'STANDBY' && (!d.online || !d.state.toUpperCase().contains('VAD'))) return false;
      if (_filter == 'OFFLINE' && d.online) return false;
      if (_searchQuery.isNotEmpty) {
        final q = _searchQuery.toLowerCase();
        final alias = widget.service.getPinAlias(d.id)?.toLowerCase() ?? '';
        return d.id.toLowerCase().contains(q) || d.network.toLowerCase().contains(q) || alias.contains(q);
      }
      return true;
    }).toList();
  }

  void _openPairModal() {
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
  }

  void _showPinDetailsSheet(DeviceStatus dev) {
    final alias = widget.service.getPinAlias(dev.id);
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0F1422),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 50,
                  height: 50,
                  decoration: BoxDecoration(
                    color: dev.stateColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: dev.stateColor.withValues(alpha: 0.3)),
                  ),
                  child: Icon(Icons.sensors_rounded, color: dev.stateColor, size: 26),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        dev.id,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      if (alias != null) ...[
                        const SizedBox(height: 1),
                        Text(
                          alias,
                          style: const TextStyle(
                            color: MobileDesignSystem.primaryGreenMint,
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                      const SizedBox(height: 2),
                      Text(
                        'Seeed XIAO ESP32S3 Sense • PDM Mic & Camera',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.5),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                MobileStatusPill(online: dev.online, state: dev.state),
              ],
            ),
            const SizedBox(height: 16),

            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.035),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: Colors.white.withValues(alpha: 0.07)),
              ),
              child: Column(
                children: [
                  _specRow('Operating State', dev.state, dev.stateColor),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('Battery Level', '${dev.battery}% (${dev.estRuntime})', dev.batteryColor),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('Voltage Nominal', '${dev.voltageEstimate}V (LiPo)', Colors.white),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('Connected Network', dev.network, Colors.white),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('Signal Strength', '${dev.rssi} dBm (${dev.signalQuality})', MobileDesignSystem.accentCyan),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('CPU Clock Mode', '${dev.cpuMhz} MHz (Balanced Clock)', MobileDesignSystem.accentIndigo),
                  const Divider(color: Colors.white10, height: 16),
                  _specRow('Last Heartbeat', dev.lastSeen, Colors.white60),
                ],
              ),
            ),
            const SizedBox(height: 20),

            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _showRenamePinDialog(dev);
                    },
                    icon: const Icon(Icons.edit_note_rounded, size: 18),
                    label: const Text('Rename Pin', style: TextStyle(fontWeight: FontWeight.w700)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: MobileDesignSystem.primaryGreenMint,
                      side: const BorderSide(color: MobileDesignSystem.primaryGreenMint),
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _showQuickDeployModal(dev);
                    },
                    icon: const Icon(Icons.wifi_tethering_rounded, size: 17),
                    label: const Text('Push Wi-Fi', style: TextStyle(fontWeight: FontWeight.w800)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: MobileDesignSystem.primaryGreen,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Delete & Unpair Pin Button
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.pop(ctx);
                  _confirmDeletePin(dev);
                },
                icon: const Icon(Icons.delete_forever_rounded, size: 17, color: Color(0xFFFF5E72)),
                label: const Text(
                  'Delete & Unpair Pin',
                  style: TextStyle(color: Color(0xFFFF5E72), fontSize: 13, fontWeight: FontWeight.w700),
                ),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(color: const Color(0xFFFF5E72).withValues(alpha: 0.40)),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showRenamePinDialog(DeviceStatus dev) {
    final currentAlias = widget.service.getPinAlias(dev.id) ?? '';
    final controller = TextEditingController(text: currentAlias);

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF101622),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.edit_note_rounded, color: MobileDesignSystem.primaryGreenMint, size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Rename Pin',
                    style: TextStyle(color: Colors.white, fontSize: 16.5, fontWeight: FontWeight.w800),
                  ),
                  Text(
                    dev.id,
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11),
                  ),
                ],
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Assign a friendly alias or student identifier for this smart pin badge.',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.72), fontSize: 12.5, height: 1.4),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              autofocus: true,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'e.g. Student Alex, Room 101, Badge A',
                hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 13),
                prefixIcon: const Icon(Icons.badge_rounded, color: MobileDesignSystem.primaryGreenMint, size: 20),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.05),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: MobileDesignSystem.primaryGreenMint),
                ),
              ),
            ),
          ],
        ),
        actions: [
          if (currentAlias.isNotEmpty)
            TextButton(
              onPressed: () async {
                Navigator.pop(ctx);
                await widget.service.renamePin(dev.id, '');
                if (mounted) {
                  setState(() {});
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      backgroundColor: const Color(0xFF131722),
                      content: Text('Alias removed for ${dev.id}.'),
                      duration: const Duration(seconds: 2),
                    ),
                  );
                }
              },
              child: const Text('Reset', style: TextStyle(color: Color(0xFFFF5E72), fontWeight: FontWeight.w600)),
            ),
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Cancel', style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontWeight: FontWeight.w600)),
          ),
          ElevatedButton(
            onPressed: () async {
              final newName = controller.text.trim();
              Navigator.pop(ctx);
              await widget.service.renamePin(dev.id, newName);
              if (mounted) {
                setState(() {});
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    backgroundColor: const Color(0xFF131722),
                    content: Text(
                      newName.isEmpty
                          ? 'Reset pin name to ${dev.id}'
                          : 'Renamed ${dev.id} to "$newName"',
                    ),
                    duration: const Duration(seconds: 2),
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: MobileDesignSystem.primaryGreen,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              elevation: 2,
            ),
            child: const Text('Save Name', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  void _confirmDeletePin(DeviceStatus dev) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF101622),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFFF5E72).withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.delete_forever_rounded, color: Color(0xFFFF5E72), size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                'Delete ${dev.id}?',
                style: const TextStyle(color: Colors.white, fontSize: 16.5, fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ),
        content: Text(
          'Are you sure you want to delete and unpair ${dev.id} from your mobile companion? This badge will be removed from your active pins list.',
          style: TextStyle(color: Colors.white.withValues(alpha: 0.72), fontSize: 12.5, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Cancel', style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontWeight: FontWeight.w600)),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await widget.service.deletePin(dev.id);
              if (mounted) {
                setState(() {});
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    backgroundColor: const Color(0xFF131722),
                    content: Text('Pin ${dev.id} deleted successfully.'),
                    duration: const Duration(seconds: 3),
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFFF5E72),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              elevation: 2,
            ),
            child: const Text('Delete Pin', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  void _showPairPinQuickDialog(DeviceStatus dev) {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF101622),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.add_link_rounded, color: MobileDesignSystem.primaryGreenMint, size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Pair ${dev.id}', style: const TextStyle(color: Colors.white, fontSize: 16.5, fontWeight: FontWeight.w800)),
                  Text(dev.network, style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                ],
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Assign a student name or identifier for this smart pin (optional):', style: TextStyle(color: Colors.white.withValues(alpha: 0.72), fontSize: 12.5)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autofocus: true,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'e.g. Student Alex, Room 101, Badge A',
                hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 13),
                prefixIcon: const Icon(Icons.person_rounded, color: MobileDesignSystem.primaryGreenMint, size: 20),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.05),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Cancel', style: TextStyle(color: Colors.white.withValues(alpha: 0.55))),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await widget.service.pairPin(dev.id, alias: controller.text.trim());
              if (mounted) {
                setState(() {});
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    backgroundColor: const Color(0xFF131722),
                    content: Text('Pin ${dev.id} paired to ${widget.service.userName}!'),
                    duration: const Duration(seconds: 2),
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: MobileDesignSystem.primaryGreen,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: const Text('Confirm Pair'),
          ),
        ],
      ),
    );
  }

  void _showQuickDeployModal(DeviceStatus dev) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0F1422),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Deploy Wi-Fi to ${dev.id}',
                  style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                ),
                IconButton(
                  onPressed: () => Navigator.pop(ctx),
                  icon: const Icon(Icons.close_rounded, color: Colors.white60),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Select a saved campus Wi-Fi checkpoint to push to this pin over-the-air.',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12),
            ),
            const SizedBox(height: 16),
            if (widget.service.checkpoints.isEmpty)
              Container(
                padding: const EdgeInsets.all(20),
                alignment: Alignment.center,
                child: Text(
                  'No saved campus checkpoints yet. Add one in the "Wi-Fi Config" tab.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 12),
                ),
              )
            else
              ...widget.service.checkpoints.map(
                (chk) => ListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  tileColor: Colors.white.withValues(alpha: 0.04),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  leading: const Icon(Icons.wifi_tethering_rounded, color: MobileDesignSystem.primaryGreenMint),
                  title: Text(chk.name, style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700)),
                  subtitle: Text('SSID: ${chk.ssid}', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                  trailing: ElevatedButton(
                    onPressed: () {
                      widget.onDeployCheckpoint(chk, dev.id);
                      Navigator.pop(ctx);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: MobileDesignSystem.primaryGreen,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    child: const Text('Push', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800)),
                  ),
                ),
              ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }

  Widget _specRow(String title, String value, Color valColor) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(title, style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 12)),
        Text(value, style: TextStyle(color: valColor, fontSize: 12, fontWeight: FontWeight.w700)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final devices = _filteredDevices;
    final total = _targetDevicePool.length;
    final online = _targetDevicePool.where((d) => d.online).length;
    final standby = _targetDevicePool.where((d) => d.online && d.state.toUpperCase().contains('VAD')).length;
    final offline = total - online;
    final incidents = widget.service.pairedIncidents;

    return RefreshIndicator(
      color: MobileDesignSystem.primaryGreen,
      backgroundColor: const Color(0xFF0E151A),
      onRefresh: () async {
        await widget.service.searchForSmartPins();
        widget.service.reconnect();
      },
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        children: [
          // Clean Modern System Header (Teachers/Students text & Priority badge removed)
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Smart Wearable Pins',
                    style: TextStyle(color: Colors.white, fontSize: 17.5, fontWeight: FontWeight.w900, letterSpacing: -0.3),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    widget.service.isConnected
                        ? 'Central System Active • ${widget.service.csId}'
                        : 'Central System Offline (Tap to reconnect)',
                    style: TextStyle(
                      color: widget.service.isConnected ? MobileDesignSystem.primaryGreenMint : MobileDesignSystem.statusWarning,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4.5),
                decoration: BoxDecoration(
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.35)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        color: widget.service.isConnected ? MobileDesignSystem.primaryGreenMint : MobileDesignSystem.statusWarning,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 5),
                    Text(
                      '$online LIVE / $total TOTAL',
                      style: const TextStyle(
                        color: MobileDesignSystem.primaryGreenMint,
                        fontSize: 9.5,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.4,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Harmful Words Filter Control Card
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              gradient: widget.service.harmfulWordsOnly
                  ? const LinearGradient(
                      colors: [Color(0xFF0F3B2E), Color(0xFF07211A)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    )
                  : LinearGradient(
                      colors: [const Color(0xFF131B26), const Color(0xFF0B1017)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: widget.service.harmfulWordsOnly
                    ? MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.5)
                    : Colors.white.withValues(alpha: 0.08),
                width: widget.service.harmfulWordsOnly ? 1.2 : 1.0,
              ),
              boxShadow: widget.service.harmfulWordsOnly
                  ? [
                      BoxShadow(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25),
                        blurRadius: 12,
                        offset: const Offset(0, 3),
                      )
                    ]
                  : null,
            ),
            child: Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: widget.service.harmfulWordsOnly
                        ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)
                        : Colors.white.withValues(alpha: 0.05),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: widget.service.harmfulWordsOnly
                          ? MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.45)
                          : Colors.white.withValues(alpha: 0.1),
                    ),
                  ),
                  child: Icon(
                    widget.service.harmfulWordsOnly ? Icons.security_rounded : Icons.record_voice_over_rounded,
                    color: widget.service.harmfulWordsOnly ? MobileDesignSystem.primaryGreenMint : Colors.white60,
                    size: 19,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            widget.service.harmfulWordsOnly ? 'HARMFUL WORDS ONLY' : 'ALL SPEECH MONITORED',
                            style: TextStyle(
                              color: widget.service.harmfulWordsOnly ? Colors.white : Colors.white.withValues(alpha: 0.9),
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 0.3,
                            ),
                          ),
                          const SizedBox(width: 6),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                            decoration: BoxDecoration(
                              color: widget.service.harmfulWordsOnly
                                  ? MobileDesignSystem.primaryGreen
                                  : Colors.white.withValues(alpha: 0.1),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(
                              widget.service.harmfulWordsOnly ? 'FILTER ON' : 'ALL',
                              style: const TextStyle(color: Colors.white, fontSize: 8.5, fontWeight: FontWeight.w800),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        widget.service.harmfulWordsOnly
                            ? 'Detecting only threats, harassment & harmful keywords'
                            : 'Logging all conversation (tap switch to filter threats only)',
                        style: TextStyle(
                          color: widget.service.harmfulWordsOnly
                              ? MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.85)
                              : Colors.white.withValues(alpha: 0.5),
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
                Switch.adaptive(
                  value: widget.service.harmfulWordsOnly,
                  activeThumbColor: MobileDesignSystem.primaryGreenMint,
                  activeTrackColor: MobileDesignSystem.primaryGreen.withValues(alpha: 0.6),
                  inactiveThumbColor: Colors.white38,
                  inactiveTrackColor: Colors.white10,
                  onChanged: (val) {
                    widget.service.toggleHarmfulWordsOnly(val);
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Live Safety Alert Banner (if incidents detected by CS for paired pins)
          if (incidents.isNotEmpty) ...[
            _buildLiveIncidentCard(incidents.first),
            const SizedBox(height: 14),
          ],

          // Quick Action Bar: Pair Pin Button & Fleet Toggle
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _openPairModal,
                  icon: const Icon(Icons.add_link_rounded, size: 17),
                  label: const Text(
                    'Pair Smart Pin',
                    style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12.5),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: MobileDesignSystem.primaryGreen,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    elevation: 3,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: () {
                  setState(() => _viewAllFleet = !_viewAllFleet);
                },
                icon: Icon(
                  _viewAllFleet ? Icons.person_rounded : Icons.hub_rounded,
                  size: 15,
                ),
                label: Text(
                  _viewAllFleet ? 'My Pins' : 'All Fleet (${widget.service.allDevices.length})',
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 11),
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white70,
                  side: BorderSide(color: Colors.white.withValues(alpha: 0.15)),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Fleet Metrics Row
          Row(
            children: [
              Expanded(
                child: _metricCard('Paired', '$total', Icons.devices_other_rounded, MobileDesignSystem.accentIndigo),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _metricCard('Connected', '$online', Icons.wifi_rounded, MobileDesignSystem.accentMint),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _metricCard('VAD Standby', '$standby', Icons.mic_rounded, MobileDesignSystem.accentCyan),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _metricCard('Offline', '$offline', Icons.wifi_off_rounded, const Color(0xFF6B7280)),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Fleet View Toggle (My Paired Pins vs Campus Network Fleet)
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.05),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white10),
            ),
            child: Row(
              children: [
                Expanded(
                  child: GestureDetector(
                    onTap: () => setState(() => _viewAllFleet = false),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      decoration: BoxDecoration(
                        color: !_viewAllFleet ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.25) : Colors.transparent,
                        borderRadius: BorderRadius.circular(10),
                        border: !_viewAllFleet ? Border.all(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.4)) : null,
                      ),
                      child: Center(
                        child: Text(
                          'My Paired Pins (${widget.service.pairedDevices.length})',
                          style: TextStyle(
                            color: !_viewAllFleet ? MobileDesignSystem.primaryGreenMint : Colors.white60,
                            fontSize: 11.5,
                            fontWeight: !_viewAllFleet ? FontWeight.w800 : FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: GestureDetector(
                    onTap: () => setState(() => _viewAllFleet = true),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      decoration: BoxDecoration(
                        color: _viewAllFleet ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.25) : Colors.transparent,
                        borderRadius: BorderRadius.circular(10),
                        border: _viewAllFleet ? Border.all(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.4)) : null,
                      ),
                      child: Center(
                        child: Text(
                          'Campus Fleet (${widget.service.allDevices.length})',
                          style: TextStyle(
                            color: _viewAllFleet ? MobileDesignSystem.primaryGreenMint : Colors.white60,
                            fontSize: 11.5,
                            fontWeight: _viewAllFleet ? FontWeight.w800 : FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Search and Filter Bar
          Row(
            children: [
              Expanded(
                child: TextField(
                  onChanged: (v) => setState(() => _searchQuery = v),
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: InputDecoration(
                    hintText: 'Search paired pins or student alias...',
                    hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 12.5),
                    prefixIcon: const Icon(Icons.search_rounded, color: Colors.white54, size: 18),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(14),
                      borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(14),
                      borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(14),
                      borderSide: const BorderSide(color: MobileDesignSystem.accentMint),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                tooltip: 'Scan for Pins / Refresh',
                onPressed: () => widget.service.searchForSmartPins(),
                icon: const Icon(Icons.sync_rounded, color: MobileDesignSystem.accentMint, size: 22),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Filter Chips
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _filterChip('ALL', 'All Pins ($total)'),
                const SizedBox(width: 8),
                _filterChip('ONLINE', 'Online ($online)'),
                const SizedBox(width: 8),
                _filterChip('STANDBY', 'VAD Standby ($standby)'),
                const SizedBox(width: 8),
                _filterChip('OFFLINE', 'Offline ($offline)'),
              ],
            ),
          ),
          const SizedBox(height: 18),

          // First Open / Zero Paired State
          if (_targetDevicePool.isEmpty)
            MobileGlassCard(
              padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 34),
              child: Column(
                children: [
                  const RadarScannerWidget(size: 110),
                  const SizedBox(height: 20),
                  Text(
                    widget.service.isSearchingPins ? 'Looking for Smart Pins...' : 'No Smart Pins Paired',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.3,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    widget.service.isSearchingPins
                        ? 'Broadcasting UDP on port 8888 & scanning BLE for student badges...'
                        : 'Pair a Seeed Studio XIAO ESP32S3 badge to monitor battery, Wi-Fi configuration, and live safety alerts.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.65),
                      fontSize: 12,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 20),

                  // Prominent Pair Smart Pin Button
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: _openPairModal,
                      icon: const Icon(Icons.add_link_rounded),
                      label: const Text(
                        'Pair Smart Pin (Wi-Fi / Bluetooth)',
                        style: TextStyle(fontWeight: FontWeight.w900, fontSize: 13.5),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: MobileDesignSystem.primaryGreen,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        elevation: 4,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),

                  OutlinedButton.icon(
                    onPressed: () => widget.service.searchForSmartPins(),
                    icon: const Icon(Icons.radar_rounded, size: 16),
                    label: const Text('Scan Local Network for Pins'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: MobileDesignSystem.accentMint,
                      side: const BorderSide(color: MobileDesignSystem.accentMint),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
                    ),
                  ),
                ],
              ),
            )
          else if (devices.isEmpty)
            Container(
              padding: const EdgeInsets.all(32),
              alignment: Alignment.center,
              child: Text(
                'No pins match the current filter.',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 13),
              ),
            )
          else
            ...devices.map(
              (dev) {
                final alias = widget.service.getPinAlias(dev.id);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: MobileGlassCard(
                    onTap: () => _showPinDetailsSheet(dev),
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              width: 40,
                              height: 40,
                              decoration: BoxDecoration(
                                color: dev.stateColor.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(color: dev.stateColor.withValues(alpha: 0.25)),
                              ),
                              child: Icon(Icons.memory_rounded, color: dev.stateColor, size: 21),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    dev.id,
                                    style: const TextStyle(
                                      color: Colors.white,
                                      fontSize: 15,
                                      fontWeight: FontWeight.w800,
                                    ),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  if (alias != null) ...[
                                    const SizedBox(height: 1),
                                    Text(
                                      alias,
                                      style: const TextStyle(
                                        color: MobileDesignSystem.primaryGreenMint,
                                        fontSize: 11,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ],
                                  const SizedBox(height: 2),
                                  Text(
                                    '${dev.network} • ${dev.rssi} dBm (${dev.signalQuality})',
                                    style: TextStyle(
                                      color: Colors.white.withValues(alpha: 0.5),
                                      fontSize: 10.5,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            MobileStatusPill(online: dev.online, state: dev.state),
                            const SizedBox(width: 4),
                            IconButton(
                              icon: const Icon(Icons.edit_note_rounded, color: MobileDesignSystem.primaryGreenMint, size: 22),
                              tooltip: 'Rename Pin',
                              padding: EdgeInsets.zero,
                              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                              onPressed: () => _showRenamePinDialog(dev),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline_rounded, color: Colors.white38, size: 20),
                              tooltip: 'Delete Pin',
                              padding: EdgeInsets.zero,
                              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                              onPressed: () => _confirmDeletePin(dev),
                            ),
                          ],
                        ),
                        const SizedBox(height: 14),

                        // Battery and state gauge
                        Row(
                          children: [
                            Icon(dev.batteryIcon, color: dev.batteryColor, size: 17),
                            const SizedBox(width: 6),
                            Text(
                              '${dev.battery}% (${dev.estRuntime})',
                              style: TextStyle(
                                color: dev.batteryColor,
                                fontSize: 12.5,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const Spacer(),
                            Text(
                              '${dev.voltageEstimate}V LiPo',
                              style: TextStyle(
                                color: Colors.white.withValues(alpha: 0.6),
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: LinearProgressIndicator(
                            value: (dev.battery / 100.0).clamp(0.0, 1.0),
                            backgroundColor: Colors.white.withValues(alpha: 0.08),
                            valueColor: AlwaysStoppedAnimation<Color>(dev.batteryColor),
                            minHeight: 4.5,
                          ),
                        ),
                        if (!widget.service.isPinPaired(dev.id)) ...[
                          const SizedBox(height: 12),
                          SizedBox(
                            width: double.infinity,
                            child: ElevatedButton.icon(
                              onPressed: () => _showPairPinQuickDialog(dev),
                              icon: const Icon(Icons.add_link_rounded, size: 16),
                              label: Text('Pair ${dev.id} to My Companion'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: MobileDesignSystem.primaryGreen,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(vertical: 9),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            ),
        ],
      ),
    );
  }

  Widget _buildLiveIncidentCard(IncidentReport inc) {
    Color badgeColor = MobileDesignSystem.statusWarning;
    if (inc.threatScore >= 7.0) {
      badgeColor = MobileDesignSystem.statusDanger;
    } else if (inc.threatScore <= 2.0) {
      badgeColor = MobileDesignSystem.primaryGreenMint;
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: badgeColor.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: badgeColor.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.security_rounded, color: badgeColor, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'SAFETY ALERT: ${inc.threatLabel} (${inc.threatScore.toStringAsFixed(1)}/10)',
                  style: TextStyle(color: badgeColor, fontSize: 11.5, fontWeight: FontWeight.w900),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.black38,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  inc.deviceId,
                  style: const TextStyle(color: Colors.white, fontSize: 9.5, fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '"${inc.transcript}"',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12.5,
              fontStyle: FontStyle.italic,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Central System AI TagalogBERT Verified',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 9.5),
              ),
              Text(
                inc.timestamp.contains(' ') ? inc.timestamp.split(' ').last : inc.timestamp,
                style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 9.5),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _metricCard(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.035),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white.withValues(alpha: 0.07)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(height: 6),
          Text(
            value,
            style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 1),
          Text(
            label,
            style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 9.5),
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  Widget _filterChip(String key, String label) {
    final isSelected = _filter == key;
    return GestureDetector(
      onTap: () => setState(() => _filter = key),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: isSelected ? MobileDesignSystem.primaryGreen : Colors.white.withValues(alpha: 0.04),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? MobileDesignSystem.primaryGreenMint : Colors.white.withValues(alpha: 0.08),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: isSelected ? Colors.white : Colors.white70,
            fontSize: 11,
            fontWeight: isSelected ? FontWeight.w800 : FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
