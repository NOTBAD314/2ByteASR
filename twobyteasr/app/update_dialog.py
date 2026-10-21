"""In-app update: the offer dialog and the check/download threads.

The logic (manifest, verification, staging) lives in ``app/updater.py``;
``MainWindow`` drives the flow.  Split out of ``app/ui.py`` on 2026-10-15;
``ui`` still exports these names.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from ..i18n import current_language, tr
from .updater import (
    automatic_check_due, check_for_update, format_bytes, prepare_update, UpdateCancelled,
)


class UpdateCheckWorker(QThread):
    """Fetch and verify the signed update manifest off the GUI thread."""

    result_ready = Signal(object)
    failed = Signal(str)
    skipped = Signal()

    def __init__(self, parent=None, *, automatic: bool = False):
        super().__init__(parent)
        self.automatic = automatic

    def run(self):
        try:
            if self.automatic and not automatic_check_due():
                self.skipped.emit()
                return
            self.result_ready.emit(check_for_update(use_cache=not self.automatic))
        except Exception as exc:  # noqa: BLE001 - UI must report network failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateDownloadWorker(QThread):
    """Download, verify and stage only the components this update changes."""

    progress_changed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, check, parent=None):
        super().__init__(parent)
        self.check = check
        self.cancel_event = threading.Event()

    def run(self):
        try:
            prepared = prepare_update(
                self.check,
                progress=lambda _name, done, total: self.progress_changed.emit(int(done), int(total)),
                cancel=self.cancel_event,
            )
            self.completed.emit(prepared)
        except UpdateCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - UI must report mirror/checksum failures
            self.failed.emit(" ".join(str(exc).split()) or exc.__class__.__name__)


class UpdateOfferDialog(QDialog):
    """Current/new version, release notes and the real download size."""

    def __init__(self, check, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(tr('发现新版本'))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        manifest, plan = check.manifest, check.plan
        heading = QLabel(tr('兔白字幕 {value0}（当前 {value1}）', value0=check.latest_version,
                            value1=check.current_version))
        heading.setObjectName('sectionTitle')
        layout.addWidget(heading)
        notes = manifest.note_for(current_language()) if manifest else ''
        if notes:
            layout.addWidget(QLabel(tr('主要变更')))
            box = QPlainTextEdit(notes)
            box.setReadOnly(True)
            box.setMaximumHeight(170)
            layout.addWidget(box)
        lines = []
        if plan is not None and plan.mode == 'components':
            lines.append(tr('本次需要下载：{value0}', value0=format_bytes(plan.download_bytes)))
            for action in plan.downloads:
                cached = '' if action.download_bytes else tr('（已下载过，直接使用）')
                lines.append('  · ' + tr('{value0}：{value1}', value0=tr(action.label),
                                         value1=format_bytes(action.archive_bytes)) + cached)
            if plan.reused:
                lines.append(tr('沿用、不下载：{value0}', value0='、'.join(tr(a.label) for a in plan.reused)))
        elif plan is not None:
            lines.append(tr('需要用完整安装包更新（{value0}）。', value0=format_bytes(plan.setup_bytes)))
            if plan.fallback_reason:
                lines.append(tr('原因：{value0}', value0=plan.fallback_reason))
            lines.append(tr('安装包会保留设置、词库、工程、模型和运行环境，覆盖安装即可，不要先卸载。'))
        if plan is not None:
            if plan.environment_changes:
                lines.append(tr('运行环境：{value0} 的需求有变化，用到时程序会提示补齐。',
                                value0='、'.join(plan.environment_changes)))
            else:
                lines.append(tr('运行环境：沿用，不需要重新下载。'))
            if plan.model_changes:
                lines.append(tr('模型：{value0} 有新版本，只有用到该模型时才需要下载。',
                                value0='、'.join(plan.model_changes)))
            else:
                lines.append(tr('模型：沿用，不需要重新下载。'))
        detail = QLabel('\n'.join(lines))
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail)
        buttons = QHBoxLayout()
        page = QPushButton(tr('打开发布页'))
        page.clicked.connect(lambda: self._finish('page'))
        later = QPushButton(tr('稍后'))
        later.clicked.connect(self.reject)
        if plan is not None and plan.mode == 'components':
            primary = QPushButton(tr('下载并准备更新'))
            primary.clicked.connect(lambda: self._finish('download'))
        else:
            primary = QPushButton(tr('下载安装包'))
            primary.clicked.connect(lambda: self._finish('setup'))
        primary.setObjectName('primary')
        primary.setDefault(True)
        buttons.addWidget(page)
        buttons.addStretch(1)
        buttons.addWidget(later)
        buttons.addWidget(primary)
        layout.addLayout(buttons)

    def _finish(self, choice):
        self.choice = choice
        self.accept()
