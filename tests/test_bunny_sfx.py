"""兔白's sound effects (2026-11-27): every sound is made, quiet enough, rate-limited and muted with her voice."""
import numpy as np

from twobyteasr.app import bunny_sfx
from twobyteasr.app.bunny_sfx import MOVE_SOUNDS, NAMES, BunnySfx, sound_pcm


class _Voice:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.pushed = []

    def play_pcm(self, pcm):
        self.pushed.append(pcm)
        return True


def test_every_sound_is_short_stereo_pcm_below_full_scale():
    for name in NAMES:
        for variant in range(bunny_sfx.VARIANTS):
            pcm = sound_pcm(name, variant)
            assert pcm and len(pcm) % 4 == 0, name
            samples = np.frombuffer(pcm, '<i2').astype(np.float64) / 32767
            assert np.array_equal(samples[0::2], samples[1::2]), name          # the same on both sides
            seconds = len(samples) / 2 / bunny_sfx.RATE
            assert 0.02 < seconds <= 0.9, (name, seconds)
            assert np.max(np.abs(samples)) <= 0.71, name                      # never louder than -3 dB
            assert np.sqrt(np.mean(samples ** 2)) < 0.075, name               # quieter than her voice


def test_moves_only_name_existing_sounds():
    assert set(MOVE_SOUNDS.values()) <= set(NAMES)


def test_play_respects_mute_rate_limit_and_unknown_names():
    voice = _Voice()
    sfx = BunnySfx(voice, warm=False)
    assert sfx.play('hop')
    assert not sfx.play('hop')                       # too soon after the last hop
    assert sfx.play('clank')
    assert not sfx.play('no-such-sound')
    assert len(voice.pushed) == 2
    assert sfx.move('cheer') and not sfx.move('tilt')     # a move with a sound, one without
    muted = _Voice(enabled=False)
    assert not BunnySfx(muted, warm=False).play('grab') and muted.pushed == []


def test_volume_scales_the_samples():
    voice = _Voice()
    BunnySfx(voice, warm=False).play('bonk', volume=0.5)
    quiet = np.abs(np.frombuffer(voice.pushed[0], '<i2')).max()
    loudest = max(np.abs(np.frombuffer(sound_pcm('bonk', variant), '<i2')).max() for variant in range(4))
    assert quiet <= loudest * 0.5 + 2


def test_play_helper_never_raises_without_sfx():
    assert bunny_sfx.play(object(), 'hop') is False

    class Broken:
        class sfx:  # noqa: N801 - a stand-in
            @staticmethod
            def play(*_args, **_kwargs):
                raise RuntimeError('boom')
    assert bunny_sfx.play(Broken(), 'hop') is False
