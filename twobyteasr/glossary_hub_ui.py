"""Online glossary hub inside the term library (2026-10-17).

* the hub page, ``HubPanel``: the 「线上词库」 tab of the term library
  (redesign of the same day, plan 2026-10-17-glossary-page-redesign): search,
  one card per community library (preview / install / update / remove) and
  the submit entry;
* the install preview sheet: every alias rule with its findings; rules the shared
  check warns about start unticked (user decision 2026-10-17);
* the submit sheet (2026-10-18 redesign): three steps - choose one of your
  libraries, check what will be uploaded (untick rows; each kind of finding
  said once), then nickname, note, CC0 consent, and export the cleaned file,
  copy the issue text and open the GitHub or GitCode issue page.

The preview and submit sheets are dimmed overlays hosted by the dialog.

Network work runs on a daemon thread; results come back through a QObject
that lives in the GUI thread.  See glossary_hub.py for the data rules.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import QColor

from .i18n import bind_text, tr, user_text
from . import glossary_hub as hub
from .glossary_lint import BLOCK, WARN, blocking, findings_by_row, lint_rows

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
# Hub page (2026-10-17 redesign v2: a tab of the term library; quiet cards,
# one accent; the title, the search and 「投稿我的词库」 share one row)


_CARD_WIDTH = 260
_CARD_GAP = 16


class _HubCard(QFrame):
    """One community library: title and status, note, size, its action."""

    def __init__(self, panel: "HubPanel", entry: dict):
        super().__init__()
        self.setObjectName("termHubCard")
        self.panel, self.entry = panel, entry
        self.setMinimumWidth(_CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel(entry.get("title") or entry["game"])
        self.title.setObjectName("termHubCardTitle")
        self.title.setToolTip(entry.get("title") or entry["game"])
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.title, 1)
        self.status_pill = QLabel()
        top.addWidget(self.status_pill)
        lay.addLayout(top)
        note = QLabel(entry.get("note") or "")
        note.setObjectName("termHubCardNote")
        note.setWordWrap(True)
        note.setToolTip(entry.get("note") or "")
        note.setFixedHeight(note.fontMetrics().lineSpacing() * 2 + 6)
        note.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(note)
        divider = QFrame()
        divider.setObjectName("termHubCardDivider")
        divider.setFixedHeight(1)
        lay.addWidget(divider)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        meta = bind_text(QLabel(), "{rows} 条 · v{version} · {updated}", rows=entry.get("rows", ""),
                         version=entry.get("version", ""), updated=str(entry.get("updated", ""))[5:] or "")
        meta.setObjectName("termHubCardMeta")
        actions.addWidget(meta, 1)
        self.remove_button = bind_text(QPushButton(), "移除")
        self.remove_button.setObjectName("termHubQuiet")
        self.remove_button.clicked.connect(self._remove)
        actions.addWidget(self.remove_button)
        self.primary = QPushButton()
        self.primary.clicked.connect(lambda: panel.preview_entry(self.entry))
        actions.addWidget(self.primary)
        lay.addLayout(actions)
        self._remove_armed = False
        self.refresh()

    def refresh(self, subs=None):
        status = hub.catalog_status(self.entry, hub.subscriptions(self.panel.legacy) if subs is None else subs)
        self.status = status
        self._remove_armed = False
        bind_text(self.remove_button, "移除")
        self.remove_button.setVisible(status != "none")
        bind_text(self.primary, {"none": "预览并安装", "update": "预览更新", "installed": "重新预览"}[status])
        self.primary.setObjectName({"none": "termHubAction", "update": "termHubActionStrong",
                                    "installed": "termHubQuiet"}[status])
        if status == "none":
            self.status_pill.hide()
        else:
            bind_text(self.status_pill, "✓ 已安装" if status == "installed" else "有更新")
            self.status_pill.setObjectName("termHubPillInstalled" if status == "installed" else "termHubPillUpdate")
            self.status_pill.show()
        for widget in (self.primary, self.status_pill):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _remove(self):
        if not self._remove_armed:
            self._remove_armed = True
            bind_text(self.remove_button, "确认移除")
            QTimer.singleShot(4000, self._disarm)
            return
        self.panel.remove_entry(self.entry)

    def _disarm(self):
        try:
            if self._remove_armed:
                self.refresh()
        except RuntimeError:  # the card was rebuilt in the meantime
            pass


class _AddCard(QFrame):
    def __init__(self, panel: "HubPanel"):
        super().__init__()
        self.setObjectName("termHubAddCard")
        self.setMinimumWidth(_CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(6)
        lay.addStretch(1)
        title = bind_text(QLabel(), "你的游戏不在这里？")
        title.setObjectName("termHubCardTitle")
        lay.addWidget(title)
        text = bind_text(QLabel(), "整理好后投稿，下一个人就不用从零开始。")
        text.setObjectName("termHubCardMeta")
        text.setWordWrap(True)
        lay.addWidget(text)
        button = bind_text(QPushButton(), "投稿我的词库 →")
        button.setObjectName("termHubLink")
        button.clicked.connect(panel.submit)
        lay.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)


class HubPanel(QWidget):
    """The online glossary as a page of the term library: search, cards,
    preview / install / update / remove, and the submit entry."""

    counts_changed = Signal(int, int)  # libraries in the catalog, installed ones with an update

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.setObjectName("termHubPanel")
        self.dialog = dialog
        self.legacy = dialog.legacy
        self.catalog: hub.Catalog | None = None
        self.entries: list[dict] = []
        self.cards: list[_HubCard] = []
        self.preview: PreviewSheet | None = None
        self._columns = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(18)

        head = QHBoxLayout()
        head.setSpacing(12)
        intro = QVBoxLayout()
        intro.setSpacing(3)
        heading = bind_text(QLabel(), "下载别人整理好的词库")
        heading.setObjectName("termLibraryName")
        intro.addWidget(heading)
        text = bind_text(QLabel(), "先预览再安装；以后线上更新，你改过的词不会被覆盖 · 中国大陆从 GitCode 下载")
        text.setObjectName("termMeta")
        text.setWordWrap(True)
        intro.addWidget(text)
        head.addLayout(intro, 1)
        self.search = QLineEdit()
        self.search.setObjectName("termHubSearch")
        bind_text(self.search, "搜索游戏或词库", property="placeholderText")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self._render)
        head.addWidget(self.search, 0, Qt.AlignmentFlag.AlignBottom)
        self.submit_button = bind_text(QPushButton(), "投稿我的词库")
        self.submit_button.setObjectName("termToolButton")
        self.submit_button.clicked.connect(self.submit)
        head.addWidget(self.submit_button, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(head)

        self.status = _muted("正在获取线上词库…")
        lay.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("termHubScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("termHubGrid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(_CARD_GAP)
        self.grid.setVerticalSpacing(_CARD_GAP)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.grid_host)
        lay.addWidget(self.scroll, 1)
        self.add_card = _AddCard(self)
        foot = QHBoxLayout()
        self.source = _muted("")
        self.source.setObjectName("termHint")
        foot.addWidget(self.source, 1)
        self.refresh_button = bind_text(QPushButton(), "刷新")
        self.refresh_button.setObjectName("termHubLink")
        self.refresh_button.clicked.connect(lambda: self.load(force=True))
        foot.addWidget(self.refresh_button)
        lay.addLayout(foot)
        self.loaded_once = False

    # ---- data

    def load(self, force: bool = False):
        self.loaded_once = True
        self.refresh_button.setEnabled(False)
        bind_text(self.status, "正在获取线上词库…")
        self.status.show()
        _run_async(self, lambda: hub.fetch_catalog(force=force, legacy=self.legacy), self._loaded)

    def _loaded(self, catalog, error):
        self.refresh_button.setEnabled(True)
        if error is not None:
            if self.catalog is None:
                self.entries = []
                self._render()
            if "还没有发布" in str(error):
                bind_text(self.status, "线上词库还没有上线。上线后这里会列出社区词库；现在可以先投稿你的词库。")
            else:
                bind_text(self.status, "获取线上词库失败：{reason}", reason=str(error))
            self.status.show()
            return
        self.catalog = catalog
        self.entries = catalog.entries
        when = __import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(catalog.fetched_at))
        if catalog.stale:
            bind_text(self.source, "离线：显示 {when} 从 {origin} 获取的目录", when=when, origin=catalog.source)
        else:
            bind_text(self.source, "来源：{origin} · 已验证签名 · {when} 获取", origin=catalog.source, when=when)
        self._render()

    def _render(self, *_args):
        subs = hub.subscriptions(self.legacy)
        query = self.search.text().strip().casefold()
        shown = [entry for entry in self.entries if not query or query in
                 f"{entry.get('title', '')} {entry.get('game', '')} {entry.get('id', '')} {entry.get('note', '')}".casefold()]
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = [_HubCard(self, entry) for entry in shown]
        for card in self.cards:
            card.refresh(subs)
        self._columns = 0
        self._place_cards()
        if self.entries and not shown:
            bind_text(self.status, "没有符合“{query}”的词库。", query=self.search.text().strip())
            self.status.show()
        elif not self.entries and self.catalog is not None:
            bind_text(self.status, "线上词库里还没有词库。")
            self.status.show()
        elif self.catalog is not None:
            self.status.hide()
        updates = sum(1 for entry in self.entries if hub.catalog_status(entry, subs) == "update")
        self.counts_changed.emit(len(self.entries), updates)

    def _place_cards(self):
        width = max(self.scroll.viewport().width(), _CARD_WIDTH)
        columns = max(1, (width + _CARD_GAP) // (_CARD_WIDTH + _CARD_GAP))
        if columns == self._columns and self.grid.count() == len(self.cards) + 1:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(max(self.grid.columnCount(), columns)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        widgets = [*self.cards, self.add_card]
        for index, widget in enumerate(widgets):
            self.grid.addWidget(widget, index // columns, index % columns)
            widget.show()
        rows = (len(widgets) + columns - 1) // columns
        for row in range(max(self.grid.rowCount(), rows + 1)):
            self.grid.setRowStretch(row, 1 if row == rows else 0)  # rows stay compact at the top
        if self.cards:
            self.add_card.setFixedHeight(max(card.sizeHint().height() for card in self.cards))

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        QTimer.singleShot(0, self._place_cards)

    def card_for(self, library_id: str) -> "_HubCard | None":
        return next((card for card in self.cards if card.entry.get("id") == library_id), None)

    # ---- actions

    def preview_entry(self, entry: dict):
        card = self.card_for(entry.get("id", ""))
        if card is not None:
            card.primary.setEnabled(False)
        bind_text(self.status, "正在下载《{title}》…", title=entry.get("title") or entry["game"])
        self.status.show()
        catalog = self.catalog
        _run_async(self, lambda: hub.fetch_library(entry, catalog),
                   lambda library, error: self._downloaded(entry, library, error))

    def _downloaded(self, entry, library, error):
        card = self.card_for(entry.get("id", ""))
        if card is not None:
            card.primary.setEnabled(True)
        if error is not None:
            bind_text(self.status, "下载失败：{reason}", reason=str(error))
            return
        self.status.hide()
        plan = hub.plan_install(entry, library, legacy=self.legacy)
        self.preview = PreviewSheet(self.dialog, plan, on_done=self._render)

    def remove_entry(self, entry: dict):
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

    def submit(self):
        open_submit_sheet(self.dialog, choose=True)


def cached_counts(legacy) -> tuple[int, int] | None:
    """(libraries, updates) from the last verified catalog on disk; no network."""
    catalog = hub.cached_catalog(legacy)
    if catalog is None:
        return None
    subs = hub.subscriptions(legacy)
    return len(catalog.entries), sum(1 for entry in catalog.entries if hub.catalog_status(entry, subs) == "update")


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
# Submit (2026-10-18 redesign, plan 2026-10-18-glossary-submit-redesign).
# The user asked "shouldn't I pick my library first and then preview it?"
# after the old sheet silently took the library last selected on 「我的词库」
# and listed 37 identical warning lines.  Now one sheet, three steps: choose a
# library, check what will be uploaded (untick rows; each kind of finding is
# said once), then sign and send.


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


_STEPS = ("选词库", "检查内容", "署名并投稿")

# The short tag a row carries, and the one sentence each kind of finding gets.
_FINDING_TAGS = {
    "short_cjk": "两字", "short_ascii": "短英文", "common_word": "日常词", "expands": "扩写",
    "truncates": "删字", "conflict": "结果冲突", "chain": "原词是正式写法", "filetrans": "超过 15 字",
    "too_long": "超过 40 字", "control": "控制字符", "empty": "空的",
}
_GROUP_TEXT = {
    "short_cjk": "{count} 条两字以内的改字规则（例如“{example}”）会改掉句子里任何位置的这几个字，别的词中间也会被改。",
    "short_ascii": "{count} 条很短的英文改字规则（例如“{example}”）可能改到无关的英文。",
    "common_word": "{count} 条改字规则的原词是日常用词（例如“{example}”），字幕里出现的地方都会被改。",
    "expands": "{count} 条会把原词扩写成更长的名字（例如“{example}”）。",
    "truncates": "{count} 条会删掉原话的一部分（例如“{example}”）。",
    "conflict": "{count} 条：同一个词被改成了不同结果（例如“{example}”），这几条都不会生效。",
    "chain": "{count} 条改字规则的原词是另一条的正式写法（例如“{example}”），识别时会被拒绝。",
    "filetrans": "{count} 条超过 15 个字（例如“{example}”），百炼 Filetrans 会整个失败。",
    "too_long": "{count} 条超过 40 个字（例如“{example}”）。",
    "control": "{count} 条含有控制字符（例如“{example}”）。",
    "empty": "{count} 条的词或改字结果是空的。",
}
_TAG_ROLE = Qt.ItemDataRole.UserRole + 7


def _pair_text(source: str, target: str) -> str:
    return target if source == target else f"{source} → {target}"


def _group_text(group: hub.FindingGroup, groups=()) -> str:
    """One sentence for one kind; the example is a rule no other kind lists, when there is one."""
    others = {key for other in groups if other is not group for key in other.keys}
    example = next((key for key in group.keys if key not in others), group.keys[0] if group.keys else ("", ""))
    return tr(_GROUP_TEXT.get(group.code, "{count} 条：{example}"), count=group.count, example=_pair_text(*example))


def _warn_header(count: int, verified: int) -> str:
    """What every warning means, said once above the kinds."""
    if verified and verified == count:
        return tr("{count} 条改字规则有提醒，照常上传；别人安装时这些规则默认不勾。都是你在实际音频里核对过的，别人可以一键勾上。",
                  count=count)
    if verified:
        return tr("{count} 条改字规则有提醒，照常上传；别人安装时这些规则默认不勾。其中 {verified} 条你在实际音频里核对过，别人可以一键勾上。",
                  count=count, verified=verified)
    return tr("{count} 条改字规则有提醒，照常上传；别人安装时这些规则默认不勾，由他们决定。", count=count)


def _wrapped(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


def _links(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(14)
    for button in buttons:
        row.addWidget(button)
    return row


def _repolish(*widgets) -> None:
    for widget in widgets:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class _StepChip(QFrame):
    """One step of the bar: a numbered dot and its name; done steps go back."""

    clicked = Signal()

    def __init__(self, number: int, text: str):
        super().__init__()
        self.setObjectName("termSubmitStep")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self._digit = str(number)
        self.number = QLabel(self._digit)
        self.number.setObjectName("termSubmitStepNumber")
        self.number.setFixedSize(20, 20)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.number)
        self.label = bind_text(QLabel(), text)
        self.label.setObjectName("termSubmitStepText")
        lay.addWidget(self.label)
        self.state = ""

    def set_state(self, state: str) -> None:
        self.state = state
        self.setProperty("state", state)
        self.number.setText("✓" if state == "done" else self._digit)
        self.setCursor(Qt.CursorShape.PointingHandCursor if state == "done" else Qt.CursorShape.ArrowCursor)
        _repolish(self, self.number, self.label)

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if self.state == "done" and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _LibraryChoice(QFrame):
    """A personal library in step 1: its name, how many words it would send."""

    def __init__(self, library: hub.SubmittableLibrary, current: bool, group: QButtonGroup):
        super().__init__()
        self.setObjectName("termSubmitLibrary")
        self.library = library
        lay = QGridLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(1)
        self.radio = user_text(QRadioButton(library.game))
        self.radio.setObjectName("termSubmitLibraryName")
        group.addButton(self.radio)
        lay.addWidget(self.radio, 0, 0)
        lay.setColumnStretch(0, 1)
        if current or library.hub_title:
            pill = bind_text(QLabel(), "当前打开" if current else "线上安装")
            pill.setObjectName("termSubmitPill" if current else "termSubmitPillQuiet")
            lay.addWidget(pill, 0, 1, Qt.AlignmentFlag.AlignRight)
        if not library.rows:
            meta = bind_text(QLabel(), "还没有确认过的词")
        elif library.hub_title:
            meta = bind_text(QLabel(), "{rows} 个词 · 装自线上《{title}》，投稿会作为它的新版本",
                             rows=library.rows, title=library.hub_title)
        else:
            meta = bind_text(QLabel(), "{rows} 个词 · 改字规则 {aliases}", rows=library.rows, aliases=library.aliases)
        meta.setObjectName("termSubmitLibraryMeta")
        meta.setContentsMargins(24, 0, 0, 0)
        meta.setWordWrap(True)
        lay.addWidget(meta, 1, 0, 1, 2)
        available = library.rows > 0
        self.radio.setEnabled(available)
        self.setProperty("available", available)
        self.setCursor(Qt.CursorShape.PointingHandCursor if available else Qt.CursorShape.ArrowCursor)
        self.radio.toggled.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        self.setProperty("selected", self.radio.isChecked())
        _repolish(self)

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if self.radio.isEnabled():
            self.radio.setChecked(True)
        super().mousePressEvent(event)


class _TagDelegate(QStyledItemDelegate):
    """Small rounded tags (两字 · 核对过 · 结果冲突) in the last column."""

    def _font(self, option) -> QFont:
        font = QFont(option.font)
        if font.pixelSize() > 0:
            font.setPixelSize(max(10, round(font.pixelSize() * 0.85)))
        else:
            font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        return font

    @staticmethod
    def _tags(index) -> list:
        return index.data(_TAG_ROLE) or []

    def paint(self, painter, option, index):
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        item.text = ""
        style = item.widget.style() if item.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, item.widget)
        tags = self._tags(index)
        if not tags:
            return
        theme = _theme()
        colors = {"warn": (theme.warning_soft, theme.warning), "ok": (theme.selected, theme.success),
                  "bad": (theme.danger_soft, theme.danger), "plain": ("", theme.text_muted)}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font(item)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        height = metrics.height() + 4
        x, y = item.rect.left() + 6, item.rect.center().y() - height // 2 + 1
        for text, kind in tags:
            width = metrics.horizontalAdvance(text) + 12
            fill, ink = colors.get(kind, colors["plain"])
            rect = QRect(x, y, width, height)
            if fill:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(fill))
                painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(ink))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
            x += width + 4
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802 - Qt API
        base = super().sizeHint(option, index)
        metrics = QFontMetrics(self._font(option))
        width = sum(metrics.horizontalAdvance(text) + 16 for text, _kind in self._tags(index)) + 12
        return QSize(max(base.width(), width), base.height())


class _ReviewRow:
    """One row of step 2: what would be sent, its findings, its tick."""

    def __init__(self, row: dict, findings: list, check: QTableWidgetItem):
        self.row, self.findings, self.check = row, findings, check
        self.key = hub.row_key(row)
        self.pair = (row["from"], row["to"])
        self.alias = row["from"] != row["to"]
        self.blocked = any(item.level == BLOCK for item in findings)
        self.warned = bool(findings)

    @property
    def ticked(self) -> bool:
        return self.check.checkState() == Qt.CheckState.Checked


class SubmitSheet:
    """「投稿到线上词库」: choose a library → check its content → sign and send."""

    def __init__(self, dialog, library_key: str = "", *, start_at_review: bool = False):
        self.dialog = dialog
        self.libraries = self._ordered_libraries()
        self.library: hub.SubmittableLibrary | None = None
        self.current_key = library_key
        self.loaded_key = ""
        self.rows: list[_ReviewRow] = []
        self.groups: list[hub.FindingGroup] = []
        self._bulk = False
        self._filter: object = "all"
        self._block_timer = QTimer()
        self._block_timer.setSingleShot(True)
        self._block_timer.setInterval(60)
        self._block_timer.timeout.connect(self._check_blocks)
        self.live_blocks: list = []

        self.sheet = _Sheet(dialog, "termHubSubmitSheet", 880, 690)
        lay = self.sheet.layout
        lay.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("termSubmitTitle")
        lay.addWidget(self.title)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.step_chips = []
        for number, text in enumerate(_STEPS, 1):
            if number > 1:
                line = QFrame()
                line.setObjectName("termSubmitStepLine")
                line.setFixedSize(18, 1)
                bar.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
            chip = _StepChip(number, text)
            chip.clicked.connect(lambda step=number - 1: self.go(step))
            bar.addWidget(chip)
            self.step_chips.append(chip)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("termSubmitStack")
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_choose())
        self.stack.addWidget(self._build_review())
        self.stack.addWidget(self._build_sign())

        start = next((item for item in self.libraries if item.key == library_key and item.rows), None)
        if start is not None:
            self.library_buttons[start.key].setChecked(True)
        self.sheet.show()
        self.go(1 if start_at_review and start is not None else 0)

    # ---- data

    def _ordered_libraries(self) -> list[hub.SubmittableLibrary]:
        """The personal libraries in the sidebar's order; hidden ones stay out."""
        libraries = hub.submittable_libraries(self.dialog.legacy)
        by_key = {item.key: item for item in libraries}
        ordered, seen = [], set()
        game_list = getattr(self.dialog, "game_list", None)
        for index in range(game_list.count() if game_list is not None else 0):
            item = game_list.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            key = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            if key not in by_key and name:
                key = self.dialog._library_key(name)
            if key in by_key and key not in seen:
                ordered.append(by_key[key])
                seen.add(key)
        hidden = getattr(self.dialog.legacy, "is_runtime_game_profile_hidden", lambda _name: False)
        ordered += [item for item in libraries if item.key not in seen and not hidden(item.game)]
        return ordered

    def excluded_keys(self) -> set[str]:
        return {item.key for item in self.rows if not item.ticked}

    def ticked_rows(self) -> list[_ReviewRow]:
        return [item for item in self.rows if item.ticked]

    # ---- step 1: choose a library

    def _build_choose(self) -> QWidget:
        page = QWidget()
        page.setObjectName("termSubmitPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_muted("选一个你自己整理的词库。只有确认过的词会上传。"))
        scroll = QScrollArea()
        scroll.setObjectName("termHubScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        host.setObjectName("termHubGrid")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(6)
        self.library_group = QButtonGroup(page)
        self.library_group.setExclusive(True)
        self.library_buttons: dict[str, QRadioButton] = {}
        self.library_choices: list[_LibraryChoice] = []
        for library in self.libraries:
            choice = _LibraryChoice(library, library.key == self.current_key, self.library_group)
            column.addWidget(choice)
            self.library_buttons[library.key] = choice.radio
            self.library_choices.append(choice)
        if not self.libraries:
            column.addWidget(_muted("你还没有自己的词库。先在「我的词库」里新建一个、确认一些词，再来投稿。"))
        column.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = _flat_button("取消")
        cancel.clicked.connect(self.sheet.close)
        self.choose_next = _flat_button("下一步：检查内容", "termHubActionStrong")
        self.choose_next.clicked.connect(lambda: self.go(1))
        foot.addWidget(cancel)
        foot.addWidget(self.choose_next)
        lay.addLayout(foot)
        self.library_group.buttonToggled.connect(lambda *_: self.choose_next.setEnabled(self._chosen() is not None))
        self.choose_next.setEnabled(False)
        return page

    def _chosen(self) -> hub.SubmittableLibrary | None:
        return next((item for item in self.libraries if self.library_buttons[item.key].isChecked()), None)

    # ---- step 2: check the content

    def _build_review(self) -> QWidget:
        page = QWidget()
        page.setObjectName("termSubmitPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        self.summary = QLabel()
        self.summary.setObjectName("termSubmitText")
        lay.addWidget(self.summary)
        self.privacy = _muted("只上传词、改字结果和分类；理由、来源、任务编号和日期留在你的电脑上。")
        lay.addWidget(self.privacy)
        self.notice_host = QVBoxLayout()
        self.notice_host.setSpacing(6)
        lay.addLayout(self.notice_host)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_group = QButtonGroup(page)
        self.chip_group.setExclusive(True)
        self.chips: dict[str, QPushButton] = {}
        for name in ("all", "alias", "hotword", "warned", "excluded"):
            chip = QPushButton()
            chip.setObjectName("termSubmitChip")
            chip.setCheckable(True)
            chip.clicked.connect(lambda _checked=False, name=name: self._set_filter(name))
            self.chip_group.addButton(chip)
            chips.addWidget(chip)
            self.chips[name] = chip
        chips.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("termHubSearch")
        bind_text(self.search, "搜索词", property="placeholderText")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._apply_filter)
        chips.addWidget(self.search)
        lay.addLayout(chips)
        self.table = _table(["上传", "词", "分类", "标记"])
        self.table.setObjectName("termSubmitTable")
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(3, _TagDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setHighlightSections(False)
        self.table.itemChanged.connect(self._ticked)
        lay.addWidget(self.table, 1)
        self.review_status = QLabel()
        self.review_status.setObjectName("termSubmitStatus")
        self.review_status.setWordWrap(True)
        self.review_status.hide()
        lay.addWidget(self.review_status)
        foot = QHBoxLayout()
        back = _flat_button("上一步")
        back.clicked.connect(lambda: self.go(0))
        foot.addWidget(back)
        foot.addStretch(1)
        cancel = _flat_button("取消")
        cancel.clicked.connect(self.sheet.close)
        self.review_next = _flat_button("下一步：署名", "termHubActionStrong")
        self.review_next.clicked.connect(lambda: self.go(2))
        foot.addWidget(cancel)
        foot.addWidget(self.review_next)
        lay.addLayout(foot)
        return page

    def _load_review(self, library: hub.SubmittableLibrary) -> bool:
        try:
            document, findings = hub.build_submission(library.key, legacy=self.dialog.legacy)
        except hub.HubError as exc:
            self.dialog._show_toast(str(exc), 3500)
            return False
        self.loaded_key = library.key
        rows = document["mappings"]
        grouped = findings_by_row(findings)
        self.groups = hub.group_findings(findings, rows)

        def rank(row):
            found = grouped.get((row["from"], row["to"]), [])
            if any(item.level == BLOCK for item in found):
                return 0
            return 1 if found else (2 if row["from"] != row["to"] else 3)

        from .main_ui_glossary import _reference_category_label
        ordered = sorted(rows, key=rank)
        self._bulk = True
        self.table.setRowCount(len(ordered))
        self.rows = []
        for index, row in enumerate(ordered):
            found = grouped.get((row["from"], row["to"]), [])
            check = QTableWidgetItem("")
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item = _ReviewRow(row, found, check)
            check.setCheckState(Qt.CheckState.Unchecked if item.blocked else Qt.CheckState.Checked)
            tags = [(tr(_FINDING_TAGS.get(code, code)), "bad" if level == BLOCK else "warn")
                    for level, code in dict.fromkeys((finding.level, finding.code) for finding in found)]
            if row.get("verified_audio"):
                tags.append((tr("核对过"), "ok"))
            if not item.alias:
                tags.append((tr("热词"), "plain"))
            notes = [tr(finding.message) for finding in found]
            if row.get("verified_audio"):
                notes.append(tr("你在实际音频里核对过"))
            if not item.alias:
                notes.append(tr("热词：只帮识别写对，不改字"))
            marks = QTableWidgetItem("")
            marks.setFlags(Qt.ItemFlag.ItemIsEnabled)
            marks.setData(_TAG_ROLE, tags)
            marks.setToolTip("；".join(dict.fromkeys(notes)))
            category = _reference_category_label(row.get("category", ""))
            for column, cell in enumerate((check, _item(_pair_text(*item.pair)), _item(category), marks)):
                self.table.setItem(index, column, cell)
            self.rows.append(item)
        self._bulk = False
        self._build_notices(library)
        self.search.clear()
        self._set_filter("all")
        self._check_blocks()
        return True

    def _build_notices(self, library: hub.SubmittableLibrary):
        while self.notice_host.count():
            widget = self.notice_host.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.notices: list[tuple[hub.FindingGroup, QPushButton, QPushButton | None]] = []
        extra = []
        if library.unconfirmed:
            extra.append(tr("另有 {count} 条还没确认，不会上传。", count=library.unconfirmed))
        if library.hub_title:
            extra.append(tr("这个词库装自线上《{title}》：投稿会作为它的新版本，审核通过后线上换成你这一份；没勾的词不在新版本里。",
                            title=library.hub_title))
        self.privacy.setText(" ".join([tr("只上传词、改字结果和分类；理由、来源、任务编号和日期留在你的电脑上。"), *extra]))
        # One card per level: a first sentence that says what it means and
        # what happens, then one line per kind with its own links.
        blocks = [group for group in self.groups if group.level == BLOCK]
        if blocks:
            keys = {key for group in blocks for key in group.keys}
            grid = self._notice_card("block")
            grid.addWidget(_wrapped(tr("{count} 条必须处理，已先设为不上传；也可以回词库改好再投稿。", count=len(keys)),
                                    "termSubmitNoticeText"), 0, 1)
            fix = _flat_button("回词库修改", "termSubmitLink")
            fix.clicked.connect(lambda: self._edit_in_library(self.loaded_key))
            grid.addLayout(_links(fix), 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            for line, group in enumerate(blocks, 1):
                show = self._show_link(group)
                self._kind_line(grid, line, group, show)
                self.notices.append((group, show, None))
        warns = [group for group in self.groups if group.level != BLOCK]
        if warns:
            keys = {key for group in warns for key in group.keys}
            verified = sum(1 for item in self.rows if item.pair in keys and item.row.get("verified_audio"))
            grid = self._notice_card("warn")
            grid.addWidget(_wrapped(_warn_header(len(keys), verified), "termSubmitNoticeText"), 0, 1, 1, 2)
            for line, group in enumerate(warns, 1):
                show = self._show_link(group)
                bulk = _flat_button("", "termSubmitLink")
                bulk.clicked.connect(lambda _checked=False, group=group: self._toggle_group_upload(group))
                self._kind_line(grid, line, group, show, bulk)
                self.notices.append((group, show, bulk))

    def _kind_line(self, grid: QGridLayout, line: int, group: hub.FindingGroup, *links):
        grid.addWidget(_wrapped("· " + _group_text(group, self.groups), "termSubmitNoticeMore"), line, 1)
        grid.addLayout(_links(*links), line, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

    def _notice_card(self, level: str) -> QGridLayout:
        frame = QFrame()
        frame.setObjectName("termSubmitNotice")
        frame.setProperty("level", level)
        grid = QGridLayout(frame)
        grid.setContentsMargins(11, 9, 12, 9)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(4)
        icon = QLabel("×" if level == "block" else "!")
        icon.setObjectName("termSubmitNoticeIcon")
        icon.setFixedSize(18, 18)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(icon, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(1, 1)
        self.notice_host.addWidget(frame)
        return grid

    def _show_link(self, group: hub.FindingGroup) -> QPushButton:
        show = _flat_button("", "termSubmitLink")
        show.clicked.connect(lambda _checked=False, group=group: self._toggle_group_filter(group))
        return show

    def _group_rows(self, group: hub.FindingGroup) -> list[_ReviewRow]:
        keys = set(group.keys)
        return [item for item in self.rows if item.pair in keys]

    def _toggle_group_filter(self, group: hub.FindingGroup):
        if self._filter == ("group", group.code):
            self._set_filter("all")
        else:
            self._filter = ("group", group.code)
            self.chip_group.setExclusive(False)    # an exclusive group cannot be all unchecked
            for chip in self.chips.values():
                chip.setChecked(False)
            self.chip_group.setExclusive(True)
            self._apply_filter()
            self._refresh_counts()

    def _toggle_group_upload(self, group: hub.FindingGroup):
        rows = self._group_rows(group)
        state = Qt.CheckState.Checked if all(not item.ticked for item in rows) else Qt.CheckState.Unchecked
        self._bulk = True
        for item in rows:
            item.check.setCheckState(state)
        self._bulk = False
        self._ticked()

    def _set_filter(self, name: str):
        self._filter = name
        self.chips[name].setChecked(True)
        self._apply_filter()
        self._refresh_counts()

    def _visible(self, item: _ReviewRow, query: str) -> bool:
        mode = self._filter
        if isinstance(mode, tuple):
            group = next((group for group in self.groups if group.code == mode[1]), None)
            shown = group is not None and item.pair in set(group.keys)
        else:
            shown = {"all": True, "alias": item.alias, "hotword": not item.alias, "warned": item.warned,
                     "excluded": not item.ticked}[mode]
        return shown and (not query or query in f"{item.row['from']} {item.row['to']}".casefold())

    def _apply_filter(self, *_):
        query = self.search.text().strip().casefold()
        for index, item in enumerate(self.rows):
            self.table.setRowHidden(index, not self._visible(item, query))

    def _ticked(self, cell=None):
        if self._bulk or (cell is not None and cell.column() != 0):
            return
        self._refresh_counts()
        if self._filter == "excluded":
            self._apply_filter()
        self._block_timer.start()

    def _refresh_counts(self):
        ticked = self.ticked_rows()
        aliases = sum(1 for item in ticked if item.alias)
        excluded = len(self.rows) - len(ticked)
        text = tr("会上传 {count} 个词 · 热词 {hotwords} · 改字规则 {aliases}",
                  count=len(ticked), hotwords=len(ticked) - aliases, aliases=aliases)
        if excluded:
            text = tr("{summary} · 不上传 {count}", summary=text, count=excluded)
        self.summary.setText(text)
        counts = {"all": len(self.rows), "alias": sum(1 for item in self.rows if item.alias),
                  "hotword": sum(1 for item in self.rows if not item.alias),
                  "warned": sum(1 for item in self.rows if item.warned), "excluded": excluded}
        labels = {"all": "全部 {count}", "alias": "改字规则 {count}", "hotword": "热词 {count}",
                  "warned": "有提醒 {count}", "excluded": "不上传 {count}"}
        for name, chip in self.chips.items():
            bind_text(chip, labels[name], count=counts[name])
        self.chips["warned"].setVisible(counts["warned"] > 0)
        for group, show, bulk in getattr(self, "notices", []):
            filtered = self._filter == ("group", group.code)
            bind_text(show, "显示全部" if filtered else "只看这 {count} 条", count=group.count)
            if bulk is not None:
                rows = self._group_rows(group)
                bind_text(bulk, "都上传" if rows and all(not item.ticked for item in rows) else "都不上传")

    def _check_blocks(self):
        """Blocking findings among the ticked rows only: unticking one of two
        conflicting rules makes the other one fine."""
        ticked = self.ticked_rows()
        self.live_blocks = blocking(lint_rows([item.row for item in ticked])) if ticked else []
        if not ticked:
            bind_text(self.review_status, "至少勾一个词才能投稿。")
        elif self.live_blocks:
            keys = {finding.key for finding in self.live_blocks}
            bind_text(self.review_status, "勾着的 {count} 条还有必须处理的问题（{reason}），取消勾选或回词库改好后才能继续。",
                      count=len(keys), reason=tr(self.live_blocks[0].message))
        self.review_status.setVisible(not ticked or bool(self.live_blocks))
        self.review_next.setEnabled(bool(ticked) and not self.live_blocks)

    def _edit_in_library(self, library_key: str):
        self.sheet.close()
        dialog = self.dialog
        if callable(getattr(dialog, "show_page", None)):
            dialog.show_page("mine")
        game_list = getattr(dialog, "game_list", None)
        for index in range(game_list.count() if game_list is not None else 0):
            item = game_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole + 1) or "") == library_key:
                game_list.setCurrentItem(item)
                break

    # ---- step 3: sign and send

    def _build_sign(self) -> QWidget:
        page = QWidget()
        page.setObjectName("termSubmitPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)
        box = QFrame()
        box.setObjectName("termSubmitSummary")
        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(14, 10, 14, 10)
        box_lay.setSpacing(3)
        self.sign_title = QLabel()
        self.sign_title.setObjectName("termSubmitSummaryTitle")
        box_lay.addWidget(self.sign_title)
        self.sign_detail = _muted("")
        box_lay.addWidget(self.sign_detail)
        lay.addWidget(box)
        self.author = QLineEdit()
        self.author.setObjectName("termSubmitField")
        bind_text(self.author, "署名（昵称，可以留空）", property="placeholderText")
        lay.addWidget(self.author)
        self.note = QPlainTextEdit()
        self.note.setObjectName("termSubmitField")
        bind_text(self.note, "给审核者的说明（可以留空），例如：这些误听来自哪些直播", property="placeholderText")
        self.note.setFixedHeight(84)
        lay.addWidget(self.note)
        self.consent = bind_text(QCheckBox(), "我同意以 CC0 公开这些词（任何人都可以自由使用）")
        self.consent.setObjectName("termSubmitConsent")
        lay.addWidget(self.consent)
        lay.addWidget(_muted("投稿时先把文件存到「下载」文件夹，再打开投稿页；标题和说明已经复制好，把文件拖进投稿页即可。"
                             "中国大陆用 GitCode 更快。"))
        lay.addStretch(1)
        foot = QHBoxLayout()
        back = _flat_button("上一步")
        back.clicked.connect(lambda: self.go(1))
        foot.addWidget(back)
        foot.addStretch(1)
        export = _flat_button("只导出文件", "termHubAction")
        export.clicked.connect(lambda: self._send(""))
        github = _flat_button("用 GitHub 投稿", "termHubAction")
        github.clicked.connect(lambda: self._send("github"))
        gitcode = _flat_button("用 GitCode 投稿", "termHubActionStrong")
        gitcode.clicked.connect(lambda: self._send("gitcode"))
        for widget in (export, github, gitcode):
            foot.addWidget(widget)
        lay.addLayout(foot)
        self.export_button, self.github_button, self.gitcode_button = export, github, gitcode
        self.send_buttons = (export, github, gitcode)
        self.consent.toggled.connect(self._sync_send)
        self._sync_send()
        return page

    def _fill_sign(self):
        library = self.library
        ticked = self.ticked_rows()
        aliases = sum(1 for item in ticked if item.alias)
        self.sign_title.setText(tr("《{game}》 · {count} 个词", game=library.game, count=len(ticked)))
        parts = [tr("热词 {hotwords} · 改字规则 {aliases}", hotwords=len(ticked) - aliases, aliases=aliases)]
        warned = sum(1 for item in ticked if item.warned)
        if warned:
            parts.append(tr("其中 {count} 条有提醒，别人安装时默认不勾", count=warned))
        excluded = len(self.rows) - len(ticked)
        if excluded:
            parts.append(tr("你去掉了 {count} 条", count=excluded))
        if library.hub_title:
            parts.append(tr("审核通过后，线上《{title}》会换成这一份", title=library.hub_title))
        self.sign_detail.setText("；".join(parts))
        self._sync_send()

    def _sync_send(self, *_):
        allowed = self.consent.isChecked() and bool(self.ticked_rows()) and not self.live_blocks
        for button in self.send_buttons:
            button.setEnabled(allowed)

    def _send(self, provider: str):
        document, findings = hub.build_submission(
            self.library.key, author=self.author.text(), note=self.note.toPlainText(), legacy=self.dialog.legacy,
            app_version=_app_version(), excluded=self.excluded_keys())
        if not document["mappings"] or any(item.level == BLOCK for item in findings):
            self.dialog._show_toast(tr("勾着的词还有必须处理的问题，没有导出。"), 4000)
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
        hub.mark_share_prompt_done(self.library.key, legacy=self.dialog.legacy)
        self.sheet.close()
        self.dialog._show_toast(message, 6000)

    # ---- navigation

    def go(self, step: int):
        if step >= 1:
            chosen = self._chosen()
            if chosen is None:
                step = 0
            elif chosen.key != self.loaded_key:
                if not self._load_review(chosen):
                    step = 0
            self.library = chosen if step >= 1 else self.library
        if step == 2:
            self._block_timer.stop()
            self._check_blocks()
            if not self.ticked_rows() or self.live_blocks:
                step = 1
            else:
                self._fill_sign()
        self.stack.setCurrentIndex(step)
        if step == 0:
            bind_text(self.title, "投稿到线上词库")
        elif step == 1:
            bind_text(self.title, "检查《{game}》要上传的内容", game=self.library.game)
        else:
            bind_text(self.title, "署名并投稿")
        for index, chip in enumerate(self.step_chips):
            reachable = index < step
            chip.set_state("on" if index == step else ("done" if reachable else "todo"))
        self.step = step


def _flat_button(text: str, name: str = "termHubQuiet") -> QPushButton:
    button = bind_text(QPushButton(), text) if text else QPushButton()
    button.setObjectName(name)
    return button


def _app_version() -> str:
    try:
        from .updater import current_version
        return current_version()
    except Exception:  # noqa: BLE001 - the version is informative only
        return ""


# --------------------------------------------------------------------------
# Entry points used by TermLibraryDialog


def open_submit_sheet(dialog, choose: bool | None = None) -> None:
    """Open the submit sheet.  ``choose=True`` starts at 「选词库」 (the hub
    page's buttons); ``False`` opens the current library's content (the share
    button beside a library's title).  ``None`` decides by the page in view."""
    if choose is None:
        stack = getattr(dialog, "page_stack", None)
        choose = stack is not None and stack.currentWidget() is getattr(dialog, "hub_page", None)
    game = dialog.state.get("game", "")
    library_key = (dialog.state.get("library_id") or dialog._library_key(game)) if game else ""
    games = dialog.legacy.load_learned_term_payload().get("games") or {}
    if library_key not in games:
        library_key = ""
    try:
        dialog._hub_submit = SubmitSheet(dialog, library_key, start_at_review=not choose and bool(library_key))
    except hub.HubError as exc:
        dialog._show_toast(str(exc), 3500)
