import 'dart:async';

import 'package:battery_plus/battery_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

/// Battery and GPS readings for the heartbeat.
class Telemetry {
  final _battery = Battery();
  Position? _lastPosition;
  DateTime? _lastFix;

  static const _locationRefresh = Duration(minutes: 10);

  /// Asks for location permission (shows the Android dialog once).
  Future<bool> ensureLocationPermission() async {
    try {
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      return permission == LocationPermission.always ||
          permission == LocationPermission.whileInUse;
    } catch (e) {
      debugPrint('Location permission check failed: $e');
      return false;
    }
  }

  Future<Position?> _position() async {
    final fresh =
        _lastFix != null &&
        DateTime.now().difference(_lastFix!) < _locationRefresh;
    if (fresh) return _lastPosition;
    try {
      final permission = await Geolocator.checkPermission();
      if (permission != LocationPermission.always &&
          permission != LocationPermission.whileInUse) {
        return _lastPosition;
      }
      if (!await Geolocator.isLocationServiceEnabled()) return _lastPosition;
      Position? pos;
      try {
        pos = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            timeLimit: Duration(seconds: 30),
          ),
        );
      } on TimeoutException {
        pos = await Geolocator.getLastKnownPosition();
      }
      if (pos != null) {
        _lastPosition = pos;
        _lastFix = DateTime.now();
      }
    } catch (e) {
      debugPrint('Location unavailable: $e');
    }
    return _lastPosition;
  }

  Future<Map<String, Object?>> snapshot() async {
    int? level;
    bool? charging;
    try {
      level = await _battery.batteryLevel;
      final state = await _battery.batteryState;
      charging = state == BatteryState.charging || state == BatteryState.full;
    } catch (_) {}
    final pos = await _position();
    return {
      'battery_level': level,
      'is_charging': charging,
      if (pos != null) ...{
        'latitude': pos.latitude,
        'longitude': pos.longitude,
        'location_accuracy_m': pos.accuracy,
      },
    };
  }
}
