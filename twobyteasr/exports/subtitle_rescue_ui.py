"""Small stand-alone rescue window. No application bootstrap or player."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout)

from .subtitle_rescue import BUILD_ID, RescueExportError, rescue_subtitles


class RescueWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str, str)

    def __init__(self, source, output, parent):
        super().__init__(parent)
        self.source, self.output = source, output

    def run(self):
        try:
            self.succeeded.emit(str(rescue_subtitles(self.source, self.output)))
        except Exception as exc:
            detail = str(exc)
            if callable(getattr(exc, "details", None)):
                detail += "\n\n" + exc.details()
            elif isinstance(exc, RescueExportError):
                cause = exc.cause
                if callable(getattr(cause, "details", None)):
                    detail += "\n\n" + cause.details()
            self.failed.emit(str(exc), detail)


class SubtitleRescueDialog(QDialog):
    def __init__(self, source=""):
        super().__init__()
        self.setWindowTitle("兔白字幕 · 字幕救援测试版")
        self.resize(800, 600)
        self.setMinimumSize(620, 480)
        # This window also opens from the full application's dark themes. Own
        # foreground and background together; a white surface must not inherit
        # near-white QLabel / placeholder colors from that application sheet.
        palette = self.palette()
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(role, QColor("#20242d"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#626c7c"))
        self.setPalette(palette)
        self.setStyleSheet(
            "QDialog {background:#f7f8fa;color:#20242d;}"
            "QLabel,QLineEdit,QPushButton,QTextEdit {font:14px 'Microsoft YaHei UI';color:#20242d;}"
            "QLabel {background:transparent;}"
            "QPushButton {background:#ffffff;border:1px solid #8c95a5;border-radius:6px;padding:8px 14px;}"
            "QPushButton:hover {background:#e8edf6;} QPushButton:disabled {color:#626c7c;background:#e8ebf0;}"
            "QLineEdit,QTextEdit {background:white;border:1px solid #8c95a5;border-radius:6px;"
            "selection-background-color:#2855a6;selection-color:white;} QLineEdit {padding:7px;}"
            "QLineEdit:focus,QTextEdit:focus {background:white;color:#20242d;border-color:#2855a6;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel("取回已保存的字幕")
        title.setStyleSheet("font-size:23px;font-weight:600;")
        layout.addWidget(title)
        note = QLabel("读取工程或自动保存副本，按目前时间轴导出全部说话人的 SRT。\n无需视频、播放器或重新识别；原工程与原有输出会保留。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.source = QLineEdit(source)
        self.source.setPlaceholderText("选择 .2byteproj、自动保存 JSON 或字幕导出 JSON")
        self.browse = QPushButton("选择文件…")
        self.browse.clicked.connect(self._choose_source)
        row = QHBoxLayout(); row.addWidget(self.source); row.addWidget(self.browse)
        form.addRow("字幕来源", row)
        self.output = QLineEdit(str(Path(source).parent) if source else "")
        self.output.setPlaceholderText("每次在此处新建一个救援文件夹")
        self.choose_output = QPushButton("选择位置…")
        self.choose_output.clicked.connect(self._choose_output)
        row = QHBoxLayout(); row.addWidget(self.output); row.addWidget(self.choose_output)
        form.addRow("保存位置", row)
        layout.addLayout(form)
        self.run_button = QPushButton("检查并导出字幕")
        self.run_button.setStyleSheet("background:#2855a6;color:white;font-weight:600;padding:12px;")
        self.run_button.clicked.connect(self.start_export)
        layout.addWidget(self.run_button)
        self.status = QLabel("支持已保存工程。尚未保存的编辑不会出现在这个文件中。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("这里会列出每个文件的条数、核对结果或具体失败位置。")
        layout.addWidget(self.details, 1)
        private = QLabel("详情与救援目录可能含字幕原文，仅保留在本机。是否提供给他人由你决定。")
        private.setWordWrap(True)
        layout.addWidget(private)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(BUILD_ID))
        footer.addStretch()
        copy_button = QPushButton("复制详情")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.details.toPlainText()))
        footer.addWidget(copy_button)
        self.open_button = QPushButton("打开救援目录")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.result_directory)))
        footer.addWidget(self.open_button)
        layout.addLayout(footer)
        self.worker = None
        self.result_directory = ""

    def _choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择已保存的字幕工程", "", "字幕工程和 JSON (*.2byteproj *.2byteasr *.json);;所有文件 (*)")
        if path:
            self.source.setText(path)
            if not self.output.text():
                self.output.setText(str(Path(path).parent))

    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存位置", self.output.text())
        if path:
            self.output.setText(path)

    def _busy(self, busy):
        for widget in (self.source, self.output, self.browse, self.choose_output, self.run_button):
            widget.setEnabled(not busy)

    def start_export(self):
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.source.text().strip() or not self.output.text().strip():
            self.status.setText("请选择字幕来源和保存位置。")
            return
        self._busy(True)
        self.open_button.setEnabled(False)
        self.status.setText("正在读取、写入候选并逐条核对…")
        self.details.clear()
        self.worker = RescueWorker(self.source.text(), self.output.text(), self)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def _success(self, directory):
        self.result_directory = directory
        manifest = json.loads((Path(directory) / "rescue-manifest.json").read_text(encoding="utf-8"))
        self.status.setText(f"已完整导出并核对当前时间轴 {manifest['timeline_cue_count']} 条字幕。")
        lines = [directory, "", *[f"{f['name']}：{f['cue_count']} 条，核对通过" for f in manifest["files"]],
                 "", *manifest["notes"], "", "原文件副本：input-copy.json", "逐条时间／文字收据：rescue-manifest.json"]
        self.details.setPlainText("\n".join(lines))
        self.open_button.setEnabled(True)

    def _failure(self, summary, details):
        self.status.setText("导出未完成；请查看下面的具体原因。")
        self.details.setPlainText(details)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("正在核对和写入，请完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)
