"""README pictures for the 2026-10-29 redesign, from real 0.8.7 window captures.

Inputs are native window captures (DPR 2) from showcase_studio.py run on tag v0.8.7,
one run per interface language, each on a copy of the real recognition run ``run-087``:
``zh-05`` (1440x900) and ``en-05`` / ``ja-05`` / ``ko-05`` (1600x1000, longer labels).

Every feature picture is a crop of one capture. The crop starts from the part that
matters (for example the preview plus the review cards, from the widget geometry the
capture script recorded) and is widened to 16:10 inside the same window, so the six
pictures share one shape without padding. Only cropping, scaling, rounded corners and
palette encoding are applied; no interface text, button or result is redrawn.

Usage: build_assets_087.py <output folder>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imgkit import fit_width, framed, save_png  # noqa: E402

BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
RUNS = BASE / 'runs'
SCALE = 2
ASPECT = 1.6
FEATURE_WIDTH = 1600
HERO_WIDTH = 2000
LANGS = (('zh', ''), ('en', '-en'), ('ja', '-ja'), ('ko', '-ko'))


def load(path):
    return Image.open(path).convert('RGB')


def union(*rects):
    rects = [r for r in rects if r]
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return [x0, y0, x1 - x0, y1 - y0]


def widen(box, size, aspect=ASPECT, down=False):
    """Grow ``box`` to ``aspect`` around its centre (or only downward), kept inside the window."""
    width, height = size
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    if w / h > aspect:
        h = w / aspect
    else:
        w = h * aspect
    if w > width:
        w, h = width, width / aspect
    if h > height:
        h, w = height, height * aspect
    x = min(max(0, cx - w / 2), width - w)
    y = min(max(0, box[1] if down else cy - h / 2), height - h)
    return [round(x), round(y), round(w), round(h)]


def crop(img, box):
    x, y, w, h = box
    return img.crop((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE))


def save_feature(img, path):
    size = (FEATURE_WIDTH, round(FEATURE_WIDTH / ASPECT))
    return save_png(framed(img.resize(size, Image.LANCZOS), radius=22), path, colors=256)


def top_part(img, height, aspect=ASPECT):
    """Top ``height`` px of a dialog capture at ``aspect``, centred horizontally.

    The speaker dialog's lower part is empty space and the Done button.
    """
    width = min(img.width, round(height * aspect))
    left = (img.width - width) // 2
    return img.crop((left, 0, left + width, height))


def shot_rects(result, name):
    row = next(r for r in reversed(result['shots']) if r['name'] == name)
    return row['rects']


def build(lang, suffix, out):
    run = RUNS / f'{lang}-05'
    result_path = run / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {}
    if not result.get('finished'):
        print(f'skip {lang}: {run.name} has not finished')
        return [], None
    shots = run / 'shots'
    size = result['info']['window']['size']
    made, boxes = [], {}

    hero = load(shots / 'studio-hero.png')
    made.append(save_png(framed(fit_width(hero, HERO_WIDTH), radius=18), out / f'workbench{suffix}.png', colors=256))

    # Dialog captures are already 16:10 (the capture script sizes them).
    made.append(save_feature(load(shots / 'link-window-compact.png'), out / f'feature-link{suffix}.png'))
    made.append(save_feature(top_part(load(shots / 'speakers-dialog.png'), 488 * SCALE), out / f'feature-speakers{suffix}.png'))

    rects = shot_rects(result, 'review-cards')
    boxes['review'] = widen(union(rects['video'], rects['review'], *(rects['cards'] or [])), size, down=True)
    made.append(save_feature(crop(load(shots / 'review-cards.png'), boxes['review']), out / f'feature-review{suffix}.png'))

    # Bilingual caption in the lower preview, down to the bottom of the translation lane.
    rects = shot_rects(result, 'studio-hero')
    video = rects['video']
    lanes_bottom = min(r[1] for r in rects['video_tracks'].values())
    anchor = [0, video[1] + video[3] * 0.45, video[0] + video[2], lanes_bottom - (video[1] + video[3] * 0.45)]
    boxes['translate'] = widen(anchor, size)
    made.append(save_feature(crop(hero, boxes['translate']), out / f'feature-translate{suffix}.png'))

    # Razor: the frame where the cut preview is shown, timeline-led.
    recording = result['recordings']['razor']
    frame_index = RAZOR_FRAME.get(lang)
    rects = recording['rects']
    timeline = rects['timeline']
    tracks_top = min(r[1] for r in rects['video_tracks'].values())
    anchor = [0, timeline[1] - 56, round(size[0] * 0.78), tracks_top - (timeline[1] - 56)]
    boxes['razor'] = widen(anchor, size)
    frame = load(run / 'frames' / 'razor' / f'{frame_index:04d}.png')
    made.append(save_feature(crop(frame, boxes['razor']), out / f'feature-razor{suffix}.png'))

    rects = shot_rects(result, 'style-final')
    boxes['style'] = widen(union(rects['video'], rects['drawer']), size)
    made.append(save_feature(crop(load(shots / 'style-final.png'), boxes['style']), out / f'feature-style{suffix}.png'))
    return made, boxes


# Razor recording frame that shows the cut preview (chosen by eye per run).
RAZOR_FRAME = {}


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    frames = json.loads((BASE / 'razor-frames.json').read_text('utf8'))
    RAZOR_FRAME.update(frames)
    made, crops = [], {}
    for lang, suffix in LANGS:
        files, boxes = build(lang, suffix, out)
        if boxes is None:
            continue
        made += files
        crops[lang] = dict(boxes, razor_frame=RAZOR_FRAME[lang])
    (BASE / 'crops-087.json').write_text(json.dumps(crops, indent=1), 'utf8')
    total = 0
    for path in made:
        total += path.stat().st_size
        with Image.open(path) as im:
            print(f'{path.name:28s} {path.stat().st_size / 1024:7.0f} KiB', im.size)
    print(f'total {total / 1048576:.2f} MiB')


if __name__ == '__main__':
    main()
