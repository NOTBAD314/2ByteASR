"""Term library page of the main window and the glossary picker.

``TermLibraryPage`` hosts ``main_ui_glossary.TermLibraryDialog`` as a main-window
page; ``GlossaryPickerDialog`` chooses which glossaries a run uses.
Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports these names.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
    QWidget,
)

from ..app.main_ui_helpers import _active_theme_definition
from ..design.ui_navigation import NAVIGATION_QSS
from ..design.ui_theme import GREEN, MUTED
from ..design.ui_widgets import AnimatedButton
from ..i18n import apply_ui_language, bind_text, current_language
from .main_ui_glossary import TermLibraryDialog

if TYPE_CHECKING:
    from ..app.ui import MainWindow


class GlossaryPickerDialog(QWidget):
    """本批词库多选器（hosted inside ModalHost）。

    No top-level native window. Host provides title/X/backdrop/Esc.
    Content shows at final size immediately; only backdrop fades.
    """

    def __init__(self, owner: "MainWindow", container: QWidget | None = None):
        parent = container if container is not None else owner
        super().__init__(parent)
        self.owner = owner
        self.legacy = owner.legacy
        self._selected: set[str] = set(owner._enabled_glossary_ids())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        hint = QLabel("本批字幕同时使用选中的词库；关闭一个不会影响其它词库。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        bind_text(self.search, '搜索词库…', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("glossaryPickerList")
        layout.addWidget(self.list_widget, 1)
        self.select_all = AnimatedButton("全选")
        self.select_all.setObjectName("flat")
        self.select_all.clicked.connect(self._toggle_select_all)
        layout.addWidget(self.select_all, 0, Qt.AlignmentFlag.AlignRight)
        actions = QHBoxLayout()
        actions.addStretch(1)
        save_button = AnimatedButton("确定")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._accept_choice)
        actions.addWidget(save_button)
        close_button = AnimatedButton("取消")
        close_button.setObjectName("outline")
        close_button.clicked.connect(self._cancel_choice)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self._result = None
        self._populate()

    def _accept_choice(self):
        self._result = self.selected_ids()
        # Notify host to close (if hosted) or do nothing if used directly.
        mw = self._find_main_window()
        if mw and hasattr(mw, "_modal_host") and mw._modal_host.isVisible():
            mw._modal_host._request_close()
        else:
            # Fallback if somehow not hosted: try to close parent dialog if any.
            p = self.parentWidget()
            while p and not isinstance(p, QDialog):
                p = p.parentWidget()
            if p:
                p.accept()
            else:
                self.hide()

    def _cancel_choice(self):
        self._result = None
        mw = self._find_main_window()
        if mw and hasattr(mw, "_modal_host") and mw._modal_host.isVisible():
            mw._modal_host._request_close()
        else:
            p = self.parentWidget()
            while p and not isinstance(p, QDialog):
                p = p.parentWidget()
            if p:
                p.reject()
            else:
                self.hide()

    def _find_main_window(self):
        p = self.parentWidget()
        while p:
            if hasattr(p, "_modal_host"):
                return p
            p = p.parentWidget()
        return None

    def selected_ids(self) -> list[str]:
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return list(dict.fromkeys(result))

    def take_result(self):
        r = self._result
        self._result = None
        return r

    # Keep the rest of the behavior identical.

    def _available_entries(self) -> list[tuple[str, str]]:
        """(display_name, identity) 可用词库：profiles + learned + history。"""
        catalog = getattr(self.legacy, "glossary_catalog", None)
        if callable(catalog):
            return [(str(row["name"]), str(row["id"])) for row in catalog()]
        entries: dict[str, str] = {}
        profiles = getattr(self.legacy, "load_game_profiles", lambda: {})() or {}
        for name in profiles:
            entries[self.legacy.runtime_game_identity(name)] = str(name)
        learned = getattr(self.legacy, "load_learned_term_payload", lambda: {"games": {}})()
        for _key, entry in (learned or {}).get("games", {}).items():
            if isinstance(entry, dict):
                name = str(entry.get("game", ""))
                if name:
                    entries.setdefault(self.legacy.runtime_game_identity(name), name)
        return [(name, identity) for identity, name in entries.items()]

    def _populate(self):
        self.list_widget.clear()
        for name, identity in self._available_entries():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, identity)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if identity in self._selected else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(item)

    def _apply_filter(self, text=""):
        query = text.strip().casefold()
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def _toggle_select_all(self):
        all_checked = all(
            self.list_widget.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.list_widget.count())
        )
        state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)


TERM_LIBRARY_PAGE_QSS = NAVIGATION_QSS + f"""
QWidget#termLibraryPage {{
    background: transparent;
}}
QFrame#recognitionRoleCard[density="compact"] QLabel#recognitionModelName {{ font-size: 18px; }}
QFrame#recognitionRoleCard[density="large"] QLabel#recognitionModelName {{ font-size: 22px; }}
QFrame#termWorkspaceSidebar {{
    background: #f4f1ea;
    border: 1px solid #ded7ca;
    border-radius: 12px;
}}
QLabel#termWorkspaceLabel {{
    color: {MUTED};
    font-weight: 600;
}}
QLabel#termSyncStatus {{
    color: {GREEN};
    font-size: 12px;
}}
"""


def build_term_library_page_qss(theme=None) -> str:
    from twobyteasr.design.qss_retheme import retheme_qss

    from twobyteasr.design.semantic_qss import build_semantic_qss
    active = theme or _active_theme_definition()
    return retheme_qss(TERM_LIBRARY_PAGE_QSS, active) + build_semantic_qss(active)


class TermLibraryPage(QWidget):
    """Resident workbench shell around the existing high-performance library."""

    recognition_requested = Signal()
    workshop_requested = Signal()
    history_requested = Signal()

    def __init__(self, owner: "MainWindow", parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.setObjectName("termLibraryPage")
        self.setStyleSheet(build_term_library_page_qss())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        from twobyteasr.design.ui_navigation import WorkspaceSidebar
        sidebar = WorkspaceSidebar("terms", object_name="termWorkspaceSidebar")
        side = sidebar.body
        self.workspace_navigation = sidebar.navigation
        self.workspace_navigation.recognition_requested.connect(self.recognition_requested)
        self.workspace_navigation.workshop_requested.connect(self.workshop_requested)
        self.workspace_navigation.history_requested.connect(self.history_requested)
        side.addStretch(1)
        sync_status = QLabel("●  官方词库已同步")
        sync_status.setObjectName("termSyncStatus")
        side.addWidget(sync_status)
        outer.addWidget(sidebar)

        self._content_layout = outer
        self.library = None
        self._placeholder = QFrame()
        self._placeholder.setObjectName("termLibraryContent")
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.addStretch(1)
        loading = QLabel("正在载入术语库…")
        loading.setObjectName("muted")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(loading)
        placeholder_layout.addStretch(1)
        outer.addWidget(self._placeholder, 1)

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(build_term_library_page_qss())

    def _ensure_library(self):
        if self.library is not None:
            return self.library
        self.library = TermLibraryDialog(self.owner, self, page_mode=True)
        self.owner._term_library_dialog = self.library
        self._content_layout.replaceWidget(self._placeholder, self.library)
        self._placeholder.hide()
        self.library.show()
        language = getattr(self.owner, "_ui_language", current_language())
        apply_ui_language(self, language)
        self.setProperty("_2b_language_applied", language)
        return self.library

    def prepare_for_show(self):
        self.workspace_navigation.set_active("terms")
        library = self._ensure_library()
        current = library.game_list.currentItem()
        target = library._canonical(library.game_box_text())
        if target:
            target_identity = library._game_identity(target)
            matching = None
            for index in range(library.game_list.count()):
                item = library.game_list.item(index)
                if library._game_identity(
                    item.data(Qt.ItemDataRole.UserRole)
                ) == target_identity:
                    matching = item
                    break
            if matching is None:
                matching = library.add_game_item(target)
            if current is None and matching is not None:
                library.game_list.setCurrentItem(matching)
                return
        if current is None and library.game_list.count():
            library.game_list.setCurrentRow(0)
            return
        QTimer.singleShot(0, library.refresh_current_game)
