"""兔白, the tutorial's guide bunny: babble voice, typed words, marked words, chat (2026-11-11).

User: the tutorial gets the user's own PNGTuber bunny beside its bubble. Its
words appear one by one while it talks in an Animal Crossing like babble: one
short, sweet consonant-vowel syllable per character, synthesized here in
memory and played through one continuous output stream. The important words
stand out; a click on the bunny makes it say something about subtitles and
video encoding, or just something friendly.

Marks in a tutorial line: ``**control**`` in the accent colour (as before),
``==what matters==`` on a bright marker. 2026-11-14 (「问问兔白」, user: jokes,
different sizes and shaking words): ``~~struck words~~`` crossed out,
``^^big^^``, ``__small__`` (a whisper) and ``%%shaking%%`` (drawn by
``MarkedLabel``). Characters not typed yet stay in the text, transparent, so
lines never re-wrap while the words appear.
"""
from __future__ import annotations

import html
import math
import random
import re
import time
from functools import lru_cache

from PySide6.QtCore import QIODevice, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel

MARK = re.compile(r'(\*\*|==|~~|\^\^|__|%%)')
_STYLE_OF = {'**': 'em', '==': 'hi', '~~': 'del', '^^': 'big', '__': 'small', '%%': 'shake'}
PAUSES = {**dict.fromkeys('，、；：,;:', 110), **dict.fromkeys('。！？!?…', 200)}
QUIET = set(' \t\n，、；：,;:。！？!?…「」『』“”"\'()（）[]【】<>《》·-—/／+→0123456789')

# 2026-11-11 (user): more to say, much of it about subtitles and encoding, plus cute lines.
TIPS = (
    'SRT 是最通用的字幕格式，几乎哪里都能导入～',
    'ASS 字幕能做花字、描边和特效，播放器大多都认',
    'TXT 只有文字没有时间，适合拿去写稿',
    '剪映文稿可以直接导进剪映接着剪哦',
    '硬字幕烧进画面，软字幕可以随时开关',
    'H.264 最通用，各大平台和老设备都能放',
    'H.265 同画质体积更小，但有些老设备放不动',
    'AV1 压缩率超高，就是编码慢，要耐心等哦',
    'MP4 是容器，里面装的才是 H.264 这些编码',
    '码率越高画质越好，文件也会越大～',
    '1080p 视频一般 6～10 Mbps 就挺清楚啦',
    'CRF 数字越小画质越好，18 到 23 最常用',
    '压制时保持原帧率，画面才不会一卡一卡',
    '关键帧间隔短一点，拖进度条会更顺',
    '音频常用 AAC，体积小、兼容好',
    '字幕一行别太长，十几个字读起来最舒服',
    '时间轴对准开口那一下，看起来最跟嘴',
    '换人说话时分开两条，观众不容易看串',
)
CUTE = (
    '嘿嘿，被你发现我啦～',
    '今天也一起做字幕吧！',
    '别戳啦，耳朵会痒的！',
    '我的眼镜好看吧？',
    '累了就休息一下，喝口水～',
    '字幕做好了记得夸夸我！',
    '跟着亮黄色的字点就对啦',
    '钥匙扣会叮当响哦～',
    '有不懂的随时戳我～',
    '你学得好快呀！',
    '摸摸头，会变聪明哦～',
    '偷偷告诉你，我最爱看游戏实况了',
    '眼镜起雾啦……擦一擦',
    '今天的字幕也闪闪发光！',
)
CHAT_LINES = TIPS + CUTE
GREETING = '嗨～我是兔白！跟着我点几下就会啦'


def plain(text: str) -> str:
    return MARK.sub('', str(text))


def marked_segments(text: str) -> list[tuple[str, str]]:
    """``[(words, style)]``; style is '' (plain), 'em' (**…**), 'hi' (==…==), 'del' (~~…~~),
    'big' (^^…^^), 'small' (__…__) or 'shake' (%%…%%)."""
    segments, style = [], ''
    for part in MARK.split(str(text)):
        if part in _STYLE_OF:
            style = '' if style == _STYLE_OF[part] else _STYLE_OF[part]
        elif part:
            segments.append((part, style))
    return segments


def segments_length(segments) -> int:
    return sum(len(words) for words, _style in segments)


def marker_colors(theme) -> dict:
    """Accent for controls; a warm marker for what matters, readable on light and dark bubbles."""
    from PySide6.QtGui import QColor
    light = QColor(theme.surface_elevated).lightness() > 128
    return dict(accent=theme.accent, mark='#ffe27a' if light else '#f7cf4a',
                mark_text='#4a3300' if light else '#2a1c00')


WORD_JOINER = '⁠'
_KEEP_MARKED = 8             # a marked run up to this long never breaks inside
_KEEP_WORD = 6               # nor a word up to this long
_words_ready = None


def warm_words() -> None:
    """Load jieba's dictionary off the GUI thread (about 0.8 s the first time)."""
    global _words_ready
    if _words_ready is not None:
        return
    import threading
    _words_ready = threading.Event()

    def load():
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                import jieba
                jieba.setLogLevel(60)
                jieba.initialize()
        except Exception:  # noqa: BLE001 - without jieba only marked runs stay whole
            pass
        finally:
            _words_ready.set()
    threading.Thread(target=load, name='bunny-words', daemon=True).start()


def words_ready() -> bool:
    return _words_ready is not None and _words_ready.is_set()


def _joints(plain_text: str, marked_runs: tuple) -> frozenset:
    """Positions after which a line must not break (2026-11-14, user: words cut in half look bad).

    Inside a Chinese word that jieba finds (新手|引导, 显卡, 时间轴) and inside a short marked run
    (**新手引导**). Qt's line breaker honours U+2060 WORD JOINER; ``white-space: nowrap`` it does not.

    2026-11-18 (user: opening 「问问兔白」 hangs): her first line used to call jieba on the GUI thread
    while its dictionary was still loading — 0.6–0.9 s with nothing drawn. Until the background
    load (``warm_words``) is done only the marked runs stay whole; that answer is not cached, so the
    lines after it get whole words.
    """
    if not words_ready():
        warm_words()
        return _marked_joints(marked_runs)
    return _word_joints(plain_text, marked_runs)


def _marked_joints(marked_runs: tuple) -> frozenset:
    joints = set()
    for start, end in marked_runs:
        if 1 < end - start <= _KEEP_MARKED:
            joints.update(range(start, end - 1))
    return frozenset(joints)


@lru_cache(maxsize=256)
def _word_joints(plain_text: str, marked_runs: tuple) -> frozenset:
    joints = set(_marked_joints(marked_runs))
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            import jieba
            jieba.setLogLevel(60)
            words = jieba.lcut(plain_text)
    except Exception:  # noqa: BLE001
        words = []
    at = 0
    for word in words:
        if 1 < len(word) <= _KEEP_WORD and not word.isspace():
            joints.update(range(at, at + len(word) - 1))
        at += len(word)
    return frozenset(joints)


def segments_html(segments, colors: dict, shown: int | None = None, keep_words: bool = False) -> str:
    """Rich text for the first ``shown`` characters (all when None); the rest is kept, transparent.

    ``keep_words``: words and short marked runs never break across lines (「问问兔白」 bubbles).
    """
    joints = frozenset()
    if keep_words:
        runs, at = [], 0
        for words, style in segments:
            if style:
                runs.append((at, at + len(words)))
            at += len(words)
        joints = _joints(''.join(words for words, _style in segments), tuple(runs))
    out, left, position = [], (10 ** 9 if shown is None else max(0, int(shown))), 0
    from ..design.typography import TITLE_FONT_STACK
    heavy = 'font-family:' + TITLE_FONT_STACK.replace('"', "'") + ';'
    for words, style in segments:
        visible, hidden = words[:left], words[left:]
        left -= len(visible)
        for chunk, seen in ((visible, True), (hidden, False)):
            if not chunk:
                continue
            start, position = position, position + len(chunk)
            if joints:
                chunk = ''.join(char + (WORD_JOINER if start + index in joints else '')
                                for index, char in enumerate(chunk))
            safe = html.escape(chunk)
            if style == 'em':
                color = colors['accent'] if seen else 'transparent'
                out.append(f'<span style="{heavy} color:{color}; font-weight:800;">{safe}</span>')
            elif style == 'hi':
                if seen:
                    out.append(f'<span style="{heavy} background-color:{colors["mark"]}; color:{colors["mark_text"]};'
                               f' font-weight:800;">{safe}</span>')
                else:
                    out.append(f'<span style="{heavy} color:transparent; font-weight:800;">{safe}</span>')
            elif style == 'del':
                # The line takes the text colour, so words not typed yet carry an invisible line too.
                # ``StrikeLabel`` draws it itself where the font's own line is too thin to see.
                color = '' if seen else ' color:transparent;'
                out.append(f'<span style="{STRIKE_CSS}{color}">{safe}</span>')
            elif style == 'big':
                color = '' if seen else ' color:transparent;'
                out.append(f'<span style="{heavy} font-size:x-large; font-weight:800;{color}">{safe}</span>')
            elif style == 'small':
                color = '' if seen else ' color:transparent;'
                out.append(f'<span style="font-size:small;{color}">{safe}</span>')
            elif style == 'shake':
                # ``MarkedLabel`` paints these itself, trembling; any other label shows them bold.
                out.append(f'<span style="{SHAKE_SEEN if seen else SHAKE_HIDDEN}">{safe}</span>')
            else:
                out.append(safe if seen else f'<span style="color:transparent;">{safe}</span>')
    return ''.join(out)


def marked_html(text: str, colors: dict, keep_words: bool = False) -> str:
    return segments_html(marked_segments(text), colors, keep_words=keep_words)


def _layout_lines(doc) -> list:
    out = []
    block = doc.begin()
    while block.isValid():
        layout = block.layout()
        out += [(layout.lineAt(i).textStart(), layout.lineAt(i).textLength()) for i in range(layout.lineCount())]
        block = block.next()
    return out


def balanced_width(rich_text: str, font, max_width: int) -> int:
    """The narrowest width that keeps ``rich_text`` on as few lines as ``max_width`` allows (2026-11-14).

    User: lines broke oddly, with a last line of only two characters. Wrapping at the widest
    width fills every line but the last; this shrinks the box until one more line would be
    needed, so the lines come out about even and nothing is left dangling.
    """
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setDefaultFont(font)
    doc.setDocumentMargin(0)
    doc.setHtml(rich_text)
    doc.setTextWidth(-1)
    natural = math.ceil(doc.idealWidth())
    if natural <= max_width:
        return max(1, natural)
    doc.setTextWidth(max_width)
    lines = len(_layout_lines(doc))
    low, high = max(1, max_width // max(1, lines) - 1), max_width
    while low < high:
        middle = (low + high) // 2
        doc.setTextWidth(middle)
        if len(_layout_lines(doc)) > lines:
            low = middle + 1
        else:
            high = middle
    doc.setTextWidth(low)
    return min(max_width, math.ceil(doc.idealWidth()) + 1)


STRIKE_CSS = 'text-decoration:line-through;'
# Shaking words carry an overline in the source only, to be found again in the laid-out text;
# the label shows them transparent (keeping their place) and paints them itself, jittering.
SHAKE_SEEN = 'text-decoration:overline; font-weight:700;'
SHAKE_HIDDEN = SHAKE_SEEN + ' color:transparent;'
_SHAKE_SHOWN = 'font-weight:700; color:transparent;'


class MarkedLabel(QLabel):
    """A rich-text label that draws ``~~crossed out~~`` and ``%%shaking%%`` words itself (2026-11-14).

    Crossed out: on Windows the bundled Source Han Sans reports a strike-out line about 0.6 px
    thick and Qt's own line does not show at all (it does offscreen, through FreeType), so the
    label paints a line of a readable thickness across the same words. Shaking: rich text cannot
    move single characters, so those words are shown transparent and painted here with a small
    jitter while the label is visible. Both are placed with a QTextDocument laid out like the
    label's own text; words not typed yet (transparent) get neither, so they follow the typing.
    """

    SHAKE_MS = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_html = ''
        self._shake = QTimer(self)
        self._shake.setInterval(self.SHAKE_MS)
        self._shake.timeout.connect(self.update)
        self._started = time.perf_counter()

    def setText(self, text):  # noqa: N802 - Qt override
        self.source_html = str(text)
        shown = self.source_html.replace(STRIKE_CSS, '').replace(SHAKE_HIDDEN, _SHAKE_SHOWN)
        super().setText(shown.replace(SHAKE_SEEN, _SHAKE_SHOWN))
        self._sync_shake()

    def _sync_shake(self):
        from ..design.ui_motion import reduced_motion
        wanted = SHAKE_SEEN in self.source_html and self.isVisible() and not reduced_motion()
        if wanted and not self._shake.isActive():
            self._shake.start()
        elif not wanted:
            self._shake.stop()

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        self._sync_shake()

    def hideEvent(self, event):  # noqa: N802 - Qt override
        super().hideEvent(event)
        self._shake.stop()

    def _runs(self):
        """(strikes [(x1, x2, y)], shaking characters [(char, x, baseline, font)]) in label coordinates."""
        strikes, shakes = [], []
        if STRIKE_CSS not in self.source_html and SHAKE_SEEN not in self.source_html:
            return strikes, shakes
        from PySide6.QtGui import QTextDocument
        rect = self.contentsRect()
        margin = self.margin()
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        doc.setHtml(self.source_html)
        doc.setTextWidth(max(1, rect.width() - 2 * margin) if self.wordWrap() else -1)
        left, top = rect.x() + margin, rect.y() + margin
        block = doc.begin()
        while block.isValid():
            layout = block.layout()
            origin = doc.documentLayout().blockBoundingRect(block).topLeft()
            text = block.text()
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                struck, shaking = fmt.fontStrikeOut(), fmt.fontOverline()
                if (struck or shaking) and fmt.foreground().color().alpha() > 0:
                    start = fragment.position() - block.position()
                    end = start + fragment.length()
                    font = fmt.font().resolve(self.font())
                    font.setOverline(False)
                    for index in range(layout.lineCount()):
                        line = layout.lineAt(index)
                        a, b = max(start, line.textStart()), min(end, line.textStart() + line.textLength())
                        if a >= b:
                            continue
                        if struck:
                            x1, _ = line.cursorToX(a)
                            x2, _ = line.cursorToX(b)
                            strikes.append((left + origin.x() + x1, left + origin.x() + x2,
                                            top + origin.y() + line.y() + line.ascent() * 0.62))
                        if shaking:
                            baseline = top + origin.y() + line.y() + line.ascent()
                            for position in range(a, b):
                                x, _ = line.cursorToX(position)
                                shakes.append((text[position], left + origin.x() + x, baseline, font))
                it += 1
            block = block.next()
        return strikes, shakes

    def strike_lines(self) -> list:
        return self._runs()[0]

    def shaking_chars(self) -> list:
        return self._runs()[1]

    def paintEvent(self, event):  # noqa: N802 - Qt override
        super().paintEvent(event)
        strikes, shakes = self._runs()
        if not strikes and not shakes:
            return
        import math
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainter, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        color = self.palette().color(self.foregroundRole())
        size = self.font().pixelSize() if self.font().pixelSize() > 0 else 15
        if shakes:
            painter.setPen(color)
            moving = self._shake.isActive()
            t = time.perf_counter() - self._started
            amp = max(1.0, size / 11.0)
            for index, (char, x, baseline, font) in enumerate(shakes):
                dx = math.sin(t * 29 + index * 1.7) * amp * 0.6 if moving else 0.0
                dy = math.cos(t * 34 + index * 2.3) * amp if moving else 0.0
                painter.setFont(font)
                painter.drawText(QPointF(x + dx, baseline + dy), char)
        if strikes:
            pen = QPen(color, max(1.5, size / 8.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for x1, x2, y in strikes:
                painter.drawLine(QPointF(x1, y), QPointF(x2, y))


StrikeLabel = MarkedLabel   # the name it had for a day


def char_delay(char: str) -> int:
    """ms before the next character.

    2026-11-11 round 3 (user's Animal Crossing reference: a syllable about every 55-60 ms, running
    together): one Chinese character is one syllable of about 62 ms; a Latin letter is quicker."""
    if char in PAUSES:
        return PAUSES[char]
    return 62 if ord(char) > 0x2e80 else 30


# ---------------------------------------------------------------- voice
# 2026-11-11 round 4 (user: 软萌甜妹 sounded pinched): the "标准动森" pitch and formants (about
# 520 Hz), keeping only the soft consonants and a softened top; quieter by default.
# 2026-11-11 round 3: the user chose "软萌甜妹" of three voices modelled on an Animal Crossing
# reference (f0 about 520 Hz there, syllables gliding in pitch and running into each other).
# Each syllable is a soft consonant gliding into a vowel: harmonics of a gliding f0 shaped by a
# cascade of formant resonators (Klatt-like magnitude) with a gentle source tilt and a little breath.

RATE = 48000                     # the app's audio output format: 48 kHz stereo 16 bit (as the cue preview)
VOWELS = {                       # F1, F2, F3 of an adult voice; scaled up for a small animal
    'a': (750, 1200, 2500), 'i': (300, 2200, 2950), 'u': (330, 850, 2250),
    'e': (480, 1850, 2550), 'o': (480, 880, 2450),
}
# consonant: (F2 locus Hz or None, F1 start factor, voice onset ms); soft ones only (no s/t/k hiss)
CONSONANTS = {'b': (900, 0.45, 3), 'd': (1750, 0.45, 3), 'm': (1000, 0.4, 2), 'n': (1700, 0.4, 2),
              'l': (1300, 0.6, 2), 'w': (750, 0.5, 2), 'y': (2200, 0.45, 2), 'h': (None, 0.8, 8), '': (None, 1.0, 0)}
BASE_HZ = 520.0
# 2026-11-19 (user: her voice is no longer cute — many low 「吧」「啊」, it sounds like Thai; picked
# 「A 修正版」 from the samples): the timbre stays, but no syllable goes below the base pitch, the
# glides inside a syllable are small and mostly rising (the big falling ones read as tones of a
# tonal language), and the dark vowels o/u and the dark consonants w/h are no longer drawn.
SPREAD = (0, 1, 2, 3, 4, 2)              # semitones, one per syllable: a sing-song line
GLIDES = (-0.03, 0.0, 0.03, 0.05, 0.08)  # pitch movement inside a syllable
FORMANT_SCALE = 1.5
SYLLABLE_S = 0.072
SOFT_TOP_HZ = 3200.0                      # harmonics above this are softened
LOUDNESS = 0.075                          # RMS of one syllable

# 2026-11-14 (「问问兔白」, user: every click sounded the same short blip; the voice should follow her
# mood and the words): (semitones, length factor, extra glide, vibrato depth, loudness factor).
# '' is the tutorial's voice, unchanged.
# 2026-11-19 (「A 修正版」): sad and gentle moods were up to 3 semitones lower, 20 % longer and fell
# 10 % inside each syllable — her long answers became a low, drawn-out 「啊」. Now no mood goes
# below the base pitch or past 1.05 x the length, and the bends are halved (never below -0.02);
# sadness is carried by a softer voice instead.
VOICE_MOODS = {
    '': (0, 1.0, 0.0, 0.0, 1.0),
    'happy': (2, 0.95, 0.025, 0.0, 1.05),
    'excited': (4, 0.86, 0.045, 0.0, 1.12),
    'teasing': (1, 1.0, 0.06, 0.0, 1.0),
    'surprised': (5, 0.92, 0.07, 0.0, 1.12),
    'thinking': (0, 1.05, -0.02, 0.0, 0.9),
    'sorry': (0, 1.05, -0.02, 0.0, 0.85),
    'shy': (1, 0.9, 0.0, 0.0, 0.7),
    'comfort': (0, 1.05, -0.02, 0.0, 0.85),
    'scared': (2, 1.05, -0.015, 0.035, 0.7),    # 2026-11-17: small and shaky after a fright
    # the words themselves: **bold** / ==marker==, ^^big^^, __whisper__, %%trembling%%
    'bright': (1, 1.0, 0.02, 0.0, 1.18),
    'big': (3, 1.05, 0.03, 0.0, 1.32),
    'whisper': (0, 0.92, -0.01, 0.0, 0.5),
    'tremble': (3, 1.05, 0.0, 0.045, 1.05),
}
STYLE_VOICE = {'em': 'bright', 'hi': 'bright', 'big': 'big', 'small': 'whisper', 'shake': 'tremble'}


def _resonance(f, F, B):
    x = f / F
    return 1.0 / ((1 - x * x) ** 2 + (f * B / (F * F)) ** 2) ** 0.5


@lru_cache(maxsize=None)
def syllable_pcm(consonant: str, vowel: str, spread: int = 2, glide: int = 2, mood: str = '') -> bytes:
    """One babble syllable as 48 kHz stereo int16 PCM (b'' without numpy); ``mood``: a ``VOICE_MOODS`` key."""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return b''
    locus, f1_factor, onset_ms = CONSONANTS.get(consonant, CONSONANTS[''])
    rng = np.random.default_rng([ord(c) for c in consonant + vowel] + [spread, glide])   # the same every run
    semitones, stretch, bend, vibrato, loud = VOICE_MOODS.get(mood, VOICE_MOODS[''])
    length = SYLLABLE_S * stretch
    n = int(RATE * length)
    t = np.arange(n) / RATE
    start = BASE_HZ * 2 ** ((SPREAD[spread % len(SPREAD)] + semitones) / 12)
    end = start * (1 + GLIDES[glide % len(GLIDES)] + bend)
    k = t / length
    f0 = start + (end - start) * (k * k * (3 - 2 * k))
    if vibrato:
        f0 = f0 * (1 + vibrato * np.sin(2 * np.pi * 19.0 * t))
    f0 = f0 * (1 + 0.004 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)))   # a little life
    target = [f * FORMANT_SCALE for f in VOWELS[vowel]]
    move = np.clip((t - onset_ms / 1000) / 0.022, 0, 1) ** 0.8
    f1 = target[0] * (f1_factor + (1 - f1_factor) * move)
    f2 = target[1] if locus is None else locus * FORMANT_SCALE + (target[1] - locus * FORMANT_SCALE) * move
    f3 = target[2]
    widths = (70 * FORMANT_SCALE, 100 * FORMANT_SCALE, 150 * FORMANT_SCALE)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    voice = np.zeros(n)
    for harmonic in range(1, int(7500 / start) + 1):
        f = harmonic * f0
        gain = _resonance(f, f1, widths[0]) * _resonance(f, f2, widths[1]) * _resonance(f, f3, widths[2])
        soft = 1.0 / (1.0 + (f / SOFT_TOP_HZ) ** 2)   # a gentle top: no pinched, piercing edge
        voice += gain * soft / harmonic ** 1.1 * np.sin(harmonic * phase + rng.uniform(0, 0.3))
    voice /= np.max(np.abs(voice)) + 1e-9
    noise = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    breath = np.fft.irfft(noise * np.exp(-((freqs - 2460) / 1800) ** 2), n)
    voice += 0.04 * breath / (np.max(np.abs(breath)) + 1e-9)
    voice *= np.clip((t - onset_ms / 1000) / 0.007, 0, 1) * np.clip((length - t) / 0.022, 0, 1) ** 1.4
    voice *= LOUDNESS * loud / (np.sqrt(np.mean(voice ** 2)) + 1e-9)
    mono = (np.clip(voice, -0.95, 0.95) * 32767).astype('<i2')
    return np.repeat(mono, 2).tobytes()


def voice_enabled() -> bool:
    from .onboarding import load_state
    return bool(load_state().get('mascot_voice', True))


def set_voice_enabled(on: bool) -> None:
    from .onboarding import load_state, save_state
    save_state(dict(load_state(), mascot_voice=bool(on)))


class _BabbleStream(QIODevice):
    """Endless 48 kHz stereo stream: queued syllables, mixed, then silence (pull mode, no restarts).

    Starting the audio output for every syllable blocked the window for up to
    two seconds on Windows; the output is started once and only reads this."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = None

    def push(self, pcm: bytes) -> None:
        import numpy as np
        new = np.frombuffer(pcm, '<i2').astype(np.int32)
        old = self._pending
        if old is not None and len(old):
            size = max(len(old), len(new))
            mixed = np.zeros(size, np.int32)
            mixed[:len(old)] += old
            mixed[:len(new)] += new
            new = mixed
        self._pending = new

    def readData(self, maxlen):  # noqa: N802 - Qt override
        import numpy as np
        maxlen -= maxlen % 4
        pending, take = self._pending, 0
        chunk = b''
        if pending is not None and len(pending):
            take = min(maxlen // 2, len(pending))
            chunk = np.clip(pending[:take], -32767, 32767).astype('<i2').tobytes()
            self._pending = pending[take:]
        return chunk + bytes(maxlen - len(chunk))

    def writeData(self, _data):  # noqa: N802 - Qt override
        return -1

    def isSequential(self):  # noqa: N802 - Qt override
        return True

    def bytesAvailable(self):  # noqa: N802 - Qt override
        return 1 << 16


class MascotVoice(QObject):
    """One babble syllable per character (at most one every ``GAP`` seconds); silent without an audio output."""

    GAP = 0.05
    VOLUME = 0.42
    VOWELS = 'aieia'               # 2026-11-19: bright vowels drawn (a and i twice), no dark o/u
    CONSONANT_ORDER = 'bdmnly'     # 2026-11-19: no w (a dark 「wo」) or breathy h

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = voice_enabled()
        self._sink = None            # QAudioSink once needed; False when there is no usable output
        self._stream = None
        self._last = 0.0

    def _output(self):
        if self._sink is None:
            try:
                from PySide6.QtGui import QGuiApplication
                from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
                if QGuiApplication.platformName() in ('offscreen', 'minimal'):
                    raise RuntimeError('no one to hear it (tests, audits)')
                device = QMediaDevices.defaultAudioOutput()
                fmt = QAudioFormat()
                fmt.setSampleRate(RATE)
                fmt.setChannelCount(2)
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                if device.isNull() or not device.isFormatSupported(fmt):
                    raise RuntimeError('no 48 kHz stereo output')
                self._stream = _BabbleStream(self)
                self._stream.open(QIODevice.OpenModeFlag.ReadOnly)
                sink = QAudioSink(device, fmt, self)
                sink.setBufferSize(7680)          # 40 ms: the mouth and the sound stay together
                sink.setVolume(self.VOLUME)
                sink.start(self._stream)
                self._sink = sink
            except Exception:  # noqa: BLE001 - no audio: the bunny talks silently
                self._sink = False
        return self._sink or None

    def warm_up(self) -> None:
        """Make the syllables and open the output before the first word (about 0.1 s, once)."""
        if self.enabled:
            for char in '嗨我是兔白跟着点几下就会啦':   # the greeting's syllables, ready before it starts
                syllable_pcm(*self.syllable_for(char))
            self._output()

    def close(self) -> None:
        """Let go of the audio output (the tutorial closed)."""
        if self._sink:
            try:
                self._sink.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._stream is not None:
            self._stream.close()
        self._sink, self._stream = None, None

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        set_voice_enabled(self.enabled)

    def syllable_for(self, char: str) -> tuple[str, str, int, int]:
        """(consonant, vowel, pitch step, glide): the same character always sounds the same."""
        code = (ord(char) * 2654435761) >> 9
        names = self.CONSONANT_ORDER + ' '
        lower = char.lower()
        typed_vowel = lower in VOWELS      # a typed Latin vowel keeps its own sound
        vowel = lower if typed_vowel else self.VOWELS[code % len(self.VOWELS)]
        consonant = '' if typed_vowel else names[(code >> 3) % len(names)].strip()
        return consonant, vowel, (code >> 7) % len(SPREAD), (code >> 11) % len(GLIDES)

    def play_pcm(self, pcm: bytes) -> bool:
        """Mix a ready 48 kHz stereo int16 sound into her output (``bunny_sfx``); False when muted or
        there is no output. 2026-11-27: her sound effects share this one output with her voice."""
        if not self.enabled or not pcm or self._output() is None:
            return False
        self._stream.push(pcm)
        return True

    def say(self, char: str, mood: str = '') -> bool:
        """A syllable for ``char`` (punctuation and spaces are silent); True when one starts.

        ``mood`` (「问问兔白」): a ``VOICE_MOODS`` key; '' is the tutorial's voice."""
        if not char or char in QUIET:
            return False
        now = time.perf_counter()
        if now - self._last < self.GAP:
            return False
        self._last = now
        if not self.enabled:
            return True   # the mouth still moves
        pcm = syllable_pcm(*self.syllable_for(char), mood if mood in VOICE_MOODS else '')
        if pcm and self._output() is not None:
            self._stream.push(pcm)
        return True


# ---------------------------------------------------------------- typing

class Typewriter(QObject):
    """Types marked lines into labels, one character at a time; ``spoke`` fires per syllable."""

    spoke = Signal(str)
    spoke_marked = Signal(str, str)   # the character and the mark it is in ('' plain, 'em', 'big'...)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._parts = []          # [label, segments, chars]
        self._colors = {}
        self._index = 0
        self._shown = 0
        self.keep_words = False   # 「问问兔白」: words never break across lines
        self.pace = 1.0           # 「问问兔白」: slower for long (sad, gentle) syllables, so sound and words stay together
        self._styles = []
        self._before = ''         # 「问问兔白」: what the label already says above the line being typed

    @property
    def running(self) -> bool:
        return bool(self._parts) and self._index < len(self._parts)

    def prepare(self, parts, colors: dict, before: str = '') -> None:
        """``parts``: [(label, marked text)]. Leaves every label blank (space kept) until ``start``.

        ``before`` (2026-11-18): HTML that stays in front of what is typed (her earlier sentences)."""
        self.stop()
        self._before = before
        self._colors = colors
        self._parts = [[label, marked_segments(text), plain(text)] for label, text in parts if text]
        self._styles = [[style for words, style in segments for _char in words] for _label, segments, _c in self._parts]
        self._index = 0
        self._shown = 0
        for label, segments, _chars in self._parts:
            label.setText(self._before + segments_html(segments, colors, 0, keep_words=self.keep_words))

    def start(self) -> None:
        if self.running and not self._timer.isActive():
            self._timer.start(60)

    def _tick(self) -> None:
        if not self.running:
            return
        label, segments, chars = self._parts[self._index]
        if self._shown >= len(chars):
            self._index += 1
            self._shown = 0
            if not self.running:
                self.finished.emit()
                return
            self._timer.start(160)   # a breath before the note
            return
        char = chars[self._shown]
        self._shown += 1
        label.setText(self._before + segments_html(segments, self._colors, self._shown, keep_words=self.keep_words))
        self.spoke.emit(char)
        styles = self._styles[self._index] if self._index < len(self._styles) else []
        self.spoke_marked.emit(char, styles[self._shown - 1] if self._shown - 1 < len(styles) else '')
        self._timer.start(max(20, round(char_delay(char) * self.pace)))

    def finish(self) -> None:
        """Everything at once (a click on the words, a window resize)."""
        if not self._parts:
            return
        self._timer.stop()
        was_running = self.running
        for label, segments, _chars in self._parts:
            label.setText(self._before + segments_html(segments, self._colors, keep_words=self.keep_words))
        self._index = len(self._parts)
        if was_running:
            self.finished.emit()

    def stop(self) -> None:
        self._timer.stop()
        self._parts = []
        self._index = 0


def next_chat_line(last: str = '', recent=()) -> str:
    """A random line, never one of the last few; about half of them are subtitle and video tips."""
    pool = TIPS if random.random() < 0.55 else CUTE
    choices = [line for line in pool if line != last and line not in recent]
    return random.choice(choices or [line for line in CHAT_LINES if line != last])


def speaking_ms(text: str) -> int:
    return sum(char_delay(char) for char in str(text))


__all__ = ['CHAT_LINES', 'GREETING', 'STYLE_VOICE', 'VOICE_MOODS', 'MascotVoice', 'Typewriter', 'marked_html', 'marked_segments',
           'marker_colors', 'next_chat_line', 'plain', 'segments_html', 'syllable_pcm', 'voice_enabled']
