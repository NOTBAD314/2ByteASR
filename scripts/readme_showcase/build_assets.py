"""Turn the real captures into README assets (docs/assets/readme/*).

Inputs are the native window captures from showcase_run.py / showcase_studio.py
and the MP4 the app exported. Only framing, scaling, cropping, palette encoding
and (on one image) a redaction bar over a local file path are applied.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imgkit import framed, fit_width, save_png  # noqa: E402

BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
RUNS = BASE / 'runs'
OUT = BASE / 'assets'
OUT.mkdir(exist_ok=True)
SCALE = 2  # captures are DPR 2 (QT_SCALE_FACTOR=2)


def load(path):
    return Image.open(path).convert('RGB')


def png(src, name, width=1760, crop=None, radius=22, colors=None, edit=None, aspect=None):
    img = load(src)
    if edit:
        img = edit(img)
    if crop:
        x, y, w, h = crop
        img = img.crop((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE))
    img = fit_width(img, width)
    card = framed(img, radius=radius)
    if aspect and card.width / card.height < aspect:
        # Transparent side padding so side-by-side images share one height.
        wide = Image.new('RGBA', (round(card.height * aspect), card.height), (0, 0, 0, 0))
        wide.alpha_composite(card, ((wide.width - card.width) // 2, 0))
        card = wide
    out = save_png(card, OUT / name, colors=colors)
    return out


def gif_from_frames(folder: Path, stamps, name, width=1100, crop=None, colors=200, tail=1.6, speed=1.0):
    frames = sorted(folder.glob('[0-9][0-9][0-9][0-9].png'))
    work = BASE / 'work' / name
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob('*.png'):
        old.unlink()
    for i, f in enumerate(frames):
        img = load(f)
        if crop:
            x, y, w, h = crop
            img = img.crop((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE))
        fit_width(img, width).save(work / f'{i:04d}.png')
    durations = [max(0.04, min(1.6, (b - a) / speed)) for a, b in zip(stamps, stamps[1:])] + [tail]
    concat = work / '_concat.txt'
    lines = []
    for i, d in enumerate(durations):
        lines += [f"file '{(work / f'{i:04d}.png').as_posix()}'", f'duration {d:.3f}']
    lines.append(f"file '{(work / f'{len(durations) - 1:04d}.png').as_posix()}'")
    concat.write_text('\n'.join(lines), 'utf8')
    palette = work / '_palette.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat),
                    '-vf', f'palettegen=max_colors={colors}:stats_mode=full', str(palette)], check=True)
    target = OUT / name
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-i', str(palette),
                    '-lavfi', 'paletteuse=dither=none:diff_mode=rectangle', '-loop', '0', '-vsync', 'vfr', str(target)],
                   check=True)
    return target


def gif_from_video(video: Path, name, start, duration, width=880, fps=12, colors=128):
    target = OUT / name
    palette = BASE / 'work' / f'{name}.palette.png'
    palette.parent.mkdir(parents=True, exist_ok=True)
    vf = f'fps={fps},scale={width}:-1:flags=lanczos'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(duration), '-i', str(video),
                    '-vf', f'{vf},palettegen=max_colors={colors}:stats_mode=diff', str(palette)], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(duration), '-i', str(video), '-i', str(palette),
                    '-lavfi', f'{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', '-loop', '0',
                    str(target)], check=True)
    return target


def redact_box(img, box_logical, fill):
    d = ImageDraw.Draw(img)
    x, y, w, h = box_logical
    d.rounded_rectangle((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE), radius=6 * SCALE, fill=fill)
    return img


def themes_strip(lang_runs, name):
    keys = ('grape', 'warm', 'plum', 'lavender', 'slate')
    shots = [load(lang_runs / 'shots' / f'theme-{k}-home.png') for k in keys]
    tile_w = 640
    tiles = [fit_width(s, tile_w) for s in shots]
    gap = 22
    width = tile_w * 3 + gap * 2
    # 3 + 2 layout, second row centered
    h = tiles[0].height
    canvas = Image.new('RGBA', (width, h * 2 + gap), (0, 0, 0, 0))
    positions = [(0, 0), (tile_w + gap, 0), ((tile_w + gap) * 2, 0),
                 ((tile_w + gap) // 2, h + gap), ((tile_w + gap) // 2 + tile_w + gap, h + gap)]
    for tile, pos in zip(tiles, positions):
        canvas.alpha_composite(framed(tile, radius=12), pos)
    return save_png(canvas, OUT / name, colors=256)


def main():
    zh = RUNS / 'final-02'
    rec = json.loads((zh / 'result.json').read_text('utf8'))['recordings']
    made = []
    shots = zh / 'shots'
    made.append(png(RUNS / 'final-04' / 'shots' / 'studio-hero.png', 'studio.png', colors=256))
    made.append(png(shots / 'home-after.png', 'home.png', colors=256))
    made.append(png(RUNS / 'run-01' / 'shots' / 'progress-0118.png', 'progress.png', colors=256))
    made.append(png(RUNS / 'run-01' / 'shots' / '04-completion.png', 'completion.png', colors=256))
    made.append(png(shots / 'page-terms.png', 'glossary.png', colors=256))
    made.append(png(shots / 'page-workshop.png', 'workshop.png', colors=256))
    made.append(png(shots / 'speakers-dialog.png', 'speakers.png', width=1400, colors=256, aspect=1.5))
    # Export result: hide only the local output folder text.
    made.append(png(shots / 'export-done.png', 'export.png', colors=256,
                    edit=lambda im: redact_box(im, (815, 598, 382, 26), (62, 55, 68))))
    made.append(themes_strip(zh, 'themes.png'))
    # Feature clips are cropped to the part of the window where the action happens.
    made.append(gif_from_frames(zh / 'frames' / 'razor', rec['razor']['stamps'], 'razor.gif',
                                width=1320, crop=(0, 445, 1320, 425)))
    made.append(gif_from_frames(zh / 'frames' / 'review', rec['review']['stamps'], 'review.gif',
                                width=1096, crop=(284, 300, 668, 440)))
    made.append(png(RUNS / 'final-04' / 'shots' / 'studio-hero.png', 'tracks.png', width=1760, colors=256,
                    crop=(0, 585, 1320, 290)))
    for lang, run in (('en', 'wide-en2'), ('ja', 'wide-ja2')):
        folder = RUNS / run / 'shots'
        if not folder.is_dir():
            continue
        for src, name, width in (('studio-hero', 'studio', 1760), ('home-after', 'home', 1760),
                                 ('page-workshop', 'workshop', 1760), ('page-terms', 'glossary', 1760),
                                 ('speakers-dialog', 'speakers', 1400)):
            if (folder / f'{src}.png').is_file():
                made.append(png(folder / f'{src}.png', f'{name}-{lang}.png', width=width, colors=256,
                                aspect=1.5 if name == 'speakers' else None))
    total = 0
    for path in made:
        total += path.stat().st_size
        print(f'{path.name:18s} {path.stat().st_size / 1024:8.0f} KiB', Image.open(path).size)
    print(f'total {total / 1048576:.2f} MiB')


if __name__ == '__main__':
    main()
