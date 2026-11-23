import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'content_cache.dart';
import 'device.dart';
import 'models.dart';
import 'play_log.dart';
import 'store.dart';
import 'telemetry.dart';

enum Phase { starting, pairing, playing }

/// Owns the tablet's lifecycle: pairing, then syncing content every minute,
/// heartbeats every 60 s and proof-of-play uploads.
///
/// With no internet (a venue without WiFi, or its WiFi down) the tablet keeps
/// playing the loop saved on it, queues its plays, and logs how long it was
/// cut off. Everything goes up the moment it can reach the server again,
/// e.g. when Tony stops by with his phone's hotspot.
class PlayerController extends ChangeNotifier {
  PlayerController({
    required this.store,
    required this.cache,
    required this.playLog,
  });

  final Store store;
  final ContentCache cache;
  final PlayLog playLog;
  final Telemetry telemetry = Telemetry();

  static const heartbeatInterval = Duration(seconds: 60);
  static const syncInterval = Duration(seconds: 60);
  static const playFlushInterval = Duration(seconds: 30);
  static const pairingPollInterval = Duration(seconds: 3);

  /// Shorter losses of contact aren't logged as outages.
  static const minOutage = Duration(minutes: 2);
  static const _maxPendingOutages = 500;
  static const _uuid = Uuid();

  late final PlayerApi api = PlayerApi(
    baseUrl: store.serverUrl,
    token: store.token,
  );

  Phase phase = Phase.starting;
  String deviceUid = '';
  String appVersion = '';
  String? pairingCode;
  String? lastError;
  DateTime? lastContactAt;

  ManifestItem? nowPlaying;
  final List<Timer> _timers = [];
  bool _disposed = false;

  Future<void> start() async {
    final info = await PackageInfo.fromPlatform();
    appVersion = '${info.version}+${info.buildNumber}';
    deviceUid = await DeviceBridge.deviceUid();
    // Ask for location up front; the heartbeat sends it once granted.
    unawaited(telemetry.ensureLocationPermission());

    if (store.token != null) {
      _enterPlaying();
    } else {
      _enterPairing();
    }
  }

  // --- Pairing ----------------------------------------------------------------

  void _enterPairing() {
    _cancelTimers();
    phase = Phase.pairing;
    pairingCode = store.claimSecret != null ? store.pairingCode : null;
    _notify();
    _pairingTick();
    _timers.add(Timer.periodic(pairingPollInterval, (_) => _pairingTick()));
  }

  bool _pairingBusy = false;

  Future<void> _pairingTick() async {
    if (_pairingBusy) return;
    _pairingBusy = true;
    try {
      if (store.claimSecret == null) {
        final reg = await api.register(deviceUid, appVersion);
        store.claimSecret = reg.claimSecret;
        store.pairingCode = reg.pairingCode;
        pairingCode = reg.pairingCode;
      }
      final status = await api.pairingStatus(deviceUid, store.claimSecret!);
      _contactOk();
      if (status.paired && status.token != null) {
        store.token = status.token;
        store.screenName = status.name;
        store.venueName = status.venueName;
        store.claimSecret = null;
        store.pairingCode = null;
        api.token = status.token;
        _enterPlaying();
        return;
      }
    } on ApiException catch (e) {
      if (e.notFound) {
        // Server forgot this registration (e.g. database reset): get a new code.
        store.claimSecret = null;
        pairingCode = null;
      }
      lastError = e.message;
    } catch (e) {
      lastError = 'Cannot reach server at ${store.serverUrl}';
    } finally {
      _pairingBusy = false;
      _notify();
    }
  }

  // --- Playing ----------------------------------------------------------------

  void _enterPlaying() {
    _cancelTimers();
    phase = Phase.playing;
    _notify();
    _syncTick();
    _heartbeatTick();
    _timers
      ..add(Timer.periodic(syncInterval, (_) => _syncTick()))
      ..add(Timer.periodic(heartbeatInterval, (_) => _heartbeatTick()))
      ..add(Timer.periodic(playFlushInterval, (_) => _flushPlays()));
  }

  Future<void> _syncTick() async {
    try {
      final switched = await cache.sync(api);
      _contactOk();
      // Tell the dashboard right away that the new loop is live.
      if (switched) unawaited(_heartbeatTick());
    } catch (e) {
      _handleError(e);
    }
  }

  Future<void> _heartbeatTick() async {
    try {
      final outages = store.pendingOutages;
      final body = <String, Object?>{
        ...await telemetry.snapshot(),
        'app_version': appVersion,
        'now_playing_media_id': nowPlaying?.mediaId,
        'now_playing_title': nowPlaying?.title,
        'outages': outages,
        'manifest_version': cache.current.value.version.isEmpty
            ? null
            : cache.current.value.version,
      };
      final result = await api.heartbeat(body);
      if (outages.isNotEmpty) {
        final sent = outages.map((o) => o['id']).toSet();
        store.pendingOutages = store.pendingOutages
            .where((o) => !sent.contains(o['id']))
            .toList();
      }
      _contactOk();
      store.screenName = result.name;
      store.venueName = result.venueName;
      store.maintenancePin = result.maintenancePin;
      // Loop changed on the dashboard: fetch it now instead of waiting.
      if (result.manifestVersion != cache.current.value.version) {
        unawaited(_syncTick());
      }
    } catch (e) {
      _handleError(e);
    }
    unawaited(_flushPlays());
  }

  Future<void> _flushPlays() async {
    try {
      await playLog.flush(api);
    } catch (e) {
      _handleError(e);
    }
  }

  void onItemStarted(ManifestItem item) {
    final changed = nowPlaying?.itemId != item.itemId;
    nowPlaying = item;
    if (changed) _notify();
  }

  /// No ad on screen (empty loop): the idle screen.
  void onIdle() {
    if (nowPlaying != null) {
      nowPlaying = null;
      _notify();
    }
  }

  void onItemFinished(ManifestItem item, DateTime startedAt, Duration played) {
    playLog.record(
      item: item,
      loopId: cache.current.value.loopId,
      startedAt: startedAt,
      played: played,
    );
  }

  void _contactOk() {
    final now = DateTime.now();
    final since = store.offlineSince;
    if (since != null) {
      store.offlineSince = null;
      if (now.difference(since) >= minOutage) _logOutage(since, now);
    }
    lastContactAt = now;
    if (lastError != null) {
      lastError = null;
      _notify();
    }
  }

  void _handleError(Object e) {
    if (e is ApiException && e.unauthorized && phase == Phase.playing) {
      // Unpaired from the dashboard: stop and show a new pairing code.
      unpairLocally();
      return;
    }
    if (_isConnectionError(e)) {
      // Couldn't reach the server at all (no WiFi, or WiFi without internet).
      // An HTTP error means we did reach it, so that's not an outage.
      store.offlineSince ??= lastContactAt ?? DateTime.now();
    }
    lastError = e is ApiException ? e.message : 'Offline: $e';
    _notify();
  }

  static bool _isConnectionError(Object e) =>
      e is SocketException ||
      e is TimeoutException ||
      e is http.ClientException ||
      e is HandshakeException;

  /// Queues an outage; it goes up with the next heartbeat.
  void _logOutage(DateTime start, DateTime end) {
    final outages = store.pendingOutages
      ..add({
        'id': _uuid.v4(),
        'started_at': start.toUtc().toIso8601String(),
        'ended_at': end.toUtc().toIso8601String(),
      });
    store.pendingOutages = outages.length > _maxPendingOutages
        ? outages.sublist(outages.length - _maxPendingOutages)
        : outages;
  }

  Future<void> unpairLocally() async {
    store.token = null;
    store.claimSecret = null;
    store.pairingCode = null;
    api.token = null;
    store.offlineSince = null;
    store.pendingOutages = [];
    nowPlaying = null;
    await cache.clear();
    _enterPairing();
  }

  void setServerUrl(String url) {
    store.serverUrl = url;
    api.baseUrl = url;
    if (phase == Phase.pairing) {
      store.claimSecret = null;
      pairingCode = null;
      _pairingTick();
    } else {
      _syncTick();
      _heartbeatTick();
    }
  }

  void _cancelTimers() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _cancelTimers();
    super.dispose();
  }
}
