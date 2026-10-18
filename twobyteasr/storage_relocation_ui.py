"""「移到其他位置…」: move models and runtimes from the storage settings (2026-10-17).

The work runs on a thread (``storage_relocation``); this dialog shows the plan,
asks once, reports progress and lets the user cancel until the new location
is registered. Closing the window while it runs is treated as cancel.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .i18n import bind_text, tr
from . import storage_relocation as relocation


class _Worker(QObject):
    progress = Signal(str, object, object)
    planned = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__(QApplication.instance())
        self.cancel = threading.Event()
        self.thread = None

    def start(self, fn):
        def run():
            try:
                fn()
            except Exception as exc:  # shown in the dialog; nothing else may swallow it
                try:
                    self.failed.emit(str(exc))
                except RuntimeError:
                    pass
        self.thread = threading.Thread(target=run, name='storage-relocation', daemon=True)
        self.thread.start()

    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())


def _label(kind: str) -> str:
    return tr('运行环境') if kind == relocation.RUNTIMES else tr('模型')


def plan_text(plan) -> str:
    lines = []
    for part in plan.parts:
        if part.empty:
            lines.append(tr('{kind}：还没有下载，以后下载到 {target}', kind=_label(part.kind), target=str(part.target)))
            continue
        how = tr('同一磁盘，直接改名') if part.same_volume else tr('复制后删除旧位置')
        lines.append(tr('{kind}：{old} → {new}', kind=_label(part.kind), old=str(part.source), new=str(part.target)))
        lines.append('    ' + tr('实际占用 {size}，{files} 个文件；{how}', size=relocation.format_size(part.unique_bytes),
                                    files=str(part.files), how=how))
    if plan.required_bytes:
        free = relocation.format_size(plan.free_bytes) if plan.free_bytes is not None else tr('未知')
        lines.append(tr('目标磁盘剩余 {free}，需要 {need}（含 1 GB 余量）', free=free,
                        need=relocation.format_size(plan.required_bytes)))
    lines.extend(plan.notes)
    return '\n'.join(lines)


class RelocationDialog(QDialog):
    """Plan → confirm → move with progress → result."""

    moved = Signal(object)

    def __init__(self, destination, parent=None, *, busy=None):
        super().__init__(parent)
        self.setObjectName('storageRelocationDialog')
        self.setWindowTitle(tr('移到其他位置'))
        self.resize(720, 460)
        self.destination = Path(destination)
        self.busy = busy
        self.plan = None
        self.result = None
        self._worker = None
        self._started = False
        outer = QVBoxLayout(self)
        # Long paths and result lists wrap; a scroll area keeps them from
        # overlapping in a window that cannot grow (seen at 175 % scaling).
        scroll = QScrollArea()
        scroll.setObjectName('storageRelocationScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName('storageRelocationBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        intro = bind_text(QLabel(), '把运行环境和模型移到你选的文件夹（例如另一块磁盘），分别放进其中的 runtimes 和 models。新位置检查能正常启动后，才删除旧位置的文件；出错会还原。')
        intro.setWordWrap(True)
        intro.setObjectName('settingsDescription')
        layout.addWidget(intro)
        self.summary = QLabel(tr('正在统计要移动的文件…'))
        self.summary.setObjectName('storageRelocationSummary')
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setProperty('i18nUserText', True)
        layout.addWidget(self.summary)
        self.problems = QLabel()
        self.problems.setObjectName('storageRelocationProblems')
        self.problems.setWordWrap(True)
        self.problems.setProperty('i18nUserText', True)
        self.problems.hide()
        layout.addWidget(self.problems)
        self.status = QLabel()
        self.status.setObjectName('storageRelocationStatus')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setProperty('i18nUserText', True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        outer.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.start_button = bind_text(QPushButton(), '开始移动')
        self.start_button.setObjectName('storageRelocationStart')
        self.start_button.setEnabled(False)
        self.cancel_button = bind_text(QPushButton(), '取消')
        self.cancel_button.setObjectName('storageRelocationCancel')
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        outer.addLayout(buttons)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self._cancel_or_close)
        self._plan()

    # -- planning
    def _busy_now(self):
        """Read the app's state on the GUI thread; the modal dialog keeps it from changing."""
        state = bool(self.busy()) if self.busy is not None else False
        return lambda: state

    def _plan(self):
        worker = self._new_worker()
        worker.planned.connect(self._planned)
        destination, busy, cancel = self.destination, self._busy_now(), worker.cancel.is_set
        worker.start(lambda: worker.planned.emit(relocation.plan_relocation(destination, busy=busy, cancel=cancel)))

    def _planned(self, plan):
        self.plan = plan
        self.bar.hide()
        self.summary.setText(plan_text(plan) or tr('没有需要移动的内容。'))
        if plan.problems:
            self.problems.setText(tr('现在不能移动：') + '\n' + '\n'.join('• ' + item for item in plan.problems))
            self.problems.show()
        self.start_button.setEnabled(plan.ok)

    # -- moving
    def start(self):
        if not self.plan or not self.plan.ok or self._started:
            return
        self._started = True
        self.start_button.setEnabled(False)
        self.problems.hide()
        total = sum(part.unique_bytes for part in self.plan.parts if not part.same_volume)
        self.bar.setRange(0, 1000 if total else 0)
        self.bar.setValue(0)
        self.bar.show()
        worker = self._new_worker()
        worker.progress.connect(self._progress)
        worker.finished.connect(self._finished)
        plan, busy, cancel = self.plan, self._busy_now(), worker.cancel.is_set
        worker.start(lambda: worker.finished.emit(relocation.execute_relocation(
            plan, cancel=cancel, busy=busy, progress=lambda text, done, all_: worker.progress.emit(text, done, all_))))

    def _progress(self, text, done, total):
        self.status.setText(text)
        if total:
            self.bar.setValue(int(1000 * min(1.0, done / total)))
        # A registered part is final (its old copy is removed next); the next
        # part can be cancelled again.
        if text.startswith(relocation.COMMITTED_PHASES):
            self.cancel_button.setEnabled(False)
        elif text.startswith(relocation.MOVING_PHASES) and not self._worker.cancel.is_set():
            self.cancel_button.setEnabled(True)

    def _finished(self, result):
        self.result = result
        self.bar.hide()
        self.cancel_button.setEnabled(True)
        bind_text(self.cancel_button, '关闭')
        heading = {
            'moved': tr('移动完成。'),
            'partial': tr('只完成了一部分：'),
            'cancelled': tr('已取消，原位置的文件没有变化。'),
            'failed': tr('移动没有完成，原位置的文件没有变化。'),
        }.get(result.status, '')
        lines = [heading, *result.messages]
        if result.moved:
            from .runtime_paths import get_runtime_paths
            paths = get_runtime_paths(refresh=True)
            lines.append(tr('运行环境：{path}', path=str(paths.managed_runtime_root)))
            lines.append(tr('模型：{path}', path=str(paths.model_root)))
        self.status.setText('\n'.join(line for line in lines if line))
        if result.moved:
            self.moved.emit(result)

    def _failed(self, message):
        self.bar.hide()
        self.cancel_button.setEnabled(True)
        bind_text(self.cancel_button, '关闭')
        self.status.setText(tr('操作未完成：') + message)

    def _new_worker(self):
        worker = _Worker()
        worker.failed.connect(self._failed)
        self._worker = worker
        return worker

    def _cancel_or_close(self):
        if self._worker is not None and self._worker.running():
            self._worker.cancel.set()
            self.status.setText(tr('正在取消并还原…'))
            self.cancel_button.setEnabled(False)
            return
        self.accept() if self.result is not None and self.result.moved else self.reject()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.running():
            # Never leave a move running behind a closed window.
            if self.cancel_button.isEnabled():
                self._cancel_or_close()
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self._worker is not None and self._worker.running():
            self._cancel_or_close()
            return
        super().reject()


def choose_and_move(parent, *, busy=None, on_moved=None):
    """Ask for a folder, then run the dialog. Returns the dialog result (or None)."""
    from PySide6.QtWidgets import QFileDialog
    if busy is not None and busy():
        QMessageBox.information(parent, tr('移到其他位置'), tr('请等识别、模型下载、安装、修复或导出结束后再移动。'))
        return None
    chosen = QFileDialog.getExistingDirectory(parent, tr('选择新位置（例如 D:\\兔白字幕数据）'), str(Path.home()))
    if not chosen:
        return None
    dialog = RelocationDialog(chosen, parent, busy=busy)
    if on_moved is not None:
        dialog.moved.connect(on_moved)
    dialog.exec()
    return dialog.result
