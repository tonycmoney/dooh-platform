import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Small persistent settings. The device token is the tablet's credential.
class Store {
  Store(this._prefs);

  static Future<Store> open() async =>
      Store(await SharedPreferences.getInstance());

  final SharedPreferences _prefs;

  /// The server new tablets talk to. Release builds set it with
  /// `--dart-define=SERVER_URL=https://...` (see scripts/build_player.sh).
  /// Without it the player uses the Mac over USB, where
  /// `adb reverse tcp:8000 tcp:8000` makes it reachable at this address.
  static const defaultServerUrl = String.fromEnvironment(
    'SERVER_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  String get serverUrl => _prefs.getString('server_url') ?? defaultServerUrl;
  set serverUrl(String value) => _prefs.setString('server_url', value);

  String? get token => _prefs.getString('token');
  set token(String? value) => _set('token', value);

  String? get claimSecret => _prefs.getString('claim_secret');
  set claimSecret(String? value) => _set('claim_secret', value);

  String? get pairingCode => _prefs.getString('pairing_code');
  set pairingCode(String? value) => _set('pairing_code', value);

  String? get screenName => _prefs.getString('screen_name');
  set screenName(String? value) => _set('screen_name', value);

  String? get venueName => _prefs.getString('venue_name');
  set venueName(String? value) => _set('venue_name', value);

  /// Hash of the dashboard's maintenance PIN, kept so it can be checked
  /// offline. Null when the dashboard has none set.
  Map<String, dynamic>? get maintenancePin {
    final raw = _prefs.getString('maintenance_pin');
    return raw == null ? null : jsonDecode(raw) as Map<String, dynamic>;
  }

  set maintenancePin(Map<String, dynamic>? value) =>
      _set('maintenance_pin', value == null ? null : jsonEncode(value));

  /// Wrong-PIN lockout, so it survives an app restart.
  DateTime? get pinLockedUntil {
    final ms = _prefs.getInt('pin_locked_until');
    return ms == null ? null : DateTime.fromMillisecondsSinceEpoch(ms);
  }

  set pinLockedUntil(DateTime? value) => value == null
      ? _prefs.remove('pin_locked_until')
      : _prefs.setInt('pin_locked_until', value.millisecondsSinceEpoch);

  void _set(String key, String? value) {
    if (value == null) {
      _prefs.remove(key);
    } else {
      _prefs.setString(key, value);
    }
  }
}
