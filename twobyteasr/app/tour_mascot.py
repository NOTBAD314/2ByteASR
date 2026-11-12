"""兔白, the tutorial's guide bunny: babble voice, typed words, marked words, chat (2026-11-11).

User: the tutorial gets the user's own PNGTuber bunny beside its bubble. Its
words appear one by one while it talks in an Animal Crossing like babble: one
short, sweet consonant-vowel syllable per character, synthesized here in
memory and played through one continuous output stream. The important words
stand out; a click on the bunny makes it say something about subtitles and
video encoding, or just something friendly.

Marks in a tutorial line: ``**control**`` in the accent colour (as before),
``==what matters==`` on a bright marker. Characters not typed yet stay in
the text, transparent, so lines never re-wrap while the words appear.
"""
from __future__ import annotations

import html
import random
import re
import time
from functools import lru_cache

from PySide6.QtCore import QIODevice, QObject, QTimer, Signal

MARK = re.compile(r'(\*\*|==)')
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
    '我的眼镜是不是很好看？',
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
    """``[(words, style)]``; style is '' (plain), 'em' (**…**) or 'hi' (==…==)."""
    segments, style = [], ''
    for part in MARK.split(str(text)):
        if part == '**':
            style = '' if style == 'em' else 'em'
        elif part == '==':
            style = '' if style == 'hi' else 'hi'
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


def segments_html(segments, colors: dict, shown: int | None = None) -> str:
    """Rich text for the first ``shown`` characters (all when None); the rest is kept, transparent."""
    out, left = [], (10 ** 9 if shown is None else max(0, int(shown)))
    for words, style in segments:
        visible, hidden = words[:left], words[left:]
        left -= len(visible)
        for chunk, seen in ((visible, True), (hidden, False)):
            if not chunk:
                continue
            safe = html.escape(chunk)
            if style == 'em':
                color = colors['accent'] if seen else 'transparent'
                out.append(f'<span style="color:{color}; font-weight:700;">{safe}</span>')
            elif style == 'hi':
                if seen:
                    out.append(f'<span style="background-color:{colors["mark"]}; color:{colors["mark_text"]};'
                               f' font-weight:700;">{safe}</span>')
                else:
                    out.append(f'<span style="color:transparent; font-weight:700;">{safe}</span>')
            else:
                out.append(safe if seen else f'<span style="color:transparent;">{safe}</span>')
    return ''.join(out)


def marked_html(text: str, colors: dict) -> str:
    return segments_html(marked_segments(text), colors)


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
SPREAD = (-3, -1, 0, 1, 2, 4)            # semitones, one per syllable: a sing-song line
GLIDES = (-0.16, -0.08, 0.0, 0.07, 0.12)  # pitch movement inside a syllable
FORMANT_SCALE = 1.5
SYLLABLE_S = 0.072
SOFT_TOP_HZ = 3200.0                      # harmonics above this are softened
LOUDNESS = 0.075                          # RMS of one syllable


def _resonance(f, F, B):
    x = f / F
    return 1.0 / ((1 - x * x) ** 2 + (f * B / (F * F)) ** 2) ** 0.5


@lru_cache(maxsize=None)
def syllable_pcm(consonant: str, vowel: str, spread: int = 2, glide: int = 2) -> bytes:
    """One babble syllable as 48 kHz stereo int16 PCM (b'' without numpy)."""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return b''
    locus, f1_factor, onset_ms = CONSONANTS.get(consonant, CONSONANTS[''])
    rng = np.random.default_rng([ord(c) for c in consonant + vowel] + [spread, glide])   # the same every run
    n = int(RATE * SYLLABLE_S)
    t = np.arange(n) / RATE
    start = BASE_HZ * 2 ** (SPREAD[spread % len(SPREAD)] / 12)
    end = start * (1 + GLIDES[glide % len(GLIDES)])
    k = t / SYLLABLE_S
    f0 = start + (end - start) * (k * k * (3 - 2 * k))
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
    voice *= np.clip((t - onset_ms / 1000) / 0.007, 0, 1) * np.clip((SYLLABLE_S - t) / 0.022, 0, 1) ** 1.4
    voice *= LOUDNESS / (np.sqrt(np.mean(voice ** 2)) + 1e-9)
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
    VOWELS = 'aiueo'
    CONSONANT_ORDER = 'bdmnlwyh'

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
        vowel = lower if lower in self.VOWELS else self.VOWELS[code % 5]
        consonant = '' if lower in self.VOWELS else names[(code >> 3) % len(names)].strip()
        return consonant, vowel, (code >> 7) % len(SPREAD), (code >> 11) % len(GLIDES)

    def say(self, char: str) -> bool:
        """A syllable for ``char`` (punctuation and spaces are silent); True when one starts."""
        if not char or char in QUIET:
            return False
        now = time.perf_counter()
        if now - self._last < self.GAP:
            return False
        self._last = now
        if not self.enabled:
            return True   # the mouth still moves
        pcm = syllable_pcm(*self.syllable_for(char))
        if pcm and self._output() is not None:
            self._stream.push(pcm)
        return True


# ---------------------------------------------------------------- typing

class Typewriter(QObject):
    """Types marked lines into labels, one character at a time; ``spoke`` fires per syllable."""

    spoke = Signal(str)
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

    @property
    def running(self) -> bool:
        return bool(self._parts) and self._index < len(self._parts)

    def prepare(self, parts, colors: dict) -> None:
        """``parts``: [(label, marked text)]. Leaves every label blank (space kept) until ``start``."""
        self.stop()
        self._colors = colors
        self._parts = [[label, marked_segments(text), plain(text)] for label, text in parts if text]
        self._index = 0
        self._shown = 0
        for label, segments, _chars in self._parts:
            label.setText(segments_html(segments, colors, 0))

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
        label.setText(segments_html(segments, self._colors, self._shown))
        self.spoke.emit(char)
        self._timer.start(char_delay(char))

    def finish(self) -> None:
        """Everything at once (a click on the words, a window resize)."""
        if not self._parts:
            return
        self._timer.stop()
        was_running = self.running
        for label, segments, _chars in self._parts:
            label.setText(segments_html(segments, self._colors))
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


__all__ = ['CHAT_LINES', 'GREETING', 'MascotVoice', 'Typewriter', 'marked_html', 'marked_segments',
           'marker_colors', 'next_chat_line', 'plain', 'segments_html', 'syllable_pcm', 'voice_enabled']
