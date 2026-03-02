"""
bot/template_generator.py

Generates the 3 permanent template postcard images using Pillow.
Called by the /upload_templates admin command to produce images that
are then uploaded to Telegram (file_id saved in Redis).

Images are NOT stored in the repository — they are generated at
runtime so they can be refreshed without a new deploy.
"""
from __future__ import annotations

import io
import math
import random
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 500  # card dimensions (px)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gradient(draw: ImageDraw.Draw, w: int, h: int,
              top: tuple, bottom: tuple) -> None:
    """Fill the canvas with a vertical linear gradient."""
    for y in range(h):
        t = y / h
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a bold system font; fall back to default if unavailable."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _shadow_text(draw: ImageDraw.Draw, xy: tuple, text: str,
                 font: ImageFont.FreeTypeFont,
                 shadow=(0, 0, 0, 140), fill=(255, 255, 255, 255)) -> None:
    x, y = xy
    for dx, dy in [(-2, 2), (2, 2), (0, 3), (0, 0)]:
        c = shadow if (dx, dy) != (0, 0) else fill
        draw.text((x + dx, y + dy), text, font=font, fill=c)


def _centered(draw: ImageDraw.Draw, img_w: int, y: int,
              text: str, font: ImageFont.FreeTypeFont, **kw) -> None:
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    _shadow_text(draw, ((img_w - tw) // 2, y), text, font, **kw)


def _text_overlay(img: Image.Image, color=(0, 0, 0, 85)) -> Image.Image:
    """Add a semi-transparent rounded rect behind the main text."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle(
        [W // 2 - 300, H // 2 - 90, W // 2 + 300, H // 2 + 95],
        radius=32, fill=color,
    )
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ---------------------------------------------------------------------------
# Individual generators
# ---------------------------------------------------------------------------

def _birthday() -> bytes:
    """Warm salmon-to-gold gradient with confetti circles."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient(draw, W, H, (255, 182, 155), (255, 223, 100))

    rng = random.Random(42)
    for _ in range(65):
        cx = rng.randint(0, W); cy = rng.randint(0, H)
        r = rng.randint(4, 18)
        col = rng.choice([
            (255, 80, 80), (255, 200, 0), (200, 80, 255),
            (80, 200, 255), (80, 255, 150),
        ])
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    img = _text_overlay(img, (0, 0, 0, 90))
    draw = ImageDraw.Draw(img)

    _centered(draw, W, H // 2 - 58, "С Днём Рождения!",
              _load_font(62), shadow=(120, 40, 0, 180), fill=(255, 255, 255, 255))
    _centered(draw, W, H // 2 + 22, "✨  🎂  ✨",
              _load_font(28), fill=(255, 240, 160, 255))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _march8() -> bytes:
    """Pink-to-lavender gradient with petal decorations."""
    def _petals(draw: ImageDraw.Draw, cx: int, cy: int, r: int) -> None:
        for i in range(6):
            a = 2 * math.pi * i / 6
            px = cx + r * math.cos(a); py = cy + r * math.sin(a)
            hr = r // 2
            draw.ellipse([px - hr, py - hr, px + hr, py + hr],
                         fill=(255, 100, 150))
        draw.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3],
                     fill=(255, 220, 230))

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient(draw, W, H, (255, 200, 220), (220, 180, 255))

    for cx, cy, sz in [
        (75, 75, 52), (W - 75, 75, 52),
        (75, H - 75, 52), (W - 75, H - 75, 52),
        (W // 2, 38, 32), (W // 2, H - 38, 32),
    ]:
        _petals(draw, cx, cy, sz)

    img = _text_overlay(img, (255, 255, 255, 110))
    draw = ImageDraw.Draw(img)

    _centered(draw, W, H // 2 - 60, "С 8 Марта!",
              _load_font(72), shadow=(150, 30, 100, 160), fill=(200, 0, 100, 255))
    _centered(draw, W, H // 2 + 22, "🌸  🌷  🌸",
              _load_font(28), fill=(180, 0, 80, 255))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _universal() -> bytes:
    """Sky-blue-to-mint gradient with star confetti."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient(draw, W, H, (180, 225, 255), (140, 255, 200))

    rng = random.Random(99)
    for i in range(55):
        cx = rng.randint(0, W); cy = rng.randint(0, H)
        r = rng.randint(3, 14)
        col = rng.choice([
            (255, 220, 0), (255, 180, 50), (200, 255, 100), (100, 200, 255),
        ])
        for a in range(0, 360, 45):
            rad = math.radians(a)
            er = r if a % 90 == 0 else max(r // 3, 2)
            px = cx + er * math.cos(rad); py = cy + er * math.sin(rad)
            draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=col)

    img = _text_overlay(img, (0, 30, 80, 95))
    draw = ImageDraw.Draw(img)

    _centered(draw, W, H // 2 - 58, "Поздравляю!",
              _load_font(74), shadow=(0, 50, 120, 180), fill=(255, 255, 255, 255))
    _centered(draw, W, H // 2 + 22, "🎉  🎊  🎉",
              _load_font(28), fill=(255, 240, 100, 255))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Mapping: template id  →  generator function
_GENERATORS: dict[str, callable] = {
    "birthday":  _birthday,
    "march8":    _march8,
    "universal": _universal,
}


def generate_template_image(template_id: str) -> bytes:
    """Return JPEG bytes for the given template id.

    Args:
        template_id: one of 'birthday', 'march8', 'universal'

    Returns:
        Raw JPEG bytes ready to be uploaded to Telegram.

    Raises:
        KeyError: if template_id is unknown.
    """
    fn = _GENERATORS[template_id]
    return fn()


def generate_all_template_images() -> dict[str, bytes]:
    """Return {template_id: jpeg_bytes} for all 3 templates."""
    return {tid: fn() for tid, fn in _GENERATORS.items()}
