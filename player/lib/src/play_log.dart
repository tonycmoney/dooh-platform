import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'models.dart';

/// Proof-of-play queue. Every play gets a UUID here on the tablet and is
/// written to disk before it is sent, so plays survive WiFi drops and app
/// restarts, and a retried batch is never double-counted by the server.
class PlayLog {
  PlayLog._(this._file);

  static const _maxQueued = 20000;
  static const _batchSize = 200;
  static const _uuid = Uuid();

  static Future<PlayLog> open() async {
    final dir = await getApplicationSupportDirectory();
    final log = PlayLog._(File('${dir.path}/pending_plays.json'));
    await log._load();
    return log;
  }

  final File _file;
  final List<PlayRecord> _pending = [];
  bool _flushing = false;
  Future<void> _writeChain = Future.value();

  int get pendingCount => _pending.length;

  Future<void> _load() async {
    try {
      if (await _file.exists()) {
        final list = jsonDecode(await _file.readAsString()) as List<dynamic>;
        _pending.addAll(
          list.map((e) => PlayRecord.fromJson(e as Map<String, dynamic>)),
        );
      }
    } catch (e) {
      debugPrint('Discarding unreadable play queue: $e');
    }
  }

  Future<void> _persist() {
    final snapshot = jsonEncode(_pending.map((p) => p.toJson()).toList());
    _writeChain = _writeChain
        .then((_) async {
          final tmp = File('${_file.path}.tmp');
          await tmp.writeAsString(snapshot, flush: true);
          await tmp.rename(_file.path);
        })
        .catchError((Object e) => debugPrint('Could not save play queue: $e'));
    return _writeChain;
  }

  void record({
    required ManifestItem item,
    required String? loopId,
    required DateTime startedAt,
    required Duration played,
  }) {
    _pending.add(
      PlayRecord(
        id: _uuid.v4(),
        mediaId: item.mediaId,
        mediaTitle: item.title,
        loopId: loopId,
        startedAt: startedAt,
        durationMs: played.inMilliseconds,
      ),
    );
    if (_pending.length > _maxQueued) {
      _pending.removeRange(0, _pending.length - _maxQueued); // drop oldest
    }
    _persist();
  }

  /// Sends queued plays in batches; stops at the first network error.
  Future<void> flush(PlayerApi api) async {
    if (_flushing || _pending.isEmpty) return;
    _flushing = true;
    try {
      while (_pending.isNotEmpty) {
        final batch = _pending.take(_batchSize).toList();
        final accepted = await api.sendPlays(batch);
        _pending.removeWhere((p) => accepted.contains(p.id));
        await _persist();
        if (accepted.length < batch.length) break;
      }
    } finally {
      _flushing = false;
    }
  }
}
