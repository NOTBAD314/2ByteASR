"""兔白's little sound effects: hops, landings, being grabbed, the pointer chase, her tools (2026-11-27).

User (2026-11-27): give 兔白's actions cute sound effects — walking, being grabbed, catching the
pointer, mending, and so on; every action should have one.

Everything is synthesised here with numpy (no sound files): short, soft and bright, never
piercing, a little quieter than her babble voice. Her vocal bits ("nya!", "eek", giggles) are her
own babble syllables (``tour_mascot.syllable_pcm``), so they sound like her. She is a keychain
(「一动就叮当响」), so catching the pointer, swinging and spinning ring like little keychain bells.

Sounds go out through her chat's ``MascotVoice`` (one audio output for voice and effects) and
follow its on/off switch: muting her voice in the chat mutes these too. Without an audio device,
under the offscreen platform (tests, audits) or without numpy, nothing plays and nothing fails.

Names (``NAMES``): hop, pip, land, plop, leap, pounce, catch, grab, whee, bonk, clank, knock, wipe,
page, tap, pop, giggle, puff, snore, swing, cheer, sparkle, dizzy, spin, pat, hmph, yawn. The sounds
are made once, in a background thread a little after she appears (``WARM_AFTER_S``), so the first
hop never waits for numpy.
"""
from __future__ import annotations

import random
import time
from functools import lru_cache

RATE = 48000
GAIN = 0.75                       # all effects, against her voice (1.0)
VARIANTS = 4                      # pitch variants per sound, so repeated hops are not identical
DEFAULT_GAP_S = 0.06
WARM_AFTER_S = 6.0                # after the start's busy seconds (startup holds the GIL)
GAPS = {'hop': 0.085, 'bonk': 0.16, 'snore': 2.5, 'catch': 0.4, 'grab': 0.25, 'whee': 0.5,
        'giggle': 0.6, 'page': 0.25, 'swing': 0.35, 'sparkle': 0.3, 'spin': 0.4, 'dizzy': 1.5}
# A move of hers (bunny_moves.MOVES) and the sound it starts with (BunnyMascot.play).
MOVE_SOUNDS = {
    'cheer': 'cheer', 'dance': 'cheer', 'spin': 'spin', 'dizzy': 'dizzy', 'tumble': 'bonk',
    'tickle': 'giggle', 'blow': 'puff', 'lean_nap': 'snore', 'curl_nap': 'snore', 'doze': 'snore',
    'flick': 'pop', 'heart_hands': 'sparkle', 'beam': 'sparkle', 'wake': 'pop', 'pout': 'hmph',
    'turn_away': 'hmph', 'shy': 'pat', 'push': 'tap', 'sit': 'plop', 'hang': 'swing', 'read': 'page',
    'wave': 'pat', 'ears_up': 'pip', 'yawn': 'yawn', 'wipe_brow': 'puff', 'glint': 'sparkle',
}


# ---------------------------------------------------------------- synthesis
def _np():
    import numpy as np
    return np


def _t(seconds: float):
    np = _np()
    return np.arange(int(RATE * seconds)) / RATE


def _env(n: int, attack: float, decay: float, *, hold: float = 0.0):
    """Quick attack, a hold, then an exponential-ish fall to silence at the end."""
    np = _np()
    t = np.arange(n) / RATE
    rise = np.clip(t / max(attack, 1e-4), 0, 1)
    tail = np.clip((t - hold) / max(decay, 1e-4), 0, None)
    fall = np.exp(-4.0 * tail)
    end = np.clip((n / RATE - t) / 0.006, 0, 1)          # no click at the very end
    return rise * fall * end


def _glide(f0: float, f1: float, seconds: float, *, shape: float = 1.0, vibrato=(0.0, 0.0)):
    """A soft tone (fundamental + a little 2nd and 3rd harmonic) gliding from f0 to f1 Hz."""
    np = _np()
    t = _t(seconds)
    k = (t / seconds) ** shape if seconds > 0 else t
    freq = f0 + (f1 - f0) * k
    depth, rate = vibrato
    if depth:
        freq = freq * (1 + depth * np.sin(2 * np.pi * rate * t))
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return np.sin(phase) + 0.22 * np.sin(2 * phase) + 0.06 * np.sin(3 * phase)


def _noise(seconds: float, centre: float, width: float, seed: int):
    """Band-limited noise around ``centre`` Hz (a Gaussian band of ``width`` Hz)."""
    np = _np()
    n = int(RATE * seconds)
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    band = np.fft.irfft(spectrum * np.exp(-((freqs - centre) / max(width, 1.0)) ** 2), n)
    return band / (np.max(np.abs(band)) + 1e-9)


def _bells(strikes, partials=(1.0, 1.5, 2.0, 2.76), base: float = 2637.0, decay: float = 0.16,
           seconds: float = 0.45, seed: int = 3):
    """Keychain bells: ``strikes`` = [(time s, pitch factor, loudness)], inharmonic partials."""
    np = _np()
    rng = np.random.default_rng(seed)
    out = np.zeros(int(RATE * seconds))
    for at, pitch, loud in strikes:
        start = int(RATE * at)
        n = len(out) - start
        if n <= 0:
            continue
        t = np.arange(n) / RATE
        ring = np.zeros(n)
        for index, partial in enumerate(partials):
            f = base * pitch * partial * (1 + 0.004 * rng.standard_normal())
            ring += np.exp(-t / (decay / (1 + index * 0.6))) * np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) / (1 + index)
        ring *= np.clip(t / 0.0015, 0, 1)
        out[start:] += loud * ring
    return out


def _syllable(consonant: str, vowel: str, spread: int, glide: int, mood: str):
    """One of her own babble syllables as float mono (her voice, so the yelps sound like her)."""
    np = _np()
    from .tour_mascot import syllable_pcm
    pcm = syllable_pcm(consonant, vowel, spread, glide, mood)
    if not pcm:
        return np.zeros(1)
    stereo = np.frombuffer(pcm, '<i2').astype(np.float64) / 32767
    return stereo[::2]


def _mix(*parts):
    """Sum (offset s, signal, gain) parts into one signal."""
    np = _np()
    length = max(int(RATE * offset) + len(signal) for offset, signal, _gain in parts)
    out = np.zeros(length)
    for offset, signal, gain in parts:
        start = int(RATE * offset)
        out[start:start + len(signal)] += gain * signal
    return out


def _shape(name: str, p: float):
    """The float mono signal of sound ``name`` at pitch factor ``p`` (unnormalised)."""
    np = _np()
    if name == 'hop':             # a light "pyon" as she takes off
        s = _glide(560 * p, 920 * p, 0.06, shape=0.7)
        return s * _env(len(s), 0.003, 0.035)
    if name == 'pip':             # ears up: the tiniest blip
        s = _glide(1300 * p, 1600 * p, 0.04)
        return 0.6 * s * _env(len(s), 0.002, 0.02)
    if name == 'land':            # a soft "pomf"
        s = _glide(240 * p, 120 * p, 0.12, shape=0.6)
        thud = _noise(0.05, 300, 260, 11)
        return _mix((0, s * _env(len(s), 0.002, 0.05), 1.0), (0, thud * _env(len(thud), 0.001, 0.02), 0.5))
    if name == 'plop':            # set down / sits: "plop"
        s = _glide(760 * p, 300 * p, 0.08, shape=0.5)
        return s * _env(len(s), 0.002, 0.04)
    if name == 'leap':            # a springy "boing" upwards
        s = _glide(380 * p, 1180 * p, 0.17, shape=0.8, vibrato=(0.025, 14))
        return s * _env(len(s), 0.004, 0.08, hold=0.05)
    if name == 'pounce':          # "nya!" and a spring
        yelp = _syllable('n', 'a', 4, 4, 'excited')
        spring = _shape('leap', p * 1.1)
        return _mix((0, yelp, 1.0), (0.03, spring, 0.45))
    if name in ('catch', 'swing'):  # the keychain rings
        strikes = ([(0, 1.0, 1.0), (0.05, 1.19, 0.7), (0.11, 0.94, 0.55)] if name == 'catch'
                   else [(0, 1.0, 0.6), (0.14, 1.06, 0.4)])
        return _bells(strikes, base=2637 * p, seconds=0.5 if name == 'catch' else 0.42)
    if name == 'grab':            # "eek!" as she is picked up
        yelp = _syllable('', 'i', 5, 4, 'surprised')
        squeak = _glide(1500 * p, 2000 * p, 0.07, vibrato=(0.03, 30))
        return _mix((0, yelp, 1.0), (0.01, squeak * _env(len(squeak), 0.003, 0.03), 0.25))
    if name == 'whee':            # thrown: "wheee"
        s = _glide(720 * p, 1380 * p, 0.34, shape=0.6, vibrato=(0.03, 8))
        return 0.8 * s * _env(len(s), 0.02, 0.12, hold=0.18)
    if name == 'bonk':            # bumps the window's edge: "boink"
        s = _glide(560 * p, 300 * p, 0.12, shape=0.5)
        click = _noise(0.012, 2500, 1500, 5)
        return _mix((0, s * _env(len(s), 0.001, 0.05), 1.0), (0, click * _env(len(click), 0.0005, 0.004), 0.35))
    if name == 'clank':           # wrench on the gear: a small bright "kling"
        ring = _bells([(0, 1.0, 1.0)], partials=(1.0, 2.49, 3.71, 5.12), base=1180 * p, decay=0.12, seconds=0.28,
                      seed=7)
        click = _noise(0.006, 4000, 2500, 9)
        return _mix((0, ring, 1.0), (0, click, 0.4))
    if name == 'knock':           # knocks on a button: a little wooden "tok"
        s = _glide(980 * p, 760 * p, 0.045)
        wood = _noise(0.03, 1300, 500, 13)
        return _mix((0, s * _env(len(s), 0.001, 0.015), 0.8), (0, wood * _env(len(wood), 0.0005, 0.01), 0.6))
    if name == 'wipe':            # polishing: a rubbery squeak
        s = _glide(1850 * p, 2250 * p, 0.08, vibrato=(0.04, 32))
        return 0.5 * s * _env(len(s), 0.01, 0.03, hold=0.03)
    if name == 'page':            # a page turns
        swish = _noise(0.16, 4200, 2200, 17)
        t = _t(0.16)
        return 0.7 * swish * np.sin(np.pi * t / 0.16) ** 2
    if name == 'tap':             # pushes / stomps: a soft "puff" of a thud
        s = _glide(200 * p, 150 * p, 0.07)
        air = _noise(0.06, 700, 500, 19)
        return _mix((0, s * _env(len(s), 0.002, 0.03), 0.9), (0, air * _env(len(air), 0.002, 0.02), 0.4))
    if name == 'pop':             # a borrowed icon flies: "pop"
        s = _glide(480 * p, 1450 * p, 0.035, shape=0.5)
        return s * _env(len(s), 0.001, 0.02)
    if name == 'giggle':          # tickling: "hi-hi-hi"
        parts = [(index * 0.095, _syllable('', 'i', 2 + index, 3, 'happy'), 1.0 - index * 0.12) for index in range(3)]
        return _mix(*parts)
    if name == 'puff':            # blows / wipes her brow: "fuu"
        air = _noise(0.28, 900, 700, 23)
        t = _t(0.28)
        return 0.6 * air * np.sin(np.pi * t / 0.28) ** 1.5
    if name == 'snore':           # dozing: a tiny "zzz"
        air = _noise(0.8, 420, 240, 29)
        t = _t(0.8)
        return 0.35 * air * (0.6 + 0.4 * np.sin(2 * np.pi * 7 * t)) * np.sin(np.pi * t / 0.8) ** 2
    if name == 'cheer':           # "yay!" and a twinkle
        yelp = _syllable('y', 'a', 4, 4, 'excited')
        return _mix((0, yelp, 1.0), (0.05, _shape('sparkle', p), 0.4))
    if name == 'sparkle':         # shiny: three rising bells
        return _bells([(0, 1.0, 0.8), (0.06, 1.26, 0.7), (0.12, 1.5, 0.6)], base=2093 * p, decay=0.12, seconds=0.42,
                      seed=31)
    if name == 'dizzy':           # dizzy: a wobbly "woo-woo"
        s = _glide(760 * p, 620 * p, 0.55, vibrato=(0.08, 5))
        return 0.55 * s * _env(len(s), 0.03, 0.2, hold=0.3)
    if name == 'spin':            # a twirl: a whoosh and a jingle
        whoosh = _noise(0.3, 1600, 900, 37)
        t = _t(0.3)
        return _mix((0, 0.5 * whoosh * np.sin(np.pi * t / 0.3) ** 2, 1.0),
                    (0.12, _bells([(0, 1.0, 0.5)], base=2637 * p, seconds=0.3), 0.6))
    if name == 'pat':             # pleased: a little "mi~"
        return _syllable('m', 'i', 3, 4, 'happy')
    if name == 'hmph':            # pouting: "hm!"
        return _syllable('n', 'e', 1, 0, 'teasing')
    if name == 'yawn':            # a soft "aa~" yawn
        return 0.6 * _syllable('', 'a', 0, 1, 'whisper')
    raise KeyError(name)


NAMES = ('hop', 'pip', 'land', 'plop', 'leap', 'pounce', 'catch', 'grab', 'whee', 'bonk', 'clank', 'knock', 'wipe',
         'page', 'tap', 'pop', 'giggle', 'puff', 'snore', 'swing', 'cheer', 'sparkle', 'dizzy', 'spin', 'pat', 'hmph',
         'yawn')
_PITCH = (1.0, 1.06, 0.95, 1.12)
_LOUDNESS = {'snore': 0.5, 'page': 0.8, 'wipe': 0.7, 'pip': 0.6, 'hop': 0.8, 'puff': 0.7, 'yawn': 0.7}


@lru_cache(maxsize=None)
def sound_pcm(name: str, variant: int = 0, pitch: float = 1.0) -> bytes:
    """Sound ``name`` as 48 kHz stereo int16 PCM (b'' without numpy). ``variant`` picks one of a few
    pitches; ``pitch`` scales it further (a domino row rises step by step)."""
    try:
        np = _np()
    except Exception:  # noqa: BLE001 - no numpy: silent
        return b''
    signal = _shape(name, _PITCH[variant % len(_PITCH)] * float(pitch))
    peak = float(np.max(np.abs(signal))) if len(signal) else 0.0
    if peak <= 0:
        return b''
    rms = float(np.sqrt(np.mean(signal ** 2)))
    # Loudness by RMS (as her voice), capped so no peak passes -3 dB.
    level = 0.06 * _LOUDNESS.get(name, 1.0) * GAIN / max(rms, 1e-9)
    signal = signal * min(level, 0.7 / peak)
    mono = (np.clip(signal, -0.95, 0.95) * 32767).astype('<i2')
    return np.repeat(mono, 2).tobytes()


# ---------------------------------------------------------------- playing
class BunnySfx:
    """Plays the effects through ``voice`` (a ``tour_mascot.MascotVoice``), rate-limited per name."""

    def __init__(self, voice, *, warm: bool = True):
        self.voice = voice
        self._last: dict[str, float] = {}
        self._rng = random.Random()
        if warm and getattr(voice, 'enabled', False):
            import threading
            timer = threading.Timer(WARM_AFTER_S, warm_up)
            timer.daemon = True
            timer.start()

    def play(self, name: str, *, volume: float = 1.0, pitch: float = 1.0) -> bool:
        voice = self.voice
        if voice is None or not getattr(voice, 'enabled', False) or name not in NAMES:
            return False
        now = time.perf_counter()
        if now - self._last.get(name, -9.0) < GAPS.get(name, DEFAULT_GAP_S):
            return False
        self._last[name] = now
        try:
            pcm = sound_pcm(name, self._rng.randrange(VARIANTS), round(float(pitch), 3))
            if not pcm:
                return False
            if volume != 1.0:
                pcm = _scaled(pcm, volume)
            return bool(voice.play_pcm(pcm))
        except Exception:  # noqa: BLE001 - a missing sound never breaks her
            return False

    def move(self, move_name: str) -> bool:
        """The sound a move of hers starts with (``MOVE_SOUNDS``), if it has one."""
        name = MOVE_SOUNDS.get(move_name)
        return self.play(name) if name else False


def warm_up() -> None:
    """Make every sound's variants now (a background thread; numpy's FFTs let the GUI run)."""
    try:
        for variant in range(VARIANTS):
            for name in NAMES:
                sound_pcm(name, variant, 1.0)
                time.sleep(0.002)               # leave the GIL to the window between sounds
    except Exception:  # noqa: BLE001 - made on first use instead
        pass


def _scaled(pcm: bytes, volume: float) -> bytes:
    np = _np()
    data = np.frombuffer(pcm, '<i2').astype(np.float64) * max(0.0, min(1.5, float(volume)))
    return np.clip(data, -32767, 32767).astype('<i2').tobytes()


def play(owner, name: str, **options) -> bool:
    """``owner.sfx.play(name)`` when ``owner`` (her chat, mascot, puck or errands) has one; never raises."""
    sfx = getattr(owner, 'sfx', None)
    if sfx is None:
        return False
    try:
        return sfx.play(name, **options)
    except Exception:  # noqa: BLE001
        return False


__all__ = ['BunnySfx', 'GAPS', 'MOVE_SOUNDS', 'NAMES', 'play', 'sound_pcm', 'warm_up']
