"""Shared helpers for README images: crop, scale, rounded frame, GIF encode."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FFMPEG = 'ffmpeg'


def load(path) -> Image.Image:
    return Image.open(path).convert('RGB')


def crop_logical(img: Image.Image, box, scale: float = 2.0) -> Image.Image:
    """Crop with a box given in logical (DPR 1) pixels."""
    x, y, w, h = box
    return img.crop((int(x * scale), int(y * scale), int((x + w) * scale), int((y + h) * scale)))


def fit_width(img: Image.Image, width: int) -> Image.Image:
    if img.width == width:
        return img
    height = round(img.height * width / img.width)
    return img.resize((width, height), Image.LANCZOS)


def framed(img: Image.Image, radius: int = 18, border=(255, 255, 255, 34), pad: int = 0) -> Image.Image:
    """Rounded corners with a hairline border on a transparent canvas.

    Transparent outside the corners, so the image sits cleanly on both the
    light and dark GitHub themes.
    """
    w, h = img.size
    scale = 3
    mask = Image.new('L', (w * scale, h * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=radius * scale, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    rgba = img.convert('RGBA')
    rgba.putalpha(mask)
    out.alpha_composite(rgba, (pad, pad))
    if border:
        ring = Image.new('L', (w * scale, h * scale), 0)
        d = ImageDraw.Draw(ring)
        d.rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=radius * scale, outline=255, width=2 * scale)
        ring = ring.resize((w, h), Image.LANCZOS)
        layer = Image.new('RGBA', (w, h), border[:3] + (0,))
        layer.putalpha(ImageChops.multiply(ring, Image.new('L', (w, h), border[3])))
        out.alpha_composite(layer, (pad, pad))
    return out


def save_png(img: Image.Image, path, colors: int | None = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if colors:
        # Palette PNG keeps flat UI crisp at a fraction of the size.
        if img.mode == 'RGBA':
            q = img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        else:
            q = img.convert('RGB').quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
    else:
        img.save(path, optimize=True)
    return path


def encode_gif(frames_dir: Path, pattern: str, out: Path, fps: float, width: int, colors: int = 192,
               durations: list[float] | None = None):
    """Two-pass ffmpeg GIF with one global palette and diff-rect frames."""
    out.parent.mkdir(parents=True, exist_ok=True)
    palette = frames_dir / '_palette.png'
    scale = f'scale={width}:-1:flags=lanczos'
    if durations:
        concat = frames_dir / '_concat.txt'
        files = sorted(frames_dir.glob(pattern))
        lines = []
        for f, d in zip(files, durations):
            lines += [f"file '{f.as_posix()}'", f'duration {d:.3f}']
        lines.append(f"file '{files[-1].as_posix()}'")
        concat.write_text('\n'.join(lines), 'utf8')
        source = ['-f', 'concat', '-safe', '0', '-i', str(concat)]
        timing = ''
    else:
        source = ['-framerate', str(fps), '-i', str(frames_dir / pattern)]
        timing = ''
    subprocess.run([FFMPEG, '-v', 'error', '-y', *source, '-vf',
                    f'{scale},palettegen=max_colors={colors}:stats_mode=full:reserve_transparent=0', str(palette)], check=True)
    subprocess.run([FFMPEG, '-v', 'error', '-y', *source, '-i', str(palette), '-lavfi',
                    f'{scale}{timing}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle', '-loop', '0', str(out)],
                   check=True)
    return out
