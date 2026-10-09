import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';

/// Keeps the assigned loop and all of its files on disk so playback never
/// depends on the network. A new loop only replaces the current one after
/// every file has been downloaded and its SHA-256 verified.
class ContentCache {
  ContentCache._(this._root);

  static Future<ContentCache> open() async {
    final dir = await getApplicationSupportDirectory();
    final cache = ContentCache._(dir);
    await cache._mediaDir.create(recursive: true);
    await cache._loadSaved();
    return cache;
  }

  final Directory _root;
  final ValueNotifier<Manifest> current = ValueNotifier(Manifest.empty);
  final ValueNotifier<String?> status = ValueNotifier(null);
  bool _syncing = false;

  Directory get _mediaDir => Directory('${_root.path}/media');
  File get _manifestFile => File('${_root.path}/manifest.json');

  File fileFor(ManifestItem item) => File('${_mediaDir.path}/${item.cacheFileName}');

  bool _isComplete(Manifest m) =>
      m.items.where((i) => i.hasFile).every((i) => fileFor(i).existsSync());

  Future<void> _loadSaved() async {
    try {
      if (!await _manifestFile.exists()) return;
      final saved = Manifest.fromJson(jsonDecode(await _manifestFile.readAsString()) as Map<String, dynamic>);
      if (_isComplete(saved)) current.value = saved;
    } catch (e) {
      debugPrint('Ignoring unreadable saved manifest: $e');
    }
  }

  /// Clears content when the tablet is unpaired.
  Future<void> clear() async {
    current.value = Manifest.empty;
    if (await _manifestFile.exists()) await _manifestFile.delete();
    await _cleanup(Manifest.empty);
  }

  /// Fetches the manifest and, if it changed, downloads what's missing and
  /// switches over. Returns true when new content went live.
  Future<bool> sync(PlayerApi api) async {
    if (_syncing) return false;
    _syncing = true;
    try {
      final next = await api.manifest();
      if (next.version == current.value.version && _isComplete(current.value)) return false;

      final files = next.items.where((i) => i.hasFile).toList();
      final seen = <String>{};
      var done = 0;
      for (final item in files) {
        if (!seen.add(item.cacheFileName!)) continue;
        status.value = 'Downloading ${++done} of ${files.length}: ${item.title}';
        await _ensureDownloaded(api, item);
      }

      await _manifestFile.writeAsString(jsonEncode(next.toJson()), flush: true);
      current.value = next;
      status.value = null;
      await _cleanup(next);
      return true;
    } catch (e) {
      // Keep playing what we have; the next sync retries.
      status.value = null;
      rethrow;
    } finally {
      _syncing = false;
    }
  }

  Future<void> _ensureDownloaded(PlayerApi api, ManifestItem item) async {
    final target = fileFor(item);
    if (await target.exists()) return;
    final part = File('${target.path}.part');
    final res = await api.download(item.url!);
    final sink = part.openWrite();
    try {
      await res.stream.pipe(sink);
    } catch (e) {
      if (await part.exists()) await part.delete();
      rethrow;
    }
    final digest = await sha256.bind(part.openRead()).first;
    if (digest.toString() != item.sha256) {
      await part.delete();
      throw StateError('Checksum mismatch for ${item.title}');
    }
    await part.rename(target.path);
  }

  Future<void> _cleanup(Manifest keep) async {
    final wanted = keep.items.map((i) => i.cacheFileName).whereType<String>().toSet();
    await for (final entity in _mediaDir.list()) {
      final name = entity.uri.pathSegments.last;
      if (entity is File && !wanted.contains(name)) {
        try {
          await entity.delete();
        } catch (_) {}
      }
    }
  }

  /// Bytes used by cached media, for the info screen.
  Future<int> sizeOnDisk() async {
    var total = 0;
    await for (final entity in _mediaDir.list()) {
      if (entity is File) total += await entity.length();
    }
    return total;
  }
}
