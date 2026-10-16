import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'mobile/securelink_mobile_app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // If previewing on desktop, set a realistic mobile phone window dimension
  if (!kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS)) {
    try {
      await windowManager.ensureInitialized();
      const options = WindowOptions(
        size: Size(440, 880),
        minimumSize: Size(380, 640),
        center: true,
        backgroundColor: Color(0xFF090C14),
        skipTaskbar: false,
        title: 'SecureLink Companion',
      );

      await windowManager.waitUntilReadyToShow(options, () async {
        await windowManager.show();
        await windowManager.focus();
      });
    } catch (_) {}
  }

  runApp(const SecureLinkMobileApp());
}
