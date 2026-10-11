import 'dart:async';

import 'package:flutter/material.dart';

import '../controller.dart';
import '../device.dart';
import 'setup_status.dart';

/// Hidden technician panel: tap the four corners clockwise from top-left,
/// then enter the dashboard's maintenance PIN. Closes itself after a few
/// idle minutes so a forgotten panel never covers the ads.
class SettingsPanel extends StatefulWidget {
  const SettingsPanel({
    super.key,
    required this.controller,
    required this.onClose,
  });

  final PlayerController controller;
  final VoidCallback onClose;

  @override
  State<SettingsPanel> createState() => _SettingsPanelState();
}

class _SettingsPanelState extends State<SettingsPanel> {
  late final TextEditingController _url = TextEditingController(
    text: widget.controller.store.serverUrl,
  );
  int? _cacheBytes;
  Timer? _idle;

  static const idleTimeout = Duration(minutes: 3);

  @override
  void initState() {
    super.initState();
    widget.controller.cache.sizeOnDisk().then((b) {
      if (mounted) setState(() => _cacheBytes = b);
    });
    _touch();
  }

  void _touch() {
    _idle?.cancel();
    _idle = Timer(idleTimeout, widget.onClose);
  }

  @override
  void dispose() {
    _idle?.cancel();
    _url.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final manifest = c.cache.current.value;
    final rows = <(String, String)>[
      ('Screen', '${c.store.screenName ?? '—'} @ ${c.store.venueName ?? '—'}'),
      ('Device ID', c.deviceUid),
      ('App version', c.appVersion),
      (
        'Loop',
        manifest.loopName == null
            ? 'None'
            : '${manifest.loopName} (${manifest.items.length} items)',
      ),
      ('Now playing', c.nowPlaying?.title ?? '—'),
      (
        'Last server contact',
        c.lastContactAt?.toLocal().toString().split('.').first ?? 'never',
      ),
      ('Status', c.lastError ?? 'OK'),
      ('Plays waiting to upload', '${c.playLog.pendingCount}'),
      (
        'Cached media',
        _cacheBytes == null
            ? '…'
            : '${(_cacheBytes! / 1048576).toStringAsFixed(1)} MB',
      ),
    ];

    return Listener(
      onPointerDown: (_) => _touch(),
      child: Material(
        color: Colors.black.withValues(alpha: 0.92),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: DefaultTextStyle(
              style: const TextStyle(color: Colors.white, fontSize: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Text(
                        'Player settings',
                        style: TextStyle(
                          fontSize: 26,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const Spacer(),
                      FilledButton(
                        onPressed: widget.onClose,
                        child: const Text('Back to playing'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  for (final (label, value) in rows)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Row(
                        children: [
                          SizedBox(
                            width: 220,
                            child: Text(
                              label,
                              style: const TextStyle(color: Colors.white54),
                            ),
                          ),
                          Expanded(child: Text(value)),
                        ],
                      ),
                    ),
                  const SizedBox(height: 24),
                  const Text(
                    'Server URL',
                    style: TextStyle(color: Colors.white54),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _url,
                          style: const TextStyle(color: Colors.white),
                          keyboardType: TextInputType.url,
                          decoration: const InputDecoration(
                            border: OutlineInputBorder(),
                            helperText: 'Over USB with adb reverse: http://127.0.0.1:8000',
                            helperStyle: TextStyle(color: Colors.white38),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () {
                          c.setServerUrl(_url.text.trim());
                          ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                            const SnackBar(content: Text('Server URL saved')),
                          );
                        },
                        child: const Text('Save'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  KioskSection(onLeave: widget.onClose),
                  const SizedBox(height: 24),
                  TextButton(
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.redAccent,
                    ),
                    onPressed: () async {
                      final ok = await showDialog<bool>(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          title: const Text('Unpair this tablet?'),
                          content: const Text(
                            'It will stop playing, delete cached content and show a new pairing code.',
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, false),
                              child: const Text('Cancel'),
                            ),
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, true),
                              child: const Text('Unpair'),
                            ),
                          ],
                        ),
                      );
                      if (ok == true) {
                        await c.unpairLocally();
                        widget.onClose();
                      }
                    },
                    child: const Text('Unpair this tablet'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Kiosk status and the ways out of it, for technicians.
class KioskSection extends StatefulWidget {
  const KioskSection({super.key, required this.onLeave});

  final VoidCallback onLeave;

  @override
  State<KioskSection> createState() => _KioskSectionState();
}

class _KioskSectionState extends State<KioskSection> {
  KioskStatus? _status;

  static const maintenanceMinutes = 15;

  @override
  void initState() {
    super.initState();
    DeviceBridge.kioskStatus().then((s) {
      if (mounted) setState(() => _status = s);
    });
  }

  Future<bool> _confirm(String title, String body, String action) async =>
      await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(action),
            ),
          ],
        ),
      ) ==
      true;

  @override
  Widget build(BuildContext context) {
    final s = _status;
    if (s == null) return const SizedBox.shrink();
    if (!s.deviceOwner) {
      // Not provisioned as a kiosk: fall back to the manual setup.
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Kiosk mode is not set up on this tablet (run scripts/provision_tablet.sh).',
            style: TextStyle(color: Colors.orangeAccent),
          ),
          const SizedBox(height: 12),
          const SetupStatus(),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          s.maintenance
              ? 'Maintenance mode: kiosk is paused'
              : '✓ Kiosk mode is on (locked: ${s.locked ? 'yes' : 'no'})',
          style: TextStyle(
            color: s.maintenance ? Colors.orangeAccent : Colors.greenAccent,
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            if (!s.maintenance)
              OutlinedButton(
                onPressed: () async {
                  await DeviceBridge.startMaintenance(maintenanceMinutes);
                  widget.onLeave();
                },
                child: const Text(
                  'Exit kiosk for $maintenanceMinutes min (open Android Settings)',
                ),
              )
            else
              FilledButton(
                onPressed: () async {
                  await DeviceBridge.endMaintenance();
                  widget.onLeave();
                },
                child: const Text('Back to kiosk mode now'),
              ),
            TextButton(
              style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
              onPressed: () async {
                if (await _confirm(
                  'Remove kiosk control?',
                  'The tablet goes back to normal: Home, notifications and Settings '
                      'work again and the player can be uninstalled. To lock it again, '
                      'run scripts/provision_tablet.sh.',
                  'Remove',
                )) {
                  await DeviceBridge.releaseKiosk();
                  widget.onLeave();
                }
              },
              child: const Text('Remove kiosk control'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        const Text(
          'Maintenance mode ends by itself: the player comes back and locks again '
          'after $maintenanceMinutes minutes.',
          style: TextStyle(color: Colors.white38, fontSize: 13),
        ),
      ],
    );
  }
}
