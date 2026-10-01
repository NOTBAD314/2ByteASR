"""Project-owned model storage inventory and management UI."""

from __future__ import annotations

import hashlib
import json
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
from .runtime_paths import get_runtime_paths, set_model_root
from .theme_manager import theme_key
from .ui_theme import theme_definition

from .i18n import bind_text

from .i18n import tr


def format_bytes(value: int) -> str:
    size = float(max(0, int(value)))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return "0 B"


def directory_size(path: Path, *, max_files: int = 8_000) -> int:
    if not path.is_dir():
        return 0
    total = 0
    counted = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
                    counted += 1
                    if counted >= max_files:
                        return total
            except OSError:
                continue
    except OSError:
        return total
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


class _StorageScanThread(QThread):
    completed = Signal(object)

    def __init__(self, root: Path, models: tuple[object, ...], current: set[str], parent=None):
        super().__init__(parent)
        self.root = root
        self.models = models
        self.current = current

    def run(self):
        self.completed.emit(scan_storage(self.root, self.models, self.current))


def scan_storage(root: Path, models: Iterable[object], current_keys: set[str]) -> list[StorageEntry]:
    root = Path(root).resolve()
    registry = scan_model_registry(install_root=root, measure_size=False)
    entries: list[StorageEntry] = []
    environment_sizes: dict[Path, int] = {}
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
        if env_path and env_path.is_dir():
            if env_path not in environment_sizes:
                environment_sizes[env_path] = _environment_bytes(env_path)
            env_bytes = environment_sizes[env_path]
        if path.is_dir():
            if expected_bytes >= 80_000_000:
                actual_bytes = expected_bytes if installed else actual_bytes
            elif actual_bytes <= 0:
                actual_bytes = directory_size(path)
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
    """Return only explicit temporary artifacts owned by this checkout."""
    root = root.resolve()
    found: list[Path] = []
    for owner in ("models", "tmp"):
        base = (root / owner).resolve()
        if not base.is_dir():
            continue
        for item in base.rglob("*"):
            try:
                if not item.is_file() or not _owned_child(root, item, owner):
                    continue
            except OSError:
                continue
            lower = item.name.lower()
            if lower.endswith((".part", ".tmp", ".download.json")) or ".part." in lower:
                found.append(item)
    return found


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
        self._scanner: _StorageScanThread | None = None
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
        set_model_root(chosen, persist=True)
        self.model_root_edit.setText(str(get_runtime_paths().model_root))
        self.refresh()

    def _scan_existing_models(self) -> None:
        from .runtime_paths import build_runtime_paths, persist_runtime_paths, reset_runtime_paths

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
        self._entries = list(entries) if isinstance(entries, list) else []
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            scanner.deleteLater()
        self._render_entries()
        if self._close_after_scan:
            QDialog.reject(self)

    def reject(self):
        if self._scanner is not None and self._scanner.isRunning():
            self._close_after_scan = True
            self.hide()
            return
        super().reject()

    def _render_entries(self):
        self._clear_rows()
        entries = self._entries
        installed = [entry for entry in entries if entry.installed]
        model_bytes = sum(entry.actual_bytes for entry in entries)
        free_bytes = shutil.disk_usage(self.root).free
        values = (str(len(installed)), format_bytes(model_bytes), str(len(entries) - len(installed)), format_bytes(free_bytes))
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
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
        actual = format_bytes(entry.actual_bytes) if entry.actual_bytes else "—"
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

    def _verify(self, entry: StorageEntry):
        ok, message = verify_model_files(self.root, entry.key)
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "校验通过" if ok else "校验失败", message)
        self.refresh()

    def _uninstall(self, entry: StorageEntry):
        self.uninstall_callback(entry.model_key)
        self.refresh()

    def _show_residuals(self):
        files = residual_files(self.root)
        if not files:
            QMessageBox.information(self, tr('残留文件'), tr('没有发现可清理的 2ByteASR 临时下载文件。'))
            return
        total = sum(item.stat().st_size for item in files if item.is_file())
        preview = "\n".join(str(item.relative_to(self.root)) for item in files[:20])
        if len(files) > 20:
            preview += f"\n…另有 {len(files) - 20} 项"
        answer = QMessageBox.question(
            self,
            tr('清理残留文件'),
            tr('将删除 {value0} 个项目内临时文件，共 {value1}：\n\n{value2}\n\n不会清理用户全局 Hugging Face cache。', value0=len(files), value1=format_bytes(total), value2=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        for item in files:
            try:
                owner = "models" if _owned_child(self.root, item, "models") else "tmp"
                if _owned_child(self.root, item, owner):
                    item.unlink()
                    removed += 1
            except OSError:
                continue
        QMessageBox.information(self, tr('清理完成'), tr('已删除 {value0} 个项目内临时文件。', value0=removed))


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
