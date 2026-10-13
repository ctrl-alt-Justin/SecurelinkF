import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

// ============================================================================
// SECURELINK — MODERN MATTE DASHBOARD
// Design Language: Ultra-rounded, Matte Solids, High-Contrast Neon Accents
// ============================================================================

// --- Design System (Tokens) ---
class _DS {
  // Backgrounds
  static const Color bg = Color(0xFF090A0F); // Deep matte background
  static const Color surface = Color(0xFF14161F); // Card surfaces
  static const Color surfaceHover = Color(0xFF1D202D);
  static const Color surfaceElevated = Color(0xFF242736);

  // Accents (Based on Image 1's striking palette)
  static const Color neonLime = Color(0xFFD4FF00);
  static const Color neonLimeDim = Color(0xFF9EBE00);
  static const Color neonBlue = Color(0xFF00E5FF);
  
  // Semantic / Threats
  static const Color danger = Color(0xFFFF2E63);
  static const Color warning = Color(0xFFFFB800);
  static const Color orange = Color(0xFFFF7A00);

  // Text
  static const Color textMain = Color(0xFFFFFFFF);
  static const Color textDim = Color(0xFF7A7D8A);
  static const Color textDark = Color(0xFF090A0F); // For text on neon backgrounds

  // Radii
  static const double r32 = 32.0;
  static const double r24 = 24.0;
  static const double r16 = 16.0;

  // Shadows
  static List<BoxShadow> softShadow = [
    BoxShadow(
      color: Colors.black.withOpacity(0.25),
      blurRadius: 24,
      offset: const Offset(0, 10),
    ),
  ];
  static List<BoxShadow> neonGlow = [
    BoxShadow(
      color: neonLime.withOpacity(0.2),
      blurRadius: 20,
      offset: const Offset(0, 4),
    ),
  ];
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    await windowManager.ensureInitialized();

    const options = WindowOptions(
      size: Size(1440, 900),
      minimumSize: Size(1120, 720),
      center: true,
      backgroundColor: Colors.transparent,
      skipTaskbar: false,
      titleBarStyle: TitleBarStyle.hidden,
      title: 'SecureLink Terminal',
    );

    await windowManager.waitUntilReadyToShow(options, () async {
      await windowManager.show();
      await windowManager.focus();
    });
  }

  runApp(const SecureLinkApp());
}

class SecureLinkApp extends StatelessWidget {
  const SecureLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'SecureLink',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: _DS.bg,
        fontFamily: 'Segoe UI', // Falls back nicely if no custom font
        sliderTheme: SliderThemeData(
          activeTrackColor: _DS.neonLime,
          inactiveTrackColor: _DS.surfaceElevated,
          thumbColor: _DS.neonLime,
          trackHeight: 8, // Thick sliders
          thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 10),
          overlayShape: SliderComponentShape.noOverlay,
        ),
        switchTheme: SwitchThemeData(
          thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? _DS.bg : _DS.textDim),
          trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? _DS.neonLime : _DS.surfaceElevated),
          trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
        ),
      ),
      home: const DashboardShell(),
    );
  }
}

// --- Enums & Models ---

enum AppTab { overview, incidents, devices, analytics, configuration }
enum ThreatLevel { normal, warning, threat, danger }

extension ThreatLevelX on ThreatLevel {
  String get label => switch (this) {
        ThreatLevel.normal => 'Clear',
        ThreatLevel.warning => 'Warning',
        ThreatLevel.threat => 'Threat',
        ThreatLevel.danger => 'Danger',
      };
  Color get color => switch (this) {
        ThreatLevel.normal => _DS.neonLime,
        ThreatLevel.warning => _DS.warning,
        ThreatLevel.threat => _DS.orange,
        ThreatLevel.danger => _DS.danger,
      };
}

class IncidentEvent {
  final String id, deviceId, time, category, transcript, duration;
  final ThreatLevel level;
  final double score;
  final bool audio, video;

  const IncidentEvent({
    required this.id, required this.deviceId, required this.time,
    required this.level, required this.score, required this.category,
    required this.transcript, required this.audio, required this.video,
    this.duration = '00:08',
  });

  factory IncidentEvent.fromJson(Map<String, dynamic> json) {
    final double s = (json['score'] as num?)?.toDouble() ?? 1.0;
    ThreatLevel lvl = ThreatLevel.normal;
    if (s >= 8.0) lvl = ThreatLevel.danger;
    else if (s >= 4.0) lvl = ThreatLevel.threat;
    else if (s >= 2.0) lvl = ThreatLevel.warning;
    
    final t = DateTime.now();
    return IncidentEvent(
      id: json['id'] ?? 'EVT-${DateTime.now().millisecondsSinceEpoch.toString().substring(8)}',
      deviceId: json['device_id'] ?? 'PIN-001',
      time: '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}',
      level: lvl, score: s,
      category: json['category'] ?? 'Conversational',
      transcript: json['transcript'] ?? '',
      audio: json['audio'] ?? true,
      video: lvl == ThreatLevel.danger,
      duration: json['duration'] ?? '00:08',
    );
  }
}

class PinNode {
  final String id, state, network, estRuntime;
  final bool online;
  final int battery, rssi;

  const PinNode({
    required this.id, required this.online, required this.battery,
    required this.state, required this.network,
    this.rssi = -60, this.estRuntime = '6h 45m',
  });
}

// ============================================================================
// MAIN SHELL
// ============================================================================

class DashboardShell extends StatefulWidget {
  const DashboardShell({super.key});
  @override
  State<DashboardShell> createState() => _DashboardShellState();
}

class _DashboardShellState extends State<DashboardShell> with WindowListener {
  AppTab tab = AppTab.overview;
  bool isMaximized = false;
  bool isServerOnline = true;
  DateTime now = DateTime.now();

  WebSocketChannel? _channel;
  Timer? _clockTimer;

  int bufferSec = 4, silenceSec = 10, wifiBatchMs = 100;
  bool autoDangerSnapshot = true;

  List<IncidentEvent> incidents = [];

  List<PinNode> pins = [];

  @override
  void initState() {
    super.initState();
    if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
      windowManager.addListener(this);
    }
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => now = DateTime.now());
    });
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    _channel?.sink.close();
    _clockTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _DS.bg,
      body: Column(
        children: [
          // Invisible drag area for custom window frame
          GestureDetector(
            behavior: HitTestBehavior.translucent,
            onPanStart: (_) => windowManager.startDragging(),
            child: const SizedBox(height: 24, width: double.infinity),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: Row(
                children: [
                  // Floating Sidebar
                  _Sidebar(active: tab, onTab: (t) => setState(() => tab = t)),
                  const SizedBox(width: 32),
                  
                  // Main Content Area
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _Header(tab: tab, now: now, online: isServerOnline),
                        const SizedBox(height: 32),
                        Expanded(
                          child: AnimatedSwitcher(
                            duration: const Duration(milliseconds: 250),
                            child: switch (tab) {
                              AppTab.overview => _OverviewPage(incidents: incidents, pins: pins),
                              AppTab.incidents => _IncidentsPage(incidents: incidents),
                              AppTab.devices => _DevicesPage(pins: pins),
                              AppTab.analytics => _AnalyticsPage(incidents: incidents),
                              AppTab.configuration => _ConfigPage(
                                bufferSec: bufferSec, silenceSec: silenceSec, wifiBatchMs: wifiBatchMs, autoDangerSnapshot: autoDangerSnapshot,
                                onBufferChanged: (v) => setState(() => bufferSec = v),
                                onSilenceChanged: (v) => setState(() => silenceSec = v),
                                onWifiBatchChanged: (v) => setState(() => wifiBatchMs = v),
                                onAutoSnapshotChanged: (v) => setState(() => autoDangerSnapshot = v),
                              ),
                            },
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ============================================================================
// SHARED COMPONENTS
// ============================================================================

class _SolidCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets? padding;
  final double? width;
  final double? height;

  const _SolidCard({required this.child, this.padding, this.width, this.height});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      padding: padding ?? const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: _DS.surface,
        borderRadius: BorderRadius.circular(_DS.r24),
        boxShadow: _DS.softShadow,
      ),
      child: child,
    );
  }
}

// --- Floating Sidebar ---
class _Sidebar extends StatelessWidget {
  final AppTab active;
  final ValueChanged<AppTab> onTab;

  const _Sidebar({required this.active, required this.onTab});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 100,
      decoration: BoxDecoration(
        color: _DS.surface,
        borderRadius: BorderRadius.circular(_DS.r32),
        boxShadow: _DS.softShadow,
      ),
      padding: const EdgeInsets.symmetric(vertical: 32),
      child: Column(
        children: [
          // Logo Mark
          Container(
            width: 48, height: 48,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: _DS.neonLime,
            ),
            child: const Icon(Icons.hub_rounded, color: _DS.textDark, size: 28),
          ),
          const SizedBox(height: 48),
          
          _SidebarIcon(icon: Icons.dashboard_rounded, active: active == AppTab.overview, onTap: () => onTab(AppTab.overview)),
          const SizedBox(height: 24),
          _SidebarIcon(icon: Icons.receipt_long_rounded, active: active == AppTab.incidents, onTap: () => onTab(AppTab.incidents)),
          const SizedBox(height: 24),
          _SidebarIcon(icon: Icons.sensors_rounded, active: active == AppTab.devices, onTap: () => onTab(AppTab.devices)),
          const SizedBox(height: 24),
          _SidebarIcon(icon: Icons.bar_chart_rounded, active: active == AppTab.analytics, onTap: () => onTab(AppTab.analytics)),
          const SizedBox(height: 24),
          _SidebarIcon(icon: Icons.settings_rounded, active: active == AppTab.configuration, onTap: () => onTab(AppTab.configuration)),
          
          const Spacer(),
          
          // App control (Exit)
          IconButton(
            icon: const Icon(Icons.power_settings_new_rounded, color: _DS.textDim),
            onPressed: () => windowManager.close(),
          )
        ],
      ),
    );
  }
}

class _SidebarIcon extends StatelessWidget {
  final IconData icon;
  final bool active;
  final VoidCallback onTap;

  const _SidebarIcon({required this.icon, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: 56, height: 56,
        decoration: BoxDecoration(
          color: active ? _DS.neonLime : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
          boxShadow: active ? _DS.neonGlow : [],
        ),
        child: Icon(
          icon,
          color: active ? _DS.textDark : _DS.textDim,
          size: 26,
        ),
      ),
    );
  }
}

// --- Header ---
class _Header extends StatelessWidget {
  final AppTab tab;
  final DateTime now;
  final bool online;

  const _Header({required this.tab, required this.now, required this.online});

  @override
  Widget build(BuildContext context) {
    final title = switch (tab) {
      AppTab.overview => 'Overview',
      AppTab.incidents => 'Incident Archives',
      AppTab.devices => 'Hardware Fleet',
      AppTab.analytics => 'Threat Analytics',
      AppTab.configuration => 'System Settings',
    };

    return Row(
      children: [
        Text(title, style: const TextStyle(color: _DS.textMain, fontSize: 32, fontWeight: FontWeight.bold, letterSpacing: -0.5)),
        const Spacer(),
        
        // System Status Pill
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          decoration: BoxDecoration(
            color: _DS.surface,
            borderRadius: BorderRadius.circular(_DS.r24),
            boxShadow: _DS.softShadow,
          ),
          child: Row(
            children: [
              Text(
                '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}',
                style: const TextStyle(color: _DS.textMain, fontSize: 16, fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: 16),
              Container(width: 2, height: 16, color: _DS.surfaceElevated),
              const SizedBox(width: 16),
              Container(
                width: 10, height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: online ? _DS.neonLime : _DS.danger,
                  boxShadow: online ? _DS.neonGlow : [],
                ),
              ),
              const SizedBox(width: 8),
              Text(online ? 'System Online' : 'Offline', style: const TextStyle(color: _DS.textDim, fontSize: 14, fontWeight: FontWeight.w500)),
            ],
          ),
        ),
      ],
    );
  }
}

// ============================================================================
// OVERVIEW PAGE
// ============================================================================

class _OverviewPage extends StatelessWidget {
  final List<IncidentEvent> incidents;
  final List<PinNode> pins;

  const _OverviewPage({required this.incidents, required this.pins});

  @override
  Widget build(BuildContext context) {
    final activeCount = pins.where((p) => p.online).length;
    final dangerCount = incidents.where((i) => i.level == ThreatLevel.danger).length;

    return Column(
      children: [
        // Top Metric Cards
        Row(
          children: [
            Expanded(child: _MetricCard(title: 'Active Pins', value: '$activeCount', total: '/ ${pins.length}', color: _DS.neonBlue)),
            const SizedBox(width: 24),
            Expanded(child: _MetricCard(title: 'Danger Events', value: '$dangerCount', total: ' today', color: _DS.danger)),
            const SizedBox(width: 24),
            Expanded(child: _MetricCard(title: 'Processing ASR', value: '16', total: ' kHz', color: _DS.neonLime)),
          ],
        ),
        const SizedBox(height: 24),
        
        // Split Content Area
        Expanded(
          child: Row(
            children: [
              // Incidents List
              Expanded(
                flex: 6,
                child: _SolidCard(
                  padding: const EdgeInsets.all(32),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Recent Alerts', style: TextStyle(color: _DS.textMain, fontSize: 22, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 24),
                      Expanded(
                        child: ListView.separated(
                          itemCount: incidents.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 16),
                          itemBuilder: (_, i) => _IncidentPill(incident: incidents[i]),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 24),
              
              // Device List
              Expanded(
                flex: 4,
                child: _SolidCard(
                  padding: const EdgeInsets.all(32),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Fleet Status', style: TextStyle(color: _DS.textMain, fontSize: 22, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 24),
                      Expanded(
                        child: ListView.separated(
                          itemCount: pins.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 16),
                          itemBuilder: (_, i) => _DevicePill(pin: pins[i]),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MetricCard extends StatelessWidget {
  final String title, value, total;
  final Color color;

  const _MetricCard({required this.title, required this.value, required this.total, required this.color});

  @override
  Widget build(BuildContext context) {
    return _SolidCard(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: _DS.textDim, fontSize: 16, fontWeight: FontWeight.w500)),
          const Spacer(),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(value, style: const TextStyle(color: _DS.textMain, fontSize: 48, fontWeight: FontWeight.w800, height: 1.0)),
              Padding(
                padding: const EdgeInsets.only(bottom: 6.0, left: 8.0),
                child: Text(total, style: const TextStyle(color: _DS.textDim, fontSize: 18, fontWeight: FontWeight.w500)),
              ),
              const Spacer(),
              // Accent Graphic (mimicking the abstract charts in Image 1/3)
              Container(
                width: 60, height: 40,
                decoration: BoxDecoration(
                  color: color.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(_DS.r16),
                ),
                child: Center(
                  child: Container(width: 12, height: 12, decoration: BoxDecoration(shape: BoxShape.circle, color: color, boxShadow: [BoxShadow(color: color.withOpacity(0.5), blurRadius: 10)])),
                ),
              )
            ],
          ),
        ],
      ),
    );
  }
}

class _IncidentPill extends StatelessWidget {
  final IncidentEvent incident;
  const _IncidentPill({required this.incident});

  @override
  Widget build(BuildContext context) {
    final color = incident.level.color;
    
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _DS.surfaceElevated,
        borderRadius: BorderRadius.circular(_DS.r24),
      ),
      child: Row(
        children: [
          // Colored Threat Block
          Container(
            width: 80, padding: const EdgeInsets.symmetric(vertical: 12),
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(_DS.r16),
              boxShadow: [BoxShadow(color: color.withOpacity(0.3), blurRadius: 12, offset: const Offset(0, 4))],
            ),
            child: Center(
              child: Text(incident.level.label, style: const TextStyle(color: _DS.textDark, fontSize: 14, fontWeight: FontWeight.bold)),
            ),
          ),
          const SizedBox(width: 24),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(incident.id, style: const TextStyle(color: _DS.textMain, fontSize: 16, fontWeight: FontWeight.bold)),
                    const SizedBox(width: 12),
                    Text(incident.time, style: const TextStyle(color: _DS.textDim, fontSize: 14)),
                  ],
                ),
                const SizedBox(height: 6),
                Text(incident.category, style: const TextStyle(color: _DS.textDim, fontSize: 14)),
              ],
            ),
          ),
          // Score
          Text(incident.score.toStringAsFixed(1), style: const TextStyle(color: _DS.textMain, fontSize: 24, fontWeight: FontWeight.w800)),
        ],
      ),
    );
  }
}

class _DevicePill extends StatelessWidget {
  final PinNode pin;
  const _DevicePill({required this.pin});

  @override
  Widget build(BuildContext context) {
    final isDanger = pin.battery < 30 && pin.online;
    final batColor = !pin.online ? _DS.textDim : (isDanger ? _DS.danger : _DS.neonLime);

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _DS.surfaceElevated,
        borderRadius: BorderRadius.circular(_DS.r24),
      ),
      child: Row(
        children: [
          // Icon Block
          Container(
            width: 56, height: 56,
            decoration: BoxDecoration(
              color: pin.online ? _DS.neonBlue.withOpacity(0.1) : _DS.surface,
              borderRadius: BorderRadius.circular(_DS.r16),
            ),
            child: Icon(Icons.mic_rounded, color: pin.online ? _DS.neonBlue : _DS.textDim),
          ),
          const SizedBox(width: 20),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(pin.id, style: const TextStyle(color: _DS.textMain, fontSize: 16, fontWeight: FontWeight.bold)),
                    Text(pin.state, style: TextStyle(color: pin.online ? _DS.neonBlue : _DS.textDim, fontSize: 14, fontWeight: FontWeight.w600)),
                  ],
                ),
                const SizedBox(height: 12),
                // Custom thick progress bar
                Container(
                  height: 6, width: double.infinity,
                  decoration: BoxDecoration(color: _DS.surface, borderRadius: BorderRadius.circular(3)),
                  child: FractionallySizedBox(
                    alignment: Alignment.centerLeft,
                    widthFactor: pin.battery / 100,
                    child: Container(decoration: BoxDecoration(color: batColor, borderRadius: BorderRadius.circular(3))),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ============================================================================
// INCIDENTS PAGE (Detailed view)
// ============================================================================

class _IncidentsPage extends StatefulWidget {
  final List<IncidentEvent> incidents;
  const _IncidentsPage({required this.incidents});

  @override
  State<_IncidentsPage> createState() => _IncidentsPageState();
}

class _IncidentsPageState extends State<_IncidentsPage> {
  IncidentEvent? selected;

  @override
  void initState() {
    super.initState();
    if (widget.incidents.isNotEmpty) selected = widget.incidents.first;
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        // List Side
        Expanded(
          flex: 5,
          child: _SolidCard(
            padding: const EdgeInsets.all(24),
            child: ListView.separated(
              itemCount: widget.incidents.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (_, i) {
                final ev = widget.incidents[i];
                final isSel = selected?.id == ev.id;
                
                return GestureDetector(
                  onTap: () => setState(() => selected = ev),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: isSel ? _DS.neonLime : _DS.surfaceElevated,
                      borderRadius: BorderRadius.circular(_DS.r24),
                      boxShadow: isSel ? _DS.neonGlow : [],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(ev.id, style: TextStyle(color: isSel ? _DS.textDark : _DS.textMain, fontSize: 16, fontWeight: FontWeight.bold)),
                            Text(ev.time, style: TextStyle(color: isSel ? _DS.textDark.withOpacity(0.6) : _DS.textDim, fontSize: 14)),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(ev.category, style: TextStyle(color: isSel ? _DS.textDark.withOpacity(0.8) : _DS.textDim, fontSize: 14)),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        const SizedBox(width: 24),
        
        // Detail Side
        if (selected != null)
          Expanded(
            flex: 6,
            child: _SolidCard(
              padding: const EdgeInsets.all(40),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title Area
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Event Details', style: TextStyle(color: _DS.textDim, fontSize: 14, letterSpacing: 1.2, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 8),
                          Text(selected!.id, style: const TextStyle(color: _DS.textMain, fontSize: 32, fontWeight: FontWeight.bold)),
                        ],
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                        decoration: BoxDecoration(color: selected!.level.color, borderRadius: BorderRadius.circular(_DS.r16)),
                        child: Text(selected!.score.toStringAsFixed(1), style: const TextStyle(color: _DS.textDark, fontSize: 24, fontWeight: FontWeight.w900)),
                      )
                    ],
                  ),
                  const SizedBox(height: 40),
                  
                  // Transcript
                  Text('TRANSCRIPT', style: TextStyle(color: _DS.textDim, fontSize: 12, letterSpacing: 1.2, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(color: _DS.surfaceElevated, borderRadius: BorderRadius.circular(_DS.r24)),
                    child: Text('"${selected!.transcript}"', style: const TextStyle(color: _DS.textMain, fontSize: 18, height: 1.5, fontStyle: FontStyle.italic)),
                  ),
                  const SizedBox(height: 32),
                  
                  // Faux Audio Player (Stylized)
                  Text('AUDIO EVIDENCE', style: TextStyle(color: _DS.textDim, fontSize: 12, letterSpacing: 1.2, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(color: _DS.surfaceElevated, borderRadius: BorderRadius.circular(_DS.r24)),
                    child: Row(
                      children: [
                        Container(
                          width: 56, height: 56,
                          decoration: BoxDecoration(color: _DS.neonLime, borderRadius: BorderRadius.circular(_DS.r16), boxShadow: _DS.neonGlow),
                          child: const Icon(Icons.play_arrow_rounded, color: _DS.textDark, size: 32),
                        ),
                        const SizedBox(width: 24),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  const Text('00:00', style: TextStyle(color: _DS.neonLime, fontWeight: FontWeight.bold)),
                                  Text(selected!.duration, style: const TextStyle(color: _DS.textDim)),
                                ],
                              ),
                              const SizedBox(height: 12),
                              Container(
                                height: 8, width: double.infinity,
                                decoration: BoxDecoration(color: _DS.surface, borderRadius: BorderRadius.circular(4)),
                                child: FractionallySizedBox(
                                  alignment: Alignment.centerLeft,
                                  widthFactor: 0.3, // fake progress
                                  child: Container(decoration: BoxDecoration(color: _DS.neonLime, borderRadius: BorderRadius.circular(4))),
                                ),
                              ),
                            ],
                          ),
                        )
                      ],
                    ),
                  ),
                ],
              ),
            ),
          )
      ],
    );
  }
}

// ============================================================================
// DEVICES PAGE
// ============================================================================

class _DevicesPage extends StatelessWidget {
  final List<PinNode> pins;
  const _DevicesPage({required this.pins});

  @override
  Widget build(BuildContext context) {
    return _SolidCard(
      child: GridView.builder(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 3,
          childAspectRatio: 1.6,
          crossAxisSpacing: 24,
          mainAxisSpacing: 24,
        ),
        itemCount: pins.length,
        itemBuilder: (_, i) {
          final pin = pins[i];
          return Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: _DS.surfaceElevated,
              borderRadius: BorderRadius.circular(_DS.r24),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(pin.id, style: const TextStyle(color: _DS.textMain, fontSize: 20, fontWeight: FontWeight.bold)),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: pin.online ? _DS.neonBlue : _DS.surface,
                        borderRadius: BorderRadius.circular(_DS.r16),
                      ),
                      child: Text(pin.state, style: TextStyle(color: pin.online ? _DS.textDark : _DS.textDim, fontSize: 12, fontWeight: FontWeight.bold)),
                    )
                  ],
                ),
                const Spacer(),
                const Text('Battery Level', style: TextStyle(color: _DS.textDim, fontSize: 14)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: Container(
                        height: 12,
                        decoration: BoxDecoration(color: _DS.surface, borderRadius: BorderRadius.circular(6)),
                        child: FractionallySizedBox(
                          alignment: Alignment.centerLeft,
                          widthFactor: pin.battery / 100,
                          child: Container(decoration: BoxDecoration(color: pin.online ? _DS.neonLime : _DS.textDim, borderRadius: BorderRadius.circular(6))),
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Text('${pin.battery}%', style: const TextStyle(color: _DS.textMain, fontSize: 16, fontWeight: FontWeight.bold)),
                  ],
                )
              ],
            ),
          );
        },
      ),
    );
  }
}

// ============================================================================
// ANALYTICS PAGE
// ============================================================================

class _AnalyticsPage extends StatelessWidget {
  final List<IncidentEvent> incidents;
  const _AnalyticsPage({required this.incidents});

  @override
  Widget build(BuildContext context) {
    return _SolidCard(
      child: Row(
        children: [
          // Stat Bars
          Expanded(
            flex: 5,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Text('Threat Distribution', style: TextStyle(color: _DS.textMain, fontSize: 28, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                const Text('RoBERTa 4-class NLP model analysis', style: TextStyle(color: _DS.textDim, fontSize: 16)),
                const SizedBox(height: 48),
                _StatBar(label: 'Physical Violence', val: 0.15, color: _DS.danger),
                const SizedBox(height: 32),
                _StatBar(label: 'Extortion Demands', val: 0.25, color: _DS.orange),
                const SizedBox(height: 32),
                _StatBar(label: 'Verbal Harassment', val: 0.40, color: _DS.warning),
                const SizedBox(height: 32),
                _StatBar(label: 'Conversational', val: 0.85, color: _DS.neonLime),
              ],
            ),
          ),
          
          // Abstract visual (Mocking the large charts in Image 2/3)
          Expanded(
            flex: 5,
            child: Center(
              child: Container(
                width: 300, height: 300,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      _DS.neonBlue.withOpacity(0.2),
                      Colors.transparent,
                    ],
                  )
                ),
                child: Center(
                  child: Container(
                    width: 200, height: 200,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: _DS.surfaceElevated, width: 40),
                    ),
                    child: CircularProgressIndicator(
                      value: 0.65,
                      strokeWidth: 40,
                      color: _DS.neonLime,
                      backgroundColor: Colors.transparent,
                      strokeCap: StrokeCap.round,
                    ),
                  ),
                ),
              ),
            ),
          )
        ],
      ),
    );
  }
}

class _StatBar extends StatelessWidget {
  final String label;
  final double val;
  final Color color;

  const _StatBar({required this.label, required this.val, required this.color});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(color: _DS.textMain, fontSize: 16, fontWeight: FontWeight.w600)),
            Text('${(val * 100).toInt()}%', style: TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.bold)),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          height: 16, width: double.infinity,
          decoration: BoxDecoration(color: _DS.surfaceElevated, borderRadius: BorderRadius.circular(8)),
          child: FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: val,
            child: Container(decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8), boxShadow: [BoxShadow(color: color.withOpacity(0.5), blurRadius: 10)])),
          ),
        ),
      ],
    );
  }
}

// ============================================================================
// CONFIGURATION PAGE
// ============================================================================

class _ConfigPage extends StatelessWidget {
  final int bufferSec, silenceSec, wifiBatchMs;
  final bool autoDangerSnapshot;
  final ValueChanged<int> onBufferChanged, onSilenceChanged, onWifiBatchChanged;
  final ValueChanged<bool> onAutoSnapshotChanged;

  const _ConfigPage({
    required this.bufferSec, required this.silenceSec, required this.wifiBatchMs, required this.autoDangerSnapshot,
    required this.onBufferChanged, required this.onSilenceChanged, required this.onWifiBatchChanged, required this.onAutoSnapshotChanged,
  });

  @override
  Widget build(BuildContext context) {
    return _SolidCard(
      padding: const EdgeInsets.all(40),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _ConfigSlider(title: 'Pre-Roll Buffer', desc: 'Audio kept in RAM before trigger.', val: bufferSec.toDouble(), min: 2, max: 8, unit: 's', onChanged: (v) => onBufferChanged(v.round())),
                const SizedBox(height: 48),
                _ConfigSlider(title: 'Silence Timeout', desc: 'Seconds of quiet before sleep.', val: silenceSec.toDouble(), min: 4, max: 20, unit: 's', onChanged: (v) => onSilenceChanged(v.round())),
                const SizedBox(height: 48),
                _ConfigSlider(title: 'Wi-Fi Batching', desc: 'Packet batch interval (ms).', val: wifiBatchMs.toDouble(), min: 50, max: 200, unit: 'ms', onChanged: (v) => onWifiBatchChanged(v.round())),
              ],
            ),
          ),
          const SizedBox(width: 64),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.all(32),
                  decoration: BoxDecoration(color: _DS.surfaceElevated, borderRadius: BorderRadius.circular(_DS.r24)),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Danger Snapshots', style: TextStyle(color: _DS.textMain, fontSize: 18, fontWeight: FontWeight.bold)),
                            const SizedBox(height: 8),
                            const Text('Auto-capture camera on Score >= 8.0', style: TextStyle(color: _DS.textDim, fontSize: 14)),
                          ],
                        ),
                      ),
                      Switch(value: autoDangerSnapshot, onChanged: onAutoSnapshotChanged),
                    ],
                  ),
                ),
                const Spacer(),
                
                // Big Deploy Button (Stylized like action buttons in references)
                InkWell(
                  onTap: () {},
                  borderRadius: BorderRadius.circular(_DS.r24),
                  child: Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    decoration: BoxDecoration(
                      color: _DS.neonLime,
                      borderRadius: BorderRadius.circular(_DS.r24),
                      boxShadow: _DS.neonGlow,
                    ),
                    child: const Center(
                      child: Text('DEPLOY CONFIGURATION', style: TextStyle(color: _DS.textDark, fontSize: 18, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                    ),
                  ),
                )
              ],
            ),
          )
        ],
      ),
    );
  }
}

class _ConfigSlider extends StatelessWidget {
  final String title, desc, unit;
  final double val, min, max;
  final ValueChanged<double> onChanged;

  const _ConfigSlider({required this.title, required this.desc, required this.val, required this.min, required this.max, required this.unit, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(color: _DS.textMain, fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text(desc, style: const TextStyle(color: _DS.textDim, fontSize: 14)),
              ],
            ),
            Text('${val.toInt()}$unit', style: const TextStyle(color: _DS.neonLime, fontSize: 24, fontWeight: FontWeight.bold)),
          ],
        ),
        const SizedBox(height: 16),
        Slider(value: val, min: min, max: max, onChanged: onChanged),
      ],
    );
  }
}