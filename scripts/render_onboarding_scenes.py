"""Build the onboarding animations (2026-10-14).

1. ``tools/node/node.exe scripts/render_onboarding_frames.mjs <frames> [fps] [source.html]`` captures
   assets/onboarding/source/scenes.html (first-run chooser) or tutorial.html (tutorial
   gestures) frame by frame (bundled Chromium);
2. this script packs each ``<scene>-<theme>`` folder into a transparent, looping
   animated WebP plus a still picture: assets/onboarding/ for the chooser
   (quick_setup.py), assets/onboarding/tutorial/ for the tutorial (home_tour.py).

usage: python scripts/render_onboarding_scenes.py <frames-dir> [fps] [out-subdir]
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# The idle picture of each card: a moment that already tells the story.
STILL_AT = {'local': 0.25, 'cloud': 0.66, 'light': 0.8, 'apple': 0.9}


def pack(frames_dir: Path, fps: int = 24, subdir: str = '') -> None:
    out = ROOT / 'assets' / 'onboarding' / subdir if subdir else ROOT / 'assets' / 'onboarding'
    out.mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        frames = [Image.open(path).convert('RGBA') for path in sorted(folder.glob('*.png'))]
        if not frames:
            continue
        still = frames[min(len(frames) - 1, int(len(frames) * STILL_AT.get(folder.name.rsplit('-', 1)[0], 0.7)))]
        still.save(out / f'{folder.name}-still.png', optimize=True)
        target = out / f'{folder.name}.webp'
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=round(1000 / fps), loop=0,
                       lossless=False, quality=80, method=4)
        print(f'{target.relative_to(ROOT)}  {len(frames)} frames  {target.stat().st_size // 1024} KB')


if __name__ == '__main__':
    pack(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 24, sys.argv[3] if len(sys.argv) > 3 else '')
