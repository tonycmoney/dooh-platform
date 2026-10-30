import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

/// Full screen Trillboards programmatic ads, shown when the screen has no
/// paid ads of ours to play. The page comes from the manifest's
/// `fallback_url` (the screen's Trillboards embed URL); Trillboards picks the
/// ads, counts the impressions and pays for them.
///
/// Trillboards' player reports events through `window.TrillboardsBridge
/// .onEvent(json)`. A small shim forwards those to [onEvent] so the dashboard
/// can show what is on screen.
class ProgrammaticFill extends StatefulWidget {
  const ProgrammaticFill({super.key, required this.url, this.onEvent});

  final String url;
  final void Function(String name, Map<String, dynamic> data)? onEvent;

  @override
  State<ProgrammaticFill> createState() => _ProgrammaticFillState();
}

class _ProgrammaticFillState extends State<ProgrammaticFill> {
  /// Reload after a failed page load (offline, DNS) this long later.
  static const retryAfter = Duration(seconds: 30);

  /// A page that runs for days can grow its memory use; start fresh now and
  /// then.
  static const freshPageEvery = Duration(hours: 6);

  static const _channel = 'TrillboardsBridgeNative';
  static const _shim =
      '''
(function () {
  if (window.__lfaBridge) return;
  window.__lfaBridge = true;
  window.TrillboardsBridge = {
    onEvent: function (payload) {
      try {
        $_channel.postMessage(
          typeof payload === 'string' ? payload : JSON.stringify(payload));
      } catch (e) {}
    }
  };
})();
''';

  late final WebViewController _web;
  Timer? _retry;
  Timer? _refresh;
  bool _failed = false;

  /// The current load hit a main frame error; Android then still reports
  /// onPageFinished for its own error page, which must stay hidden.
  bool _errorThisLoad = false;

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.black)
      ..addJavaScriptChannel(_channel, onMessageReceived: _onMessage)
      ..setNavigationDelegate(
        NavigationDelegate(
          // A kiosk screen must stay on Trillboards' player: a tapped ad
          // never takes the whole screen off to another website.
          onNavigationRequest: (request) =>
              !request.isMainFrame || _allowed(request.url)
              ? NavigationDecision.navigate
              : NavigationDecision.prevent,
          onPageStarted: (_) {
            _errorThisLoad = false;
            _injectShim();
          },
          onPageFinished: (_) {
            _injectShim();
            if (!_errorThisLoad && _failed && mounted) {
              setState(() => _failed = false);
            }
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame ?? true) {
              _errorThisLoad = true;
              _scheduleRetry();
            }
          },
          onHttpError: (error) {
            // A 5xx on the page itself (not one of its ads): try again later.
            final status = error.response?.statusCode ?? 0;
            if (status >= 500 && error.request?.uri.host == Uri.parse(widget.url).host) {
              _errorThisLoad = true;
              _scheduleRetry();
            }
          },
        ),
      );
    final platform = _web.platform;
    if (platform is AndroidWebViewController) {
      // A kiosk has nobody to tap play: let video ads start on their own.
      platform.setMediaPlaybackRequiresUserGesture(false);
    }
    _load();
    _refresh = Timer.periodic(freshPageEvery, (_) => _load());
  }

  @override
  void didUpdateWidget(ProgrammaticFill old) {
    super.didUpdateWidget(old);
    if (old.url != widget.url) _load();
  }

  @override
  void dispose() {
    _retry?.cancel();
    _refresh?.cancel();
    // Stop any ad audio or video right away.
    _web.loadRequest(Uri.parse('about:blank')).catchError((_) {});
    super.dispose();
  }

  void _load() {
    _retry?.cancel();
    _web.loadRequest(Uri.parse(widget.url)).catchError((Object e) {
      debugPrint('Trillboards page failed to load: $e');
      _scheduleRetry();
    });
  }

  bool _allowed(String url) {
    if (url == 'about:blank') return true;
    final uri = Uri.tryParse(url);
    if (uri == null || uri.scheme != 'https') return false;
    final start = Uri.tryParse(widget.url);
    return uri.host == 'trillboards.com' ||
        uri.host.endsWith('.trillboards.com') ||
        (start != null && uri.host == start.host);
  }

  void _injectShim() {
    _web.runJavaScript(_shim).catchError((_) {});
  }

  void _scheduleRetry() {
    if (!mounted) return;
    if (!_failed) setState(() => _failed = true);
    if (_retry?.isActive ?? false) return;
    _retry = Timer(retryAfter, _load);
  }

  void _onMessage(JavaScriptMessage message) {
    final callback = widget.onEvent;
    if (callback == null) return;
    try {
      final decoded = jsonDecode(message.message);
      if (decoded is! Map<String, dynamic>) return;
      final name = _eventName(decoded);
      if (name == null) return;
      final data = decoded['data'] is Map<String, dynamic>
          ? decoded['data'] as Map<String, dynamic>
          : decoded;
      callback(name, data);
    } catch (e) {
      debugPrint('Unreadable Trillboards event: $e');
    }
  }

  static const _knownEvents = {
    'ready',
    'ad_started',
    'ad_completed',
    'ad_skipped',
    'ad_ended',
    'ad_error',
    'no_ads',
    'ads_refreshed',
    'online',
    'offline',
    'state_changed',
  };

  static String? _eventName(Map<String, dynamic> json) {
    for (final key in const ['event', 'name', 'eventName']) {
      final value = json[key];
      if (value is String) return value;
    }
    final type = json['type'];
    if (type is String && _knownEvents.contains(type)) return type;
    return null;
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        // Nobody should tap their way out of the ad player on a kiosk.
        IgnorePointer(child: WebViewWidget(controller: _web)),
        if (_failed)
          const ColoredBox(
            color: Colors.black,
            child: Center(
              child: Text(
                'Waiting for a connection…',
                style: TextStyle(color: Colors.white38, fontSize: 18),
              ),
            ),
          ),
      ],
    );
  }
}
