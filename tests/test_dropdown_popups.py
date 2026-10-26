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
