import 'package:flutter/material.dart';

import '../controller.dart';
import 'setup_status.dart';

/// Hidden technician panel: tap the top-left corner 5 times while playing.
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

  @override
  void initState() {
    super.initState();
    widget.controller.cache.sizeOnDisk().then((b) {
      if (mounted) setState(() => _cacheBytes = b);
    });
  }

  @override
  void dispose() {
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

    return Material(
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
                const SetupStatus(),
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
    );
  }
}
