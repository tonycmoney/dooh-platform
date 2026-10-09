import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'src/content_cache.dart';
import 'src/controller.dart';
import 'src/play_log.dart';
import 'src/store.dart';
import 'src/ui/pairing_screen.dart';
import 'src/ui/player_view.dart';
import 'src/ui/settings_panel.dart';

Future<void> main() async {
  // Errors in Dart code are logged and playback continues; native crashes are
  // handled by PlayerApplication.kt, which relaunches the app.
  runZonedGuarded(() async {
    WidgetsFlutterBinding.ensureInitialized();
    FlutterError.onError = (details) => FlutterError.presentError(details);
    ErrorWidget.builder = (_) => const ColoredBox(color: Colors.black);

    await SystemChrome.setPreferredOrientations([
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);

    final controller = PlayerController(
      store: await Store.open(),
      cache: await ContentCache.open(),
      playLog: await PlayLog.open(),
    );
    runApp(PlayerApp(controller: controller));
    await controller.start();
  }, (error, stack) => debugPrint('Uncaught: $error\n$stack'));
}

class PlayerApp extends StatelessWidget {
  const PlayerApp({super.key, required this.controller});

  final PlayerController controller;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'DOOH Player',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue, brightness: Brightness.dark)),
      home: Scaffold(backgroundColor: Colors.black, body: _Root(controller: controller)),
    );
  }
}

class _Root extends StatefulWidget {
  const _Root({required this.controller});

  final PlayerController controller;

  @override
  State<_Root> createState() => _RootState();
}

class _RootState extends State<_Root> {
  bool _settingsOpen = false;
  final List<DateTime> _cornerTaps = [];

  void _onCornerTap() {
    final now = DateTime.now();
    _cornerTaps
      ..add(now)
      ..removeWhere((t) => now.difference(t) > const Duration(seconds: 3));
    if (_cornerTaps.length >= 5) {
      _cornerTaps.clear();
      setState(() => _settingsOpen = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false, // the Back button never leaves the player
      onPopInvokedWithResult: (didPop, _) {
        if (_settingsOpen) setState(() => _settingsOpen = false);
      },
      child: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final c = widget.controller;
          final Widget body = switch (c.phase) {
            Phase.starting => const ColoredBox(color: Colors.black),
            Phase.pairing => PairingScreen(controller: c, onOpenSettings: () => setState(() => _settingsOpen = true)),
            Phase.playing => PlayerView(controller: c),
          };
          return Stack(
            fit: StackFit.expand,
            children: [
              body,
              if (c.phase == Phase.playing)
                Positioned(
                  left: 0,
                  top: 0,
                  width: 120,
                  height: 120,
                  child: GestureDetector(behavior: HitTestBehavior.translucent, onTap: _onCornerTap),
                ),
              if (c.phase == Phase.playing && c.lastError != null)
                const Positioned(
                  right: 10,
                  bottom: 10,
                  child: Icon(Icons.cloud_off, color: Colors.white24, size: 18),
                ),
              if (_settingsOpen) SettingsPanel(controller: c, onClose: () => setState(() => _settingsOpen = false)),
            ],
          );
        },
      ),
    );
  }
}
