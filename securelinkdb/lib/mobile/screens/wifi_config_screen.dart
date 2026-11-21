import 'package:flutter/material.dart';
import '../models/device_model.dart';
import '../services/mobile_server_service.dart';
import '../widgets/mobile_components.dart';

class WifiConfigScreen extends StatefulWidget {
  final MobileServerService service;

  const WifiConfigScreen({super.key, required this.service});

  @override
  State<WifiConfigScreen> createState() => _WifiConfigScreenState();
}

class _WifiConfigScreenState extends State<WifiConfigScreen> {
  void _showAddEditCheckpointDialog([WifiCheckpoint? existing]) {
    final nameCtrl = TextEditingController(text: existing?.name ?? '');
    final ssidCtrl = TextEditingController(text: existing?.ssid ?? '');
    final passCtrl = TextEditingController(text: existing?.pass ?? '');
    final ipCtrl = TextEditingController(text: existing?.serverIp ?? widget.service.host);
    final portCtrl = TextEditingController(text: (existing?.serverPort ?? widget.service.port).toString());
    bool isDefault = existing?.isDefault ?? false;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDlgState) => AlertDialog(
          backgroundColor: const Color(0xFF0F1422),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          title: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.wifi_tethering_rounded, color: MobileDesignSystem.primaryGreen, size: 20),
              ),
              const SizedBox(width: 10),
              Text(
                existing == null ? 'Add Wi-Fi Checkpoint' : 'Edit Wi-Fi Checkpoint',
                style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: nameCtrl,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    labelText: 'Checkpoint Friendly Name',
                    hintText: 'e.g. Science Wing AP',
                    labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: ssidCtrl,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    labelText: 'Wi-Fi Network SSID',
                    hintText: 'Campus-SSID',
                    prefixIcon: const Icon(Icons.wifi_rounded, color: MobileDesignSystem.primaryGreen, size: 18),
                    labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: passCtrl,
                  obscureText: true,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    labelText: 'Wi-Fi Password / WPA2 Key',
                    hintText: '••••••••',
                    prefixIcon: const Icon(Icons.password_rounded, color: MobileDesignSystem.primaryGreen, size: 18),
                    labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: ipCtrl,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    labelText: 'AI Server Target IP',
                    hintText: '10.28.20.28',
                    prefixIcon: const Icon(Icons.dns_rounded, color: MobileDesignSystem.primaryGreen, size: 18),
                    labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: portCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    labelText: 'AI Server Port',
                    hintText: '8080',
                    prefixIcon: const Icon(Icons.numbers_rounded, color: MobileDesignSystem.primaryGreen, size: 18),
                    labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(height: 12),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Set as Default Campus AP', style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                  value: isDefault,
                  activeThumbColor: MobileDesignSystem.primaryGreen,
                  onChanged: (v) => setDlgState(() => isDefault = v),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel', style: TextStyle(color: Colors.white60)),
            ),
            ElevatedButton(
              onPressed: () {
                final ssid = ssidCtrl.text.trim();
                if (ssid.isEmpty) return;

                final chk = WifiCheckpoint(
                  id: existing?.id ?? 'chk_${DateTime.now().millisecondsSinceEpoch}',
                  name: nameCtrl.text.trim().isEmpty ? ssid : nameCtrl.text.trim(),
                  ssid: ssid,
                  pass: passCtrl.text.trim(),
                  serverIp: ipCtrl.text.trim().isEmpty ? widget.service.host : ipCtrl.text.trim(),
                  serverPort: int.tryParse(portCtrl.text.trim()) ?? 8080,
                  isDefault: isDefault,
                  lastDeployed: existing?.lastDeployed,
                );

                widget.service.saveCheckpoint(chk);
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    backgroundColor: const Color(0xFF131722),
                    content: Text('Checkpoint "${chk.name}" saved.'),
                  ),
                );
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: MobileDesignSystem.primaryGreen,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              ),
              child: const Text('Save Checkpoint', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );
  }

  void _showDeployTargetDialog(WifiCheckpoint chk) {
    String selectedTarget = 'ALL';
    final activePins = widget.service.devices.where((d) => d.online).toList();

    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0F1422),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (context, setSheetState) => Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.cloud_upload_rounded, color: MobileDesignSystem.primaryGreen, size: 22),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Push "${chk.name}"', style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
                        Text('SSID: ${chk.ssid} • Target: ${chk.serverIp}:${chk.serverPort}', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              const Text('Select Target Pins for OTA Wi-Fi Provisioning:', style: TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600)),
              const SizedBox(height: 10),
              GestureDetector(
                onTap: () => setSheetState(() => selectedTarget = 'ALL'),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 180),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                  decoration: BoxDecoration(
                    color: selectedTarget == 'ALL'
                        ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.12)
                        : Colors.white.withValues(alpha: 0.03),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: selectedTarget == 'ALL'
                          ? MobileDesignSystem.primaryGreen
                          : Colors.white.withValues(alpha: 0.1),
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        selectedTarget == 'ALL'
                            ? Icons.radio_button_checked_rounded
                            : Icons.radio_button_off_rounded,
                        color: selectedTarget == 'ALL'
                            ? MobileDesignSystem.primaryGreen
                            : Colors.white38,
                        size: 20,
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'All Active Smart Pins (Fleet Broadcast)',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w700),
                            ),
                            Text(
                              'Broadcast new credentials to ${activePins.length} currently connected badge(s)',
                              style: TextStyle(
                                  color: Colors.white.withValues(alpha: 0.5),
                                  fontSize: 11),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              ...activePins.map(
                (pin) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: GestureDetector(
                    onTap: () => setSheetState(() => selectedTarget = pin.id),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 180),
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                      decoration: BoxDecoration(
                        color: selectedTarget == pin.id
                            ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.12)
                            : Colors.white.withValues(alpha: 0.03),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: selectedTarget == pin.id
                              ? MobileDesignSystem.primaryGreen
                              : Colors.white.withValues(alpha: 0.1),
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            selectedTarget == pin.id
                                ? Icons.radio_button_checked_rounded
                                : Icons.radio_button_off_rounded,
                            color: selectedTarget == pin.id
                                ? MobileDesignSystem.primaryGreen
                                : Colors.white38,
                            size: 20,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  pin.id,
                                  style: const TextStyle(
                                      color: Colors.white,
                                      fontSize: 13,
                                      fontWeight: FontWeight.w700),
                                ),
                                Text(
                                  'Currently on: ${pin.network}',
                                  style: TextStyle(
                                      color: Colors.white.withValues(alpha: 0.5),
                                      fontSize: 11),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () {
                    widget.service.deployCheckpoint(chk, target: selectedTarget);
                    Navigator.pop(ctx);
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        backgroundColor: const Color(0xFF131722),
                        content: Text('Deploying "${chk.name}" to $selectedTarget over WebSocket...'),
                      ),
                    );
                  },
                  icon: const Icon(Icons.send_rounded, size: 18),
                  label: const Text('Deploy Wi-Fi Over-The-Air', style: TextStyle(fontWeight: FontWeight.w800)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: MobileDesignSystem.primaryGreen,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _confirmForgetWifi() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0F1422),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: MobileDesignSystem.statusDanger.withValues(alpha: 0.12),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.wifi_off_rounded, color: MobileDesignSystem.statusDanger, size: 22),
            ),
            const SizedBox(width: 12),
            const Text('Forget Wi-Fi on Pins?', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700)),
          ],
        ),
        content: Text(
          'This dispatches CMD:FORGET_WIFI to all active pins. They will clear saved Wi-Fi from NVS Flash and start their local "SecureLink-Setup" AP portal (192.168.4.1) for direct pairing.',
          style: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.white60)),
          ),
          ElevatedButton(
            onPressed: () {
              widget.service.forgetWifi();
              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  backgroundColor: Color(0xFF131722),
                  content: Text('CMD:FORGET_WIFI dispatched. Pins entering Setup Portal.'),
                ),
              );
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: MobileDesignSystem.statusDanger,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: const Text('Reset & Forget', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final checkpoints = widget.service.checkpoints;
    final currentSsid = widget.service.devices.isNotEmpty
        ? widget.service.devices.first.network
        : 'Campus Wi-Fi';

    return RefreshIndicator(
      color: MobileDesignSystem.primaryGreen,
      backgroundColor: const Color(0xFF131722),
      onRefresh: () async {
        widget.service.reconnect();
      },
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        children: [
          // Current Fleet Network Card
          MobileGlassCard(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.3)),
                  ),
                  child: const Icon(Icons.wifi_rounded, color: MobileDesignSystem.primaryGreen, size: 24),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Active Fleet Wi-Fi',
                        style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        currentSsid,
                        style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'Server: ${widget.service.host}:${widget.service.port}',
                        style: TextStyle(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.85), fontSize: 10.5, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  onPressed: () {
                    showModalBottomSheet(
                      context: context,
                      isScrollControlled: true,
                      backgroundColor: const Color(0xFF141923),
                      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
                      builder: (ctx) => ServerHostModal(service: widget.service),
                    );
                  },
                  icon: const Icon(Icons.settings_rounded, color: Colors.white70),
                  tooltip: 'Server Settings',
                ),
              ],
            ),
          ),

          const SizedBox(height: 18),

          // Checkpoints Section Header
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Campus Wi-Fi Checkpoints (${checkpoints.length})',
                style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w800),
              ),
              ElevatedButton.icon(
                onPressed: () => _showAddEditCheckpointDialog(),
                icon: const Icon(Icons.add_rounded, size: 16),
                label: const Text('Add AP', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
                style: ElevatedButton.styleFrom(
                  backgroundColor: MobileDesignSystem.primaryGreen,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ],
          ),

          const SizedBox(height: 10),

          // Real Checkpoints List or Clean Empty State
          if (checkpoints.isEmpty)
            MobileGlassCard(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
              child: Column(
                children: [
                  const Icon(Icons.wifi_find_rounded, color: Colors.white30, size: 36),
                  const SizedBox(height: 12),
                  const Text(
                    'No Campus Checkpoints Loaded',
                    style: TextStyle(color: Colors.white, fontSize: 14.5, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Tap "Add AP" above to save your school or campus Wi-Fi network credentials for over-the-air deployment to your smart badges.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11.5, height: 1.4),
                  ),
                ],
              ),
            )
          else
            ...checkpoints.map(
              (chk) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: MobileGlassCard(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: chk.isDefault ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.06),
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Icon(
                              Icons.wifi_tethering_rounded,
                              color: chk.isDefault ? MobileDesignSystem.primaryGreen : Colors.white70,
                              size: 20,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Flexible(
                                      child: Text(
                                        chk.name,
                                        style: const TextStyle(color: Colors.white, fontSize: 14.5, fontWeight: FontWeight.w800),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    if (chk.isDefault) ...[
                                      const SizedBox(width: 6),
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                        decoration: BoxDecoration(
                                          color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.15),
                                          borderRadius: BorderRadius.circular(6),
                                        ),
                                        child: const Text('DEFAULT', style: TextStyle(fontSize: 8, color: MobileDesignSystem.primaryGreen, fontWeight: FontWeight.w800)),
                                      ),
                                    ],
                                  ],
                                ),
                                const SizedBox(height: 2),
                                Text('SSID: ${chk.ssid}', style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontSize: 11)),
                              ],
                            ),
                          ),
                          IconButton(
                            onPressed: () => _showAddEditCheckpointDialog(chk),
                            icon: const Icon(Icons.edit_outlined, size: 18, color: Colors.white60),
                          ),
                          IconButton(
                            onPressed: () => widget.service.deleteCheckpoint(chk.id),
                            icon: const Icon(Icons.delete_outline_rounded, size: 18, color: Colors.white38),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.03),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text('Server Target: ${chk.serverIp}:${chk.serverPort}', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10)),
                            const Text('WPA2-PSK', style: TextStyle(color: Colors.white70, fontSize: 10, fontWeight: FontWeight.w600)),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: () => _showDeployTargetDialog(chk),
                          icon: const Icon(Icons.send_rounded, size: 15),
                          label: const Text('Deploy Checkpoint to Pins', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: MobileDesignSystem.primaryGreen,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 10),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),

          const SizedBox(height: 14),

          // Emergency Reset / Forget Wi-Fi Card
          MobileGlassCard(
            backgroundColor: MobileDesignSystem.statusDanger.withValues(alpha: 0.06),
            border: Border.all(color: MobileDesignSystem.statusDanger.withValues(alpha: 0.25)),
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.settings_backup_restore_rounded, color: Color(0xFFFF5E72), size: 20),
                    SizedBox(width: 8),
                    Text('Emergency Hotspot Portal Reset', style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800)),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  'Clears saved Wi-Fi credentials on all pins and puts them into captive portal setup mode ("SecureLink-Setup" AP at 192.168.4.1).',
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.65), fontSize: 11),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _confirmForgetWifi,
                    icon: const Icon(Icons.wifi_off_rounded, size: 14),
                    label: const Text('Reset Fleet to Setup AP (Forget Wi-Fi)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFFFF5E72),
                      side: BorderSide(color: const Color(0xFFFF5E72).withValues(alpha: 0.4)),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
