"""The launch screen's picture of Home is taken from a settled layout (2026-11-27).

User (2026-11-27): for the first two seconds after start Home looked broken — the header's buttons
were cut to two characters and the left card sat narrow beside an empty gap. The launch screen grabs
Home at its first paint and shows that picture while its wordmark flies onto the title; the window had
just grown (to maximized) and its new layout was still queued, so the picture was stale.
"""
from __future__ import annotations


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


NAVIGATION = ('support_button', 'update_button', 'subtitle_studio_button', 'model_workshop_button',
              'recognition_history_button', 'app_settings_button')


def _clipped(window) -> list:
    """Header buttons drawn narrower than their text needs (the broken picture)."""
    out = []
    for name in NAVIGATION:
        button = getattr(window, name)
        if button.isVisible() and button.text() and button.width() + 2 < button.sizeHint().width():
            out.append((name, button.width(), button.sizeHint().width()))
    return out


def test_home_is_laid_out_for_its_final_size_before_the_launch_picture_is_taken():
    import subtitle_core as legacy
    from twobyteasr.app import launch_picture
    from twobyteasr.app.ui import MainWindow
    app = _app()
    window = MainWindow([], legacy, object(), None)
    try:
        window.resize(960, 760)                    # narrow: the header becomes icon buttons
        window.show()
        for _ in range(20):
            app.processEvents()
        assert not window.support_button.text(), 'narrow window: icon-only header'
        window.resize(1680, 1000)                  # maximized: words come back, layout still queued
        window._refresh_header_density()
        assert _clipped(window), 'without settling, the header would be drawn cut off'
        launch_picture.settle_layout(window)
        assert not _clipped(window), _clipped(window)
        assert window.support_button.text()
        picture = window.grab().toImage()
        assert picture.width() >= 1680 * picture.devicePixelRatio() - 1
        _check_left_cover_fits_at_once(window, app)
    finally:
        from PySide6.QtCore import QCoreApplication, QEvent
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)   # gone for the next test
        app.processEvents()


def _expected_cover(card) -> int:
    """What the queued pass would give the cover for the card's size now (run on a twin card state)."""
    hero = card._recent_layout_parts[1]
    before = hero.maximumHeight()
    card._fit_recent_rows()
    wanted = hero.maximumHeight()
    hero.setMaximumHeight(before)
    return wanted


def _check_left_cover_fits_at_once(window, app):
    """2026-11-27 (user: every start the left card's cover is squashed for a second or two): the
    cover was sized by a queued pass, first from the card's default size before it was placed and
    again only after Home's busy first moments; the launch picture caught the squashed one. A new
    card size, and the pre-picture settle, now size the cover at once (no event loop in between)."""
    card = window.studio_entry_card
    hero = window.studio_recent_hero
    card.resize(card.width(), 400)
    hero.setMaximumHeight(150)                     # the squashed cover from a too-small first pass
    card.resize(card.width(), 640)                 # placed at its real size: fitted in resizeEvent
    assert hero.maximumHeight() == _expected_cover(card) > 150
    hero.setMaximumHeight(150)
    window.home_studio_pin._sync_timer.start(0)    # queued, as at start
    from twobyteasr.app import launch_picture
    launch_picture.settle_layout(window)           # the picture's settle places the card and fits now
    assert hero.maximumHeight() == _expected_cover(card) > 150
    pin = window.home_studio_pin
    pin.sync()
    settled_geometry = card.geometry()
    hero.setMaximumHeight(150)
    pin.sync(fit_now=True)
    assert card.geometry() == settled_geometry
    assert hero.maximumHeight() == _expected_cover(card) > 150
