"""Online glossary hub sheets inside the term library (2026-10-17).

Three hosted sheets, styled like the batch-import sheet:

* the hub list (browse, refresh, install / update / remove);
* the install preview: every alias rule with its findings; rules the shared
  check warns about start unticked (user decision 2026-10-17);
* the submit sheet: checks, nickname, CC0 consent, then export the cleaned
  file, copy the issue text and open the GitHub or GitCode issue page.

Network work runs on a daemon thread; results come back through a QObject
that lives in the GUI thread.  See glossary_hub.py for the data rules.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from PySide6.QtGui import QColor

from .i18n import bind_text, tr
from . import glossary_hub as hub
from .glossary_lint import BLOCK, WARN, findings_by_row

_STATUS_TEXT = {"none": "未安装", "installed": "已安装", "update": "有更新"}
_ROW_NOTES = {
    "same": "你的词库已有，保持你的版本",
    "conflict": "和你的词库冲突，不安装",
    "declined": "你以前没装或删掉了，默认不勾",
}


class _Relay(QObject):
    """Carries a worker-thread result back to the GUI thread."""

    finished = Signal(object, object)

    def __init__(self, parent, callback):
        super().__init__(parent)
        self._callback = callback
        self.finished.connect(self._deliver)

    def _deliver(self, result, error):
        try:
            self._callback(result, error)
        finally:
            self.deleteLater()


def _run_async(owner, job, callback) -> None:
    relay = _Relay(owner, callback)

    def run():
        try:
            result, error = job(), None
        except Exception as exc:  # noqa: BLE001 - shown to the user as text
            result, error = None, exc
        relay.finished.emit(result, error)

    threading.Thread(target=run, name="glossary-hub-ui", daemon=True).start()


def _theme():
    from .main_ui_glossary import _sheet_theme
    return _sheet_theme()


class _Sheet:
    """A dimmed, centred sheet hosted inside the term library dialog."""

    def __init__(self, dialog, name: str, width: int = 860, height: int = 640):
        theme = _theme()
        self.dialog, self.width, self.height = dialog, width, height
        self.dim = QFrame(dialog)
        self.dim.setObjectName(name + "Dim")
        self.dim.setStyleSheet(f"background: {getattr(theme, 'overlay_scrim', 'rgba(0,0,0,0.35)')}; border:0;")
        self.frame = QFrame(dialog)
        self.frame.setObjectName(name)
        self.frame.setStyleSheet(
            f"QFrame#{name} {{ background:{theme.surface}; border:1px solid {theme.border}; border-radius:12px; }}")
        self.frame.setAutoFillBackground(True)
        self.layout = QVBoxLayout(self.frame)
        self.layout.setContentsMargins(16, 14, 16, 14)
        self.layout.setSpacing(8)
        self.closed = False
        self._resize = _ResizeWatcher(dialog, self.place)

    def place(self):
        if self.closed:
            return
        rect = self.dialog.rect()
        self.dim.setGeometry(rect)
        width = min(self.width, max(340, rect.width() - 48))
        height = min(self.height, max(380, rect.height() - 60))
        self.frame.setGeometry((rect.width() - width) // 2, max(24, (rect.height() - height) // 2 - 10),
                               width, height)

    def show(self):
        self.place()
        self.dim.show()
        self.dim.raise_()
        self.frame.show()
        self.frame.raise_()

    def close(self):
        self.closed = True
        self._resize.stop()
        for widget in (self.dim, self.frame):
            try:
                widget.deleteLater()
            except RuntimeError:
                pass


class _ResizeWatcher(QObject):
    def __init__(self, target, callback):
        super().__init__(target)
        self._target, self._callback = target, callback
        target.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent
        if obj is self._target and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._callback)
        return False

    def stop(self):
        try:
            self._target.removeEventFilter(self)
        except RuntimeError:
            pass


def _title(text: str, **arguments) -> QLabel:
    label = bind_text(QLabel(), text, **arguments)
    label.setStyleSheet("font-weight:700; font-size:15px;")
    return label


def _muted(text: str, **arguments) -> QLabel:
    label = bind_text(QLabel(), text, **arguments)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _button(text: str, primary: bool = False) -> QPushButton:
    button = bind_text(QPushButton(), text)
    button.setObjectName("workshopAction" if primary else "workshopSecondary")
    return button


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([tr(header) for header in headers])
    table.verticalHeader().hide()
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setWordWrap(False)
    return table


def _item(text, tooltip: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _finding_text(findings) -> str:
    return "；".join(dict.fromkeys(tr(item.message) for item in findings))


def _refresh_dialog(dialog, library_key: str, name: str, created: bool) -> None:
    dialog._notify_library_changed()
    if created:
        dialog.add_game_item(name, select=True, library_id=library_key)
    else:
        dialog.refresh_current_game()
    refresh_counts = getattr(dialog, "_refresh_game_item_counts", None)
    if callable(refresh_counts):
        refresh_counts()


def _forget_library(dialog, library_key: str) -> None:
    """The library an uninstall deleted: leave the enabled set and the list."""
    owner = dialog.owner
    enabled = [item for item in owner._enabled_glossary_ids() if item != library_key]
    owner.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})["enabled_glossary_ids"] = enabled
    owner._save_glossary_settings()
    for index in range(dialog.game_list.count()):
        item = dialog.game_list.item(index)
        if item and str(item.data(Qt.ItemDataRole.UserRole + 1) or "") == library_key:
            dialog.game_list.takeItem(index)
            break
    if dialog.state.get("library_id") == library_key:
        dialog.state["game"], dialog.state["library_id"] = "", ""
    dialog._notify_library_changed()
    if dialog.game_list.count():
        dialog.game_list.setCurrentRow(0)
    else:
        dialog.refresh_current_game()


# --------------------------------------------------------------------------
# Hub list


class HubSheet:
    def __init__(self, dialog):
        self.dialog = dialog
        self.legacy = dialog.legacy
        self.catalog: hub.Catalog | None = None
        self.entries: list[dict] = []
        self.preview: PreviewSheet | None = None
        self.sheet = _Sheet(dialog, "termHubSheet")
        lay = self.sheet.layout
        head = QHBoxLayout()
        head.addWidget(_title("线上词库"))
        head.addStretch(1)
        close = _button("关闭")
        close.clicked.connect(self.close)
        head.addWidget(close)
        lay.addLayout(head)
        lay.addWidget(_muted("社区整理的游戏术语库，维护者审核后发布。中国大陆从 GitCode 下载，海外从 GitHub 下载；"
                             "每个文件都校验签名和哈希。"))
        self.search = QLineEdit()
        bind_text(self.search, "搜索游戏或词库…", property="placeholderText")
        self.search.textChanged.connect(self._render)
        lay.addWidget(self.search)
        self.status = _muted("正在获取线上词库…")
        lay.addWidget(self.status)
        self.table = _table(["词库", "游戏", "词条", "版本", "更新", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._primary())
        lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.source = _muted("")
        foot.addWidget(self.source, 1)
        self.refresh_button = _button("刷新")
        self.refresh_button.clicked.connect(lambda: self.load(force=True))
        self.submit_button = _button("投稿我的词库")
        self.submit_button.clicked.connect(self._submit)
        self.remove_button = _button("移除")
        self.remove_button.clicked.connect(self._remove)
        self.primary = _button("预览并安装", primary=True)
        self.primary.clicked.connect(self._primary)
        for widget in (self.refresh_button, self.submit_button, self.remove_button, self.primary):
            foot.addWidget(widget)
        lay.addLayout(foot)
        self._remove_armed = False
        self.sheet.show()
        self._selection_changed()
        self.load(force=False)

    # ---- data

    def load(self, force: bool):
        self.refresh_button.setEnabled(False)
        bind_text(self.status, "正在获取线上词库…")
        self.status.show()
        _run_async(self.dialog, lambda: hub.fetch_catalog(force=force, legacy=self.legacy), self._loaded)

    def _loaded(self, catalog, error):
        if self.sheet.closed:
            return
        self.refresh_button.setEnabled(True)
        if error is not None:
            self.catalog, self.entries = None, []
            self.table.setRowCount(0)
            if "还没有发布" in str(error):
                bind_text(self.status, "线上词库还没有上线。上线后这里会列出社区词库；现在可以先投稿你的词库。")
            else:
                bind_text(self.status, "获取线上词库失败：{reason}", reason=str(error))
            self.source.setText("")
            self._selection_changed()
            return
        self.catalog = catalog
        self.entries = catalog.entries
        when = __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(catalog.fetched_at))
        if catalog.stale:
            bind_text(self.source, "离线：显示 {when} 从 {origin} 获取的目录", when=when, origin=catalog.source)
        else:
            bind_text(self.source, "来源：{origin} · 已验证签名 · {when} 获取", origin=catalog.source, when=when)
        self._render()

    def _render(self):
        subs = hub.subscriptions(self.legacy)
        query = self.search.text().strip().casefold()
        shown = [entry for entry in self.entries if not query or query in
                 f"{entry.get('title', '')} {entry.get('game', '')} {entry.get('id', '')}".casefold()]
        self.table.setRowCount(len(shown))
        for row, entry in enumerate(shown):
            status = hub.catalog_status(entry, subs)
            note = entry.get("note") or ""
            values = (entry.get("title") or entry["game"], entry["game"], entry.get("rows", ""),
                      f"v{entry['version']}", entry.get("updated", ""), tr(_STATUS_TEXT[status]))
            for column, value in enumerate(values):
                item = _item(value, note)
                item.setData(Qt.ItemDataRole.UserRole, entry["id"])
                self.table.setItem(row, column, item)
        if self.entries and not shown:
            bind_text(self.status, "没有符合“{query}”的词库。", query=self.search.text().strip())
            self.status.show()
        elif not self.entries and self.catalog is not None:
            bind_text(self.status, "线上词库里还没有词库。")
            self.status.show()
        else:
            self.status.setVisible(self.catalog is None)
        self._selection_changed()

    def _selected(self) -> dict | None:
        items = self.table.selectedItems()
        if not items:
            return None
        library_id = items[0].data(Qt.ItemDataRole.UserRole)
        return next((entry for entry in self.entries if entry["id"] == library_id), None)

    def _selection_changed(self):
        entry = self._selected()
        self._remove_armed = False
        bind_text(self.remove_button, "移除")
        if entry is None:
            bind_text(self.primary, "预览并安装")
            self.primary.setEnabled(False)
            self.remove_button.setEnabled(False)
            return
        status = hub.catalog_status(entry, hub.subscriptions(self.legacy))
        bind_text(self.primary, {"none": "预览并安装", "update": "预览更新", "installed": "重新预览"}[status])
        self.primary.setEnabled(True)
        self.remove_button.setEnabled(status != "none")

    # ---- actions

    def _primary(self):
        entry = self._selected()
        if entry is None or not self.primary.isEnabled():
            return
        self.primary.setEnabled(False)
        bind_text(self.status, "正在下载《{title}》…", title=entry.get("title") or entry["game"])
        self.status.show()
        catalog = self.catalog
        _run_async(self.dialog, lambda: hub.fetch_library(entry, catalog), lambda library, error:
                   self._downloaded(entry, library, error))

    def _downloaded(self, entry, library, error):
        if self.sheet.closed:
            return
        self.primary.setEnabled(True)
        if error is not None:
            bind_text(self.status, "下载失败：{reason}", reason=str(error))
            return
        self.status.hide()
        plan = hub.plan_install(entry, library, legacy=self.legacy)
        self.preview = PreviewSheet(self.dialog, plan, on_done=self._render)

    def _remove(self):
        entry = self._selected()
        if entry is None:
            return
        if not self._remove_armed:
            self._remove_armed = True
            bind_text(self.remove_button, "确认移除")
            QTimer.singleShot(4000, lambda: (not self.sheet.closed and self._selection_changed()))
            return
        subs = hub.subscriptions(self.legacy)
        library_key = subs.get(entry["id"], ("", {}))[0]
        removed = hub.uninstall(entry["id"], legacy=self.legacy)
        still_there = library_key in (self.legacy.load_learned_term_payload().get("games") or {})
        if library_key and not still_there:
            _forget_library(self.dialog, library_key)
        else:
            _refresh_dialog(self.dialog, library_key, "", created=False)
        self.dialog._show_toast(tr("已移除 {count} 条线上词条；你改过的词条保留。", count=removed), 3000)
        self._render()

    def _submit(self):
        self.close()
        open_submit_sheet(self.dialog)

    def close(self):
        self.sheet.close()
        self.dialog._hub_sheet = None


# --------------------------------------------------------------------------
# Install preview


class PreviewSheet:
    def __init__(self, dialog, plan: hub.InstallPlan, on_done=None):
        self.dialog, self.plan, self.on_done = dialog, plan, on_done
        self.sheet = _Sheet(dialog, "termHubPreviewSheet", 900, 680)
        lay = self.sheet.layout
        entry = plan.entry
        name = entry.get("title") or entry["game"]
        if plan.updating:
            lay.addWidget(_title("更新《{name}》到 v{version}", name=name, version=entry["version"]))
            lay.addWidget(_muted("你改过或删掉的词条保持原样；线上已删除的词条会一起移除。"))
        elif plan.target_key:
            lay.addWidget(_title("安装《{name}》 v{version}", name=name, version=entry["version"]))
            lay.addWidget(_muted("会装进你已有的词库《{target}》；你原有的词条保持不动。", target=plan.target_name))
        else:
            lay.addWidget(_title("安装《{name}》 v{version}", name=name, version=entry["version"]))
            lay.addWidget(_muted("会新建词库《{target}》。", target=plan.target_name))
        hotwords = sum(1 for item in plan.rows if not item.is_alias and item.status in {"new", "installed", "declined"})
        aliases = sum(1 for item in plan.rows if item.is_alias and item.status in {"new", "installed", "declined"})
        skipped = plan.count("same", "conflict", "blocked")
        self.summary = _muted("热词 {hotwords} 条（只帮识别写对，不改字）· 改字规则 {aliases} 条 · 跳过 {skipped} 条 · 移除 {removed} 条",
                              hotwords=hotwords, aliases=aliases, skipped=skipped, removed=len(plan.removed))
        lay.addWidget(self.summary)
        lay.addWidget(_muted("改字规则会把字幕里所有左边的词改成右边。带提醒的规则默认不勾，请按需要勾选。"))
        self.table = _table(["安装", "原词 → 结果", "分类", "说明"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        installable_statuses = {"new", "installed", "declined"}

        def rank(index):
            # Rules the user decides on first (warned aliases, then other aliases,
            # then hotwords); rows that will not be installed go last.
            item = plan.rows[index]
            if item.status not in installable_statuses:
                return (3 if item.status == "same" else 2, index)
            if item.is_alias:
                return (0 if any(finding.level == WARN for finding in item.findings) else 1, index)
            return (1.5, index)

        order = sorted(range(len(plan.rows)), key=rank)
        self.table.setRowCount(len(order))
        self._checks: list[tuple[QTableWidgetItem, hub.PlanRow]] = []
        muted = QColor(_theme().text_muted)
        from .main_ui_glossary import _reference_category_label
        for row, index in enumerate(order):
            item = plan.rows[index]
            check = QTableWidgetItem("")
            installable = item.status in installable_statuses
            if installable:
                check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                check.setCheckState(Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked)
                self._checks.append((check, item))
            else:
                check.setFlags(Qt.ItemFlag.ItemIsEnabled)
            text = item.row["to"] if not item.is_alias else f"{item.row['from']} → {item.row['to']}"
            notes = []
            if item.status in _ROW_NOTES:
                notes.append(tr(_ROW_NOTES[item.status]))
            relevant = [finding for finding in item.findings
                        if finding.level == BLOCK or (installable and finding.level == WARN)]
            if relevant:
                notes.append(_finding_text(relevant))
            if installable and item.row.get("verified_audio"):
                notes.append(tr("投稿人在实际音频里核对过"))
            if installable and item.row.get("note"):
                notes.append(item.row["note"])
            cells = (check, _item(text), _item(_reference_category_label(item.row.get("category", ""))),
                     _item("；".join(notes), "；".join(notes)))
            for column, cell in enumerate(cells):
                if not installable:
                    cell.setForeground(muted)
                self.table.setItem(row, column, cell)
        lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        verified = _button("勾选已核对的规则")
        verified.setEnabled(any(item.row.get("verified_audio") for _check, item in self._checks))
        verified.clicked.connect(self._tick_verified)
        foot.addWidget(verified)
        foot.addStretch(1)
        cancel = _button("取消")
        cancel.clicked.connect(self.sheet.close)
        install = _button("更新" if plan.updating else "安装", primary=True)
        install.clicked.connect(self._install)
        self.install_button = install
        foot.addWidget(cancel)
        foot.addWidget(install)
        lay.addLayout(foot)
        self.sheet.show()

    def _tick_verified(self):
        for check, item in self._checks:
            if item.row.get("verified_audio"):
                check.setCheckState(Qt.CheckState.Checked)

    def _install(self):
        chosen = {hub.row_key(item.row) for check, item in self._checks
                  if check.checkState() == Qt.CheckState.Checked}
        try:
            result = hub.apply_install(self.plan, chosen, legacy=self.dialog.legacy)
        except (hub.HubError, OSError, ValueError) as exc:
            self.dialog._show_toast(tr("没有安装：{reason}", reason=str(exc)), 5000)
            return
        self.sheet.close()
        created = not self.plan.target_key
        _refresh_dialog(self.dialog, result.library_key, self.plan.target_name, created)
        if self.plan.updating:
            message = tr("已更新《{name}》：新增 {added} 条，移除 {removed} 条，保留你改过的 {kept} 条。",
                         name=self.plan.target_name, added=result.added, removed=result.removed, kept=result.kept_edits)
        else:
            message = tr("已把 {added} 条词装进《{name}》。", added=result.added, name=self.plan.target_name)
        self.dialog._show_toast(message, 3500)
        if callable(self.on_done):
            self.on_done()


# --------------------------------------------------------------------------
# Submit


def _downloads_folder() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return Path(location) if location else Path.home() / "Downloads"


def _reveal(path: Path) -> None:
    import sys
    if sys.platform == "win32":
        from .processes import popen_hidden_subprocess
        popen_hidden_subprocess(["explorer.exe", "/select,", str(path)], purpose="reveal glossary submission")
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class SubmitSheet:
    def __init__(self, dialog, library_key: str, game: str):
        self.dialog, self.library_key, self.game = dialog, library_key, game
        self.sheet = _Sheet(dialog, "termHubSubmitSheet", 760, 640)
        lay = self.sheet.layout
        lay.addWidget(_title("投稿《{game}》到线上词库", game=game))
        self.document, self.findings = hub.build_submission(library_key, legacy=dialog.legacy)
        rows = self.document["mappings"]
        aliases = sum(1 for row in rows if row["from"] != row["to"])
        lay.addWidget(_muted("{count} 条已确认的词，其中改字规则 {aliases} 条。只上传词和分类；理由、来源、任务编号和日期留在你的电脑上。",
                             count=len(rows), aliases=aliases))
        grouped = findings_by_row(self.findings)            # one line per rule
        verified = {(row["from"], row["to"]) for row in rows if row.get("verified_audio")}
        blocked = [key for key, found in grouped.items() if any(item.level == BLOCK for item in found)]
        warned = [key for key in grouped if key not in blocked]
        if blocked:
            lay.addWidget(_muted("有 {count} 条必须先改才能投稿（见下表）。", count=len(blocked)))
        else:
            lay.addWidget(_muted("✓ 没有阻止发布的问题。"))
        if warned:
            lay.addWidget(_muted("! {count} 条规则有提醒：别人安装时默认不勾，审核时也会看。", count=len(warned)))
        listed = blocked + warned
        if listed:
            table = _table(["级别", "原词 → 结果", "说明"])
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            table.setRowCount(len(listed))
            for row, key in enumerate(listed):
                found = grouped[key]
                notes = _finding_text(found)
                if key in verified:
                    notes += "；" + tr("已标为实际音频核对")
                table.setItem(row, 0, _item(tr("必须改") if key in blocked else tr("提醒")))
                table.setItem(row, 1, _item(f"{key[0]} → {key[1]}"))
                table.setItem(row, 2, _item(notes, notes))
            lay.addWidget(table, 1)
        else:
            lay.addStretch(1)
        self.author = QLineEdit()
        bind_text(self.author, "署名（昵称，可以留空）", property="placeholderText")
        lay.addWidget(self.author)
        self.note = QPlainTextEdit()
        bind_text(self.note, "给审核者的说明（可以留空），例如：这些误听来自哪些直播", property="placeholderText")
        self.note.setMaximumHeight(70)
        lay.addWidget(self.note)
        self.consent = bind_text(QCheckBox(), "我同意以 CC0 公开这些词条（任何人都可以自由使用）")
        lay.addWidget(self.consent)
        foot = QHBoxLayout()
        export = _button("只导出文件")
        export.clicked.connect(lambda: self._send(""))
        cancel = _button("取消")
        cancel.clicked.connect(self.sheet.close)
        github = _button("用 GitHub 投稿")
        github.clicked.connect(lambda: self._send("github"))
        gitcode = _button("用 GitCode 投稿", primary=True)
        gitcode.clicked.connect(lambda: self._send("gitcode"))
        foot.addWidget(export)
        foot.addStretch(1)
        for widget in (cancel, github, gitcode):
            foot.addWidget(widget)
        lay.addLayout(foot)
        self.send_buttons = (export, github, gitcode)
        self.github_button, self.gitcode_button = github, gitcode

        def update_state(*_):
            allowed = not blocked and bool(rows) and self.consent.isChecked()
            for button in self.send_buttons:
                button.setEnabled(allowed)

        self.consent.toggled.connect(update_state)
        update_state()
        self.sheet.show()

    def _send(self, provider: str):
        document, findings = hub.build_submission(
            self.library_key, author=self.author.text(), note=self.note.toPlainText(), legacy=self.dialog.legacy,
            app_version=_app_version())
        if any(item.level == BLOCK for item in findings):
            self.dialog._show_toast(tr("词库有必须先改的问题，没有导出。"), 4000)
            return
        try:
            path = hub.write_submission(document, _downloads_folder())
        except OSError as exc:
            self.dialog._show_toast(tr("导出失败：{reason}", reason=str(exc)), 5000)
            return
        try:
            _reveal(path)
        except Exception:  # noqa: BLE001 - revealing the file is a convenience
            pass
        if provider:
            title, body = hub.issue_text(document, findings)
            QApplication.clipboard().setText(f"{title}\n\n{body}")
            QDesktopServices.openUrl(QUrl(hub.issue_url(provider, document, findings)))
            message = tr("已导出 {name}，并打开投稿页。标题和说明已复制，把文件拖进投稿页即可。", name=path.name)
        else:
            message = tr("已导出 {name}。", name=path.name)
        self.sheet.close()
        self.dialog._show_toast(message, 6000)


def _app_version() -> str:
    try:
        from .updater import current_version
        return current_version()
    except Exception:  # noqa: BLE001 - the version is informative only
        return ""


# --------------------------------------------------------------------------
# Entry points used by TermLibraryDialog


def open_hub_sheet(dialog) -> None:
    current = getattr(dialog, "_hub_sheet", None)
    if current is not None and not current.sheet.closed:
        current.sheet.show()
        return
    dialog._hub_sheet = HubSheet(dialog)


def open_submit_sheet(dialog) -> None:
    game = dialog.state.get("game", "")
    library_key = dialog.state.get("library_id") or dialog._library_key(game)
    games = dialog.legacy.load_learned_term_payload().get("games") or {}
    if not game or library_key not in games:
        dialog._show_toast(tr("请先在左侧选择一个你自己的词库，再投稿。"), 3500)
        return
    try:
        dialog._hub_submit = SubmitSheet(dialog, library_key, game)
    except hub.HubError as exc:
        dialog._show_toast(str(exc), 3500)
