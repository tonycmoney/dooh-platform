import 'package:flutter/services.dart';

/// Native helpers implemented in MainActivity.kt.
class DeviceBridge {
  static const _channel = MethodChannel('dooh/device');

  static Future<String> deviceUid() async =>
      await _channel.invokeMethod<String>('deviceUid') ?? 'android-unknown';

  static Future<bool> canStartFromBackground() async =>
      await _channel.invokeMethod<bool>('canStartFromBackground') ?? false;

  static Future<void> openOverlaySettings() => _channel.invokeMethod('openOverlaySettings');

  static Future<bool> isDefaultHome() async =>
      await _channel.invokeMethod<bool>('isDefaultHome') ?? false;

  static Future<void> requestDefaultHome() => _channel.invokeMethod('requestDefaultHome');
}
