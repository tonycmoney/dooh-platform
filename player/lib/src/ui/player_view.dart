import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../controller.dart';
import '../models.dart';
import 'blur_fill.dart';
import 'text_slide_view.dart';

/// Plays the cached loop forever. Each item is shown for its set duration.
/// Videos either loop to fill that time or play once and are cut at it.
/// A changed loop takes over at the next item boundary.
class PlayerView extends StatefulWidget {
  const PlayerView({super.key, required this.controller});

  final PlayerController controller;

  @override
  State<PlayerView> createState() => _PlayerViewState();
}

class _PlayerViewState extends State<PlayerView> {
  PlayerController get ctl => widget.controller;

  Manifest _manifest = Manifest.empty;
  int _index = -1;
  ManifestItem? _item;
  DateTime _startedAt = DateTime.now();
  VideoPlayerController? _video;
  VideoPlayerController? _nextVideo;
  String? _nextVideoItemId;
  Timer? _timer;
  int _failuresInARow = 0;
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    ctl.cache.current.addListener(_onManifestChanged);
    _manifest = ctl.cache.current.value;
    _advance(recordPrevious: false);
  }

  @override
  void dispose() {
    _disposed = true;
    ctl.cache.current.removeListener(_onManifestChanged);
    _timer?.cancel();
    _video?.dispose();
    _nextVideo?.dispose();
    super.dispose();
  }

  void _onManifestChanged() {
    // Nothing playing (empty loop): start right away. Otherwise switch at the
    // next boundary so the current ad is never cut off mid-play.
    if (_item == null && !(_timer?.isActive ?? false)) {
      _manifest = ctl.cache.current.value;
      _index = -1;
      _advance(recordPrevious: false);
    }
  }

  Future<void> _advance({bool recordPrevious = true}) async {
    if (_disposed) return;
    _timer?.cancel();
    final previous = _item;
    if (recordPrevious && previous != null) {
      ctl.onItemFinished(
        previous,
        _startedAt,
        DateTime.now().difference(_startedAt),
      );
    }

    final latest = ctl.cache.current.value;
    if (latest.version != _manifest.version) {
      _manifest = latest;
      _index = -1;
      await _disposeNextVideo();
    }

    if (_manifest.items.isEmpty) {
      final old = _video;
      setState(() {
        _item = null;
        _video = null;
      });
      await old?.dispose();
      return;
    }

    _index = (_index + 1) % _manifest.items.length;
    await _show(_manifest.items[_index]);
  }

  Future<void> _show(ManifestItem item) async {
    final oldVideo = _video;
    VideoPlayerController? video;
    var showFor = Duration(seconds: max(1, item.durationSeconds));

    try {
      if (item.kind == MediaKind.video) {
        video = await _takeVideo(item);
        final length = video.value.duration;
        if (item.videoFit == VideoFit.loop) {
          await video.setLooping(true);
        } else {
          await video.setLooping(false);
          if (length > Duration.zero && length < showFor) showFor = length;
        }
        await video.seekTo(Duration.zero);
        await video.play();
      } else if (item.kind == MediaKind.image) {
        final file = ctl.cache.fileFor(item);
        if (!file.existsSync()) throw StateError('missing ${file.path}');
        if (mounted) await precacheImage(FileImage(file), context);
      }
      _failuresInARow = 0;
    } catch (e) {
      debugPrint('Skipping "${item.title}": $e');
      await video?.dispose();
      _failuresInARow++;
      // If everything is failing, don't spin: wait before trying again.
      final wait = _failuresInARow >= _manifest.items.length ? 5 : 0;
      _item = null;
      _timer = Timer(
        Duration(seconds: wait),
        () => _advance(recordPrevious: false),
      );
      return;
    }

    if (_disposed) {
      await video?.dispose();
      return;
    }
    setState(() {
      _item = item;
      _video = video;
    });
    _startedAt = DateTime.now();
    ctl.onItemStarted(item);
    _timer = Timer(showFor, _advance);

    // Free the previous video after the new frame is on screen.
    if (oldVideo != null && oldVideo != video) {
      WidgetsBinding.instance.addPostFrameCallback((_) => oldVideo.dispose());
    }
    unawaited(_preloadNext());
  }

  Future<VideoPlayerController> _takeVideo(ManifestItem item) async {
    if (_nextVideo != null && _nextVideoItemId == item.itemId) {
      final ready = _nextVideo!;
      _nextVideo = null;
      _nextVideoItemId = null;
      if (ready.value.isInitialized) return ready;
      await ready.dispose();
    }
    final controller = VideoPlayerController.file(
      ctl.cache.fileFor(item),
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: true),
    );
    try {
      await controller.initialize().timeout(const Duration(seconds: 15));
    } catch (_) {
      // Release the hardware decoder, or later videos can't get one.
      await controller.dispose();
      rethrow;
    }
    return controller;
  }

  /// Initializes the next video while the current item plays, so the switch
  /// is instant.
  Future<void> _preloadNext() async {
    if (_manifest.items.length < 2) return;
    final next = _manifest.items[(_index + 1) % _manifest.items.length];
    if (next.kind != MediaKind.video || next.itemId == _item?.itemId) return;
    if (_nextVideoItemId == next.itemId) return;
    await _disposeNextVideo();
    final controller = VideoPlayerController.file(
      ctl.cache.fileFor(next),
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: true),
    );
    _nextVideo = controller;
    _nextVideoItemId = next.itemId;
    try {
      await controller.initialize();
    } catch (_) {
      if (_nextVideo == controller) await _disposeNextVideo();
    }
  }

  Future<void> _disposeNextVideo() async {
    final v = _nextVideo;
    _nextVideo = null;
    _nextVideoItemId = null;
    await v?.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final item = _item;
    Widget child;
    if (item == null) {
      child = _Idle(controller: ctl, hasLoop: _manifest.loopId != null);
    } else {
      switch (item.kind) {
        case MediaKind.text:
          child = TextSlideView(slide: item.text!);
        case MediaKind.image:
          final image = Image.file(
            ctl.cache.fileFor(item),
            fit: BoxFit.fill,
            gaplessPlayback: true,
          );
          final ratio = item.aspectRatio;
          child = ratio == null
              ? Image.file(
                  ctl.cache.fileFor(item),
                  fit: BoxFit.contain,
                  gaplessPlayback: true,
                )
              : BlurFill(
                  aspectRatio: ratio,
                  background: Image.file(
                    ctl.cache.fileFor(item),
                    fit: BoxFit.cover,
                    width: double.infinity,
                    height: double.infinity,
                    gaplessPlayback: true,
                  ),
                  child: image,
                );
        case MediaKind.video:
          final v = _video!;
          final ratio = v.value.aspectRatio > 0
              ? v.value.aspectRatio
              : (item.aspectRatio ?? 9 / 16);
          child = BlurFill(aspectRatio: ratio, child: VideoPlayer(v));
      }
    }
    return ColoredBox(
      color: Colors.black,
      child: SizedBox.expand(
        child: KeyedSubtree(
          key: ValueKey(item?.itemId ?? 'idle'),
          child: child,
        ),
      ),
    );
  }
}

class _Idle extends StatelessWidget {
  const _Idle({required this.controller, required this.hasLoop});

  final PlayerController controller;
  final bool hasLoop;

  @override
  Widget build(BuildContext context) {
    final status = controller.cache.status.value;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            controller.store.screenName ?? 'Screen',
            style: const TextStyle(color: Colors.white70, fontSize: 28),
          ),
          const SizedBox(height: 12),
          Text(
            status ??
                (hasLoop
                    ? 'This loop has no approved content yet'
                    : 'Paired. Waiting for a loop to be assigned…'),
            style: const TextStyle(color: Colors.white38, fontSize: 18),
          ),
        ],
      ),
    );
  }
}
