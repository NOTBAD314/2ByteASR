"""Preserve an unsafe project and offer the existing read-only rescue dialog."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..design.studio_theme import apply_secondary_surface_theme
from ..i18n import tr


def show_load_failure(page, path, error) -> None:
    box = QMessageBox(page)
    box.setObjectName("subtitleConsistencyFailure")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("字幕工程需要检查"))
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(tr("工程中的字幕时间或来源引用存在冲突，尚未进入工作台。原文件与已保存的人工文字保留。"))
    result = getattr(error, "result", None)
    box.setInformativeText(str(error))
    if result is not None:
        box.setDetailedText(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    rescue = box.addButton(tr("字幕救援…"), QMessageBox.ButtonRole.ActionRole)
    rescue.setObjectName("subtitleConsistencyRescue")
    close = box.addButton(QMessageBox.StandardButton.Close)
    box.setDefaultButton(close)
    apply_secondary_surface_theme(box)
    box.exec()
    if box.clickedButton() is rescue:
        from ..exports.subtitle_rescue_ui import SubtitleRescueDialog
        # Retained by the owning page; the rescue worker keeps its own lifetime.
        dialog = SubtitleRescueDialog(str(Path(path)))
        page._subtitle_rescue_dialog = dialog
        dialog.show()


def show_alignment_warning(page, result) -> None:
    if not result.warnings:
        return
    count = len({issue.cue_id for issue in result.warnings})
    page.save_state.setText(tr("部分字级时间待更新"))
    page.save_state.setToolTip(
        tr("已保留当前文字与句级时间；可继续编辑或导出句级字幕。")
        + f"\n{count} " + tr("条字幕的旧字级记录需要检查。"))

