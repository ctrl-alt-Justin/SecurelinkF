import 'dart:io';
import 'dart:ui';
import 'package:flutter/material.dart';
import '../services/mobile_server_service.dart';

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

  @override
  void initState() {
    super.initState();
    _hostCtrl = TextEditingController(text: widget.service.host);
    _portCtrl = TextEditingController(text: widget.service.port.toString());
  }

  @override
  void dispose() {
    _hostCtrl.dispose();
    _portCtrl.dispose();
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
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: () {
                final h = _hostCtrl.text.trim();
                final p = int.tryParse(_portCtrl.text.trim()) ?? 8080;
                if (h.isNotEmpty) {
                  widget.service.updateHost(h, p);
                }
                Navigator.pop(context);
              },
              icon: const Icon(Icons.sync_rounded),
              label: const Text(
                'Sync with Central System',
                style: TextStyle(fontWeight: FontWeight.w800),
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
  final TextEditingController _pinIdCtrl = TextEditingController(text: 'PIN-001');
  final TextEditingController _aliasCtrl = TextEditingController(text: 'Student: Juan Dela Cruz');
  final TextEditingController _ssidCtrl = TextEditingController(text: 'SLTYMTBLLS');
  final TextEditingController _passCtrl = TextEditingController(text: '9945SUmaxx!');
  bool _isPairing = false;
  String _selectedBlePin = 'SECURELINK-PIN-001';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    if (widget.service.checkpoints.isNotEmpty) {
      _ssidCtrl.text = widget.service.checkpoints.first.ssid;
      _passCtrl.text = widget.service.checkpoints.first.pass;
    }
  }

  @override
  void dispose() {
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
                Tab(icon: Icon(Icons.wifi_rounded, size: 18), text: 'Wi-Fi Pairing'),
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
    return ListView(
      children: [
        // Instructions
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
              const Text('How to Pair via Wi-Fi:', style: TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Text(
                '1. Turn on Pin badge switch.\n2. Hold the BOOT button for 2s (Pin AP launches "SecureLink-Setup").\n3. Enter Wi-Fi credentials below to deploy OTA directly to the Pin.',
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
            hintText: 'e.g. PIN-001',
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
                    await widget.service.provisionPinWifiSetup(
                      pinId: _pinIdCtrl.text.trim(),
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
                          'Smart Pin ${_pinIdCtrl.text.toUpperCase()} paired to ${widget.service.userName}!',
                          style: const TextStyle(color: MobileDesignSystem.primaryGreenMint),
                        ),
                      ),
                    );
                  },
            icon: _isPairing
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                : const Icon(Icons.check_circle_rounded),
            label: Text(
              _isPairing ? 'Provisioning Pin & Syncing CS...' : 'Pair & Connect Pin (Wi-Fi)',
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
    return ListView(
      children: [
        Center(
          child: Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.12),
              border: Border.all(color: MobileDesignSystem.primaryGreenMint.withValues(alpha: 0.35)),
            ),
            child: const Icon(Icons.bluetooth_searching_rounded, color: MobileDesignSystem.primaryGreenMint, size: 36),
          ),
        ),
        const SizedBox(height: 10),
        const Center(
          child: Text(
            'Scanning for Nearby BLE Smart Pins...',
            style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(height: 16),

        // Discovered Devices list
        _bleDeviceTile('SECURELINK-PIN-001', -52, 'XIAO ESP32S3 • Armed Standby'),
        const SizedBox(height: 8),
        _bleDeviceTile('SECURELINK-PIN-002', -68, 'XIAO ESP32S3 • In Range'),
        const SizedBox(height: 14),

        TextField(
          controller: _aliasCtrl,
          style: const TextStyle(color: Colors.white, fontSize: 13.5),
          decoration: InputDecoration(
            labelText: 'Assign to Student / Teacher',
            labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.7), fontSize: 12),
            hintText: 'e.g. Student: Maria Santos',
            prefixIcon: const Icon(Icons.badge_rounded, color: MobileDesignSystem.primaryGreenMint, size: 18),
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
                    final pinId = _selectedBlePin.replaceAll('SECURELINK-', '');
                    await widget.service.pairPinViaBluetooth(
                      pinId: pinId,
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
                          'Pin $pinId paired via Bluetooth to ${widget.service.userName}!',
                          style: const TextStyle(color: MobileDesignSystem.primaryGreenMint),
                        ),
                      ),
                    );
                  },
            icon: _isPairing
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                : const Icon(Icons.bluetooth_connected_rounded),
            label: Text(
              _isPairing ? 'Pairing via BLE...' : 'Pair Selected Pin via Bluetooth',
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

  Widget _bleDeviceTile(String name, int rssi, String subtitle) {
    final isSelected = _selectedBlePin == name;
    return GestureDetector(
      onTap: () => setState(() => _selectedBlePin = name),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: isSelected ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.16) : Colors.white.withValues(alpha: 0.03),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: isSelected ? MobileDesignSystem.primaryGreenMint : Colors.white10,
            width: isSelected ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(Icons.memory_rounded, color: isSelected ? MobileDesignSystem.primaryGreenMint : Colors.white60, size: 24),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800)),
                  Text(subtitle, style: TextStyle(color: Colors.white.withValues(alpha: 0.55), fontSize: 10.5)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('$rssi dBm', style: const TextStyle(color: MobileDesignSystem.primaryGreenMint, fontSize: 10, fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );
  }
}
