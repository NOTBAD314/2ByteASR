"""The child-window observer must not poll long-lived children at 2 Hz."""
from twobyteasr import process_diagnostics as diagnostics


def test_new_children_are_watched_closely_then_backed_off():
    owned = {1: ("process", "path", {}, 100.0)}
    # A child that just started: every 0.5 s.
    assert diagnostics._poll_due(owned, 100.6, 100.0)
    assert not diagnostics._poll_due(owned, 100.4, 100.0)
    # After it settled (mpv, media probe...): only every few seconds.
    settled = 100.0 + diagnostics._YOUNG_CHILD_S + 1
    assert not diagnostics._poll_due(owned, settled + 0.6, settled)
    assert diagnostics._poll_due(owned, settled + diagnostics._SETTLED_POLL_S, settled)
    # One new child brings the close watch back for everyone.
    owned[2] = ("process", "path", {}, settled + 1)
    assert diagnostics._poll_due(owned, settled + 1.6, settled + 1.0)
