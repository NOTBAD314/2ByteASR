"""Render every 兔白 move, sticker and reaction to animated WebP with the real BunnyMascot (2026-11-14).

The review page for the user's acceptance shows these files: each is drawn by
``twobyteasr.design.bunny_mascot.BunnyMascot`` itself, with its clock stepped frame by frame, so
what the page shows is what the app draws. Also writes ``manifest.json`` (names, titles, kinds)
and ``contact.png`` (one frame of each, for a quick look).

usage: python -X utf8 scripts/render_bunny_moves.py --output tmp/<folder> [--height 220] [--fps 25]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--height', type=int, default=220)
    parser.add_argument('--fps', type=int, default=25)
    parser.add_argument('--only', default='', help='comma-separated names (moves, stickers or acts)')
    parser.add_argument('--kinds', default='move,sticker,act,scene', help='which kinds to render')
    args = parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    from PIL import Image
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QRegion
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design.bunny_mascot import BunnyMascot
    from twobyteasr.design.bunny_moves import ACTS, MOVES, STICKERS

    mascot = BunnyMascot(height=args.height, motion='bob')
    mascot.reduced_motion = False
    mascot.resize(mascot.size())
    deadline = time.time() + 20
    while mascot._layers() is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if mascot._layers() is None:
        print('mascot pictures did not load', file=sys.stderr)
        return 1
    clock = {'now': 1000.0}
    mascot.clock = lambda: clock['now']
    mascot._started = clock['now']
    mascot._next_blink = clock['now'] + 10 ** 6       # no random blinks in the recordings

    def frame() -> Image.Image:
        image = QImage(mascot.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        mascot.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        data = bytes(image.constBits())
        return Image.frombuffer('RGBA', (image.width(), image.height()), data, 'raw', 'RGBA', image.bytesPerLine(), 1).copy()

    def record(name: str, seconds: float, start, tail: float = 0.5, hook=None) -> list:
        mascot.stop_move()
        mascot.unstick()
        mascot.ear_bias = mascot.lean = 0.0
        mascot._sway = mascot._sway_v = 0.0
        clock['now'] += 5.0
        mascot._sway_at = clock['now']
        start()
        frames = []
        count = max(2, round((seconds + tail) * args.fps))
        for index in range(count):
            if hook is not None:
                hook(index / args.fps)
            frames.append(frame())
            clock['now'] += 1.0 / args.fps
        path = out / f'{name}.webp'
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=round(1000 / args.fps), loop=0,
                       lossless=False, quality=80, method=4, background=(0, 0, 0, 0))
        return frames

    wanted = {name for name in args.only.split(',') if name}
    manifest, stills = [], []
    kinds = set(args.kinds.split(','))
    for name, move in MOVES.items():
        if 'move' not in kinds or (wanted and name not in wanted):
            continue
        seconds = move.seconds * (2 if move.loop else 1)
        frames = record(f'move-{name}', seconds, lambda name=name: mascot.play(name))
        manifest.append(dict(kind='move', name=name, title=move.title, file=f'move-{name}.webp', loop=move.loop,
                             seconds=move.seconds))
        stills.append((move.title, frames[len(frames) // 3]))
    for name, sticker in STICKERS.items():
        if 'sticker' not in kinds or (wanted and name not in wanted):
            continue
        seconds = sticker.seconds * (2 if sticker.loop else 1)
        frames = record(f'sticker-{name}', seconds, lambda name=name: mascot.stick(name))
        manifest.append(dict(kind='sticker', name=name, title=sticker.title, file=f'sticker-{name}.webp',
                             loop=sticker.loop, seconds=sticker.seconds))
        stills.append((sticker.title, frames[len(frames) // 3]))
    for name, act in ACTS.items():
        if 'act' not in kinds or (wanted and name not in wanted):
            continue
        seconds = max(MOVES[act.move].seconds if act.move else 0, STICKERS[act.sticker].seconds if act.sticker else 0)
        frames = record(f'act-{name}', seconds, lambda name=name: mascot.act(name))
        manifest.append(dict(kind='act', name=name, title=act.title, when=act.when, move=act.move,
                             sticker=act.sticker, file=f'act-{name}.webp'))
        stills.append((act.title, frames[len(frames) // 3]))
    import math
    scenes = (   # C: how she reacts to the app, as the chat drives her
        ('c1', '查资料：拿放大镜左右看', 4.0, lambda: (mascot.play('search'), mascot.stick('magnifier')), None),
        ('c2', '帮我做：飘到控件旁推一下', 1.6, lambda: (mascot.play('push'), mascot.stick('wrench')), None),
        ('c3', '说到某个按钮：耳朵朝那边歪', 2.4, lambda: None,
         lambda t: setattr(mascot, 'ear_bias', 28.0 * math.sin(min(1.0, t / .4) * math.pi / 2) * (1 if t < 1.2 else -1))),
        ('c4', '等 AI 回答：抱着钥匙圈想', 4.0, lambda: (mascot.play('think'), mascot.stick('dots')), None),
        ('c5', '出错：眼镜起雾擦一擦', 2.4, lambda: (mascot.play('fog'), mascot.stick('sweat')), None),
        ('c6', '你在打字：往输入框靠', 2.0, lambda: None,
         lambda t: setattr(mascot, 'lean', -12.0 * math.sin(min(1.0, t / .5) * math.pi / 2) if t < 1.3
                           else -12.0 * max(0.0, 1 - (t - 1.3) / .5))),
        ('c7', '拖动主窗口：跟着晃', 2.4, lambda: mascot.nudge(70), None),
        ('c8', '戳太多次：哼，转过去', 2.6, lambda: mascot.act('hmph'), None),
        ('c9', '鼠标靠近：耳朵跟着鼠标', 3.0, lambda: None,
         lambda t: setattr(mascot, 'ear_bias', 26.0 * math.sin(t * 2 * math.pi / 1.5))),
        ('c10', '深夜还在用：打哈欠', 2.4, lambda: mascot.act('sleepy'), None),
        ('c11', '识别完成：跳出来欢呼', 1.8, lambda: mascot.act('cheer'), None),
        ('a16', '很久没互动：打瞌睡，被叫醒', 4.2, lambda: (mascot.play('doze'), mascot.stick('zzz')),
         lambda t: (mascot.play('wake'), mascot.unstick('zzz'), mascot.stick('exclaim')) if abs(t - 3.2) < .02 else None),
        ('a17', '被提起来：小脚乱踢', 2.0, lambda: mascot.play('struggle'), None),
        ('a11', '被扔太猛：头晕', 2.6, lambda: mascot.act('dizzy'), None),
    )
    for key, title, seconds, start, hook in scenes:
        if 'scene' not in kinds or (wanted and key not in wanted):
            continue
        frames = record(f'scene-{key}', seconds, start, hook=hook)
        manifest.append(dict(kind='scene', name=key, title=title, file=f'scene-{key}.webp'))
        stills.append((title, frames[len(frames) // 3]))
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    if stills:
        w, h = stills[0][1].size
        cols = 8
        rows = (len(stills) + cols - 1) // cols
        sheet = Image.new('RGBA', (cols * w, rows * h), (235, 228, 217, 255))
        for index, (_title, image) in enumerate(stills):
            sheet.alpha_composite(image, ((index % cols) * w, (index // cols) * h))
        sheet.save(out / 'contact.png')
    print(json.dumps(dict(output=str(out), items=len(manifest)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
