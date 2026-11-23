import 'dart:io';

import 'package:dooh_player/src/models.dart';
import 'package:dooh_player/src/play_log.dart';
import 'package:flutter_test/flutter_test.dart';

ManifestItem _item() => ManifestItem.fromJson({
  'item_id': 'i1',
  'media_id': 'm1',
  'kind': 'image',
  'title': 'Promo',
  'duration_seconds': 10,
  'video_fit': 'loop',
  'url': '/files/a.jpg',
  'sha256': 'abc',
  'size_bytes': 1,
  'media_duration_seconds': null,
  'text': null,
});

Future<void> _record(PlayLog log, int n) async {
  for (var i = 0; i < n; i++) {
    log.record(
      item: _item(),
      loopId: 'loop-1',
      startedAt: DateTime.utc(2026, 11, 23, 12, 0, i),
      played: const Duration(seconds: 10),
    );
  }
  await log.add(
    PlayRecord(
      id: 'last-$n',
      mediaId: 'm1',
      mediaTitle: 'Promo',
      loopId: 'loop-1',
      startedAt: DateTime.utc(2026, 11, 23),
      durationMs: 10000,
    ),
  );
}

void main() {
  late Directory dir;

  setUp(() => dir = Directory.systemTemp.createTempSync('playlog'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('keeps far more than the old 20,000 plays and sends them all', () async {
    final log = await PlayLog.open(dir: dir);
    await _record(log, 25000);
    expect(log.pendingCount, 25001);

    // Survives an app restart.
    final reopened = await PlayLog.open(dir: dir);
    expect(reopened.pendingCount, 25001);

    final sent = <String>{};
    await reopened.flushWith((batch) async {
      expect(batch.length, lessThanOrEqualTo(200));
      final ids = batch.map((p) => p.id).toSet();
      sent.addAll(ids);
      return ids;
    });
    expect(sent.length, 25001);
    expect(reopened.pendingCount, 0);
    expect(File('${dir.path}/plays.jsonl').lengthSync(), 0); // started over
  });

  test('a failed upload keeps everything for the next try', () async {
    final log = await PlayLog.open(dir: dir);
    await _record(log, 450);
    var calls = 0;
    await expectLater(
      log.flushWith((batch) async {
        if (++calls == 2) throw const SocketException('no wifi');
        return batch.map((p) => p.id).toSet();
      }),
      throwsA(isA<SocketException>()),
    );
    expect(log.pendingCount, 251); // first batch of 200 confirmed

    final again = await PlayLog.open(dir: dir);
    expect(again.pendingCount, 251);
    final sent = <String>[];
    await again.flushWith((batch) async {
      sent.addAll(batch.map((p) => p.id));
      return batch.map((p) => p.id).toSet();
    });
    expect(sent.length, 251);
    expect(sent.last, 'last-450');
  });

  test('a line cut off by a power loss is skipped, not stuck', () async {
    final log = await PlayLog.open(dir: dir);
    await _record(log, 2);
    File('${dir.path}/plays.jsonl')
        .writeAsStringSync('{"id": "half', mode: FileMode.append);

    final reopened = await PlayLog.open(dir: dir);
    await reopened.add(
      PlayRecord(
        id: 'after',
        mediaId: null,
        mediaTitle: null,
        loopId: null,
        startedAt: DateTime.utc(2026),
        durationMs: 1,
      ),
    );
    final sent = <String>[];
    await reopened.flushWith((batch) async {
      sent.addAll(batch.map((p) => p.id));
      return batch.map((p) => p.id).toSet();
    });
    expect(sent.length, 4);
    expect(sent.last, 'after');
    expect(reopened.pendingCount, 0);
  });

  test('moves plays from the old single-file queue', () async {
    File('${dir.path}/pending_plays.json').writeAsStringSync(
      '[{"id":"old-1","media_id":"m1","media_title":"Promo","loop_id":null,'
      '"started_at":"2026-11-01T00:00:00.000Z","duration_ms":10000}]',
    );
    final log = await PlayLog.open(dir: dir);
    expect(log.pendingCount, 1);
    expect(File('${dir.path}/pending_plays.json').existsSync(), isFalse);
    final sent = <String>[];
    await log.flushWith((batch) async {
      sent.addAll(batch.map((p) => p.id));
      return batch.map((p) => p.id).toSet();
    });
    expect(sent, ['old-1']);
  });
}
