"""README banner v2: brand + three differentiators, proved by two real UI crops.

Visual language follows the product website (website/DESIGN.md, 2026-10-09):
solid dark background with static grain, no gradients or glows; chapter
colours violet (recognise), apricot (review), berry (refine).

Right side: (1) the review strip where MOSS/FireRed and Qwen3-ASR disagree,
(2) the timeline with the razor preview card and the two speaker tracks.
Both crops come from native window captures; nothing in them is redrawn.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imgkit import framed  # noqa: E402

BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
REPO = Path(__file__).resolve().parents[2]
OUT = BASE / 'assets'
RUNS = BASE / 'runs'
HEAVY = str(REPO / 'assets/fonts/SourceHanSansSC-Heavy.otf')
MEDIUM = str(REPO / 'assets/fonts/SourceHanSansSC-Medium.otf')
ICON = REPO / 'assets/2byteasr-icon-transparent.png'
W, H = 1760, 660
SCALE = 2
COLORS = ((164, 138, 217), (236, 141, 176), (214, 149, 124))  # violet, berry-tx, apricot

THEMES = {
    'dark': dict(bg=(23, 18, 30), title=(244, 238, 233), sub=(236, 141, 176), body=(206, 196, 203), muted=(160, 148, 158),
                 border=(255, 255, 255, 40), shadow=(0, 0, 0, 150), pill=(33, 26, 41), pill_text=(244, 238, 233)),
}
TEXT = {
    'zh': dict(tagline='游戏实况字幕，从识别到成片',
               points=('三个模型各听一遍，分歧自动标出', '每个字都有时间，剃刀切在字缝', '说话人自动分轨，游戏术语可复用'),
               pills=('① 三个模型的分歧', '② 字级切点　③ 说话人分轨'), note='右侧均为软件真实界面截图'),
    'en': dict(tagline='Game stream subtitles, from recognition to final cut',
               points=('Three models listen; disagreements get flagged', 'Every character is timed; cut between characters',
                       'One track per speaker; reusable game term libraries'),
               pills=('① Where the models disagree', '② Character-level cut   ③ Speaker tracks'),
               note='Real screenshots of the app'),
    'ja': dict(tagline='ゲーム実況の字幕を、認識から完成動画まで',
               points=('3 つのモデルが聞き取り、食い違いを表示', '1 文字ずつ時刻付き、文字の境目でカット', '話者ごとにトラック、用語集を再利用'),
               pills=('① モデル間の食い違い', '② 文字単位のカット　③ 話者トラック'), note='右側はすべて実際のアプリ画面'),
}


def background(t):
    """Solid colour plus a static grain, like the website."""
    rng = np.random.default_rng(20261009)
    base = np.empty((H, W, 3), float)
    base[:] = t['bg']
    base += rng.normal(0, 2.0, (H, W, 1))
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert('RGBA')


def crop(path, box):
    x, y, w, h = box
    return Image.open(path).convert('RGB').crop((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE))


def fit_font(draw, text, font_path, size, max_width, minimum=14):
    while size > minimum:
        font = ImageFont.truetype(font_path, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 1
    return ImageFont.truetype(font_path, minimum)


def card(img, width, t):
    img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    return framed(img, radius=16, border=t['border'])


def place(canvas, item, x, y, t):
    shadow = Image.new('RGBA', (item.width + 100, item.height + 100), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((50, 58, 50 + item.width, 58 + item.height), radius=18, fill=t['shadow'])
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)), (x - 50, y - 50))
    canvas.alpha_composite(item, (x, y))


def pill(canvas, text, x, y, color, t, font):
    d = ImageDraw.Draw(canvas)
    w = int(d.textlength(text, font=font)) + 32
    d.rounded_rectangle((x, y, x + w, y + 38), radius=19, fill=t['pill'] + (245,), outline=color + (210,), width=2)
    d.text((x + 16, y + 5), text, font=font, fill=t['pill_text'])


def build(kind, lang):
    t, words = THEMES[kind], TEXT[lang]
    canvas = background(t)
    d = ImageDraw.Draw(canvas)
    icon = Image.open(ICON).convert('RGBA')
    icon = icon.crop(icon.getbbox())
    icon.thumbnail((176, 176), Image.LANCZOS)
    canvas.alpha_composite(icon, (70, 70))
    d.text((262, 74), '兔白字幕', font=ImageFont.truetype(HEAVY, 96), fill=t['title'])
    sub = ImageFont.truetype(MEDIUM, 40)
    x = 268
    for ch in '2ByteASR':
        d.text((x, 196), ch, font=sub, fill=t['sub'])
        x += d.textlength(ch, font=sub) + 4
    left_w = 640
    d.text((72, 296), words['tagline'], font=fit_font(d, words['tagline'], MEDIUM, 34, left_w), fill=t['title'])
    point_font = min((fit_font(d, p, MEDIUM, 26, left_w - 40) for p in words['points']), key=lambda f: f.size)
    for i, (text, color) in enumerate(zip(words['points'], COLORS)):
        y = 372 + i * 58
        d.ellipse((74, y + 9, 90, y + 25), fill=color + (255,))
        d.text((106, y), text, font=point_font, fill=t['body'])
    d.text((74, 572), words['note'], font=ImageFont.truetype(MEDIUM, 20), fill=t['muted'])

    review = crop(RUNS / 'final-02' / 'frames' / 'review' / '0008.png', (288, 318, 662, 164))
    razor = crop(RUNS / 'final-02' / 'frames' / 'razor' / '0038.png', (0, 576, 960, 290))
    right_x, right_w = 770, 930
    a = card(review, right_w, t)
    b = card(razor, right_w, t)
    pill_h, pill_gap, gap = 38, 10, 26
    block = pill_h + pill_gap + a.height + gap + pill_h + pill_gap + b.height
    top = (H - block) // 2
    pill_font = ImageFont.truetype(MEDIUM, 20)
    pill(canvas, words['pills'][0], right_x + 4, top, COLORS[0], t, pill_font)
    y_a = top + pill_h + pill_gap
    place(canvas, a, right_x, y_a, t)
    y_p2 = y_a + a.height + gap
    pill(canvas, words['pills'][1], right_x + 4, y_p2, COLORS[1], t, pill_font)
    place(canvas, b, right_x, y_p2 + pill_h + pill_gap, t)
    out = framed(canvas.convert('RGB'), radius=26, border=None)
    name = f'banner-{lang}.png'
    out.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(OUT / name, optimize=True)
    print(name, (OUT / name).stat().st_size // 1024, 'KiB', out.size)


if __name__ == '__main__':
    for lang in TEXT:
        for kind in THEMES:
            build(kind, lang)
