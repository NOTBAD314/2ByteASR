"""The motion tokens of feel 「A 沉穩」 (the user's pick, 2026-11-18)."""
from __future__ import annotations

import pytest

from twobyteasr.design import motion_tokens as m


def test_the_feel_is_the_calm_one_the_user_picked():
    assert m.FEEL == 'calm'
    assert m.PAGE_IN == m.Tween(380, (0.32, 0.72, 0.0, 1.0))
    assert m.DIALOG_IN == m.Spring(0.30, 1.0)        # 2026-11-18 evening: quicker (user: too slow)
    assert m.STAGGER_MS == 26 and m.PRESS_SCALE == 0.97


def test_calm_springs_never_overshoot_and_settle_quickly():
    for name, value in m.as_dict().items():
        if isinstance(value, dict) and 'damping' in value:
            spring = m.Spring(**value)
            assert spring.damping >= 1.0, name                 # A 沉穩: no bounce anywhere
            stiffness, coefficient = spring.constants()
            x, v, lowest = 1.0, 0.0, 1.0
            for _ in range(2000):                              # 2 s at 1 ms steps
                v += (-stiffness * x - coefficient * v) * 0.001
                x += v * 0.001
                lowest = min(lowest, x)
            assert lowest > -0.002, (name, lowest)             # does not pass the target
            # Rest within 0.2 % (the eye sees it arrive well before); VALUE, the number catch-up, is the slowest.
            assert spring.settle_ms() <= 800, (name, spring.settle_ms())


def test_nothing_runs_longer_than_the_plan_allows():
    for name, value in m.as_dict().items():
        if isinstance(value, dict) and 'ms' in value:
            assert 100 <= value['ms'] <= 400, name


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_qt_curve_follows_the_bezier(app):
    curve = m.easing_curve(m.PAGE_IN)
    assert curve.valueForProgress(0.0) == pytest.approx(0.0, abs=1e-3)
    assert curve.valueForProgress(1.0) == pytest.approx(1.0, abs=1e-3)
    # (0.32, 0.72, 0, 1) is front-loaded: well past half way at a quarter of the time.
    assert curve.valueForProgress(0.25) > 0.55
    assert curve.valueForProgress(0.5) < 1.0
