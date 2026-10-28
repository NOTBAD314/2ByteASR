"""Every dropdown opens the same way (2026-10-26, user: some lists opened
upward, one filled the screen, one hid its first row, rounded lists sat in a
square frame). Plain QComboBox, StudioComboBox and the home page's own popup
share one row height, at most ten rows, a transparent container without a
system shadow, and open below their box (shorter first, above only when not
even three rows fit)."""
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QStyle, QWidget

from twobyteasr.app.ui_zoom import px
from twobyteasr.design import combo_popup, theme_manager


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(theme_manager, "_settings", lambda: QSettings(str(ini), QSettings.Format.IniFormat))
    theme_manager.apply_application_theme(app=application, key="sand")
    yield application
    theme_manager.apply_application_theme(app=application, key="warm")


def host(app):
    window = QWidget()
    area = window.screen().availableGeometry()
    window.setGeometry(area.left() + 10, area.top() + 10, 520, area.height() - 40)
    return window


def opened(combo):
    combo.showPopup()
    QTest.qWait(30)
    return combo.view().window()


def bottom_of(combo):
    return combo.mapToGlobal(QPoint(0, combo.height() - 1)).y() + 1


def test_plain_and_studio_dropdowns_open_a_rounded_list_below(app):
    from twobyteasr.design.studio_theme import StudioComboBox
    window = host(app)
    plain = QComboBox(window)
    plain.addItems([f"item {index}" for index in range(30)])
    plain.setGeometry(20, 20, 300, 36)
    studio = StudioComboBox(window)
    studio.addItems(["one", "two", "three"])
    studio.setGeometry(20, 80, 300, 36)
    window.show()
    QTest.qWait(50)
    try:
        for combo, rows in ((plain, combo_popup.MAX_ROWS), (studio, 3)):
            container = opened(combo)
            assert combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, None, combo) == 0   # a list, not a menu
            assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            assert container.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
            assert type(combo.itemDelegate()).__name__ == "QStyledItemDelegate"
            view = combo.view()
            row = view.sizeHintForRow(0)
            assert row == px(combo_popup.ROW)
            chrome = container.height() - view.viewport().height()
            assert container.height() - chrome == rows * row
            assert container.geometry().top() >= bottom_of(combo)
            assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
            combo.hidePopup()
            QTest.qWait(20)
    finally:
        window.close()


def test_a_dropdown_near_the_bottom_gets_shorter_then_opens_above(app):
    window = host(app)
    area = window.screen().availableGeometry()
    short = QComboBox(window)
    short.addItems([f"row {index}" for index in range(30)])
    tight = QComboBox(window)
    tight.addItems([f"row {index}" for index in range(30)])
    window.show()
    QTest.qWait(50)
    row = px(combo_popup.ROW)
    try:
        # Room below for about six rows: still below, just shorter.
        top = area.bottom() - window.mapToGlobal(QPoint(0, 0)).y() - 36 - 6 * row - 30
        short.setGeometry(20, top, 300, 36)
        container = opened(short)
        assert container.geometry().top() >= bottom_of(short)
        assert container.geometry().bottom() <= area.bottom()
        assert container.height() < combo_popup.MAX_ROWS * row
        short.hidePopup()
        # Not even three rows below: above the box.
        top = area.bottom() - window.mapToGlobal(QPoint(0, 0)).y() - 36 - row
        tight.setGeometry(20, top, 300, 36)
        container = opened(tight)
        assert container.geometry().bottom() < tight.mapToGlobal(QPoint(0, 0)).y()
        tight.hidePopup()
    finally:
        window.close()


def test_home_popup_shares_rows_shape_and_direction(app):
    from twobyteasr.design.main_ui_popup import FramelessPopupCombo
    window = host(app)
    combo = FramelessPopupCombo(window)
    combo.addItems([f"model {index}" for index in range(14)])
    combo.setGeometry(20, 20, 300, 40)
    window.show()
    QTest.qWait(50)
    try:
        assert combo.property(combo_popup.READY)        # owns its popup: no Qt list container
        assert combo.maxVisibleItems() == combo_popup.MAX_ROWS
        combo.showPopup()
        QTest.qWait(300)
        popup = combo._popup
        assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert popup.listing.sizeHintForRow(0) == px(combo_popup.ROW)
        assert popup.geometry().top() >= bottom_of(combo)
        assert popup.property("_comboPopupSheet")       # the shared sheet
        combo.hidePopup()
    finally:
        window.close()


# Further right on the screen than the list is wide: a point in the list's
# own coordinates then never falls inside its screen rectangle.
RIGHT_OF_ITS_WIDTH = (280, 60, 220, 40)


def _press_then_release_on_what_is_shown(popup, fallback, spot):
    """Press on the popup window, then release on the popup only while it is
    still shown, otherwise on the window below, where it does not reach the
    list: what the Mac user saw. (Windows Qt still hands such a release to
    the row that got the press, so the old code worked there.)"""
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QTest.mousePress(popup.windowHandle(), left, none, popup.mapFromGlobal(spot))
    shown_after_press = popup.isVisible()
    receiver = popup if shown_after_press else fallback
    QTest.mouseRelease(receiver.windowHandle(), left, none, receiver.mapFromGlobal(spot))
    QTest.qWait(30)
    return shown_after_press


def test_home_popup_stays_open_until_the_release_chooses_a_row(app):
    """2026-10-28 (Mac user: no dropdown option could be chosen). The
    outside-click check compared a point in the popup's own coordinates with
    its screen rectangle, so the press on a row hid the list before the
    release."""
    from twobyteasr.design.main_ui_popup import FramelessPopupCombo
    window = host(app)
    combo = FramelessPopupCombo(window)
    combo.addItems(["保留原文", "添加标点"])
    combo.setGeometry(*RIGHT_OF_ITS_WIDTH)
    chosen = []
    combo.activated.connect(chosen.append)
    window.show()
    QTest.qWait(50)
    try:
        combo.showPopup()
        QTest.qWait(300)
        popup = combo._popup
        listing = popup.listing
        spot = listing.viewport().mapToGlobal(listing.visualItemRect(listing.item(1)).center())
        assert _press_then_release_on_what_is_shown(popup, window, spot)
        assert combo.currentIndex() == 1 and chosen == [1]
        assert not popup.isVisible()
        # A press outside the list still closes it without choosing.
        combo.showPopup()
        QTest.qWait(300)
        outside = window.mapToGlobal(QPoint(window.width() - 20, window.height() - 20))
        assert not _press_then_release_on_what_is_shown(popup, window, outside)
        assert combo.currentIndex() == 1 and chosen == [1]
    finally:
        window.close()


def test_home_popup_scroll_bar_press_keeps_the_list_open(app):
    """Same check: a press on a long list's scroll bar closed the list on
    every platform."""
    from twobyteasr.design.main_ui_popup import FramelessPopupCombo
    window = host(app)
    combo = FramelessPopupCombo(window)
    combo.addItems([f"model {index}" for index in range(30)])
    combo.setGeometry(*RIGHT_OF_ITS_WIDTH)
    window.show()
    QTest.qWait(50)
    try:
        combo.showPopup()
        QTest.qWait(300)
        popup = combo._popup
        bar = popup.listing.verticalScrollBar()
        assert bar.isVisible()
        spot = bar.mapToGlobal(QPoint(bar.width() // 2, bar.height() - 20))
        assert _press_then_release_on_what_is_shown(popup, window, spot)
        assert popup.isVisible() and bar.value() > 0
        assert combo.currentIndex() == 0
        combo.hidePopup()
    finally:
        window.close()


def test_list_stays_on_the_screen_beside_its_box(app):
    window = host(app)
    area = window.screen().availableGeometry()
    combo = QComboBox(window)
    combo.setGeometry(window.width() - 40, 20, 30, 30)
    window.show()
    QTest.qWait(50)
    try:
        rect = combo_popup.below_rect(combo, 4000, 200, 100)
        assert area.left() <= rect.left() and rect.right() <= area.right()
        assert rect.top() >= bottom_of(combo)
    finally:
        window.close()
