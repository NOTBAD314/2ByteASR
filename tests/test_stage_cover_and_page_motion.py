"""2026-11-19: pictures that must lie above video are drawn into a kept, transparent window over the
main window (on the screen before the page under them changes); a finished page rises and fades in;
one late frame no longer cuts a motion; pages are prepared at the size they will be shown at."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
    from twobyteasr.design import transitions
    monkeypatch.setattr(transitions, 'enabled', lambda: True)
    root = QWidget()
    root.resize(640, 420)
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    pages = QStackedWidget(root)
    for name in ('old', 'new'):
        page = QWidget()
        page.setObjectName(name)
        pages.addWidget(page)
    layout.addWidget(pages)
    root.pages = pages
    root.show()
    app.processEvents()
    yield root
    transitions.end_all()
    for cover in list(transitions._COVERS.values()):
        cover.deleteLater()
    transitions._COVERS.clear()
    root.close()
    root.deleteLater()
    app.processEvents()


def _ready_cover(window):
    from twobyteasr.design import transitions
    cover = transitions.StageCover(window)
    cover._ready_at = time.perf_counter()
    transitions._COVERS[transitions._key(window)] = cover
    return cover


def _picture(color, size=(640, 420)):
    from PySide6.QtGui import QColor, QPixmap
    picture = QPixmap(*size)
    picture.fill(QColor(color))
    return picture


# ------------------------------------------------------------------ the kept cover
def test_the_cover_is_only_made_on_windows_desktop(window):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.design import transitions
    if QApplication.platformName() != 'windows':
        assert transitions.install_stage_cover(window) is None
    assert transitions.stage_cover(window.pages) is None       # none made: nothing to draw into


def test_a_picture_over_video_is_drawn_into_the_kept_cover_and_waits_to_fade(app, window):
    from twobyteasr.design import transitions
    cover = _ready_cover(window)
    assert cover.isVisible() and cover.ready()
    from PySide6.QtCore import Qt
    assert cover.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)     # never takes a click
    assert cover.windowFlags() & Qt.WindowType.WindowTransparentForInput
    overlay = transitions.cover_page(window.pages, _picture('#c02020'))
    assert overlay is not None and overlay.cover is cover and overlay.parentWidget() is cover
    assert overlay.isVisible() and not overlay._timer.isActive()        # up, not fading yet
    assert overlay.geometry() == window.pages.geometry()
    window.pages.setCurrentIndex(1)
    overlay.release()
    assert overlay._timer.isActive()
    deadline = time.monotonic() + 1.5
    while overlay in transitions._ACTIVE_FADES and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert overlay not in transitions._ACTIVE_FADES
    assert cover.isVisible()                    # the cover itself stays, transparent, for the next one


def test_the_picture_in_the_cover_survives_the_page_area_changing_height(app, window):
    from twobyteasr.design import transitions
    _ready_cover(window)
    overlay = transitions.cover_page(window.pages, _picture('#c02020'))
    window.pages.setFixedHeight(300)            # Home's start bar comes or goes under the stack
    app.processEvents()
    assert overlay in transitions._ACTIVE_FADES and overlay.isVisible()
    overlay.release()


def test_without_a_ready_cover_nothing_is_put_up_ahead(window):
    from twobyteasr.design import transitions
    cover = _ready_cover(window)
    cover._ready_at = None                      # shown, but Windows has not had its turn yet
    assert transitions.cover_page(window.pages, _picture('#c02020')) is None


def test_the_loading_card_covers_itself_before_it_hides(app, window, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.design import transitions
    card = QWidget(window)
    card.setGeometry(40, 40, 300, 200)
    card.show()
    app.processEvents()
    transitions.fade_on_show_and_hide(card)
    started = []
    monkeypatch.setattr(card._show_hide_fade, '_fade', lambda widget, kind: started.append(kind) or True)
    card._show_hide_fade.before_hide()
    card.hide()                                 # the Hide event must not start a second fade
    app.processEvents()
    assert len(started) == 1
    card.show()
    app.processEvents()
    assert len(started) == 2                    # and the next showing fades in as before


# ------------------------------------------------------------------ the motion
def test_a_late_frame_holds_the_motion_instead_of_ending_it():
    from twobyteasr.design import motion_tokens as tokens, transitions

    class Motion:
        _last = 0.0
        _late = 0

        def screen(self):
            return None

    motion = Motion()
    late = (tokens.MAX_FRAME_GAP_MS + 10) / 1000
    at = 0.0
    for _ in range(tokens.MAX_LATE_FRAMES - 1):
        at += late
        step = transitions._frame_step(motion, at)
        assert step is not None and step < late        # one normal frame, no jump
    at += 0.016
    assert transitions._frame_step(motion, at) == pytest.approx(0.016)
    at += late
    assert transitions._frame_step(motion, at) is None  # too many: end on the final picture


def test_the_new_page_rises_and_fades_in_over_the_old(app, window):
    from PySide6.QtGui import QColor, QImage
    from twobyteasr.design import motion_tokens as tokens, transitions
    hold = transitions.PageHold(window.pages, _picture('#ff0000'), wait=False)
    hold.new = _picture('#0000ff')
    hold.phase = 'fade'

    def frame(progress):
        hold.progress = progress
        image = QImage(hold.size(), QImage.Format.Format_RGB32)
        image.fill(QColor('#000000'))
        hold.render(image)
        return image

    start, middle, end = frame(0.0), frame(0.5), frame(1.0)
    assert start.pixelColor(200, 200).red() == 255 and end.pixelColor(200, 200).blue() == 255
    mixed = middle.pixelColor(200, 200)
    assert 80 < mixed.red() < 180 and 80 < mixed.blue() < 180
    top = middle.pixelColor(200, 1)                    # still under the rising page's top edge
    assert top.red() == 255 and top.blue() == 0
    assert tokens.PAGE_ENTER.ms >= 300 and tokens.PAGE_SHIFT_PX > 0
    hold.finish()


def test_a_page_shown_before_waits_one_quiet_frame_at_most_briefly(app, window):
    from twobyteasr.design import motion_tokens as tokens, transitions
    hold = transitions.PageHold(window.pages, _picture('#ff0000'), wait=False)
    now = hold._began
    assert not hold._ready(now)                                    # not in the same instant
    assert hold._ready(now + 0.05)                                 # quiet since: go
    hold._changed = now + 0.07
    assert not hold._ready(now + 0.075)                            # it just changed
    assert hold._ready(now + tokens.PAGE_SHOWN_QUIET_LIMIT_MS / 1000 + 0.001)
    hold.finish()


# ------------------------------------------------------------------ prepared at the shown size
def test_a_page_is_prepared_at_the_height_it_gets_without_homes_start_bar(app):
    from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
    from twobyteasr.app.idle_prepare import future_page_rect
    window = QWidget()
    window.resize(600, 500)
    host = QWidget(window)
    content = QVBoxLayout(host)
    content.setSpacing(12)
    window.content_layout = content
    pages = QStackedWidget(host)
    home, other = QWidget(), QWidget()
    pages.addWidget(home)
    pages.addWidget(other)
    window.settings_scroll = home
    bar = QWidget(host)
    bar.setFixedHeight(60)
    window.bottom_bar = bar
    content.addWidget(pages, 1)
    content.addWidget(bar, 0)
    QVBoxLayout(window).addWidget(host)
    window.show()
    app.processEvents()
    try:
        plain = pages.contentsRect()
        assert future_page_rect(home, pages) == plain
        assert future_page_rect(other, pages).height() == plain.height() + 60 + 12
        bar.hide()
        app.processEvents()
        assert future_page_rect(other, pages) == pages.contentsRect()
    finally:
        window.close()
        window.deleteLater()


def test_page_hold_paints_newly_exposed_area_before_the_fade(app, window):
    from PySide6.QtGui import QColor
    from twobyteasr.design.transitions import PageHold

    stack = window.pages
    size = stack.size()
    # Home's bottom bar used to occupy the new page's bottom strip.
    old = _picture('red', (size.width(), size.height() - 60))
    overlay = PageHold(stack, old)
    overlay.show()
    app.processEvents()
    image = overlay.grab().toImage()
    assert image.pixelColor(10, 10) == QColor('red')
    uncovered = image.pixelColor(10, image.height() - 10)
    assert uncovered.alpha() == 255
    assert uncovered == overlay.palette().window().color()
    overlay.finish()


# ------------------------------------------------------------------ the sideways slide with arriving parts
def test_the_spring_settles_without_overshoot():
    from twobyteasr.design import motion_tokens as tokens, transitions
    values = [transitions.spring_progress(tokens.PAGE_SLIDE_IN, ms) for ms in range(0, 1200, 20)]
    assert values[0] == 0.0 and values[-1] > 0.999
    assert all(b >= a for a, b in zip(values, values[1:])) and max(values) <= 1.0


def test_page_parts_follow_the_widgets_rows_and_leave_the_sidebar(app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QFrame, QWidget
    from twobyteasr.design import transitions
    stack = QWidget()
    stack.resize(1000, 700)
    page = QWidget(stack)
    page.setGeometry(0, 0, 1000, 700)
    sidebar = QFrame(page)
    sidebar.setGeometry(0, 0, 200, 700)
    main = QFrame(page)
    main.setGeometry(210, 0, 790, 700)
    title = QFrame(main)
    title.setGeometry(0, 0, 790, 80)
    grid = QFrame(main)
    grid.setGeometry(0, 100, 790, 600)
    for row in range(4):
        for column in range(5):
            QFrame(grid).setGeometry(column * 150, row * 140, 140, 120)
    stack.show()
    app.processEvents()
    try:
        keep = QRect(0, 0, 200, 700)
        parts = transitions.page_parts(page, stack, keep)
        assert parts and all(not keep.intersects(part) for part in parts)
        assert parts == sorted(parts, key=lambda r: (r.top(), r.left()))
        assert len(parts) == 5                                   # the title, then the grid row by row
        assert parts[0].height() == 80 and all(part.width() > 600 for part in parts[1:])
        whole = transitions.page_parts(page, stack, None)
        assert any(part.left() == 0 for part in whole)           # without a kept sidebar it arrives too
    finally:
        stack.deleteLater()


def test_the_new_page_slides_in_from_the_side_and_the_sidebar_stays(app, window):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage
    from twobyteasr.design import motion_tokens as tokens, transitions
    hold = transitions.PageHold(window.pages, _picture('#ff0000'), wait=False)
    hold.new = _picture('#0000ff')
    keep = QRect(0, 0, 120, hold.height())
    hold.choreo = transitions.PageMotion(1, keep=keep, parts=[QRect(200, 40, 300, 120)], background=QColor('#101010'))
    hold.choreo.prepare(hold)
    hold.phase = 'fade'

    def frame(ms):
        hold._elapsed = ms / 1000
        image = QImage(hold.size(), QImage.Format.Format_RGB32)
        image.fill(QColor('#000000'))
        hold.render(image)
        return image

    start = frame(0)
    assert start.pixelColor(60, 200).blue() == 255                    # the kept sidebar is the new one at once
    assert start.pixelColor(400, 300).red() == 255                    # the rest is still the old page
    middle = frame(tokens.PAGE_SLIDE_OLD.ms)
    assert middle.pixelColor(400, 300).red() < 40                     # the old page has gone by now
    end = frame(hold.choreo.total_ms)
    assert end.pixelColor(400, 300).blue() == 255 and end.pixelColor(250, 100).blue() == 255
    assert hold.choreo.total_ms < 1200
    # Further down the navigation the new page comes from the right; up it, from the left.
    early = tokens.PAGE_SLIDE_DELAY_MS + 30
    assert hold.choreo._arrival(tokens.PAGE_SLIDE_DELAY_MS, early)[0] > 0
    back = transitions.PageMotion(-1, parts=[])
    back.prepare(hold)
    assert back._arrival(tokens.PAGE_SLIDE_DELAY_MS, early)[0] < 0
    hold.finish()


# ------------------------------------------------------------------ dialogs: ghost in the cover, dim that fades
def test_a_closing_dialogs_picture_is_up_in_the_cover_before_it_hides(app, window, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout
    from twobyteasr.design import transitions
    cover = _ready_cover(window)
    motion = transitions.install(app)
    dialog = QDialog(window)
    dialog.setWindowFlags(dialog.windowFlags())
    column = QVBoxLayout(dialog)
    for text in ('一', '二', '三'):
        column.addWidget(QLabel(text))
    dialog.resize(300, 200)
    dialog.move(window.mapToGlobal(window.rect().center()) - dialog.rect().center())
    dialog.show()
    app.processEvents()
    for key in list(motion._flights):
        motion._drop(key, restore=True)
    assert transitions.closing_now(dialog)
    def visible():
        return [child for child in cover.findChildren(transitions._Ghost) if child.isVisible()]
    ghosts = visible()
    assert len(ghosts) == 1 and ghosts[0].cover is cover                   # drawn into the kept cover
    dialog.hide()                                                          # its Hide starts nothing more
    app.processEvents()
    assert visible() == ghosts
    transitions.end_all()
    dialog.deleteLater()


def test_a_larger_dialog_opens_with_its_sections_rising_one_after_another(app, window):
    from PySide6.QtWidgets import QDialog, QFrame, QVBoxLayout
    from twobyteasr.design import transitions
    dialog = QDialog(window)
    column = QVBoxLayout(dialog)
    for _ in range(4):
        part = QFrame()
        part.setMinimumHeight(60)
        column.addWidget(part)
    dialog.resize(600, 420)
    dialog.show()
    app.processEvents()
    parts = transitions.page_parts(dialog, dialog, None, 10)
    assert len(parts) >= 3
    ghost = transitions._Ghost(dialog.grab(), dialog.frameGeometry())
    ghost.parts = parts
    assert ghost.cascade_ms() > transitions._dialog_part_delay(len(parts) - 1)
    ghost.deleteLater()
    dialog.deleteLater()


def test_the_dim_behind_a_dialog_fades_in_and_out(app, window, monkeypatch):
    import time as _time
    from twobyteasr.design import motion_tokens as tokens
    from twobyteasr.design.main_ui_dialogs import _FadingBackdrop
    backdrop = _FadingBackdrop(window, '#000000')
    backdrop.setGeometry(window.rect())
    backdrop.show()
    backdrop.fade_to(_FadingBackdrop.ALPHA, tokens.SCRIM_IN)
    assert backdrop.alpha < _FadingBackdrop.ALPHA                        # not at full strength at once
    done = []
    deadline = _time.monotonic() + 1.0
    while backdrop.alpha < _FadingBackdrop.ALPHA and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.005)
    assert backdrop.alpha == pytest.approx(_FadingBackdrop.ALPHA, abs=0.5)
    backdrop.fade_to(0.0, tokens.SCRIM_OUT, then=lambda: done.append(1))
    deadline = _time.monotonic() + 1.0
    while not done and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.005)
    assert done and backdrop.alpha == 0.0
    backdrop.deleteLater()


def test_windows_10_gets_round_corners_by_a_region(app, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from twobyteasr.design import popup_corners
    monkeypatch.setenv('TWOBYTEASR_ROUND_REGION', '1')
    monkeypatch.setattr(popup_corners.sys, 'platform', 'win32')
    dialog = QDialog()
    popup_corners.round_native_window(dialog, '#574c60')
    assert getattr(dialog, '_rounded_region', None) is not None        # follows the window's size from now on
    dialog.deleteLater()


def test_the_header_reads_the_support_setting_with_the_same_key():
    from twobyteasr.app import support_entry, ui
    assert ui.SUPPORT_HIDDEN_KEY == support_entry.SUPPORT_HIDDEN_KEY
