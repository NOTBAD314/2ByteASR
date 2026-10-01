"""Capture deterministic Studio secondary-surface acceptance screenshots."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", str(ROOT / "tmp" / "p21-secondary-local-data"))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import twobyteasr.studio_render_ui as render_ui  # noqa: E402
from twobyteasr.studio_project import StudioMedia, SubtitleProject  # noqa: E402
from twobyteasr.studio_theme import StudioComboBox, create_studio_menu  # noqa: E402
from twobyteasr.studio_ui import ShortcutSettingsDialog  # noqa: E402


def _save(widget, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(target), "PNG"):
        raise RuntimeError(f"Could not save {target}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    windows_cjk = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if windows_cjk.is_file():
        QFontDatabase.addApplicationFont(str(windows_cjk))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    output = ROOT / "screenshots" / "p21-secondary-surfaces"

    shortcuts = ShortcutSettingsDialog({}, None)
    shortcuts.resize(620, 620)
    shortcuts.show()
    app.processEvents()
    _save(shortcuts, output / "shortcut-dialog-100.png")

    render_ui.encoder_choices = lambda *_args: ["h264_nvenc", "libx264"]
    project = SubtitleProject(
        media=StudioMedia(path=str(ROOT / "tmp" / "source-video.mp4"), duration_ms=600_000)
    )
    render = render_ui.StudioRenderDialog(project, str(ROOT / "tmp" / "preview.ass"), 32.0)
    render.resize(620, 760)
    render.show()
    app.processEvents()
    _save(render, output / "render-dialog-125.png")

    combo = StudioComboBox()
    combo.resize(280, 38)
    combo.addItems(("H.264 - NVIDIA NVENC", "HEVC / H.265 - Software x265", "AV1 - 当前设备不可用"))
    combo.model().item(2).setEnabled(False)
    combo.show()
    combo.showPopup()
    combo.setCurrentIndex(1)
    app.processEvents()
    _save(combo.view().window(), output / "combo-popup-selected-disabled.png")

    menu = create_studio_menu()
    first = menu.addAction("当前字幕编辑器")
    first.setCheckable(True)
    first.setChecked(True)
    menu.addSeparator()
    menu.addAction("字幕列表")
    disabled = menu.addAction("证据检查器（项目无证据）")
    disabled.setEnabled(False)
    menu.popup(QPoint(100, 100))
    app.processEvents()
    _save(menu, output / "context-menu-checked-disabled.png")

    menu.close()
    combo.hidePopup()
    combo.close()
    render.close()
    shortcuts.close()
    app.processEvents()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
