import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'models/device_model.dart';
import 'services/mobile_server_service.dart';
import 'screens/pins_overview_screen.dart';
import 'screens/incidents_screen.dart';
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
      title: 'SecureLink Companion',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: MobileDesignSystem.bgDark, // 0xFF070A12
        colorScheme: const ColorScheme.dark(
          primary: MobileDesignSystem.primaryGreen, // 0xFF109C6D
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
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(
                  children: [
                    // Official SecureLink Logo
                    const MobileSecureLinkLogo(size: 34),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            'SecureLink Companion',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w900,
                              color: Colors.white,
                              letterSpacing: -0.3,
                            ),
                            overflow: TextOverflow.ellipsis,
                            maxLines: 1,
                          ),
                          Text(
                            'Smart Wearable Safety Sentinel',
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
                          ? 'Harmful Words Filter: ON (Alerts on flagged words only)'
                          : 'Harmful Words Filter: OFF (Receiving all transcripts)',
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
                                _serverService.harmfulWordsOnly ? 'FLAGGED' : 'ALL',
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

                    // Live Central System Status Indicator
                    GestureDetector(
                      onTap: () {
                        showModalBottomSheet(
                          context: context,
                          isScrollControlled: true,
                          backgroundColor: const Color(0xFF0E151A),
                          shape: const RoundedRectangleBorder(
                            borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
                          ),
                          builder: (ctx) => ServerHostModal(service: _serverService),
                        );
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                        decoration: BoxDecoration(
                          color: _serverService.isConnected
                              ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.16)
                              : MobileDesignSystem.statusWarning.withValues(alpha: 0.14),
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: _serverService.isConnected
                                ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.45)
                                : MobileDesignSystem.statusWarning.withValues(alpha: 0.40),
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
                              _serverService.isConnected ? 'CS LIVE' : 'SYNC CS',
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
                Color(0xFF0E1C15), // Deep emerald glow
                Color(0xFF070A12), // Deep obsidian background
              ],
            ),
          ),
          child: Column(
            children: [
              // Urgent Alert Banner (shown when a critical/flagged incident arrives)
              if (_serverService.latestAlert != null)
                _buildUrgentAlertBanner(_serverService.latestAlert!),

              Expanded(
                child: IndexedStack(
                  index: _currentIndex,
                  children: [
                    PinsOverviewScreen(
                      service: _serverService,
                      onDeployCheckpoint: _handleDeployCheckpoint,
                    ),
                    IncidentsScreen(service: _serverService),
                    BatteryTrackerScreen(service: _serverService),
                    WifiConfigScreen(service: _serverService),
                  ],
                ),
              ),
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
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _navButton(
                    index: 0,
                    icon: Icons.sensors_rounded,
                    label: 'Pins',
                    badgeCount: _serverService.pairedDevices.isNotEmpty
                        ? _serverService.pairedDevices.length
                        : null,
                  ),
                  _navButton(
                    index: 1,
                    icon: Icons.warning_amber_rounded,
                    label: 'Incidents',
                    badgeCount: _serverService.importantIncidents.isNotEmpty
                        ? _serverService.importantIncidents.length
                        : null,
                    hasAlert: _serverService.importantIncidents.any((i) => i.isThreat || i.isDanger),
                  ),
                  _navButton(
                    index: 2,
                    icon: Icons.battery_charging_full_rounded,
                    label: 'Battery',
                    hasAlert: _serverService.lowBatteryCount > 0,
                  ),
                  _navButton(
                    index: 3,
                    icon: Icons.wifi_tethering_rounded,
                    label: 'Wi-Fi',
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
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
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

  Widget _buildUrgentAlertBanner(IncidentReport alert) {
    final alertColor = alert.isDanger
        ? MobileDesignSystem.statusDanger
        : MobileDesignSystem.statusThreat;
    final alias = _serverService.getPinAlias(alert.deviceId);

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: alertColor.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: alertColor.withValues(alpha: 0.45), width: 1.2),
        boxShadow: [
          BoxShadow(
            color: alertColor.withValues(alpha: 0.20),
            blurRadius: 14,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: alertColor.withValues(alpha: 0.25),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.warning_amber_rounded, color: alertColor, size: 22),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: InkWell(
              onTap: () {
                setState(() => _currentIndex = 1); // Switch to Incidents tab
                _serverService.clearLatestAlert();
              },
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Text(
                        'SAFETY ALERT • ${alert.flagType.toUpperCase()}',
                        style: TextStyle(
                          color: alertColor,
                          fontSize: 10.5,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 0.5,
                        ),
                      ),
                      const Spacer(),
                      Text(
                        alias != null ? '$alias (${alert.deviceId})' : alert.deviceId,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text(
                    alert.transcript.isNotEmpty ? '"${alert.transcript}"' : 'Suspicious audio activity detected',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 6),
          IconButton(
            onPressed: () => _serverService.clearLatestAlert(),
            icon: const Icon(Icons.close_rounded, size: 18, color: Colors.white60),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
          ),
        ],
      ),
    );
  }
}
