import 'package:shared_preferences/shared_preferences.dart';

/// Small persistent settings. The device token is the tablet's credential.
class Store {
  Store(this._prefs);

  static Future<Store> open() async =>
      Store(await SharedPreferences.getInstance());

  final SharedPreferences _prefs;

  /// Over USB, `adb reverse tcp:8000 tcp:8000` makes the Mac reachable here.
  static const defaultServerUrl = 'http://127.0.0.1:8000';

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

  void _set(String key, String? value) {
    if (value == null) {
      _prefs.remove(key);
    } else {
      _prefs.setString(key, value);
    }
  }
}
