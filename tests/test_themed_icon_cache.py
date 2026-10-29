"""Themed icons are rasterized once per size (2026-10-22).

qtawesome drew each glyph with QPainter text on every paint; toolbars repaint
on each step of a Studio panel-divider drag. The cached engine must give the
same pixels as qtawesome at every scale and follow mode changes.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def test_cached_icon_matches_qtawesome_at_each_scale():
    QApplication.instance() or QApplication([])
    import qtawesome as qta
    from twobyteasr.design.themed_icons import _active_theme, icon_role_color, themed_icon

    icon = themed_icon("fa5s.cut", "primary")
    color = icon_role_color("primary")
    reference = qta.icon("fa5s.cut", color=color, color_active=color, color_disabled=_active_theme(None).disabled)
    for scale in (1.0, 1.25, 1.75, 2.0):
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled):
            cached = icon.pixmap(QSize(24, 24), scale, mode)
            expected = reference.pixmap(QSize(24, 24), scale, mode)
            assert cached.size() == expected.size()
            assert cached.devicePixelRatio() == expected.devicePixelRatio()
            assert cached.toImage() == expected.toImage()


def test_cached_icon_renders_each_size_once(monkeypatch):
    QApplication.instance() or QApplication([])
    import qtawesome as qta
    from twobyteasr.design import themed_icons

    calls = []
    real = qta.icon

    def counting(*args, **kwargs):
        source = real(*args, **kwargs)
        original = source.pixmap
        calls.append(0)

        class Wrapped(QIcon):
            def pixmap(self, *a, **k):  # noqa: D401
                calls[-1] += 1
                return original(*a, **k)
        return Wrapped(source)

    monkeypatch.setattr(themed_icons.qta, "icon", counting)
    icon = themed_icons.themed_icon("fa5s.play", "primary")
    for _ in range(5):
        icon.pixmap(QSize(24, 24), 1.75)
    copy = QIcon(icon)
    copy.pixmap(QSize(24, 24), 1.75)
    assert calls == [1]


def test_explicit_colour_icons_share_cache_and_preserve_pixels():
    QApplication.instance() or QApplication([])
    import qtawesome as qta
    from twobyteasr.design.themed_icons import colored_icon
    a=colored_icon('fa5s.video','#8fc4df');b=colored_icon('fa5s.video','#8fc4df')
    assert a.cacheKey()==b.cacheKey()
    reference=qta.icon('fa5s.video',color='#8fc4df')
    for scale in (1.,1.75,2.):
        assert a.pixmap(QSize(24,24),scale).toImage()==reference.pixmap(QSize(24,24),scale).toImage()
