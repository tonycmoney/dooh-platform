import 'package:flutter/material.dart';

import '../controller.dart';
import '../device.dart';
import 'setup_status.dart';

class PairingScreen extends StatelessWidget {
  const PairingScreen({
    super.key,
    required this.controller,
    required this.onOpenSettings,
  });

  final PlayerController controller;
  final VoidCallback onOpenSettings;

  @override
  Widget build(BuildContext context) {
    // On a kiosk tablet the manual setup and the visible settings button are
    // hidden: the corner pattern opens the panel instead.
    return FutureBuilder<KioskStatus>(
      future: DeviceBridge.kioskStatus(),
      builder: (context, snap) =>
          _build(context, kiosk: snap.data?.deviceOwner ?? true),
    );
  }

  Widget _build(BuildContext context, {required bool kiosk}) {
    final code = controller.pairingCode;
    return Scaffold(
      backgroundColor: const Color(0xFF0F1115),
      body: SafeArea(
        child: Stack(
          children: [
            Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(32),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'Pair this screen',
                      style: TextStyle(color: Colors.white70, fontSize: 28),
                    ),
                    const SizedBox(height: 24),
                    if (code == null)
                      const SizedBox(
                        height: 120,
                        child: Center(child: CircularProgressIndicator()),
                      )
                    else
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 40,
                          vertical: 16,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          child: Text(
                            code,
                            style: const TextStyle(
                              fontSize: 110,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 18,
                              fontFamily: 'monospace',
                              color: Colors.black,
                            ),
                          ),
                        ),
                      ),
                    const SizedBox(height: 24),
                    const Text(
                      'In the dashboard, open Screens → Pair new screen and enter this code.',
                      style: TextStyle(color: Colors.white60, fontSize: 20),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    if (controller.lastError != null)
                      Text(
                        controller.lastError!,
                        style: const TextStyle(
                          color: Colors.redAccent,
                          fontSize: 16,
                        ),
                      ),
                    if (!kiosk) ...[
                      const SizedBox(height: 32),
                      const SetupStatus(),
                    ],
                    const SizedBox(height: 16),
                    Text(
                      'Device ${controller.deviceUid} · v${controller.appVersion} · ${controller.store.serverUrl}',
                      style: const TextStyle(
                        color: Colors.white30,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (!kiosk)
              Positioned(
                top: 8,
                right: 8,
                child: IconButton(
                  icon: const Icon(Icons.settings, color: Colors.white38),
                  tooltip: 'Settings',
                  onPressed: onOpenSettings,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
