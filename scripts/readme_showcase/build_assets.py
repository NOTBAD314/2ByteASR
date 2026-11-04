"""Turn the real 0.7.1 captures into README assets (docs/assets/readme/*), 2026-10-14.

Inputs are native window captures (DPR 2) from showcase_run.py and showcase_studio.py
run on the v0.7.1 source:

- run-071: real recognition of the test-card sample (home with media, progress, completion)
- zh-01:   Chinese UI at 1320x880 (razor and review recordings, glossary, workshop, themes)
- zh-02:   Chinese UI at 1440x900 (studio hero, speaker manager, export result)
- en-01 / ja-01: English / Japanese UI at 1440x900

Only cropping, scaling, layering on a plain background, rounded frames, palette/WebP
encoding and one redaction (the local output folder on the export page) are applied.
No interface text, button or recognition result is redrawn.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imgkit import framed, fit_width, save_png  # noqa: E402

BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
RUNS = BASE / 'runs'
OUT = BASE / 'assets'
OUT.mkdir(exist_ok=True)
SCALE = 2  # captures are DPR 2 (QT_SCALE_FACTOR=2)
# Plain dark ground with static grain, as on the product website (no gradient, no glow).
GROUND = (22, 17, 26)
# Recording crops (logical px) in the 1600x1000 English/Japanese window.
WIDE_RAZOR = (0, 496, 1600, 480)
WIDE_REVIEW = (288, 372, 944, 176)
WIDE_GLOSSARY = (264, 116, 1320, 864)
# Speaker manager without its window title and tab row (dialog is 1052x772 in every language).
SPEAKER_BOX = (0, 76, 1052, 696)


def load(path):
    return Image.open(path).convert('RGB')


def crop(img, box):
    x, y, w, h = box
    return img.crop((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE))


def grain_ground(size, radius):
    w, h = size
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 3.2, (h, w, 1))
    base = np.clip(np.array(GROUND, float)[None, None, :] + noise, 0, 255).astype(np.uint8)
    ground = Image.fromarray(base, 'RGB').convert('RGBA')
    mask = Image.new('L', (w * 3, h * 3), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius=radius * 3, fill=255)
    ground.putalpha(mask.resize((w, h), Image.LANCZOS))
    return ground


def shadow(canvas, box, radius, strength=150, blur=26, offset=(0, 14)):
    x0, y0, x1, y1 = box
    layer = Image.new('L', canvas.size, 0)
    ImageDraw.Draw(layer).rounded_rectangle((x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]),
                                            radius=radius, fill=strength)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    dark = Image.new('RGBA', canvas.size, (0, 0, 0, 255))
    dark.putalpha(layer)
    canvas.alpha_composite(dark)


def hero(studio_path, home_path, name, width=2000):
    """Studio in front at almost full width; home behind it, showing its title bar above.

    Studio stays fully visible (nothing is laid over it). Home is the supporting window:
    only its top band shows, enough to read the app name and the recognition row.
    """
    margin, peek, radius = 40, 150, 16
    studio = framed(fit_width(load(studio_path), width - margin * 2), radius=radius)
    home = framed(fit_width(load(home_path), round(width * 0.62)), radius=radius)
    height = margin + peek + studio.height + margin
    canvas = grain_ground((width, height), 30)
    home_xy = (width - margin - home.width - 36, margin)
    studio_xy = (margin, margin + peek)
    shadow(canvas, (*home_xy, home_xy[0] + home.width, home_xy[1] + home.height), radius, 120, 20)
    canvas.alpha_composite(home, home_xy)
    shadow(canvas, (*studio_xy, studio_xy[0] + studio.width, studio_xy[1] + studio.height), radius, 190, 28)
    canvas.alpha_composite(studio, studio_xy)
    return save_png(canvas, OUT / name, colors=256)


def png(src, name, width=1760, box=None, radius=18, edit=None):
    img = load(src)
    if edit:
        img = edit(img)
    if box:
        img = crop(img, box)
    return save_png(framed(fit_width(img, width), radius=radius), OUT / name, colors=256)


def webp_from_frames(run, rec_name, name, box, width, first=0, last=None, tail=2.4, lead=0.0, quality=82):
    """Real frame recording -> animated WebP, keeping the captured timing."""
    folder = RUNS / run / 'frames' / rec_name
    stamps = json.loads((RUNS / run / 'result.json').read_text('utf8'))['recordings'][rec_name]['stamps']
    files = sorted(folder.glob('[0-9][0-9][0-9][0-9].png'))
    last = len(files) - 1 if last is None else last
    frames, durations = [], []
    for index in range(first, last + 1):
        frames.append(framed(fit_width(crop(load(files[index]), box), width), radius=14))
        if index < last:
            durations.append(int(max(40, min(1600, (stamps[index + 1] - stamps[index]) * 1000))))
    durations.append(int(tail * 1000))
    # Extra time on the first frame so the reader can take in the starting state.
    durations[0] += int(lead * 1000)
    target = OUT / name
    frames[0].save(target, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   quality=quality, method=6, lossless=False)
    return target


def redact_box(img, box_logical, fill):
    d = ImageDraw.Draw(img)
    x, y, w, h = box_logical
    d.rounded_rectangle((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE), radius=6 * SCALE, fill=fill)
    return img


def themes_strip(run, name):
    keys = ('grape', 'warm', 'plum', 'lavender', 'slate')
    tile_w, gap = 640, 22
    tiles = [fit_width(load(RUNS / run / 'shots' / f'theme-{k}-studio.png'), tile_w) for k in keys]
    h = tiles[0].height
    canvas = Image.new('RGBA', (tile_w * 3 + gap * 2, h * 2 + gap), (0, 0, 0, 0))
    positions = [(0, 0), (tile_w + gap, 0), ((tile_w + gap) * 2, 0),
                 ((tile_w + gap) // 2, h + gap), ((tile_w + gap) // 2 + tile_w + gap, h + gap)]
    for tile, pos in zip(tiles, positions):
        canvas.alpha_composite(framed(tile, radius=12), pos)
    return save_png(canvas, OUT / name, colors=256)


def main():
    made = []
    run = RUNS / 'run-071' / 'shots'
    zh1, zh2 = RUNS / 'zh-01' / 'shots', RUNS / 'zh-02' / 'shots'
    # Hero and the full-window screenshots (Chinese UI).
    made.append(hero(zh2 / 'studio-hero.png', run / '02-home-media.png', 'hero.png'))
    made.append(png(zh2 / 'studio-hero.png', 'studio.png'))
    made.append(png(run / '02-home-media.png', 'home.png'))
    made.append(png(run / 'progress-0088.png', 'progress.png'))
    made.append(png(run / '04-completion.png', 'completion.png'))
    # Term library: the page body without the shared title bar and left navigation.
    made.append(png(zh1 / 'page-terms.png', 'glossary.png', box=(256, 116, 1050, 760)))
    made.append(png(zh1 / 'page-workshop.png', 'workshop.png'))
    made.append(png(zh2 / 'speakers-dialog.png', 'speakers.png', width=1600, box=SPEAKER_BOX))
    # Speaker lanes of the 1440x900 hero (timeline area only).
    made.append(png(zh2 / 'studio-hero.png', 'tracks.png', box=(0, 590, 1440, 270)))
    # Export result: cover only the local output folder (it contains the Windows user name).
    made.append(png(zh2 / 'export-done.png', 'export.png',
                    edit=lambda im: redact_box(im, (892, 594, 428, 34), (36, 32, 40))))
    made.append(themes_strip('zh-01', 'themes.png'))
    # Real recordings: razor (merge preview, then the razor cut on word boundaries) and review.
    # The review clip shows only the candidate strip: after adopting, the paused preview above it
    # drew an empty caption box until the next refresh (seen in 0.7.1, noted in the asset notes).
    made.append(webp_from_frames('zh-01', 'razor', 'razor.webp', box=(0, 440, 1320, 430), width=1320))
    made.append(webp_from_frames('zh-01', 'review', 'review.webp', box=(284, 306, 670, 174), width=1005,
                                 first=3, last=14, lead=1.5, tail=3.0))
    for lang in ('en', 'ja', 'ko'):
        # English, Japanese and Korean labels are longer: these runs use a 1600x1000 window.
        runs = RUNS / f'{lang}-02'
        result = runs / 'result.json'
        if not result.is_file() or not json.loads(result.read_text('utf8')).get('finished'):
            continue
        shots = runs / 'shots'
        made.append(hero(shots / 'studio-hero.png', shots / 'home-after.png', f'hero-{lang}.png'))
        made.append(png(shots / 'studio-hero.png', f'studio-{lang}.png'))
        made.append(png(shots / 'home-after.png', f'home-{lang}.png'))
        made.append(png(shots / 'page-terms.png', f'glossary-{lang}.png', box=WIDE_GLOSSARY))
        made.append(png(shots / 'page-workshop.png', f'workshop-{lang}.png'))
        made.append(png(shots / 'speakers-dialog.png', f'speakers-{lang}.png', width=1600, box=SPEAKER_BOX))
        made.append(webp_from_frames(f'{lang}-02', 'razor', f'razor-{lang}.webp', box=WIDE_RAZOR, width=1320))
        made.append(webp_from_frames(f'{lang}-02', 'review', f'review-{lang}.webp', box=WIDE_REVIEW, width=1180,
                                     first=3, last=14, lead=1.5, tail=3.0))
    total = 0
    for path in made:
        total += path.stat().st_size
        with Image.open(path) as im:
            print(f'{path.name:22s} {path.stat().st_size / 1024:8.0f} KiB', im.size, getattr(im, 'n_frames', 1))
    print(f'total {total / 1048576:.2f} MiB')


if __name__ == '__main__':
    main()
