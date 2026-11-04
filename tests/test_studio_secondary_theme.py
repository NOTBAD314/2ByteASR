import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QStyle, QStyleOptionViewItem

from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
from twobyteasr.exports.studio_render_ui import StudioRenderDialog
from twobyteasr.design.studio_theme import (
    SECONDARY_SURFACE_QSS,
    StudioComboBox,
    create_studio_menu,
)
from twobyteasr.studio.studio_ui import LazyFontComboBox, ShortcutSettingsDialog


def _app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path):
    return SubtitleProject(media=StudioMedia(path=str(tmp_path / "source.mp4"), duration_ms=60_000))


def test_secondary_surface_theme_covers_required_states():
    required = (
        "QDialog",
        "QMessageBox",
        "QMenu::item:selected",
        "QMenu::item:disabled",
        "QToolTip",
        "QAbstractItemView::item:hover",
        "QAbstractItemView::item:selected",
        "QScrollBar:vertical",
        "QScrollBar:horizontal",
    )
    assert all(selector in SECONDARY_SURFACE_QSS for selector in required)


def test_menu_and_combobox_popup_share_top_level_theme():
    app = _app()
    menu = create_studio_menu()
    menu.addAction("可用项目")
    disabled = menu.addAction("不可用项目")
    disabled.setEnabled(False)
    assert isinstance(menu, QMenu)
    assert "QMenu::item:selected" in menu.styleSheet()
    assert not menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    combo = StudioComboBox()
    combo.resize(160, 36)
    combo.addItems(("短选项", "一个用于验证弹出层宽度不会截断的长选项", "禁用选项"))
    combo.model().item(2).setEnabled(False)
    combo.show()
    combo.showPopup()
    app.processEvents()
    # 2026-10-26: the list sheet, width and placement are shared by every
    # dropdown and set on the popup window (combo_popup).
    container = combo.view().window()
    assert container.width() >= combo.width()
    assert container.width() >= combo.view().fontMetrics().horizontalAdvance(combo.itemText(1))
    assert "QAbstractItemView::item:selected" in container.styleSheet()
    assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert container.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    combo.hidePopup()
    combo.deleteLater()
    menu.deleteLater()


def _relative_luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        normalized = value / 255.0
        return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _contrast_ratio(left: QColor, right: QColor) -> float:
    lighter = max(_relative_luminance(left), _relative_luminance(right))
    darker = min(_relative_luminance(left), _relative_luminance(right))
    return (lighter + 0.05) / (darker + 0.05)


def test_font_delegate_renders_readable_palette_owned_rows():
    _app()
    combo = LazyFontComboBox()
    view = combo.view()
    delegate = view.itemDelegate()
    index = combo.model().index(0, 0)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Base, QColor("#20282d"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#334148"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f3f6f7"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5f7d69"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#7daf91"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#465057"))

    states = {
        "normal": (QStyle.StateFlag.State_Enabled, QColor("#20282d"), 4.5),
        "hover": (
            QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_MouseOver,
            QColor("#334148"),
            4.5,
        ),
        "selected": (
            QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected,
            QColor("#5f7d69"),
            4.5,
        ),
        "disabled": (QStyle.StateFlag.State_None, QColor("#20282d"), 3.0),
    }
    rendered = {}
    for state_name, (state, background, minimum_contrast) in states.items():
        image = QImage(320, 40, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#ff00ff"))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, image.width(), image.height())
        option.palette = palette
        option.font = view.font()
        option.state = state
        option.widget = view
        painter = QPainter(image)
        delegate.paint(painter, option, index)
        painter.end()
        rendered[state_name] = image

        assert image.pixelColor(0, image.height() // 2) == QColor("#20282d")
        assert image.pixelColor(image.width() // 2, image.height() // 2) == background
        name_pixels = (
            image.pixelColor(x, y)
            for y in range(5, image.height() - 5)
            for x in range(8, 180)
        )
        assert sum(_contrast_ratio(pixel, background) >= minimum_contrast for pixel in name_pixels) >= 8

    recent_image = rendered["normal"]
    accent = QColor("#7daf91")
    assert sum(
        recent_image.pixelColor(x, y) == accent
        for y in range(recent_image.height())
        for x in range(220, recent_image.width())
    ) >= 20
    combo.deleteLater()


def test_shortcut_and_render_dialogs_fit_common_dpi_sizes(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setattr("twobyteasr.exports.studio_render_ui.cached_encoder_choices", lambda *_args: ["libx264"])
    shortcuts = ShortcutSettingsDialog({}, None)
    render = StudioRenderDialog(_project(tmp_path), str(tmp_path / "preview.ass"), 0.0)

    assert "QDialog" in shortcuts.styleSheet()
    assert "QDialog" in render.styleSheet()
    assert all(isinstance(combo, StudioComboBox) for combo in render.findChildren(QComboBox))

    for width, height in ((620, 620), (775, 720), (930, 810)):
        shortcuts.resize(width, height)
        shortcuts.show()
        app.processEvents()
        assert shortcuts.list_view.geometry().right() <= shortcuts.contentsRect().right()
        assert shortcuts.list_view.geometry().bottom() <= shortcuts.contentsRect().bottom()

    for width, height in ((560, 650), (700, 760), (840, 860)):
        render.resize(width, height)
        render.show()
        app.processEvents()
        assert render.layout().contentsRect().right() <= render.contentsRect().right()
        assert render.output.geometry().right() <= render.contentsRect().right()

    shortcuts.close()
    render.close()
    shortcuts.deleteLater()
    render.deleteLater()


def test_render_dialog_filters_codecs_by_container(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr(
        "twobyteasr.exports.studio_render_ui.cached_encoder_choices",
        lambda _ffmpeg, codec: {
            "h264": ["libx264"],
            "hevc": ["libx265"],
            "av1": ["libaom-av1"],
        }[codec],
    )
    render = StudioRenderDialog(_project(tmp_path), str(tmp_path / "preview.ass"), 0.0)

    render.container.setCurrentText("WebM")
    assert [render.codec.itemData(index) for index in range(render.codec.count())] == ["av1"]
    assert [render.quality_mode.itemData(index) for index in range(render.quality_mode.count())] == [
        "recommended", "high", "size", "custom"
    ]
    render.container.setCurrentText("FLV")
    assert [render.codec.itemData(index) for index in range(render.codec.count())] == ["h264"]
    render.resolution.setCurrentIndex(render.resolution.findText("Custom"))
    assert not render.custom_resolution_widget.isHidden()
    render.close()
    render.deleteLater()


def test_render_dialog_defaults_archive_projects_to_exports(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr("twobyteasr.exports.studio_render_ui.cached_encoder_choices", lambda *_args: ["libx264"])
    archive = tmp_path / "2ByteASR Projects" / "source"
    exports = archive / "exports"
    exports.mkdir(parents=True)
    project_path = archive / "source.2byteproj"
    project_path.write_text("{}", encoding="utf-8")

    render = StudioRenderDialog(
        _project(tmp_path),
        str(tmp_path / "preview.ass"),
        0.0,
        project_path=project_path,
    )
    assert Path(render.output.text()).parent == exports
    render.close()
    render.deleteLater()


def test_render_dialog_cold_cache_scans_encoders_in_background(tmp_path, monkeypatch):
    import threading

    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    scanned = threading.Event()

    def fake_scan(_ffmpeg):
        scanned.set()
        return {}

    monkeypatch.setattr(
        "twobyteasr.exports.studio_render_ui.scan_encoder_capabilities", fake_scan
    )

    def fail_synchronous_probe(*_args, **_kwargs):
        raise AssertionError("dialog must not probe encoders on the UI thread")

    monkeypatch.setattr(
        "twobyteasr.exports.studio_render.available_encoders", fail_synchronous_probe
    )

    render = StudioRenderDialog(_project(tmp_path), str(tmp_path / "preview.ass"), 0.0)
    assert scanned.wait(5), "background capability scan never ran"
    assert not render.render_button.isEnabled()
    app.processEvents()
    # The fake scan wrote no cache; the dialog must report once instead of
    # looping back into another scan.
    assert "未能检测可用编码器" in render.status.text()
    render.close()
    render.deleteLater()
