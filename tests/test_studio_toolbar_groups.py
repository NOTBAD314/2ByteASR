"""Geometry regressions for the real toolbar's five functional groups."""
import pytest
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

from twobyteasr.design.studio_theme import build_studio_qss, apply_secondary_surface_theme
from twobyteasr.studio.studio_toolbar_layout import install_command_groups, toolbar_geometry_snapshot
from twobyteasr.design.ui_theme import theme_definition


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def toolbar(app, width=2048, theme="grape"):
    page = QWidget()
    page.setObjectName("subtitleStudio")
    page.setStyleSheet(build_studio_qss(theme_definition(theme)))
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    old = QHBoxLayout()
    outer.addLayout(old)

    def icon(name):
        button = QToolButton()
        button.setObjectName("studioTool")
        button.setToolTip(name)
        button.setIconSize(QSize(24, 24))
        button.setMinimumSize(32, 32)
        old.addWidget(button)
        return button

    title = QLabel("时间轴")
    old.addWidget(title)
    old.addSpacing(10)
    for name in ("媒体池", "视频轨", "字幕轨", "选择", "向前选择", "剃刀", "合并", "转场", "更多"):
        icon(name)
    old.addStretch(1)
    transport = icon("上一帧")
    icon("播放")
    icon("下一帧")
    page.timecode_input = QLineEdit("00:00:07.425")
    page.timecode_input.setObjectName("timelineTimecodeInput")
    page.timecode_input.setFixedWidth(128)
    old.addWidget(page.timecode_input)
    duration = QLabel("/ 1:07")
    duration.setObjectName("timelineDuration")
    old.addWidget(duration)
    speed = QComboBox()
    speed.addItem("1x")
    speed.setFixedWidth(68)
    old.addWidget(speed)
    old.addWidget(QLabel("音量"))
    volume = QSlider(Qt.Orientation.Horizontal)
    volume.setFixedWidth(72)
    old.addWidget(volume)

    def button(text):
        result = QPushButton(text)
        result.setObjectName("studioButton")
        old.addWidget(result)
        return result

    diagnostics = button("声音诊断")
    old.addStretch(1)
    zoom = icon("缩小")
    icon("放大")
    button("适应窗口")
    toggles = []
    for text in ("波形", "缩略图", "跟随", "吸附"):
        toggle = QCheckBox(text)
        toggle.setChecked(True)
        old.addWidget(toggle)
        toggles.append(toggle)
    refine = button("AI 断句")
    page.project_range_bar = QWidget()
    range_layout = QHBoxLayout(page.project_range_bar)
    range_layout.addWidget(QPushButton("入点 I"))
    range_layout.addWidget(QLineEdit("工程开头"))
    range_layout.addWidget(QPushButton("出点 O"))
    range_layout.addWidget(QLineEdit("工程结尾"))
    range_layout.addStretch(1)
    range_layout.addWidget(QPushButton("保存当前帧"))
    range_layout.addWidget(QPushButton("制作封面"))
    outer.addWidget(page.project_range_bar)
    outer.addStretch(1)
    install_command_groups(page, outer, old, transport, zoom,
                           diagnostics_start=diagnostics, toggles_start=toggles[0], refine_start=refine)
    page.resize(width, 300)
    page.show()
    app.processEvents()
    return page


def check_geometry(page):
    result = toolbar_geometry_snapshot(page)
    assert [group["role"] for group in result["groups"]] == ["editing", "transport", "view", "display", "refine"]
    previous_center = -1
    rectangles = []
    for group in result["groups"]:
        x, y, width, height = group["rect"]
        center = y + height / 2
        assert center >= previous_center - 1
        previous_center = center
        centers = []
        for control in group["controls"]:
            cx, cy, cw, ch = control["rect"]
            assert control["visible"]
            assert cx >= 0 and cy >= 0
            assert cx + cw <= result["width"] and cy + ch <= result["height"]
            assert cw >= control["minimum"][0]
            centers.append(cy + ch / 2)
            rectangles.append((cx, cy, cw, ch))
        assert max(centers) - min(centers) <= 1
    for index, (x, y, w, h) in enumerate(rectangles):
        for a, b, c, d in rectangles[index + 1:]:
            assert x + w <= a or a + c <= x or y + h <= b or b + d <= y
    assert result["range_bar"]["rect"][1] >= result["height"]
    # The existing timecode QSS adds its padding/border to the 128px field.
    assert page.timecode_input.width() >= 128
    return result


def test_wide_group_spacing_alignment_and_unreduced_text(app):
    page = toolbar(app)
    result = check_geometry(page)
    # Centers differ by at most a pixel. The transport pill is taller than the
    # other groups (room around the play button, 2026-10-14), so tops differ.
    centers = [group["rect"][1] + group["rect"][3] / 2 for group in result["groups"]]
    assert max(centers) - min(centers) <= 1
    controls = result["groups"][3]["controls"]
    assert [control["text"] for control in controls] == ["波形", "缩略图", "跟随", "吸附"]
    assert all(control["font"]["pixels"] == 13 for control in controls)
    assert all(control["rect"][3] >= 34 for control in controls)
    for left, right in zip(controls, controls[1:]):
        assert right["rect"][0] - sum(left["rect"][::2]) >= 12
    first, second = result["groups"][:2]
    assert second["rect"][0] - first["rect"][0] - first["rect"][2] > 16
    page.close()


@pytest.mark.parametrize("width", [900, 1100, 1400])
def test_narrow_wraps_complete_groups_without_moving_range_into_commands(app, width):
    page = toolbar(app, width)
    result = check_geometry(page)
    if width == 900:
        assert result["height"] > 60
    range_controls = result["range_controls"]
    assert [item["text"] for item in range_controls[-2:]] == ["保存当前帧", "制作封面"]
    page.close()


def test_resize_roundtrip_is_deterministic(app):
    page = toolbar(app)
    before = check_geometry(page)
    page.resize(900, 300)
    app.processEvents()
    check_geometry(page)
    page.resize(2048, 300)
    app.processEvents()
    after = check_geometry(page)
    assert before == after
    page.close()


def test_secondary_surface_theme_and_theme_switch_cannot_redefine_toolbar(app, monkeypatch, tmp_path):
    from twobyteasr.design import theme_manager
    monkeypatch.setattr(theme_manager, "_settings", lambda: QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat))
    page = toolbar(app)
    theme_manager.apply_application_theme(app, "grape")
    app.processEvents()
    before = check_geometry(page)
    for name in ("applicationSettings", "toolDialog", "completionDetails"):
        dialog = QDialog(page)
        dialog.setObjectName(name)
        apply_secondary_surface_theme(dialog)
        dialog.show()
        app.processEvents()
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        assert check_geometry(page) == before
    for key in ("warm", "slate", "grape"):
        theme_manager.apply_application_theme(app, key)
        app.processEvents()
        result = check_geometry(page)
        assert [group["rect"] for group in result["groups"]] == [group["rect"] for group in before["groups"]]
        assert all(c["font"]["pixels"] == 13 for c in result["groups"][3]["controls"])
    page.close()
