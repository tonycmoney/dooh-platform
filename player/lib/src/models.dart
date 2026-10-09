enum MediaKind { image, video, text }

enum VideoFit { loop, cut }

class TextSlide {
  const TextSlide({
    required this.text,
    required this.fontSize,
    required this.textColor,
    required this.backgroundColor,
  });

  final String text;
  final int fontSize;
  final String textColor;
  final String backgroundColor;

  factory TextSlide.fromJson(Map<String, dynamic> json) => TextSlide(
        text: json['text'] as String? ?? '',
        fontSize: json['font_size'] as int? ?? 96,
        textColor: json['text_color'] as String? ?? '#FFFFFF',
        backgroundColor: json['background_color'] as String? ?? '#000000',
      );

  Map<String, dynamic> toJson() => {
        'text': text,
        'font_size': fontSize,
        'text_color': textColor,
        'background_color': backgroundColor,
      };
}

class ManifestItem {
  const ManifestItem({
    required this.itemId,
    required this.mediaId,
    required this.kind,
    required this.title,
    required this.durationSeconds,
    required this.videoFit,
    this.url,
    this.sha256,
    this.sizeBytes,
    this.mediaDurationSeconds,
    this.text,
  });

  final String itemId;
  final String mediaId;
  final MediaKind kind;
  final String title;
  final int durationSeconds;
  final VideoFit videoFit;
  final String? url;
  final String? sha256;
  final int? sizeBytes;
  final double? mediaDurationSeconds;
  final TextSlide? text;

  bool get hasFile => kind != MediaKind.text && url != null && sha256 != null;

  /// Cached files are named by content hash, so identical uploads share a file
  /// and a changed file can never be confused with the old one.
  String? get cacheFileName {
    if (!hasFile) return null;
    final dot = url!.lastIndexOf('.');
    final ext = dot >= 0 ? url!.substring(dot) : '';
    return '$sha256$ext';
  }

  factory ManifestItem.fromJson(Map<String, dynamic> json) => ManifestItem(
        itemId: json['item_id'] as String,
        mediaId: json['media_id'] as String,
        kind: MediaKind.values.byName(json['kind'] as String),
        title: json['title'] as String? ?? '',
        durationSeconds: json['duration_seconds'] as int? ?? 10,
        videoFit: VideoFit.values.byName(json['video_fit'] as String? ?? 'loop'),
        url: json['url'] as String?,
        sha256: json['sha256'] as String?,
        sizeBytes: json['size_bytes'] as int?,
        mediaDurationSeconds: (json['media_duration_seconds'] as num?)?.toDouble(),
        text: json['text'] == null ? null : TextSlide.fromJson(json['text'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {
        'item_id': itemId,
        'media_id': mediaId,
        'kind': kind.name,
        'title': title,
        'duration_seconds': durationSeconds,
        'video_fit': videoFit.name,
        'url': url,
        'sha256': sha256,
        'size_bytes': sizeBytes,
        'media_duration_seconds': mediaDurationSeconds,
        'text': text?.toJson(),
      };
}

class Manifest {
  const Manifest({required this.version, this.loopId, this.loopName, required this.items});

  final String version;
  final String? loopId;
  final String? loopName;
  final List<ManifestItem> items;

  static const empty = Manifest(version: '', items: []);

  factory Manifest.fromJson(Map<String, dynamic> json) => Manifest(
        version: json['version'] as String,
        loopId: json['loop_id'] as String?,
        loopName: json['loop_name'] as String?,
        items: (json['items'] as List<dynamic>)
            .map((e) => ManifestItem.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'version': version,
        'loop_id': loopId,
        'loop_name': loopName,
        'items': items.map((e) => e.toJson()).toList(),
      };
}

class PlayRecord {
  PlayRecord({
    required this.id,
    required this.mediaId,
    required this.mediaTitle,
    required this.loopId,
    required this.startedAt,
    required this.durationMs,
  });

  final String id;
  final String? mediaId;
  final String? mediaTitle;
  final String? loopId;
  final DateTime startedAt;
  final int durationMs;

  factory PlayRecord.fromJson(Map<String, dynamic> json) => PlayRecord(
        id: json['id'] as String,
        mediaId: json['media_id'] as String?,
        mediaTitle: json['media_title'] as String?,
        loopId: json['loop_id'] as String?,
        startedAt: DateTime.parse(json['started_at'] as String),
        durationMs: json['duration_ms'] as int,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'media_id': mediaId,
        'media_title': mediaTitle,
        'loop_id': loopId,
        'started_at': startedAt.toUtc().toIso8601String(),
        'duration_ms': durationMs,
      };
}
