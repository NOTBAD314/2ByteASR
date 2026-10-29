"""README pictures from the 2026-10-29 film runs: real 0.8.7 window recordings.

Inputs (showcase_studio.py on tag v0.8.7, DPR 2):
- ``<lang>-f2``: the Tears of Steel clip (CC BY 3.0, Blender Foundation), recognised for
  real in ``run-tos``; scenes film_speakers, film_razor, film_translate, film_hero,
  film_play, link, film_style.
- ``<lang>-05``: the review recording of the Chinese sample (0.8.7 builds no model
  candidates for English lines); only the candidate strip is used.

Every animated picture is a sequence of real frames from one window, cropped the same way
for every frame and kept at the captured timing. Only cropping, scaling, rounded corners,
palette/WebP encoding and, for the review strip, centring on a plate of the app's own
background colour are applied.

Usage: build_assets_film.py <output folder>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_assets_087 import ASPECT, RUNS, SCALE, crop, load, shot_rects, top_part, union, widen  # noqa: E402
from imgkit import fit_width, framed, save_png  # noqa: E402

LANGS = (('en', ''), ('zh', '-zh'), ('ja', '-ja'), ('ko', '-ko'))
WIDTH = 1200
PLATE = (27, 22, 31)


def plate(img, aspect=ASPECT, fill=PLATE):
    w = img.width
    h = round(w / aspect)
    if img.height > h:
        h = img.height
        w = round(h * aspect)
    canvas = Image.new('RGB', (w, h), fill)
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


def review_last(run, strip, first=3):
    """Last frame showing the adopted reading.

    The candidate strip changes twice: when a reading is adopted and when the
    review moves on to the next line. The clip ends just before the second change.
    """
    import numpy as np
    files = sorted((run / 'frames' / 'review').glob('[0-9][0-9][0-9][0-9].png'))
    crops = [np.asarray(crop(load(f), strip).convert('L'), dtype=np.int16) for f in files]
    changes = [i for i in range(first + 1, len(crops)) if np.abs(crops[i] - crops[i - 1]).mean() > 0.3]
    return changes[1] - 1 if len(changes) > 1 else len(files) - 1


def animate(run, name, out, cut, tail=2.0, first=0, last=None, quality=80):
    folder = run / 'frames' / name
    stamps = json.loads((run / 'result.json').read_text('utf8'))['recordings'][name]['stamps']
    files = sorted(folder.glob('[0-9][0-9][0-9][0-9].png'))
    last = len(files) - 1 if last is None else last
    frames, durations = [], []
    for index in range(first, last + 1):
        img = cut(load(files[index]))
        img = img.resize((WIDTH, round(WIDTH / ASPECT)), Image.LANCZOS)
        frames.append(framed(img, radius=16))
        if index < last:
            durations.append(int(max(60, min(1500, (stamps[index + 1] - stamps[index]) * 1000))))
    durations.append(int(tail * 1000))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   quality=quality, method=6, lossless=False)
    return out


def build(lang, suffix, out):
    run = RUNS / f'{lang}-f2'
    path = run / 'result.json'
    result = json.loads(path.read_text('utf8')) if path.is_file() else {}
    if not result.get('finished'):
        print(f'skip {lang}')
        return []
    size = result['info']['window']['size']
    shots = run / 'shots'
    made = [save_png(framed(fit_width(load(shots / 'studio-hero.png'), 2000), radius=18),
                     out / f'workbench{suffix}.png', colors=256)]

    rects = result['recordings']['play']['rects']
    video = rects['video']
    tracks_top = min(r[1] for r in rects['video_tracks'].values())
    box = widen([0, video[1], video[0] + video[2], tracks_top - video[1]], size)
    made.append(animate(run, 'play', out / f'feature-translate{suffix}.webp', lambda im: crop(im, box)))

    rects = result['recordings']['style']['rects']
    box = widen(union(rects['video'], rects['drawer']), size)
    made.append(animate(run, 'style', out / f'feature-style{suffix}.webp', lambda im: crop(im, box)))

    rects = result['recordings']['razor']['rects']
    timeline = rects['timeline']
    tracks_top = min(r[1] for r in rects['video_tracks'].values())
    box = widen([0, timeline[1] - 56, round(size[0] * 0.78), tracks_top - (timeline[1] - 56)], size)
    made.append(animate(run, 'razor', out / f'feature-razor{suffix}.webp', lambda im: crop(im, box)))

    review_run = RUNS / f'{lang}-05'
    review_result = json.loads((review_run / 'result.json').read_text('utf8'))
    r = shot_rects(review_result, 'review-cards')
    strip = union(r['review'], *(r['cards'] or []))
    strip = [strip[0] - 8, strip[1] + 4, strip[2] + 16, strip[3] + 4]
    made.append(animate(review_run, 'review', out / f'feature-review{suffix}.webp',
                        lambda im: plate(crop(im, strip)), first=3, last=review_last(review_run, strip)))

    made.append(animate(run, 'speakers', out / f'feature-speakers{suffix}.webp',
                        lambda im: top_part(im, 488 * SCALE)))

    link = load(shots / 'link-window-compact.png').resize((WIDTH, round(WIDTH / ASPECT)), Image.LANCZOS)
    made.append(save_png(framed(link, radius=16), out / f'feature-link{suffix}.png', colors=256))
    return made


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for lang, suffix in LANGS:
        made += build(lang, suffix, out)
    total = 0
    for path in made:
        total += path.stat().st_size
        with Image.open(path) as im:
            print(f'{path.name:28s} {path.stat().st_size / 1024:7.0f} KiB', im.size, getattr(im, 'n_frames', 1))
    print(f'total {total / 1048576:.2f} MiB')


if __name__ == '__main__':
    main()
