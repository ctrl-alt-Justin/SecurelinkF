import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'models/device_model.dart';
import 'services/mobile_server_service.dart';
import 'screens/pins_overview_screen.dart';
import 'screens/battery_tracker_screen.dart';
import 'screens/wifi_config_screen.dart';
import 'widgets/mobile_components.dart';
import 'widgets/mobile_splash_screen.dart';

class SecureLinkMobileApp extends StatefulWidget {
  final String? initialHost;
  final int? initialPort;

  const SecureLinkMobileApp({
    super.key,
    this.initialHost,
    this.initialPort,
  });

  @override
  State<SecureLinkMobileApp> createState() => _SecureLinkMobileAppState();
}

class _SecureLinkMobileAppState extends State<SecureLinkMobileApp> {
  final MobileServerService _serverService = MobileServerService();
  int _currentIndex = 0;
  bool _showSplash = true;
  double _splashOpacity = 1.0;

  @override
  void initState() {
    super.initState();
    if (widget.initialHost != null) {
      _serverService.updateHost(widget.initialHost!, widget.initialPort);
    } else {
      _serverService.connect();
    }
    _serverService.addListener(_onServiceChanged);

    // 1.5 second splash display, then smooth 300ms fade transition
    Future.delayed(const Duration(milliseconds: 1500), () {
      if (mounted) {
        setState(() => _splashOpacity = 0.0);
        Future.delayed(const Duration(milliseconds: 300), () {
          if (mounted) {
            setState(() => _showSplash = false);
          }
        });
      }
    });
  }

  @override
  void dispose() {
    _serverService.removeListener(_onServiceChanged);
    super.dispose();
  }

  void _onServiceChanged() {
    if (mounted) setState(() {});
  }

  void _handleDeployCheckpoint(WifiCheckpoint chk, String target) {
    _serverService.deployCheckpoint(chk, target: target);
  }

  @override
  Widget build(BuildContext context) {
    SystemChrome.setSystemUIOverlayStyle(
      const SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: Brightness.light,
        systemNavigationBarColor: Color(0xFF070A12),
        systemNavigationBarIconBrightness: Brightness.light,
      ),
    );

    return MaterialApp(
      title: 'SecureLink Mobile',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: MobileDesignSystem.bgDark, // 0xFF070A12 (same as desktop)
        colorScheme: const ColorScheme.dark(
          primary: MobileDesignSystem.primaryGreen, // 0xFF109C6D (desktop brand green)
          secondary: MobileDesignSystem.primaryGreenMint, // 0xFF55E2C0
          surface: MobileDesignSystem.surface1,
        ),
        fontFamily: 'Segoe UI',
        useMaterial3: true,
      ),
      home: Stack(
        children: [
          Scaffold(
        appBar: PreferredSize(
          preferredSize: const Size.fromHeight(66),
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xFF0A0F14),
              border: Border(
                bottom: BorderSide(
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.18),
                  width: 1,
                ),
              ),
            ),
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Row(
                  children: [
                    // Brand Shield Icon with Desktop Green Gradient
                    Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [
                            MobileDesignSystem.primaryGreen,
                            MobileDesignSystem.primaryGreenMint,
                          ],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        borderRadius: BorderRadius.circular(10),
                        boxShadow: [
                          BoxShadow(
                            color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.35),
                            blurRadius: 10,
                            offset: const Offset(0, 2),
                          ),
                        ],
                      ),
                      child: const Icon(
                        Icons.shield_rounded,
                        color: Colors.white,
                        size: 19,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            'SecureLink',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w900,
                              color: Colors.white,
                              letterSpacing: -0.3,
                            ),
                            overflow: TextOverflow.ellipsis,
                            maxLines: 1,
                          ),
                          Text(
                            'Smart Safety Wearables',
                            style: TextStyle(
                              fontSize: 9.5,
                              color: MobileDesignSystem.primaryGreenMint,
                              fontWeight: FontWeight.w600,
                            ),
                            overflow: TextOverflow.ellipsis,
                            maxLines: 1,
                          ),
                        ],
                      ),
                    ),

                    // Harmful Words Filter Toggle Button
                    Tooltip(
                      message: _serverService.harmfulWordsOnly
                          ? 'Harmful Words Filter: ON (Ignoring normal speech)'
                          : 'Harmful Words Filter: OFF (Logging all speech)',
                      child: GestureDetector(
                        onTap: () {
                          _serverService.toggleHarmfulWordsOnly();
                        },
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 5),
                          decoration: BoxDecoration(
                            color: _serverService.harmfulWordsOnly
                                ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.22)
                                : Colors.white.withValues(alpha: 0.05),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: _serverService.harmfulWordsOnly
                                  ? MobileDesignSystem.primaryGreenMint
                                  : Colors.white.withValues(alpha: 0.12),
                              width: _serverService.harmfulWordsOnly ? 1.2 : 1.0,
                            ),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                _serverService.harmfulWordsOnly
                                    ? Icons.shield_rounded
                                    : Icons.shield_outlined,
                                size: 13,
                                color: _serverService.harmfulWordsOnly
                                    ? MobileDesignSystem.primaryGreenMint
                                    : Colors.white60,
                              ),
                              const SizedBox(width: 4),
                              Text(
                                _serverService.harmfulWordsOnly ? 'HARMFUL' : 'ALL',
                                style: TextStyle(
                                  fontSize: 8.5,
                                  fontWeight: FontWeight.w900,
                                  letterSpacing: 0.3,
                                  color: _serverService.harmfulWordsOnly
                                      ? MobileDesignSystem.primaryGreenMint
                                      : Colors.white60,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 5),

                    // Pair Pin Action
                    IconButton(
                      tooltip: 'Pair Smart Pin',
                      padding: EdgeInsets.zero,
                      constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                      onPressed: () {
                        showModalBottomSheet(
                          context: context,
                          isScrollControlled: true,
                          backgroundColor: const Color(0xFF0E151A),
                          shape: const RoundedRectangleBorder(
                            borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
                          ),
                          builder: (ctx) => PairPinModal(
                            service: _serverService,
                            onPaired: () => setState(() {}),
                          ),
                        );
                      },
                      icon: const Icon(Icons.add_link_rounded, color: MobileDesignSystem.primaryGreenMint, size: 20),
                    ),
                    const SizedBox(width: 5),

                    // Live Server Status Indicator (Desktop Emerald Pill)
                    GestureDetector(
                      onTap: () {
                        showModalBottomSheet(
                          context: context,
                          isScrollControlled: true,
                          backgroundColor: const Color(0xFF0E151A),
                          shape: const RoundedRectangleBorder(
                            borderRadius:
                                BorderRadius.vertical(top: Radius.circular(26)),
                          ),
                          builder: (ctx) =>
                              ServerHostModal(service: _serverService),
                        );
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 5),
                        decoration: BoxDecoration(
                          color: _serverService.isConnected
                              ? MobileDesignSystem.primaryGreen
                                  .withValues(alpha: 0.16)
                              : MobileDesignSystem.statusWarning
                                  .withValues(alpha: 0.14),
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: _serverService.isConnected
                                ? MobileDesignSystem.primaryGreen
                                    .withValues(alpha: 0.45)
                                : MobileDesignSystem.statusWarning
                                    .withValues(alpha: 0.40),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 6,
                              height: 6,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: _serverService.isConnected
                                    ? MobileDesignSystem.primaryGreen
                                    : MobileDesignSystem.statusWarning,
                              ),
                            ),
                            const SizedBox(width: 4),
                            Text(
                              _serverService.isConnected
                                  ? 'CS LIVE'
                                  : 'OFFLINE',
                              style: TextStyle(
                                fontSize: 8.5,
                                fontWeight: FontWeight.w800,
                                letterSpacing: 0.5,
                                color: _serverService.isConnected
                                    ? MobileDesignSystem.primaryGreenMint
                                    : MobileDesignSystem.statusWarning,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        body: Container(
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(0, -0.6),
              radius: 1.15,
              colors: [
                Color(0xFF0E1C15), // Deep emerald glow matching desktop
                Color(0xFF070A12), // Deep obsidian background
              ],
            ),
          ),
          child: IndexedStack(
            index: _currentIndex,
            children: [
              PinsOverviewScreen(
                service: _serverService,
                onDeployCheckpoint: _handleDeployCheckpoint,
              ),
              BatteryTrackerScreen(service: _serverService),
              WifiConfigScreen(service: _serverService),
            ],
          ),
        ),
        bottomNavigationBar: Container(
          decoration: BoxDecoration(
            color: const Color(0xFF0A0F14),
            border: Border(
              top: BorderSide(
                color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.16),
                width: 1,
              ),
            ),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _navButton(
                    index: 0,
                    icon: Icons.sensors_rounded,
                    label: 'Pins Overview',
                    badgeCount: _serverService.devices.isNotEmpty
                        ? _serverService.devices.length
                        : null,
                  ),
                  _navButton(
                    index: 1,
                    icon: Icons.battery_charging_full_rounded,
                    label: 'Battery Life',
                    hasAlert: _serverService.lowBatteryCount > 0,
                  ),
                  _navButton(
                    index: 2,
                    icon: Icons.wifi_tethering_rounded,
                    label: 'Wi-Fi Config',
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
      if (_showSplash)
          Positioned.fill(
            child: AnimatedOpacity(
              opacity: _splashOpacity,
              duration: const Duration(milliseconds: 300),
              curve: Curves.easeOut,
              child: const MobileSplashScreen(),
            ),
          ),
      ],
    ),
  );
}

  Widget _navButton({
    required int index,
    required IconData icon,
    required String label,
    int? badgeCount,
    bool hasAlert = false,
  }) {
    final active = _currentIndex == index;
    return GestureDetector(
      onTap: () => setState(() => _currentIndex = index),
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
        decoration: BoxDecoration(
          color: active
              ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.16)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          border: active
              ? Border.all(
                  color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.35),
                  width: 1,
                )
              : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Stack(
              clipBehavior: Clip.none,
              children: [
                Icon(
                  icon,
                  size: 22,
                  color: active
                      ? MobileDesignSystem.primaryGreenMint
                      : Colors.white54,
                ),
                if (hasAlert)
                  Positioned(
                    right: -4,
                    top: -2,
                    child: Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: MobileDesignSystem.statusDanger,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                if (badgeCount != null && badgeCount > 0 && !hasAlert)
                  Positioned(
                    right: -8,
                    top: -4,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 4, vertical: 1),
                      decoration: BoxDecoration(
                        color: active
                            ? MobileDesignSystem.primaryGreen
                            : Colors.white24,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '$badgeCount',
                        style: const TextStyle(
                          fontSize: 8.5,
                          fontWeight: FontWeight.w900,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              label,
              style: TextStyle(
                fontSize: 10.5,
                fontWeight: active ? FontWeight.w800 : FontWeight.w600,
                color: active
                    ? MobileDesignSystem.primaryGreenMint
                    : Colors.white54,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
