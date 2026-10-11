"""Turns any image, video or text slide into the screen format: exactly
1080 x 1920 with a 12 px white border on all four edges.

Inside the border (1056 x 1896):
- "fit" (default): content that's already the screen's shape (within 2%) fills
  it; any other shape is shown whole, never stretched or cut, over a blurred,
  darkened copy of itself.
- "fill": the content covers the area and the edges are cropped.

Text slides are rendered here too, so the dashboard preview and the screen
show exactly the same picture.
"""

import logging
import subprocess
from pathlib import Path
from textwrap import dedent

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .models import FitMode

log = logging.getLogger("dooh.formatting")

# Bump to have `python -m app.reformat` redo every item after a format change.
FORMAT_VERSION = 1

CANVAS_W, CANVAS_H = 1080, 1920
BORDER = 12
BORDER_COLOR = (255, 255, 255)
INNER_W, INNER_H = CANVAS_W - 2 * BORDER, CANVAS_H - 2 * BORDER
FILL_TOLERANCE = 0.02  # this close to the screen's shape fills instead of fitting

# Background behind fitted content: a heavily blurred, darkened copy.
BLUR_W, BLUR_H = INNER_W // 4, INNER_H // 4
BLUR_RADIUS = 10
BACKGROUND_BRIGHTNESS = 0.55

MAX_VIDEO_FPS = 30
VIDEO_TIMEOUT = 60 * 60

FONT_PATH = Path(__file__).parent / "fonts" / "Inter.ttf"
TEXT_PAD_X, TEXT_PAD_Y = 72, 140
TEXT_MIN_SIZE, TEXT_MAX_SIZE = 28, 360
TEXT_LINE_HEIGHT = 1.15


def covers(width: int, height: int, mode: FitMode) -> bool:
    """True when the content should cover the inner area (cropping at most a
    sliver), False when it should be fitted over a blurred background."""
    if mode is FitMode.fill:
        return True
    ratio = (width / height) / (INNER_W / INNER_H)
    return abs(ratio - 1) <= FILL_TOLERANCE


def describe(width: int, height: int, mode: FitMode) -> str:
    shape = "Vertical" if height > width * 1.05 else "Landscape" if width > height * 1.05 else "Square"
    if covers(width, height, mode):
        how = "cropped to fill" if mode is FitMode.fill else "fills the screen"
    else:
        how = "shown whole over a blurred background"
    return f"{shape} {width}×{height}: {how}"


def _framed(inner: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BORDER_COLOR)
    canvas.paste(inner, (BORDER, BORDER))
    return canvas


def _save_jpeg(img: Image.Image, target: Path) -> None:
    # 4:4:4 keeps small text in flyers crisp; no EXIF means no GPS.
    img.save(target, "JPEG", quality=92, subsampling=0, optimize=True, progressive=True)


# --- Images -------------------------------------------------------------------


def open_upright(source: Path) -> Image.Image:
    """Opens an image (incl. HEIC) with the camera's rotation applied and any
    transparency flattened onto white. Raises OSError/ValueError if unreadable."""
    with Image.open(source) as img:
        img.draft("RGB", (CANVAS_W * 2, CANVAS_H * 2))  # fast JPEG downscale for huge photos
        img.load()
        out = ImageOps.exif_transpose(img)
    if out.mode in ("RGBA", "LA", "P", "PA"):
        rgba = out.convert("RGBA")
        out = Image.new("RGB", rgba.size, (255, 255, 255))
        out.paste(rgba, mask=rgba.getchannel("A"))
    return out.convert("RGB")


def format_image(source: Path, target: Path, mode: FitMode) -> tuple[int, int]:
    """Writes the framed 1080x1920 JPEG. Returns the upright source size."""
    img = open_upright(source)
    size = img.size
    if covers(*size, mode):
        inner = ImageOps.fit(img, (INNER_W, INNER_H), Image.Resampling.LANCZOS)
    else:
        background = ImageOps.fit(img, (BLUR_W, BLUR_H), Image.Resampling.BILINEAR)
        background = background.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        background = ImageEnhance.Brightness(background).enhance(BACKGROUND_BRIGHTNESS)
        inner = background.resize((INNER_W, INNER_H), Image.Resampling.BICUBIC)
        content = ImageOps.contain(img, (INNER_W, INNER_H), Image.Resampling.LANCZOS)
        inner.paste(content, ((INNER_W - content.width) // 2, (INNER_H - content.height) // 2))
    _save_jpeg(_framed(inner), target)
    return size


# --- Text slides --------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), size)
    font.set_variation_by_axes([32, 800])  # optical size, ExtraBold
    return font


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str] | None:
    """Greedy word wrap that keeps the slide's own line breaks. Returns None
    if a single word is wider than the slide at this size."""
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if font.getlength(candidate) <= width:
                line = candidate
            elif font.getlength(word) > width:
                return None
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _layout_text(text: str) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """The largest font size at which the whole text fits the slide."""
    box_w, box_h = INNER_W - 2 * TEXT_PAD_X, INNER_H - 2 * TEXT_PAD_Y
    lo, hi, best = TEXT_MIN_SIZE, TEXT_MAX_SIZE, None
    while lo <= hi:
        size = (lo + hi) // 2
        font = _font(size)
        lines = _wrap(text, font, box_w)
        if lines is not None and len(lines) * size * TEXT_LINE_HEIGHT <= box_h:
            best, lo = (font, lines, size), size + 1
        else:
            hi = size - 1
    if best is None:  # very long text: smallest size, hard-wrapped by character
        font = _font(TEXT_MIN_SIZE)
        lines = []
        for paragraph in text.splitlines() or [""]:
            line = ""
            for ch in paragraph:
                if font.getlength(line + ch) > box_w and line:
                    lines.append(line)
                    line = ch.lstrip()
                else:
                    line += ch
            lines.append(line)
        best = (font, lines, TEXT_MIN_SIZE)
    return best


def _color(value: str | None, default: str) -> tuple[int, int, int]:
    value = value or default
    if len(value) == 9:  # #RRGGBBAA: alpha is ignored on a solid slide
        value = value[:7]
    return ImageColor.getrgb(value)[:3]


def render_text(text: str, text_color: str | None, background_color: str | None, target: Path) -> None:
    """Writes a framed 1080x1920 JPEG of the text, sized to fill the slide."""
    inner = Image.new("RGB", (INNER_W, INNER_H), _color(background_color, "#000000"))
    draw = ImageDraw.Draw(inner)
    font, lines, size = _layout_text(text.strip())
    line_h = size * TEXT_LINE_HEIGHT
    top = (INNER_H - len(lines) * line_h) / 2
    ascent, descent = font.getmetrics()
    # Center each line's glyphs (not its full em box) within its line slot.
    offset = (line_h - (ascent + descent)) / 2
    for i, line in enumerate(lines):
        draw.text((INNER_W / 2, top + i * line_h + offset), line, font=font,
                  fill=_color(text_color, "#FFFFFF"), anchor="ma")
    _save_jpeg(_framed(inner), target)


# --- Videos -------------------------------------------------------------------

TONEMAP_TO_SDR = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)


def video_filter(width: int, height: int, mode: FitMode, *, hdr: bool, fps: float) -> str:
    """The ffmpeg filter graph that frames a video like format_image does."""
    pre = []
    if hdr:
        pre.append(TONEMAP_TO_SDR)
    if fps > MAX_VIDEO_FPS + 0.5:
        pre.append(f"fps={MAX_VIDEO_FPS}")  # budget tablet decoders top out around 30 fps at 1080p
    pre.append("setsar=1")
    head = "[0:v]" + ",".join(pre)
    frame = f"pad={CANVAS_W}:{CANVAS_H}:{BORDER}:{BORDER}:color=white,format=yuv420p[v]"
    if covers(width, height, mode):
        return (f"{head},scale={INNER_W}:{INNER_H}:force_original_aspect_ratio=increase,"
                f"crop={INNER_W}:{INNER_H},{frame}")
    dim = BACKGROUND_BRIGHTNESS
    return dedent(f"""\
        {head},split[a][b];
        [a]scale={BLUR_W}:{BLUR_H}:force_original_aspect_ratio=increase,crop={BLUR_W}:{BLUR_H},
        gblur=sigma={BLUR_RADIUS},colorchannelmixer=rr={dim}:gg={dim}:bb={dim},
        scale={INNER_W}:{INNER_H}[bg];
        [b]scale={INNER_W}:{INNER_H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];
        [bg][fg]overlay=(W-w)/2:(H-h)/2,{frame}""").replace("\n", "")


def format_video(source: Path, target: Path, width: int, height: int, mode: FitMode,
                 *, hdr: bool, fps: float) -> subprocess.CompletedProcess | None:
    """Encodes the framed 1080x1920 H.264 MP4 (AAC 48 kHz audio if any).
    Returns the ffmpeg result, or None on timeout."""
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-filter_complex", video_filter(width, height, mode, hdr=hdr, fps=fps),
        "-map", "[v]", "-map", "0:a:0?",
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "medium", "-crf", "20",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
        "-movflags", "+faststart", "-map_metadata", "-1", str(target),
    ]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=VIDEO_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
