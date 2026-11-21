import 'dart:io';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import '../services/mobile_server_service.dart';
import '../services/ble_pin_relay_service.dart';

class MobileDesignSystem {
  // Desktop scaffold & surface colors
  static const Color bgDark = Color(0xFF070A12); // Exact desktop scaffoldBackgroundColor
  static const Color surface1 = Color(0xFF0E151A); // Forest obsidian card surface
  static const Color surface2 = Color(0xFF142026);
  static const Color surfaceBorder = Color(0x1FFFFFFF);

  // Exact Desktop Emerald Green Identity
  static const Color primaryGreen = Color(0xFF109C6D);        // Desktop Primary Action Green
  static const Color primaryGreenBright = Color(0xFF1E9B57);   // Desktop Vibrant Green
  static const Color primaryGreenMint = Color(0xFF55E2C0);     // Desktop Secondary Mint Accent
  static const Color primaryGreenSoft = Color(0xFF55D58B);     // Desktop Normal Status Green
  static const Color deepGreenGlow = Color(0xFF123524);        // Desktop Safe State / Ambient Green

  // Desktop green aliases
  static const Color accentMint = Color(0xFF55E2C0);
  static const Color accentCyan = Color(0xFF55E2C0);
  static const Color accentIndigo = Color(0xFF7F6CFF);         // Desktop Secondary Indigo
  static const Color statusWarning = Color(0xFFFFB800);
  static const Color statusThreat = Color(0xFFFF6A1A);
  static const Color statusDanger = Color(0xFFFF4D67);
}

class MobileSecureLinkLogo extends StatelessWidget {
  final double size;
  final BoxFit fit;

  const MobileSecureLinkLogo({
    super.key,
    this.size = 28,
    this.fit = BoxFit.contain,
  });

  @override
  Widget build(BuildContext context) {
    return Image.asset(
      'Securelinklogo.png',
      width: size,
      height: size,
      fit: fit,
      errorBuilder: (context, error, stackTrace) {
        final f1 = File('assets/Securelinklogo.png');
        if (f1.existsSync()) {
          return Image.file(f1, width: size, height: size, fit: fit);
        }
        final f2 = File('Securelinklogo.png');
        if (f2.existsSync()) {
          return Image.file(f2, width: size, height: size, fit: fit);
        }
        return Icon(Icons.shield_rounded, size: size, color: Colors.white);
      },
    );
  }
}

class MobileThreatTranscript extends StatelessWidget {
  final String text;
  final double fontSize;
  final FontWeight fontWeight;
  final Color baseColor;

  const MobileThreatTranscript({
    super.key,
    required this.text,
    this.fontSize = 13.0,
    this.fontWeight = FontWeight.w500,
    this.baseColor = Colors.white,
  });

  static const hardThreats = {
    'papatayin', 'patayin', 'ipapatay', 'pinatay', 'katayin', 'kakatayin',
    'bugbugin', 'bubugbugin', 'binugbog', 'bugbugan',
    'sasapakin', 'sapakin', 'sinapak', 'sapakan',
    'suntukin', 'susuntukin', 'sinuntok', 'suntukan',
    'tadyakan', 'tatadyakan', 'tinadyakan',
    'upakan', 'uupakan', 'inupakan',
    'saksakin', 'sasaksakin', 'sinaksak',
    'barilin', 'babarilin', 'binaril',
    'gulpihin', 'gugulpihin', 'ginulpi',
    'abangan', 'aabangan', 'tumba', 'tumbahin', 'hiwain', 'masaktan', 'resbak', 'resbakan', 'yari',
    'kill', 'punch', 'attack', 'stab', 'murder', 'hurt', 'shoot'
  };

  static const hardExtort = {
    'pera', 'bayad', 'ambag', 'ilabas', 'akin na', 'bigyan', 'palamunin', 'baon', 'holdap', 'snatch'
  };

  static const hardHarass = {
    // Bullying & ableist/psychological slurs
    'mongoloid', 'mongol', 'abnoy', 'autistic', 'retard', 'retarded',
    'sintosinto', 'sayad', 'baliw', 'lukaluka', 'buang', 'timang', 'kulangkulang',
    'siraulo', 'unggoy', 'aswang',
    // Body-shaming & appearance bullying
    'tabatoy', 'baboy', 'balyena', 'tingting', 'kalansay', 'ngongo', 'ngiwi',
    'panget', 'pangit', 'chaka', 'dugyot', 'mabaho', 'baho',
    // Social degradation & poverty insults
    'squatter', 'skwater', 'isquatter', 'pulubi', 'hampaslupa', 'pataygutom',
    'alipin', 'palamunin', 'pabigat', 'salot', 'patapon', 'basura', 'walangkwenta', 'ampaw',
    // Slut-shaming & gender/homophobic insults
    'bakla', 'bading', 'bayot', 'tibo', 'pokpok', 'malandi', 'kiri', 'higad', 'hitad', 'puday', 'bastos',
    // Profanities & verbal abuse
    'gago', 'gaga', 'tarantado', 'tarantada', 'ulol', 'tangina', 'tanginamo', 'putangina', 'putanginamoka', 'puta',
    'pakshet', 'pakyu', 'kupal', 'leche', 'letse', 'bwisit', 'bwiset',
    'hayop', 'hayup', 'walanghiya', 'taragis', 'hudas', 'inutil', 'bobo', 'tanga',
    'ungas', 'punyeta', 'lintik', 'demonyo', 'kingina', 'pota', 'yawa', 'kuwenta', 'kwenta',
    // English slurs & abuse
    'fuck', 'shit', 'bitch', 'asshole', 'bastard', 'cunt', 'idiot', 'stupid', 'loser', 'trash'
  };

  @override
  Widget build(BuildContext context) {
    final words = text.split(' ');
    final spans = <InlineSpan>[];

    for (int i = 0; i < words.length; i++) {
      final word = words[i];
      final clean = word.toLowerCase().replaceAll(RegExp(r'[^a-zA-Z0-9]'), '');

      Color? tagColor;
      if (hardThreats.contains(clean)) {
        tagColor = const Color(0xFFFF3B5C);
      } else if (hardExtort.contains(clean)) {
        tagColor = const Color(0xFFFFB800);
      } else if (hardHarass.contains(clean)) {
        tagColor = const Color(0xFFFF8533);
      }

      if (tagColor != null) {
        spans.add(
          WidgetSpan(
            alignment: PlaceholderAlignment.middle,
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 1.5, vertical: 1),
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
              decoration: BoxDecoration(
                color: tagColor.withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(5),
                border: Border.all(color: tagColor.withValues(alpha: 0.45), width: 0.8),
                boxShadow: [
                  BoxShadow(
                    color: tagColor.withValues(alpha: 0.25),
                    blurRadius: 6,
                    spreadRadius: 0.5,
                  ),
                ],
              ),
              child: Text(
                word,
                style: TextStyle(
                  color: tagColor,
                  fontSize: fontSize,
                  fontWeight: FontWeight.w800,
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
            ),
          ),
        );
      }
    }

    return RichText(
      text: TextSpan(children: spans),
    );
  }
}

class MobileGlassCard extends StatelessWidget {
  final Widget child;
  final double radius;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry? margin;
  final Color? backgroundColor;
  final Border? border;
  final VoidCallback? onTap;

  const MobileGlassCard({
    super.key,
    required this.child,
    this.radius = 20,
    this.padding = const EdgeInsets.all(16),
    this.margin,
    this.backgroundColor,
    this.border,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    Widget card = Container(
      margin: margin,
      decoration: BoxDecoration(
        color: backgroundColor ?? MobileDesignSystem.surface1.withValues(alpha: 0.90),
        borderRadius: BorderRadius.circular(radius),
        border: border ??
            Border.all(
              color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.22),
              width: 1,
            ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.50),
            blurRadius: 22,
            offset: const Offset(0, 8),
          ),
          BoxShadow(
            color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.05),
            blurRadius: 14,
            spreadRadius: 1,
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
          child: Padding(
            padding: padding,
            child: child,
          ),
        ),
      ),
    );

    if (onTap != null) {
      return Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(radius),
          onTap: onTap,
          child: card,
        ),
      );
    }
    return card;
  }
}

class MobileStatusPill extends StatelessWidget {
  final bool online;
  final String state;

  const MobileStatusPill({
    super.key,
    required this.online,
    required this.state,
  });

  @override
  Widget build(BuildContext context) {
    final upper = state.toUpperCase();
    final Color color;
    if (!online) {
      color = const Color(0xFF6B7280);
    } else if (upper.contains('STREAMING')) {
      color = MobileDesignSystem.primaryGreenMint;
    } else if (upper.contains('ANALYZING') || upper.contains('WHISPER')) {
      color = MobileDesignSystem.accentIndigo;
    } else {
      color = MobileDesignSystem.primaryGreen;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(30),
        border: Border.all(color: color.withValues(alpha: 0.38), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color,
              boxShadow: online
                  ? [
                      BoxShadow(
                        color: color.withValues(alpha: 0.8),
                        blurRadius: 6,
                        spreadRadius: 1.5,
                      )
                    ]
                  : null,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            !online ? 'OFFLINE' : state,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.6,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class MobileBatteryMeter extends StatelessWidget {
  final int battery;
  final String estRuntime;
  final bool showEstRuntime;
  final double height;

  const MobileBatteryMeter({
    super.key,
    required this.battery,
    required this.estRuntime,
    this.showEstRuntime = true,
    this.height = 6,
  });

  Color get _color {
    if (battery <= 15) return MobileDesignSystem.statusDanger;
    if (battery <= 25) return const Color(0xFFFF5E72);
    if (battery <= 45) return MobileDesignSystem.statusWarning;
    return MobileDesignSystem.primaryGreen;
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Row(
              children: [
                Icon(
                  battery <= 20
                      ? Icons.battery_alert_rounded
                      : Icons.battery_charging_full_rounded,
                  size: 15,
                  color: _color,
                ),
                const SizedBox(width: 5),
                Text(
                  '$battery%',
                  style: TextStyle(
                    color: _color,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.2,
                  ),
                ),
              ],
            ),
            if (showEstRuntime)
              Text(
                estRuntime,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.65),
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
          ],
        ),
        const SizedBox(height: 7),
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Stack(
            children: [
              Container(
                height: height,
                width: double.infinity,
                color: Colors.white.withValues(alpha: 0.06),
              ),
              FractionallySizedBox(
                widthFactor: (battery.clamp(0, 100)) / 100.0,
                child: Container(
                  height: height,
                  decoration: BoxDecoration(
                    color: _color,
                    borderRadius: BorderRadius.circular(10),
                    boxShadow: [
                      BoxShadow(
                        color: _color.withValues(alpha: 0.6),
                        blurRadius: 8,
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

class RadarScannerWidget extends StatefulWidget {
  final double size;
  const RadarScannerWidget({super.key, this.size = 110});

  @override
  State<RadarScannerWidget> createState() => _RadarScannerWidgetState();
}

class _RadarScannerWidgetState extends State<RadarScannerWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _anim;

  @override
  void initState() {
    super.initState();
    _anim = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2400),
    )..repeat();
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _anim,
      builder: (context, child) {
        return SizedBox(
          width: widget.size,
          height: widget.size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              // Outer pulse ring
              Transform.scale(
                scale: 0.4 + (_anim.value * 0.6),
                child: Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: MobileDesignSystem.primaryGreen
                          .withValues(alpha: (1.0 - _anim.value) * 0.5),
                      width: 1.5,
                    ),
                  ),
                ),
              ),
              // Secondary ring
              Transform.scale(
                scale: 0.2 + (((_anim.value + 0.5) % 1.0) * 0.6),
                child: Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: MobileDesignSystem.primaryGreenMint.withValues(
                          alpha: (1.0 - ((_anim.value + 0.5) % 1.0)) * 0.4),
                      width: 1.2,
                    ),
                  ),
                ),
              ),
              // Center glow hub
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.16),
                  border: Border.all(
                    color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.45),
                    width: 1.8,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25),
                      blurRadius: 16,
                      spreadRadius: 2,
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.sensors_rounded,
                  color: MobileDesignSystem.primaryGreenMint,
                  size: 26,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class ServerHostModal extends StatefulWidget {
  final MobileServerService service;
  const ServerHostModal({super.key, required this.service});

  @override
  State<ServerHostModal> createState() => _ServerHostModalState();
}

class _ServerHostModalState extends State<ServerHostModal> {
  late TextEditingController _hostCtrl;
  late TextEditingController _portCtrl;
  late TextEditingController _tunnelCtrl;
  late bool _useTunnel;
  bool _isFetchingTunnel = false;

  @override
  void initState() {
    super.initState();
    _hostCtrl = TextEditingController(text: widget.service.host);
    _portCtrl = TextEditingController(text: widget.service.port.toString());
    final initialTunnel = widget.service.cloudTunnelUrl.isNotEmpty
        ? widget.service.cloudTunnelUrl
        : 'https://rings-diploma-evaluated-mls.trycloudflare.com';
    _tunnelCtrl = TextEditingController(text: initialTunnel);
    _useTunnel = widget.service.useCloudTunnel;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _autoFetchTunnel(notify: false);
    });
  }

  Future<void> _autoFetchTunnel({bool notify = true}) async {
    if (_isFetchingTunnel) return;
    setState(() => _isFetchingTunnel = true);
    try {
      final fetched = await widget.service.fetchCloudTunnel();
      if (mounted) {
        if (fetched != null && fetched.isNotEmpty) {
          setState(() {
            _tunnelCtrl.text = fetched;
          });
          if (notify) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                backgroundColor: const Color(0xFF0E151A),
                content: Text(
                  'Auto-detected active tunnel: $fetched',
                  style: const TextStyle(color: MobileDesignSystem.primaryGreenMint),
                ),
                duration: const Duration(seconds: 2),
              ),
            );
          }
        } else if (_tunnelCtrl.text.isEmpty && widget.service.cloudTunnelUrl.isNotEmpty) {
          setState(() {
            _tunnelCtrl.text = widget.service.cloudTunnelUrl;
          });
        }
      }
    } catch (_) {
    } finally {
      if (mounted) {
        setState(() => _isFetchingTunnel = false);
      }
    }
  }

  @override
  void dispose() {
    _hostCtrl.dispose();
    _portCtrl.dispose();
    _tunnelCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
        top: 24,
        left: 20,
        right: 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(9),
                      decoration: BoxDecoration(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.18),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.hub_rounded,
                        color: MobileDesignSystem.primaryGreenMint,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 12),
                    const Text(
                      'AI Server Connection',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
                IconButton(
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close_rounded, color: Colors.white60),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'Central System is the primary station running AI inference. Mobile companions sync to receive real-time telemetry and safety alerts.',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.6),
                fontSize: 12.5,
              ),
            ),
            const SizedBox(height: 14),

            // Cloudflare Tunnel Mode Toggle
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                gradient: _useTunnel
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
                  color: _useTunnel
                      ? MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.5)
                      : Colors.white.withValues(alpha: 0.1),
                ),
              ),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: _useTunnel
                          ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)
                          : Colors.white.withValues(alpha: 0.05),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Icon(
                      Icons.cloud_sync_rounded,
                      color: _useTunnel ? MobileDesignSystem.primaryGreenMint : Colors.white60,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Cloudflare Global Tunnel',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text(
                          'Bypasses Campus AP Isolation over WSS/TLS',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.6),
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Switch.adaptive(
                    value: _useTunnel,
                    activeThumbColor: MobileDesignSystem.primaryGreenMint,
                    activeTrackColor: MobileDesignSystem.primaryGreen.withValues(alpha: 0.5),
                    onChanged: (val) {
                      setState(() {
                        _useTunnel = val;
                      });
                      if (val && _tunnelCtrl.text.trim().isEmpty) {
                        _autoFetchTunnel(notify: true);
                      }
                    },
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),

            if (_useTunnel) ...[
              // Cloudflare Tunnel URL Input
              TextField(
                controller: _tunnelCtrl,
                style: const TextStyle(color: Colors.white, fontSize: 14),
                decoration: InputDecoration(
                  labelText: 'Cloudflare Tunnel WebSocket/HTTP URL',
                  labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7)),
                  hintText: 'https://<tunnel-id>.trycloudflare.com',
                  prefixIcon: const Icon(Icons.cloud_rounded, color: MobileDesignSystem.primaryGreenMint),
                  filled: true,
                  fillColor: Colors.white.withValues(alpha: 0.05),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: const BorderSide(color: MobileDesignSystem.primaryGreenMint),
                  ),
                ),
              ),
              const SizedBox(height: 10),

              // Auto-Fetch Button from Central System
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _isFetchingTunnel ? null : () => _autoFetchTunnel(notify: true),
                  icon: _isFetchingTunnel
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2, color: MobileDesignSystem.primaryGreenMint),
                        )
                      : const Icon(Icons.sync_rounded, size: 16),
                  label: Text(
                    _isFetchingTunnel ? 'Fetching tunnel from Laptop Central System...' : 'Auto-Fetch Active Tunnel from Laptop',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
                  ),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: MobileDesignSystem.primaryGreenMint,
                    side: BorderSide(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.5)),
                    padding: const EdgeInsets.symmetric(vertical: 11),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
              const SizedBox(height: 10),

              // Quick Action Chips: Paste & Active Preset
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ActionChip(
                    avatar: const Icon(Icons.content_paste_rounded, size: 14, color: Colors.white70),
                    label: const Text('Paste from Clipboard', style: TextStyle(fontSize: 11, color: Colors.white)),
                    backgroundColor: Colors.white.withValues(alpha: 0.08),
                    side: BorderSide(color: Colors.white.withValues(alpha: 0.15)),
                    onPressed: () async {
                      final data = await Clipboard.getData(Clipboard.kTextPlain);
                      if (data?.text != null && data!.text!.trim().isNotEmpty) {
                        setState(() {
                          _tunnelCtrl.text = data.text!.trim();
                        });
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              backgroundColor: Color(0xFF0E151A),
                              content: Text('Pasted Cloudflare Tunnel URL from clipboard!', style: TextStyle(color: MobileDesignSystem.primaryGreenMint)),
                              duration: Duration(seconds: 1),
                            ),
                          );
                        }
                      }
                    },
                  ),
                  ActionChip(
                    avatar: const Icon(Icons.bolt_rounded, size: 14, color: MobileDesignSystem.primaryGreenMint),
                    label: Text(
                      'Active: ${(widget.service.cloudTunnelUrl.isNotEmpty ? widget.service.cloudTunnelUrl : "https://rings-diploma-evaluated-mls.trycloudflare.com").replaceAll("https://", "")}',
                      style: const TextStyle(fontSize: 10.5, color: Colors.white70),
                    ),
                    backgroundColor: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
                    side: BorderSide(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.3)),
                    onPressed: () {
                      setState(() {
                        _tunnelCtrl.text = widget.service.cloudTunnelUrl.isNotEmpty
                            ? widget.service.cloudTunnelUrl
                            : 'https://rings-diploma-evaluated-mls.trycloudflare.com';
                      });
                    },
                  ),
                ],
              ),
            ] else ...[
              // Priority Architecture Card
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.hub_rounded, color: MobileDesignSystem.primaryGreenMint, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Central Station: ${widget.service.csId}',
                            style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Priority 1: Central System • Priority 2: Mobile Companion',
                            style: TextStyle(color: Colors.white.withValues(alpha: 0.65), fontSize: 10.5),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),

              // Auto-Discovery Button
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: widget.service.isAutoDiscoveringCS
                      ? null
                      : () async {
                          final found = await widget.service.autoDiscoverCentralSystem();
                          if (context.mounted) {
                            setState(() {
                              _hostCtrl.text = widget.service.host;
                              _portCtrl.text = widget.service.port.toString();
                            });
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                backgroundColor: const Color(0xFF0E151A),
                                content: Text(
                                  found
                                      ? 'Discovered Central System at ${widget.service.host}:${widget.service.port}!'
                                      : 'Could not auto-discover. Please check laptop Wi-Fi.',
                                  style: TextStyle(
                                    color: found ? MobileDesignSystem.primaryGreenMint : MobileDesignSystem.statusWarning,
                                  ),
                                ),
                              ),
                            );
                          }
                        },
                  icon: widget.service.isAutoDiscoveringCS
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2, color: MobileDesignSystem.primaryGreenMint),
                        )
                      : const Icon(Icons.radar_rounded, size: 16),
                  label: Text(
                    widget.service.isAutoDiscoveringCS ? 'Scanning Wi-Fi & UDP 8888...' : 'Auto-Discover Central System (UDP 8888)',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
                  ),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: MobileDesignSystem.primaryGreenMint,
                    side: BorderSide(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.5)),
                    padding: const EdgeInsets.symmetric(vertical: 11),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
              const SizedBox(height: 14),

              // Preset Quick Buttons
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _presetChip('Laptop Host (10.28.20.11)', '10.28.20.11'),
                  _presetChip('Campus Wi-Fi (10.28.20.28)', '10.28.20.28'),
                  _presetChip('Localhost (127.0.0.1)', '127.0.0.1'),
                  _presetChip('Local Subnet (192.168.1.100)', '192.168.1.100'),
                ],
              ),

              const SizedBox(height: 18),
              TextField(
                controller: _hostCtrl,
                style: const TextStyle(color: Colors.white, fontSize: 14.5),
                decoration: InputDecoration(
                  labelText: 'Central System IP / Hostname',
                  labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7)),
                  hintText: 'e.g. 10.28.20.11',
                  prefixIcon: const Icon(Icons.dns_rounded,
                      color: MobileDesignSystem.primaryGreenMint),
                  filled: true,
                  fillColor: Colors.white.withValues(alpha: 0.05),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide:
                        const BorderSide(color: MobileDesignSystem.primaryGreenMint),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _portCtrl,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white, fontSize: 14.5),
                decoration: InputDecoration(
                  labelText: 'Central System Port',
                  labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7)),
                  hintText: '8080',
                  prefixIcon: const Icon(Icons.numbers_rounded,
                      color: MobileDesignSystem.primaryGreenMint),
                  filled: true,
                  fillColor: Colors.white.withValues(alpha: 0.05),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: BorderSide(
                        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide:
                        const BorderSide(color: MobileDesignSystem.primaryGreenMint),
                  ),
                ),
              ),
            ],

            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () {
                  if (_useTunnel) {
                    final t = _tunnelCtrl.text.trim();
                    if (t.isNotEmpty) {
                      widget.service.setCloudTunnelUrl(t, enable: true);
                    } else {
                      widget.service.setCloudTunnelEnabled(true);
                    }
                  } else {
                    final h = _hostCtrl.text.trim();
                    final p = int.tryParse(_portCtrl.text.trim()) ?? 8080;
                    if (h.isNotEmpty) {
                      widget.service.setCloudTunnelEnabled(false);
                      widget.service.updateHost(h, p);
                    }
                  }
                  Navigator.pop(context);
                },
                icon: const Icon(Icons.sync_rounded),
                label: Text(
                  _useTunnel ? 'Connect via Cloudflare Tunnel' : 'Sync with Central System',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: MobileDesignSystem.primaryGreen,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  elevation: 4,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _presetChip(String label, String ip) {
    return GestureDetector(
      onTap: () {
        setState(() {
          _hostCtrl.text = ip;
          _portCtrl.text = '8080';
        });
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.30)),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 10.5,
            color: Colors.white.withValues(alpha: 0.85),
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PRIORITY HIERARCHY BADGE
// ════════════════════════════════════════════════════════════════════════════
class PriorityHierarchyBadge extends StatelessWidget {
  final String csId;
  const PriorityHierarchyBadge({super.key, this.csId = 'CS-1'});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.28)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
            decoration: BoxDecoration(
              color: MobileDesignSystem.primaryGreen,
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Text(
              'P1',
              style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w900, color: Colors.white),
            ),
          ),
          const SizedBox(width: 4),
          Text(
            csId,
            style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Colors.white),
          ),
          const SizedBox(width: 6),
          Icon(Icons.arrow_forward_rounded, size: 10, color: Colors.white.withValues(alpha: 0.4)),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Text(
              'P2',
              style: TextStyle(fontSize: 8.5, fontWeight: FontWeight.w900, color: Colors.white70),
            ),
          ),
          const SizedBox(width: 4),
          const Text(
            'Mobile',
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Colors.white70),
          ),
        ],
      ),
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PAIR SMART PIN MODAL (WI-FI & BLUETOOTH)
// ════════════════════════════════════════════════════════════════════════════
class PairPinModal extends StatefulWidget {
  final MobileServerService service;
  final VoidCallback? onPaired;

  const PairPinModal({super.key, required this.service, this.onPaired});

  @override
  State<PairPinModal> createState() => _PairPinModalState();
}

class _PairPinModalState extends State<PairPinModal> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final TextEditingController _pinIdCtrl = TextEditingController();
  final TextEditingController _aliasCtrl = TextEditingController();
  final TextEditingController _ssidCtrl = TextEditingController();
  final TextEditingController _passCtrl = TextEditingController();
  bool _isPairing = false;
  ScanResult? _selectedBleScanResult;
  String? _selectedBlePin;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _tabController.addListener(_handleTabChange);
    if (widget.service.checkpoints.isNotEmpty) {
      _ssidCtrl.text = widget.service.checkpoints.first.ssid;
      _passCtrl.text = widget.service.checkpoints.first.pass;
    }
    BlePinRelayService().addListener(_onBleRelayChanged);
    BlePinRelayService().startScan();
    // Auto-scan Wi-Fi on modal open
    WidgetsBinding.instance.addPostFrameCallback((_) {
      widget.service.searchForSmartPins();
    });
  }

  void _onBleRelayChanged() {
    if (mounted) setState(() {});
  }

  void _handleTabChange() {
    if (_tabController.index == 1) {
      BlePinRelayService().startScan();
    }
  }

  @override
  void dispose() {
    BlePinRelayService().removeListener(_onBleRelayChanged);
    _tabController.removeListener(_handleTabChange);
    _tabController.dispose();
    _pinIdCtrl.dispose();
    _aliasCtrl.dispose();
    _ssidCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: MediaQuery.of(context).size.height * 0.88,
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
        top: 16,
        left: 20,
        right: 20,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Drag handle
          Center(
            child: Container(
              width: 44,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.white24,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Header
          Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [MobileDesignSystem.primaryGreen, MobileDesignSystem.primaryGreenMint],
                  ),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Icon(Icons.add_link_rounded, color: Colors.white, size: 22),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Pair Smart Pin Badge',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: Colors.white),
                    ),
                    Text(
                      'Link Seeed XIAO ESP32S3 to ${widget.service.userName}',
                      style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.6)),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close_rounded, color: Colors.white54),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Priority Architecture Banner
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.04),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
            ),
            child: Row(
              children: [
                const Icon(Icons.account_tree_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Connection Hierarchy',
                        style: TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700),
                      ),
                      Text(
                        '1st Priority: Central System (${widget.service.csId})\n2nd Priority: This Mobile Device (${widget.service.userName})',
                        style: TextStyle(color: Colors.white.withValues(alpha: 0.65), fontSize: 10, height: 1.3),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Tabs
          Container(
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.05),
              borderRadius: BorderRadius.circular(14),
            ),
            child: TabBar(
              controller: _tabController,
              indicatorColor: MobileDesignSystem.primaryGreenMint,
              indicatorSize: TabBarIndicatorSize.tab,
              labelColor: Colors.white,
              unselectedLabelColor: Colors.white54,
              tabs: const [
                Tab(icon: Icon(Icons.wifi_rounded, size: 18), text: 'Wi-Fi & Network'),
                Tab(icon: Icon(Icons.bluetooth_rounded, size: 18), text: 'Bluetooth (BLE)'),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Tab views
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildWifiPairingTab(),
                _buildBluetoothPairingTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWifiPairingTab() {
    final discovered = widget.service.allDevices;

    return ListView(
      children: [
        // Real Discovered Smart Pins Section
        if (discovered.isNotEmpty) ...[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'DETECTED ON NETWORK (${discovered.length})',
                style: const TextStyle(
                  color: MobileDesignSystem.primaryGreenMint,
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 0.8,
                ),
              ),
              GestureDetector(
                onTap: () async {
                  await widget.service.searchForSmartPins();
                  setState(() {});
                },
                child: const Row(
                  children: [
                    Icon(Icons.refresh_rounded, size: 13, color: Colors.white70),
                    SizedBox(width: 3),
                    Text('Refresh', style: TextStyle(color: Colors.white70, fontSize: 11, fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...discovered.map((dev) {
            final isPaired = widget.service.isPinPaired(dev.id);
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: isPaired
                    ? Colors.white.withValues(alpha: 0.03)
                    : MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isPaired
                      ? Colors.white12
                      : MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.35),
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.sensors_rounded,
                    color: dev.stateColor,
                    size: 22,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              dev.id,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w800,
                                fontSize: 13.5,
                              ),
                            ),
                            const SizedBox(width: 6),
                            if (isPaired)
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
                                decoration: BoxDecoration(
                                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25),
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: const Text(
                                  'PAIRED',
                                  style: TextStyle(color: MobileDesignSystem.primaryGreenMint, fontSize: 8.5, fontWeight: FontWeight.w900),
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${dev.state} • ${dev.battery}% (${dev.estRuntime}) • ${dev.network}',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.6),
                            fontSize: 10.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                  ElevatedButton(
                    onPressed: () async {
                      _pinIdCtrl.text = dev.id;
                      if (!isPaired) {
                        await widget.service.pairPin(dev.id, alias: _aliasCtrl.text.trim());
                        if (!mounted) return;
                        Navigator.pop(context);
                        widget.onPaired?.call();
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            backgroundColor: const Color(0xFF0E151A),
                            content: Text(
                              'Pin ${dev.id} successfully paired!',
                              style: const TextStyle(color: MobileDesignSystem.primaryGreenMint),
                            ),
                          ),
                        );
                      }
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: isPaired
                          ? Colors.white12
                          : MobileDesignSystem.primaryGreen,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    child: Text(
                      isPaired ? 'Selected' : '1-Tap Pair',
                      style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800),
                    ),
                  ),
                ],
              ),
            );
          }),
          const SizedBox(height: 14),
          const Divider(color: Colors.white12),
          const SizedBox(height: 10),
        ],

        // Manual / Direct Setup Section
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.03),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white10),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Manual Pin Pairing & Wi-Fi Provisioning:', style: TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Text(
                'Enter Pin ID to assign it directly, or boot Pin into Setup AP mode ("SecureLink-Setup") and push network credentials.',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.65), fontSize: 10.5, height: 1.4),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),

        TextField(
          controller: _pinIdCtrl,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Smart Pin ID',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            hintText: 'e.g. PIN-001 or PIN-005',
            prefixIcon: const Icon(Icons.tag_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
        const SizedBox(height: 10),

        TextField(
          controller: _aliasCtrl,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Student / Teacher Assignment (Alias)',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            hintText: 'e.g. Student: Juan Dela Cruz (Grade 10)',
            prefixIcon: const Icon(Icons.person_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
        const SizedBox(height: 10),

        TextField(
          controller: _ssidCtrl,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Wi-Fi Network SSID',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            prefixIcon: const Icon(Icons.wifi_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
        const SizedBox(height: 10),

        TextField(
          controller: _passCtrl,
          obscureText: true,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Wi-Fi Password',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            prefixIcon: const Icon(Icons.lock_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
        const SizedBox(height: 18),

        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: _isPairing
                ? null
                : () async {
                    setState(() => _isPairing = true);
                    final pinId = _pinIdCtrl.text.trim();
                    if (pinId.isEmpty) {
                      setState(() => _isPairing = false);
                      return;
                    }
                    await widget.service.provisionPinWifiSetup(
                      pinId: pinId,
                      ssid: _ssidCtrl.text.trim(),
                      password: _passCtrl.text.trim(),
                      alias: _aliasCtrl.text.trim(),
                    );
                    if (!mounted) return;
                    setState(() => _isPairing = false);
                    Navigator.pop(context);
                    widget.onPaired?.call();
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        backgroundColor: const Color(0xFF0E151A),
                        content: Text(
                          'Smart Pin ${pinId.toUpperCase()} paired to ${widget.service.userName}!',
                          style: const TextStyle(color: MobileDesignSystem.primaryGreenMint),
                        ),
                      ),
                    );
                  },
            icon: _isPairing
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                : const Icon(Icons.check_circle_rounded),
            label: Text(
              _isPairing ? 'Provisioning Pin & Syncing CS...' : 'Pair & Connect Pin',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: MobileDesignSystem.primaryGreen,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildBluetoothPairingTab() {
    final ble = BlePinRelayService();
    final scanResults = ble.scanResults;

    return ListView(
      children: [
        Center(
          child: Container(
            width: 68,
            height: 68,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: const Color(0xFF007AFF).withValues(alpha: 0.12),
              border: Border.all(color: const Color(0xFF00C6FF).withValues(alpha: 0.35)),
            ),
            child: Icon(
              ble.isScanning ? Icons.bluetooth_searching_rounded : Icons.bluetooth_audio_rounded,
              color: const Color(0xFF00C6FF),
              size: 34,
            ),
          ),
        ),
        const SizedBox(height: 10),
        Center(
          child: Text(
            ble.isScanning
                ? 'Scanning for Nearby Smart Pins (BLE)...'
                : 'Real Bluetooth Low Energy (BLE) Scan',
            style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(height: 6),
        Center(
          child: Text(
            ble.isScanning
                ? 'Searching 2.4GHz spectrum for Nordic UART Service...'
                : (scanResults.isEmpty
                    ? 'No Smart Pins found nearby yet'
                    : '${scanResults.length} Pin(s) discovered in Bluetooth signal range'),
            style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11),
          ),
        ),
        const SizedBox(height: 14),

        // Discovered Devices list from REAL BlePinRelayService FlutterBluePlus scan
        if (scanResults.isNotEmpty) ...[
          ...scanResults.map((r) {
            final adv = r.advertisementData.advName;
            final devName = r.device.platformName;
            final name = adv.isNotEmpty ? adv : (devName.isNotEmpty ? devName : 'SecureLink-PIN');
            final isSelected = _selectedBleScanResult == r;

            return GestureDetector(
              onTap: () {
                setState(() {
                  _selectedBleScanResult = r;
                  _selectedBlePin = name;
                });
              },
              child: Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                decoration: BoxDecoration(
                  color: isSelected
                      ? const Color(0xFF007AFF).withValues(alpha: 0.18)
                      : Colors.white.withValues(alpha: 0.03),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: isSelected ? const Color(0xFF00C6FF) : Colors.white10,
                    width: isSelected ? 1.5 : 1,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      isSelected ? Icons.check_circle_rounded : Icons.bluetooth_rounded,
                      color: isSelected ? const Color(0xFF00C6FF) : Colors.white60,
                      size: 24,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(name, style: const TextStyle(color: Colors.white, fontSize: 13.5, fontWeight: FontWeight.w800)),
                          const SizedBox(height: 2),
                          Text(
                            'MAC: ${r.device.remoteId.str} • Nordic UART Service Ready',
                            style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontSize: 10.5),
                          ),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '${r.rssi} dBm',
                        style: const TextStyle(color: Color(0xFF00C6FF), fontSize: 10, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ),
              ),
            );
          }),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: ble.isScanning ? null : () => ble.startScan(),
              icon: const Icon(Icons.refresh_rounded, size: 14, color: Color(0xFF00C6FF)),
              label: const Text('Rescan BLE', style: TextStyle(color: Color(0xFF00C6FF), fontSize: 11)),
            ),
          ),
        ] else
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.04),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              children: [
                Icon(
                  ble.isScanning ? Icons.sync_rounded : Icons.bluetooth_disabled_rounded,
                  color: const Color(0xFF00C6FF),
                  size: 32,
                ),
                const SizedBox(height: 10),
                Text(
                  ble.isScanning ? 'Scanning for Nearby Smart Pins...' : 'No Smart Pins Discovered Over Bluetooth',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                Text(
                  ble.isScanning
                      ? 'Listening for BLE advertisements...'
                      : 'Ensure your XIAO ESP32-S3 Sense is powered on and within Bluetooth range (~10m).',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11),
                ),
                const SizedBox(height: 14),
                ElevatedButton.icon(
                  onPressed: ble.isScanning ? null : () => ble.startScan(),
                  icon: ble.isScanning
                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                      : const Icon(Icons.search_rounded, size: 16),
                  label: Text(ble.isScanning ? 'Scanning...' : 'Scan Bluetooth (BLE)'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF007AFF),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: 14),

        TextField(
          controller: _aliasCtrl,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Assign to Student / Teacher (Optional)',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            hintText: 'e.g. Student: Maria Santos',
            prefixIcon: const Icon(Icons.badge_rounded, color: Color(0xFF00C6FF), size: 18),
            filled: true,
            fillColor: Colors.white.withValues(alpha: 0.04),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
        const SizedBox(height: 18),

        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: _isPairing || _selectedBleScanResult == null
                ? null
                : () async {
                    setState(() => _isPairing = true);
                    final sel = _selectedBleScanResult!;
                    final advName = sel.advertisementData.advName;
                    final devName = sel.device.platformName;
                    String targetPinId = _selectedBlePin ?? (advName.isNotEmpty ? advName : (devName.isNotEmpty ? devName : 'SecureLink-PIN'));
                    targetPinId = targetPinId.replaceAll('SECURELINK-', '').replaceAll('SecureLink-', '').trim();
                    if (targetPinId.isEmpty) {
                      final clean = sel.device.remoteId.str.replaceAll(':', '').toUpperCase();
                      targetPinId = 'PIN-${clean.length > 4 ? clean.substring(clean.length - 4) : clean}';
                    }
                    if (!targetPinId.startsWith('PIN-') && !targetPinId.startsWith('PIN')) {
                      targetPinId = 'PIN-$targetPinId';
                    }

                    // REAL BLE connection and bridge
                    final connOk = await ble.connectToDevice(sel.device, widget.service, pinId: targetPinId);
                    if (connOk) {
                      await widget.service.pairPin(
                        targetPinId,
                        alias: _aliasCtrl.text.trim(),
                        method: 'Bluetooth Low Energy',
                      );
                      if (!mounted) return;
                      setState(() => _isPairing = false);
                      Navigator.pop(context);
                      widget.onPaired?.call();
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          backgroundColor: const Color(0xFF0E151A),
                          content: Text(
                            'Smart Pin $targetPinId bridged and paired via BLE!',
                            style: const TextStyle(color: Color(0xFF00C6FF)),
                          ),
                        ),
                      );
                    } else {
                      if (!mounted) return;
                      setState(() => _isPairing = false);
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          backgroundColor: const Color(0xFF0E151A),
                          content: Text(
                            'Failed to connect to ${sel.device.platformName}. Ensure pin is powered on.',
                            style: const TextStyle(color: MobileDesignSystem.statusDanger),
                          ),
                        ),
                      );
                    }
                  },
            icon: _isPairing
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                : const Icon(Icons.bluetooth_connected_rounded),
            label: Text(
              _isPairing
                  ? 'Connecting Real BLE...'
                  : (_selectedBleScanResult == null ? 'Select Discovered Pin Above' : 'Connect & Bridge Selected Pin'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF007AFF),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
          ),
        ),
      ],
    );
  }
}
