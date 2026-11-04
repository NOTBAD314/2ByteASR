"""Project-owned model storage inventory and management UI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import qtawesome as qta
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .model_registry import ModelHealth, scan_model_registry
from ..runtime_paths import get_runtime_paths
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition

from ..i18n import bind_text

from ..i18n import tr


def format_bytes(value: int) -> str:
    size = float(max(0, int(value)))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return "0 B"


def directory_size(path: Path, *, max_files: int | None = None) -> int:
    if not path.is_dir():
        return 0
    total = 0
    from .model_removal import _link
    def failure(exc): raise exc
    for directory, dirs, files in os.walk(path, followlinks=False, onerror=failure):
        base = Path(directory)
        dirs[:] = [name for name in dirs if not _link(base / name)]
        for name in files:
            item = base / name
            if not _link(item): total += item.stat().st_size
    return total


def _environment_bytes(path: Path) -> int:
    """Exact size for tiny fixtures; skip walking a real Python environment."""

    try:
        children = list(path.iterdir())
    except OSError:
        return 0
    if any(
        child.is_dir() and child.name.lower() in {"lib", "scripts", "include", "bin"}
        for child in children
    ):
        return 0
    return directory_size(path)


def _owned_child(root: Path, candidate: Path, owner: str) -> bool:
    resolved_root = root.resolve()
    resolved_owner = (resolved_root / owner).resolve()
    resolved = candidate.resolve()
    return resolved_owner in resolved.parents and resolved != resolved_owner


@dataclass(frozen=True)
class StorageEntry:
    model_key: str
    key: str
    name: str
    role: str
    languages: tuple[str, ...]
    path: Path
    installed: bool
    expected_bytes: int
    actual_bytes: int
    environment_name: str
    environment_path: Path | None
    environment_bytes: int
    current: bool
    revision: str
    measurement_error: str = ''


class _StorageScanThread(QThread):
    completed = Signal(object)

    def __init__(self, root: Path, models: tuple[object, ...], current: set[str], parent=None):
        super().__init__(parent)
        self.root = root
        self.models = models
        self.current = current

    def run(self):
        # MFA's conda env (2026-10-19) is walked once: its own row and the MFA model row's runtime column.
        from .model_runtime_cleanup import plan_mfa_runtime_removal
        runtime = plan_mfa_runtime_removal()
        self.completed.emit((scan_storage(self.root, self.models, self.current, mfa_runtime=runtime), runtime))


class _HistoryCleanupThread(QThread):
    completed = Signal(object)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try: self.completed.emit((self.action(), ''))
        except Exception as exc: self.completed.emit((None, str(exc)))


_UNSCANNED = object()


def scan_storage(root: Path, models: Iterable[object], current_keys: set[str], *,
                 mfa_runtime: object = _UNSCANNED) -> list[StorageEntry]:
    """``mfa_runtime``: an already made ``plan_mfa_runtime_removal()`` (None: not on disk)."""
    from ..recognition import mfa_aligner
    root = Path(root).resolve()
    registry = scan_model_registry(install_root=root, measure_size=False)
    entries: list[StorageEntry] = []
    environment_sizes: dict[Path, int] = {}
    mfa_keys = set(mfa_aligner.LANGUAGE_MODELS.values())
    models = tuple(models)
    if mfa_runtime is _UNSCANNED and any(getattr(model, "download_key", "") in mfa_keys for model in models):
        from .model_runtime_cleanup import plan_mfa_runtime_removal
        mfa_runtime = plan_mfa_runtime_removal()
    for model in models:
        download_key = str(getattr(model, "download_key", "") or "")
        if not download_key:
            continue
        record = registry.record(download_key)
        env_name = ""
        path = root / "models" / "__invalid__"
        expected_bytes = 0
        actual_bytes = 0
        revision = ""
        installed = False
        measurement_error = ''
        if record is not None:
            path = record.installation_path
            expected_bytes = record.expected_bytes
            actual_bytes = record.size_bytes
            revision = record.version
            installed = record.health is ModelHealth.INSTALLED
            env_name = record.runtime_environment
        if not env_name:
            env_name = ".venv-moss" if download_key == "moss" else ".venv-main"
        env_path = (root / env_name).resolve() if env_name else None
        env_bytes = 0
        if download_key in mfa_keys:
            # Its own conda env under the runtime root, not a venv next to the program.
            env_name = mfa_aligner.RUNTIME_DIR_NAME
            env_path = getattr(mfa_runtime, "root", None) or mfa_aligner.runtime_prefix()
            env_bytes = getattr(mfa_runtime, "logical_bytes", 0) if getattr(mfa_runtime, "ready", False) else 0
        elif env_path and env_path.is_dir():
            if env_path not in environment_sizes:
                environment_sizes[env_path] = _environment_bytes(env_path)
            env_bytes = environment_sizes[env_path]
        if record and record.health is ModelHealth.UNREADABLE:
            measurement_error = '目录不可访问，统计未完成'
        elif path.is_dir():
            try: actual_bytes = directory_size(path)
            except OSError as exc: measurement_error = str(exc)
        entries.append(StorageEntry(
            model_key=str(getattr(model, "key", download_key)),
            key=download_key,
            name=str(getattr(model, "name", download_key)),
            role=str(getattr(model, "role", "")),
            languages=tuple(getattr(model, "languages", ()) or ()),
            path=path,
            installed=installed,
            expected_bytes=expected_bytes,
            actual_bytes=actual_bytes,
            environment_name=env_name,
            environment_path=env_path,
            environment_bytes=env_bytes,
            current=str(getattr(model, "key", "")) in current_keys,
            revision=revision,
            measurement_error=measurement_error,
        ))
    return entries


def verify_model_files(root: Path, key: str) -> tuple[bool, str]:
    try:
        lock = json.loads((Path(root) / "dependencies.lock.json").read_text(encoding="utf-8"))
        spec = lock["models"][key]
    except (OSError, ValueError, TypeError, KeyError):
        return False, "依赖清单中没有这个模型。"
    registry = scan_model_registry(install_root=Path(root))
    record = registry.record(str(key))
    path = record.installation_path if record is not None else (Path(root) / str(spec.get("path") or "")).resolve()
    missing = [name for name in spec.get("required_files") or () if not (path / name).is_file()]
    if missing:
        return False, "缺少关键文件：\n" + "\n".join(missing[:8])
    for relative, expected in (spec.get("sha256") or {}).items():
        file_path = path / relative
        if not file_path.is_file():
            return False, f"缺少校验文件：{relative}"
        digest = hashlib.sha256()
        try:
            with file_path.open("rb") as stream:
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            return False, f"读取失败：{exc}"
        if digest.hexdigest().lower() != str(expected).lower():
            return False, f"SHA-256 不匹配：{relative}"
    return True, "关键文件与已有 SHA-256 校验均通过。"


def residual_files(root: Path) -> list[Path]:
    """Explicit downloader receipts only; checkout tmp is development data."""
    from .model_download_cache import scan_download_transactions
    return [path for transaction in scan_download_transactions(get_runtime_paths().model_root / '.downloads')
            for path in transaction.paths]


class ModelStorageDialog(QDialog):
    def __init__(
        self,
        root: Path,
        models: Iterable[object],
        current_keys: Callable[[], set[str]],
        download: Callable[[str, str], object],
        uninstall: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self.root = root.resolve()
        self.models = tuple(models)
        self.current_keys = current_keys
        self.download_callback = download
        self.uninstall_callback = uninstall
        self.filter_mode = "all"
        self._entries: list[StorageEntry] = []
        self._mfa_runtime = None  # model_runtime_cleanup.MfaRuntimePlan of the last scan
        self._scanner: _StorageScanThread | None = None
        self._history_worker: _HistoryCleanupThread | None = None
        self._close_after_scan = False
        self.setObjectName("modelStorageDialog")
        bind_text(self, '模型存储管理', property='windowTitle')
        self.setModal(True)
        self.resize(1040, 740)
        self.setMinimumSize(840, 600)
        self._build()
        self.refresh()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 22)
        outer.setSpacing(14)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("模型存储管理")
        title.setObjectName("storageTitle")
        subtitle = QLabel("模型文件与 Python Runtime 分开统计。源码运行和正式 EXE 共用同一模型目录。")
        subtitle.setObjectName("storageMuted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.residual_button = QPushButton("扫描残留文件")
        self.residual_button.setObjectName("storageOutline")
        self.residual_button.clicked.connect(self._show_residuals)
        header.addWidget(self.residual_button)
        self.history_cleanup_button = QPushButton('永久清理历史模型残留')
        self.history_cleanup_button.setObjectName('storageDanger')
        self.history_cleanup_button.clicked.connect(self._scan_history_cleanup)
        header.addWidget(self.history_cleanup_button)
        outer.addLayout(header)

        path_row = QHBoxLayout()
        path_label = QLabel("模型存储位置")
        path_label.setObjectName("storageFactLabel")
        self.model_root_edit = QLineEdit(str(get_runtime_paths().model_root))
        self.model_root_edit.setObjectName("storagePathEdit")
        self.model_root_edit.setReadOnly(True)
        change_path = QPushButton("更改")
        change_path.setObjectName("storageOutline")
        change_path.clicked.connect(self._change_model_root)
        scan_existing = QPushButton("扫描已有模型")
        scan_existing.setObjectName("storageOutline")
        scan_existing.clicked.connect(self._scan_existing_models)
        path_row.addWidget(path_label)
        path_row.addWidget(self.model_root_edit, 1)
        path_row.addWidget(change_path)
        path_row.addWidget(scan_existing)
        outer.addLayout(path_row)
        runtime_row = QHBoxLayout()
        runtime_note = QLabel('运行环境只清理已有健康替代、无进程引用且有完整归属登记的旧版本；当前共享环境保留。')
        runtime_note.setObjectName('storageMuted'); runtime_note.setWordWrap(True)
        runtime_row.addWidget(runtime_note, 1)
        self.runtime_cleanup_button = QPushButton('清理不再使用的模型运行环境')
        self.runtime_cleanup_button.setObjectName('storageOutline')
        self.runtime_cleanup_button.clicked.connect(self._scan_unused_runtimes)
        runtime_row.addWidget(self.runtime_cleanup_button)
        outer.addLayout(runtime_row)

        summary = QFrame()
        summary.setObjectName("storageSummary")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setHorizontalSpacing(24)
        self.summary_labels = []
        for column, name in enumerate(("已安装模型", "模型总占用", "可安装模型", "磁盘剩余")):
            label = QLabel(name)
            label.setObjectName("storageFactLabel")
            value = QLabel("—")
            value.setObjectName("storageFactValue")
            summary_layout.addWidget(label, 0, column)
            summary_layout.addWidget(value, 1, column)
            self.summary_labels.append(value)
        outer.addWidget(summary)

        filters = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for text, mode in (("全部", "all"), ("已安装", "installed"), ("未安装", "missing")):
            button = QPushButton(text)
            button.setObjectName("storageFilter")
            button.setCheckable(True)
            button.setChecked(mode == "all")
            button.clicked.connect(lambda _checked=False, value=mode: self._set_filter(value))
            self.filter_group.addButton(button)
            filters.addWidget(button)
        filters.addStretch(1)
        outer.addLayout(filters)

        scroll = QScrollArea()
        scroll.setObjectName("storageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.rows = QVBoxLayout(host)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self.setStyleSheet(build_storage_qss())

    def _change_model_root(self) -> None:
        current = str(get_runtime_paths().model_root)
        chosen = QFileDialog.getExistingDirectory(self, tr('选择模型存储位置'), current)
        if not chosen:
            return
        # Same validated save as 应用设置 (2026-10-15): the folder is created and
        # tested for writing now, and is not switched while a download runs,
        # instead of failing later inside the download script.
        from .model_root_settings import save_model_download_root
        owner = self.parentWidget().window() if self.parentWidget() else None
        try:
            save_model_download_root(chosen, owner=owner)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('无法使用这个位置'), str(exc))
            return
        # Re-selecting a location is the explicit restore operation for models
        # previously detached from this exact external directory.
        from .model_associations import restore_model_association
        from ..runtime_paths import model_folder_name
        lock = json.loads((self.root / 'dependencies.lock.json').read_text('utf-8-sig'))
        for spec in lock.get('models', {}).values():
            restore_model_association(Path(chosen) / model_folder_name(str(spec.get('path', ''))))
        self.model_root_edit.setText(str(get_runtime_paths().model_root))
        self.refresh()

    def _scan_existing_models(self) -> None:
        from ..runtime_paths import build_runtime_paths, persist_runtime_paths, reset_runtime_paths

        reset_runtime_paths()
        paths = build_runtime_paths(install_root=self.root, persist=True)
        persist_runtime_paths(paths)
        self.model_root_edit.setText(str(paths.model_root))
        self.refresh()

    def _set_filter(self, mode: str):
        self.filter_mode = mode
        self._render_entries()

    def refresh(self):
        if self._scanner is not None and self._scanner.isRunning():
            return
        self._clear_rows()
        loading = QLabel("正在扫描模型文件与运行环境…")
        loading.setObjectName("storageMuted")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rows.insertWidget(0, loading)
        for label in self.summary_labels:
            bind_text(label, '扫描中')
        self._scanner = _StorageScanThread(
            self.root, self.models, self.current_keys(), self
        )
        self._scanner.completed.connect(self._scan_completed)
        self._scanner.start()

    def _clear_rows(self):
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scan_completed(self, entries: object):
        entries, self._mfa_runtime = entries if isinstance(entries, tuple) else (entries, None)
        self._entries = list(entries) if isinstance(entries, list) else []
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            scanner.deleteLater()
        self._render_entries()
        if self._close_after_scan:
            QDialog.reject(self)

    def reject(self):
        if ((self._scanner is not None and self._scanner.isRunning()) or
                (self._history_worker is not None and self._history_worker.isRunning())):
            self._close_after_scan = True
            self.hide()
            return
        super().reject()

    def _history_action(self, action, callback):
        self.history_cleanup_button.setEnabled(False)
        self.residual_button.setEnabled(False)
        self.runtime_cleanup_button.setEnabled(False)
        worker = _HistoryCleanupThread(action, self)
        self._history_worker = worker
        def completed(payload):
            self._history_worker = None
            self.history_cleanup_button.setEnabled(True)
            self.residual_button.setEnabled(True)
            self.runtime_cleanup_button.setEnabled(True)
            callback(payload)
            if self._close_after_scan: QDialog.reject(self)
        worker.completed.connect(completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _scan_history_cleanup(self):
        if self._storage_busy():
            QMessageBox.information(self, tr('任务正在运行'), tr('请等待模型推理、下载、安装或修复结束。')); return
        main = self.parentWidget()
        while main is not None and not hasattr(main, '_run_in_progress'):
            main = main.parentWidget()
        if main and (main._run_in_progress or
                     (getattr(main, 'worker', None) is not None and main.worker.isRunning())):
            QMessageBox.information(self, tr('任务正在运行'), tr('请先等待任务结束或正常取消任务，再永久清理历史模型。'))
            return
        if self._history_worker is not None: return
        from .model_removal import historical_model_removals
        self._history_action(lambda: historical_model_removals(self.root), self._confirm_history_cleanup)

    def _storage_busy(self):
        node = self.parentWidget()
        while node is not None:
            if getattr(node, '_run_in_progress', False): return True
            worker = getattr(node, 'worker', None)
            if worker is not None and worker.isRunning(): return True
            for dialog in getattr(node, '_download_dialogs', ()):
                if dialog.process.state().value != 0: return True
            node = node.parentWidget()
        return False

    def _scan_unused_runtimes(self):
        if self._history_worker is not None: return
        if self._storage_busy():
            QMessageBox.information(self, tr('任务正在运行'), tr('请等待模型推理、下载、安装或修复结束。')); return
        from .model_runtime_cleanup import scan_unused_model_runtimes
        self._history_action(scan_unused_model_runtimes, self._confirm_unused_runtimes)

    def _confirm_unused_runtimes(self, payload):
        plans, error = payload
        if error:
            QMessageBox.warning(self, tr('运行环境扫描失败'), error); return
        if not plans:
            QMessageBox.information(self, tr('运行环境清理'), tr('未发现应用登记的旧版本运行环境。')); return
        eligible = [plan for plan in plans if not plan.protected_reason and plan.removal is not None]
        detail = '\n'.join(str(plan.root) + '\n' + (plan.protected_reason or
            tr('可清理逻辑大小 {size}；保留未知文件 {count} 项', size=format_bytes(plan.removal.logical_bytes), count=len(plan.removal.retained))) for plan in plans)
        if not eligible:
            QMessageBox.information(self, tr('运行环境均受保护'), detail); return
        answer = QMessageBox.question(self, tr('清理不再使用的模型运行环境'),
            tr('{detail}\n\n只永久删除清单中的旧版本文件；重新检查当前登记、进程占用和替代环境健康。当前运行环境、Python基底和模型权重保持。', detail=detail),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        from .model_runtime_cleanup import remove_unused_model_runtime
        self._cleanup_result_title = '运行环境清理结果'
        self._history_action(lambda: [remove_unused_model_runtime(plan, install_root=self.root,
            busy=self._storage_busy) for plan in eligible], self._history_cleanup_completed)

    def _confirm_history_cleanup(self, payload):
        plans, error = payload
        if error:
            QMessageBox.warning(self, tr('历史模型扫描失败'), error); return
        if not plans:
            QMessageBox.information(self, tr('历史模型残留'), tr('没有发现本应用管理范围内的历史模型残留。')); return
        preview = '\n'.join(str(tr('{key}: {path}（{count} 项，{size}）', key=p.model_key,
                                  path=str(p.root), count=len(p.paths), size=format_bytes(p.logical_bytes))) for p in plans)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(tr('永久清理历史模型残留'))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(str(tr('{preview}\n\n只删除清单中已登记的模型文件，保留共享或未知文件、模型运行环境和全局缓存。\n'
                              '目录 .bin 与权重文件扩展名 .bin 分开处理。不会移入回收站。', preview=preview)) +
                       '\n' + tr('再次使用需要下载。'))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(tr('永久删除'))
        dialog.button(QMessageBox.StandardButton.No).setText(tr('取消'))
        answer = dialog.exec()
        if answer != QMessageBox.StandardButton.Yes: return
        from .model_removal import execute_removal
        def remove():
            if self._storage_busy(): raise BlockingIOError('模型任务已开始，等待占用释放后重新清理')
            from ..recognition.asr import end_local_asr_session
            end_local_asr_session(force=True)
            return [execute_removal(plan, busy_check=self._storage_busy) for plan in plans]
        self._history_action(remove, self._history_cleanup_completed)

    def _history_cleanup_completed(self, payload):
        results, error = payload
        if error:
            QMessageBox.warning(self, tr('历史模型清理失败'), error); return
        failures = {p: why for result in results for p, why in result.failures.items()}
        retained = [p for result in results for p in result.retained]
        message = str(tr('已永久删除 {count} 项，逻辑大小 {logical}。\n独占文件 {exclusive}，硬链接可能仍由其他目录持有。',
                         count=sum(len(r.removed) for r in results), logical=format_bytes(sum(r.logical_bytes for r in results)),
                         exclusive=format_bytes(sum(r.exclusive_bytes for r in results))))
        if failures: message += '\n\n' + tr('未能删除：') + '\n' + '\n'.join(f'{p}: {why}' for p, why in failures.items())
        if retained: message += '\n\n' + tr('保留共享或未登记文件：') + '\n' + '\n'.join(retained[:20])
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning if failures or retained else QMessageBox.Icon.Information)
        dialog.setWindowTitle(tr(getattr(self, '_cleanup_result_title', '历史模型清理结果')))
        self._cleanup_result_title = '历史模型清理结果'
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.button(QMessageBox.StandardButton.Ok).setText(tr('确定'))
        dialog.exec()
        self.refresh()

    def _render_entries(self):
        self._clear_rows()
        entries = self._entries
        installed = [entry for entry in entries if entry.installed]
        model_bytes = sum(entry.actual_bytes for entry in entries)
        free_bytes = shutil.disk_usage(self.root).free
        values = (str(len(installed)), format_bytes(model_bytes), str(len(entries) - len(installed)), format_bytes(free_bytes))
        if any(entry.measurement_error for entry in entries):
            values = (values[0], tr('统计未完成（已知 {size}）', size=format_bytes(model_bytes)), values[2], values[3])
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        if self._mfa_runtime is not None and self.filter_mode != "missing":
            self.rows.insertWidget(self.rows.count() - 1, self._mfa_runtime_row(self._mfa_runtime))
        for entry in entries:
            if self.filter_mode == "installed" and not entry.installed:
                continue
            if self.filter_mode == "missing" and entry.installed:
                continue
            self.rows.insertWidget(self.rows.count() - 1, self._row(entry))

    def _row(self, entry: StorageEntry) -> QFrame:
        row = QFrame()
        row.setObjectName("storageRow")
        layout = QGridLayout(row)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(5)
        icon = QLabel()
        icon.setObjectName("storageIcon")
        icon.setPixmap(qta.icon("fa5s.database", color=theme_definition().accent).pixmap(25, 25))
        layout.addWidget(icon, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        name = QLabel(entry.name)
        name.setObjectName("storageModelName")
        layout.addWidget(name, 0, 1)
        status = QLabel("当前使用" if entry.current else ("已安装" if entry.installed else "未安装"))
        status.setObjectName("storageCurrent" if entry.current else ("storageInstalled" if entry.installed else "storageMissing"))
        layout.addWidget(status, 0, 2, Qt.AlignmentFlag.AlignLeft)
        role = {"primary": "主力转写", "timeline": "时间轴", "review": "文字复核"}.get(entry.role, entry.role)
        language = " / ".join(entry.languages) if entry.languages else "语言以官方资料为准"
        meta = QLabel(f"{role} · {language}")
        meta.setObjectName("storageMuted")
        meta.setWordWrap(True)
        layout.addWidget(meta, 1, 1, 1, 2)
        expected = format_bytes(entry.expected_bytes) if entry.expected_bytes else "以仓库实际文件为准"
        actual = tr('统计未完成') if entry.measurement_error else (format_bytes(entry.actual_bytes) if entry.actual_bytes else "—")
        runtime = f"{entry.environment_name} · {format_bytes(entry.environment_bytes)}" if entry.environment_bytes else f"{entry.environment_name} · 未安装"
        detail = bind_text(QLabel(), '预计下载 {expected}    模型文件 {actual}    运行环境 {runtime}\n{value3}', expected=expected, actual=actual, runtime=runtime, value3=entry.path)
        detail.setObjectName("storageDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail, 2, 1, 1, 3)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        if not entry.installed:
            download = QPushButton("下载")
            download.setObjectName("storagePrimary")
            download.clicked.connect(lambda _checked=False, item=entry: self.download_callback(item.key, item.name))
            actions.addWidget(download)
        else:
            verify = QPushButton("校验")
            verify.setObjectName("storageOutline")
            verify.clicked.connect(lambda _checked=False, item=entry: self._verify(item))
            actions.addWidget(verify)
            open_button = QPushButton("打开目录")
            open_button.setObjectName("storageOutline")
            open_button.clicked.connect(lambda _checked=False, path=entry.path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            actions.addWidget(open_button)
            uninstall = QPushButton("卸载")
            uninstall.setObjectName("storageDanger")
            uninstall.clicked.connect(lambda _checked=False, item=entry: self._uninstall(item))
            actions.addWidget(uninstall)
        actions.addStretch(1)
        layout.addLayout(actions, 3, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        return row

    def _mfa_runtime_row(self, plan) -> QFrame:
        """MFA's conda env (2026-10-19): no uv registry entry, so it gets its own row and delete button."""
        row = QFrame()
        row.setObjectName("storageRow")
        layout = QGridLayout(row)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(5)
        icon = QLabel()
        icon.setObjectName("storageIcon")
        icon.setPixmap(qta.icon("fa5s.cubes", color=theme_definition().accent).pixmap(25, 25))
        layout.addWidget(icon, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        name = QLabel("MFA 运行环境（实验）")
        name.setObjectName("storageModelName")
        layout.addWidget(name, 0, 1)
        current = "mfa_aligner" in self.current_keys()
        status = QLabel("当前使用" if current else ("已安装" if plan.ready else "未完成安装"))
        status.setObjectName("storageCurrent" if current else ("storageInstalled" if plan.ready else "storageMissing"))
        layout.addWidget(status, 0, 2, Qt.AlignmentFlag.AlignLeft)
        meta = QLabel("时间轴 · Montreal Forced Aligner（实验）独用的 conda 运行环境")
        meta.setObjectName("storageMuted")
        meta.setWordWrap(True)
        layout.addWidget(meta, 1, 1, 1, 2)
        tool = next((removal for removal in plan.removals if removal.root != plan.root), None)
        detail = bind_text(QLabel(), '运行环境 {size}（{count} 个文件）    安装工具 {tool}\n{path}',
                           size=format_bytes(plan.logical_bytes), count=f"{plan.files:,}",
                           tool=format_bytes(tool.logical_bytes) if tool else "—", path=str(plan.root))
        detail.setObjectName("storageDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail, 2, 1, 1, 3)
        if plan.protected_reason:
            reason = QLabel(tr(plan.protected_reason))
            reason.setObjectName("storageMuted")
            reason.setWordWrap(True)
            layout.addWidget(reason, 3, 1, 1, 3)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        if plan.root.is_dir():
            open_button = QPushButton("打开目录")
            open_button.setObjectName("storageOutline")
            open_button.clicked.connect(lambda _checked=False, path=plan.root: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            actions.addWidget(open_button)
        delete = QPushButton("删除运行环境")
        delete.setObjectName("storageDanger")
        delete.setEnabled(not plan.protected_reason and bool(plan.removals))
        delete.clicked.connect(lambda _checked=False, item=plan: self._delete_mfa_runtime(item))
        actions.addWidget(delete)
        actions.addStretch(1)
        layout.addLayout(actions, 4, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        return row

    def _delete_mfa_runtime(self, plan):
        if self._history_worker is not None:
            return
        if self._storage_busy():
            QMessageBox.information(self, tr('任务正在运行'), tr('请等待模型推理、下载、安装或修复结束。')); return
        if "mfa_aligner" in self.current_keys():
            QMessageBox.information(self, tr('正在使用这个运行环境'),
                                    tr('字幕时间轴正在用 MFA（实验）。请先在模型工坊为字幕时间轴选择其他模型，再删除它的运行环境。'))
            return
        tool = next((removal for removal in plan.removals if removal.root != plan.root), None)
        answer = QMessageBox.question(self, tr('删除 MFA 运行环境'),
            tr('{path}\n可删除逻辑大小 {size}（{count} 个文件）；安装工具 {tool}\n\n'
               '永久删除 Montreal Forced Aligner（实验）的运行环境，不移入回收站。只有它使用这个环境；'
               '模型文件、其他运行环境和设置保持。以后再用 MFA，在模型工坊点「安装 / 修复独立环境」重新准备（约 340 MB 下载）。',
               path=str(plan.root), size=format_bytes(plan.total_bytes), count=f"{plan.files:,}",
               tool=format_bytes(tool.logical_bytes) if tool else "—"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        from .model_runtime_cleanup import remove_mfa_runtime
        self._cleanup_result_title = '运行环境删除结果'
        self._history_action(lambda: [remove_mfa_runtime(plan, busy=self._storage_busy)], self._history_cleanup_completed)

    def _verify(self, entry: StorageEntry):
        ok, message = verify_model_files(self.root, entry.key)
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "校验通过" if ok else "校验失败", message)
        self.refresh()

    def _uninstall(self, entry: StorageEntry):
        self.uninstall_callback(entry.model_key)
        self.refresh()

    def _show_residuals(self):
        if self._history_worker is not None: return
        from .model_download_cache import scan_download_transactions
        staging = get_runtime_paths().model_root / '.downloads'
        self._history_action(lambda: scan_download_transactions(staging), self._confirm_residuals)

    def _confirm_residuals(self, payload):
        transactions, error = payload
        if error:
            QMessageBox.warning(self, tr('残留扫描失败'), error); return
        if not transactions:
            QMessageBox.information(self, tr('残留文件'), tr('没有发现可清理的 2ByteASR 临时下载文件。'))
            return
        total = sum(item.logical_bytes for item in transactions)
        preview = '\n'.join(f'{item.model_key}: {item.root} [{item.state}] {format_bytes(item.logical_bytes)}' for item in transactions)
        answer = QMessageBox.question(
            self,
            tr('清理残留文件'),
            tr('下载事务 {value0} 项，共 {value1}：\n\n{value2}\n\n仅清理已发布或超过续传保留期限的明确归属文件。使用中、未到期、未知文件与开发tmp保留。', value0=len(transactions), value1=format_bytes(total), value2=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from .model_download_cache import cleanup_download_transaction
        from ..storage.storage_service import StorageService
        resume_days = StorageService().policy()['resume_days']
        staging = get_runtime_paths().model_root / '.downloads'
        def remove():
            if self._storage_busy(): raise BlockingIOError('模型任务已开始，等待占用释放')
            return [cleanup_download_transaction(item, staging_root=staging,
                expired_only=True, resume_days=resume_days) for item in transactions]
        self._history_action(remove, self._residual_cleanup_completed)

    def _residual_cleanup_completed(self, payload):
        results, error = payload
        if error:
            QMessageBox.warning(self, tr('下载残留清理失败'), error); return
        removed = sum(len(item['removed']) for item in results)
        logical = sum(item['logical_bytes'] for item in results)
        reasons = [why for item in results for why in item['skipped']]
        failures = {path: why for item in results for path, why in item['failures'].items()}
        text = tr('已删除 {count} 项，逻辑大小 {logical}（实际空间可能受硬链接、稀疏文件及同期磁盘活动影响）。', count=removed, logical=format_bytes(logical))
        if reasons: text += '\n' + '\n'.join(reasons)
        if failures: text += '\n' + '\n'.join(f'{path}: {why}' for path, why in failures.items())
        QMessageBox.information(self, tr('下载残留清理结果'), text)


def build_storage_qss() -> str:
    theme = theme_definition(theme_key())
    return f"""
QDialog#modelStorageDialog {{ background: {theme.surface}; color: {theme.text}; }}
QDialog#modelStorageDialog QLabel {{ color: {theme.text}; background: transparent; }}
QLabel#storageTitle {{ font-family: 'Source Han Sans SC', '思源黑体', 'Microsoft YaHei UI'; font-size: 22px; font-weight: 700; color: {theme.text}; }}
QLabel#storageMuted, QLabel#storageDetail, QLabel#storageFactLabel {{ color: {theme.text_secondary}; font-size: 12px; }}
QFrame#storageSummary {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 10px; }}
QLabel#storageFactValue {{ color: {theme.text}; font-size: 17px; font-weight: 600; }}
QLineEdit#storagePathEdit {{
    background: {theme.input_surface}; color: {theme.text}; border: 1px solid {theme.border};
    border-radius: 8px; min-height: 32px; padding: 0 10px;
}}
QFrame#storageRow {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; border-radius: 10px; }}
QFrame#storageRow:hover {{ border-color: {theme.accent}; background: {theme.selected}; }}
QLabel#storageModelName {{ font-size: 15px; font-weight: 700; color: {theme.text}; }}
QLabel#storageDetail {{ font-family: 'Source Han Sans SC', '思源黑体', 'Microsoft YaHei UI'; color: {theme.text_muted}; }}
QLabel#storageInstalled, QLabel#storageCurrent, QLabel#storageMissing {{ padding: 3px 8px; border-radius: 8px; font-size: 11px; font-weight: 600; }}
QLabel#storageInstalled {{ color: {theme.success}; background: {theme.accent_soft}; }}
QLabel#storageCurrent {{ color: {theme.text}; background: {theme.accent_soft}; border: 1px solid {theme.accent}; }}
QLabel#storageMissing {{ color: {theme.warning}; background: {theme.warning_soft}; }}
QPushButton#storageFilter, QPushButton#storageOutline, QPushButton#storagePrimary, QPushButton#storageDanger {{ min-height: 30px; padding: 0 11px; border-radius: 8px; font-weight: 600; }}
QPushButton#storageFilter, QPushButton#storageOutline {{ background: {theme.surface_elevated}; border: 1px solid {theme.border}; color: {theme.text}; }}
QPushButton#storageFilter:checked, QPushButton#storagePrimary {{ background: {theme.accent}; border: 1px solid {theme.accent}; color: {theme.text_on_accent}; }}
QPushButton#storageDanger {{ background: transparent; border: 1px solid {theme.danger}; color: {theme.danger}; }}
QPushButton:hover {{ border-color: {theme.accent_hover}; }}
QPushButton:disabled {{ color: {theme.disabled}; background: {theme.panel}; border-color: {theme.border}; }}
QScrollArea#storageScroll {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: {theme.panel}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {theme.border_strong}; min-height: 24px; border-radius: 5px; }}
"""


_STORAGE_QSS = build_storage_qss()
