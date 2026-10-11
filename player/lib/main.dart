import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'src/content_cache.dart';
import 'src/controller.dart';
import 'src/play_log.dart';
import 'src/store.dart';
import 'src/device.dart';
import 'src/ui/maintenance_gate.dart';
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

    // Portrait only; never rotates, even if the tablet is turned.
    await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
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
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.blue,
          brightness: Brightness.dark,
        ),
      ),
      home: Scaffold(
        backgroundColor: Colors.black,
        body: _Root(controller: controller),
      ),
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
  bool _pinOpen = false;

  /// After the secret corner pattern: ask for the dashboard's PIN, or open
  /// straight away if none has been set yet (e.g. a tablet being set up).
  void _requestSettings() {
    final hasPin = widget.controller.store.maintenancePin != null;
    setState(() => hasPin ? _pinOpen = true : _settingsOpen = true);
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false, // the Back button never leaves the player
      onPopInvokedWithResult: (didPop, _) {
        if (_settingsOpen || _pinOpen) {
          setState(() => _settingsOpen = _pinOpen = false);
        }
      },
      child: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final c = widget.controller;
          final Widget body = switch (c.phase) {
            Phase.starting => const ColoredBox(color: Colors.black),
            Phase.pairing => PairingScreen(
              controller: c,
              onOpenSettings: _requestSettings,
            ),
            Phase.playing => PlayerView(controller: c),
          };
          return Stack(
            fit: StackFit.expand,
            children: [
              body,
              if (!_settingsOpen && !_pinOpen)
                CornerTapZones(onPattern: _requestSettings),
              if (c.phase == Phase.playing && c.lastError != null)
                const Positioned(
                  right: 10,
                  bottom: 10,
                  child: Icon(Icons.cloud_off, color: Colors.white24, size: 18),
                ),
              if (_pinOpen)
                PinPad(
                  lockedUntil: c.store.pinLockedUntil,
                  onLockout: (until) => c.store.pinLockedUntil = until,
                  verify: (pin) async {
                    final hash = c.store.maintenancePin;
                    return hash != null &&
                        await DeviceBridge.verifyPin(pin, hash);
                  },
                  onSuccess: () => setState(() {
                    _pinOpen = false;
                    _settingsOpen = true;
                  }),
                  onCancel: () => setState(() => _pinOpen = false),
                ),
              if (_settingsOpen)
                SettingsPanel(
                  controller: c,
                  onClose: () => setState(() => _settingsOpen = false),
                ),
            ],
          );
        },
      ),
    );
  }
}
