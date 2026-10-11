import 'package:flutter/services.dart';

/// Native helpers implemented in MainActivity.kt.
class DeviceBridge {
  static const _channel = MethodChannel('dooh/device');

  static Future<String> deviceUid() async =>
      await _channel.invokeMethod<String>('deviceUid') ?? 'android-unknown';

  static Future<bool> canStartFromBackground() async =>
      await _channel.invokeMethod<bool>('canStartFromBackground') ?? false;

  static Future<void> openOverlaySettings() =>
      _channel.invokeMethod('openOverlaySettings');

  static Future<bool> isDefaultHome() async =>
      await _channel.invokeMethod<bool>('isDefaultHome') ?? false;

  static Future<void> requestDefaultHome() =>
      _channel.invokeMethod('requestDefaultHome');

  // --- Kiosk (Kiosk.kt) ---

  static Future<KioskStatus> kioskStatus() async {
    final m = await _channel.invokeMapMethod<String, bool>('kioskStatus') ?? {};
    return KioskStatus(
      deviceOwner: m['deviceOwner'] ?? false,
      locked: m['locked'] ?? false,
      maintenance: m['maintenance'] ?? false,
    );
  }

  /// Pauses kiosk mode for [minutes] and opens Android Settings.
  static Future<void> startMaintenance(int minutes) =>
      _channel.invokeMethod('startMaintenance', {'minutes': minutes});

  static Future<void> endMaintenance() =>
      _channel.invokeMethod('endMaintenance');

  /// Crashes the app on purpose; it should be back within seconds.
  static Future<void> testCrash() => _channel.invokeMethod('testCrash');

  /// Gives up device ownership (kiosk off for good, app removable).
  static Future<void> releaseKiosk() => _channel.invokeMethod('releaseKiosk');

  static Future<bool> verifyPin(String pin, Map<String, dynamic> hash) async =>
      await _channel.invokeMethod<bool>('verifyPin', {
        'pin': pin,
        'salt': hash['salt'],
        'hash': hash['hash'],
        'iterations': hash['iterations'],
      }) ??
      false;
}

class KioskStatus {
  const KioskStatus({
    required this.deviceOwner,
    required this.locked,
    required this.maintenance,
  });

  /// Set up with scripts/provision_tablet.sh; everything else needs it.
  final bool deviceOwner;
  final bool locked;
  final bool maintenance;
}
