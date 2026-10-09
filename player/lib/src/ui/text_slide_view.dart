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

/// Text slides are designed on a 1080-px-tall canvas (matching the dashboard
/// preview) and scaled to this screen's height.
class TextSlideView extends StatelessWidget {
  const TextSlideView({super.key, required this.slide});

  static const canvasHeight = 1080.0;

  final TextSlide slide;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final scale = constraints.maxHeight / canvasHeight;
      return Container(
        color: parseHexColor(slide.backgroundColor, fallback: Colors.black),
        padding: EdgeInsets.all(48 * scale),
        alignment: Alignment.center,
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: constraints.maxWidth - 96 * scale),
            child: Text(
              slide.text,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: parseHexColor(slide.textColor),
                fontSize: slide.fontSize * scale,
                fontWeight: FontWeight.w700,
                height: 1.15,
              ),
            ),
          ),
        ),
      );
    });
  }
}
