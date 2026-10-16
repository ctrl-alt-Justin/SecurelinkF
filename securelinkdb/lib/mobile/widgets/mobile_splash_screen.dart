import 'dart:math';
import 'dart:ui';
import 'package:flutter/material.dart';

class _MobileSplashParticle {
  final double x;
  final double y;
  final double size;
  final double speedY;
  final double maxOpacity;
  final double phase;

  const _MobileSplashParticle({
    required this.x,
    required this.y,
    required this.size,
    required this.speedY,
    required this.maxOpacity,
    required this.phase,
  });
}

class _MobileSplashParticlesPainter extends CustomPainter {
  final List<_MobileSplashParticle> particles;
  final double elapsedSeconds;
  final Color color;

  const _MobileSplashParticlesPainter({
    required this.particles,
    required this.elapsedSeconds,
    required this.color,
  });

  @override
  void paint(Canvas canvas, Size size) {
    for (final p in particles) {
      final rawY = p.y - (elapsedSeconds * p.speedY);
      final currentY = rawY - rawY.floorToDouble();

      final rawX = p.x + (sin(elapsedSeconds * 0.6 + p.phase) * 0.02);
      final currentX = rawX - rawX.floorToDouble();

      final posX = currentX * size.width;
      final posY = currentY * size.height;

      final edgeFade = sin((currentY * pi).clamp(0.0, pi));
      final shimmer = (sin((elapsedSeconds * 1.6) + p.phase) + 1.0) / 2.0;
      final alpha =
          (p.maxOpacity * (0.35 + 0.65 * shimmer) * edgeFade).clamp(0.0, 1.0);

      final paint = Paint()..color = color.withValues(alpha: alpha);
      canvas.drawCircle(Offset(posX, posY), p.size, paint);
    }
  }

  @override
  bool shouldRepaint(_MobileSplashParticlesPainter oldDelegate) => true;
}

class _MobileAnimatedRingPainter extends CustomPainter {
  final double ringProgress;
  final Color brandGreen;

  const _MobileAnimatedRingPainter({
    required this.ringProgress,
    required this.brandGreen,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - 1.5;
    final rect = Rect.fromCircle(center: center, radius: radius);

    // Subtle track circle
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0
      ..color = brandGreen.withValues(alpha: 0.12);
    canvas.drawCircle(center, radius, trackPaint);

    double sweepAngle = 0.0;
    double opacity = 1.0;
    double pulse = 0.0;

    if (ringProgress <= 0.70) {
      // Counter-clockwise sweep
      final t = (ringProgress / 0.70).clamp(0.0, 1.0);
      final curvedT = Curves.easeInOutCubic.transform(t);
      sweepAngle = -2 * pi * curvedT;
      opacity = 1.0;
      pulse = 0.0;
    } else if (ringProgress <= 0.88) {
      // Pulse & bloom when circle completes
      sweepAngle = -2 * pi;
      final t = ((ringProgress - 0.70) / 0.18).clamp(0.0, 1.0);
      pulse = sin(t * pi);
      opacity = 1.0;
    } else {
      sweepAngle = -2 * pi;
      final t = ((ringProgress - 0.88) / 0.12).clamp(0.0, 1.0);
      opacity = (1.0 - t).clamp(0.0, 1.0);
      pulse = 0.0;
    }

    if (opacity > 0.005 && sweepAngle.abs() > 0.005) {
      if (pulse > 0.05) {
        final glowPaint = Paint()
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = 2.5 + (pulse * 4.5)
          ..color = brandGreen.withValues(alpha: 0.40 * pulse * opacity);
        canvas.drawArc(rect, -pi / 2, sweepAngle, false, glowPaint);
      }

      final activeColor = Color.lerp(
        brandGreen,
        const Color(0xFFD8FFF4),
        pulse * 0.65,
      )!;

      final activePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 1.3 + (pulse * 1.5)
        ..color = activeColor.withValues(alpha: opacity);

      canvas.drawArc(rect, -pi / 2, sweepAngle, false, activePaint);
    }
  }

  @override
  bool shouldRepaint(_MobileAnimatedRingPainter oldDelegate) => true;
}

/// A sleek, atmospheric 1.5s splash screen for SecureLink Mobile matching
/// the desktop aesthetic with an animated glowing counter-clockwise ring,
/// floating particles, and brand typography.
class MobileSplashScreen extends StatefulWidget {
  const MobileSplashScreen({super.key});

  @override
  State<MobileSplashScreen> createState() => _MobileSplashScreenState();
}

class _MobileSplashScreenState extends State<MobileSplashScreen>
    with TickerProviderStateMixin {
  late final AnimationController _breatheController;
  late final AnimationController _ringController;
  late final List<_MobileSplashParticle> _particles;
  late final DateTime _startTime;

  @override
  void initState() {
    super.initState();
    _startTime = DateTime.now();

    // Gentle ambient breathing glow (3s duration)
    _breatheController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 3000),
    )..repeat();

    // Fast-acting ring sweep tuned for the 1.5s mobile screen window
    _ringController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    )..forward();

    final rng = Random(42);
    _particles = List.generate(28, (i) {
      return _MobileSplashParticle(
        x: rng.nextDouble(),
        y: rng.nextDouble(),
        size: 1.0 + rng.nextDouble() * 2.0,
        speedY: 0.025 + rng.nextDouble() * 0.045,
        maxOpacity: 0.20 + rng.nextDouble() * 0.35,
        phase: rng.nextDouble() * 2 * pi,
      );
    });
  }

  @override
  void dispose() {
    _breatheController.dispose();
    _ringController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const Color brandGreen = Color(0xFF55E2C0);
    const Color brandGreenDark = Color(0xFF10B981);
    const Color cardBg = Color(0xFF06140E);

    return Material(
      color: Colors.transparent,
      child: AnimatedBuilder(
        animation: Listenable.merge([_breatheController, _ringController]),
        builder: (context, _) {
          final progress = _breatheController.value;
          final ringProgress = _ringController.value;

          final breathe = (sin(progress * 2 * pi) + 1.0) / 2.0;
          final elapsedSeconds =
              DateTime.now().difference(_startTime).inMilliseconds / 1000.0;

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
                // Floating subtle green particle field
                Positioned.fill(
                  child: CustomPaint(
                    painter: _MobileSplashParticlesPainter(
                      particles: _particles,
                      elapsedSeconds: elapsedSeconds,
                      color: brandGreen,
                    ),
                  ),
                ),

                // Ambient glowing radial halo
                Container(
                  width: 280 + (breathe * 40),
                  height: 280 + (breathe * 40),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        brandGreen.withValues(alpha: 0.05 + (breathe * 0.04)),
                        brandGreenDark.withValues(alpha: 0.015 + (breathe * 0.015)),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),

                // Center Content: Round Animated Card with Shield + SecureLink Brand Name
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Round Animated Card with Counter-Clockwise Glowing Ring
                    SizedBox(
                      width: 160,
                      height: 160,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          // Frosted Glass Round Enclosure
                          ClipOval(
                            child: BackdropFilter(
                              filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
                              child: Container(
                                width: 160,
                                height: 160,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: cardBg.withValues(alpha: 0.90),
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(alpha: 0.65),
                                      blurRadius: 32,
                                      offset: const Offset(0, 14),
                                    ),
                                    BoxShadow(
                                      color: brandGreen.withValues(
                                          alpha: 0.05 + (breathe * 0.04)),
                                      blurRadius: 24,
                                      spreadRadius: -2,
                                    ),
                                  ],
                                ),
                                alignment: Alignment.center,
                                // Gradient Logo Icon in Center
                                child: Container(
                                  width: 58,
                                  height: 58,
                                  decoration: BoxDecoration(
                                    borderRadius: BorderRadius.circular(18),
                                    gradient: const LinearGradient(
                                      colors: [brandGreen, brandGreenDark],
                                      begin: Alignment.topLeft,
                                      end: Alignment.bottomRight,
                                    ),
                                    boxShadow: [
                                      BoxShadow(
                                        color: brandGreen.withValues(
                                            alpha: 0.32 + (breathe * 0.18)),
                                        blurRadius: 18 + (breathe * 6),
                                        spreadRadius: 2,
                                      ),
                                    ],
                                  ),
                                  child: const Icon(
                                    Icons.shield_rounded,
                                    size: 32,
                                    color: Colors.white,
                                  ),
                                ),
                              ),
                            ),
                          ),

                          // Animated Glowing Ring Border
                          Positioned.fill(
                            child: CustomPaint(
                              painter: _MobileAnimatedRingPainter(
                                ringProgress: ringProgress,
                                brandGreen: brandGreen,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 24),

                    // Application Name "SecureLink"
                    const Text(
                      'SECURELINK',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 2.8,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'CAMPUS SENTINEL',
                      style: TextStyle(
                        fontSize: 9.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.6,
                        color: brandGreen,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
