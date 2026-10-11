import 'package:dooh_player/src/models.dart';
import 'package:dooh_player/src/ui/blur_fill.dart';
import 'package:dooh_player/src/ui/maintenance_gate.dart';
import 'package:dooh_player/src/ui/text_slide_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('manifest round-trips through JSON and names cache files by hash', () {
    final manifest = Manifest.fromJson({
      'version': 'v1',
      'loop_id': 'loop-1',
      'loop_name': 'Main',
      'items': [
        {
          'item_id': 'i1',
          'media_id': 'm1',
          'kind': 'video',
          'title': 'Clip',
          'duration_seconds': 10,
          'video_fit': 'cut',
          'url': '/files/abc.mp4',
          'sha256': 'deadbeef',
          'size_bytes': 5,
          'media_duration_seconds': 4.5,
          'text': null,
        },
        {
          'item_id': 'i2',
          'media_id': 'm2',
          'kind': 'text',
          'title': 'Promo',
          'duration_seconds': 10,
          'video_fit': 'loop',
          'text': {
            'text': 'Hi',
            'font_size': 120,
            'text_color': '#FFFF00',
            'background_color': '#000080',
          },
        },
      ],
    });
    expect(manifest.items.first.cacheFileName, 'deadbeef.mp4');
    expect(manifest.items.first.videoFit, VideoFit.cut);
    expect(manifest.items.last.hasFile, isFalse);
    final again = Manifest.fromJson(manifest.toJson());
    expect(again.items.last.text!.fontSize, 120);
    expect(again.items.first.framed, isFalse); // older servers don't send it
    final framed = ManifestItem.fromJson({
      ...manifest.items.first.toJson(),
      'framed': true,
    });
    expect(ManifestItem.fromJson(framed.toJson()).framed, isTrue);
  });

  test('parses dashboard hex colors', () {
    expect(parseHexColor('#FF0000'), const Color(0xFFFF0000));
    expect(parseHexColor('#00FF0080'), const Color(0x8000FF00));
    expect(parseHexColor('nope', fallback: Colors.black), Colors.black);
  });

  testWidgets('text slide scales font to portrait screen width', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1280);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      const MaterialApp(
        home: TextSlideView(
          slide: TextSlide(
            text: 'Sale',
            fontSize: 108,
            textColor: '#FFFFFF',
            backgroundColor: '#000000',
          ),
        ),
      ),
    );
    final text = tester.widget<Text>(find.text('Sale'));
    expect(
      text.style!.fontSize,
      closeTo(108 * 800 / 1080, 0.01),
    ); // 1080-wide canvas
  });

  testWidgets(
    'landscape content is centered over blurred bars, portrait fills',
    (tester) async {
      tester.view.physicalSize = const Size(800, 1280);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      const box = ColoredBox(color: Colors.red);

      await tester.pumpWidget(const BlurFill(aspectRatio: 16 / 9, child: box));
      expect(find.byType(ImageFiltered), findsOneWidget);
      final fg = tester.getSize(find.byType(AspectRatio));
      expect(fg.width, 800);
      expect(fg.height, closeTo(450, 0.5)); // not stretched, not cropped

      await tester.pumpWidget(
        const BlurFill(aspectRatio: 800 / 1280, child: box),
      );
      expect(find.byType(ImageFiltered), findsNothing);
    },
  );

  testWidgets('formatted 9:16 content on a 10:16 tablet is padded in white', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1280);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      const WhiteFrameFill(
        aspectRatio: 1080 / 1920,
        child: ColoredBox(color: Colors.red),
      ),
    );
    expect(find.byType(ImageFiltered), findsNothing);
    final fg = tester.getSize(find.byType(AspectRatio));
    expect(fg.height, 1280);
    expect(fg.width, closeTo(720, 0.5)); // whole frame, 40 px white each side
    final bg = tester.widget<ColoredBox>(find.byType(ColoredBox).first);
    expect(bg.color, Colors.white);
  });

  test('corner pattern: clockwise from top-left, within 3 s per tap', () {
    final t0 = DateTime(2026);
    DateTime at(int ms) => t0.add(Duration(milliseconds: ms));
    final p = CornerPattern();
    expect(p.tap(Corner.topLeft, at(0)), isFalse);
    expect(p.tap(Corner.topRight, at(500)), isFalse);
    expect(p.tap(Corner.bottomRight, at(1000)), isFalse);
    expect(p.tap(Corner.bottomLeft, at(1500)), isTrue);

    // Too slow between taps: starts over.
    p.tap(Corner.topLeft, at(10000));
    p.tap(Corner.topRight, at(10500));
    p.tap(Corner.bottomRight, at(20000));
    expect(p.tap(Corner.bottomLeft, at(20500)), isFalse);

    // Counter-clockwise, or a stray tap, doesn't open it.
    for (final c in [
      Corner.topLeft,
      Corner.bottomLeft,
      Corner.bottomRight,
      Corner.topRight,
    ]) {
      expect(p.tap(c, at(30000)), isFalse);
    }
    // A repeated first corner still counts as the start.
    p.tap(Corner.topLeft, at(40000));
    p.tap(Corner.topLeft, at(40200));
    p.tap(Corner.topRight, at(40400));
    p.tap(Corner.bottomRight, at(40600));
    expect(p.tap(Corner.bottomLeft, at(40800)), isTrue);
  });

  testWidgets('PIN pad: right PIN opens, 5 wrong PINs lock it out', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1280);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var opened = false;
    DateTime? lockedUntil;
    await tester.pumpWidget(
      MaterialApp(
        home: PinPad(
          verify: (pin) async => pin == '4821',
          onSuccess: () => opened = true,
          onCancel: () {},
          onLockout: (until) => lockedUntil = until,
        ),
      ),
    );
    Future<void> enter(String pin) async {
      for (final d in pin.split('')) {
        await tester.tap(find.widgetWithText(OutlinedButton, d));
      }
      await tester.tap(find.widgetWithText(OutlinedButton, 'OK'));
      await tester.pumpAndSettle();
    }

    await enter('1111');
    expect(find.text('Wrong PIN'), findsOneWidget);
    expect(opened, isFalse);
    for (var i = 0; i < 4; i++) {
      await enter('1111');
    }
    expect(lockedUntil, isNotNull);
    await enter('4821'); // locked: even the right PIN is ignored
    expect(opened, isFalse);
  });

  testWidgets('PIN pad opens with the right PIN', (tester) async {
    tester.view.physicalSize = const Size(800, 1280);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var opened = false;
    await tester.pumpWidget(
      MaterialApp(
        home: PinPad(
          verify: (pin) async => pin == '4821',
          onSuccess: () => opened = true,
          onCancel: () {},
        ),
      ),
    );
    for (final d in '4821'.split('')) {
      await tester.tap(find.widgetWithText(OutlinedButton, d));
    }
    await tester.tap(find.widgetWithText(OutlinedButton, 'OK'));
    await tester.pumpAndSettle();
    expect(opened, isTrue);
  });
}
