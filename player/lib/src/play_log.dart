import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'models.dart';

/// Sends a batch of plays; returns the ids the server accepted.
typedef SendPlays = Future<Set<String>> Function(List<PlayRecord> plays);

/// Proof-of-play queue. Every play gets a UUID here on the tablet and is
/// written to disk before it is sent, so plays survive WiFi drops and app
/// restarts, and a retried batch is never double-counted by the server.
///
/// Plays are appended to a journal file, one JSON line each, and a separate
/// small file remembers how far into the journal the server has confirmed.
/// Recording a play only appends one line, so a screen with no WiFi for weeks
/// (an offline screen synced on visits) keeps every play without rewriting a
/// growing file every ten seconds.
class PlayLog {
  PlayLog._(this._dir);

  /// About 200 bytes a play, so roughly 500,000 plays: seven weeks of
  /// 10 second ads around the clock. Past this the oldest unsent plays go.
  static const maxJournalBytes = 100 * 1024 * 1024;
  static const _batchSize = 200;
  static const _readChunk = 256 * 1024;
  static const _newline = 10;
  static const _uuid = Uuid();

  static Future<PlayLog> open({Directory? dir}) async {
    final log = PlayLog._(dir ?? await getApplicationSupportDirectory());
    await log._load();
    return log;
  }

  final Directory _dir;
  File get _journal => File('${_dir.path}/plays.jsonl');
  File get _offsetFile => File('${_dir.path}/plays.offset');
  // The previous format: the whole queue as one JSON array.
  File get _legacyFile => File('${_dir.path}/pending_plays.json');

  /// Bytes at the start of the journal the server has confirmed.
  int _sentOffset = 0;
  int _pendingCount = 0;

  /// Bumped whenever the journal is rewritten, so a flush that read a batch
  /// before the rewrite doesn't move the offset afterwards.
  int _generation = 0;
  bool _flushing = false;

  /// Every file change runs on this chain, one at a time.
  Future<void> _chain = Future.value();

  int get pendingCount => _pendingCount;

  Future<T> _locked<T>(Future<T> Function() action) {
    final result = _chain.then((_) => action());
    _chain = result.then<void>((_) {}, onError: (Object e) {
      debugPrint('Play log: $e');
    });
    return result;
  }

  Future<void> _load() async {
    try {
      final saved = await _offsetFile.exists()
          ? int.tryParse((await _offsetFile.readAsString()).trim()) ?? 0
          : 0;
      final length = await _journal.exists() ? await _journal.length() : 0;
      _sentOffset = saved <= length ? saved : 0;
      if (length > 0 && await _lastByte() != _newline) {
        // A write cut off by a power loss: close the line so the next play
        // starts on its own line (the cut-off line is skipped when sent).
        await _journal.writeAsString('\n', mode: FileMode.append, flush: true);
      }
      _pendingCount = await _countLines(_sentOffset);
      await _migrateLegacy();
    } catch (e) {
      debugPrint('Play log unreadable, starting over: $e');
      _sentOffset = 0;
      _pendingCount = 0;
    }
  }

  Future<int> _lastByte() async {
    final raf = await _journal.open();
    try {
      await raf.setPosition(await raf.length() - 1);
      return await raf.readByte();
    } finally {
      await raf.close();
    }
  }

  Future<int> _countLines(int from) async {
    if (!await _journal.exists()) return 0;
    var count = 0;
    await for (final chunk in _journal.openRead(from)) {
      for (final b in chunk) {
        if (b == _newline) count++;
      }
    }
    return count;
  }

  Future<void> _migrateLegacy() async {
    if (!await _legacyFile.exists()) return;
    try {
      final list = jsonDecode(await _legacyFile.readAsString()) as List;
      final lines = list.map((e) => '${jsonEncode(e)}\n').join();
      if (lines.isNotEmpty) {
        await _journal.writeAsString(lines, mode: FileMode.append, flush: true);
        _pendingCount += list.length;
      }
    } catch (e) {
      debugPrint('Discarding unreadable old play queue: $e');
    }
    await _legacyFile.delete();
  }

  void record({
    required ManifestItem item,
    required String? loopId,
    required DateTime startedAt,
    required Duration played,
  }) {
    add(
      PlayRecord(
        id: _uuid.v4(),
        mediaId: item.mediaId,
        mediaTitle: item.title,
        loopId: loopId,
        startedAt: startedAt,
        durationMs: played.inMilliseconds,
      ),
    ).catchError((Object e) => debugPrint('Could not save play: $e'));
  }

  /// Appends one play to the journal.
  Future<void> add(PlayRecord play) {
    _pendingCount++;
    final line = '${jsonEncode(play.toJson())}\n';
    return _locked(() async {
      await _journal.writeAsString(line, mode: FileMode.append, flush: true);
      if (await _journal.length() > maxJournalBytes) await _dropOldest();
    });
  }

  /// Full journal: keep the newest three quarters, starting at a line.
  Future<void> _dropOldest() async {
    final length = await _journal.length();
    final keepFrom = await _nextLineStart(length - maxJournalBytes * 3 ~/ 4);
    await _rewriteFrom(max(keepFrom, _sentOffset));
    debugPrint('Play log full: dropped the oldest unsent plays');
  }

  /// First byte after the newline at or after [from].
  Future<int> _nextLineStart(int from) async {
    final raf = await _journal.open();
    try {
      await raf.setPosition(from);
      var pos = from;
      while (true) {
        final b = await raf.readByte();
        if (b == -1) return pos;
        pos++;
        if (b == _newline) return pos;
      }
    } finally {
      await raf.close();
    }
  }

  /// Rewrites the journal to start at [from] (a line start); the offset
  /// becomes 0. Only call on the chain.
  Future<void> _rewriteFrom(int from) async {
    final tmp = File('${_journal.path}.tmp');
    final sink = tmp.openWrite();
    await sink.addStream(_journal.openRead(from));
    await sink.flush();
    await sink.close();
    await tmp.rename(_journal.path);
    _generation++;
    await _saveOffset(0);
    _pendingCount = await _countLines(0);
  }

  Future<void> _saveOffset(int offset) async {
    _sentOffset = offset;
    final tmp = File('${_offsetFile.path}.tmp');
    await tmp.writeAsString('$offset', flush: true);
    await tmp.rename(_offsetFile.path);
  }

  /// The next unsent plays, and the journal bytes they take up.
  Future<(List<PlayRecord>, List<int>)> _readBatch() async {
    if (!await _journal.exists()) return (<PlayRecord>[], <int>[]);
    final raf = await _journal.open();
    final List<int> bytes;
    try {
      await raf.setPosition(_sentOffset);
      bytes = await raf.read(_readChunk);
    } finally {
      await raf.close();
    }
    final plays = <PlayRecord>[];
    final ends = <int>[]; // journal offset just past each line read
    var start = 0;
    for (var i = 0; i < bytes.length && ends.length < _batchSize; i++) {
      if (bytes[i] != _newline) continue;
      try {
        final json = jsonDecode(utf8.decode(bytes.sublist(start, i)));
        plays.add(PlayRecord.fromJson(json as Map<String, dynamic>));
      } catch (_) {
        plays.add(_unreadable); // still moves the offset past the bad line
      }
      ends.add(_sentOffset + i + 1);
      start = i + 1;
    }
    return (plays, ends);
  }

  static final _unreadable = PlayRecord(
    id: '',
    mediaId: null,
    mediaTitle: null,
    loopId: null,
    startedAt: DateTime.fromMillisecondsSinceEpoch(0),
    durationMs: 0,
  );

  /// Sends queued plays in batches; stops at the first network error.
  Future<void> flush(PlayerApi api) => flushWith(api.sendPlays);

  Future<void> flushWith(SendPlays send) async {
    if (_flushing || _pendingCount == 0) return;
    _flushing = true;
    try {
      while (true) {
        final generation = _generation;
        final (plays, ends) = await _locked(_readBatch);
        if (plays.isEmpty) break;
        final valid = plays.where((p) => p.id.isNotEmpty).toList();
        final accepted = valid.isEmpty ? <String>{} : await send(valid);
        // Move past the longest run of lines the server confirmed (or that
        // were unreadable and can never be sent).
        var done = 0;
        while (done < plays.length &&
            (plays[done].id.isEmpty || accepted.contains(plays[done].id))) {
          done++;
        }
        if (done == 0) break;
        final moved = await _locked(() async {
          if (generation != _generation) return false; // rewritten meanwhile
          await _saveOffset(ends[done - 1]);
          _pendingCount = max(0, _pendingCount - done);
          await _compactIfSent();
          return true;
        });
        if (!moved || done < plays.length) break;
      }
    } finally {
      _flushing = false;
    }
  }

  /// Once everything is sent, start the journal over so it doesn't grow.
  Future<void> _compactIfSent() async {
    final length = await _journal.length();
    if (_sentOffset == length && length > 0) {
      await _journal.writeAsString('', flush: true);
      _generation++;
      await _saveOffset(0);
    } else if (_sentOffset > 20 * 1024 * 1024) {
      await _rewriteFrom(_sentOffset);
    }
  }
}
