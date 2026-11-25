"""Render text overlays to transparent PNGs with Pillow.

Used instead of ffmpeg's drawtext/subtitles filters because those need
libfreetype/libass built into ffmpeg, which isn't guaranteed on every
machine running this template (it's missing on the one this was built on).
PNG + the core `overlay` filter works on any ffmpeg build.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _font(size):
    return ImageFont.truetype(FONT_PATH, size)


def render_text_png(text, out_path, fontsize, canvas_w=1080, fill=(255, 255, 255, 255),
                     stroke_fill=(0, 0, 0, 255), stroke_width=6, box=False,
                     box_fill=(0, 0, 0, 90), pad_x=28, pad_y=18, max_text_w=None):
    """Render centered text on a transparent canvas_w-wide strip, tightly
    cropped vertically. Returns (path, width, height)."""
    font = _font(fontsize)
    max_text_w = max_text_w or (canvas_w - 2 * pad_x)

    # Wrap long text to fit max_text_w.
    words = text.split()
    lines, cur = [], ""
    tmp_img = Image.new("RGBA", (10, 10))
    tmp_draw = ImageDraw.Draw(tmp_img)
    for w in words:
        trial = (cur + " " + w).strip()
        bbox = tmp_draw.textbbox((0, 0), trial, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_text_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    line_h = fontsize + stroke_width * 2 + 10
    text_block_h = line_h * len(lines)
    canvas_h = text_block_h + 2 * pad_y

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if box:
        draw.rounded_rectangle([0, 0, canvas_w, canvas_h], radius=18, fill=box_fill)

    y = pad_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        w = bbox[2] - bbox[0]
        x = (canvas_w - w) / 2 - bbox[0]
        draw.text((x, y - bbox[1]), line, font=font, fill=fill,
                   stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += line_h

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return str(out_path), canvas_w, canvas_h
