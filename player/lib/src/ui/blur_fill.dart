import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// Shows [child] (an image or video of [aspectRatio] = width / height) on a
/// portrait screen without stretching or cropping it.
///
/// Content that matches the screen shape (within 3%) simply fills it. Anything
/// else, such as a landscape ad, is centered at full size and the empty space
/// is filled with a blurred, darkened, zoomed-in copy of the same content.
class BlurFill extends StatelessWidget {
  const BlurFill({
    super.key,
    required this.aspectRatio,
    required this.child,
    this.background,
  });

  final double aspectRatio;
  final Widget child;

  /// What to blur behind [child]. Defaults to [child] zoomed to cover; images
  /// should pass their own `Image(fit: BoxFit.cover)`, which draws reliably
  /// inside the blur on every GPU.
  final Widget? background;

  static const _matchTolerance = 0.03;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final screenRatio = box.maxWidth / box.maxHeight;
        final sized = SizedBox(
          width: aspectRatio * 1000,
          height: 1000,
          child: child,
        );

        if ((aspectRatio - screenRatio).abs() / screenRatio <=
            _matchTolerance) {
          return SizedBox.expand(
            child: FittedBox(
              fit: BoxFit.cover,
              clipBehavior: Clip.hardEdge,
              child: sized,
            ),
          );
        }

        return Stack(
          fit: StackFit.expand,
          alignment: Alignment.center,
          children: [
            // Background bars: the same content, zoomed to cover and blurred.
            ClipRect(
              child: ImageFiltered(
                imageFilter: ui.ImageFilter.blur(
                  sigmaX: 36,
                  sigmaY: 36,
                  tileMode: TileMode.mirror,
                ),
                child:
                    background ??
                    FittedBox(
                      fit: BoxFit.cover,
                      clipBehavior: Clip.hardEdge,
                      child: sized,
                    ),
              ),
            ),
            const ColoredBox(
              color: Color(0x59000000),
            ), // ~35% black so the ad stands out
            Center(
              child: AspectRatio(aspectRatio: aspectRatio, child: child),
            ),
          ],
        );
      },
    );
  }
}

/// Shows server-formatted content (exactly 1080x1920 with a white border)
/// whole and centered. On a screen of another shape, such as a 10:16 tablet,
/// the leftover space is white, so it reads as a slightly wider border
/// instead of a blur around a frame.
class WhiteFrameFill extends StatelessWidget {
  const WhiteFrameFill({
    super.key,
    required this.aspectRatio,
    required this.child,
  });

  final double aspectRatio;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.white,
      child: Center(
        child: AspectRatio(aspectRatio: aspectRatio, child: child),
      ),
    );
  }
}
