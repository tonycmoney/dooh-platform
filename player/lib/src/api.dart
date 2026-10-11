import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);
  final int statusCode;
  final String message;

  bool get unauthorized => statusCode == 401;
  bool get notFound => statusCode == 404;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class RegisterResult {
  RegisterResult(this.pairingCode, this.claimSecret);
  final String pairingCode;
  final String claimSecret;
}

class PairingStatus {
  PairingStatus({required this.paired, this.token, this.name, this.venueName});
  final bool paired;
  final String? token;
  final String? name;
  final String? venueName;
}

class HeartbeatResult {
  HeartbeatResult({
    required this.manifestVersion,
    this.name,
    this.venueName,
    this.maintenancePin,
  });
  final String manifestVersion;
  final String? name;
  final String? venueName;

  /// The dashboard's maintenance PIN as {salt, hash, iterations}, or null
  /// when none is set.
  final Map<String, dynamic>? maintenancePin;
}

/// Talks to the FastAPI backend's /api/player endpoints.
class PlayerApi {
  PlayerApi({required this.baseUrl, this.token, http.Client? client})
    : _client = client ?? http.Client();

  String baseUrl;
  String? token;
  final http.Client _client;

  static const _timeout = Duration(seconds: 20);

  Uri uri(String path) =>
      Uri.parse(baseUrl.replaceAll(RegExp(r'/+$'), '') + path);

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Future<Map<String, dynamic>> _post(String path, Object body) async {
    final res = await _client
        .post(uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(_timeout);
    return _decode(res);
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final res = await _client
        .get(uri(path), headers: _headers)
        .timeout(_timeout);
    return _decode(res);
  }

  Map<String, dynamic> _decode(http.Response res) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      var message = res.reasonPhrase ?? 'HTTP ${res.statusCode}';
      try {
        message =
            (jsonDecode(res.body) as Map<String, dynamic>)['detail']
                ?.toString() ??
            message;
      } catch (_) {}
      throw ApiException(res.statusCode, message);
    }
    return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
  }

  Future<RegisterResult> register(String deviceUid, String appVersion) async {
    final json = await _post('/api/player/register', {
      'device_uid': deviceUid,
      'app_version': appVersion,
    });
    return RegisterResult(
      json['pairing_code'] as String,
      json['claim_secret'] as String,
    );
  }

  Future<PairingStatus> pairingStatus(
    String deviceUid,
    String claimSecret,
  ) async {
    final json = await _post('/api/player/pairing-status', {
      'device_uid': deviceUid,
      'claim_secret': claimSecret,
    });
    return PairingStatus(
      paired: json['paired'] as bool,
      token: json['token'] as String?,
      name: json['name'] as String?,
      venueName: json['venue_name'] as String?,
    );
  }

  Future<Manifest> manifest() async =>
      Manifest.fromJson(await _get('/api/player/manifest'));

  Future<HeartbeatResult> heartbeat(Map<String, Object?> body) async {
    final json = await _post('/api/player/heartbeat', body);
    return HeartbeatResult(
      manifestVersion: json['manifest_version'] as String,
      name: json['name'] as String?,
      venueName: json['venue_name'] as String?,
      maintenancePin: json['maintenance_pin'] as Map<String, dynamic>?,
    );
  }

  /// Returns the ids the server has stored (new or already known).
  Future<Set<String>> sendPlays(List<PlayRecord> plays) async {
    final json = await _post('/api/player/plays', {
      'plays': plays.map((p) => p.toJson()).toList(),
    });
    return (json['accepted'] as List<dynamic>).cast<String>().toSet();
  }

  /// Streams a file download; the caller writes and verifies it.
  Future<http.StreamedResponse> download(String path) async {
    final req = http.Request('GET', uri(path));
    final res = await _client.send(req).timeout(_timeout);
    if (res.statusCode != 200) {
      throw ApiException(res.statusCode, 'Download failed: $path');
    }
    return res;
  }
}
