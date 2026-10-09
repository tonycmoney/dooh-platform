import 'package:flutter/material.dart';

import '../device.dart';

/// One-time tablet setup that Android 10+ requires before an app may start
/// itself after a reboot or crash.
class SetupStatus extends StatefulWidget {
  const SetupStatus({super.key});

  @override
  State<SetupStatus> createState() => _SetupStatusState();
}

class _SetupStatusState extends State<SetupStatus> with WidgetsBindingObserver {
  bool? _overlay;
  bool? _home;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh(); // back from Settings
  }

  Future<void> _refresh() async {
    final overlay = await DeviceBridge.canStartFromBackground();
    final home = await DeviceBridge.isDefaultHome();
    if (!mounted) return;
    setState(() {
      _overlay = overlay;
      _home = home;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_overlay == null) return const SizedBox.shrink();
    if (_overlay! && _home!) {
      return const Text('✓ Auto-start and crash restart are set up',
          style: TextStyle(color: Colors.greenAccent, fontSize: 16));
    }
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.white24),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('One-time setup for unattended use',
              style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          _row(
            done: _overlay!,
            label: 'Allow "Display over other apps" (auto-start after reboot or crash)',
            action: 'Open setting',
            onTap: DeviceBridge.openOverlaySettings,
          ),
          _row(
            done: _home!,
            label: 'Make DOOH Player the default Home app',
            action: 'Set as Home',
            onTap: DeviceBridge.requestDefaultHome,
          ),
        ],
      ),
    );
  }

  Widget _row({required bool done, required String label, required String action, required VoidCallback onTap}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(done ? Icons.check_circle : Icons.radio_button_unchecked,
              color: done ? Colors.greenAccent : Colors.white54, size: 20),
          const SizedBox(width: 8),
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 15)),
          const SizedBox(width: 12),
          if (!done) OutlinedButton(onPressed: onTap, child: Text(action)),
        ],
      ),
    );
  }
}
