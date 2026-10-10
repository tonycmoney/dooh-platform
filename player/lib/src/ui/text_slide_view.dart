import 'package:flutter/material.dart';

import '../models.dart';

Color parseHexColor(String hex, {Color fallback = Colors.white}) {
  var value = hex.replaceFirst('#', '');
  if (value.length == 6) value = 'FF$value';
  if (value.length == 8 && hex.length == 9) {
    // #RRGGBBAA -> AARRGGBB
    value = value.substring(6) + value.substring(0, 6);
  }
  final parsed = int.tryParse(value, radix: 16);
  return parsed == null ? fallback : Color(parsed);
}

/// Text slides are designed on a 1080 x 1920 portrait canvas (the same canvas
/// the dashboard previews) and scaled to this screen's width, so a font size
/// of 96 looks the same on every portrait screen.
class TextSlideView extends StatelessWidget {
  const TextSlideView({super.key, required this.slide});

  static const canvasWidth = 1080.0;
  static const canvasHeight = 1920.0;
  static const sidePadding = 90.0; // on the 1080-wide canvas
  static const verticalPadding = 160.0;

  final TextSlide slide;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final scale = box.maxWidth / canvasWidth;
        return Container(
          color: parseHexColor(slide.backgroundColor, fallback: Colors.black),
          padding: EdgeInsets.symmetric(
            horizontal: sidePadding * scale,
            vertical: verticalPadding * scale,
          ),
          alignment: Alignment.center,
          // Text wraps to the slide width; if a long message still doesn't fit
          // the height, it is scaled down rather than cut off.
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: SizedBox(
              width: box.maxWidth - 2 * sidePadding * scale,
              child: Text(
                slide.text,
                textAlign: TextAlign.center,
                softWrap: true,
                style: TextStyle(
                  color: parseHexColor(slide.textColor),
                  fontSize: slide.fontSize * scale,
                  fontWeight: FontWeight.w800,
                  height: 1.12,
                  letterSpacing: -0.01 * slide.fontSize * scale,
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
