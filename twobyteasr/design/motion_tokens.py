"""The app's motion tokens: feel 「A 沉穩」, picked by the user on 2026-11-18.

User (2026-11-18): motion should feel like macOS / the iPhone site — smooth, continuous, nothing
popping in. From the interactive demo (now / A calm / B lively / C mixed) they chose A: almost no
overshoot, long soft deceleration, quiet and weighty. These numbers are the single source for
every animation; the motion toolkit (docs/exec-plans/active/2026-11-18-premium-motion.md) reads
them, and the demo page used exactly these values.

Two kinds of timing:

- ``Spring(response, damping)``: like SwiftUI. ``response`` is the seconds of one undamped
  oscillation (how quick), ``damping`` 1.0 means it arrives without overshoot. A spring keeps its
  velocity when retargeted, so an animation interrupted halfway continues from where it is.
- ``Tween(ms, bezier)``: a fixed duration on a cubic-bezier curve, for fades and exits.

Pure data plus two small helpers; Qt is imported only inside ``easing_curve``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FEEL = 'calm'          # 「A 沉穩」


@dataclass(frozen=True)
class Spring:
    response: float    # seconds
    damping: float     # 1.0 = critically damped (no overshoot)

    def constants(self) -> tuple[float, float]:
        """(stiffness, damping coefficient) for a unit mass."""
        omega = 2 * math.pi / self.response
        return omega * omega, 2 * self.damping * omega

    def settle_ms(self, tolerance: float = 0.002) -> int:
        """About how long until it rests within ``tolerance`` of its target (from rest, distance 1)."""
        stiffness, coefficient = self.constants()
        x, v, t, h = 1.0, 0.0, 0.0, 1 / 960
        while t < 5.0:
            v += (-stiffness * x - coefficient * v) * h
            x += v * h
            t += h
            if abs(x) < tolerance and abs(v) < tolerance * 10:
                break
        return round(t * 1000)


@dataclass(frozen=True)
class Tween:
    ms: int
    bezier: tuple[float, float, float, float]


APPLE_EASE = (0.32, 0.72, 0.0, 1.0)     # long, soft deceleration (iOS sheets, macOS windows)
EXIT_EASE = (0.4, 0.0, 1.0, 1.0)        # leaves quickly, no lingering
FADE_EASE = (0.33, 1.0, 0.68, 1.0)      # OutCubic: short fades and scrims

# Pages: the old page steps back and fades, the new one rises a little and fades in.
PAGE_IN = Tween(380, APPLE_EASE)
PAGE_OUT = Tween(190, EXIT_EASE)
PAGE_IN_DELAY_MS = 40                   # the new page starts while the old one is leaving
PAGE_SHIFT_PX = 14                      # the new page rises this far
PAGE_OUT_SCALE = 0.985                  # the old page shrinks to this

# 2026-11-18, first build in the app: the new page is live (and clickable) at once; a picture of
# the old page lies over it and steps back while it fades, so nothing jumps when it ends.
PAGE_CROSSFADE = Tween(180, APPLE_EASE)   # 2026-11-18 evening (user: too slow, sluggish): 320 -> 180
# 2026-11-19 (user: going to a page flashes two or three times before it is there): a page that is
# still building is not shown. The old page's picture stays until nothing in the new page has
# been added, laid out, shown or hidden for PAGE_SETTLE_QUIET_MS (and it says it is done); then one
# cross-fade between two finished pictures. A page that needs longer than PAGE_SETTLE_LIMIT_MS
# (a first visit in the first second after startup, before the pages were prepared) is shown as
# far as it is and finishes in view: a click is answered within half a second either way.
PAGE_SETTLE_QUIET_MS = 48
PAGE_SETTLE_LIMIT_MS = 450
# A page shown before is not built again, but its show still queues small work (a status re-check,
# badges): one quiet frame is waited for, at most this long, so that work does not land on the motion.
PAGE_SHOWN_QUIET_LIMIT_MS = 80
# 2026-11-19 (user: going to the workshop or the term library there is hardly any motion to see):
# the finished new page now enters as in the demo they picked — it rises PAGE_SHIFT_PX and fades in
# on PAGE_IN after PAGE_IN_DELAY_MS, over the old page's picture — instead of the 180 ms cross-fade
# whose curve had done most of its change in the first 70 ms.
PAGE_ENTER = PAGE_IN
# 2026-11-19 (user, after the three drafts: "option 1's slide as the base, with option 3's rising
# cascade, but from right to left or left to right: lively, good looking and with a direction"):
# a page switch slides the new content in along the navigation order (a page further down comes
# from the right), its parts arriving one after another; the old content steps the other way and
# fades; a sidebar shared by both pages stays and its highlight glides to the new item.
PAGE_SLIDE_PX = 56                      # how far the new content travels (logical px)
PAGE_SLIDE_OLD_SHARE = 0.6              # the old content leaves this part of the distance
PAGE_SLIDE_OLD = Tween(200, (0.4, 0.0, 0.6, 1.0))
PAGE_SLIDE_IN = Spring(0.46, 1.0)       # each part's travel: the list spring (LIST), no overshoot
PAGE_SLIDE_FADE = Tween(240, FADE_EASE)  # each part's fade-in
PAGE_SLIDE_DELAY_MS = 60                # the new content starts while the old is leaving
PAGE_SLIDE_STAGGER_MS = 24              # one part after another, at most PAGE_SLIDE_STAGGER_STEPS apart
PAGE_SLIDE_STAGGER_STEPS = 6            # (34 ms x 8 left the middle of a page empty for 0.3 s)
PAGE_SLIDE_PARTS_MAX = 14
NAV_GLIDE = Spring(0.32, 1.0)           # the sidebar highlight moving to its new item (SMALL)
NAV_GLIDE_FADE = Tween(160, FADE_EASE)
# 2026-11-19 (user picked option A for the start): the kept picture of Home fades out over the
# real window once it has painted, instead of vanishing. Longer and softer than a page fade: the two
# pictures may differ after an update, and the change should read as one calm dissolve.
LAUNCH_HANDOFF = Tween(260, FADE_EASE)
# A frame later than this during a motion does not move it on by more than one normal frame (no
# jump); after MAX_LATE_FRAMES of them the motion ends on its final picture: a busy GUI thread gets
# no motion rather than a 5 fps one (user, 2026-11-18: "fps only 5", "twitching"). Until
# 2026-11-19 the first late frame ended it, and one 55 ms frame (a page's own re-check right
# after showing) was enough to cut a page's motion to its end.
MAX_FRAME_GAP_MS = 45
MAX_LATE_FRAMES = 3
# Panels slide out to their side and in from it (user: tool panel to the right, subtitle list left).
PANEL_SLIDE_IN = Tween(200, APPLE_EASE)
PANEL_SLIDE_OUT = Tween(160, EXIT_EASE)

# Dialogs and popovers grow out of the control that opened them and shrink back into it.
DIALOG_IN = Spring(0.30, 1.0)                # 2026-11-18 evening: 0.42 -> 0.30 (quicker, still no bounce)
DIALOG_OUT = Tween(170, EXIT_EASE)
DIALOG_FADE_IN = Tween(140, FADE_EASE)
SCRIM_IN = Tween(220, FADE_EASE)
SCRIM_OUT = Tween(200, EXIT_EASE)
DIALOG_MIN_SCALE = 0.25                 # never starts smaller than this, however small the button
# 2026-11-19 (user: the settings and the tutorial open with no motion of their own): while a larger
# dialog grows out of its button, its sections rise into place one after another, as page parts do.
DIALOG_PARTS_MAX = 10
DIALOG_PART_RISE = Spring(0.32, 1.0)    # SMALL
DIALOG_PART_RISE_PX = 14
DIALOG_PART_FADE = Tween(200, FADE_EASE)
DIALOG_PART_DELAY_MS = 40
DIALOG_PART_STAGGER_MS = 22
DIALOG_PART_STEPS = 6

# A card that becomes a page (shared element) and goes back.
SHARED = Spring(0.50, 1.0)
SHARED_BACK = Spring(0.36, 1.0)
SHARED_CONTENT_DELAY_MS = 120           # the page's content fades in after the card has grown a bit

# Small things: toggles, segmented controls, the sliding highlight under tabs, progress bars.
SMALL = Spring(0.32, 1.0)

# Lists: items come in one after another and make room for inserts and deletes.
LIST = Spring(0.46, 1.0)
STAGGER_MS = 26
STAGGER_MAX = 8                         # items after the eighth come in together with it
LIST_ENTER_SHIFT_PX = 12
ITEM_EXIT = Tween(150, EXIT_EASE)

# Pressing: down quickly, back on the small spring.
PRESS_SCALE = 0.97
PRESS_IN = Spring(0.16, 1.0)

# Wheel and touchpad scrolling ease toward the target instead of jumping a notch at a time.
SCROLL = Spring(0.36, 1.0)

# Numbers and progress catch up with their value instead of jumping.
VALUE = Spring(0.55, 1.0)


def easing_curve(tween: Tween):
    """A ``QEasingCurve`` for this tween's cubic-bezier."""
    from PySide6.QtCore import QEasingCurve, QPointF
    x1, y1, x2, y2 = tween.bezier
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


def as_dict() -> dict:
    """Every token by name, for the demo page and for reports."""
    out = {'feel': FEEL}
    for name, value in globals().items():
        if name.isupper() and isinstance(value, (Spring, Tween, int, float, tuple)):
            out[name] = value.__dict__ if isinstance(value, (Spring, Tween)) else value
    return out


__all__ = ['FEEL', 'Spring', 'Tween', 'as_dict', 'easing_curve']
