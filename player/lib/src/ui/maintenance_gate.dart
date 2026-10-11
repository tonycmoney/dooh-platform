import 'package:flutter/material.dart';

/// The secret way into the maintenance panel: tap the four corners of the
/// screen clockwise, starting top-left (top-left, top-right, bottom-right,
/// bottom-left), with at most [maxGap] between taps. Then a PIN is asked.
enum Corner { topLeft, topRight, bottomRight, bottomLeft }

class CornerPattern {
  CornerPattern({this.maxGap = const Duration(seconds: 3)});

  static const sequence = [
    Corner.topLeft,
    Corner.topRight,
    Corner.bottomRight,
    Corner.bottomLeft,
  ];

  final Duration maxGap;
  int _progress = 0;
  DateTime? _last;

  /// Records a tap; returns true when it completes the pattern.
  bool tap(Corner corner, DateTime now) {
    if (_last != null && now.difference(_last!) > maxGap) _progress = 0;
    _last = now;
    if (corner == sequence[_progress]) {
      _progress++;
    } else {
      // A wrong corner restarts the pattern (it may itself be the first step).
      _progress = corner == sequence.first ? 1 : 0;
    }
    if (_progress == sequence.length) {
      _progress = 0;
      return true;
    }
    return false;
  }
}

/// Invisible tap targets in the four corners, on top of the content.
class CornerTapZones extends StatefulWidget {
  const CornerTapZones({super.key, required this.onPattern, this.size = 140});

  final VoidCallback onPattern;
  final double size;

  @override
  State<CornerTapZones> createState() => _CornerTapZonesState();
}

class _CornerTapZonesState extends State<CornerTapZones> {
  final _pattern = CornerPattern();

  Widget _zone(Corner corner) => SizedBox(
    width: widget.size,
    height: widget.size,
    child: GestureDetector(
      key: ValueKey(corner),
      behavior: HitTestBehavior.translucent,
      onTap: () {
        if (_pattern.tap(corner, DateTime.now())) widget.onPattern();
      },
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned(left: 0, top: 0, child: _zone(Corner.topLeft)),
        Positioned(right: 0, top: 0, child: _zone(Corner.topRight)),
        Positioned(right: 0, bottom: 0, child: _zone(Corner.bottomRight)),
        Positioned(left: 0, bottom: 0, child: _zone(Corner.bottomLeft)),
      ],
    );
  }
}

/// On-screen number pad for the maintenance PIN (no system keyboard, which
/// could offer a way out of the app).
class PinPad extends StatefulWidget {
  const PinPad({
    super.key,
    required this.verify,
    required this.onSuccess,
    required this.onCancel,
    this.lockedUntil,
    this.onLockout,
  });

  final Future<bool> Function(String pin) verify;
  final VoidCallback onSuccess;
  final VoidCallback onCancel;

  /// Still locked out from earlier wrong PINs, if in the future.
  final DateTime? lockedUntil;
  final void Function(DateTime until)? onLockout;

  static const maxAttempts = 5;
  static const lockout = Duration(minutes: 5);

  @override
  State<PinPad> createState() => _PinPadState();
}

class _PinPadState extends State<PinPad> {
  String _pin = '';
  int _wrong = 0;
  bool _checking = false;
  String? _message;
  late DateTime? _lockedUntil = widget.lockedUntil;

  bool get _locked =>
      _lockedUntil != null && DateTime.now().isBefore(_lockedUntil!);

  Future<void> _submit() async {
    if (_pin.length < 4 || _checking || _locked) return;
    setState(() => _checking = true);
    final ok = await widget.verify(_pin);
    if (!mounted) return;
    if (ok) {
      widget.onSuccess();
      return;
    }
    _wrong++;
    setState(() {
      _checking = false;
      _pin = '';
      if (_wrong >= PinPad.maxAttempts) {
        _wrong = 0;
        _lockedUntil = DateTime.now().add(PinPad.lockout);
        widget.onLockout?.call(_lockedUntil!);
        _message = 'Too many wrong PINs. Try again in 5 minutes.';
      } else {
        _message = 'Wrong PIN';
      }
    });
  }

  void _press(String key) {
    if (_checking || _locked) return;
    setState(() {
      _message = null;
      if (key == '⌫') {
        if (_pin.isNotEmpty) _pin = _pin.substring(0, _pin.length - 1);
      } else if (_pin.length < 8) {
        _pin += key;
      }
    });
  }

  Widget _key(String label, {VoidCallback? onTap}) => Padding(
    padding: const EdgeInsets.all(6),
    child: SizedBox(
      width: 84,
      height: 72,
      child: OutlinedButton(
        onPressed: onTap ?? () => _press(label),
        style: OutlinedButton.styleFrom(
          foregroundColor: Colors.white,
          side: const BorderSide(color: Colors.white24),
          textStyle: const TextStyle(fontSize: 26),
        ),
        child: Text(label),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.black.withValues(alpha: 0.94),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Maintenance PIN',
              style: TextStyle(color: Colors.white, fontSize: 24),
            ),
            const SizedBox(height: 16),
            Text(
              _pin.isEmpty ? ' ' : '•' * _pin.length,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 32,
                letterSpacing: 8,
              ),
            ),
            SizedBox(
              height: 28,
              child: Text(
                _checking
                    ? 'Checking…'
                    : _message ??
                          (_locked
                              ? 'Too many wrong PINs. Try again later.'
                              : ''),
                style: const TextStyle(color: Colors.orangeAccent),
              ),
            ),
            for (final row in const [
              ['1', '2', '3'],
              ['4', '5', '6'],
              ['7', '8', '9'],
            ])
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [for (final k in row) _key(k)],
              ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _key('⌫'),
                _key('0'),
                _key('OK', onTap: _submit),
              ],
            ),
            const SizedBox(height: 12),
            TextButton(
              onPressed: widget.onCancel,
              child: const Text(
                'Cancel',
                style: TextStyle(color: Colors.white70),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
