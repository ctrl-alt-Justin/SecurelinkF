import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:window_manager/window_manager.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:audioplayers/audioplayers.dart';
import 'mobile/securelink_mobile_app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    await windowManager.ensureInitialized();

    const options = WindowOptions(
      size: Size(1440, 920),
      minimumSize: Size(1100, 720),
      center: true,
      backgroundColor: Colors.transparent,
      skipTaskbar: false,
      titleBarStyle: TitleBarStyle.hidden,
      title: 'SecureLink - AI Checkpoint Dashboard',
    );

    await windowManager.waitUntilReadyToShow(options, () async {
      await windowManager.setPreventClose(true);
      await windowManager.show();
      await windowManager.focus();
    });
  }

  runApp(const SecureLinkApp());
}

class ServerManager {
  static Process? _process;
  static bool isStarting = false;
  static String statusMessage = 'Checking...';

  static Future<bool> isAlive() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(milliseconds: 600);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/health'));
      final res = await req.close();
      client.close();
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  static Future<void> startServerIfNeeded({required VoidCallback onStatusChanged}) async {
    if (await isAlive()) {
      statusMessage = 'AI Server Online';
      onStatusChanged();
      return;
    }

    if (isStarting) return;
    isStarting = true;
    statusMessage = 'Starting AI Engine...';
    onStatusChanged();

    try {
      final target = _findServerTargets();
      if (target == null) {
        debugPrint('[SERVER] Could not find server.py or server.exe');
        isStarting = false;
        statusMessage = 'Server script not found';
        onStatusChanged();
        return;
      }

      final (executable, args, workDir) = target;
      debugPrint('[SERVER] Auto-starting AI Server: $executable ${args.join(" ")} in $workDir');

      _process = await Process.start(
        executable,
        args,
        workingDirectory: workDir,
        mode: ProcessStartMode.normal,
      );

      _process?.stdout.transform(utf8.decoder).listen((data) {
        debugPrint('[AI-SERVER] $data');
      });

      _process?.stderr.transform(utf8.decoder).listen((data) {
        debugPrint('[AI-SERVER-ERR] $data');
      });

      _process?.exitCode.then((code) {
        debugPrint('[SERVER] Process exited with code: $code');
        _process = null;
        isStarting = false;
      });

      // Poll up to 75 seconds for the heavy AI models (Faster-Whisper large-v3-turbo + RoBERTa) to finish loading
      final stopwatch = Stopwatch()..start();
      while (stopwatch.elapsedMilliseconds < 75000) {
        await Future.delayed(const Duration(milliseconds: 1000));
        final elapsedSec = (stopwatch.elapsedMilliseconds / 1000).round();
        statusMessage = 'Loading AI Models (${elapsedSec}s)...';
        onStatusChanged();
        if (await isAlive()) {
          debugPrint('[SERVER] AI Server successfully initialized and online!');
          isStarting = false;
          statusMessage = 'AI Server Online';
          onStatusChanged();
          return;
        }
      }
    } catch (e) {
      debugPrint('[SERVER] Error starting AI server: $e');
    }

    isStarting = false;
    statusMessage = 'Awaiting Server (8080)';
    onStatusChanged();
  }

  static (String, List<String>, String)? _findServerTargets() {
    // 1. Check next to current executable (Production build: server.exe)
    final exeDir = File(Platform.resolvedExecutable).parent.path;
    if (File('$exeDir/server.exe').existsSync()) {
      return ('$exeDir/server.exe', <String>[], exeDir);
    }

    // 2. Check next to executable for server.py
    if (File('$exeDir/server.py').existsSync()) {
      return ('python', ['server.py'], exeDir);
    }

    // 3. Check current working directory
    final currentDir = Directory.current.path;
    if (File('$currentDir/server.py').existsSync()) {
      return ('python', ['server.py'], currentDir);
    }

    // 4. Check 'securelinkdb' subfolder or parent folder
    if (File('$currentDir/securelinkdb/server.py').existsSync()) {
      return ('python', ['server.py'], '$currentDir/securelinkdb');
    }

    final parentDir = Directory.current.parent.path;
    if (File('$parentDir/securelinkdb/server.py').existsSync()) {
      return ('python', ['server.py'], '$parentDir/securelinkdb');
    }

    // 5. Fallback workspace directory
    const fallbackPath = r'd:\Flutter Securelink Dashboard\securelinkdb';
    if (File('$fallbackPath\\server.py').existsSync()) {
      return ('python', ['server.py'], fallbackPath);
    }

    return null;
  }

  static void stopServer() {
    if (_process != null) {
      final pid = _process!.pid;
      final proc = _process;
      _process = null;
      debugPrint('[SERVER] Stopping background AI server process (PID: $pid)...');
      if (Platform.isWindows) {
        try {
          Process.run('taskkill', ['/F', '/T', '/PID', '$pid']).catchError((_) {});
        } catch (_) {
          try {
            proc?.kill();
          } catch (_) {}
        }
      } else {
        try {
          proc?.kill();
        } catch (_) {}
      }
    }
  }
}

class SecureLinkApp extends StatelessWidget {
  const SecureLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb && (Platform.isAndroid || Platform.isIOS)) {
      return const SecureLinkMobileApp();
    }

    return MaterialApp(
      title: 'SecureLink',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF070A12),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF7F6CFF),
          secondary: Color(0xFF55E2C0),
          surface: Color(0xFF111722),
        ),
        fontFamily: 'Segoe UI',
        useMaterial3: true,
      ),
      home: const DashboardShell(),
    );
  }
}

enum AppTab { overview, incidents, devices, analytics, configuration }
enum IncidentLevel { normal, warning, threat, danger }

extension IncidentLevelX on IncidentLevel {
  String get label => switch (this) {
        IncidentLevel.normal => 'NORMAL',
        IncidentLevel.warning => 'WARNING',
        IncidentLevel.threat => 'THREAT',
        IncidentLevel.danger => 'DANGER',
      };

  Color get color => switch (this) {
        IncidentLevel.normal => const Color(0xFF55D58B),
        IncidentLevel.warning => const Color(0xFFFFC857),
        IncidentLevel.threat => const Color(0xFFFF914D),
        IncidentLevel.danger => const Color(0xFFFF4D67),
      };

  IconData get icon => switch (this) {
        IncidentLevel.normal => Icons.check_circle_outline_rounded,
        IncidentLevel.warning => Icons.warning_amber_rounded,
        IncidentLevel.threat => Icons.gpp_maybe_outlined,
        IncidentLevel.danger => Icons.emergency_outlined,
      };
}

class _SplashParticle {
  final double x;
  final double y;
  final double size;
  final double speedY;
  final double maxOpacity;
  final double phase;

  const _SplashParticle({
    required this.x,
    required this.y,
    required this.size,
    required this.speedY,
    required this.maxOpacity,
    required this.phase,
  });
}

class _SplashParticlesPainter extends CustomPainter {
  final List<_SplashParticle> particles;
  final double elapsedSeconds;
  final Color color;

  const _SplashParticlesPainter({
    required this.particles,
    required this.elapsedSeconds,
    required this.color,
  });

  @override
  void paint(Canvas canvas, Size size) {
    for (final p in particles) {
      // Continuous monotonic upward drift with mathematically seamless wrap-around
      final rawY = p.y - (elapsedSeconds * p.speedY);
      final currentY = rawY - rawY.floorToDouble();

      final rawX = p.x + (sin(elapsedSeconds * 0.6 + p.phase) * 0.02);
      final currentX = rawX - rawX.floorToDouble();

      final posX = currentX * size.width;
      final posY = currentY * size.height;

      // Smooth vertical edge fade so particles fade in and out gracefully at borders
      final edgeFade = sin((currentY * pi).clamp(0.0, pi));

      // Organic continuous twinkle
      final shimmer = (sin((elapsedSeconds * 1.6) + p.phase) + 1.0) / 2.0;
      final alpha = (p.maxOpacity * (0.35 + 0.65 * shimmer) * edgeFade).clamp(0.0, 1.0);

      final paint = Paint()..color = color.withOpacity(alpha);
      canvas.drawCircle(Offset(posX, posY), p.size, paint);
    }
  }

  @override
  bool shouldRepaint(_SplashParticlesPainter oldDelegate) => true;
}

class _Backdrop extends StatefulWidget {
  final DashboardStatus status;
  const _Backdrop({super.key, required this.status});

  @override
  State<_Backdrop> createState() => _BackdropState();
}

class _BackdropState extends State<_Backdrop> with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  late final List<_SplashParticle> _particles;
  late final DateTime _startTime;

  @override
  void initState() {
    super.initState();
    _startTime = DateTime.now();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 3200),
    )..repeat(reverse: true);

    final rng = Random(66);
    _particles = List.generate(45, (i) {
      return _SplashParticle(
        x: rng.nextDouble(),
        y: rng.nextDouble(),
        size: 1.0 + rng.nextDouble() * 2.2,
        speedY: 0.016 + rng.nextDouble() * 0.030,
        maxOpacity: 0.16 + rng.nextDouble() * 0.28,
        phase: rng.nextDouble() * 2 * pi,
      );
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = widget.status.baseColor;
    final accent = widget.status.accent;
    final isAlert = widget.status == DashboardStatus.danger || widget.status == DashboardStatus.threat;

    return IgnorePointer(
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 400),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              const Color(0xFF04070B),
              Color.lerp(const Color(0xFF071015), base, .25)!,
              Color.lerp(const Color(0xFF050A0F), base, .16)!,
              const Color(0xFF030508),
            ],
            stops: const [0.0, 0.35, 0.75, 1.0],
          ),
        ),
        child: Stack(
          fit: StackFit.expand,
          children: [
            // Procedural Tactical Grid & Crosshairs
            AnimatedBuilder(
              animation: _pulseController,
              builder: (context, _) => CustomPaint(
                painter: _TacticalGridPainter(
                  accent: accent,
                  isAlert: isAlert,
                  pulse: _pulseController.value,
                ),
              ),
            ),

            // Continuous floating dynamic particles across the whole application background
            AnimatedBuilder(
              animation: _pulseController,
              builder: (context, _) {
                final elapsedSeconds = DateTime.now().difference(_startTime).inMilliseconds / 1000.0;
                return CustomPaint(
                  painter: _SplashParticlesPainter(
                    particles: _particles,
                    elapsedSeconds: elapsedSeconds,
                    color: const Color(0xFF55E2C0),
                  ),
                );
              },
            ),

            Positioned(left: -190, top: -220, child: _GlowOrb(size: 540, color: accent.withOpacity(.08))),
            Positioned(right: -210, top: 50, child: _GlowOrb(size: 470, color: base.withOpacity(.07))),
            Positioned(left: 240, bottom: -280, child: _GlowOrb(size: 580, color: accent.withOpacity(.04))),
          ],
        ),
      ),
    );
  }
}

class _TacticalGridPainter extends CustomPainter {
  final Color accent;
  final bool isAlert;
  final double pulse;

  const _TacticalGridPainter({
    required this.accent,
    required this.isAlert,
    required this.pulse,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final dotPaint = Paint()
      ..color = Colors.white.withOpacity(0.022)
      ..strokeWidth = 1.0;

    final crossPaint = Paint()
      ..color = accent.withOpacity(0.12 + (isAlert ? pulse * 0.12 : 0.0))
      ..strokeWidth = 1.0
      ..strokeCap = StrokeCap.square;

    const step = 48.0;

    // Draw coordinate dots and intermittent tactical crosshairs
    for (double x = step; x < size.width; x += step) {
      for (double y = step; y < size.height; y += step) {
        canvas.drawCircle(Offset(x, y), 0.75, dotPaint);

        if ((x ~/ step) % 4 == 0 && (y ~/ step) % 4 == 0) {
          canvas.drawLine(Offset(x - 3.5, y), Offset(x + 3.5, y), crossPaint);
          canvas.drawLine(Offset(x, y - 3.5), Offset(x, y + 3.5), crossPaint);
        }
      }
    }

    // Dynamic perimeter vignette alert when threat level rises
    if (isAlert) {
      final borderGlow = Paint()
        ..shader = RadialGradient(
          center: Alignment.center,
          radius: 1.15,
          colors: [
            Colors.transparent,
            accent.withOpacity(0.03 + pulse * 0.08),
          ],
          stops: const [0.72, 1.0],
        ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

      canvas.drawRect(Rect.fromLTWH(0, 0, size.width, size.height), borderGlow);
    }
  }

  @override
  bool shouldRepaint(_TacticalGridPainter oldDelegate) {
    return oldDelegate.accent != accent ||
        oldDelegate.isAlert != isAlert ||
        oldDelegate.pulse != pulse;
  }
}

class _GlowOrb extends StatelessWidget {
  final double size;
  final Color color;
  const _GlowOrb({required this.size, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(colors: [color, color.withOpacity(0.0)]),
      ),
    );
  }
}

// Glassmorphism 2.0 with true acrylic blur & calm, steady styling (no pop/jump on hover)
class _Glass extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radius;
  final Color? tint;
  final Border? border;
  final VoidCallback? onTap;

  const _Glass({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.radius = 24,
    this.tint,
    this.border,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    Widget content = Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            tint?.withOpacity(0.92) ?? const Color(0xEE0E141B),
            tint ?? const Color(0xEE090D13),
          ],
        ),
        border: border ??
            Border.all(
              color: Colors.white.withOpacity(0.06),
              width: 1.0,
            ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.24),
            blurRadius: 24,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
          child: Padding(padding: padding, child: child),
        ),
      ),
    );

    if (onTap != null) {
      content = GestureDetector(onTap: onTap, child: content);
    }

    return content;
  }
}

enum DashboardStatus { safe, warning, threat, danger }

extension DashboardStatusX on DashboardStatus {
  String get label => switch (this) {
        DashboardStatus.safe => 'SAFE',
        DashboardStatus.warning => 'WARNING',
        DashboardStatus.threat => 'THREAT',
        DashboardStatus.danger => 'DANGER'
      };
  Color get baseColor => switch (this) {
        DashboardStatus.safe => const Color(0xFF06352A),
        DashboardStatus.warning => const Color(0xFF463800),
        DashboardStatus.threat => const Color(0xFF4A2109),
        DashboardStatus.danger => const Color(0xFF42101F)
      };
  Color get accent => switch (this) {
        DashboardStatus.safe => const Color(0xFF109C6D),
        DashboardStatus.warning => const Color(0xFFB48E15),
        DashboardStatus.threat => const Color(0xFFC95A17),
        DashboardStatus.danger => const Color(0xFFA52A4B)
      };
  IconData get icon => switch (this) {
        DashboardStatus.safe => Icons.verified_rounded,
        DashboardStatus.warning => Icons.warning_amber_rounded,
        DashboardStatus.threat => Icons.gpp_maybe_outlined,
        DashboardStatus.danger => Icons.emergency_rounded
      };
}

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
  });

  factory DeviceStatus.fromJson(Map<String, dynamic> json) {
    final batt = json['battery'] ?? 100;
    final hours = (batt / 100.0 * 7.5);
    final h = hours.floor();
    final m = ((hours - h) * 60).round();
    final runtime = '${h}h ${m}m';

    return DeviceStatus(
      id: json['id'] ?? 'PIN-001',
      online: json['online'] ?? false,
      battery: batt,
      state: json['state'] ?? 'STANDBY',
      network: json['network'] ?? 'Campus Wi-Fi',
      lastSeen: json['lastSeen'] ?? 'Just now',
      cpuMhz: json['cpuMhz'] ?? 160,
      rssi: json['rssi'] ?? -62,
      estRuntime: json['estRuntime'] ?? runtime,
    );
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
    serverIp: json['server_ip'] as String? ?? '127.0.0.1',
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
    'last_deployed': lastDeployed,
  };
}

class Incident {
  final String id;
  final String deviceId;
  final String time;
  final IncidentLevel level;
  final double score;
  final String category;
  final String transcript;
  final bool audio;
  final bool video;
  final String audioDuration;
  final String? audioUrl;
  final String? audioFile;

  const Incident({
    required this.id,
    required this.deviceId,
    required this.time,
    required this.level,
    required this.score,
    required this.category,
    required this.transcript,
    required this.audio,
    required this.video,
    this.audioDuration = '00:08',
    this.audioUrl,
    this.audioFile,
  });

  factory Incident.fromJson(Map<String, dynamic> json) {
    double parsedScore = (json['score'] as num).toDouble();
    IncidentLevel parsedLevel = IncidentLevel.normal;
    if (parsedScore >= 8.0) {
      parsedLevel = IncidentLevel.danger;
    } else if (parsedScore >= 4.0) {
      parsedLevel = IncidentLevel.threat;
    } else if (parsedScore >= 2.0) {
      parsedLevel = IncidentLevel.warning;
    }

    // Camera snapshots are ONLY enabled for DANGER grade events!
    final bool hasVideoSnapshot = parsedLevel == IncidentLevel.danger;
    final String evtId = json['id'] ?? 'EVT-${DateTime.now().millisecondsSinceEpoch.toString().substring(8)}';

    return Incident(
      id: evtId,
      deviceId: json['device_id'] ?? 'PIN-001',
      time: _formatTime(DateTime.now()),
      level: parsedLevel,
      score: parsedScore,
      category: json['category'] ?? 'Conversational',
      transcript: json['transcript'] ?? '',
      audio: json['audio'] ?? true,
      video: hasVideoSnapshot,
      audioDuration: json['duration'] ?? '00:08',
      audioUrl: json['audio_url'] ?? 'http://127.0.0.1:8080/recordings/audio/$evtId.wav',
      audioFile: json['audio_file'] ?? '$evtId.wav',
    );
  }

  static String _formatTime(DateTime time) {
    return '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  }
}

class DashboardShell extends StatefulWidget {
  const DashboardShell({super.key});

  @override
  State<DashboardShell> createState() => _DashboardShellState();
}

class _DashboardShellState extends State<DashboardShell> with WindowListener {
  AppTab tab = AppTab.overview;
  bool maximized = false;
  bool refreshing = false;
  DashboardStatus currentStatus = DashboardStatus.safe;
  DateTime now = DateTime.now();

  // Configuration settings for the fleet
  int bufferDurationSeconds = 4;
  int silenceTimeoutSeconds = 10;
  int vadStreakThreshold = 8;
  bool autoDangerSnapshot = true;
  int wifiBatchMs = 100;

  List<Incident> liveIncidents = [];

  List<DeviceStatus> liveDevices = [];
  List<WifiCheckpoint> checkpoints = [];

  WebSocketChannel? _uiChannel;
  bool isServerConnected = false;
  bool harmfulWordsOnly = false;
  Timer? _reconnectTimer;
  Timer? _pingTimer;

  void toggleHarmfulWordsOnly() {
    final next = !harmfulWordsOnly;
    setState(() => harmfulWordsOnly = next);
    if (_uiChannel != null && isServerConnected) {
      _uiChannel!.sink.add(jsonEncode({
        'event_type': 'set_harmful_only',
        'enabled': next,
      }));
    }
  }

  bool _showSplashScreen = true;
  double _splashOpacity = 1.0;

  void _dismissSplashScreen() {
    if (_showSplashScreen && _splashOpacity > 0.0) {
      Future.delayed(const Duration(milliseconds: 600), () {
        if (mounted && _showSplashScreen) {
          setState(() => _splashOpacity = 0.0);
          Future.delayed(const Duration(milliseconds: 400), () {
            if (mounted) setState(() => _showSplashScreen = false);
          });
        }
      });
    }
  }

  @override
  void initState() {
    super.initState();
    if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
      windowManager.addListener(this);
      _syncMaximizedState();
    }
    Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => now = DateTime.now());
    });

    _initServerAndConnect();
  }

  Future<void> _initServerAndConnect() async {
    await ServerManager.startServerIfNeeded(onStatusChanged: () {
      if (mounted) setState(() {});
    });
    if (await ServerManager.isAlive()) {
      _connectToServer();
    } else {
      _handleDisconnect();
    }
  }

  void _connectToServer() {
    _uiChannel?.sink.close();
    _pingTimer?.cancel();

    try {
      final wsUrl = Uri.parse('ws://127.0.0.1:8080/ui');
      _uiChannel = WebSocketChannel.connect(wsUrl);

      // Instantly detect connection establishment via channel.ready
      _uiChannel!.ready.then((_) {
        if (mounted) {
          if (!isServerConnected) {
            setState(() => isServerConnected = true);
          }
          _dismissSplashScreen();
        }
        try {
          _uiChannel?.sink.add('ping');
        } catch (_) {}
      }).catchError((err) {
        debugPrint('WebSocket ready error: $err');
      });

      // Regular heartbeat every 5 seconds
      _pingTimer = Timer.periodic(const Duration(seconds: 5), (_) {
        try {
          _uiChannel?.sink.add('ping');
        } catch (_) {}
      });

      _uiChannel!.stream.listen(
        (message) {
          if (!isServerConnected && mounted) {
            setState(() => isServerConnected = true);
            _dismissSplashScreen();
          }

          try {
            final data = jsonDecode(message);
            final eventType = data['event_type'] ?? 'incident';

            if (eventType == 'device_update') {
              final dev = DeviceStatus.fromJson(data['device']);
              setState(() {
                final idx = liveDevices.indexWhere((d) => d.id == dev.id);
                if (idx >= 0) {
                  liveDevices[idx] = dev;
                } else {
                  liveDevices.add(dev);
                }
                liveDevices = List.from(liveDevices);
              });
            } else if (eventType == 'incident') {
              final newIncident = Incident.fromJson(data);
              // Deduplicate: ignore if exact same ID or identical transcript arrived from device in same time slot
              final isDuplicate = liveIncidents.any((inc) =>
                inc.id == newIncident.id ||
                (inc.deviceId == newIncident.deviceId &&
                 inc.transcript.trim().isNotEmpty &&
                 inc.transcript.trim() == newIncident.transcript.trim() &&
                 inc.time == newIncident.time)
              );
              if (isDuplicate) return;

              setState(() {
                liveIncidents = [newIncident, ...liveIncidents];

                if (newIncident.level == IncidentLevel.danger) {
                  currentStatus = DashboardStatus.danger;
                  // Dispatch DANGER trigger to tell the ESP32 pin to capture an evidence snapshot
                  _uiChannel?.sink.add('TRIGGER:DANGER');
                } else if (newIncident.level == IncidentLevel.threat) {
                  currentStatus = DashboardStatus.threat;
                } else if (newIncident.level == IncidentLevel.warning) {
                  currentStatus = DashboardStatus.warning;
                } else if (newIncident.level == IncidentLevel.normal) {
                  currentStatus = DashboardStatus.safe;
                }
              });
            } else if (eventType == 'checkpoints_updated') {
              final raw = data['checkpoints'] as List? ?? [];
              setState(() {
                checkpoints = raw.map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>)).toList();
              });
            } else if (eventType == 'checkpoint_deployed') {
              final msg = data['message'] as String? ?? 'Checkpoint deployed successfully!';
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(msg),
                    backgroundColor: const Color(0xFF109C6D),
                    duration: const Duration(seconds: 4),
                  ),
                );
              }
            } else if (eventType == 'harmful_only_update') {
              final enabled = data['enabled'] == true;
              if (mounted) {
                setState(() => harmfulWordsOnly = enabled);
              }
            } else if (eventType == 'server_status') {
              if (data.containsKey('harmful_words_only') && mounted) {
                setState(() => harmfulWordsOnly = data['harmful_words_only'] == true);
              }
            }
          } catch (e) {
            debugPrint('Error parsing incoming UI event: $e');
          }
        },
        onDone: () => _handleDisconnect(),
        onError: (error) {
          debugPrint('WebSocket Stream Error: $error');
          _handleDisconnect();
        },
        cancelOnError: true,
      );
    } catch (e) {
      debugPrint('WebSocket Connection failed: $e');
      _handleDisconnect();
    }
  }

  void _handleDisconnect() {
    if (!mounted) return;
    setState(() => isServerConnected = false);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 4), () async {
      if (!isServerConnected) {
        if (!await ServerManager.isAlive()) {
          await ServerManager.startServerIfNeeded(onStatusChanged: () {
            if (mounted) setState(() {});
          });
        }
        if (await ServerManager.isAlive()) {
          _connectToServer();
        } else {
          _handleDisconnect();
        }
      }
    });
  }

  void syncConfigToFleet() {
    final payload = jsonEncode({
      'event_type': 'fleet_config',
      'buffer_duration': bufferDurationSeconds,
      'silence_timeout': silenceTimeoutSeconds,
      'vad_streak': vadStreakThreshold,
      'auto_danger_snapshot': autoDangerSnapshot,
      'wifi_batch_ms': wifiBatchMs,
    });
    if (isServerConnected && _uiChannel != null) {
      _uiChannel!.sink.add(payload);
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Configuration deployed: ${bufferDurationSeconds}s Pre-roll buffer synced to smart pins.'),
        backgroundColor: const Color(0xFF7F6CFF),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  void forgetPinNetwork() {
    final payload = jsonEncode({
      'event_type': 'forget_wifi',
      'command': 'CMD:FORGET_WIFI',
    });
    if (isServerConnected && _uiChannel != null) {
      _uiChannel!.sink.add(payload);
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Forget Wi-Fi command sent! Pin is entering Setup Portal ("SecureLink-Setup").'),
        backgroundColor: Color(0xFFEF4444),
        duration: Duration(seconds: 4),
      ),
    );
  }

  void _confirmForgetWifi() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: Color(0xFF334155)),
        ),
        title: const Row(
          children: [
            Icon(Icons.wifi_off_rounded, color: Color(0xFFEF4444), size: 22),
            SizedBox(width: 10),
            Text('Forget Pin Wi-Fi Network?', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700)),
          ],
        ),
        content: Text(
          'This will instruct your connected SecureLink smart pin to clear its saved Wi-Fi credentials from flash memory and launch the "SecureLink-Setup" Wi-Fi hotspot.\n\nYou can then connect your phone to "SecureLink-Setup" to configure a new network.',
          style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12.5, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Cancel', style: TextStyle(color: Colors.white.withOpacity(0.5))),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              forgetPinNetwork();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            child: const Text('Forget & Reconfigure'),
          ),
        ],
      ),
    );
  }

  void _openPinSetupDialog() {
    showDialog(
      context: context,
      builder: (ctx) => _PinSetupDialog(
        liveDevices: liveDevices,
        isServerConnected: isServerConnected,
      ),
    );
  }

  Future<void> _fetchCheckpoints() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/api/checkpoints'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final list = (data['checkpoints'] as List? ?? [])
            .map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>))
            .toList();
        if (mounted) setState(() => checkpoints = list);
      }
    } catch (_) {}
  }

  Future<void> _saveCheckpoint(WifiCheckpoint chk) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:8080/api/checkpoints'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode(chk.toJson()));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final list = (data['checkpoints'] as List? ?? [])
            .map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>))
            .toList();
        if (mounted) {
          setState(() => checkpoints = list);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Checkpoint "${chk.name}" saved!'),
              backgroundColor: const Color(0xFF109C6D),
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error saving checkpoint: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _deleteCheckpoint(String chkId) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final req = await client.deleteUrl(Uri.parse('http://127.0.0.1:8080/api/checkpoints/$chkId'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final list = (data['checkpoints'] as List? ?? [])
            .map((c) => WifiCheckpoint.fromJson(c as Map<String, dynamic>))
            .toList();
        if (mounted) {
          setState(() => checkpoints = list);
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Checkpoint removed.'),
              backgroundColor: Color(0xFF334155),
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error deleting checkpoint: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _deployCheckpoint({
    required WifiCheckpoint checkpoint,
    required String target,
    String method = 'wifi',
    String? comPort,
  }) async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 6);
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:8080/api/checkpoints/deploy'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode({
        'checkpoint_id': checkpoint.id,
        'ssid': checkpoint.ssid,
        'pass': checkpoint.pass,
        'server_ip': checkpoint.serverIp,
        'server_port': checkpoint.serverPort,
        'name': checkpoint.name,
        'target': target,
        'method': method,
        'com_port': comPort,
      }));
      final resp = await req.close();
      final body = await resp.transform(utf8.decoder).join();
      final data = jsonDecode(body) as Map<String, dynamic>;
      final msg = data['message'] as String? ?? 'Checkpoint deployed successfully!';
      final isSuccess = data['status'] == 'success';

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(msg),
            backgroundColor: isSuccess ? const Color(0xFF109C6D) : Colors.red,
            duration: const Duration(seconds: 4),
          ),
        );
      }
      _fetchCheckpoints();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Deploy failed: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  void _showCheckpointEditorDialog([WifiCheckpoint? existing]) {
    showDialog(
      context: context,
      builder: (ctx) => _CheckpointEditorDialog(
        existing: existing,
        onSave: (chk) => _saveCheckpoint(chk),
      ),
    );
  }

  void _showAssignCheckpointDialog(DeviceStatus dev) {
    showDialog(
      context: context,
      builder: (ctx) => _AssignPinCheckpointDialog(
        device: dev,
        checkpoints: checkpoints,
        onDeploy: ({required checkpoint, required method, comPort}) {
          _deployCheckpoint(
            checkpoint: checkpoint,
            target: dev.id,
            method: method,
            comPort: comPort,
          );
        },
        onAddNew: () => _showCheckpointEditorDialog(),
      ),
    );
  }


  Future<void> _handleWindowClose() async {
    try {
      if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
        await windowManager.hide();
      }
    } catch (_) {}
    ServerManager.stopServer();
    try {
      if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
        await windowManager.destroy();
      }
    } catch (_) {}
    exit(0);
  }

  @override
  void onWindowClose() => _handleWindowClose();

  @override
  void dispose() {
    if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
      windowManager.removeListener(this);
    }
    _uiChannel?.sink.close();
    _pingTimer?.cancel();
    _reconnectTimer?.cancel();
    ServerManager.stopServer();
    super.dispose();
  }

  Future<void> _syncMaximizedState() async {
    maximized = await windowManager.isMaximized();
    if (mounted) setState(() {});
  }

  @override
  void onWindowMaximize() => _syncMaximizedState();

  @override
  void onWindowUnmaximize() => _syncMaximizedState();

  Future<void> _toggleMaximize() async {
    final isMax = await windowManager.isMaximized();
    if (isMax) {
      await windowManager.unmaximize();
    } else {
      await windowManager.maximize();
    }
    await _syncMaximizedState();
  }

  Future<void> _refresh() async {
    setState(() => refreshing = true);
    _uiChannel?.sink.close();
    if (mounted) setState(() => isServerConnected = false);
    _connectToServer();
    await Future<void>.delayed(const Duration(milliseconds: 350));
    if (mounted) setState(() => refreshing = false);
  }

  @override
  Widget build(BuildContext context) {
    final desktop = Platform.isWindows || Platform.isLinux || Platform.isMacOS;

    return Scaffold(
      body: Stack(
        children: [
          _Backdrop(status: currentStatus),
          Column(
            children: [
              if (desktop)
                _DesktopTitleBar(
                  onMinimize: () => windowManager.minimize(),
                  onMaximize: _toggleMaximize,
                  onClose: _handleWindowClose,
                  maximized: maximized,
                ),
              Expanded(
                child: Row(
                  children: [
                    _Sidebar(
                      tab: tab,
                      isServerConnected: isServerConnected,
                      onTabChanged: (value) => setState(() => tab = value),
                    ),
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                        child: Column(
                          children: [
                            const SizedBox(height: 12),
                            _Header(
                              tab: tab,
                              now: now,
                              refreshing: refreshing,
                              isServerConnected: isServerConnected,
                              onRefresh: _refresh,
                              status: currentStatus,
                              onStatusChanged: (value) {
                                setState(() => currentStatus = value);
                              },
                              onOpenPinSetup: _openPinSetupDialog,
                              hasOnlinePin: liveDevices.any((d) => d.online),
                              harmfulWordsOnly: harmfulWordsOnly,
                              onToggleHarmfulWordsOnly: toggleHarmfulWordsOnly,
                            ),
                            const SizedBox(height: 14),
                            Expanded(
                              child: AnimatedSwitcher(
                                duration: const Duration(milliseconds: 220),
                                child: KeyedSubtree(
                                  key: ValueKey(tab),
                                  child: _buildPage(),
                                ),
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
          ),

          // --- FULLSCREEN SERVER BOOT SPLASH SCREEN ---
          if (_showSplashScreen)
            Positioned.fill(
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 380),
                curve: Curves.easeInOut,
                opacity: _splashOpacity,
                child: _ServerLoadingSplashScreen(
                  isStarting: ServerManager.isStarting,
                  statusMessage: ServerManager.statusMessage,
                  onProceedOffline: () {
                    setState(() => _splashOpacity = 0.0);
                    Future.delayed(const Duration(milliseconds: 380), () {
                      if (mounted) setState(() => _showSplashScreen = false);
                    });
                  },
                  onCloseApp: _handleWindowClose,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildPage() {
    switch (tab) {
      case AppTab.overview:
        return _OverviewPage(
          incidents: liveIncidents,
          devices: liveDevices,
          status: currentStatus,
          isServerConnected: isServerConnected,
          bufferDurationSeconds: bufferDurationSeconds,
          onOpenPinSetup: _openPinSetupDialog,
        );
      case AppTab.incidents:
        return _IncidentsPage(incidents: liveIncidents);
      case AppTab.devices:
        return _DevicesPage(
          devices: liveDevices,
          checkpoints: checkpoints,
          onOpenPinSetup: _openPinSetupDialog,
          onConfigurePinWifi: _showAssignCheckpointDialog,
        );
      case AppTab.analytics:
        return _AnalyticsPage(incidents: liveIncidents);
      case AppTab.configuration:
        return _ConfigurationPage(
          bufferDuration: bufferDurationSeconds,
          silenceTimeout: silenceTimeoutSeconds,
          vadStreak: vadStreakThreshold,
          autoDangerSnapshot: autoDangerSnapshot,
          wifiBatchMs: wifiBatchMs,
          devices: liveDevices,
          checkpoints: checkpoints,
          onBufferChanged: (v) => setState(() => bufferDurationSeconds = v),
          onSilenceChanged: (v) => setState(() => silenceTimeoutSeconds = v),
          onVadStreakChanged: (v) => setState(() => vadStreakThreshold = v),
          onAutoSnapshotChanged: (v) => setState(() => autoDangerSnapshot = v),
          onWifiBatchChanged: (v) => setState(() => wifiBatchMs = v),
          onSave: syncConfigToFleet,
          onForgetWifi: _confirmForgetWifi,
          onAddCheckpoint: () => _showCheckpointEditorDialog(),
          onEditCheckpoint: (chk) => _showCheckpointEditorDialog(chk),
          onDeleteCheckpoint: (id) => _deleteCheckpoint(id),
          onDeployCheckpoint: _deployCheckpoint,
        );
    }
  }
}

// Clean draggable title bar without duplicate logo or redundant branding
class _DesktopTitleBar extends StatelessWidget {
  final VoidCallback onMinimize;
  final VoidCallback onMaximize;
  final VoidCallback onClose;
  final bool maximized;

  const _DesktopTitleBar({required this.onMinimize, required this.onMaximize, required this.onClose, required this.maximized});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: Row(
        children: [
          const SizedBox(width: 16),
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.translucent,
              onPanStart: (_) => windowManager.startDragging(),
              child: Container(
                height: double.infinity,
                alignment: Alignment.centerLeft,
                child: Text(
                  'SECURELINK',
                  style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(.48), fontWeight: FontWeight.w700, letterSpacing: 1.5),
                ),
              ),
            ),
          ),
          _WindowButton(icon: Icons.remove_rounded, onTap: onMinimize),
          _WindowButton(icon: maximized ? Icons.filter_none_rounded : Icons.crop_square_rounded, onTap: onMaximize),
          _WindowButton(icon: Icons.close_rounded, close: true, onTap: onClose),
          const SizedBox(width: 6),
        ],
      ),
    );
  }
}

class _WindowButton extends StatefulWidget {
  final IconData icon;
  final VoidCallback onTap;
  final bool close;

  const _WindowButton({required this.icon, required this.onTap, this.close = false});

  @override
  State<_WindowButton> createState() => _WindowButtonState();
}

class _WindowButtonState extends State<_WindowButton> {
  bool hover = false;

  @override
  Widget build(BuildContext context) {
    final bg = widget.close && hover ? const Color(0xFFE95463) : hover ? Colors.white.withOpacity(.09) : Colors.transparent;
    return MouseRegion(
      onEnter: (_) => setState(() => hover = true),
      onExit: (_) => setState(() => hover = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          width: 42,
          height: 30,
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
          child: Icon(widget.icon, size: 15, color: widget.close && hover ? Colors.white : Colors.white.withOpacity(.50)),
        ),
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  final AppTab tab;
  final bool isServerConnected;
  final ValueChanged<AppTab> onTabChanged;

  const _Sidebar({required this.tab, required this.isServerConnected, required this.onTabChanged});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 228,
      margin: const EdgeInsets.fromLTRB(16, 0, 0, 20),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(.03),
        border: Border.all(color: Colors.white.withOpacity(.06)),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Column(
        children: [
          const SizedBox(height: 4),
          _LogoBrand(),
          const SizedBox(height: 20),
          const _SideLabel('MONITORING'),
          _SideItem(icon: Icons.space_dashboard_rounded, label: 'Overview', active: tab == AppTab.overview, onTap: () => onTabChanged(AppTab.overview)),
          _SideItem(icon: Icons.receipt_long_rounded, label: 'Incidents & Evidence', active: tab == AppTab.incidents, onTap: () => onTabChanged(AppTab.incidents)),
          _SideItem(icon: Icons.devices_other_rounded, label: 'Hardware Pins', active: tab == AppTab.devices, onTap: () => onTabChanged(AppTab.devices)),
          _SideItem(icon: Icons.bar_chart_rounded, label: 'Speech Analytics', active: tab == AppTab.analytics, onTap: () => onTabChanged(AppTab.analytics)),
          const SizedBox(height: 12),
          const _SideLabel('SYSTEM'),
          _SideItem(icon: Icons.tune_rounded, label: 'Configuration', active: tab == AppTab.configuration, onTap: () => onTabChanged(AppTab.configuration)),
          const Spacer(),
          _ServerCard(isServerConnected: isServerConnected),
        ],
      ),
    );
  }
}

class _LogoBrand extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(11),
            gradient: const LinearGradient(colors: [Color(0xFF8D77FF), Color(0xFF4FE2C0)]),
          ),
          child: const Icon(Icons.shield_rounded, size: 20, color: Colors.white),
        ),
        const SizedBox(width: 10),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('SECURELINK', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 1.05)),
              Text('CAMPUS SENTINEL', style: TextStyle(fontSize: 8, fontWeight: FontWeight.w600, color: Color(0xFF55E2C0), letterSpacing: .7)),
            ],
          ),
        ),
      ],
    );
  }
}

class _SideLabel extends StatelessWidget {
  final String text;
  const _SideLabel(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(text, style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w600, letterSpacing: 1.2, color: Colors.white.withOpacity(.28))),
        ),
      );
}

class _SideItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback onTap;

  const _SideItem({required this.icon, required this.label, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Material(
        color: active ? Colors.white.withOpacity(.075) : Colors.transparent,
        borderRadius: BorderRadius.circular(13),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(13),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 10),
            child: Row(
              children: [
                Icon(icon, size: 17, color: active ? const Color(0xFF9B88FF) : Colors.white.withOpacity(.48)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: active ? FontWeight.w600 : FontWeight.w500,
                      color: active ? Colors.white : Colors.white.withOpacity(.60),
                    ),
                  ),
                ),
                if (active) Container(width: 5, height: 5, decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xFF7F6CFF))),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ServerCard extends StatelessWidget {
  final bool isServerConnected;
  const _ServerCard({required this.isServerConnected});

  @override
  Widget build(BuildContext context) {
    final isStarting = ServerManager.isStarting;
    final statusText = isServerConnected
        ? 'Inference Online (8080)'
        : (isStarting ? 'Starting AI Engine...' : 'Awaiting Server (8080)');
    final statusColor = isServerConnected
        ? const Color(0xFF57DDA0)
        : (isStarting ? const Color(0xFF9B88FF) : const Color(0xFFFFC857));

    return Container(
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(.12),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: Colors.white.withOpacity(.05)),
      ),
      child: Row(
        children: [
          _StatusDot(
            active: isServerConnected,
            activeColor: const Color(0xFF57DDA0),
            inactiveColor: isStarting ? const Color(0xFF9B88FF) : const Color(0xFFFFC857),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('AI CHECKPOINT', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(
                  statusText,
                  style: TextStyle(
                    fontSize: 9,
                    color: statusColor,
                    fontWeight: isStarting ? FontWeight.w600 : FontWeight.w400,
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

class _StatusDot extends StatefulWidget {
  final bool active;
  final double size;
  final Color? activeColor;
  final Color? inactiveColor;

  const _StatusDot({
    super.key,
    required this.active,
    this.size = 7.0,
    this.activeColor,
    this.inactiveColor,
  });

  @override
  State<_StatusDot> createState() => _StatusDotState();
}

class _StatusDotState extends State<_StatusDot> with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1900),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final baseColor = widget.active
        ? (widget.activeColor ?? const Color(0xFF57DDA0))
        : (widget.inactiveColor ?? const Color(0xFFFF5E72));

    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final progress = _controller.value;
        final rippleSize = widget.size + (progress * 13.0);
        final rippleOpacity = (1.0 - progress) * (widget.active ? 0.70 : 0.0);

        return SizedBox(
          width: widget.size + 14,
          height: widget.size + 14,
          child: Stack(
            alignment: Alignment.center,
            children: [
              if (widget.active)
                Container(
                  width: rippleSize,
                  height: rippleSize,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: baseColor.withOpacity(rippleOpacity),
                      width: 1.2,
                    ),
                  ),
                ),
              Container(
                width: widget.size,
                height: widget.size,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: baseColor,
                  boxShadow: [
                    BoxShadow(
                      color: baseColor.withOpacity(widget.active ? 0.65 : 0.25),
                      blurRadius: widget.active ? 6 : 2,
                      spreadRadius: widget.active ? 1 : 0,
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _Header extends StatelessWidget {
  final AppTab tab;
  final DateTime now;
  final bool refreshing;
  final bool isServerConnected;
  final VoidCallback onRefresh;
  final DashboardStatus status;
  final ValueChanged<DashboardStatus> onStatusChanged;
  final VoidCallback onOpenPinSetup;
  final bool hasOnlinePin;
  final bool harmfulWordsOnly;
  final VoidCallback onToggleHarmfulWordsOnly;

  const _Header({
    required this.tab,
    required this.now,
    required this.refreshing,
    required this.isServerConnected,
    required this.onRefresh,
    required this.status,
    required this.onStatusChanged,
    required this.onOpenPinSetup,
    required this.hasOnlinePin,
    required this.harmfulWordsOnly,
    required this.onToggleHarmfulWordsOnly,
  });

  String get title => switch (tab) {
        AppTab.overview => 'Overview',
        AppTab.incidents => 'Incidents & Evidence',
        AppTab.devices => 'Hardware Smart Pins',
        AppTab.analytics => 'Speech & Model Analytics',
        AppTab.configuration => 'Fleet Configuration',
      };

  String get subtitle => switch (tab) {
        AppTab.overview => 'Live system status, acoustic telemetry & incident queue',
        AppTab.incidents => 'Review speech transcripts, audio playback & camera snapshots',
        AppTab.devices => 'Monitor XIAO ESP32S3 wearable pins (160MHz Standard & 200mAh LiPo)',
        AppTab.analytics => 'Tagalog RoBERTa threat distribution & research metrics',
        AppTab.configuration => 'Configure pre-trigger buffer duration, silence timeouts & camera policies',
      };

  @override
  Widget build(BuildContext context) {
    final time = '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';

    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, letterSpacing: -.5)),
              const SizedBox(height: 2),
              Text(subtitle, style: TextStyle(fontSize: 10, color: Colors.white.withOpacity(.50))),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
          decoration: BoxDecoration(color: Colors.white.withOpacity(.03), borderRadius: BorderRadius.circular(9), border: Border.all(color: Colors.white.withOpacity(.06))),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.access_time_rounded, size: 12, color: Colors.white54),
              const SizedBox(width: 5),
              Text(time, style: TextStyle(color: Colors.white.withOpacity(.7), fontSize: 10.5, fontWeight: FontWeight.w600, fontFamily: 'monospace')),
            ],
          ),
        ),
        const SizedBox(width: 8),
        _HeaderStatusPicker(status: status, onChanged: onStatusChanged),
        const SizedBox(width: 8),
        _HarmfulWordsToggleButton(
          active: harmfulWordsOnly,
          onToggle: onToggleHarmfulWordsOnly,
        ),
        const SizedBox(width: 8),
        _PairPinHeaderButton(
          hasPins: hasOnlinePin,
          onTap: onOpenPinSetup,
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
          decoration: BoxDecoration(color: const Color(0xE60B1016), borderRadius: BorderRadius.circular(11), border: Border.all(color: Colors.white.withOpacity(.07))),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            _StatusDot(active: isServerConnected),
            const SizedBox(width: 6),
            Text(isServerConnected ? 'SERVER ONLINE' : 'CHECKPOINT OFFLINE', style: const TextStyle(fontSize: 8.5, fontWeight: FontWeight.w700, letterSpacing: .6)),
          ]),
        ),
        const SizedBox(width: 6),
        IconButton(
          tooltip: 'Preview Mobile Companion (Phone Edition)',
          onPressed: () {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (ctx) => Scaffold(
                  backgroundColor: const Color(0xFF090C14),
                  body: Stack(
                    children: [
                      const Center(
                        child: SizedBox(
                          width: 440,
                          child: SecureLinkMobileApp(),
                        ),
                      ),
                      Positioned(
                        top: 16,
                        right: 16,
                        child: Material(
                          color: Colors.transparent,
                          child: InkWell(
                            borderRadius: BorderRadius.circular(30),
                            onTap: () => Navigator.of(ctx).pop(),
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                              decoration: BoxDecoration(
                                color: Colors.black.withOpacity(0.7),
                                borderRadius: BorderRadius.circular(30),
                                border: Border.all(color: Colors.white24),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.close_rounded, color: Colors.white, size: 16),
                                  SizedBox(width: 6),
                                  Text('Exit Phone View', style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
          icon: const Icon(Icons.phone_android_rounded, size: 19, color: Color(0xFF55E2C0)),
        ),
        const SizedBox(width: 4),
        IconButton(
          tooltip: 'Central System Mobile Sync Gateway (Priority 1)',
          onPressed: () => _showCentralSystemSyncDialog(context),
          icon: const Icon(Icons.hub_rounded, size: 19, color: Color(0xFF109C6D)),
        ),
        IconButton(
          tooltip: 'Reconnect / Refresh',
          onPressed: refreshing ? null : onRefresh,
          icon: AnimatedSwitcher(
            duration: const Duration(milliseconds: 180),
            child: refreshing ? const SizedBox(key: ValueKey('loader'), width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.refresh_rounded, key: ValueKey('refresh'), size: 19),
          ),
        ),
      ],
    );
  }

  void _showCentralSystemSyncDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0F14),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(22),
          side: const BorderSide(color: Color(0x33109C6D)),
        ),
        title: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF109C6D), Color(0xFF55E2C0)],
                ),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.hub_rounded, color: Colors.white, size: 20),
            ),
            const SizedBox(width: 12),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Central System Gateway',
                    style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                  Text(
                    'Primary Life-Safety & AI Hub (Priority 1)',
                    style: TextStyle(color: Color(0xFF55E2C0), fontSize: 10.5, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ],
        ),
        content: SizedBox(
          width: 440,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.035),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withOpacity(0.08)),
                ),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Connection Hierarchy Architecture',
                      style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
                    ),
                    SizedBox(height: 6),
                    Text(
                      '• Priority 1 (Primary): Central System (This Laptop)\n  Pins stream raw 16kHz audio here for Faster-Whisper STT & TagalogBERT classification.\n\n• Priority 2 (Secondary): Mobile Companion (Teacher/Student)\n  Central System verifies incidents and pushes real-time safety alerts and battery telemetry to the paired phone.',
                      style: TextStyle(color: Colors.white70, fontSize: 10.5, height: 1.4),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),

              // Server host & port card
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: const Color(0xFF123524).withOpacity(0.4),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.4)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.dns_rounded, color: Color(0xFF55E2C0), size: 22),
                    const SizedBox(width: 12),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Central System IP', style: TextStyle(color: Colors.white60, fontSize: 10)),
                          Text('10.28.20.11:8080', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w800)),
                          Text('UDP Auto-Discovery Beacon: Port 8888 Active', style: TextStyle(color: Color(0xFF55E2C0), fontSize: 9.5)),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFF109C6D),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Text('CS-1', style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w900)),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),

              const Text(
                'How to Sync with Mobile Companion:',
                style: TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              const Text(
                '1. Open SecureLink Mobile on teacher or student phone.\n2. Tap "Auto-Discover Central System" or enter 10.28.20.11.\n3. The phone will link to CS-1 and immediately receive verified threat alerts.',
                style: TextStyle(color: Colors.white60, fontSize: 10.5, height: 1.4),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close', style: TextStyle(color: Colors.white70)),
          ),
        ],
      ),
    );
  }
}

class _HeaderStatusPicker extends StatelessWidget {
  final DashboardStatus status;
  final ValueChanged<DashboardStatus> onChanged;

  const _HeaderStatusPicker({required this.status, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final c = status.accent;
    return PopupMenuButton<DashboardStatus>(
      tooltip: 'Override threat status',
      onSelected: onChanged,
      color: const Color(0xFF111722),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: BorderSide(color: Colors.white.withOpacity(.08))),
      itemBuilder: (context) => DashboardStatus.values.map((value) => PopupMenuItem<DashboardStatus>(value: value, child: Row(children: [Icon(value.icon, size: 15, color: value.accent), const SizedBox(width: 8), Text(value.label, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600, color: value == status ? Colors.white : Colors.white.withOpacity(.72)))]))).toList(),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
        decoration: BoxDecoration(color: c.withOpacity(.10), borderRadius: BorderRadius.circular(11), border: Border.all(color: c.withOpacity(.18))),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(status.icon, color: c, size: 13),
            const SizedBox(width: 5),
            Text(status.label, style: TextStyle(color: c, fontSize: 8.5, fontWeight: FontWeight.w700, letterSpacing: .7)),
          ],
        ),
      ),
    );
  }
}

class _HarmfulWordsToggleButton extends StatelessWidget {
  final bool active;
  final VoidCallback onToggle;

  const _HarmfulWordsToggleButton({
    required this.active,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: active
          ? 'Harmful Words Filter: ACTIVE\nOnly threats, verbal harassment & harmful keywords trigger incidents.\nBenign conversational speech is ignored.'
          : 'Harmful Words Filter: INACTIVE\nMonitoring all spoken conversation.\nClick to detect harmful words & threats only.',
      waitDuration: const Duration(milliseconds: 300),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onToggle,
          borderRadius: BorderRadius.circular(11),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6.5),
            decoration: BoxDecoration(
              gradient: active
                  ? const LinearGradient(
                      colors: [Color(0xFF0C3829), Color(0xFF06221A)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    )
                  : LinearGradient(
                      colors: [Colors.white.withOpacity(0.04), Colors.white.withOpacity(0.02)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(
                color: active ? const Color(0xFF109C6D).withOpacity(0.85) : Colors.white.withOpacity(0.09),
                width: active ? 1.2 : 1.0,
              ),
              boxShadow: active
                  ? [
                      BoxShadow(
                        color: const Color(0xFF109C6D).withOpacity(0.40),
                        blurRadius: 10,
                        spreadRadius: 1,
                      )
                    ]
                  : null,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  active ? Icons.shield_rounded : Icons.shield_outlined,
                  size: 13.5,
                  color: active ? const Color(0xFF55E2C0) : Colors.white60,
                ),
                const SizedBox(width: 6),
                Text(
                  'HARMFUL ONLY',
                  style: TextStyle(
                    fontSize: 8.5,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.6,
                    color: active ? const Color(0xFF55E2C0) : Colors.white70,
                  ),
                ),
                const SizedBox(width: 5),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 4.5, vertical: 1.5),
                  decoration: BoxDecoration(
                    color: active ? const Color(0xFF109C6D) : Colors.white.withOpacity(0.10),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    active ? 'ON' : 'OFF',
                    style: TextStyle(
                      fontSize: 7.5,
                      fontWeight: FontWeight.w900,
                      color: active ? Colors.white : Colors.white54,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _OverviewPage extends StatelessWidget {
  final List<Incident> incidents;
  final List<DeviceStatus> devices;
  final DashboardStatus status;
  final bool isServerConnected;
  final int bufferDurationSeconds;
  final VoidCallback onOpenPinSetup;

  const _OverviewPage({
    required this.incidents,
    required this.devices,
    required this.status,
    required this.isServerConnected,
    required this.bufferDurationSeconds,
    required this.onOpenPinSetup,
  });

  @override
  Widget build(BuildContext context) {
    final active = devices.where((d) => d.online).length;
    final nonNormal = incidents.where((i) => i.level != IncidentLevel.normal).length;
    final danger = incidents.where((i) => i.level == IncidentLevel.danger).length;

    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 980;
        if (compact) {
          return SingleChildScrollView(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(
              children: [
                _StatusHero(status: status, activeDevices: active, totalDevices: devices.length, incidentCount: incidents.length),
                const SizedBox(height: 10),
                _MetricStrip(active: active, nonNormal: nonNormal, danger: danger),
                const SizedBox(height: 10),
                SizedBox(height: 380, child: _RecentIncidents(incidents)),
                const SizedBox(height: 10),
                SizedBox(height: 280, child: _CompactDeviceList(devices, onOpenPinSetup: onOpenPinSetup)),
                const SizedBox(height: 10),
                SizedBox(
                  height: 120,
                  child: _DashboardInfoRow(
                    status: status,
                    devices: devices,
                    isServerConnected: isServerConnected,
                    bufferDurationSeconds: bufferDurationSeconds,
                  ),
                ),
              ],
            ),
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(height: 80, child: _StatusHero(status: status, activeDevices: active, totalDevices: devices.length, incidentCount: incidents.length)),
            const SizedBox(height: 10),
            SizedBox(height: 106, child: _MetricStrip(active: active, nonNormal: nonNormal, danger: danger)),
            const SizedBox(height: 10),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(flex: 7, child: _RecentIncidents(incidents)),
                  const SizedBox(width: 10),
                  Expanded(flex: 5, child: _CompactDeviceList(devices, onOpenPinSetup: onOpenPinSetup)),
                ],
              ),
            ),
            const SizedBox(height: 10),
            SizedBox(
              height: 110,
              child: _DashboardInfoRow(
                status: status,
                devices: devices,
                isServerConnected: isServerConnected,
                bufferDurationSeconds: bufferDurationSeconds,
              ),
            ),
          ],
        );
      },
    );
  }
}

class _MetricStrip extends StatelessWidget {
  final int active;
  final int nonNormal;
  final int danger;
  const _MetricStrip({required this.active, required this.nonNormal, required this.danger});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _MetricCard(label: 'ACTIVE PINS', value: '$active', caption: '160MHz Xiao S3 Connected', icon: Icons.sensors_rounded, color: const Color(0xFF61D9AA))),
        const SizedBox(width: 10),
        Expanded(child: _MetricCard(label: 'THREAT ALERTS', value: '$nonNormal', caption: 'verbal & extortion events', icon: Icons.warning_amber_rounded, color: const Color(0xFFFFC45D))),
        const SizedBox(width: 10),
        Expanded(child: _MetricCard(label: 'DANGER ESCALATIONS', value: '$danger', caption: 'OV2640 snapshot triggered', icon: Icons.emergency_rounded, color: const Color(0xFFFF5E72))),
        const SizedBox(width: 10),
        const Expanded(child: _MetricCard(label: 'VAD ENGINE', value: 'ACTIVE', caption: '16kHz Speex + RoBERTa', icon: Icons.multitrack_audio_rounded, color: Color(0xFF9B84FF))),
      ],
    );
  }
}

class _StatusHero extends StatelessWidget {
  final DashboardStatus status;
  final int activeDevices;
  final int totalDevices;
  final int incidentCount;

  const _StatusHero({required this.status, required this.activeDevices, required this.totalDevices, required this.incidentCount});

  @override
  Widget build(BuildContext context) {
    final c = status.accent;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 350),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        gradient: LinearGradient(colors: [c.withOpacity(.10), c.withOpacity(.03), Colors.white.withOpacity(.015)]),
        border: Border.all(color: c.withOpacity(.16)),
      ),
      child: Row(
        children: [
          Container(width: 40, height: 40, decoration: BoxDecoration(shape: BoxShape.circle, color: c.withOpacity(.08), border: Border.all(color: c.withOpacity(.16))), child: Icon(status.icon, color: c, size: 20)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('CAMPUS SAFETY STATUS', style: TextStyle(color: Colors.white.withOpacity(.35), fontSize: 8, fontWeight: FontWeight.w600, letterSpacing: .9)),
                const SizedBox(height: 2),
                Text(status.label, style: TextStyle(color: c, fontSize: 18, fontWeight: FontWeight.w700)),
              ],
            ),
          ),
          _StatusMetric(label: 'PINS ONLINE', value: '$activeDevices/$totalDevices'),
          const SizedBox(width: 20),
          _StatusMetric(label: 'EVENTS DETECTED', value: '$incidentCount'),
          const SizedBox(width: 20),
          const _StatusMetric(label: 'SPEECH ENGINE', value: '16kHz PCM'),
        ],
      ),
    );
  }
}

class _StatusMetric extends StatelessWidget {
  final String label;
  final String value;
  const _StatusMetric({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(label, style: TextStyle(color: Colors.white.withOpacity(.30), fontSize: 7.5, fontWeight: FontWeight.w600, letterSpacing: .7)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
      ],
    );
  }
}

class _DashboardInfoRow extends StatelessWidget {
  final DashboardStatus status;
  final List<DeviceStatus> devices;
  final bool isServerConnected;
  final int bufferDurationSeconds;

  const _DashboardInfoRow({
    required this.status,
    required this.devices,
    required this.isServerConnected,
    required this.bufferDurationSeconds,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(
          child: _MiniPanel(
            title: 'NETWORK HEALTH',
            child: _NetworkHealth(
              devices: devices,
              isServerConnected: isServerConnected,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _MiniPanel(
            title: 'EDGE & AI PIPELINE',
            child: _PipelineStatus(
              devices: devices,
              isServerConnected: isServerConnected,
              bufferDurationSeconds: bufferDurationSeconds,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(child: _MiniPanel(title: 'SYSTEM ADVISORY', child: _SystemNotes(status: status))),
      ],
    );
  }
}

class _MiniPanel extends StatelessWidget {
  final String title;
  final Widget child;
  const _MiniPanel({required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return _Glass(radius: 16, padding: const EdgeInsets.fromLTRB(12, 8, 12, 8), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TextStyle(color: Colors.white.withOpacity(.30), fontSize: 8, fontWeight: FontWeight.w700, letterSpacing: .9)), const SizedBox(height: 5), Expanded(child: child)]));
  }
}

class _NetworkHealth extends StatelessWidget {
  final List<DeviceStatus> devices;
  final bool isServerConnected;

  const _NetworkHealth({
    required this.devices,
    required this.isServerConnected,
  });

  @override
  Widget build(BuildContext context) {
    final activePin = devices.where((d) => d.online).firstOrNull ?? devices.firstOrNull;
    final isPinOnline = activePin != null && activePin.online;

    // Real Wi-Fi Network Name from connected pin or gateway
    final wifiName = isPinOnline
        ? (activePin.network.isNotEmpty ? activePin.network : 'Campus Wi-Fi')
        : (isServerConnected ? 'Campus Wi-Fi (Standby)' : 'Disconnected');
    final wifiColor = isPinOnline
        ? const Color(0xFF57DDA0)
        : (isServerConnected ? const Color(0xFFFFC45D) : const Color(0xFFFF5E72));

    // Real Transmission / RSSI Signal
    final transmission = isPinOnline
        ? '${activePin.rssi} dBm (RSSI)'
        : (isServerConnected ? 'Gateway Active (Port 8080)' : 'Gateway Offline');
    final transmissionColor = isPinOnline
        ? (activePin.rssi >= -68 ? const Color(0xFF57DDA0) : const Color(0xFFFFC45D))
        : (isServerConnected ? const Color(0xFF57DDA0) : const Color(0xFFFF5E72));

    // Real Power & Battery Target
    final batteryInfo = activePin != null
        ? '${activePin.battery}% • ${activePin.estRuntime}'
        : (isServerConnected ? 'Inference Engine Ready' : 'AI Server Offline');
    final batteryColor = activePin != null
        ? (activePin.battery > 25 ? const Color(0xFF57DDA0) : const Color(0xFFFF5E72))
        : (isServerConnected ? const Color(0xFF9B84FF) : const Color(0xFFFF5E72));

    return Column(
      children: [
        _InfoRow(icon: Icons.wifi_rounded, label: 'Campus Wi-Fi', value: wifiName, color: wifiColor),
        _InfoRow(icon: Icons.speed_rounded, label: 'Transmission', value: transmission, color: transmissionColor),
        _InfoRow(icon: Icons.battery_charging_full_rounded, label: 'Power Target', value: batteryInfo, color: batteryColor),
      ],
    );
  }
}

class _PipelineStatus extends StatelessWidget {
  final List<DeviceStatus> devices;
  final bool isServerConnected;
  final int bufferDurationSeconds;

  const _PipelineStatus({
    required this.devices,
    required this.isServerConnected,
    required this.bufferDurationSeconds,
  });

  @override
  Widget build(BuildContext context) {
    final activePin = devices.where((d) => d.online).firstOrNull ?? devices.firstOrNull;
    final isPinOnline = activePin != null && activePin.online;

    return Column(
      children: [
        _PipelineStep(
          label: isPinOnline ? '16kHz PDM & Speex VAD (${activePin.id})' : '16kHz PDM & Speex VAD',
          state: isPinOnline ? activePin.state : 'PIN STANDBY',
          color: isPinOnline ? const Color(0xFF57DDA0) : Colors.white38,
          icon: isPinOnline ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
        ),
        _PipelineStep(
          label: '${bufferDurationSeconds}s PSRAM Audio Pre-roll',
          state: isPinOnline ? 'ARMED' : 'READY',
          color: const Color(0xFF57DDA0),
          icon: Icons.check_circle_rounded,
        ),
        _PipelineStep(
          label: 'Faster-Whisper STT (Tagalog)',
          state: isServerConnected ? 'ONLINE' : 'OFFLINE',
          color: isServerConnected ? const Color(0xFF57DDA0) : const Color(0xFFFF5E72),
          icon: isServerConnected ? Icons.check_circle_rounded : Icons.cancel_rounded,
        ),
        _PipelineStep(
          label: 'TagalogBERT 4-Class Threat NLP',
          state: isServerConnected ? 'ONLINE' : 'OFFLINE',
          color: isServerConnected ? const Color(0xFF57DDA0) : const Color(0xFFFF5E72),
          icon: isServerConnected ? Icons.check_circle_rounded : Icons.cancel_rounded,
        ),
      ],
    );
  }
}

class _PipelineStep extends StatelessWidget {
  final String label;
  final String state;
  final Color color;
  final IconData icon;

  const _PipelineStep({
    required this.label,
    required this.state,
    this.color = const Color(0xFF57DDA0),
    this.icon = Icons.check_circle_rounded,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Row(
        children: [
          Icon(icon, color: color, size: 11),
          const SizedBox(width: 5),
          Expanded(child: Text(label, style: TextStyle(color: Colors.white.withOpacity(.55), fontSize: 8.5))),
          Text(state, style: TextStyle(color: color, fontSize: 7, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _SystemNotes extends StatelessWidget {
  final DashboardStatus status;
  const _SystemNotes({required this.status});

  @override
  Widget build(BuildContext context) {
    final note = switch (status) {
      DashboardStatus.safe => 'Fleet running optimally. Voice detection armed in standby mode.',
      DashboardStatus.warning => 'Heated speech detected. Auto-archiving audio evidence.',
      DashboardStatus.threat => 'Extortion or intimidation pattern detected. Audio recorded.',
      DashboardStatus.danger => 'CRITICAL THREAT: Direct violence detected. Camera snapshot captured.'
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(note, style: TextStyle(color: Colors.white.withOpacity(.65), fontSize: 8.5, height: 1.25)), const Spacer(), Text('SecureLink Threat Detection Engine v2.0', style: TextStyle(color: Colors.white.withOpacity(.22), fontSize: 7))]);
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;
  const _InfoRow({required this.icon, required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Padding(padding: const EdgeInsets.only(bottom: 3), child: Row(children: [Icon(icon, color: Colors.white54, size: 11), const SizedBox(width: 5), Expanded(child: Text(label, style: TextStyle(color: Colors.white.withOpacity(.54), fontSize: 8))), Text(value, style: TextStyle(color: color, fontSize: 7, fontWeight: FontWeight.w700))]));
  }
}

class _MetricCard extends StatelessWidget {
  final String label, value, caption;
  final IconData icon;
  final Color color;
  const _MetricCard({required this.label, required this.value, required this.caption, required this.icon, required this.color});

  @override
  Widget build(BuildContext context) {
    return _Glass(
      radius: 18,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(children: [Container(width: 28, height: 28, decoration: BoxDecoration(color: color.withOpacity(.10), borderRadius: BorderRadius.circular(8)), child: Icon(icon, size: 15, color: color)), const Spacer(), Container(width: 5, height: 5, decoration: BoxDecoration(color: color, shape: BoxShape.circle))]),
          const SizedBox(height: 6),
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: Colors.white.withOpacity(.50), fontSize: 8, fontWeight: FontWeight.w600, letterSpacing: .8)),
          const SizedBox(height: 1),
          Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 22, height: 1.0, fontWeight: FontWeight.w700, letterSpacing: -.4)),
          const SizedBox(height: 2),
          Text(caption, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: Colors.white.withOpacity(.42), fontSize: 8, height: 1.0)),
        ],
      ),
    );
  }
}

// Threat keyword detection for high-impact forensic transcript review
Widget _buildThreatTranscript(
  String text, {
  double fontSize = 10.5,
  FontWeight fontWeight = FontWeight.w400,
  FontStyle fontStyle = FontStyle.normal,
  Color baseColor = const Color(0xFFDCE2EC),
  int? maxLines,
}) {
  const hardThreats = {
    'papatayin', 'patayin', 'bugbugin', 'sasapakin', 'suntukin', 'tadyakan',
    'upakan', 'abangan', 'tumba', 'hiwain', 'masaktan', 'resbak', 'yari'
  };
  const hardExtort = {
    'pera', 'bayad', 'ambag', 'ilabas', 'akin na', 'bigyan', 'palamunin'
  };
  const hardHarass = {
    'bobo', 'tanga', 'kwenta', 'kuwenta', 'kupal', 'bwisit', 'inutil', 'kadiri', 'pangit'
  };

  final words = text.split(' ');
  final spans = <InlineSpan>[];

  for (int i = 0; i < words.length; i++) {
    final word = words[i];
    final clean = word.toLowerCase().replaceAll(RegExp(r'[^a-zA-Z0-9]'), '');

    Color? tagColor;
    Color? glowColor;

    if (hardThreats.contains(clean)) {
      tagColor = const Color(0xFFFF4D67);
      glowColor = const Color(0xFFFF4D67).withOpacity(0.35);
    } else if (hardExtort.contains(clean)) {
      tagColor = const Color(0xFFFFB800);
      glowColor = const Color(0xFFFFB800).withOpacity(0.30);
    } else if (hardHarass.contains(clean)) {
      tagColor = const Color(0xFFFFC45D);
      glowColor = const Color(0xFFFFC45D).withOpacity(0.25);
    }

    if (tagColor != null) {
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 1.5, vertical: 0.5),
            padding: const EdgeInsets.symmetric(horizontal: 4.5, vertical: 1.5),
            decoration: BoxDecoration(
              color: tagColor.withOpacity(0.16),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: tagColor.withOpacity(0.42), width: 0.8),
              boxShadow: [
                BoxShadow(
                  color: glowColor!,
                  blurRadius: 5,
                  spreadRadius: 0.5,
                ),
              ],
            ),
            child: Text(
              word,
              style: TextStyle(
                color: tagColor,
                fontSize: fontSize,
                fontWeight: FontWeight.w700,
                fontStyle: fontStyle,
              ),
            ),
          ),
        ),
      );
      spans.add(const TextSpan(text: ' '));
    } else {
      spans.add(
        TextSpan(
          text: '$word ',
          style: TextStyle(
            color: baseColor,
            fontSize: fontSize,
            fontWeight: fontWeight,
            fontStyle: fontStyle,
          ),
        ),
      );
    }
  }

  return RichText(
    maxLines: maxLines,
    overflow: maxLines != null ? TextOverflow.ellipsis : TextOverflow.clip,
    text: TextSpan(children: spans),
  );
}

class _IncidentRow extends StatefulWidget {
  final Incident incident;
  const _IncidentRow({super.key, required this.incident});

  @override
  State<_IncidentRow> createState() => _IncidentRowState();
}

class _IncidentRowState extends State<_IncidentRow> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final incident = widget.incident;
    final level = incident.level;

    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 140),
        curve: Curves.easeOutQuad,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: _hover ? Colors.white.withOpacity(0.045) : Colors.white.withOpacity(0.02),
          borderRadius: BorderRadius.circular(13),
          border: Border.all(
            color: _hover ? level.color.withOpacity(0.28) : Colors.white.withOpacity(0.04),
            width: 1.0,
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                color: level.color.withOpacity(.12),
                border: Border.all(color: level.color.withOpacity(.20), width: 0.8),
              ),
              child: Icon(level.icon, color: level.color, size: 16),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Row(
                    children: [
                      Text(
                        level.label,
                        style: TextStyle(
                          color: level.color,
                          fontSize: 8.5,
                          fontWeight: FontWeight.w700,
                          letterSpacing: .6,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          incident.category,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: Colors.white.withOpacity(.38), fontSize: 8),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  _buildThreatTranscript(
                    incident.transcript,
                    fontSize: 10.5,
                    maxLines: 1,
                    baseColor: Colors.white.withOpacity(.78),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(incident.time, style: TextStyle(color: Colors.white.withOpacity(.34), fontSize: 8)),
                const SizedBox(height: 4),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: level.color.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: level.color.withOpacity(0.25), width: 0.8),
                  ),
                  child: Text(
                    '${incident.score.toStringAsFixed(1)}/10',
                    style: TextStyle(fontSize: 7.5, fontWeight: FontWeight.w700, color: level.color),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentIncidents extends StatelessWidget {
  final List<Incident> incidents;
  const _RecentIncidents(this.incidents);

  @override
  Widget build(BuildContext context) {
    return _Glass(
      radius: 20,
      padding: const EdgeInsets.fromLTRB(14, 11, 14, 9),
      child: Column(
        children: [
          const _SectionHeader(title: 'Live Incidents Queue', action: 'Streaming...'),
          const SizedBox(height: 7),
          Expanded(child: incidents.isEmpty ? Center(child: Text('Awaiting incoming events...', style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 11))) : ListView.separated(padding: EdgeInsets.zero, physics: const ClampingScrollPhysics(), itemCount: incidents.length, separatorBuilder: (_, __) => const SizedBox(height: 5), itemBuilder: (_, index) { return _IncidentRow(incident: incidents[index]); })),
        ],
      ),
    );
  }
}

class _CompactDeviceList extends StatelessWidget {
  final List<DeviceStatus> devices;
  final VoidCallback onOpenPinSetup;

  const _CompactDeviceList(this.devices, {required this.onOpenPinSetup});

  @override
  Widget build(BuildContext context) {
    final activeCount = devices.where((d) => d.online).length;
    final totalCount = devices.length;
    final ratio = totalCount == 0 ? 0.0 : (activeCount / totalCount);

    return _Glass(
      radius: 20,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Expanded(child: _SectionHeader(title: 'Connected Wearable Pins', action: 'XIAO ESP32S3 Fleet')),
              InkWell(
                onTap: onOpenPinSetup,
                borderRadius: BorderRadius.circular(6),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.add_circle_outline_rounded, size: 12, color: Color(0xFF55E2C0)),
                      const SizedBox(width: 4),
                      Text('Pair Pin', style: TextStyle(color: const Color(0xFF55E2C0), fontSize: 9, fontWeight: FontWeight.w700)),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (devices.isEmpty)
            Expanded(
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.sensors_off_rounded, size: 26, color: Colors.white.withOpacity(.25)),
                    const SizedBox(height: 6),
                    Text(
                      'No pins detected.\nPlug in pin or connect via Wi-Fi.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.white.withOpacity(.38), fontSize: 10),
                    ),
                    const SizedBox(height: 8),
                    TextButton.icon(
                      onPressed: onOpenPinSetup,
                      icon: const Icon(Icons.usb_rounded, size: 13),
                      label: const Text('Pair Smart Pin', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                      style: TextButton.styleFrom(
                        foregroundColor: const Color(0xFF55E2C0),
                        backgroundColor: const Color(0xFF109C6D).withOpacity(0.14),
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                      ),
                    ),
                  ],
                ),
              ),
            )
          else ...[
            Expanded(
              child: ListView.separated(
                padding: EdgeInsets.zero,
                itemCount: devices.length,
                separatorBuilder: (_, __) => const SizedBox(height: 5),
                itemBuilder: (_, index) => _DeviceRow(device: devices[index]),
              ),
            ),
            Divider(color: Colors.white.withOpacity(.06), height: 1),
            const SizedBox(height: 8),
            Row(children: [Expanded(child: _FleetMetric(label: 'ONLINE STATUS', value: '$activeCount OF $totalCount ACTIVE', color: const Color(0xFF57DDA0))), const Expanded(child: _FleetMetric(label: 'CLOCK RATE', value: '160MHz BALANCED', color: Color(0xFF9B84FF)))]),
            const SizedBox(height: 6),
            ClipRRect(borderRadius: BorderRadius.circular(8), child: LinearProgressIndicator(minHeight: 4, value: ratio, backgroundColor: Colors.white.withOpacity(.05), valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFF57DDA0)))),
          ],
        ],
      ),
    );
  }
}

class _FleetMetric extends StatelessWidget {
  final String label, value;
  final Color color;
  const _FleetMetric({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: TextStyle(color: Colors.white.withOpacity(.32), fontSize: 7.5, fontWeight: FontWeight.w600, letterSpacing: .7)), const SizedBox(height: 2), Text(value, style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w700))]);
}

class _DeviceRow extends StatelessWidget {
  final DeviceStatus device;
  const _DeviceRow({required this.device});

  @override
  Widget build(BuildContext context) {
    final batteryColor = device.battery <= 20 ? const Color(0xFFFF5E72) : device.battery <= 35 ? const Color(0xFFFFC45D) : const Color(0xFF5BDC9F);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: Colors.white.withOpacity(.02), borderRadius: BorderRadius.circular(11)),
      child: Row(
        children: [
          Container(width: 7, height: 7, decoration: BoxDecoration(shape: BoxShape.circle, color: device.online ? const Color(0xFF57DDA0) : Colors.white24)),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(device.id, style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700)),
                Text('${device.cpuMhz}MHz • ${device.rssi} dBm', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.35))),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
            decoration: BoxDecoration(color: Colors.white.withOpacity(0.04), borderRadius: BorderRadius.circular(5)),
            child: Text(device.state, style: TextStyle(color: Colors.white.withOpacity(.55), fontSize: 7.5, fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 8),
          Text('${device.battery}%', style: TextStyle(color: batteryColor, fontSize: 9, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  final bool online;
  final String state;
  const _StatusPill({required this.online, this.state = ''});

  @override
  Widget build(BuildContext context) {
    final s = state.toUpperCase();
    final isStreaming = s.contains('STREAMING');
    final isAnalyzing = s.contains('ANALYZING');
    
    Color color;
    String label;
    IconData icon;
    
    if (isStreaming) {
      color = const Color(0xFF38BDF8); // Cyan
      label = 'STREAMING AUDIO';
      icon = Icons.graphic_eq_rounded;
    } else if (isAnalyzing) {
      color = const Color(0xFFA78BFA); // Lavender
      label = 'ANALYZING SPEECH';
      icon = Icons.psychology_rounded;
    } else if (online) {
      color = const Color(0xFF54DCA0); // Emerald
      label = 'ARMED (STANDBY)';
      icon = Icons.security_rounded;
    } else {
      color = Colors.white38;
      label = 'OFFLINE';
      icon = Icons.power_settings_new_rounded;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: color.withOpacity(0.12),
        border: Border.all(color: color.withOpacity(0.30)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 10, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(color: color, fontSize: 7.5, fontWeight: FontWeight.w700, letterSpacing: 0.4),
          ),
        ],
      ),
    );
  }
}

class _DevicesPage extends StatelessWidget {
  final List<DeviceStatus> devices;
  final List<WifiCheckpoint> checkpoints;
  final VoidCallback onOpenPinSetup;
  final ValueChanged<DeviceStatus> onConfigurePinWifi;

  const _DevicesPage({
    required this.devices,
    required this.checkpoints,
    required this.onOpenPinSetup,
    required this.onConfigurePinWifi,
  });

  @override
  Widget build(BuildContext context) {
    if (devices.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 76,
              height: 76,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF109C6D).withOpacity(0.12),
                border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.35)),
              ),
              child: const Icon(Icons.sensors_rounded, size: 38, color: Color(0xFF55E2C0)),
            ),
            const SizedBox(height: 16),
            const Text(
              'No Active Smart Pins Connected',
              style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            SizedBox(
              width: 420,
              child: Text(
                'Plug your XIAO ESP32S3 pin into this laptop via USB or connect via the "SecureLink-Setup" Wi-Fi hotspot to begin streaming audio and telemetry.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white.withOpacity(.50), fontSize: 11, height: 1.4),
              ),
            ),
            const SizedBox(height: 20),
            ElevatedButton.icon(
              onPressed: onOpenPinSetup,
              icon: const Icon(Icons.usb_rounded, size: 16),
              label: const Text('Pair Smart Pin (USB or Wi-Fi)', style: TextStyle(fontWeight: FontWeight.w700)),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF109C6D),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 13),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(11)),
                elevation: 4,
              ),
            ),
          ],
        ),
      );
    }
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('${devices.length} Hardware Pin(s) Registered (${devices.where((d) => d.online).length} Active)', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Colors.white70)),
            OutlinedButton.icon(
              onPressed: onOpenPinSetup,
              icon: const Icon(Icons.add_rounded, size: 14, color: Color(0xFF55E2C0)),
              label: const Text('Pair / Configure Pin', style: TextStyle(fontSize: 10.5, color: Color(0xFF55E2C0), fontWeight: FontWeight.w600)),
              style: OutlinedButton.styleFrom(
                side: BorderSide(color: const Color(0xFF109C6D).withOpacity(0.4)),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Expanded(
          child: GridView.builder(
            padding: const EdgeInsets.only(bottom: 8),
            gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
              maxCrossAxisExtent: 440,
              crossAxisSpacing: 12,
              mainAxisSpacing: 12,
              mainAxisExtent: 255,
            ),
            itemCount: devices.length,
            itemBuilder: (_, index) => _DeviceCard(
              device: devices[index],
              onConfigureWifi: onConfigurePinWifi,
            ),
          ),
        ),
      ],
    );
  }
}

class _DeviceCard extends StatelessWidget {
  final DeviceStatus device;
  final ValueChanged<DeviceStatus> onConfigureWifi;
  const _DeviceCard({required this.device, required this.onConfigureWifi});

  @override
  Widget build(BuildContext context) {
    final batteryColor = device.battery <= 20 ? const Color(0xFFFF5E72) : device.battery <= 35 ? const Color(0xFFFFC45D) : const Color(0xFF5BDC9F);
    return _Glass(
      radius: 20,
      padding: const EdgeInsets.all(15),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _StatusPill(online: device.online, state: device.state),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                decoration: BoxDecoration(color: const Color(0xFF7F6CFF).withOpacity(0.10), borderRadius: BorderRadius.circular(7), border: Border.all(color: const Color(0xFF7F6CFF).withOpacity(0.18))),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.bolt_rounded, size: 10, color: Color(0xFF7F6CFF)),
                    const SizedBox(width: 3),
                    Text('${device.cpuMhz} MHz Standard', style: const TextStyle(fontSize: 7.5, fontWeight: FontWeight.w700, color: Color(0xFF7F6CFF))),
                  ],
                ),
              ),
              const Spacer(),
              Text(device.lastSeen, style: TextStyle(color: Colors.white.withOpacity(.28), fontSize: 8.5)),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(color: Colors.white.withOpacity(.04), borderRadius: BorderRadius.circular(12)),
                child: const Icon(Icons.memory_rounded, size: 20, color: Color(0xFF55E2C0)),
              ),
              const SizedBox(width: 10),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(device.id, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 1),
                  Text('XIAO ESP32S3 Sense • PDM Mic + CAM', style: TextStyle(color: Colors.white.withOpacity(.35), fontSize: 8)),
                  const SizedBox(height: 2),
                  Text(device.state, style: TextStyle(
                    color: device.state.contains('STREAMING') ? const Color(0xFF38BDF8) : device.state.contains('ANALYZING') ? const Color(0xFFA78BFA) : const Color(0xFF55E2C0),
                    fontSize: 8.5,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  )),
                ],
              ),
            ],
          ),
          const Spacer(),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(color: Colors.white.withOpacity(0.02), borderRadius: BorderRadius.circular(11), border: Border.all(color: Colors.white.withOpacity(0.04))),
            child: Column(
              children: [
                Row(
                  children: [
                    Icon(Icons.battery_std_rounded, size: 13, color: batteryColor),
                    const SizedBox(width: 4),
                    Text('${device.battery}% (${device.estRuntime})', style: TextStyle(color: batteryColor, fontSize: 8.5, fontWeight: FontWeight.w700)),
                    const Spacer(),
                    Text('200mAh LiPo', style: TextStyle(color: Colors.white.withOpacity(0.28), fontSize: 8)),
                  ],
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(5),
                  child: LinearProgressIndicator(
                    minHeight: 3.5,
                    value: device.battery / 100.0,
                    backgroundColor: Colors.white.withOpacity(0.04),
                    valueColor: AlwaysStoppedAnimation<Color>(batteryColor),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Icon(Icons.wifi_rounded, size: 13, color: Colors.white.withOpacity(.35)),
              const SizedBox(width: 4),
              Expanded(child: Text('${device.network} (${device.rssi} dBm)', style: TextStyle(color: Colors.white.withOpacity(.50), fontSize: 8))),
              const Icon(Icons.sd_card_rounded, size: 11, color: Colors.white30),
              const SizedBox(width: 3),
              Text('8MB PSRAM', style: TextStyle(color: Colors.white.withOpacity(.3), fontSize: 7.5, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => onConfigureWifi(device),
              icon: const Icon(Icons.wifi_password_rounded, size: 12, color: Color(0xFF55E2C0)),
              label: Text('Change Wi-Fi Checkpoint (${device.id})', style: const TextStyle(fontSize: 8.5, color: Color(0xFF55E2C0), fontWeight: FontWeight.w700)),
              style: OutlinedButton.styleFrom(
                side: BorderSide(color: const Color(0xFF109C6D).withOpacity(0.35)),
                backgroundColor: const Color(0xFF109C6D).withOpacity(0.08),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                padding: const EdgeInsets.symmetric(vertical: 6),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _IncidentsPage extends StatefulWidget {
  final List<Incident> incidents;
  const _IncidentsPage({required this.incidents});

  @override
  State<_IncidentsPage> createState() => _IncidentsPageState();
}

class _IncidentsPageState extends State<_IncidentsPage> {
  IncidentLevel? filter;
  Incident? selected;
  final TextEditingController _searchController = TextEditingController();
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    if (widget.incidents.isNotEmpty) {
      selected = widget.incidents.first;
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = widget.incidents.where((i) {
      if (filter != null && i.level != filter) return false;
      if (_searchQuery.isNotEmpty) {
        final q = _searchQuery.toLowerCase();
        final matchText = i.transcript.toLowerCase().contains(q) ||
            i.category.toLowerCase().contains(q) ||
            i.deviceId.toLowerCase().contains(q) ||
            i.id.toLowerCase().contains(q);
        if (!matchText) return false;
      }
      return true;
    }).toList();

    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: Container(
                height: 38,
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.03),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(color: Colors.white.withOpacity(0.05)),
                ),
                child: TextField(
                  controller: _searchController,
                  onChanged: (val) => setState(() => _searchQuery = val),
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w400),
                  decoration: InputDecoration(
                    hintText: 'Search transcripts, incident IDs, categories, or smart pins...',
                    hintStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.28), fontWeight: FontWeight.w400),
                    prefixIcon: const Icon(Icons.search_rounded, size: 15, color: Colors.white38),
                    suffixIcon: _searchQuery.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear_rounded, size: 13),
                            onPressed: () {
                              _searchController.clear();
                              setState(() => _searchQuery = '');
                            },
                          )
                        : null,
                    border: InputBorder.none,
                    contentPadding: const EdgeInsets.symmetric(vertical: 9),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            TextButton.icon(
              onPressed: () {
                final report = widget.incidents.map((e) => '[${e.time}] ${e.id} (${e.level.label} - ${e.score}/10) [${e.deviceId}]: "${e.transcript}"').join('\n');
                Clipboard.setData(ClipboardData(text: report));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('All incident transcripts copied to clipboard!'),
                    backgroundColor: Color(0xFF7F6CFF),
                    duration: Duration(seconds: 2),
                  ),
                );
              },
              icon: const Icon(Icons.ios_share_rounded, size: 13),
              label: const Text('Export Log', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600)),
              style: TextButton.styleFrom(
                backgroundColor: Colors.white.withOpacity(0.035),
                foregroundColor: Colors.white70,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: BorderSide(color: Colors.white.withOpacity(0.06))),
                padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            _FilterChip(label: 'ALL', active: filter == null, onTap: () => setState(() => filter = null)),
            ...IncidentLevel.values.map(
              (level) => Padding(
                padding: const EdgeInsets.only(left: 6),
                child: _FilterChip(
                  label: level.label,
                  active: filter == level,
                  color: level.color,
                  onTap: () => setState(() => filter = filter == level ? null : level),
                ),
              ),
            ),
            const Spacer(),
            Text('${filtered.length} incidents found', style: TextStyle(color: Colors.white.withOpacity(.42), fontSize: 9.5)),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                flex: 7,
                child: _Glass(
                  radius: 20,
                  padding: const EdgeInsets.all(12),
                  child: filtered.isEmpty
                      ? Center(child: Text('No incidents match the current filters.', style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 11)))
                      : ListView.separated(
                          itemCount: filtered.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 5),
                          itemBuilder: (_, index) {
                            final item = filtered[index];
                            final isSel = selected?.id == item.id;
                            return InkWell(
                              borderRadius: BorderRadius.circular(13),
                              onTap: () => setState(() => selected = item),
                              child: Container(
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(13),
                                  border: isSel ? Border.all(color: item.level.color.withOpacity(0.4), width: 1.2) : null,
                                ),
                                child: _IncidentRow(incident: item),
                              ),
                            );
                          },
                        ),
                ),
              ),
              if (selected != null) ...[
                const SizedBox(width: 12),
                Expanded(
                  flex: 5,
                  child: _IncidentDetailCard(incident: selected!),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool active;
  final Color? color;
  final VoidCallback? onTap;
  const _FilterChip({required this.label, required this.active, this.color, this.onTap});

  @override
  Widget build(BuildContext context) {
    final accent = color ?? const Color(0xFF8B77FF);
    return Material(
      color: active ? accent.withOpacity(.12) : Colors.white.withOpacity(.025),
      borderRadius: BorderRadius.circular(9),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(9),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(9),
            border: Border.all(color: active ? accent.withOpacity(.22) : Colors.white.withOpacity(.04)),
          ),
          child: Text(label, style: TextStyle(color: active ? accent : Colors.white.withOpacity(.36), fontSize: 7.5, fontWeight: FontWeight.w700, letterSpacing: .7)),
        ),
      ),
    );
  }
}

class _IncidentDetailCard extends StatefulWidget {
  final Incident incident;
  const _IncidentDetailCard({required this.incident});

  @override
  State<_IncidentDetailCard> createState() => _IncidentDetailCardState();
}

class _IncidentDetailCardState extends State<_IncidentDetailCard> {
  late final AudioPlayer _audioPlayer;
  bool isPlaying = false;
  double playProgress = 0.0;
  Duration _duration = Duration.zero;
  Duration _position = Duration.zero;
  StreamSubscription? _posSub;
  StreamSubscription? _durSub;
  StreamSubscription? _stateSub;
  StreamSubscription? _completeSub;

  @override
  void initState() {
    super.initState();
    _audioPlayer = AudioPlayer();
    _initAudioPlayer();
  }

  void _initAudioPlayer() {
    _stateSub = _audioPlayer.onPlayerStateChanged.listen((state) {
      if (!mounted) return;
      setState(() {
        isPlaying = (state == PlayerState.playing);
      });
    });

    _durSub = _audioPlayer.onDurationChanged.listen((d) {
      if (!mounted) return;
      setState(() => _duration = d);
    });

    _posSub = _audioPlayer.onPositionChanged.listen((p) {
      if (!mounted) return;
      setState(() {
        _position = p;
        if (_duration.inMilliseconds > 0) {
          playProgress = (_position.inMilliseconds / _duration.inMilliseconds).clamp(0.0, 1.0);
        }
      });
    });

    _completeSub = _audioPlayer.onPlayerComplete.listen((_) {
      if (!mounted) return;
      setState(() {
        isPlaying = false;
        playProgress = 0.0;
        _position = Duration.zero;
      });
    });
  }

  @override
  void didUpdateWidget(covariant _IncidentDetailCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.incident.id != widget.incident.id) {
      _audioPlayer.stop();
      setState(() {
        isPlaying = false;
        playProgress = 0.0;
        _position = Duration.zero;
        _duration = Duration.zero;
      });
    }
  }

  @override
  void dispose() {
    _posSub?.cancel();
    _durSub?.cancel();
    _stateSub?.cancel();
    _completeSub?.cancel();
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _togglePlay() async {
    if (isPlaying) {
      await _audioPlayer.pause();
    } else {
      final incident = widget.incident;
      final String filename = incident.audioFile ?? '${incident.id}.wav';

      final List<String> candidatePaths = [
        'recordings/audio/$filename',
        'recordings\\audio\\$filename',
        'securelinkdb/recordings/audio/$filename',
        'd:/Flutter Securelink Dashboard/securelinkdb/recordings/audio/$filename',
        'd:\\Flutter Securelink Dashboard\\securelinkdb\\recordings\\audio\\$filename',
      ];

      String? existingFilePath;
      for (final p in candidatePaths) {
        if (File(p).existsSync()) {
          existingFilePath = p;
          break;
        }
      }

      try {
        if (existingFilePath != null) {
          await _audioPlayer.play(DeviceFileSource(existingFilePath));
        } else if (incident.audioUrl != null && incident.audioUrl!.isNotEmpty) {
          await _audioPlayer.play(UrlSource(incident.audioUrl!));
        } else {
          await _audioPlayer.play(UrlSource('http://127.0.0.1:8080/recordings/audio/$filename'));
        }
      } catch (e) {
        debugPrint('[AUDIO] Playback error: $e');
      }
    }
  }

  Future<void> _seek(double progress) async {
    if (_duration.inMilliseconds > 0) {
      final target = Duration(milliseconds: (progress * _duration.inMilliseconds).round());
      await _audioPlayer.seek(target);
    }
  }

  @override
  Widget build(BuildContext context) {
    final incident = widget.incident;
    final l = incident.level;

    return _Glass(
      radius: 20,
      padding: const EdgeInsets.all(16),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(width: 38, height: 38, decoration: BoxDecoration(color: l.color.withOpacity(.10), borderRadius: BorderRadius.circular(11)), child: Icon(l.icon, color: l.color, size: 18)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(incident.id, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
                      const SizedBox(height: 2),
                      Text('${incident.deviceId} • Captured at ${incident.time}', style: TextStyle(color: Colors.white.withOpacity(.45), fontSize: 9)),
                    ],
                  ),
                ),
                _LevelBadge(level: l),
              ],
            ),
            const SizedBox(height: 14),
            _DetailLine(label: 'CATEGORY', value: incident.category),
            _DetailLine(label: 'THREAT SCORE', value: '${incident.score.toStringAsFixed(1)} / 10.0'),
            _DetailLine(label: 'EVIDENCE TYPE', value: '${incident.audio ? 'AUDIO (16kHz PCM)' : 'NO AUDIO'}${incident.video ? ' + OV2640 CAMERA SNAPSHOT' : ' (CAMERA STANDBY)'}'),
            const Divider(height: 22, color: Colors.white10),

            // SPEECH TRANSCRIPT BOX
            Text('SPEECH TRANSCRIPT', style: TextStyle(color: Colors.white.withOpacity(.32), fontSize: 8, fontWeight: FontWeight.w600, letterSpacing: 1.0)),
            const SizedBox(height: 6),
            // SPEECH TRANSCRIPT BOX WITH FORENSIC KEYWORD HIGHLIGHTING
            Text('FORENSIC SPEECH TRANSCRIPT (TAGALOG / TAGLISH)', style: TextStyle(color: Colors.white.withOpacity(.36), fontSize: 8, fontWeight: FontWeight.w700, letterSpacing: 1.1)),
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(13),
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.30),
                borderRadius: BorderRadius.circular(13),
                border: Border.all(color: Colors.white.withOpacity(0.06)),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.20),
                    blurRadius: 12,
                    offset: const Offset(0, 4),
                  ),
                ],
              ),
              child: _buildThreatTranscript(
                incident.transcript,
                fontSize: 12.5,
                fontStyle: FontStyle.italic,
                baseColor: Colors.white.withOpacity(0.92),
              ),
            ),
            const SizedBox(height: 14),

            // AUDIO EVIDENCE PLAYER WITH DYNAMIC WAVEFORM EQUALIZER & SEEKING
            if (incident.audio) ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('ACOUSTIC EVIDENCE & WAVEFORM', style: TextStyle(color: Colors.white.withOpacity(.36), fontSize: 8, fontWeight: FontWeight.w700, letterSpacing: 1.1)),
                  Text('16kHz PCM • SPEEX VAD', style: TextStyle(color: const Color(0xFF55E2C0).withOpacity(0.7), fontSize: 7.5, fontWeight: FontWeight.w600, letterSpacing: 0.8)),
                ],
              ),
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.024),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withOpacity(0.05)),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.25),
                      blurRadius: 14,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Material(
                          color: Colors.transparent,
                          child: InkWell(
                            onTap: _togglePlay,
                            borderRadius: BorderRadius.circular(10),
                            child: AnimatedContainer(
                              duration: const Duration(milliseconds: 140),
                              width: 36,
                              height: 36,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(10),
                                gradient: LinearGradient(
                                  begin: Alignment.topLeft,
                                  end: Alignment.bottomRight,
                                  colors: isPlaying
                                      ? [const Color(0xFF55E2C0), const Color(0xFF7F6CFF)]
                                      : [const Color(0xFF7F6CFF).withOpacity(0.22), const Color(0xFF7F6CFF).withOpacity(0.10)],
                                ),
                                border: Border.all(color: const Color(0xFF7F6CFF).withOpacity(isPlaying ? 0.8 : 0.25)),
                                boxShadow: [
                                  if (isPlaying)
                                    BoxShadow(
                                      color: const Color(0xFF55E2C0).withOpacity(0.4),
                                      blurRadius: 10,
                                      spreadRadius: 1,
                                    ),
                                ],
                              ),
                              child: Icon(
                                isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                                size: 20,
                                color: isPlaying ? const Color(0xFF071015) : const Color(0xFF7F6CFF),
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    isPlaying ? 'PLAYING AUDIO STREAM...' : 'CLICK WAVEFORM TO SEEK',
                                    style: TextStyle(
                                      fontSize: 8,
                                      fontWeight: FontWeight.w700,
                                      color: isPlaying ? const Color(0xFF55E2C0) : Colors.white.withOpacity(0.40),
                                      letterSpacing: 0.6,
                                    ),
                                  ),
                                  Text(
                                    _duration.inSeconds > 0
                                        ? '${_position.inMinutes.toString().padLeft(2, '0')}:${(_position.inSeconds % 60).toString().padLeft(2, '0')} / ${_duration.inMinutes.toString().padLeft(2, '0')}:${(_duration.inSeconds % 60).toString().padLeft(2, '0')}'
                                        : '00:00 / ${incident.audioDuration}',
                                    style: TextStyle(
                                      fontSize: 8.5,
                                      color: Colors.white.withOpacity(0.70),
                                      fontFamily: 'monospace',
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 5),
                              // Interactive scrub track
                              GestureDetector(
                                behavior: HitTestBehavior.opaque,
                                onHorizontalDragUpdate: (details) {
                                  final box = context.findRenderObject() as RenderBox?;
                                  if (box != null) {
                                    final width = box.size.width - 60;
                                    if (width > 0) {
                                      final newProg = (details.localPosition.dx / width).clamp(0.0, 1.0);
                                      setState(() => playProgress = newProg);
                                      _seek(newProg);
                                    }
                                  }
                                },
                                onTapDown: (details) {
                                  final box = context.findRenderObject() as RenderBox?;
                                  if (box != null) {
                                    final width = box.size.width - 60;
                                    if (width > 0) {
                                      final newProg = (details.localPosition.dx / width).clamp(0.0, 1.0);
                                      setState(() => playProgress = newProg);
                                      _seek(newProg);
                                    }
                                  }
                                },
                                child: ClipRRect(
                                  borderRadius: BorderRadius.circular(5),
                                  child: LinearProgressIndicator(
                                    value: playProgress,
                                    minHeight: 4.5,
                                    backgroundColor: Colors.white.withOpacity(0.05),
                                    valueColor: AlwaysStoppedAnimation<Color>(
                                      incident.level == IncidentLevel.danger
                                          ? const Color(0xFFFF4D67)
                                          : const Color(0xFF7F6CFF),
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),

                    // Interactive reactive equalizer bars
                    GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTapDown: (details) {
                        final box = context.findRenderObject() as RenderBox?;
                        if (box != null) {
                          setState(() {
                            playProgress = (details.localPosition.dx / box.size.width).clamp(0.0, 1.0);
                          });
                        }
                      },
                      child: Container(
                        height: 28,
                        padding: const EdgeInsets.symmetric(horizontal: 2),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: List.generate(32, (index) {
                            final baseH = 5.0 + (sin(index * 0.58) * 8.0 + cos(index * 1.25) * 6.0).abs();
                            final isPlayed = (index / 32.0) <= playProgress;
                            final activeHeight = isPlaying
                                ? max(4.0, baseH * (0.65 + Random().nextDouble() * 0.70))
                                : baseH;

                            final barColor = isPlayed
                                ? (incident.level == IncidentLevel.danger
                                    ? const Color(0xFFFF4D67)
                                    : const Color(0xFF55E2C0))
                                : Colors.white.withOpacity(0.12);

                            return AnimatedContainer(
                              duration: const Duration(milliseconds: 90),
                              width: 3.5,
                              height: activeHeight,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(2.5),
                                color: barColor,
                                boxShadow: [
                                  if (isPlayed && isPlaying)
                                    BoxShadow(
                                      color: barColor.withOpacity(0.45),
                                      blurRadius: 4,
                                      spreadRadius: 0.5,
                                    ),
                                ],
                              ),
                            );
                          }),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
            ],

            // CAMERA SNAPSHOT EVIDENCE (DANGER ONLY)
            if (incident.video && incident.level == IncidentLevel.danger) ...[
              Text('CAMERA FRAME CAPTURE (DANGER EVENT)', style: TextStyle(color: Colors.white.withOpacity(.32), fontSize: 8, fontWeight: FontWeight.w600, letterSpacing: 1.0)),
              const SizedBox(height: 6),
              Container(
                height: 140,
                width: double.infinity,
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.35),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: const Color(0xFFFF4D67).withOpacity(0.3)),
                ),
                child: Stack(
                  children: [
                    Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.videocam_rounded, size: 32, color: const Color(0xFFFF4D67).withOpacity(0.7)),
                          const SizedBox(height: 5),
                          const Text('OV2640 DANGER SNAPSHOT CAPTURED', style: TextStyle(color: Colors.white70, fontSize: 9.5, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 2),
                          Text('320x240 QVGA • Triggered automatically by DANGER grade speech', style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 7.5)),
                        ],
                      ),
                    ),
                    Positioned(
                      top: 7,
                      left: 9,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2.5),
                        decoration: BoxDecoration(color: const Color(0xFFFF4D67).withOpacity(0.2), borderRadius: BorderRadius.circular(5), border: Border.all(color: const Color(0xFFFF4D67).withOpacity(0.4))),
                        child: Text('REC • ${incident.deviceId}', style: const TextStyle(fontSize: 7.5, color: Color(0xFFFF4D67), fontWeight: FontWeight.w700)),
                      ),
                    ),
                    Positioned(
                      bottom: 7,
                      right: 9,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2.5),
                        decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(5)),
                        child: Text('${incident.time} PST', style: const TextStyle(fontSize: 7.5, color: Colors.white70, fontFamily: 'monospace')),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
            ] else ...[
              // Policy banner for non-danger incidents
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.02),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white.withOpacity(0.03)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.videocam_off_outlined, size: 14, color: Colors.white.withOpacity(0.35)),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        'Camera in low-power sleep (OV2640 triggers exclusively on DANGER events to preserve 200mAh battery).',
                        style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.38), fontWeight: FontWeight.w400),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
            ],

            // EXPORT BUTTON
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () {
                  final text = 'INCIDENT REPORT\nID: ${incident.id}\nDevice: ${incident.deviceId}\nTime: ${incident.time}\nLevel: ${incident.level.label}\nScore: ${incident.score}/10\nCategory: ${incident.category}\nTranscript: "${incident.transcript}"';
                  Clipboard.setData(ClipboardData(text: text));
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Incident ${incident.id} report copied to clipboard!'),
                      backgroundColor: const Color(0xFF7F6CFF),
                    ),
                  );
                },
                icon: const Icon(Icons.copy_rounded, size: 13),
                label: const Text('Export Incident Dossier', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600)),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF7F6CFF).withOpacity(0.12),
                  foregroundColor: const Color(0xFF7F6CFF),
                  elevation: 0,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: BorderSide(color: const Color(0xFF7F6CFF).withOpacity(0.2))),
                  padding: const EdgeInsets.symmetric(vertical: 10),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  final String label, value;
  const _DetailLine({required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 80, child: Text(label, style: TextStyle(color: Colors.white.withOpacity(.28), fontSize: 7.5, fontWeight: FontWeight.w600, letterSpacing: .7))),
            Expanded(child: Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w500))),
          ],
        ),
      );
}

// Configuration Page allowing user to configure buffer duration, timeouts, and fleet policies
// Configuration Page allowing admin to configure Wi-Fi Checkpoints, fleet roaming, buffer duration, and timeouts
class _ConfigurationPage extends StatefulWidget {
  final int bufferDuration;
  final int silenceTimeout;
  final int vadStreak;
  final bool autoDangerSnapshot;
  final int wifiBatchMs;
  final List<DeviceStatus> devices;
  final List<WifiCheckpoint> checkpoints;
  final ValueChanged<int> onBufferChanged;
  final ValueChanged<int> onSilenceChanged;
  final ValueChanged<int> onVadStreakChanged;
  final ValueChanged<bool> onAutoSnapshotChanged;
  final ValueChanged<int> onWifiBatchChanged;
  final VoidCallback onSave;
  final VoidCallback onForgetWifi;
  final VoidCallback onAddCheckpoint;
  final ValueChanged<WifiCheckpoint> onEditCheckpoint;
  final ValueChanged<String> onDeleteCheckpoint;
  final Future<void> Function({
    required WifiCheckpoint checkpoint,
    required String target,
    required String method,
    String? comPort,
  }) onDeployCheckpoint;

  const _ConfigurationPage({
    super.key,
    required this.bufferDuration,
    required this.silenceTimeout,
    required this.vadStreak,
    required this.autoDangerSnapshot,
    required this.wifiBatchMs,
    required this.devices,
    required this.checkpoints,
    required this.onBufferChanged,
    required this.onSilenceChanged,
    required this.onVadStreakChanged,
    required this.onAutoSnapshotChanged,
    required this.onWifiBatchChanged,
    required this.onSave,
    required this.onForgetWifi,
    required this.onAddCheckpoint,
    required this.onEditCheckpoint,
    required this.onDeleteCheckpoint,
    required this.onDeployCheckpoint,
  });

  @override
  State<_ConfigurationPage> createState() => _ConfigurationPageState();
}

class _ConfigurationPageState extends State<_ConfigurationPage> {
  String _selectedTarget = 'ALL'; // 'ALL' or individual pin id like 'PIN-001'
  String? _selectedCheckpointId;
  String _deployMethod = 'wifi'; // 'wifi' or 'usb'
  String? _selectedComPort;
  List<Map<String, dynamic>> _comPorts = [];
  bool _isDeploying = false;

  @override
  void initState() {
    super.initState();
    if (widget.checkpoints.isNotEmpty) {
      final def = widget.checkpoints.firstWhere((c) => c.isDefault, orElse: () => widget.checkpoints.first);
      _selectedCheckpointId = def.id;
    }
    _loadComPorts();
  }

  @override
  void didUpdateWidget(covariant _ConfigurationPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_selectedCheckpointId == null && widget.checkpoints.isNotEmpty) {
      final def = widget.checkpoints.firstWhere((c) => c.isDefault, orElse: () => widget.checkpoints.first);
      _selectedCheckpointId = def.id;
    }
  }

  Future<void> _loadComPorts() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/api/network-info'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final rawPorts = (data['serial_ports'] as List? ?? []);
        final portList = rawPorts.map((p) => Map<String, dynamic>.from(p as Map)).toList();
        if (mounted) {
          setState(() {
            _comPorts = portList;
            if (portList.isNotEmpty && _selectedComPort == null) {
              final espPort = portList.firstWhere((p) => p['is_esp'] == true, orElse: () => portList.first);
              _selectedComPort = espPort['port'] as String?;
            }
          });
        }
      }
    } catch (_) {}
  }

  Future<void> _triggerDeploy() async {
    if (widget.checkpoints.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please add at least one authorized checkpoint first.'), backgroundColor: Colors.orange),
      );
      return;
    }
    final chk = widget.checkpoints.firstWhere(
      (c) => c.id == _selectedCheckpointId,
      orElse: () => widget.checkpoints.first,
    );

    setState(() => _isDeploying = true);
    await widget.onDeployCheckpoint(
      checkpoint: chk,
      target: _selectedTarget,
      method: _deployMethod,
      comPort: _selectedComPort,
    );
    if (mounted) setState(() => _isDeploying = false);
  }

  @override
  Widget build(BuildContext context) {
    final psramBytes = widget.bufferDuration * 16000 * 2;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // =========================================================================
          // 1. AUTHORIZED WI-FI CHECKPOINTS (CAMPUS ROAMING)
          // =========================================================================
          _ConfigCard(
            title: 'AUTHORIZED WI-FI CHECKPOINTS (CAMPUS ROAMING)',
            subtitle: 'Pre-authorized campus Wi-Fi access points so pins auto-connect anywhere. Deploy to all pins or target a single device.',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${widget.checkpoints.length} Authorized Checkpoint(s) Configured',
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0)),
                    ),
                    ElevatedButton.icon(
                      onPressed: widget.onAddCheckpoint,
                      icon: const Icon(Icons.add_location_alt_rounded, size: 14),
                      label: const Text('+ Add Checkpoint', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF109C6D),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                if (widget.checkpoints.isEmpty)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.02),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white.withOpacity(0.05)),
                    ),
                    child: Center(
                      child: Column(
                        children: [
                          Icon(Icons.wifi_off_rounded, size: 28, color: Colors.white.withOpacity(0.3)),
                          const SizedBox(height: 6),
                          Text('No authorized checkpoints added yet.', style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 11)),
                          const SizedBox(height: 6),
                          TextButton(
                            onPressed: widget.onAddCheckpoint,
                            child: const Text('Add your first authorized Wi-Fi network', style: TextStyle(color: Color(0xFF55E2C0), fontSize: 10)),
                          ),
                        ],
                      ),
                    ),
                  )
                else
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: widget.checkpoints.map((chk) {
                      final isSelected = _selectedCheckpointId == chk.id;
                      return Container(
                        width: 320,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: isSelected ? const Color(0xFF109C6D).withOpacity(0.12) : Colors.white.withOpacity(0.025),
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: isSelected ? const Color(0xFF109C6D).withOpacity(0.45) : Colors.white.withOpacity(0.06),
                            width: isSelected ? 1.5 : 1.0,
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Container(
                                  padding: const EdgeInsets.all(6),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFF55E2C0).withOpacity(0.12),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: const Icon(Icons.wifi_tethering_rounded, size: 16, color: Color(0xFF55E2C0)),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        chk.name,
                                        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                      Text(
                                        'SSID: ${chk.ssid}',
                                        style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.5)),
                                      ),
                                    ],
                                  ),
                                ),
                                if (chk.isDefault)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: const Color(0xFF109C6D).withOpacity(0.20),
                                      borderRadius: BorderRadius.circular(6),
                                      border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.35)),
                                    ),
                                    child: const Text('DEFAULT', style: TextStyle(fontSize: 7.5, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0))),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                Icon(Icons.dns_rounded, size: 11, color: Colors.white.withOpacity(0.35)),
                                const SizedBox(width: 4),
                                Text('${chk.serverIp}:${chk.serverPort}', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                                const Spacer(),
                                if (chk.lastDeployed != null)
                                  Text('Deployed: ${chk.lastDeployed}', style: TextStyle(fontSize: 7.5, color: Colors.white.withOpacity(0.3))),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                OutlinedButton.icon(
                                  onPressed: () {
                                    setState(() => _selectedCheckpointId = chk.id);
                                    _triggerDeploy();
                                  },
                                  icon: const Icon(Icons.send_rounded, size: 11, color: Color(0xFF55E2C0)),
                                  label: const Text('Deploy', style: TextStyle(fontSize: 9, color: Color(0xFF55E2C0))),
                                  style: OutlinedButton.styleFrom(
                                    side: BorderSide(color: const Color(0xFF109C6D).withOpacity(0.3)),
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    visualDensity: VisualDensity.compact,
                                  ),
                                ),
                                const Spacer(),
                                IconButton(
                                  icon: const Icon(Icons.edit_rounded, size: 14),
                                  color: Colors.white60,
                                  tooltip: 'Edit Checkpoint',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () => widget.onEditCheckpoint(chk),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline_rounded, size: 14),
                                  color: Colors.white38,
                                  tooltip: 'Delete Checkpoint',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () => widget.onDeleteCheckpoint(chk.id),
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    }).toList(),
                  ),
                const SizedBox(height: 16),
                Divider(color: Colors.white.withOpacity(0.06), height: 1),
                const SizedBox(height: 14),

                // Deployment Controls Panel
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.02),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: Colors.white.withOpacity(0.05)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.hub_rounded, size: 16, color: Color(0xFF7F6CFF)),
                          const SizedBox(width: 8),
                          const Text(
                            'DEPLOY CHECKPOINT TO PINS',
                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.8),
                          ),
                          const Spacer(),
                          Text(
                            'Modify one pin or the whole fleet',
                            style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4)),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          // Target selector dropdown
                          SizedBox(
                            width: 240,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Target Pins', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                                const SizedBox(height: 4),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 10),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withOpacity(0.04),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(color: Colors.white.withOpacity(0.08)),
                                  ),
                                  child: DropdownButtonHideUnderline(
                                    child: DropdownButton<String>(
                                      value: _selectedTarget,
                                      isExpanded: true,
                                      dropdownColor: const Color(0xFF0F261F),
                                      style: const TextStyle(fontSize: 11, color: Colors.white),
                                      items: [
                                        const DropdownMenuItem(
                                          value: 'ALL',
                                          child: Row(
                                            children: [
                                              Icon(Icons.all_inclusive_rounded, size: 14, color: Color(0xFF55E2C0)),
                                              SizedBox(width: 6),
                                              Text('All Fleet Pins (Broadcast)'),
                                            ],
                                          ),
                                        ),
                                        ...widget.devices.map((d) => DropdownMenuItem(
                                          value: d.id,
                                          child: Row(
                                            children: [
                                              Icon(Icons.pin_drop_rounded, size: 14, color: Color(0xFF7F6CFF)),
                                              SizedBox(width: 6),
                                              Text('${d.id} (${d.network})'),
                                            ],
                                          ),
                                        )),
                                      ],
                                      onChanged: (val) {
                                        if (val != null) setState(() => _selectedTarget = val);
                                      },
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),

                          // Checkpoint selector dropdown
                          SizedBox(
                            width: 240,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Select Checkpoint', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                                const SizedBox(height: 4),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 10),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withOpacity(0.04),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(color: Colors.white.withOpacity(0.08)),
                                  ),
                                  child: DropdownButtonHideUnderline(
                                    child: DropdownButton<String>(
                                      value: _selectedCheckpointId,
                                      isExpanded: true,
                                      dropdownColor: const Color(0xFF0F261F),
                                      style: const TextStyle(fontSize: 11, color: Colors.white),
                                      items: widget.checkpoints.map((c) => DropdownMenuItem(
                                        value: c.id,
                                        child: Text('${c.name} (${c.ssid})'),
                                      )).toList(),
                                      onChanged: (val) {
                                        if (val != null) setState(() => _selectedCheckpointId = val);
                                      },
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),

                          // Delivery Method
                          SizedBox(
                            width: 210,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('Delivery Channel', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                                const SizedBox(height: 4),
                                Row(
                                  children: [
                                    _BatchChoiceChip(
                                      label: 'Wi-Fi OTA',
                                      selected: _deployMethod == 'wifi',
                                      onTap: () => setState(() => _deployMethod = 'wifi'),
                                    ),
                                    const SizedBox(width: 8),
                                    _BatchChoiceChip(
                                      label: 'USB Cable',
                                      selected: _deployMethod == 'usb',
                                      onTap: () {
                                        setState(() => _deployMethod = 'usb');
                                        _loadComPorts();
                                      },
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),

                          // USB COM Port selector (if USB mode)
                          if (_deployMethod == 'usb')
                            SizedBox(
                              width: 170,
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('USB COM Port', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                                  const SizedBox(height: 4),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8),
                                    decoration: BoxDecoration(
                                      color: Colors.white.withOpacity(0.04),
                                      borderRadius: BorderRadius.circular(8),
                                      border: Border.all(color: Colors.white.withOpacity(0.08)),
                                    ),
                                    child: DropdownButtonHideUnderline(
                                      child: DropdownButton<String>(
                                        value: _selectedComPort,
                                        isExpanded: true,
                                        dropdownColor: const Color(0xFF0F261F),
                                        style: const TextStyle(fontSize: 11, color: Colors.white),
                                        items: _comPorts.map((p) => DropdownMenuItem(
                                          value: p['port'] as String?,
                                          child: Text('${p['port']} (${p['description']})'),
                                        )).toList(),
                                        onChanged: (val) {
                                          if (val != null) setState(() => _selectedComPort = val);
                                        },
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),

                          // Big Deploy Button
                          Padding(
                            padding: const EdgeInsets.only(top: 14),
                            child: ElevatedButton.icon(
                              onPressed: _isDeploying ? null : _triggerDeploy,
                              icon: _isDeploying
                                  ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                  : const Icon(Icons.rocket_launch_rounded, size: 15),
                              label: Text(
                                _selectedTarget == 'ALL' ? 'Deploy Checkpoint to All Pins' : 'Deploy to $_selectedTarget',
                                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
                              ),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF109C6D),
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                                elevation: 3,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // =========================================================================
          // 2. HARDWARE BUFFER & TIMEOUT CONTROLS
          // =========================================================================
          Row(
            children: [
              Expanded(
                child: _ConfigCard(
                  title: 'PRE-TRIGGER AUDIO BUFFER DURATION',
                  subtitle: 'Seconds of audio held in continuous circular PSRAM buffer before speech arming',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('${widget.bufferDuration} Seconds Pre-roll', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0))),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(color: Colors.white.withOpacity(0.04), borderRadius: BorderRadius.circular(6)),
                            child: Text('${psramBytes ~/ 1024} KB in 8MB PSRAM', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          activeTrackColor: const Color(0xFF55E2C0),
                          thumbColor: const Color(0xFF55E2C0),
                          overlayColor: const Color(0xFF55E2C0).withOpacity(0.15),
                        ),
                        child: Slider(
                          value: widget.bufferDuration.toDouble(),
                          min: 2,
                          max: 8,
                          divisions: 6,
                          label: '${widget.bufferDuration} s',
                          onChanged: (val) => widget.onBufferChanged(val.round()),
                        ),
                      ),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('2s (Low Memory)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                          Text('4s (Balanced)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                          Text('8s (Max Context)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _ConfigCard(
                  title: 'SILENCE TIMEOUT (MODEM SLEEP)',
                  subtitle: 'Silence duration required before pin terminates Wi-Fi and sleeps',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('${widget.silenceTimeout} Seconds Window', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: Color(0xFF7F6CFF))),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(color: Colors.white.withOpacity(0.04), borderRadius: BorderRadius.circular(6)),
                            child: Text('Extends 200mAh Life', style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4))),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          activeTrackColor: const Color(0xFF7F6CFF),
                          thumbColor: const Color(0xFF7F6CFF),
                          overlayColor: const Color(0xFF7F6CFF).withOpacity(0.15),
                        ),
                        child: Slider(
                          value: widget.silenceTimeout.toDouble(),
                          min: 4,
                          max: 20,
                          divisions: 8,
                          label: '${widget.silenceTimeout} s',
                          onChanged: (val) => widget.onSilenceChanged(val.round()),
                        ),
                      ),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('4s (Aggressive Sleep)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                          Text('10s (Recommended)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                          Text('20s (Extended)', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.3))),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // =========================================================================
          // 3. CAMERA & WI-FI RF BATCHING
          // =========================================================================
          Row(
            children: [
              Expanded(
                child: _ConfigCard(
                  title: 'CAMERA EVIDENCE TRIGGER POLICY',
                  subtitle: 'Controls when the OV2640 camera wakes up on wearable pins',
                  child: Column(
                    children: [
                      SwitchListTile(
                        value: widget.autoDangerSnapshot,
                        onChanged: widget.onAutoSnapshotChanged,
                        activeColor: const Color(0xFFFF4D67),
                        title: const Text('Capture Snapshot on DANGER Only', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                        subtitle: Text(
                          'Keeps camera in standby during Normal, Warning, and Threat events. Essential to reach 6-8h on 200mAh battery.',
                          style: TextStyle(fontSize: 9, color: Colors.white.withOpacity(0.45)),
                        ),
                        contentPadding: EdgeInsets.zero,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _ConfigCard(
                  title: 'WI-FI RF PACKET BATCHING',
                  subtitle: 'Audio frame aggregation interval before Wi-Fi transmission',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          _BatchChoiceChip(
                            label: '50ms (20 pkts/s)',
                            selected: widget.wifiBatchMs == 50,
                            onTap: () => widget.onWifiBatchChanged(50),
                          ),
                          const SizedBox(width: 8),
                          _BatchChoiceChip(
                            label: '100ms (10 pkts/s)',
                            selected: widget.wifiBatchMs == 100,
                            onTap: () => widget.onWifiBatchChanged(100),
                          ),
                          const SizedBox(width: 8),
                          _BatchChoiceChip(
                            label: '200ms (5 pkts/s)',
                            selected: widget.wifiBatchMs == 200,
                            onTap: () => widget.onWifiBatchChanged(200),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '100ms cuts radio RF wakeups by 80% compared to unbatched 20ms streaming.',
                        style: TextStyle(fontSize: 8.5, color: Colors.white.withOpacity(0.4)),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // =========================================================================
          // 4. PIN WI-FI RESET & FLEET SAVE
          // =========================================================================
          _ConfigCard(
            title: 'PIN WI-FI RESET & PORTAL LAUNCH',
            subtitle: 'Remotely instruct smart pins to clear stored Wi-Fi and enter setup hotspot',
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Need to manually configure the pin via phone? Tap "Forget Wi-Fi" to clear stored credentials and switch the pin into its setup portal ("SecureLink-Setup") without pressing hardware buttons.',
                    style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.5)),
                  ),
                ),
                const SizedBox(width: 16),
                OutlinedButton.icon(
                  onPressed: widget.onForgetWifi,
                  icon: const Icon(Icons.wifi_password_rounded, size: 15, color: Color(0xFFFCA5A5)),
                  label: const Text('Forget Wi-Fi & Launch Portal', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600, color: Color(0xFFFCA5A5))),
                  style: OutlinedButton.styleFrom(
                    side: BorderSide(color: const Color(0xFFEF4444).withOpacity(0.4)),
                    backgroundColor: const Color(0xFFEF4444).withOpacity(0.12),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: 260,
            child: ElevatedButton.icon(
              onPressed: widget.onSave,
              icon: const Icon(Icons.cloud_upload_rounded, size: 16),
              label: const Text('Deploy Fleet Audio Policies', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF7F6CFF),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// Dialog to add or edit an authorized Wi-Fi checkpoint
class _CheckpointEditorDialog extends StatefulWidget {
  final WifiCheckpoint? existing;
  final ValueChanged<WifiCheckpoint> onSave;

  const _CheckpointEditorDialog({this.existing, required this.onSave});

  @override
  State<_CheckpointEditorDialog> createState() => _CheckpointEditorDialogState();
}

class _CheckpointEditorDialogState extends State<_CheckpointEditorDialog> {
  late final TextEditingController _nameController;
  late final TextEditingController _ssidController;
  late final TextEditingController _passController;
  late final TextEditingController _serverIpController;
  late final TextEditingController _serverPortController;
  bool _isDefault = false;
  bool _showPassword = false;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.existing?.name ?? 'Campus AP');
    _ssidController = TextEditingController(text: widget.existing?.ssid ?? '');
    _passController = TextEditingController(text: widget.existing?.pass ?? '');
    _serverIpController = TextEditingController(text: widget.existing?.serverIp ?? '10.28.20.4');
    _serverPortController = TextEditingController(text: '${widget.existing?.serverPort ?? 8080}');
    _isDefault = widget.existing?.isDefault ?? false;
    _fetchDefaultServerIp();
  }

  Future<void> _fetchDefaultServerIp() async {
    if (widget.existing != null) return;
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/api/network-info'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final srvIp = data['server_ip'] as String?;
        if (srvIp != null && srvIp.isNotEmpty && mounted) {
          setState(() => _serverIpController.text = srvIp);
        }
      }
    } catch (_) {}
  }

  @override
  void dispose() {
    _nameController.dispose();
    _ssidController.dispose();
    _passController.dispose();
    _serverIpController.dispose();
    _serverPortController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.existing != null;
    return AlertDialog(
      backgroundColor: const Color(0xFF0F261F),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: Color(0xFF1B4938)),
      ),
      title: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(7),
            decoration: BoxDecoration(
              color: const Color(0xFF109C6D).withOpacity(0.18),
              borderRadius: BorderRadius.circular(9),
            ),
            child: const Icon(Icons.wifi_tethering_rounded, size: 20, color: Color(0xFF55E2C0)),
          ),
          const SizedBox(width: 10),
          Text(
            isEdit ? 'Edit Authorized Checkpoint' : 'Add Authorized Wi-Fi Checkpoint',
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white),
          ),
        ],
      ),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Configure a campus Wi-Fi AP so wearable pins can auto-connect and stream audio seamlessly.',
                style: TextStyle(fontSize: 10.5, color: Colors.white.withOpacity(0.55)),
              ),
              const SizedBox(height: 14),
              _buildField('Checkpoint Label / Location', _nameController, hint: 'e.g. Main Admin, Library, Gate AP'),
              const SizedBox(height: 10),
              _buildField('Wi-Fi SSID (Network Name)', _ssidController, hint: 'e.g. SLTYMTBLLS, Campus-Wi-Fi'),
              const SizedBox(height: 10),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Wi-Fi Password', style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600, color: Colors.white.withOpacity(0.5))),
                  const SizedBox(height: 4),
                  Container(
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.04),
                      borderRadius: BorderRadius.circular(9),
                      border: Border.all(color: Colors.white.withOpacity(0.08)),
                    ),
                    child: TextField(
                      controller: _passController,
                      obscureText: !_showPassword,
                      style: const TextStyle(fontSize: 12, color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'Leave empty if open network',
                        hintStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.25)),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                        suffixIcon: IconButton(
                          icon: Icon(_showPassword ? Icons.visibility_off_rounded : Icons.visibility_rounded, size: 16, color: Colors.white38),
                          onPressed: () => setState(() => _showPassword = !_showPassword),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    flex: 3,
                    child: _buildField('Server IP (This Laptop / Host)', _serverIpController, hint: 'e.g. 10.28.20.4'),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    flex: 1,
                    child: _buildField('Port', _serverPortController, hint: '8080'),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              SwitchListTile(
                value: _isDefault,
                onChanged: (v) => setState(() => _isDefault = v),
                activeColor: const Color(0xFF109C6D),
                contentPadding: EdgeInsets.zero,
                title: const Text('Set as Default Checkpoint', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
                subtitle: Text('New pins and boot reconnects will prioritize this AP.', style: TextStyle(fontSize: 9, color: Colors.white.withOpacity(0.4))),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text('Cancel', style: TextStyle(color: Colors.white.withOpacity(0.5))),
        ),
        ElevatedButton(
          onPressed: () {
            final ssid = _ssidController.text.trim();
            if (ssid.isEmpty) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Wi-Fi SSID is required.'), backgroundColor: Colors.red),
              );
              return;
            }
            final chk = WifiCheckpoint(
              id: widget.existing?.id ?? 'chk_${DateTime.now().millisecondsSinceEpoch}',
              name: _nameController.text.trim().isEmpty ? ssid : _nameController.text.trim(),
              ssid: ssid,
              pass: _passController.text.trim(),
              serverIp: _serverIpController.text.trim().isEmpty ? '10.28.20.4' : _serverIpController.text.trim(),
              serverPort: int.tryParse(_serverPortController.text.trim()) ?? 8080,
              isDefault: _isDefault,
              lastDeployed: widget.existing?.lastDeployed,
            );
            widget.onSave(chk);
            Navigator.pop(context);
          },
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF109C6D),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          ),
          child: Text(isEdit ? 'Update Checkpoint' : 'Save Checkpoint'),
        ),
      ],
    );
  }

  Widget _buildField(String label, TextEditingController controller, {String? hint}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w600, color: Colors.white.withOpacity(0.5))),
        const SizedBox(height: 4),
        Container(
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.04),
            borderRadius: BorderRadius.circular(9),
            border: Border.all(color: Colors.white.withOpacity(0.08)),
          ),
          child: TextField(
            controller: controller,
            style: const TextStyle(fontSize: 12, color: Colors.white),
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.25)),
              border: InputBorder.none,
              contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
          ),
        ),
      ],
    );
  }
}

// Dialog to assign a checkpoint to an individual pin
class _AssignPinCheckpointDialog extends StatefulWidget {
  final DeviceStatus device;
  final List<WifiCheckpoint> checkpoints;
  final Function({
    required WifiCheckpoint checkpoint,
    required String method,
    String? comPort,
  }) onDeploy;
  final VoidCallback onAddNew;

  const _AssignPinCheckpointDialog({
    required this.device,
    required this.checkpoints,
    required this.onDeploy,
    required this.onAddNew,
  });

  @override
  State<_AssignPinCheckpointDialog> createState() => _AssignPinCheckpointDialogState();
}

class _AssignPinCheckpointDialogState extends State<_AssignPinCheckpointDialog> {
  String? _selectedCheckpointId;
  String _method = 'wifi';
  String? _selectedComPort;
  List<Map<String, dynamic>> _comPorts = [];
  bool _isDeploying = false;

  @override
  void initState() {
    super.initState();
    if (widget.checkpoints.isNotEmpty) {
      final match = widget.checkpoints.firstWhere((c) => c.ssid == widget.device.network, orElse: () => widget.checkpoints.first);
      _selectedCheckpointId = match.id;
    }
    _loadComPorts();
  }

  Future<void> _loadComPorts() async {
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/api/network-info'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final rawPorts = (data['serial_ports'] as List? ?? []);
        final portList = rawPorts.map((p) => Map<String, dynamic>.from(p as Map)).toList();
        if (mounted) {
          setState(() {
            _comPorts = portList;
            if (portList.isNotEmpty && _selectedComPort == null) {
              final espPort = portList.firstWhere((p) => p['is_esp'] == true, orElse: () => portList.first);
              _selectedComPort = espPort['port'] as String?;
            }
          });
        }
      }
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF0F261F),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: Color(0xFF1B4938)),
      ),
      title: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(7),
            decoration: BoxDecoration(
              color: const Color(0xFF109C6D).withOpacity(0.18),
              borderRadius: BorderRadius.circular(9),
            ),
            child: const Icon(Icons.wifi_password_rounded, size: 20, color: Color(0xFF55E2C0)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Assign Wi-Fi to ${widget.device.id}',
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white),
                ),
                Text(
                  'Current AP: ${widget.device.network} • ${widget.device.state}',
                  style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.5)),
                ),
              ],
            ),
          ),
        ],
      ),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Select an authorized campus checkpoint to push directly to this pin over-the-air or via USB cable:',
              style: TextStyle(fontSize: 10.5, color: Colors.white.withOpacity(0.65), height: 1.3),
            ),
            const SizedBox(height: 12),
            if (widget.checkpoints.isEmpty)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text('No checkpoints available. Add one in Configuration.', style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 11)),
              )
            else
              Container(
                constraints: const BoxConstraints(maxHeight: 180),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.02),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white.withOpacity(0.05)),
                ),
                child: ListView.separated(
                  shrinkWrap: true,
                  padding: const EdgeInsets.all(6),
                  itemCount: widget.checkpoints.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 4),
                  itemBuilder: (ctx, idx) {
                    final chk = widget.checkpoints[idx];
                    final isSel = chk.id == _selectedCheckpointId;
                    return InkWell(
                      onTap: () => setState(() => _selectedCheckpointId = chk.id),
                      borderRadius: BorderRadius.circular(8),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                        decoration: BoxDecoration(
                          color: isSel ? const Color(0xFF109C6D).withOpacity(0.18) : Colors.transparent,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: isSel ? const Color(0xFF109C6D).withOpacity(0.4) : Colors.transparent),
                        ),
                        child: Row(
                          children: [
                            Icon(isSel ? Icons.radio_button_checked : Icons.radio_button_off, size: 15, color: isSel ? const Color(0xFF55E2C0) : Colors.white30),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(chk.name, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                                  Text('SSID: ${chk.ssid}', style: TextStyle(fontSize: 9, color: Colors.white.withOpacity(0.45))),
                                ],
                              ),
                            ),
                            if (chk.isDefault)
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
                                decoration: BoxDecoration(color: const Color(0xFF109C6D).withOpacity(0.2), borderRadius: BorderRadius.circular(4)),
                                child: const Text('DEFAULT', style: TextStyle(fontSize: 7.5, color: Color(0xFF55E2C0), fontWeight: FontWeight.w700)),
                              ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
            const SizedBox(height: 12),
            Row(
              children: [
                _BatchChoiceChip(
                  label: 'Wi-Fi OTA (Live)',
                  selected: _method == 'wifi',
                  onTap: () => setState(() => _method = 'wifi'),
                ),
                const SizedBox(width: 8),
                _BatchChoiceChip(
                  label: 'USB Cable (Serial)',
                  selected: _method == 'usb',
                  onTap: () {
                    setState(() => _method = 'usb');
                    _loadComPorts();
                  },
                ),
                const Spacer(),
                TextButton.icon(
                  onPressed: () {
                    Navigator.pop(context);
                    widget.onAddNew();
                  },
                  icon: const Icon(Icons.add_rounded, size: 13),
                  label: const Text('+ New AP', style: TextStyle(fontSize: 10)),
                  style: TextButton.styleFrom(foregroundColor: const Color(0xFF55E2C0)),
                ),
              ],
            ),
            if (_method == 'usb') ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.04),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.white.withOpacity(0.08)),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: _selectedComPort,
                    isExpanded: true,
                    dropdownColor: const Color(0xFF0F261F),
                    style: const TextStyle(fontSize: 11, color: Colors.white),
                    items: _comPorts.map((p) => DropdownMenuItem(
                      value: p['port'] as String?,
                      child: Text('${p['port']} (${p['description']})'),
                    )).toList(),
                    onChanged: (val) {
                      if (val != null) setState(() => _selectedComPort = val);
                    },
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text('Cancel', style: TextStyle(color: Colors.white.withOpacity(0.5))),
        ),
        ElevatedButton(
          onPressed: _isDeploying || widget.checkpoints.isEmpty ? null : () async {
            final chk = widget.checkpoints.firstWhere(
              (c) => c.id == _selectedCheckpointId,
              orElse: () => widget.checkpoints.first,
            );
            setState(() => _isDeploying = true);
            await widget.onDeploy(
              checkpoint: chk,
              method: _method,
              comPort: _selectedComPort,
            );
            if (mounted) Navigator.pop(context);
          },
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF109C6D),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          ),
          child: _isDeploying
              ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : Text('Deploy to ${widget.device.id}'),
        ),
      ],
    );
  }
}

class _ConfigCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final Widget child;

  const _ConfigCard({required this.title, required this.subtitle, required this.child});

  @override
  Widget build(BuildContext context) {
    return _Glass(
      radius: 18,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w700, color: Colors.white.withOpacity(0.35), letterSpacing: 0.9)),
          const SizedBox(height: 2),
          Text(subtitle, style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.55))),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}

class _BatchChoiceChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _BatchChoiceChip({required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFF7F6CFF).withOpacity(0.18) : Colors.white.withOpacity(0.025),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: selected ? const Color(0xFF7F6CFF) : Colors.white.withOpacity(0.05)),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 9,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
            color: selected ? const Color(0xFF7F6CFF) : Colors.white60,
          ),
        ),
      ),
    );
  }
}

class _AnalyticsPage extends StatelessWidget {
  final List<Incident> incidents;
  const _AnalyticsPage({required this.incidents});

  @override
  Widget build(BuildContext context) {
    final total = incidents.length;
    final danger = incidents.where((i) => i.level == IncidentLevel.danger).length;
    final threat = incidents.where((i) => i.level == IncidentLevel.threat).length;
    final warning = incidents.where((i) => i.level == IncidentLevel.warning).length;
    final normal = incidents.where((i) => i.level == IncidentLevel.normal).length;

    return SingleChildScrollView(
      child: Column(
        children: [
          Row(children: [
            Expanded(child: _MetricCard(label: 'TOTAL EVENTS', value: '$total', caption: 'active session', icon: Icons.receipt_long_rounded, color: const Color(0xFF8F7CFF))),
            const SizedBox(width: 10),
            Expanded(child: _MetricCard(label: 'THREATS', value: '$threat', caption: 'elevated severity', icon: Icons.gpp_maybe_outlined, color: const Color(0xFFFF914D))),
            const SizedBox(width: 10),
            Expanded(child: _MetricCard(label: 'DANGER', value: '$danger', caption: 'highest severity', icon: Icons.emergency_rounded, color: const Color(0xFFFF4D67))),
          ]),
          const SizedBox(height: 12),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 6,
              child: _Glass(
                radius: 20,
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Tagalog NLP Severity Distribution', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
                    const SizedBox(height: 4),
                    Text('Categorized by fine-tuned jcblaise/roberta-tagalog-base model', style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.35))),
                    const SizedBox(height: 16),
                    _BarMetric(label: 'Normal', value: normal, total: total, color: IncidentLevel.normal.color),
                    _BarMetric(label: 'Warning', value: warning, total: total, color: IncidentLevel.warning.color),
                    _BarMetric(label: 'Threat', value: threat, total: total, color: IncidentLevel.threat.color),
                    _BarMetric(label: 'Danger', value: danger, total: total, color: IncidentLevel.danger.color),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 12),
            const Expanded(
              flex: 5,
              child: _Glass(
                radius: 20,
                padding: EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('System Architecture Diagnostics', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
                    SizedBox(height: 4),
                    Text('XIAO ESP32S3 + Server Infrastructure', style: TextStyle(fontSize: 9.5, color: Colors.white30)),
                    SizedBox(height: 16),
                    _ResearchMetric(label: 'Edge MCU', value: 'XIAO ESP32S3 Sense (Dual-Core LX7)'),
                    _ResearchMetric(label: 'Clock Speed', value: '80 MHz Eco (Underclocked)'),
                    _ResearchMetric(label: 'Battery', value: '3.7V 200mAh LiPo (~7h Runtime)'),
                    _ResearchMetric(label: 'Microphone', value: 'MSM261D3526H1CPM PDM (16kHz)'),
                    _ResearchMetric(label: 'Pre-roll Buffer', value: '8MB PSRAM (Configurable circular)'),
                    _ResearchMetric(label: 'Speech-to-Text', value: 'Faster-Whisper (Tagalog Conditioned)'),
                    _ResearchMetric(label: 'NLP Classifier', value: 'RoBERTa Tagalog Base (4 Classes)'),
                  ],
                ),
              ),
            ),
          ]),
        ],
      ),
    );
  }
}

class _BarMetric extends StatelessWidget {
  final String label;
  final int value;
  final int total;
  final Color color;
  const _BarMetric({required this.label, required this.value, required this.total, required this.color});

  @override
  Widget build(BuildContext context) {
    final ratio = total == 0 ? 0.0 : value / total;
    return Padding(padding: const EdgeInsets.only(bottom: 12), child: Row(children: [SizedBox(width: 65, child: Text(label, style: TextStyle(color: Colors.white.withOpacity(.48), fontSize: 9.5))), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(6), child: LinearProgressIndicator(minHeight: 6, value: ratio, backgroundColor: Colors.white.withOpacity(.04), valueColor: AlwaysStoppedAnimation<Color>(color)))), SizedBox(width: 30, child: Align(alignment: Alignment.centerRight, child: Text('$value', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 9.5))))]));
  }
}

class _ResearchMetric extends StatelessWidget {
  final String label, value;
  const _ResearchMetric({required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.symmetric(vertical: 5), child: Row(children: [SizedBox(width: 90, child: Text(label.toUpperCase(), style: TextStyle(color: Colors.white.withOpacity(.30), fontSize: 7.5, fontWeight: FontWeight.w600, letterSpacing: .6))), Expanded(child: Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w500)))]));
}

class _SectionHeader extends StatelessWidget {
  final String title, action;
  const _SectionHeader({required this.title, required this.action});

  @override
  Widget build(BuildContext context) => Row(children: [Expanded(child: Text(title, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700))), Text(action, style: const TextStyle(color: Color(0xFF8F7CFF), fontSize: 8.5, fontWeight: FontWeight.w600))]);
}

class _LevelBadge extends StatelessWidget {
  final IncidentLevel level;
  const _LevelBadge({required this.level});

  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5), decoration: BoxDecoration(color: level.color.withOpacity(.10), borderRadius: BorderRadius.circular(8), border: Border.all(color: level.color.withOpacity(.14))), child: Text(level.label, style: TextStyle(color: level.color, fontSize: 7.5, fontWeight: FontWeight.w700, letterSpacing: .7)));
}

class _PairPinHeaderButton extends StatelessWidget {
  final bool hasPins;
  final VoidCallback onTap;

  const _PairPinHeaderButton({required this.hasPins, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(11),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          color: hasPins
              ? const Color(0xFF109C6D).withOpacity(0.14)
              : const Color(0xFF7F6CFF).withOpacity(0.14),
          borderRadius: BorderRadius.circular(11),
          border: Border.all(
            color: hasPins
                ? const Color(0xFF109C6D).withOpacity(0.40)
                : const Color(0xFF7F6CFF).withOpacity(0.35),
            width: 1.0,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              hasPins ? Icons.sensors_rounded : Icons.sensors_off_rounded,
              size: 13,
              color: hasPins ? const Color(0xFF55E2C0) : const Color(0xFF9B88FF),
            ),
            const SizedBox(width: 6),
            Text(
              hasPins ? 'SMART PIN LINKED' : 'PAIR SMART PIN',
              style: TextStyle(
                fontSize: 8.5,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.7,
                color: hasPins ? const Color(0xFF55E2C0) : const Color(0xFF9B88FF),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PinSetupDialog extends StatefulWidget {
  final List<DeviceStatus> liveDevices;
  final bool isServerConnected;

  const _PinSetupDialog({
    required this.liveDevices,
    required this.isServerConnected,
  });

  @override
  State<_PinSetupDialog> createState() => _PinSetupDialogState();
}

class _PinSetupDialogState extends State<_PinSetupDialog> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final TextEditingController _ssidController = TextEditingController(text: 'SLTYMTBLLS');
  final TextEditingController _passController = TextEditingController(text: '9945SUmaxx!');
  final TextEditingController _serverIpController = TextEditingController(text: '127.0.0.1');
  final TextEditingController _serverPortController = TextEditingController(text: '8080');

  bool _obscurePass = true;
  bool _isLoadingNetwork = true;
  bool _isProvisioning = false;
  String? _selectedPort;
  List<Map<String, dynamic>> _serialPorts = [];
  String? _statusMessage;
  bool _statusSuccess = false;
  List<String> _consoleLogs = [];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _loadNetworkAndPorts();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _ssidController.dispose();
    _passController.dispose();
    _serverIpController.dispose();
    _serverPortController.dispose();
    super.dispose();
  }

  Future<void> _loadNetworkAndPorts() async {
    setState(() {
      _isLoadingNetwork = true;
      _statusMessage = null;
    });

    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 3);
      final req = await client.getUrl(Uri.parse('http://127.0.0.1:8080/api/network-info'));
      final resp = await req.close();
      if (resp.statusCode == 200) {
        final body = await resp.transform(utf8.decoder).join();
        final data = jsonDecode(body) as Map<String, dynamic>;
        final serverIp = data['server_ip'] as String? ?? '127.0.0.1';
        final rawPorts = (data['serial_ports'] as List? ?? []);
        final portList = rawPorts.map((p) => Map<String, dynamic>.from(p as Map)).toList();

        if (mounted) {
          setState(() {
            _serverIpController.text = serverIp;
            _serialPorts = portList;
            _isLoadingNetwork = false;

            if (portList.isNotEmpty) {
              final espPort = portList.firstWhere(
                (p) => p['is_esp'] == true,
                orElse: () => portList.first,
              );
              _selectedPort = espPort['port'] as String?;
            } else {
              _selectedPort = null;
            }
          });
        }
      } else {
        if (mounted) setState(() => _isLoadingNetwork = false);
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoadingNetwork = false;
          _statusMessage = 'Could not fetch station network info: $e';
          _statusSuccess = false;
        });
      }
    }
  }

  Future<void> _flashWifiToPin() async {
    if (_selectedPort == null) {
      setState(() {
        _statusMessage = 'Please select a USB COM port (plug ESP32 pin into laptop).';
        _statusSuccess = false;
      });
      return;
    }
    if (_ssidController.text.trim().isEmpty) {
      setState(() {
        _statusMessage = 'Wi-Fi SSID cannot be empty.';
        _statusSuccess = false;
      });
      return;
    }

    setState(() {
      _isProvisioning = true;
      _statusMessage = 'Flashing credentials to $_selectedPort...';
      _statusSuccess = false;
      _consoleLogs.clear();
    });

    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 5);
      final req = await client.postUrl(Uri.parse('http://127.0.0.1:8080/api/provision-pin'));
      req.headers.contentType = ContentType.json;
      req.write(jsonEncode({
        'port': _selectedPort,
        'ssid': _ssidController.text.trim(),
        'pass': _passController.text.trim(),
        'server_ip': _serverIpController.text.trim(),
        'server_port': int.tryParse(_serverPortController.text.trim()) ?? 8080,
      }));
      final resp = await req.close();
      final body = await resp.transform(utf8.decoder).join();
      final data = jsonDecode(body) as Map<String, dynamic>;

      if (mounted) {
        final success = data['status'] == 'success';
        final rawLogs = (data['logs'] as List? ?? []);
        final logs = rawLogs.map((e) => e.toString()).toList();
        setState(() {
          _isProvisioning = false;
          _statusSuccess = success;
          _statusMessage = data['message'] as String? ?? (success ? 'Configuration Flashed!' : 'Failed');
          _consoleLogs = logs;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isProvisioning = false;
          _statusSuccess = false;
          _statusMessage = 'Error connecting to provisioning API: $e';
        });
      }
    }
  }

  void _openPortalInBrowser() {
    try {
      Process.run('cmd', ['/c', 'start', 'http://192.168.4.1']);
    } catch (e) {
      debugPrint('Launch browser error: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasConnectedPin = widget.liveDevices.any((d) => d.online);
    final activePin = hasConnectedPin ? widget.liveDevices.firstWhere((d) => d.online) : null;

    return Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
      child: Container(
        width: 580,
        constraints: const BoxConstraints(maxHeight: 680),
        decoration: BoxDecoration(
          color: const Color(0xFF0C121A),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.35), width: 1.2),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.65),
              blurRadius: 36,
              spreadRadius: 4,
            ),
            BoxShadow(
              color: const Color(0xFF109C6D).withOpacity(0.12),
              blurRadius: 28,
              spreadRadius: 1,
            ),
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(22),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // HEADER
              Container(
                padding: const EdgeInsets.fromLTRB(20, 18, 16, 16),
                decoration: BoxDecoration(
                  color: const Color(0xFF111A24),
                  border: Border(bottom: BorderSide(color: Colors.white.withOpacity(0.06))),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 40,
                      height: 40,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(12),
                        gradient: const LinearGradient(
                          colors: [Color(0xFF109C6D), Color(0xFF042F2E)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        border: Border.all(color: const Color(0xFF55E2C0).withOpacity(0.4)),
                      ),
                      child: const Icon(Icons.developer_board_rounded, color: Color(0xFF55E2C0), size: 22),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'SMART PIN PAIRING & PROVISIONING',
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.9,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Connect your XIAO ESP32S3 wearable pin to Wi-Fi and pair with Checkpoint',
                            style: TextStyle(
                              fontSize: 10,
                              color: Colors.white.withOpacity(0.55),
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded, size: 20, color: Colors.white54),
                      tooltip: 'Close',
                    ),
                  ],
                ),
              ),

              // TAB SELECTOR
              Container(
                color: const Color(0xFF0E1620),
                child: TabBar(
                  controller: _tabController,
                  indicatorColor: const Color(0xFF55E2C0),
                  indicatorWeight: 2.5,
                  labelColor: const Color(0xFF55E2C0),
                  unselectedLabelColor: Colors.white.withOpacity(0.45),
                  labelStyle: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700),
                  unselectedLabelStyle: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w500),
                  tabs: const [
                    Tab(
                      icon: Icon(Icons.usb_rounded, size: 16),
                      text: '⚡ USB One-Click Setup (Recommended)',
                    ),
                    Tab(
                      icon: Icon(Icons.wifi_tethering_rounded, size: 16),
                      text: '📶 Wi-Fi Hotspot Setup',
                    ),
                  ],
                ),
              ),

              // TAB CONTENT
              Expanded(
                child: TabBarView(
                  controller: _tabController,
                  children: [
                    // --- TAB 1: USB PROVISIONING ---
                    SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // COM PORT SELECTOR
                          Text(
                            'DETECTED USB SERIAL PORT',
                            style: TextStyle(
                              fontSize: 8.5,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.8,
                              color: Colors.white.withOpacity(0.4),
                            ),
                          ),
                          const SizedBox(height: 6),
                          if (_isLoadingNetwork)
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: Colors.white.withOpacity(0.03),
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(color: Colors.white.withOpacity(0.06)),
                              ),
                              child: const Row(
                                children: [
                                  SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                                  SizedBox(width: 10),
                                  Text('Scanning available USB ports...', style: TextStyle(fontSize: 11, color: Colors.white60)),
                                ],
                              ),
                            )
                          else if (_serialPorts.isEmpty)
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: const Color(0xFFB45309).withOpacity(0.12),
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(color: const Color(0xFFF59E0B).withOpacity(0.3)),
                              ),
                              child: Row(
                                children: [
                                  const Icon(Icons.usb_off_rounded, color: Color(0xFFF59E0B), size: 20),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        const Text('No USB COM port detected', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Color(0xFFFDE68A))),
                                        const SizedBox(height: 2),
                                        Text('Plug your ESP32 pin into your laptop using a USB data cable (charge-only cables will not show up).', style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.6))),
                                      ],
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  TextButton.icon(
                                    onPressed: _loadNetworkAndPorts,
                                    icon: const Icon(Icons.refresh_rounded, size: 14),
                                    label: const Text('Rescan', style: TextStyle(fontSize: 10.5)),
                                    style: TextButton.styleFrom(
                                      foregroundColor: const Color(0xFF55E2C0),
                                    ),
                                  ),
                                ],
                              ),
                            )
                          else
                            Row(
                              children: [
                                Expanded(
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 12),
                                    decoration: BoxDecoration(
                                      color: const Color(0xFF141E2B),
                                      borderRadius: BorderRadius.circular(10),
                                      border: Border.all(color: const Color(0xFF55E2C0).withOpacity(0.35)),
                                    ),
                                    child: DropdownButtonHideUnderline(
                                      child: DropdownButton<String>(
                                        value: _selectedPort,
                                        isExpanded: true,
                                        dropdownColor: const Color(0xFF141E2B),
                                        items: _serialPorts.map((p) {
                                          final port = p['port'] as String;
                                          final desc = p['description'] as String? ?? '';
                                          final isEsp = p['is_esp'] == true;
                                          return DropdownMenuItem<String>(
                                            value: port,
                                            child: Row(
                                              children: [
                                                Icon(
                                                  Icons.usb_rounded,
                                                  size: 15,
                                                  color: isEsp ? const Color(0xFF55E2C0) : Colors.white54,
                                                ),
                                                const SizedBox(width: 8),
                                                Text(
                                                  '$port - $desc',
                                                  style: TextStyle(
                                                    fontSize: 11,
                                                    fontWeight: isEsp ? FontWeight.w700 : FontWeight.w500,
                                                    color: isEsp ? const Color(0xFF55E2C0) : Colors.white,
                                                  ),
                                                ),
                                                if (isEsp) ...[
                                                  const SizedBox(width: 8),
                                                  Container(
                                                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                                                    decoration: BoxDecoration(
                                                      color: const Color(0xFF109C6D).withOpacity(0.25),
                                                      borderRadius: BorderRadius.circular(4),
                                                    ),
                                                    child: const Text('ESP32 DETECTED', style: TextStyle(fontSize: 8, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0))),
                                                  ),
                                                ],
                                              ],
                                            ),
                                          );
                                        }).toList(),
                                        onChanged: (val) => setState(() => _selectedPort = val),
                                      ),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                IconButton(
                                  onPressed: _loadNetworkAndPorts,
                                  icon: const Icon(Icons.refresh_rounded, size: 18, color: Color(0xFF55E2C0)),
                                  tooltip: 'Rescan ports',
                                ),
                              ],
                            ),

                          const SizedBox(height: 16),

                          // WI-FI CREDENTIALS
                          Text(
                            'WI-FI CREDENTIALS (2.4GHz)',
                            style: TextStyle(
                              fontSize: 8.5,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.8,
                              color: Colors.white.withOpacity(0.4),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Container(
                            decoration: BoxDecoration(
                              color: const Color(0xFF141E2B),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: Colors.white.withOpacity(0.08)),
                            ),
                            child: TextField(
                              controller: _ssidController,
                              style: const TextStyle(fontSize: 12, color: Colors.white),
                              decoration: InputDecoration(
                                prefixIcon: const Icon(Icons.wifi_rounded, size: 16, color: Color(0xFF55E2C0)),
                                hintText: 'Enter 2.4GHz Wi-Fi SSID / Network Name',
                                hintStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.3)),
                                border: InputBorder.none,
                                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                              ),
                            ),
                          ),
                          const SizedBox(height: 10),
                          Container(
                            decoration: BoxDecoration(
                              color: const Color(0xFF141E2B),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: Colors.white.withOpacity(0.08)),
                            ),
                            child: TextField(
                              controller: _passController,
                              obscureText: _obscurePass,
                              style: const TextStyle(fontSize: 12, color: Colors.white),
                              decoration: InputDecoration(
                                prefixIcon: const Icon(Icons.lock_outline_rounded, size: 16, color: Color(0xFF55E2C0)),
                                suffixIcon: IconButton(
                                  icon: Icon(
                                    _obscurePass ? Icons.visibility_off_rounded : Icons.visibility_rounded,
                                    size: 16,
                                    color: Colors.white38,
                                  ),
                                  onPressed: () => setState(() => _obscurePass = !_obscurePass),
                                ),
                                hintText: 'Enter Wi-Fi Password',
                                hintStyle: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.3)),
                                border: InputBorder.none,
                                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                              ),
                            ),
                          ),

                          const SizedBox(height: 14),

                          // STATION SERVER CONFIGURATION
                          Row(
                            children: [
                              Expanded(
                                flex: 3,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'LAPTOP / CHECKPOINT SERVER IP',
                                      style: TextStyle(
                                        fontSize: 8.5,
                                        fontWeight: FontWeight.w700,
                                        letterSpacing: 0.8,
                                        color: Colors.white.withOpacity(0.4),
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Container(
                                      decoration: BoxDecoration(
                                        color: const Color(0xFF141E2B),
                                        borderRadius: BorderRadius.circular(10),
                                        border: Border.all(color: Colors.white.withOpacity(0.08)),
                                      ),
                                      child: TextField(
                                        controller: _serverIpController,
                                        style: const TextStyle(fontSize: 12, color: Colors.white),
                                        decoration: InputDecoration(
                                          prefixIcon: const Icon(Icons.lan_rounded, size: 16, color: Color(0xFF55E2C0)),
                                          border: InputBorder.none,
                                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                flex: 1,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'PORT',
                                      style: TextStyle(
                                        fontSize: 8.5,
                                        fontWeight: FontWeight.w700,
                                        letterSpacing: 0.8,
                                        color: Colors.white.withOpacity(0.4),
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Container(
                                      decoration: BoxDecoration(
                                        color: const Color(0xFF141E2B),
                                        borderRadius: BorderRadius.circular(10),
                                        border: Border.all(color: Colors.white.withOpacity(0.08)),
                                      ),
                                      child: TextField(
                                        controller: _serverPortController,
                                        style: const TextStyle(fontSize: 12, color: Colors.white),
                                        decoration: const InputDecoration(
                                          border: InputBorder.none,
                                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),

                          const SizedBox(height: 18),

                          // FLASH BUTTON
                          SizedBox(
                            width: double.infinity,
                            height: 44,
                            child: ElevatedButton.icon(
                              onPressed: _isProvisioning ? null : _flashWifiToPin,
                              icon: _isProvisioning
                                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                  : const Icon(Icons.bolt_rounded, size: 18),
                              label: Text(
                                _isProvisioning ? 'FLASHING CREDENTIALS TO PIN...' : '⚡ FLASH WI-FI CREDENTIALS TO PIN',
                                style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.8),
                              ),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF109C6D),
                                foregroundColor: Colors.white,
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                elevation: 3,
                              ),
                            ),
                          ),

                          // STATUS FEEDBACK
                          if (_statusMessage != null) ...[
                            const SizedBox(height: 12),
                            Container(
                              padding: const EdgeInsets.all(10),
                              decoration: BoxDecoration(
                                color: (_statusSuccess ? const Color(0xFF109C6D) : const Color(0xFFEF4444)).withOpacity(0.12),
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(
                                  color: (_statusSuccess ? const Color(0xFF109C6D) : const Color(0xFFEF4444)).withOpacity(0.4),
                                ),
                              ),
                              child: Row(
                                children: [
                                  Icon(
                                    _statusSuccess ? Icons.check_circle_rounded : Icons.error_outline_rounded,
                                    size: 16,
                                    color: _statusSuccess ? const Color(0xFF55E2C0) : const Color(0xFFF87171),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      _statusMessage!,
                                      style: TextStyle(
                                        fontSize: 11,
                                        color: _statusSuccess ? const Color(0xFF55E2C0) : const Color(0xFFFCA5A5),
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],

                          if (_consoleLogs.isNotEmpty) ...[
                            const SizedBox(height: 10),
                            Container(
                              width: double.infinity,
                              padding: const EdgeInsets.all(10),
                              decoration: BoxDecoration(
                                color: Colors.black.withOpacity(0.4),
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: Colors.white.withOpacity(0.06)),
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('SERIAL LOGS:', style: TextStyle(fontSize: 8, color: Colors.white.withOpacity(0.4), fontWeight: FontWeight.w700)),
                                  const SizedBox(height: 4),
                                  ..._consoleLogs.map((log) => Text(log, style: const TextStyle(fontSize: 9.5, color: Color(0xFF4ADE80), fontFamily: 'monospace'))),
                                ],
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),

                    // --- TAB 2: WI-FI HOTSPOT PROVISIONING ---
                    SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: const Color(0xFF141E2B),
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(color: Colors.white.withOpacity(0.06)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Container(
                                      padding: const EdgeInsets.all(6),
                                      decoration: BoxDecoration(
                                        color: const Color(0xFF55E2C0).withOpacity(0.12),
                                        borderRadius: BorderRadius.circular(8),
                                      ),
                                      child: const Icon(Icons.wifi_tethering_rounded, size: 18, color: Color(0xFF55E2C0)),
                                    ),
                                    const SizedBox(width: 10),
                                    const Expanded(
                                      child: Text(
                                        'Wireless Captive Portal Setup',
                                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Colors.white),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 12),
                                _SetupStep(
                                  number: '1',
                                  title: 'Power on the Pin',
                                  desc: 'Plug the XIAO ESP32S3 into any USB wall charger, battery bank, or laptop.',
                                ),
                                _SetupStep(
                                  number: '2',
                                  title: 'Check for "SecureLink-Setup" Wi-Fi',
                                  desc: 'The pin automatically broadcasts an open Wi-Fi network named "SecureLink-Setup". (If not visible, hold the tiny BOOT button on the pin for 2 seconds).',
                                ),
                                _SetupStep(
                                  number: '3',
                                  title: 'Connect your Phone or Laptop',
                                  desc: 'Join the "SecureLink-Setup" Wi-Fi network (no password required).',
                                ),
                                _SetupStep(
                                  number: '4',
                                  title: 'Open the Setup Portal in Browser',
                                  desc: 'Navigate to http://192.168.4.1 to select your local Wi-Fi and input this station\'s server host IP.',
                                ),
                              ],
                            ),
                          ),

                          const SizedBox(height: 14),

                          // HELPER BOX FOR SERVER IP
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xFF0F261F),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.4)),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.info_outline_rounded, color: Color(0xFF55E2C0), size: 18),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      const Text('YOUR STATION SERVER IP:', style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0), letterSpacing: 0.7)),
                                      const SizedBox(height: 2),
                                      Text('${_serverIpController.text}:8080', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Colors.white, fontFamily: 'monospace')),
                                    ],
                                  ),
                                ),
                                ElevatedButton.icon(
                                  onPressed: () {
                                    Clipboard.setData(ClipboardData(text: _serverIpController.text));
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(content: Text('Server IP copied to clipboard!'), duration: Duration(seconds: 2)),
                                    );
                                  },
                                  icon: const Icon(Icons.copy_rounded, size: 13),
                                  label: const Text('Copy IP', style: TextStyle(fontSize: 10)),
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: const Color(0xFF109C6D),
                                    foregroundColor: Colors.white,
                                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                                  ),
                                ),
                              ],
                            ),
                          ),

                          const SizedBox(height: 14),

                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: _openPortalInBrowser,
                              icon: const Icon(Icons.open_in_browser_rounded, size: 16),
                              label: const Text('🌐 Open http://192.168.4.1 in Browser', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                              style: OutlinedButton.styleFrom(
                                foregroundColor: const Color(0xFF55E2C0),
                                side: BorderSide(color: const Color(0xFF55E2C0).withOpacity(0.4)),
                                padding: const EdgeInsets.symmetric(vertical: 12),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),

              // FOOTER (LIVE CONNECTION STATUS)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                decoration: BoxDecoration(
                  color: const Color(0xFF0A0F16),
                  border: Border(top: BorderSide(color: Colors.white.withOpacity(0.06))),
                ),
                child: Row(
                  children: [
                    _StatusDot(
                      active: hasConnectedPin,
                      activeColor: const Color(0xFF55E2C0),
                      inactiveColor: const Color(0xFF9B88FF),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        hasConnectedPin
                            ? 'SMART PIN CONNECTED: ${activePin?.id ?? "PIN-001"} (${activePin?.state ?? "VAD ARMED"} • ${activePin?.battery ?? 100}% LiPo • ${activePin?.network ?? "Wi-Fi"})'
                            : 'Waiting for smart pin handshake on Checkpoint Server (port 8080)...',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: hasConnectedPin ? FontWeight.w700 : FontWeight.w500,
                          color: hasConnectedPin ? const Color(0xFF55E2C0) : Colors.white60,
                        ),
                      ),
                    ),
                    if (hasConnectedPin)
                      ElevatedButton(
                        onPressed: () => Navigator.of(context).pop(),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF109C6D),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        child: const Text('Done', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SetupStep extends StatelessWidget {
  final String number;
  final String title;
  final String desc;

  const _SetupStep({required this.number, required this.title, required this.desc});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 20,
            height: 20,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: const Color(0xFF109C6D).withOpacity(0.2),
              border: Border.all(color: const Color(0xFF109C6D).withOpacity(0.5)),
            ),
            alignment: Alignment.center,
            child: Text(number, style: const TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: Color(0xFF55E2C0))),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Colors.white)),
                const SizedBox(height: 2),
                Text(desc, style: TextStyle(fontSize: 9.5, color: Colors.white.withOpacity(0.55), height: 1.3)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


class _ServerLoadingSplashScreen extends StatefulWidget {
  final bool isStarting;
  final String statusMessage;
  final VoidCallback onProceedOffline;
  final VoidCallback onCloseApp;

  const _ServerLoadingSplashScreen({
    required this.isStarting,
    required this.statusMessage,
    required this.onProceedOffline,
    required this.onCloseApp,
  });

  @override
  State<_ServerLoadingSplashScreen> createState() => _ServerLoadingSplashScreenState();
}

class _AnimatedRingPainter extends CustomPainter {
  final double ringProgress;
  final Color brandGreen;

  const _AnimatedRingPainter({
    required this.ringProgress,
    required this.brandGreen,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - 1.5;
    final rect = Rect.fromCircle(center: center, radius: radius);

    // 1. Subtle static background trace (very thin line around the circle)
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0
      ..color = brandGreen.withOpacity(0.12);
    canvas.drawCircle(center, radius, trackPaint);

    // 2. Animated active arc
    double sweepAngle = 0.0;
    double opacity = 1.0;
    double pulse = 0.0;

    if (ringProgress <= 0.65) {
      // Phase 1: Starting from top (-pi / 2), sweeps counter-clockwise to destination
      final t = (ringProgress / 0.65).clamp(0.0, 1.0);
      final curvedT = Curves.easeInOutCubic.transform(t);
      sweepAngle = -2 * pi * curvedT;
      opacity = 1.0;
      pulse = 0.0;
    } else if (ringProgress <= 0.82) {
      // Phase 2: Full circle reached original destination, pulses a bit bright
      sweepAngle = -2 * pi;
      final t = ((ringProgress - 0.65) / 0.17).clamp(0.0, 1.0);
      pulse = sin(t * pi);
      opacity = 1.0;
    } else {
      // Phase 3: Fades away
      sweepAngle = -2 * pi;
      final t = ((ringProgress - 0.82) / 0.18).clamp(0.0, 1.0);
      opacity = (1.0 - t).clamp(0.0, 1.0);
      pulse = 0.0;
    }

    if (opacity > 0.005 && sweepAngle.abs() > 0.005) {
      // Glow blooming during pulse
      if (pulse > 0.05) {
        final glowPaint = Paint()
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = 2.5 + (pulse * 4.5)
          ..color = brandGreen.withOpacity(0.40 * pulse * opacity);
        canvas.drawArc(rect, -pi / 2, sweepAngle, false, glowPaint);
      }

      // Main active line
      final activeColor = Color.lerp(
        brandGreen,
        const Color(0xFFD8FFF4),
        pulse * 0.65,
      )!;

      final activePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 1.2 + (pulse * 1.4)
        ..color = activeColor.withOpacity(opacity);

      canvas.drawArc(rect, -pi / 2, sweepAngle, false, activePaint);
    }
  }

  @override
  bool shouldRepaint(_AnimatedRingPainter oldDelegate) => true;
}

class _ServerLoadingSplashScreenState extends State<_ServerLoadingSplashScreen>
    with TickerProviderStateMixin {
  late final AnimationController _animController;
  late final AnimationController _ringController;
  late final List<_SplashParticle> _particles;
  late final DateTime _startTime;

  @override
  void initState() {
    super.initState();
    _startTime = DateTime.now();

    // Calming, slow ambient breathing cycle (6.2 seconds)
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 6200),
    )..repeat();

    // Ring loading animation cycle (2.5 seconds)
    _ringController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2500),
    )..repeat();

    // Initialize deterministic, organic particles with calm float speeds
    final rng = Random(42);
    _particles = List.generate(40, (i) {
      return _SplashParticle(
        x: rng.nextDouble(),
        y: rng.nextDouble(),
        size: 1.0 + rng.nextDouble() * 2.2,
        speedY: 0.022 + rng.nextDouble() * 0.038,
        maxOpacity: 0.20 + rng.nextDouble() * 0.35,
        phase: rng.nextDouble() * 2 * pi,
      );
    });
  }

  @override
  void dispose() {
    _animController.dispose();
    _ringController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const Color brandGreen = Color(0xFF55E2C0);
    const Color brandGreenDark = Color(0xFF10B981);
    const Color cardBg = Color(0xFF06140E);

    return AnimatedBuilder(
      animation: Listenable.merge([_animController, _ringController]),
      builder: (context, _) {
        final progress = _animController.value;
        final ringProgress = _ringController.value;

        // Smooth sine wave for gentle, slow breathing in and out
        final breathe = (sin(progress * 2 * pi) + 1.0) / 2.0;

        // Monotonically increasing continuous seconds: zero looping seams
        final elapsedSeconds = DateTime.now().difference(_startTime).inMilliseconds / 1000.0;

        // Darkened green palette: remains deeply dark and moody at all times
        final Color coreColor = Color.lerp(
          const Color(0xFF02140B),
          const Color(0xFF062518),
          breathe,
        )!;

        final Color midColor = Color.lerp(
          const Color(0xFF010C07),
          const Color(0xFF03160D),
          breathe,
        )!;

        final Color edgeColor = Color.lerp(
          const Color(0xFF000502),
          const Color(0xFF010804),
          breathe,
        )!;

        return Container(
          width: double.infinity,
          height: double.infinity,
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: const Alignment(0.0, -0.1),
              radius: 1.15 + (breathe * 0.20),
              colors: [coreColor, midColor, edgeColor],
              stops: const [0.0, 0.55, 1.0],
            ),
          ),
          child: Stack(
            alignment: Alignment.center,
            children: [
              // Dynamic continuous drifting particles across the dark green background
              Positioned.fill(
                child: CustomPaint(
                  painter: _SplashParticlesPainter(
                    particles: _particles,
                    elapsedSeconds: elapsedSeconds,
                    color: brandGreen,
                  ),
                ),
              ),

              // Soft, subdued ambient green breathing glow behind card
              Container(
                width: 360 + (breathe * 50),
                height: 360 + (breathe * 50),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      brandGreen.withOpacity(0.045 + (breathe * 0.04)),
                      brandGreenDark.withOpacity(0.015 + (breathe * 0.015)),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),

              // Close button at top-right
              Positioned(
                top: 14,
                right: 16,
                child: IconButton(
                  icon: Icon(Icons.close_rounded, color: Colors.white.withOpacity(0.50), size: 20),
                  tooltip: 'Close Application',
                  onPressed: widget.onCloseApp,
                ),
              ),

              // Central Content Column with Round Card Enclosing Logo
              Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Round Card with Animated Counter-Clockwise Line
                  SizedBox(
                    width: 190,
                    height: 190,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // Frosted Glass Round Card
                        ClipOval(
                          child: BackdropFilter(
                            filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
                            child: Container(
                              width: 190,
                              height: 190,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: cardBg.withOpacity(0.88),
                                boxShadow: [
                                  BoxShadow(
                                    color: Colors.black.withOpacity(0.65),
                                    blurRadius: 36,
                                    offset: const Offset(0, 16),
                                  ),
                                  BoxShadow(
                                    color: brandGreen.withOpacity(0.04 + (breathe * 0.04)),
                                    blurRadius: 28,
                                    spreadRadius: -2,
                                  ),
                                ],
                              ),
                              alignment: Alignment.center,
                              // Logo in the middle enclosed by the round card
                              child: Container(
                                width: 68,
                                height: 68,
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(20),
                                  gradient: const LinearGradient(
                                    colors: [brandGreen, brandGreenDark],
                                    begin: Alignment.topLeft,
                                    end: Alignment.bottomRight,
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: brandGreen.withOpacity(0.28 + (breathe * 0.18)),
                                      blurRadius: 18 + (breathe * 8),
                                      spreadRadius: 2,
                                    ),
                                  ],
                                ),
                                child: const Icon(Icons.shield_rounded, size: 36, color: Colors.white),
                              ),
                            ),
                          ),
                        ),

                        // Animated Counter-Clockwise Ring Border
                        Positioned.fill(
                          child: CustomPaint(
                            painter: _AnimatedRingPainter(
                              ringProgress: ringProgress,
                              brandGreen: brandGreen,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Brand Name
                  const Text(
                    'SECURELINK',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 2.2,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'CAMPUS SENTINEL',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.4,
                      color: brandGreen,
                    ),
                  ),
                  const SizedBox(height: 18),

                  // Status Row with subtle pulsing beacon dot
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: brandGreen,
                          boxShadow: [
                            BoxShadow(
                              color: brandGreen.withOpacity(0.4 + 0.6 * breathe),
                              blurRadius: 8,
                              spreadRadius: 1,
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        'Preparing the server...',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w500,
                          letterSpacing: 0.4,
                          color: Colors.white.withOpacity(0.72),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 22),

                  // Offline Bypass
                  TextButton(
                    onPressed: widget.onProceedOffline,
                    child: Text(
                      'Proceed to Dashboard (Offline Mode)',
                      style: TextStyle(
                        fontSize: 10,
                        color: Colors.white.withOpacity(0.35),
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}