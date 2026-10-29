"""Build the self-made README demo clip: two TTS voices over a quiet test card.

Everything here is generated locally (shapes drawn with PIL, OFL fonts,
Windows OneCore voices). Output: media/test-card.mp4 and media/timeline.json.
`build_demo_media.py forest` renders the earlier side-scroller art instead
(media/forest-run.mp4, used by the 2026-10-09 screenshots).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
BASE = Path(os.environ.get('README_SHOWCASE_DIR') or Path(__file__).resolve().parents[2] / 'tmp' / 'readme-showcase').resolve()
MEDIA = BASE / 'media'
REPO = HERE.parents[1]
FONT_PIXEL = REPO / 'assets/fonts/Cubic11.ttf'
FONT_HEAVY = REPO / 'assets/fonts/SourceHanSansSC-Heavy.otf'
W, H, FPS = 1920, 1080, 30
SR = 48000
GAP = 0.42
LEAD = 0.8


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), 'rb') as handle:
        rate = handle.getframerate()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    # Linear resample 16 kHz -> 48 kHz (speech only; fine for a demo bed).
    t_old = np.arange(len(data)) / rate
    t_new = np.arange(int(len(data) * SR / rate)) / SR
    return np.interp(t_new, t_old, data).astype(np.float32)


def trim(signal: np.ndarray) -> np.ndarray:
    level = np.convolve(np.abs(signal), np.ones(480) / 480, mode='same')
    voiced = np.where(level > 0.012)[0]
    if not len(voiced):
        return signal
    start = max(0, voiced[0] - int(0.05 * SR))
    end = min(len(signal), voiced[-1] + int(0.12 * SR))
    return signal[start:end]


def tone(freq: float, dur: float, decay: float = 18.0, gain: float = 0.05) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (np.sin(2 * math.pi * freq * t) * np.exp(-decay * t) * gain).astype(np.float32)


def build_audio(sfx=True):
    dialogue = json.loads((HERE / 'dialogue.json').read_text('utf8'))
    clips = sorted((MEDIA / 'tts').glob('line*.wav'))
    cursor = LEAD
    lines = []
    pieces = []
    for item, path in zip(dialogue, clips):
        signal = trim(read_wav(path))
        dur = len(signal) / SR
        lines.append(dict(speaker=item['speaker'], text=item['text'], start=round(cursor, 3), end=round(cursor + dur, 3)))
        pieces.append((cursor, signal))
        cursor += dur + GAP
    total = cursor + 0.9
    mix = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for start, signal in pieces:
        i = int(start * SR)
        mix[i:i + len(signal)] += signal * 0.92
    events = plan_events(lines, total)
    # Small, quiet game sounds so the clip feels alive; kept far below speech.
    for at in events['coins'] if sfx else ():
        i = int(at * SR)
        blip = np.concatenate([tone(988, 0.07, 30, 0.035), tone(1319, 0.16, 22, 0.035)])
        mix[i:i + len(blip)] += blip
    for at in events['hits'] if sfx else ():
        i = int(at * SR)
        thump = tone(140, 0.18, 26, 0.06) + tone(90, 0.18, 20, 0.04)
        mix[i:i + len(thump)] += thump
    mix = np.clip(mix[:int(total * SR)], -1, 1)
    stereo = np.stack([mix, mix], axis=1)
    out = MEDIA / 'forest-run.wav'
    with wave.open(str(out), 'wb') as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return lines, total, events


def plan_events(lines, total):
    """Game beats tied to what the players say."""
    l = lines
    coins = [l[2]['start'] + 0.9 + 0.55 * k for k in range(3)]
    slime_in = l[3]['start'] + 0.2
    hits = [l[4]['end'] - 0.3, l[5]['end'] + 0.1, l[6]['start'] + 0.05]
    slime_out = l[6]['start'] + 0.35
    camp = l[7]['start'] + 1.2
    return dict(coins=coins, slime_in=slime_in, slime_out=slime_out, hits=hits, camp=camp, total=total)


# ---------------------------------------------------------------- drawing
SKY_TOP = (176, 214, 214)
SKY_LOW = (232, 238, 214)
SUN = (250, 226, 160)
MOUNT_FAR = (128, 176, 168)
MOUNT_MID = (88, 148, 132)
HILL = (66, 120, 104)
GRASS = (140, 172, 104)
GRASS_DARK = (112, 148, 88)
PATH = (222, 192, 148)
TREE = (42, 99, 82)
TREE_LIGHT = (58, 120, 98)
TRUNK = (109, 90, 74)
WATER = (120, 182, 196)
INK = (34, 30, 40)


def supersampled(size, painter, scale=2):
    big = Image.new('RGBA', (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    painter(ImageDraw.Draw(big), scale)
    return big.resize(size, Image.LANCZOS)


def layer_sky():
    img = Image.new('RGB', (W, H))
    top, low = np.array(SKY_TOP, float), np.array(SKY_LOW, float)
    ramp = np.linspace(0, 1, H)[:, None]
    arr = (top * (1 - ramp) + low * ramp)[:, None, :].repeat(W, axis=1)
    img = Image.fromarray(arr.astype(np.uint8))
    sun = supersampled((260, 260), lambda d, s: d.ellipse((0, 0, 259 * s, 259 * s), fill=SUN + (255,)))
    img.paste(sun, (1440, 90), sun)
    return img.convert('RGBA')


def ridge(width, base, amp, seed, color, step=220):
    rng = np.random.default_rng(seed)
    xs = np.arange(-step, width + step * 2, step)
    ys = base - rng.uniform(0.25, 1.0, len(xs)) * amp

    def paint(d, s):
        pts = []
        for x, y in zip(xs, ys):
            pts.append((x * s, y * s))
        pts += [((width + step * 2) * s, H * s), (-step * s, H * s)]
        d.polygon(pts, fill=color + (255,))
    return supersampled((width, H), paint)


def tree(d, s, x, ground, height, light=False):
    trunk_w = height * 0.09
    d.rectangle(((x - trunk_w / 2) * s, (ground - height * 0.45) * s, (x + trunk_w / 2) * s, ground * s), fill=TRUNK + (255,))
    r = height * 0.33
    cy = ground - height * 0.62
    d.ellipse(((x - r) * s, (cy - r) * s, (x + r) * s, (cy + r) * s), fill=(TREE_LIGHT if light else TREE) + (255,))


def layer_trees(width, ground, seed, sizes, light):
    rng = np.random.default_rng(seed)

    def paint(d, s):
        x = 80
        while x < width + 200:
            tree(d, s, x, ground + rng.uniform(-6, 6), rng.uniform(*sizes), light)
            x += rng.uniform(260, 520)
    return supersampled((width, H), paint)


def layer_ground(width):
    def paint(d, s):
        d.rectangle((0, 820 * s, width * s, H * s), fill=GRASS + (255,))
        d.rectangle((0, 860 * s, width * s, 900 * s), fill=PATH + (255,))
        # river band behind the path, glints
        d.rectangle((0, 792 * s, width * s, 822 * s), fill=WATER + (255,))
        for x in range(0, width, 90):
            d.rounded_rectangle(((x + 10) * s, 803 * s, (x + 46) * s, 808 * s), radius=2 * s, fill=(206, 232, 236, 255))
        for x in range(0, width, 64):
            d.polygon([((x) * s, 940 * s), ((x + 10) * s, 916 * s), ((x + 20) * s, 940 * s)], fill=GRASS_DARK + (255,))
        for x in range(30, width, 140):
            d.rounded_rectangle((x * s, 874 * s, (x + 34) * s, 882 * s), radius=4 * s, fill=(204, 172, 128, 255))
    return supersampled((width, H), paint)


def layer_flowers(width):
    rng = np.random.default_rng(5)

    def paint(d, s):
        x = 40
        while x < width + 100:
            y = rng.uniform(960, 1060)
            for k in range(3):
                dx = rng.uniform(-14, 14)
                d.polygon([((x + dx) * s, (y + 30) * s), ((x + dx + 7) * s, (y - 8) * s), ((x + dx + 14) * s, (y + 30) * s)], fill=(96, 136, 80, 255))
            if rng.random() < 0.5:
                c = [(246, 236, 220), (240, 190, 200), (250, 220, 120)][int(rng.integers(0, 3))]
                d.ellipse(((x + 4) * s, (y - 14) * s, (x + 20) * s, (y + 2) * s), fill=c + (255,))
            x += rng.uniform(120, 260)
    return supersampled((width, H), paint)


def bush(scale=1.0):
    def paint(d, s):
        for cx, cy, r in ((60, 70, 48), (110, 58, 56), (160, 72, 44)):
            d.ellipse(((cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s), fill=(78, 140, 92, 255))
    return supersampled((220, 120), paint)


def hero(kind, frame, hurt=False):
    """kind 'A': red jacket explorer; 'B': lilac hoodie with rabbit ears."""
    def paint(d, s):
        bob = math.sin(frame * 0.45) * 4
        leg = math.sin(frame * 0.45) * 10
        body = (214, 96, 70) if kind == 'A' else (176, 140, 214)
        if hurt:
            body = (250, 250, 250)
        cx, top = 70, 40 + bob
        if kind == 'B':
            for ex in (-18, 18):
                d.rounded_rectangle(((cx + ex - 9) * s, (top - 40) * s, (cx + ex + 9) * s, (top + 6) * s), radius=9 * s, fill=(246, 240, 246, 255))
                d.rounded_rectangle(((cx + ex - 4) * s, (top - 32) * s, (cx + ex + 4) * s, (top) * s), radius=4 * s, fill=(232, 176, 196, 255))
        d.ellipse(((cx - 30) * s, top * s, (cx + 30) * s, (top + 58) * s), fill=(250, 220, 186, 255))
        d.ellipse(((cx + 6) * s, (top + 22) * s, (cx + 14) * s, (top + 32) * s), fill=INK + (255,))
        d.rounded_rectangle(((cx - 32) * s, (top + 54) * s, (cx + 32) * s, (top + 124) * s), radius=16 * s, fill=body + (255,))
        d.rounded_rectangle(((cx - 22 + leg) * s, (top + 118) * s, (cx - 6 + leg) * s, (top + 160) * s), radius=6 * s, fill=(52, 64, 78, 255))
        d.rounded_rectangle(((cx + 6 - leg) * s, (top + 118) * s, (cx + 22 - leg) * s, (top + 160) * s), radius=6 * s, fill=(52, 64, 78, 255))
        if kind == 'A':
            d.rounded_rectangle(((cx + 26) * s, (top + 70) * s, (cx + 92) * s, (top + 80) * s), radius=4 * s, fill=(206, 210, 220, 255))
    return supersampled((170, 210), paint)


def slime(frame, flash=False):
    def paint(d, s):
        squish = math.sin(frame * 0.3) * 6
        color = (255, 255, 255) if flash else (124, 196, 112)
        d.ellipse((10 * s, (40 + squish) * s, 150 * s, 130 * s), fill=color + (255,))
        d.rectangle((10 * s, 85 * s, 150 * s, 130 * s), fill=color + (255,))
        d.ellipse((50 * s, 70 * s, 62 * s, 86 * s), fill=INK + (255,))
        d.ellipse((96 * s, 70 * s, 108 * s, 86 * s), fill=INK + (255,))
        d.ellipse((30 * s, 56 * s, 52 * s, 70 * s), fill=(220, 246, 210, 200))
    return supersampled((160, 140), paint)


def coin(phase):
    def paint(d, s):
        w = abs(math.cos(phase)) * 26 + 6
        d.ellipse(((32 - w) * s, 4 * s, (32 + w) * s, 60 * s), fill=(246, 196, 72, 255), outline=(196, 140, 40, 255), width=4 * s)
    return supersampled((64, 64), paint)


def hud(img, now, coins_taken, hp_b, events, font_px, font_sm):
    d = ImageDraw.Draw(img)
    panel = Image.new('RGBA', (560, 132), (24, 20, 30, 150))
    img.alpha_composite(panel, (40, 36))
    d.text((64, 48), 'STAGE 2-3  林间小径', font=font_px, fill=(250, 240, 220))
    # two player bars
    for row, (name, hp, color) in enumerate((('A  河边探险家', 1.0, (214, 96, 70)), ('B  白兔', hp_b, (176, 140, 214)))):
        y = 96 + row * 32
        d.text((64, y - 4), name, font=font_sm, fill=(236, 228, 236))
        d.rounded_rectangle((300, y, 560, y + 18), radius=9, fill=(60, 52, 66))
        d.rounded_rectangle((300, y, 300 + int(260 * hp), y + 18), radius=9, fill=color)
    coin_panel = Image.new('RGBA', (220, 72), (24, 20, 30, 150))
    img.alpha_composite(coin_panel, (W - 260, 36))
    c = coin(0.0).resize((44, 44))
    img.alpha_composite(c, (W - 240, 50))
    d.text((W - 186, 46), f'x {12 + coins_taken:02d}', font=font_px, fill=(250, 240, 220))
    # route progress
    d.rounded_rectangle((W // 2 - 300, 1030, W // 2 + 300, 1042), radius=6, fill=(24, 20, 30, 120))
    p = min(1.0, now / events['total'])
    d.rounded_rectangle((W // 2 - 300, 1030, W // 2 - 300 + int(600 * p), 1042), radius=6, fill=(250, 226, 160))
    d.text((W // 2 - 300, 996), '营地', font=font_sm, fill=(40, 52, 46))
    d.text((W // 2 + 252, 996), '首领', font=font_sm, fill=(40, 52, 46))


def render(lines, events, total):
    frames = int(total * FPS)
    speed_far, speed_mid, speed_tree, speed_ground = 18, 40, 120, 210
    width_needed = int(speed_ground * total) + W + 400
    sky = layer_sky()
    far = ridge(int(speed_far * total) + W + 400, 560, 300, 3, MOUNT_FAR)
    mid = ridge(int(speed_mid * total) + W + 400, 660, 260, 7, MOUNT_MID, step=300)
    hill = ridge(int(speed_mid * 1.6 * total) + W + 400, 780, 140, 11, HILL, step=360)
    trees_back = layer_trees(int(speed_tree * total) + W + 400, 800, 21, (220, 300), True)
    ground = layer_ground(width_needed)
    trees_front = layer_flowers(width_needed)
    bush_img = bush()
    font_px = ImageFont.truetype(str(FONT_PIXEL), 40)
    font_sm = ImageFont.truetype(str(FONT_PIXEL), 26)
    coin_world = [speed_ground * t + 760 for t in events['coins']]  # pickup when ground offset passes
    ffmpeg = [
        'ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', str(MEDIA / 'forest-run.wav'), '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', str(MEDIA / 'forest-run.mp4')]
    proc = subprocess.Popen(ffmpeg, stdin=subprocess.PIPE)
    for f in range(frames):
        now = f / FPS
        frame = sky.copy()
        frame.alpha_composite(far.crop((int(speed_far * now), 0, int(speed_far * now) + W, H)))
        frame.alpha_composite(mid.crop((int(speed_mid * now), 0, int(speed_mid * now) + W, H)))
        frame.alpha_composite(hill.crop((int(speed_mid * 1.6 * now), 0, int(speed_mid * 1.6 * now) + W, H)))
        frame.alpha_composite(trees_back.crop((int(speed_tree * now), 0, int(speed_tree * now) + W, H)))
        offset = speed_ground * now
        frame.alpha_composite(ground.crop((int(offset), 0, int(offset) + W, H)))
        # coins: placed in world space, vanish when collected
        taken = sum(1 for t in events['coins'] if now >= t)
        for k, t in enumerate(events['coins']):
            if now < t:
                x = int(coin_world[k] - offset + 40)
                if -80 < x < W:
                    frame.alpha_composite(coin(now * 4 + k), (x, 700 - int(math.sin(now * 3 + k) * 10)))
            elif now < t + 0.35:
                rise = (now - t) / 0.35
                spark = coin(now * 10).resize((40, 40))
                spark.putalpha(Image.eval(spark.getchannel('A'), lambda a: int(a * (1 - rise))))
                frame.alpha_composite(spark, (760 + 52, int(700 - 80 * rise)))
        # bush + slime encounter on the right
        if events['slime_in'] - 1.5 <= now <= events['slime_out'] + 1.2:
            bx = int(1500 - (now - events['slime_in']) * 40)
            frame.alpha_composite(bush_img, (bx, 760))
        if events['slime_in'] <= now <= events['slime_out']:
            appear = min(1.0, (now - events['slime_in']) / 0.6)
            sx = int(1560 - 240 * appear)
            flash = any(0 <= now - h < 0.12 for h in events['hits'])
            frame.alpha_composite(slime(f, flash), (sx, 732))
        elif events['slime_out'] < now < events['slime_out'] + 0.5:
            fade = 1 - (now - events['slime_out']) / 0.5
            s = slime(f, True)
            s.putalpha(Image.eval(s.getchannel('A'), lambda a: int(a * fade)))
            frame.alpha_composite(s, (1320, 732 - int(40 * (1 - fade))))
        # heroes
        fighting = events['slime_in'] + 0.6 <= now <= events['slime_out']
        hit_b = any(0 <= now - h < 0.12 for h in events['hits'][1:2])
        b = hero('B', f + 7).resize((212, 262), Image.LANCZOS)
        a = hero('A', f).resize((212, 262), Image.LANCZOS)
        frame.alpha_composite(b, (560, 636))
        frame.alpha_composite(a, (780 if not fighting else 930, 636))
        # foreground trees (fast parallax) slightly blurred for depth
        frame.alpha_composite(trees_front.crop((int(offset), 0, int(offset) + W, H)))
        hp_b = 0.86 if now > events['hits'][0] else 1.0
        hud(frame, now, taken, hp_b, events, font_px, font_sm)
        if now > events['camp'] - 0.5:
            glow = Image.new('RGBA', (W, H), (255, 236, 196, int(min(1.0, (now - events['camp'] + 0.5) / 1.5) * 60)))
            frame.alpha_composite(glow)
        proc.stdin.write(frame.convert('RGB').tobytes())
        if f % 150 == 0:
            print(f'frame {f}/{frames}', flush=True)
    proc.stdin.close()
    proc.wait()
    return proc.returncode


# ------------------------------------------------------------ test card
# A quiet test-card picture for README screenshots (2026-10-14): the software
# is the subject, so the video area shows a restrained placeholder instead of
# drawn game art. Muted bars, a timecode and a level meter that follows the
# real speech track; the bottom third stays dark for the subtitles.
CARD_BG = (21, 18, 26)
CARD_PANEL = (30, 26, 36)
CARD_BARS = [(188, 186, 192), (190, 178, 98), (96, 170, 178), (104, 164, 98),
             (164, 98, 160), (168, 90, 92), (92, 98, 168)]
CARD_TEXT = (226, 222, 230)
CARD_DIM = (150, 144, 158)
FONT_MEDIUM = REPO / 'assets/fonts/SourceHanSansSC-Medium.otf'
FONT_MONO = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'consola.ttf'


def testcard_base():
    img = Image.new('RGBA', (W, H), CARD_BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((360, 120, 1560, 740), radius=22, fill=CARD_PANEL)
    left, top, width = 400, 160, 1120
    step = width // len(CARD_BARS)
    for k, color in enumerate(CARD_BARS):
        d.rectangle((left + k * step, top, left + (k + 1) * step - 1, top + 340), fill=color)
    reverse = [CARD_BARS[6], CARD_PANEL, CARD_BARS[4], CARD_PANEL, CARD_BARS[2], CARD_PANEL, CARD_BARS[0]]
    for k, color in enumerate(reverse):
        d.rectangle((left + k * step, top + 340, left + (k + 1) * step - 1, top + 380), fill=color)
    ramp = 8
    for k in range(ramp):
        level = int(26 + (200 - 26) * k / (ramp - 1))
        x0 = left + k * width // ramp
        d.rectangle((x0, top + 380, left + (k + 1) * width // ramp - 1, top + 470), fill=(level, level - 2, level + 4))
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o = ImageDraw.Draw(overlay)
    cx, cy = 960, 395
    o.ellipse((cx - 250, cy - 250, cx + 250, cy + 250), outline=(255, 255, 255, 80), width=3)
    o.line((cx, top, cx, top + 470), fill=(255, 255, 255, 46), width=2)
    o.line((left, cy, left + width, cy), fill=(255, 255, 255, 46), width=2)
    o.rounded_rectangle((cx - 250, cy - 58, cx + 250, cy + 58), radius=14, fill=(20, 17, 24, 236))
    img.alpha_composite(overlay)
    big = ImageFont.truetype(str(FONT_MEDIUM), 40)
    small = ImageFont.truetype(str(FONT_MEDIUM), 22)
    d = ImageDraw.Draw(img)
    d.text((cx, cy - 14), 'SAMPLE MEDIA', font=big, fill=CARD_TEXT, anchor='mm')
    d.text((cx, cy + 30), '2ByteASR test card', font=small, fill=CARD_DIM, anchor='mm')
    d.text((left, 676), 'CH 1-2  48 kHz', font=small, fill=CARD_DIM, anchor='ls')
    return img


def speech_levels(total):
    with wave.open(str(MEDIA / 'forest-run.wav'), 'rb') as handle:
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    mono = data[0::2]
    hop = SR // FPS
    levels = []
    for f in range(int(total * FPS)):
        chunk = mono[f * hop:(f + 1) * hop]
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
        levels.append(min(1.0, rms * 6.0))
    return levels


def render_testcard(total):
    frames = int(total * FPS)
    base = testcard_base()
    mono = ImageFont.truetype(str(FONT_MONO), 30) if FONT_MONO.is_file() else ImageFont.truetype(str(FONT_MEDIUM), 30)
    levels = speech_levels(total)
    shown = 0.0
    ffmpeg = [
        'ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
        '-i', str(MEDIA / 'forest-run.wav'), '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', str(MEDIA / 'test-card.mp4')]
    proc = subprocess.Popen(ffmpeg, stdin=subprocess.PIPE)
    for f in range(frames):
        frame = base.copy()
        d = ImageDraw.Draw(frame)
        seconds, sub = divmod(f, FPS)
        d.text((960, 676), f'00:00:{seconds:02d}:{sub:02d}', font=mono, fill=CARD_DIM, anchor='ms')
        # Meter eases down so it reads as a level, not a flicker.
        shown = max(levels[f], shown * 0.82)
        for row, y in enumerate((656, 670)):
            d.rounded_rectangle((1280, y, 1520, y + 8), radius=4, fill=(48, 42, 56))
            if shown > 0.02:
                d.rounded_rectangle((1280, y, 1280 + int(240 * shown), y + 8), radius=4, fill=(132, 172, 124))
        proc.stdin.write(frame.convert('RGB').tobytes())
        if f % 150 == 0:
            print(f'frame {f}/{frames}', flush=True)
    proc.stdin.close()
    proc.wait()
    return proc.returncode


def main():
    visual = sys.argv[1] if len(sys.argv) > 1 else 'testcard'
    if visual not in ('testcard', 'forest'):
        raise SystemExit('usage: build_demo_media.py [testcard|forest]')
    lines, total, events = build_audio(sfx=visual == 'forest')
    (MEDIA / 'timeline.json').write_text(json.dumps(dict(lines=lines, events=events), ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(lines, ensure_ascii=False, indent=1))
    code = render(lines, events, total) if visual == 'forest' else render_testcard(total)
    print('ffmpeg exit', code)
    return code


if __name__ == '__main__':
    sys.exit(main())
