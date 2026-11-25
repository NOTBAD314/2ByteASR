"""Preview independently of Studio and without materializing a widget per cue."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QTableView, QVBoxLayout)

from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme
from ..i18n import tr
from ..media.link_manifest import load_manifest, read_normalized, resolve_relative
from ..media.link_reconstruction import reconstruct
from ..media.link_subtitles import parse_subtitles, srt_bytes
from .link_download_widgets import button


def prepare(directory, manifest_name):
    manifest_path = Path(directory) / manifest_name
    contents = load_manifest(manifest_path)
    outputs = {}
    for sub in contents["subtitles"]:
        track = sub["track"]
        raw_path = resolve_relative(manifest_path.parent, sub["original"]["path"])
        raw = raw_path.read_bytes()
        source = track.get("source", "unknown")
        language = track.get("language", "")
        original = parse_subtitles(raw, expected_format=sub["actual_format"], source=source)
        prepared = reconstruct(original, language=language, source=source,
                               keep_sound=sub.get("keep_sound", True))
        original = reconstruct(original, language=language, source=source, mode="original")
        ai = sub.get("ai")
        refined = read_normalized(resolve_relative(manifest_path.parent, sub["normalized"]["path"])) if ai and ai["applied"] else None
        outputs[track["track_id"]] = (track, raw_path, original, prepared, refined, ai)
    return outputs


class CaptionTable(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(("开始", "结束", "字幕")[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole) or not index.isValid():
            return None
        row = self.rows[index.row()]
        value = (row.start_ms, row.end_ms, row.text)[index.column()]
        if isinstance(value, int):
            sec, ms = divmod(value, 1000)
            return f"{sec // 3600:02}:{sec // 60 % 60:02}:{sec % 60:02}.{ms:03}"
        return value


def show_preview(parent, outputs):
    if not outputs:
        return
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle(tr("字幕预览"))
    layout = QVBoxLayout(dialog)
    selector = QHBoxLayout()
    track = StudioComboBox()
    for identity, (row, *_rest) in outputs.items():
        track.addItem(f"{row.get('language', '')} · {row.get('label', '')}", identity)
    mode = StudioComboBox()
    mode.addItem(tr("原始字幕"), "original")
    mode.addItem(tr("智能整句重建"), "smart")
    if any(row[-1] for row in outputs.values()):
        mode.addItem(tr("AI 精细断句"), "ai")
    mode.setCurrentIndex(1)
    selector.addWidget(track, 1)
    selector.addWidget(mode, 1)
    layout.addLayout(selector)
    summary = QLabel()
    summary.setWordWrap(True)
    layout.addWidget(summary)
    table = QTableView()
    model = CaptionTable(table)
    table.setModel(model)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    layout.addWidget(table, 1)

    def current():
        row, path, original, smart, refined, _ = outputs[track.currentData()]
        parsed = original if mode.currentData() == "original" else (refined or smart) if mode.currentData() == "ai" else smart
        return row, path, parsed

    def refresh():
        row, _, parsed = current()
        model.replace(parsed.captions)
        count = sum(a.get("precision", "").startswith("segment") for c in parsed.captions for a in c.anchors)
        message = tr("{count} 条 · {format} · {language} · {anchors} 个来源时间锚点",
                           count=len(parsed.captions), format=parsed.format.upper(),
                           language=row.get("language", "—"), anchors=count)
        if mode.currentData() == "ai":
            status = outputs[track.currentData()][-1] or {}
            if status.get("status") == "completed":
                message += " · " + tr("AI 已调整 {count} 个范围", count=status["applied"])
            else:
                message += " · " + tr("AI 未完成，未通过的范围保留智能重建")
        summary.setText(message)

    def save(raw):
        row, path, parsed = current()
        selected, _ = QFileDialog.getSaveFileName(dialog, tr("保存原始字幕" if raw else "保存此版本的 SRT"),
            str(path.with_suffix(path.suffix if raw else ".srt")), "" if raw else "SubRip (*.srt)")
        if not selected:
            return
        try:
            destination = Path(selected)
            if destination.resolve() == path.resolve():
                raise OSError(tr("请选择其他位置，原始字幕受保护。"))
            destination.write_bytes(path.read_bytes() if raw else srt_bytes(parsed))
        except OSError as exc:
            summary.setText(tr("保存失败") + " · " + str(exc))
        else:
            summary.setText(tr("已保存"))

    export = QHBoxLayout()
    raw_button = button(tr("保存原始字幕"))
    raw_button.clicked.connect(lambda: save(True))
    srt = button(tr("保存此版本的 SRT"))
    srt.clicked.connect(lambda: save(False))
    export.addStretch()
    export.addWidget(raw_button)
    export.addWidget(srt)
    layout.addLayout(export)
    track.currentIndexChanged.connect(refresh)
    mode.currentIndexChanged.connect(refresh)
    refresh()
    apply_secondary_surface_theme(dialog)
    dialog.resize(760, 450)
    dialog.show()
