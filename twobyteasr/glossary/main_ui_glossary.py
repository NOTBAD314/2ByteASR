"""Term Library presentation widgets and models."""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from copy import deepcopy
from .glossary_write_feedback import glossary_write_errors
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .glossary_learning import GlossaryLearningStore
from .glossary_input import parse_term_line, validate_term_records
from .glossary_term_cards import TermCardView, avatar_style
from ..i18n import current_language, translate
from ..app.main_ui_branding import _icon
from ..app.main_ui_helpers import GUI_PROFILE_ENABLED
from ..design.main_ui_popup import FramelessPopupCombo
from .main_ui_smart_glossary import SmartGlossaryDialog
from ..design.ui_theme import (
    BACKGROUND as IVORY,
    BORDER as LINE,
    GREEN,
    GREEN_SUBTLE,
    MUTED,
    SURFACE,
)
from ..design.ui_widgets import AnimatedButton

from ..i18n import bind_text

from ..i18n import tr
from ..app.lazy_pages import existing_page
from ..design.typography import emphasis_qss


class _SheetDim(QFrame):
    """The layer under an in-page sheet; reports a press outside the sheet."""

    pressed = Signal()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        self.pressed.emit()
        event.accept()


def _sheet_theme():
    """Theme tokens for on-demand sheets/toasts created outside the QSS pipeline."""

    from ..design.theme_manager import theme_definition, theme_key

    return theme_definition(theme_key())


def term_library_game_names(legacy, current_game: str = "") -> list[str]:
    """Build the independent term-library game index in useful display order."""
    canonical = legacy.canonicalize_runtime_game_name
    identity = legacy.runtime_game_identity
    candidates = [canonical(current_game)]
    candidates.extend(getattr(legacy, "BUILTIN_GAME_PROFILES", ()))
    profiles = getattr(legacy, "load_game_profiles", lambda: {})()
    if isinstance(profiles, dict):
        candidates.extend(profiles.keys())
    candidates.extend(legacy.load_runtime_game_history())
    # Read-only: the cached view avoids re-parsing the glossary file per call.
    learned_payload = (
        getattr(legacy, "_learned_term_payload_view", None)
        or getattr(legacy, "load_learned_term_payload", lambda: {"games": {}})
    )()
    learned_games = (
        learned_payload.get("games", {}) if isinstance(learned_payload, dict) else {}
    )
    if isinstance(learned_games, dict):
        for entry in learned_games.values():
            if isinstance(entry, dict):
                candidates.append(entry.get("game", ""))

    result = []
    seen = set()
    for value in candidates:
        game_name = canonical(str(value or ""))
        game_key = identity(game_name)
        hidden = getattr(
            legacy, "is_runtime_game_profile_hidden", lambda _name: False
        )(game_name)
        if game_name and game_key and game_key not in seen and not hidden:
            result.append(game_name)
            seen.add(game_key)
    return result


def preview_term_import(text, existing=(), *, mapping_mode=False):
    """Parse existing quick lines/TSV and JSON without writing any user data."""
    records = []
    raw = str(text or "").strip(' \r\n')
    if raw.startswith(("{", "[")):
        payload = json.loads(raw)
        if isinstance(payload, dict) and 'concepts' in payload:
            raise ValueError('这是完整多语言词库，请点击“导入多语言…”以保留语言状态与概念关联')
        items = payload if isinstance(payload, list) else payload.get("mappings", payload.get("terms", []))
        if isinstance(payload, dict) and isinstance(payload.get("games"), dict):
            items = [row for entry in payload["games"].values() if isinstance(entry, dict) for row in entry.get("mappings", [])]
        for item in items:
            if not isinstance(item, dict):
                continue
            target = str(item.get("to", item.get("canonical", item.get("term", "")))).strip()
            source = str(item.get("from", target)).strip()
            records.append({"from": source, "to": target, "category": str(item.get("category", "其他"))})
            records.extend({"from": str(alias).strip(), "to": target, "category": str(item.get("category", "其他"))} for alias in item.get("aliases", ()) if str(alias).strip())
    else:
        header = None
        for line_number, line in enumerate(raw.splitlines(), 1):
            line = line.strip(' \r')
            if not line or line.startswith(("#", "```")):
                continue
            columns = line.split("\t")
            if columns[0].casefold() in {"term", "canonical", "规范词", "标准词", "术语"}:
                header = columns
                continue
            if header and len(columns) > 1:
                target = columns[0].strip()
                category = columns[1].strip() or "其他"
                records.append({"from": target, "to": target, "category": category})
                if len(columns) > 2:
                    records.extend({"from": alias.strip(), "to": target, "category": category} for alias in __import__("re").split(r"[、,，;；|]+", columns[2]) if alias.strip())
            else:
                parsed = parse_term_line(line, mapping_mode=mapping_mode)
                parsed['line'] = line_number
                records.append(parsed)
    return validate_term_records(records, existing)


class TermGameListRow(QFrame):
    """Two-level glossary nav row: strong name, quiet count."""

    clicked = Signal()
    menu_requested = Signal(object)  # global QPoint of a right click

    def __init__(
        self,
        name: str,
        count: int,
        content_type: str,
        reference_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("termGameRow")
        self.setProperty("selected", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        # 2026-11-03: a first-character badge instead of the hidden book icon.
        self.icon_label = QLabel()
        self.icon_label.setObjectName("termGameAvatar")
        self.icon_label.setFixedSize(30, 30)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        name_line = QHBoxLayout()
        name_line.setSpacing(6)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("termGameRowName")
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)
        self.name_label.setToolTip(name)
        name_line.addWidget(self.name_label, 1)
        self.in_use_label = bind_text(QLabel(), '在用')
        self.in_use_label.setObjectName("termGameInUse")
        bind_text(self.in_use_label, '这一批字幕正在用这个词库', property='toolTip')
        self.in_use_label.hide()
        name_line.addWidget(self.in_use_label)
        self.count_label = QLabel()
        self.count_label.setObjectName("termGameRowCount")
        meta = QHBoxLayout()
        meta.setSpacing(5)
        meta.addWidget(self.count_label)
        meta.addStretch(1)
        text.addLayout(name_line)
        text.addLayout(meta)
        layout.addLayout(text, 1)
        for child in (self.icon_label, self.name_label, self.count_label, self.in_use_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_content(name, count, content_type, reference_count)

    def update_content(
        self, name: str, count: int, content_type: str, reference_count: int = 0
    ):
        self.name_label.setText(name)
        self.name_label.setToolTip(name)
        self.icon_label.setText(str(name or "?")[:1])
        self.icon_label.setStyleSheet(avatar_style(name))
        if count == '…' or reference_count == '…':
            # 2026-11-13 (user): 「… 已确认 · … 参考」 read as cut-off text.
            bind_text(self.count_label, '正在统计…')
            return
        (bind_text(self.count_label, f'{count} confirmed · {reference_count} references') if current_language() == 'en' else bind_text(self.count_label, '{value0} 已确认 · {value1} 参考', value0=count, value1=reference_count))

    def set_in_use(self, in_use: bool):
        self.in_use_label.setVisible(bool(in_use))

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802 - Qt API
        self.menu_requested.emit(event.globalPos())
        event.accept()


# P0-5: Lightweight model + delegate for 650-row term table.
# No per-row QWidget creation (no setCellWidget for chips or action buttons).
# Category is painted; actions handled via clicked -> edit (bulk delete via toolbar).
class _TermMappingsModel(QAbstractTableModel):
    HEADERS = ["术语 / 纠错", "分类", "来源", "状态", "操作"]
    STATUS_LABELS = {
        "confirmed": "已确认",
        "reference": "参考",
        "hidden": "已隐藏",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._language = current_language()

    def set_language(self, language: str):
        language = str(language or "zh")
        if language == self._language:
            return False
        self._language = language
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self.HEADERS) - 1
        )
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.DisplayRole],
            )
        return True

    def set_data(self, items: list[dict], *, prepared=False):
        if items == self._rows:
            return False
        # Background preparation owns these immutable row dictionaries.
        # Ordinary callers keep the existing defensive-copy contract.
        rows = list(items) if prepared else deepcopy(items) if items else []
        old_keys = [row.get('concept_id') or (row.get('target'), row.get('source'), row.get('status')) for row in self._rows]
        new_keys = [row.get('concept_id') or (row.get('target'), row.get('source'), row.get('status')) for row in rows]
        if old_keys == new_keys:
            changed = [i for i, row in enumerate(rows) if row != self._rows[i]]
            self._rows = rows
            self.dataChanged.emit(self.index(changed[0], 0), self.index(changed[-1], self.columnCount() - 1), [])
            return True
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        return True

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return translate(self.HEADERS[section], self._language)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return r.get("term_text", "")
            if col == 1:
                return translate(r.get("category", "其他"), self._language)
            if col == 2:
                return " / ".join(r.get("origin_labels", ()) or ())
            if col == 3:
                status = str(r.get("status", "reference"))
                if self._language == "en":
                    return {
                        "confirmed": "Confirmed",
                        "reference": "Reference",
                        "hidden": "Hidden",
                    }.get(status, status)
                return self.STATUS_LABELS.get(status, status)
            if col == 4:
                actions = r.get("actions", ())
                return "  ".join(actions)
            return ""
        if role == Qt.ItemDataRole.UserRole:
            return r.get("raw", {})
        if role == Qt.ItemDataRole.UserRole + 1:
            return (r.get("source"), r.get("target"))
        if role == Qt.ItemDataRole.UserRole + 2:
            return str(r.get("status", ""))
        if role == Qt.ItemDataRole.ToolTipRole:
            return r.get("tooltip", "")
        if role == Qt.ItemDataRole.ForegroundRole and col in (1, 2, 4):
            theme = _glossary_theme()
            return QColor(theme.text_secondary if col == 1 else theme.text_muted)
        return None

    def data_for_row(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


def _glossary_theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


from ..design.semantic_qss import pill_palette  # noqa: E402


class _CategoryPillDelegate(QStyledItemDelegate):
    """Paint a compact category pill without creating a QWidget per row."""

    def paint(self, painter, option, index):
        painter.save()
        text = str(
            index.data(Qt.ItemDataRole.DisplayRole)
            or translate("其他", current_language())
        )
        theme = _glossary_theme()
        bg, fg, br = (QColor(value) for value in pill_palette(theme)["category"])
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.selected))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme.selected))
        painter.setFont(option.font)
        fm = painter.fontMetrics()
        pill_width = min(option.rect.width() - 12, max(46, fm.horizontalAdvance(text) + 20))
        pill_height = min(22, max(18, option.rect.height() - 8))
        r = QRect(
            option.rect.x() + (option.rect.width() - pill_width) // 2,
            option.rect.y() + (option.rect.height() - pill_height) // 2,
            pill_width,
            pill_height,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(bg)
        painter.setPen(QPen(br, 1))
        painter.drawRoundedRect(r, pill_height // 2, pill_height // 2)
        painter.setPen(fg)
        tw = fm.horizontalAdvance(text)
        tx = r.x() + max(0, (r.width() - tw) // 2)
        ty = r.y() + (r.height() + fm.ascent() - fm.descent()) // 2 - 1
        painter.drawText(tx, ty, text)
        painter.restore()

    def sizeHint(self, option, index):
        text = str(
            index.data(Qt.ItemDataRole.DisplayRole)
            or translate("其他", current_language())
        )
        return QSize(max(72, option.fontMetrics.horizontalAdvance(text) + 32), 34)


class _StatusPillDelegate(QStyledItemDelegate):
    """Compact status pill: confirmed (green), reference (neutral), hidden (muted)."""

    PALETTE = {
        "confirmed": ("#e2efdd", "#43754b", "#c6dcc2"),
        "reference": ("#f3efe6", "#6d6a5f", "#e3dccc"),
        "hidden": ("#eeeae4", "#9a968b", "#ddd8cf"),
    }

    def paint(self, painter, option, index):
        painter.save()
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        status = str(index.data(Qt.ItemDataRole.UserRole + 2) or "reference")
        theme = _glossary_theme()
        palette = pill_palette(theme)
        bg, fg, br = palette.get(status, palette["reference"])
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.selected))
        painter.setFont(option.font)
        fm = painter.fontMetrics()
        pill_width = min(option.rect.width() - 10, max(44, fm.horizontalAdvance(text) + 18))
        pill_height = min(22, max(18, option.rect.height() - 8))
        r = QRect(
            option.rect.x() + (option.rect.width() - pill_width) // 2,
            option.rect.y() + (option.rect.height() - pill_height) // 2,
            pill_width,
            pill_height,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(bg))
        painter.setPen(QPen(QColor(br), 1))
        painter.drawRoundedRect(r, pill_height // 2, pill_height // 2)
        painter.setPen(QColor(fg))
        tw = fm.horizontalAdvance(text)
        tx = r.x() + max(0, (r.width() - tw) // 2)
        ty = r.y() + (r.height() + fm.ascent() - fm.descent()) // 2 - 1
        painter.drawText(tx, ty, text)
        painter.restore()

    def sizeHint(self, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        return QSize(max(56, option.fontMetrics.horizontalAdvance(text) + 26), 34)


# profile / 图鉴文件里的英文分类 key → 中文展示（用户可见层绝不显示内部字段名）。
_REFERENCE_CATEGORY_LABELS = {
    "character": "角色",
    "spirit": "角色",
    "skill": "技能",
    "item": "物品",
    "equipment": "装备",
    "material": "材料",
    "merchandise_name": "周边",
    "merchandise_term": "周边",
    "boss": "Boss",
    "location": "地点",
    "region": "地点",
    "mechanic": "机制",
    "game_mechanic": "机制",
    "game_system": "机制",
    "faction": "阵营",
    "event": "活动",
    "community": "玩家用语",
    "spoken_game_abbreviation": "玩家用语",
    "spoken_skill_abbreviation": "玩家用语",
    "game_term": "游戏术语",
    "game_collocation": "常用搭配",
    "common_collocation": "常用搭配",
    "art_term": "美术术语",
    "term": "术语",
    "currency": "货币",
    "other": "其他",
}


def _reference_category_label(raw: str) -> str:
    key = str(raw or "").strip().casefold()
    return _REFERENCE_CATEGORY_LABELS.get(key, str(raw or "其他").strip() or "其他")


class _DrawerFrame(QFrame):
    """Right-side drawer of 「名称与译名」 (2026-11-13). It takes the height the
    cards have and scrolls inside; its word-wrapped content must not report a
    height-for-width that would make the page taller than the window."""

    def hasHeightForWidth(self):  # noqa: N802 - Qt API
        return False

    def sizeHint(self):  # noqa: N802 - Qt API
        return QSize(self.minimumWidth(), 0)

    def minimumSizeHint(self):  # noqa: N802 - Qt API
        return QSize(self.minimumWidth(), 0)


class TermLibraryDialog(QWidget):
    """术语库与学习记录（C 轮重排）。

    Hosted inside MainWindow ModalHost (no new native top-level window).
    Card chrome (title + X + backdrop + Esc) is provided by the host.
    Dialog card shows at final size immediately; only backdrop fades.
    """

    libraries_changed = Signal()
    _term_rows_prepared = Signal(int, object)
    _batch_summary_ready = Signal(object, object)

    def __init__(
        self,
        owner: "MainWindow",
        container: QWidget | None = None,
        *,
        page_mode: bool = False,
    ):
        parent = container if container is not None else owner
        super().__init__(parent)
        self.setObjectName("termLibraryRoot")
        self.owner = owner
        self.legacy = owner.legacy
        self.page_mode = bool(page_mode)
        self._search_visible = False
        self._builtin_expanded = False
        # No window flags here — we are a content card inside the overlay host.
        # The host provides consistent title/X/backdrop/Esc behavior.

        def canonical(value):
            return self.legacy.canonicalize_runtime_game_name(str(value or ""))

        def game_identity(value):
            resolve = getattr(self.legacy, "resolve_glossary_identity", lambda _value: "")
            return resolve(value) or self.legacy.runtime_game_identity(canonical(value))

        self._canonical = canonical
        self._game_identity = game_identity
        self.state = {"game": "", "library_id": "", "mappings": [], "builtin_names": [], "loaded": []}
        self._task_manager = None
        self._task_manager_wired = False
        self._search_visible = False
        self._builtin_expanded = False
        # P0 perf: in-memory cache so switching between games (e.g. 原神 <-> 异环) is instant after first load.
        # 650 rows should switch in <200ms when cached. We still pay the first load cost once per game.
        self._mappings_cache: dict[str, list] = {}
        self._library_stats_cache: dict[str, dict[str, int]] = {}
        self._building_game_index = True
        self._sidebar_count_cursor = 0
        self._sidebar_counts_timer = QTimer(self)
        self._sidebar_counts_timer.setSingleShot(True)
        self._sidebar_counts_timer.setInterval(100)
        self._sidebar_counts_timer.timeout.connect(self._fill_next_sidebar_count)
        self._confirming_references = False
        self._builtin_cache: dict[str, tuple] = {}
        self._builtin_entry_cache: dict[str, list[dict[str, str]]] = {}
        self._term_rows_cache = None
        self._rows_prepared_async = False
        self._batch_revision = 0
        self._batch_summary_cache = {}
        self._batch_request_key = None
        self._batch_running = False
        self._batch_queued = None
        self._summary_cancel = threading.Event()
        QApplication.instance().aboutToQuit.connect(self._summary_cancel.set)
        self._batch_summary_ready.connect(self._receive_batch_summary)
        self._row_generation = 0
        self._row_build_running = False
        self._row_build_queued = None
        self._row_build_state = None
        self._library_read_stamp = None
        self._library_stamp_observed = False
        self._term_rows_prepared.connect(self._receive_term_rows)
        self._filter_key = None
        self._filter_running = False
        self._filter_pending = False
        self._diagnostics = Counter() if os.environ.get('TWOBYTEASR_GLOSSARY_DIAGNOSTICS') == '1' else None
        self._toolbar_timer = QTimer(self)
        self._toolbar_timer.setSingleShot(True)
        self._toolbar_timer.timeout.connect(self._sync_term_toolbar)
        self._learning_store = GlossaryLearningStore()
        getattr(self.legacy, "migrate_user_verified_profile_terms", lambda: 0)()
        # P0 perf: build skeleton fast; do NOT load per-game mappings/builtins or select synchronously.
        # Heavy work (learned_mappings_for_game + builtin_for_game for 650-term sets) is deferred after show().
        games = term_library_game_names(self.legacy, self.game_box_text())
        profiles = getattr(self.legacy, "load_game_profiles", lambda: {})()
        self.profile_game_ids = {
            game_identity(name)
            for name in profiles
            if game_identity(name)
        }
        self.protected_game_ids = {
            game_identity(name)
            for name, profile in profiles.items()
            if game_identity(name) and (
                bool(profile.get("lexicons"))
                or bool(getattr(
                    self.legacy,
                    "builtin_reference_terms_for_game",
                    lambda _name: [],
                )(name))
            )
        }
        self._build(games)
        from .multilingual_terms_ui import install
        install(self)
        for entry in getattr(self.legacy, "glossary_catalog", lambda: [])():
            self.add_game_item(entry["name"], library_id=entry["id"])
        self.libraries_changed.connect(self._notify_owner_library_changed)
        self._building_game_index = False
        self._sidebar_counts_timer.start()
        # Do not setCurrentRow(0) here — that triggers sync heavy refresh_current_game.
        # After show(), the owner will kick refresh on next tick. If no games, just enable editor focus later.
        if not self.game_list.count():
            # Still allow manual focus on editor for empty state; no heavy load yet.
            QTimer.singleShot(0, lambda: self.term_editor.setFocus() if hasattr(self, "term_editor") else None)

    # ------------------------------------------------------------ helpers

    def game_box_text(self) -> str:
        return self.owner.game_box.currentText()

    def _library_key(self, name=None):
        name = self.state.get("game", "") if name is None else str(name)
        if name == self.state.get("game") and self.state.get("library_id"):
            return str(self.state["library_id"])
        return getattr(self.legacy, "resolve_glossary_identity", lambda _name: "")(name) or name

    def _notify_owner_library_changed(self):
        from .visual_emphasis import refresh_visual_glossary
        refresh_visual_glossary(getattr(self.owner, '_studio_page_instance', None))
        refresh = getattr(self.owner, "_refresh_content_choices", None)
        if callable(refresh):
            refresh()
        self._refresh_batch_bar()

    def _notify_library_changed(self):
        # An explicit mutation signal, never a periodic full-library reload.
        self._mappings_cache.clear()
        self._library_stats_cache.clear()
        self._builtin_cache.clear()
        self._builtin_entry_cache.clear()
        self._term_rows_cache = None
        self._batch_revision += 1
        self._row_generation += 1
        self._row_build_state = None
        self._filter_key = None
        self.libraries_changed.emit()

    def builtin_for_game(self, game_name):
        """(全部参考名, 资料构成, 已隐藏参考名)——统一主列表的数据底座。"""
        if str(self._library_key(game_name)).startswith("library:"):
            return [], [], []
        saved = self.legacy.RUNTIME_GAME_NAME
        self.legacy.RUNTIME_GAME_NAME = game_name
        try:
            names, loaded = self.legacy.load_active_game_lexicon_names(
                include_hidden=True
            )
            profile_terms = getattr(
                self.legacy,
                "builtin_reference_terms_for_game",
                lambda _name, **_kwargs: [],
            )(game_name, include_hidden=True)
            names = list(dict.fromkeys([*names, *profile_terms]))
            if profile_terms:
                loaded = [
                    *loaded,
                    ("profile", len(profile_terms), len(set(profile_terms))),
                ]
            hidden = sorted(
                getattr(
                    self.legacy, "hidden_reference_terms_for_game", lambda _name: set()
                )(game_name)
            )
            return names, loaded, hidden
        finally:
            self.legacy.RUNTIME_GAME_NAME = saved

    def _reference_entries_for_game(self, game_name):
        """内置参考条目（含隐藏标记与 profile 别名/分类），用于统一主列表。"""
        if str(self._library_key(game_name)).startswith('library:'):
            return []
        if game_name in self._builtin_entry_cache:
            return self._builtin_entry_cache[game_name]
        cache = self._builtin_cache.get(game_name, ([], [], []))
        names = set(cache[0])
        hidden = set(cache[2] if len(cache) > 2 else ())
        entries: dict[str, dict] = {}
        saved = self.legacy.RUNTIME_GAME_NAME
        self.legacy.RUNTIME_GAME_NAME = game_name
        try:
            for path in getattr(self.legacy, "active_profile_lexicon_paths", lambda: [])():
                try:
                    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                except (OSError, ValueError, TypeError):
                    continue
                category = _reference_category_label(str(payload.get("category") or "其他"))
                source = str(payload.get("attribution") or Path(path).name)
                for item in payload.get("entries", []):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if name and name in names:
                        entries.setdefault(
                            name,
                            {
                                "name": name,
                                "category": category,
                                "source": source,
                                "aliases": list(item.get('aliases') or []),
                                "hidden": name in hidden,
                            },
                        )
            profiles = getattr(self.legacy, "load_game_profiles", lambda: {})()
            for profile_name, profile in profiles.items():
                if self._game_identity(str(profile.get("identity", profile_name))) != self._game_identity(game_name):
                    continue
                for item in profile.get("terms", []):
                    if not isinstance(item, dict):
                        continue
                    canonical = str(item.get("canonical") or "").strip()
                    if not canonical or canonical not in names:
                        continue
                    entry = entries.setdefault(
                        canonical,
                        {
                            "name": canonical,
                            "category": "其他",
                            "source": "内置资料",
                            "aliases": [],
                            "hidden": canonical in hidden,
                        },
                    )
                    category = _reference_category_label(str(item.get("category") or ""))
                    if category and category != "其他":
                        entry["category"] = category
                    for alias in item.get("aliases", []):
                        alias = str(alias or "").strip()
                        if alias and alias != canonical and alias not in entry["aliases"]:
                            entry["aliases"].append(alias)
                break
        finally:
            self.legacy.RUNTIME_GAME_NAME = saved
        for name in names:
            entries.setdefault(
                name,
                {
                    "name": name,
                    "category": "其他",
                    "source": "内置资料",
                    "aliases": [],
                    "hidden": name in hidden,
                },
            )
        result = sorted(entries.values(), key=lambda entry: entry["name"])
        self._builtin_entry_cache[game_name] = result
        return result

    @staticmethod
    def parse_term(value):
        parsed = parse_term_line(value)
        return parsed['from'], parsed['to']

    def _parsed_quick_terms(self):
        source, canonical = self.parse_term(self.term_editor.text().strip())
        aliases = [alias.strip() for alias in __import__("re").split(r"[、,，;；\n]+", self.term_alias_editor.text()) if alias.strip()]
        if source and source != canonical:
            aliases.insert(0, source)
        return canonical, list(dict.fromkeys(aliases))

    def _refresh_term_parse_preview(self, *_args):
        canonical, aliases = self._parsed_quick_terms()
        if canonical or aliases:
            if not getattr(self, '_quick_draft_library_id', ''):
                self._quick_draft_library_id = self._library_key() or '通用词库'
        else:
            self._quick_draft_library_id = ''
        self.term_parse_preview.setVisible(bool(canonical or aliases))
        self.term_parse_preview.setText(
            f"保存到《{getattr(self.legacy, 'glossary_display_name', str)(self._quick_draft_library_id) if (canonical or aliases) else self.state.get('game', '')}》；规范词：{canonical or '（未填写）'}；已确认映射："
            + ("；".join(f"{alias} → {canonical}" for alias in aliases) if aliases else "无（只规范大小写）"))

    def has_pending_edits(self):
        return bool(self.term_editor.text().strip() or self.term_alias_editor.text().strip()
                    or (getattr(self, '_edit_pending', None) and self._edit_pending())
                    or (getattr(self, '_import_pending', None) and self._import_pending()))

    def prepare_for_task(self):
        """Resolve visible drafts before navigation or freezing a task snapshot."""
        if getattr(self, 'pending_draft_dialog', None) is not None:
            return False
        if not self.has_pending_edits():
            return True
        preview = self.term_parse_preview.text() if (self.term_editor.text().strip()
                  or self.term_alias_editor.text().strip()) else ''
        if getattr(self, '_edit_pending', None) and self._edit_pending():
            preview += ('\n' if preview else '') + self._edit_preview()
        if getattr(self, '_import_pending', None) and self._import_pending():
            preview += ('\n' if preview else '') + self.import_preview.toPlainText()
        message = QMessageBox(self)
        from ..design.studio_theme import apply_secondary_surface_theme
        apply_secondary_surface_theme(message)
        message.setWindowTitle('词库还有未保存的输入')
        message.setText('确认以下规范词与别名后继续。任务只会读取已保存的词库。')
        message.setInformativeText(preview)
        save = message.addButton('保存并继续', QMessageBox.ButtonRole.AcceptRole)
        discard = message.addButton('放弃输入并继续', QMessageBox.ButtonRole.DestructiveRole)
        message.addButton('返回编辑', QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(save)
        self.pending_draft_dialog = message
        try:
            message.exec()
            clicked = message.clickedButton()
        finally:
            self.pending_draft_dialog = None
        if clicked is discard:
            self.term_editor.clear()
            self.term_alias_editor.clear()
            if getattr(self, '_edit_cleanup', None):
                self._edit_cleanup()
            if getattr(self, '_import_cleanup', None):
                self._import_cleanup()
            return True
        if clicked is not save:
            return False
        if getattr(self, '_edit_pending', None) and self._edit_pending():
            if not self._edit_submit():
                return False
        if getattr(self, '_import_pending', None) and self._import_pending():
            if not self._import_submit():
                return False
        if self.term_editor.text().strip() or self.term_alias_editor.text().strip():
            if not self.add_single_term():
                return False
        return not self.has_pending_edits()

    def try_sentence(self):
        from .terminology import GlossarySnapshot, snapshot_glossaries
        from .glossary_diagnostics import diagnose_sentence, diagnostic_text
        from ..recognition.content_scene import resolve_content_scene
        from types import SimpleNamespace
        text = self.term_try_input.text()
        library_id = self._library_key()
        browsed = snapshot_glossaries(self.legacy, (library_id,))
        terms_widget = getattr(self.owner, 'terms', None)
        terms_active = terms_widget is None or terms_widget.isChecked()
        enabled = snapshot_glossaries(self.legacy, self.owner._enabled_glossary_ids() if terms_active else ())
        context = SimpleNamespace(game_name=self.game_box_text(), enable_domain_terms=terms_active,
            enabled_glossary_ids=self.owner._enabled_glossary_ids())
        scene = resolve_content_scene(context, enabled)
        task_snapshot = None
        options = getattr(getattr(self.owner, 'worker', None), 'options', None)
        raw_snapshot = getattr(options, 'glossary_snapshot_json', '')
        if raw_snapshot:
            try:
                task_snapshot = GlossarySnapshot.from_dict(json.loads(raw_snapshot))
            except (TypeError, ValueError, KeyError):
                pass
        self.last_sentence_diagnostic = diagnose_sentence(text, browsed, enabled,
            expected_canonical=self.term_try_expected.text(), scene=scene,
            task_snapshot=task_snapshot, pending=self.has_pending_edits())
        self.term_try_panel.show()
        bind_text(self.term_try_toggle, '收起试一句')
        self.term_try_result.setText(diagnostic_text(self.last_sentence_diagnostic))
        self.term_try_result.setToolTip('本地词库诊断不调用 AI；后续 AI 建议和拒绝请查看任务详情。')
        # Wrapped labels otherwise have a near-zero minimum in a crowded
        # page and can be compressed into the input row by the outer layout.
        result_height = max(
            self.term_try_result.fontMetrics().lineSpacing() * 2 + 4,
            self.term_try_result.heightForWidth(max(120, self.term_try_result.width())),
        )
        self.term_try_result.setMinimumHeight(result_height)
        self.term_try_panel.layout().invalidate()
        self.term_try_panel.layout().activate()
        self._refresh_try_layout()

    def _refresh_try_layout(self):
        # Propagate a wrapped result's changed minimum before the sibling AI
        # card is positioned. Otherwise a compact button row can leave the
        # old header geometry valid for one layout pass and overlap the trial.
        widget = self.term_try_panel
        while widget is not None and widget is not self:
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            widget.updateGeometry()
            widget = widget.parentWidget()

    def _toggle_try_panel(self):
        visible = self.term_try_panel.isHidden()
        self.term_try_panel.setVisible(visible)
        bind_text(self.term_try_toggle, '收起试一句' if visible else '试一句')
        self._refresh_try_layout()
        if visible:
            self.term_try_input.setFocus()

    def _type_labels(self):
        labels = {
            "game": "游戏", "event": "活动", "series": "系列",
            "creator": "创作者", "other": "其它内容",
        }
        return {key: translate(value, current_language()) for key, value in labels.items()}

    def _focus_new_game(self):
        self.show_page("mine")
        self.new_library_panel.show()
        self._refresh_restore_builtin()
        self.game_input.setFocus()
        self.game_input.selectAll()

    def _toggle_game_search(self):
        visible = self.game_search.isHidden()
        self.game_search.setVisible(visible)
        if visible:
            self.game_search.setFocus()
            self.game_search.selectAll()

    # ------------------------------------------------------------ build

    def _build(self, games):
        # 2026-10-17 redesign v2 (plan docs/exec-plans/completed/2026-10-17-glossary-page-redesign.md):
        # one accent color, underline tabs on a hairline, a flat library list,
        # and one content card whose sections are split by hairlines instead of
        # nested boxes.  Older control names stay (tests and acceptance scripts
        # click them); rarely used controls live in the 「AI 更新 ▾」 and 「⋯」 menus.
        from .glossary_page_parts import ActionPopup, PageTab
        from ..design.ui_widgets import SwitchControl

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(0)

        # 2026-11-03 card wall: the title and the two tabs share one row.
        heading = QHBoxLayout()
        heading.setSpacing(28)
        title = QLabel("术语库")
        title.setObjectName("termLibraryTitle")
        from twobyteasr.design.ui_navigation import style_workspace_page_title
        style_workspace_page_title(title)
        heading.addWidget(title, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(heading)

        tab_bar = QFrame()
        tab_bar.setObjectName("termTabBar")
        tabs = QHBoxLayout(tab_bar)
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(32)
        self.my_tab_button = PageTab("我的词库")
        self.my_tab_button.setChecked(True)
        self.my_tab_button.clicked.connect(lambda: self.show_page("mine"))
        tabs.addWidget(self.my_tab_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.hub_tab_button = PageTab("线上词库")
        bind_text(self.hub_tab_button, '下载别人整理好的词库，或投稿你的词库', property='toolTip')
        self.hub_tab_button.clicked.connect(lambda: self.show_page("hub"))
        tabs.addWidget(self.hub_tab_button, 0, Qt.AlignmentFlag.AlignBottom)
        tabs.addStretch(1)
        self.hub_button = self.hub_tab_button  # name before the redesign
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_group.addButton(self.my_tab_button)
        self._tab_group.addButton(self.hub_tab_button)
        heading.addWidget(tab_bar, 1, Qt.AlignmentFlag.AlignBottom)
        self._page_title = title
        self._align_heading()
        layout.addSpacing(12)
        # The library count once lived in a badge; the 「我的词库」 tab shows it now.
        self.library_badge = QLabel(self)
        self.library_badge.hide()

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("termPageStack")
        layout.addWidget(self.page_stack, 1)
        mine_page = QWidget()
        mine_page.setObjectName("termMinePage")
        self.mine_page = mine_page
        body = QHBoxLayout(mine_page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        self.page_stack.addWidget(mine_page)
        self.hub_page = QWidget()
        self.hub_page.setObjectName("termHubPage")
        self.hub_page_layout = QVBoxLayout(self.hub_page)
        self.hub_page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_stack.addWidget(self.hub_page)
        self.hub_panel = None  # built on first open (glossary_hub_ui.HubPanel)

        # ---- left: my libraries, a flat list
        sidebar = QFrame()
        sidebar.setObjectName("termLibrarySidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(236)
        sidebar.setProperty('uiZoomOwnSize', True)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.library_sidebar = sidebar
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)
        sidebar_head = QHBoxLayout()
        sidebar_head.setSpacing(8)
        self.game_search = QLineEdit()
        self.game_search.setObjectName("termSidebarSearch")
        bind_text(self.game_search, '搜索词库', property='placeholderText')
        self.game_search.setClearButtonEnabled(True)
        self.game_search.textChanged.connect(self._filter_games)
        sidebar_head.addWidget(self.game_search, 1)
        self.sidebar_new_button = AnimatedButton("新建")
        self.sidebar_new_button.setObjectName("termToolButton")
        bind_text(self.sidebar_new_button, '新建游戏 / 内容词库', property='toolTip')
        self.sidebar_new_button.clicked.connect(self._focus_new_game)
        sidebar_head.addWidget(self.sidebar_new_button)
        sidebar_layout.addLayout(sidebar_head)
        # The list search is always shown now; the old toggle stays hidden.
        self.sidebar_search_button = AnimatedButton("")
        bind_text(self.sidebar_search_button, '搜索我的词库', property='toolTip')
        self.sidebar_search_button.clicked.connect(self._toggle_game_search)
        self.sidebar_search_button.setParent(sidebar)
        self.sidebar_search_button.hide()
        # 新建词库：点「新建」才展开的小表单。
        self.new_library_panel = QFrame()
        self.new_library_panel.setObjectName("termNewLibrary")
        new_library = QVBoxLayout(self.new_library_panel)
        new_library.setContentsMargins(10, 10, 10, 10)
        new_library.setSpacing(8)
        self.game_input = QLineEdit()
        bind_text(self.game_input, '输入游戏 / 内容名称', property='placeholderText')
        self.game_input.returnPressed.connect(self.create_game)
        new_library.addWidget(self.game_input)
        self.content_type = FramelessPopupCombo()
        for label, value in (
            ("游戏", "game"),
            ("活动 / 嘉年华", "event"),
            ("系列 / IP", "series"),
            ("主播 / 创作者", "creator"),
            ("其它内容", "other"),
        ):
            self.content_type.addItem(label, value)
        new_library.addWidget(self.content_type)
        new_library_actions = QHBoxLayout()
        new_library_actions.setSpacing(6)
        new_library_actions.addStretch(1)
        cancel_new = AnimatedButton("取消")
        cancel_new.setObjectName("termGhostButton")
        cancel_new.clicked.connect(self.new_library_panel.hide)
        new_library_actions.addWidget(cancel_new)
        self.add_game_button = AnimatedButton("创建")
        self.add_game_button.setObjectName("termAccentButton")
        bind_text(self.add_game_button, '创建该游戏 / 内容的术语库', property='toolTip')
        self.add_game_button.clicked.connect(self.create_game)
        new_library_actions.addWidget(self.add_game_button)
        new_library.addLayout(new_library_actions)
        # 2026-10-25: deleted built-in libraries come back from here.
        self.restore_builtin_button = AnimatedButton("恢复自带词库")
        self.restore_builtin_button.setObjectName("termLinkButton")
        bind_text(self.restore_builtin_button, '把删除过的软件自带词库放回列表', property='toolTip')
        self.restore_builtin_popup = ActionPopup(self.restore_builtin_button, min_width=200)
        new_library.addWidget(self.restore_builtin_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.restore_builtin_button.hide()
        self.new_library_panel.hide()
        sidebar_layout.addWidget(self.new_library_panel)
        self.game_list = QListWidget()
        self.game_list.setObjectName("termGameList")
        self.game_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.game_list.setSpacing(1)
        self.game_list.currentItemChanged.connect(self.select_game)
        sidebar_layout.addWidget(self.game_list, 1)
        body.addWidget(sidebar)

        # ---- right: the selected library, one card
        content = QFrame()
        content.setObjectName("termLibraryContent")
        self.library_content = content
        content_layout = QVBoxLayout(content)
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        content_header = QFrame()
        content_header.setObjectName("termLibraryContentHeader")
        content_header_layout = QVBoxLayout(content_header)
        content_header_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content_header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_header_layout.setContentsMargins(18, 14, 16, 8)
        content_header_layout.setSpacing(10)

        selected_row = QHBoxLayout()
        selected_row.setSpacing(8)
        self.selected_avatar = QLabel()
        self.selected_avatar.setObjectName("termHeaderAvatar")
        self.selected_avatar.setFixedSize(34, 34)
        self.selected_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_avatar.hide()
        selected_row.addWidget(self.selected_avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        selected_row.addSpacing(4)
        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        self.selected_title = QLabel("请选择游戏")
        self.selected_title.setObjectName("termLibraryName")
        name_row.addWidget(self.selected_title)
        self.selected_type = QLabel()
        self.selected_type.setObjectName("termTypeTag")
        self.selected_type.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.selected_type.hide()
        name_row.addWidget(self.selected_type, 0, Qt.AlignmentFlag.AlignVCenter)
        title_column.addLayout(name_row)
        self.header_meta = QWidget()
        self.header_meta.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        meta_row = QHBoxLayout(self.header_meta)
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(10)
        name_row.addWidget(self.header_meta)
        name_row.addStretch(1)  # keeps the type tag beside the name when meta wraps (2026-11-13)
        self.selected_title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._header_name_row, self._header_title_column = name_row, title_column
        self._header_narrow = False
        meta_row.addSpacing(2)
        self.selected_stats = QLabel()
        self.selected_stats.setObjectName("termMeta")
        bind_text(self.selected_stats, translate('尚未选择', current_language()))
        meta_row.addWidget(self.selected_stats)
        self._meta_dot = QLabel("·")
        self._meta_dot.setObjectName("termMeta")
        meta_row.addWidget(self._meta_dot)
        self.official_stats = QLabel("0 条参考")
        self.official_stats.setObjectName("termMeta")
        meta_row.addWidget(self.official_stats)
        self._meta_dot_batch = QLabel("·")
        self._meta_dot_batch.setObjectName("termMeta")
        meta_row.addWidget(self._meta_dot_batch)
        self.selected_batch = QLabel()
        self.selected_batch.setObjectName("termMeta")
        meta_row.addWidget(self.selected_batch)
        meta_row.addStretch(1)
        selected_row.addLayout(title_column, 1)
        # 2026-11-03: the batch switch sits next to the name, where it is seen.
        self.use_game = SwitchControl("本批字幕使用")
        self.use_game.setObjectName("termBatchSwitch")
        bind_text(self.use_game, '打开后，这一批字幕识别会用这个词库', property='toolTip')
        self.use_game.setEnabled(False)
        self.use_game.clicked.connect(self._on_batch_switch)
        selected_row.addWidget(self.use_game, 0, Qt.AlignmentFlag.AlignVCenter)
        self.batch_toggle = self.use_game  # name before the redesign
        selected_row.addSpacing(6)
        self._header_row = selected_row  # library actions join it below (2026-11-13)
        self.share_button = AnimatedButton("分享")
        self.share_button.setObjectName("termToolButton")
        bind_text(self.share_button, '把这个词库投稿到线上词库：先检查，再打开 GitHub 或 GitCode 的投稿页', property='toolTip')
        self.share_button.clicked.connect(self.open_glossary_submit)
        selected_row.addWidget(self.share_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.submit_terms = self.share_button  # name before the redesign
        self.more_button = AnimatedButton("⋯")
        self.more_button.setObjectName("termIconButton")
        self.more_button.setFixedSize(34, 34)
        bind_text(self.more_button, '改名、给 AI 的说明、导出、删除', property='toolTip')
        selected_row.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.rename_game_button = AnimatedButton("改名")
        self.rename_game_button.clicked.connect(self.rename_current_game)
        # 2026-10-16 (ADR 0124): the user's own note sent to AI with this library.
        self.ai_note_button = AnimatedButton("给 AI 的说明")
        bind_text(self.ai_note_button, 'AI 校对时，把你写的这段说明和这个术语库一起发给 AI', property='toolTip')
        self.ai_note_button.clicked.connect(self.edit_ai_note)
        self.export_terms = AnimatedButton("导出词库")
        self.export_terms.clicked.connect(self.export_current_library)
        self.delete_game_button = AnimatedButton("删除词库")
        bind_text(self.delete_game_button, '删除当前游戏及其术语', property='toolTip')
        self.delete_game_button.setEnabled(False)
        self.delete_game_button.clicked.connect(self.delete_current_game)
        self.more_popup = ActionPopup(self.more_button, min_width=200)
        self.more_popup.add_button(self.rename_game_button)
        self.more_popup.add_button(self.ai_note_button)
        self.more_popup.add_button(self.export_terms)
        self.more_popup.add_separator()
        self.more_popup.add_button(self.delete_game_button, danger=True)
        content_header_layout.addLayout(selected_row)
        from ..studio.studio_toolbar_layout import CommandBar, CommandFlowLayout
        self._header_actions_bar = CommandBar()
        self._header_actions_flow = CommandFlowLayout(self._header_actions_bar)
        self._header_actions_flow.setContentsMargins(0, 0, 0, 0)
        self._header_actions_flow.setSpacing(8)
        self._header_actions_flow.stretch_after = set()
        self._header_actions_bar.hide()
        content_header_layout.addWidget(self._header_actions_bar)

        # 分享提示：已确认词够多、这个游戏线上还没有词库时提示一次（可关掉）。
        self.share_nudge = QFrame()
        self.share_nudge.setObjectName("termNotice")
        nudge_layout = QHBoxLayout(self.share_nudge)
        nudge_layout.setContentsMargins(14, 8, 10, 8)
        nudge_layout.setSpacing(10)
        nudge_dot = QLabel()
        nudge_dot.setObjectName("termDot")
        nudge_dot.setFixedSize(8, 8)
        nudge_layout.addWidget(nudge_dot)
        self.share_nudge_text = QLabel()
        self.share_nudge_text.setWordWrap(True)
        nudge_layout.addWidget(self.share_nudge_text, 1)
        self.share_nudge_button = AnimatedButton("分享")
        self.share_nudge_button.setObjectName("termAccentButton")
        self.share_nudge_button.clicked.connect(self.open_glossary_submit)
        nudge_layout.addWidget(self.share_nudge_button)
        self.share_nudge_later = AnimatedButton("以后再说")
        self.share_nudge_later.setObjectName("termGhostButton")
        self.share_nudge_later.clicked.connect(self._dismiss_share_nudge)
        nudge_layout.addWidget(self.share_nudge_later)
        self.share_nudge.hide()
        content_header_layout.addWidget(self.share_nudge)

        # 加词（2026-11-03）：带列名的一行——正确写法 | 常被听成（可不填）| 分类 | 添加，
        # 列名就是说明；下面一行灰字讲两种填法。
        quick_add_panel = QFrame()
        quick_add_panel.setObjectName("termQuickAdd")
        self.quick_add_panel = quick_add_panel
        quick_add = QVBoxLayout(quick_add_panel)
        quick_add.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        quick_add.setContentsMargins(0, 0, 0, 0)
        quick_add.setSpacing(0)
        add_columns = (1, 5, 6, 0, 0)  # plus mark, correct, heard, category, button

        def add_grid(widget):
            row = QHBoxLayout(widget)
            row.setContentsMargins(10, 0, 10, 0)
            row.setSpacing(8)
            return row

        add_head = QWidget()
        add_head.setObjectName("termAddHead")
        add_head.setFixedHeight(28)
        head_row = add_grid(add_head)
        head_labels = []
        for text in ("", "正确写法", "常被听成（可不填）", "分类", ""):
            label = bind_text(QLabel(), text) if text else QLabel()
            label.setObjectName("termAddHeadLabel")
            head_labels.append(label)
        composer = CommandBar()
        composer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        composer.setObjectName("termComposer")
        composer.setMinimumHeight(48)
        composer_row = add_grid(composer)
        plus = QLabel("+")
        plus.setObjectName("termAddPlus")
        plus.setFixedSize(24, 24)
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.term_editor = QLineEdit()
        self.term_editor.setObjectName("termComposerInput")
        bind_text(self.term_editor, '正确写法，如「倾泻」', property='placeholderText')
        self.term_editor.setAccessibleName('规范写法 / 最终输出')
        self.term_editor.setToolTip('字幕里最终要出现的写法，大小写原样保留')
        self.term_editor.returnPressed.connect(self.add_single_term)
        self.term_alias_editor = QLineEdit()
        # The names drawer reduces the content allocation. Keep fixed actions
        # reachable while the two editable fields share the remaining space.
        self.term_editor.setMinimumWidth(150)
        self.term_alias_editor.setMinimumWidth(150)
        self.term_alias_editor.setObjectName("termComposerInput")
        bind_text(self.term_alias_editor, '常被听成（可不填）', property='placeholderText')
        bind_text(self.term_alias_editor, '常被听成（可不填，多个用顿号）', property='toolTip')
        self.term_alias_editor.setAccessibleName('别名 / 常见错词')
        self.term_alias_editor.returnPressed.connect(self.add_single_term)
        self.term_category = FramelessPopupCombo()
        self.term_category.setObjectName("termComposerCombo")
        for category in ("选手 ID", "人物", "角色", "Boss", "物品", "方块", "阵营", "地点", "模型", "技能", "事件", "其他"):
            self.term_category.addItem(category, category)
        self.term_category.setFixedWidth(116)  # CN labels such as 「选手 ID」 must not truncate
        self.add_term_button = AnimatedButton("添加")
        self.add_term_button.setObjectName("termAccentButton")
        self.add_term_button.clicked.connect(self.add_single_term)
        self.add_term_button.setFixedWidth(max(72, self.add_term_button.sizeHint().width()))
        for row, widgets in ((head_row, head_labels),
                             (composer_row, (plus, self.term_editor, self.term_alias_editor,
                                             self.term_category, self.add_term_button))):
            for widget, stretch in zip(widgets, add_columns):
                row.addWidget(widget, stretch)
        # Same widths in the label row and the input row keep the labels over their fields.
        head_labels[0].setFixedWidth(24)
        head_labels[3].setFixedWidth(self.term_category.width())
        head_labels[4].setFixedWidth(self.add_term_button.width())
        self._add_head_labels = head_labels
        QWidget.setTabOrder(self.term_editor, self.term_alias_editor)
        QWidget.setTabOrder(self.term_alias_editor, self.term_category)
        QWidget.setTabOrder(self.term_category, self.add_term_button)
        quick_add.addWidget(add_head)
        quick_add.addWidget(composer)
        hint_box = QWidget()
        hint_box.setObjectName("termAddHint")
        hint_row = QHBoxLayout(hint_box)
        hint_row.setContentsMargins(42, 4, 10, 6)
        hint_row.setSpacing(4)
        hint = bind_text(QLabel(), '只写正确写法 → 帮识别写对；再写常被听成 → 识别成那样时自动改过来')
        hint.setObjectName("termHint")
        hint.setWordWrap(True)
        hint_row.addWidget(hint, 1)
        self.quick_mapping_button = AnimatedButton('批量映射…')
        self.quick_mapping_button.setObjectName('termLinkButton')
        bind_text(self.quick_mapping_button, '一次贴上多行「听错的写法 -> 正确写法」', property='toolTip')
        self.quick_mapping_button.clicked.connect(lambda: self.show_import_dialog(mapping_mode=True))
        hint_row.addWidget(self.quick_mapping_button)
        self.term_try_toggle = AnimatedButton('试一句')
        self.term_try_toggle.setObjectName('termLinkButton')
        bind_text(self.term_try_toggle, '写一句字幕，看看当前词库会改成什么', property='toolTip')
        self.term_try_toggle.clicked.connect(self._toggle_try_panel)
        hint_row.addWidget(self.term_try_toggle)
        quick_add.addWidget(hint_box)
        # 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): one row.
        # The column names became placeholders, the two-way hint a tooltip, and
        # 批量映射 / 试一句 sit at the end of the same row.
        for link in (self.quick_mapping_button, self.term_try_toggle):
            hint_row.removeWidget(link)
            composer_row.addWidget(link)
        bind_text(composer, '只写正确写法 → 帮识别写对；再写常被听成 → 识别成那样时自动改过来', property='toolTip')
        add_head.hide()
        hint_box.hide()
        self.term_parse_preview = QLabel("规范词原样保存；只有已确认的别名才用于纠错。")
        self.term_parse_preview.setObjectName("termHint")
        self.term_parse_preview.setWordWrap(True)
        self.term_editor.textChanged.connect(self._refresh_term_parse_preview)
        self.term_alias_editor.textChanged.connect(self._refresh_term_parse_preview)
        self.term_parse_preview.setContentsMargins(42, 0, 10, 6)
        quick_add.addWidget(self.term_parse_preview)
        self.term_parse_preview.hide()
        self.term_try_panel = QFrame()
        self.term_try_panel.setObjectName("termTryPanel")
        try_layout = QVBoxLayout(self.term_try_panel)
        try_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        try_layout.setContentsMargins(12, 8, 10, 8)
        try_layout.setSpacing(6)
        try_row = QHBoxLayout()
        self.term_try_input = QLineEdit()
        self.term_try_input.setPlaceholderText("输入一句字幕，检查当前本批词库是否实际生效")
        try_row.addWidget(self.term_try_input, 1)
        try_button = AnimatedButton("检查")
        try_button.setObjectName("termToolButton")
        try_button.clicked.connect(self.try_sentence)
        self.term_try_input.returnPressed.connect(self.try_sentence)
        try_row.addWidget(try_button)
        try_layout.addLayout(try_row)
        association_row = QHBoxLayout()
        self.term_try_expected = QLineEdit()
        self.term_try_expected.setPlaceholderText('期望规范词（可选，用于区分缺词条或别名未关联）')
        association_row.addWidget(self.term_try_expected, 1)
        self.term_association_button = AnimatedButton('关联别名…')
        self.term_association_button.setObjectName("termToolButton")
        self.term_association_button.clicked.connect(self._show_association_sheet)
        association_row.addWidget(self.term_association_button)
        try_layout.addLayout(association_row)
        self.term_try_result = QLabel()
        self.term_try_result.setObjectName("termHint")
        self.term_try_result.setWordWrap(True)
        self.term_try_result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        try_layout.addWidget(self.term_try_result)
        self.term_try_panel.hide()
        content_layout.addWidget(content_header)

        content_body = QFrame()
        content_body.setObjectName("termLibraryBody")
        content_body_layout = QVBoxLayout(content_body)
        content_body_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content_body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_body_layout.setContentsMargins(14, 0, 14, 8)
        content_body_layout.setSpacing(8)

        # 一排工具（2026-11-03）：状态切换 · 找词 · 试一句 ……… AI 更新 ▾ · 导入
        term_tools = QHBoxLayout()
        self.term_tools_layout = term_tools
        term_tools.setSpacing(6)
        self.status_segment = QFrame()
        self.status_segment.setObjectName("termSegment")
        segment_row = QHBoxLayout(self.status_segment)
        segment_row.setContentsMargins(3, 3, 3, 3)
        segment_row.setSpacing(2)
        self._status_group = QButtonGroup(self)
        self._status_group.setExclusive(True)
        self.status_buttons = {}
        for label, value in (("全部", ""), ("已确认", "confirmed"), ("参考", "reference"), ("已隐藏", "hidden")):
            button = AnimatedButton(label)
            button.setObjectName("termSegmentButton")
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.setChecked(not value)
            button.setProperty("statusLabel", label)
            button.clicked.connect(lambda _checked=False, v=value: self._choose_status_filter(v))
            self._status_group.addButton(button)
            segment_row.addWidget(button)
            self.status_buttons[value] = button
        term_tools.addWidget(self.status_segment)
        # 术语搜索：常显，只搜当前词库；分类名也能搜
        self.search = QLineEdit()
        self.search.setObjectName("termToolSearch")
        bind_text(self.search, '找词或分类', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(120)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.apply_filter)
        term_tools.addWidget(self.search, 1)
        term_tools.addStretch(1)
        # 2026-11-13 (user, option A of tmp/glossary-ai-menu-20261113): one
        # 「AI 帮忙 ▾」 grouped by what you want (找新词 / 加外语名), each entry
        # in plain words with one line on what it does; whether the chosen AI
        # can go online sits beside it, and entries that need it say so.
        from .glossary_page_parts import AIMenuEntry
        self.ai_menu_button = AnimatedButton("AI 帮忙 ▾")
        self.ai_menu_button.setObjectName("termToolButton")
        bind_text(self.ai_menu_button, 'AI 联网查资料，建立或更新这个词库', property='toolTip')
        term_tools.addWidget(self.ai_menu_button)
        self.ai_update_button = AIMenuEntry(icon="fa5s.seedling", tone="new")
        bind_text(self.ai_update_button, '补上最近版本的新词')
        bind_text(self.ai_update_button, '已有词库：查最近更新里新出现的词', property='subtitle')
        bind_text(self.ai_update_button, '版本增量：检索最近版本新增与高频术语（单轮，适合已建库词库）', property='toolTip')
        self.ai_update_button.clicked.connect(lambda: self._start_ai_update("incremental"))
        self.ai_full_button = AIMenuEntry(icon="fa5s.book-open", tone="full")
        bind_text(self.ai_full_button, '从零整理一整个词库')
        bind_text(self.ai_full_button, '新词库或想大扫除：查资料、AI 梳理去重，你勾选后加入', property='subtitle')
        bind_text(self.ai_full_button, '查询资料与有效缓存 → AI 提取和梳理 → 补充核对 → 去重与实用筛选 → 选择应用；保留已确认写法', property='toolTip')
        self.ai_full_button.clicked.connect(lambda: self._start_ai_update("full"))
        self.smart_build_button = AIMenuEntry(icon="fa5s.paste", tone="text")
        bind_text(self.smart_build_button, '从一段文字里挑词')
        bind_text(self.smart_build_button, '粘贴攻略、wiki 或用内置资料挑出专有名词，不用上网', property='subtitle')
        self.smart_build_button.clicked.connect(self.open_smart_build)
        self.ai_batch_button = AnimatedButton("一次更新多个词库…")
        self.ai_batch_button.clicked.connect(self._open_batch_update)
        self.ai_history_button = AnimatedButton("更新记录")
        self.ai_history_button.clicked.connect(self._open_update_history)
        self.ai_service_combo = FramelessPopupCombo()
        bind_text(self.ai_service_combo, '使用哪个 AI 执行本次检索整理（复用已配置的登录/密钥，不改动全局设置）', property='toolTip')
        self.ai_service_combo.currentIndexChanged.connect(self._on_ai_service_changed)
        self.ai_model_combo = FramelessPopupCombo()
        self.ai_model_combo.setEditable(True)
        self.ai_model_combo.currentIndexChanged.connect(self._refresh_ai_capability_label)
        self.ai_capability_label = QLabel()
        self.ai_capability_label.setObjectName("termAiCapability")
        self.ai_capability_label.setWordWrap(False)
        self.ai_popup = ActionPopup(self.ai_menu_button, min_width=380)
        self.ai_popup.setMaximumWidth(420)
        self.ai_popup.add_caption("找新词")
        for entry in (self.ai_update_button, self.ai_full_button, self.smart_build_button):
            self.ai_popup.add_entry(entry)
        self.ai_popup.add_separator()
        # 加外语名 (查外语官方名 / 确认译名) is added by multilingual_terms_ui.install.
        self.ai_names_caption = self.ai_popup.add_caption("加外语名")
        self.ai_bar = QFrame()
        self.ai_bar.setObjectName("termAiBar")
        self.ai_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar = QVBoxLayout(self.ai_bar)
        bar.setContentsMargins(10, 8, 10, 10)
        bar.setSpacing(6)
        bar_caption = bind_text(QLabel(), "使用的 AI")
        bar_caption.setObjectName("termAiBarCaption")
        bar.addWidget(bar_caption)
        bar.addWidget(self.ai_service_combo)
        bar.addWidget(self.ai_model_combo)
        bar.addWidget(self.ai_capability_label)
        self.ai_popup.add_widget(self.ai_bar)
        links = QHBoxLayout()
        links.setContentsMargins(4, 0, 4, 2)
        links.setSpacing(2)
        for button in (self.ai_batch_button, self.ai_history_button):
            button.setObjectName("termPopupLink")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(self.ai_popup.hide)
            links.addWidget(button)
        links.addStretch(1)
        self.ai_popup._layout.addLayout(links)
        self.import_terms = AnimatedButton("导入")
        self.import_terms.setObjectName("termToolButton")
        bind_text(self.import_terms, '一次导入多条：粘贴文字，或选 .json / .csv / .txt 文件', property='toolTip')
        self.import_terms.clicked.connect(self.show_import_dialog)
        term_tools.addWidget(self.import_terms)
        # Classification is independent of the new-word category composer.
        # Filter the complete row universe before the virtual card view paints it.
        self.filter_category = FramelessPopupCombo()
        self.filter_category.setObjectName("termToolCombo")
        self.filter_category.addItem("全部分类", "")
        self.filter_category.setMinimumWidth(104)
        self.filter_category.currentIndexChanged.connect(self.apply_filter)
        self.filter_category.setMaximumWidth(148)
        self.filter_category.setAccessibleName('筛选已有词条分类')
        bind_text(self.filter_category, '筛选当前词库的已有词条；选择全部分类可清除', property='toolTip')
        term_tools.insertWidget(2, self.filter_category)
        self.confirm_all_button = AnimatedButton('全部确认参考词（0）')
        self.confirm_all_button.setObjectName('termAccentButton')
        bind_text(self.confirm_all_button, '确认当前词库内全部参考词，包含未显示和被搜索、分类、状态筛掉的词；不含已隐藏和待学习记录', property='toolTip')
        self.confirm_all_button.clicked.connect(self.confirm_all_references)
        self.confirm_all_button.setEnabled(False)
        term_tools.insertWidget(3, self.confirm_all_button)
        self.filter_status = FramelessPopupCombo()
        self.filter_status.setObjectName("termToolCombo")
        for label, value in (
            ("全部状态", ""),
            ("已确认", "confirmed"),
            ("参考", "reference"),
            ("已隐藏", "hidden"),
        ):
            self.filter_status.addItem(label, value)
        self.filter_status.setMinimumWidth(104)
        self.filter_status.currentIndexChanged.connect(self.apply_filter)
        self.filter_status.currentIndexChanged.connect(self._sync_status_segment)
        self.filter_status.setParent(content_body)
        self.filter_status.hide()
        # 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): one row —
        # search, category and status on the left; the card display language
        # (``term_actions``, filled by multilingual_terms_ui.install) on the
        # right, wrapping below on narrow widths. Library actions (confirm all,
        # AI 更新, 导入) moved into the header row next to 分享.
        self.term_filter_pair = QWidget()
        self.term_filter_pair.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        pair_layout = QHBoxLayout(self.term_filter_pair)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(6)
        for control in (self.search, self.filter_category, self.status_segment):
            term_tools.removeWidget(control)
        pair_layout.addWidget(self.search, 1)
        pair_layout.addWidget(self.filter_category)
        term_tools.insertWidget(0, self.term_filter_pair, 1)
        term_tools.insertWidget(1, self.status_segment)
        for action in (self.confirm_all_button, self.ai_menu_button, self.import_terms):
            term_tools.removeWidget(action)
            self._header_row.insertWidget(self._header_row.indexOf(self.share_button), action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.term_actions = QWidget()
        actions_row = QHBoxLayout(self.term_actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)
        self.term_actions_layout = actions_row
        term_tools.addWidget(self.term_actions)
        self.term_toolbar = QWidget()
        self.term_toolbar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.term_toolbar_stack = QVBoxLayout(self.term_toolbar)
        self.term_toolbar_stack.setContentsMargins(0, 0, 0, 0)
        self.term_toolbar_stack.setSpacing(4)
        self.term_toolbar_stack.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.term_toolbar_stack.addLayout(term_tools)
        self._term_toolbar_narrow = False
        content_body_layout.addWidget(self.term_toolbar)
        content_body_layout.addWidget(quick_add_panel)
        content_body_layout.addWidget(self.term_try_panel)

        # 第一次用：三步说明，点「知道了」后不再出现。
        self.term_guide = QFrame()
        self.term_guide.setObjectName("termGuide")
        guide_row = QHBoxLayout(self.term_guide)
        guide_row.setContentsMargins(12, 7, 8, 7)
        guide_row.setSpacing(14)
        guide_title = bind_text(QLabel(), '第一次用？')
        guide_title.setObjectName("termGuideTitle")
        guide_row.addWidget(guide_title)
        for number, text in (("1", "写正确写法，点添加"), ("2", "听错的写法可不填"),
                             ("3", "虚线卡点「收下」才生效")):
            step = QHBoxLayout()
            step.setSpacing(6)
            badge = QLabel(number)
            badge.setObjectName("termGuideNumber")
            badge.setFixedSize(18, 18)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step.addWidget(badge)
            words = bind_text(QLabel(), text)
            words.setObjectName("termGuideText")
            words.setWordWrap(True)
            words.setMinimumWidth(80)
            step.addWidget(words, 1)
            guide_row.addLayout(step, 1)
        self.term_guide_close = AnimatedButton("知道了")
        self.term_guide_close.setObjectName("termGhostButton")
        self.term_guide_close.clicked.connect(self._dismiss_term_guide)
        guide_row.addWidget(self.term_guide_close)
        self.term_guide.hide()
        content_body_layout.addWidget(self.term_guide)

        # AI 任务进度与失败说明（任务栏在第一次需要时插到这里）。
        self.ai_status_area = QWidget()
        ai_status_layout = QVBoxLayout(self.ai_status_area)
        ai_status_layout.setContentsMargins(0, 0, 0, 0)
        ai_status_layout.setSpacing(4)
        self.ai_task_strip = None  # 延迟创建：需要 manager（见 _ensure_task_manager）
        self.ai_update_status = QLabel("")
        self.ai_update_status.setObjectName("termReferencePolicy")
        self.ai_update_status.setWordWrap(True)
        self.ai_update_status.hide()
        ai_status_layout.addWidget(self.ai_update_status)
        content_body_layout.addWidget(self.ai_status_area)

        from .learning_review_ui import LearningReviewPanel
        self.learning_panel = LearningReviewPanel(self)
        self.learning_count = self.learning_panel.count
        self.learning_box = self.learning_panel.box
        self.learning_list = self.learning_panel.listing
        self.learning_toggle = self.learning_panel.toggle
        self.learning_accept_button = self.learning_panel.accept
        self.learning_ignore = self.learning_panel.ignore
        # 2026-11-13: reference terms waiting to be kept join the 待处理 strip.
        from .glossary_page_parts import StripChip
        self.reference_chip = StripChip(tone="warning")
        self.reference_chip.setToolTip("只显示参考词；在卡片上点「收下」，或用标题栏的「全部确认参考词」")
        self.reference_chip.clicked.connect(lambda _c: self._choose_status_filter("reference"))
        self.reference_chip.hide()
        self.learning_panel.chip_layout.addWidget(self.reference_chip)
        content_body_layout.addWidget(self.learning_panel)

        # 选了词条才出现：确认 / 隐藏 / 删除。
        self.selection_bar = QFrame()
        self.selection_bar.setObjectName("termNotice")
        selection_layout = QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(14, 5, 8, 5)
        selection_layout.setSpacing(6)
        self.selection_label = QLabel()
        self.selection_label.setObjectName("termNoticeStrong")
        selection_layout.addWidget(self.selection_label)
        selection_layout.addStretch(1)
        self.bulk_confirm = AnimatedButton("确认所选参考")
        self.bulk_confirm.setObjectName("termToolButton")
        self.bulk_confirm.clicked.connect(self.confirm_selected_references)
        self.bulk_confirm.setEnabled(False)
        selection_layout.addWidget(self.bulk_confirm)
        self.bulk_hide = AnimatedButton("隐藏所选")
        self.bulk_hide.setObjectName("termToolButton")
        self.bulk_hide.clicked.connect(self.hide_selected_references)
        self.bulk_hide.setEnabled(False)
        selection_layout.addWidget(self.bulk_hide)
        self.remove_terms = AnimatedButton("删除所选术语")
        self.remove_terms.setObjectName("termDangerButton")
        self.remove_terms.setEnabled(False)
        self.remove_terms.clicked.connect(self.remove_selected_terms)
        selection_layout.addWidget(self.remove_terms)
        self.clear_selection = AnimatedButton("取消选择")
        self.clear_selection.setObjectName("termGhostButton")
        self.clear_selection.clicked.connect(lambda: self.listing.clearSelection())
        selection_layout.addWidget(self.clear_selection)
        self.selection_bar.hide()
        content_body_layout.addWidget(self.selection_bar)

        # 词卡墙（2026-11-03）：同一个表格模型，一条映射/参考一张卡，委托绘制，
        # 650 条也不建逐条 QWidget（P0-5 的约束不变）。
        self.learned_title = QLabel("术语列表")
        self.learned_title.setObjectName("termTableTitle")
        bind_text(self.learned_title, '已确认/学习映射会参与纠错；内置词库只提供弱候选，不会仅凭名字相似强制改字。', property='toolTip')
        content_body_layout.addWidget(self.learned_title)
        self.learned_title.hide()  # the status segment and the footer carry the counts
        self.listing = TermCardView()
        self._term_model = _TermMappingsModel(self)
        self.listing.setModel(self._term_model)
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listing.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.listing.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listing.setFrameShape(QFrame.Shape.NoFrame)
        self.listing.setMinimumHeight(240)
        self.listing.doubleClicked.connect(self._on_table_double_click)
        self.listing.edit_requested.connect(self._on_card_clicked)
        self.listing.action_requested.connect(self._on_card_action)
        self.listing.category_requested.connect(self._choose_category_filter)
        # The selection bar floats over the cards so Ctrl+clicks never move them.
        content_body_layout.removeWidget(self.selection_bar)
        self.listing.set_overlay(self.selection_bar)
        try:
            self.listing.selectionModel().selectionChanged.connect(self.update_remove_action)
        except Exception:
            pass
        card_stage = QWidget()
        card_stage_layout = QGridLayout(card_stage)
        card_stage_layout.setContentsMargins(0, 0, 0, 0)
        card_stage_layout.addWidget(self.listing, 0, 0)
        # 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): 「名称与译名」
        # opens here, beside the cards, instead of a separate window.
        self.names_drawer = _DrawerFrame()
        self.names_drawer.setObjectName("termNamesDrawer")
        self.names_drawer.setFixedWidth(440)
        # Never let the drawer's content set the page height; it scrolls inside.
        self.names_drawer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        self.names_drawer.setMinimumHeight(0)
        drawer_layout = QVBoxLayout(self.names_drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.names_drawer.hide()
        # Placed beside the whole library panel (full height) further below.
        content_body_layout.addWidget(card_stage, 3)
        # 空态：没有词条时给两个起点（线上词库 / 自己整理）；筛选后没词时只说明
        self.listing_empty = QWidget()
        self.listing_empty.setObjectName("termMappingEmpty")
        empty_layout = QVBoxLayout(self.listing_empty)
        empty_layout.setContentsMargins(12, 18, 12, 18)
        empty_layout.setSpacing(8)
        empty_layout.addStretch(1)
        self.listing_empty_title = QLabel("让识别更懂你的游戏")
        self.listing_empty_title.setObjectName("termEmptyTitle")
        self.listing_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.listing_empty_title)
        self.listing_empty_label = QLabel("加入角色名、地点和专有词，可以减少同音词误识别。")
        self.listing_empty_label.setObjectName("termEmptyHint")
        self.listing_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.listing_empty_label.setWordWrap(True)
        empty_layout.addWidget(self.listing_empty_label)
        self.start_cards = QWidget()
        start_layout = QHBoxLayout(self.start_cards)
        start_layout.setContentsMargins(0, 10, 0, 0)
        start_layout.setSpacing(16)
        hub_card = QFrame()
        hub_card.setObjectName("termStartCardHub")
        hub_card_layout = QVBoxLayout(hub_card)
        hub_card_layout.setContentsMargins(20, 18, 20, 18)
        hub_card_layout.setSpacing(8)
        hub_card_head = QHBoxLayout()
        hub_card_head.setSpacing(8)
        hub_card_title = QLabel("从线上词库下载")
        hub_card_title.setObjectName("termStartTitle")
        hub_card_head.addWidget(hub_card_title)
        hub_card_pill = QLabel("推荐")
        hub_card_pill.setObjectName("termStartPill")
        hub_card_head.addWidget(hub_card_pill)
        hub_card_head.addStretch(1)
        hub_card_layout.addLayout(hub_card_head)
        hub_card_text = QLabel("别的玩家已经整理好的词库，先预览再一键安装。")
        hub_card_text.setObjectName("termStartText")
        hub_card_text.setWordWrap(True)
        hub_card_layout.addWidget(hub_card_text)
        hub_card_layout.addStretch(1)
        self.listing_empty_hub = AnimatedButton("浏览线上词库")
        self.listing_empty_hub.setObjectName("termAccentButton")
        self.listing_empty_hub.clicked.connect(lambda: self.show_page("hub"))
        hub_card_layout.addWidget(self.listing_empty_hub, 0, Qt.AlignmentFlag.AlignLeft)
        start_layout.addWidget(hub_card, 1)
        own_card = QFrame()
        own_card.setObjectName("termStartCard")
        own_card_layout = QVBoxLayout(own_card)
        own_card_layout.setContentsMargins(20, 18, 20, 18)
        own_card_layout.setSpacing(8)
        own_card_title = QLabel("自己整理")
        own_card_title.setObjectName("termStartTitle")
        own_card_layout.addWidget(own_card_title)
        own_card_text = QLabel("在上面添加错词和正确写法；也可以批量导入，或让 AI 帮你查资料。")
        own_card_text.setObjectName("termStartText")
        own_card_text.setWordWrap(True)
        own_card_layout.addWidget(own_card_text)
        own_card_layout.addStretch(1)
        empty_actions = QHBoxLayout()
        empty_actions.setSpacing(6)
        self.listing_empty_build = AnimatedButton("新建词库")
        self.listing_empty_build.setObjectName("termToolButton")
        self.listing_empty_build.clicked.connect(self._focus_new_game)
        empty_actions.addWidget(self.listing_empty_build)
        self.listing_empty_import = AnimatedButton("导入词库")
        self.listing_empty_import.setObjectName("termGhostButton")
        self.listing_empty_import.clicked.connect(self.show_import_dialog)
        empty_actions.addWidget(self.listing_empty_import)
        self.listing_empty_smart = AnimatedButton("智能建词")
        self.listing_empty_smart.setObjectName("termGhostButton")
        self.listing_empty_smart.clicked.connect(self.open_smart_build)
        empty_actions.addWidget(self.listing_empty_smart)
        empty_actions.addStretch(1)
        self.listing_empty_actions = empty_actions
        own_card_layout.addLayout(empty_actions)
        start_layout.addWidget(own_card, 1)
        empty_layout.addWidget(self.start_cards)
        empty_layout.addStretch(1)
        self.listing_empty.hide()
        card_stage_layout.addWidget(self.listing_empty, 0, 0)
        self.listing_empty.raise_()
        content_layout.addWidget(content_body, 1)

        # 页底：一个开关决定这个词库用不用在本批字幕
        footer = QFrame()
        footer.setObjectName("termLibraryFooter")
        self.library_footer = footer
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 6, 16, 6)
        footer_layout.setSpacing(12)
        # 2026-11-03: the batch switch moved to the title row; the footer keeps
        # the batch summary and how to use the cards.
        self.batch_status = QLabel()
        self.batch_status.setObjectName("termHint")
        self.batch_status.setWordWrap(True)
        self.batch_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        footer_layout.addWidget(self.batch_status, 1)
        self.card_hint = bind_text(QLabel(), '✓ = 译名已确认 · 虚线框 = 参考词 · 点卡片在右侧编辑名称与译名')
        self.card_hint.setObjectName("termHint")
        footer_layout.addWidget(self.card_hint)
        if not self.page_mode:
            close = AnimatedButton("关闭")
            close.setObjectName("termToolButton")
            close.clicked.connect(self._close_hosted)
            footer_layout.addWidget(close)
        content_layout.addWidget(footer)
        self.library_content_scroll = QScrollArea()
        self.library_content_scroll.setObjectName("termContentScroll")
        self.library_content_scroll.setWidgetResizable(True)
        self.library_content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.library_content_scroll.setWidget(content)
        body.addWidget(self.library_content_scroll, 1)
        body.addWidget(self.names_drawer)

        self.refresh_learning_suggestions()
        self._refresh_ai_choices()

        for game_name in games:
            self.add_game_item(game_name)
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))
        self._sync_tab_counts()
        self._apply_cached_hub_counts()

    # ------------------------------------------------------------ pages, hub, sharing

    def show_page(self, page: str):
        """「我的词库」(page="mine") or 「线上词库」(page="hub")."""
        if page == "hub":
            if self.hub_panel is None:
                from .glossary_hub_ui import HubPanel
                self.hub_panel = HubPanel(self, self.hub_page)
                self.hub_panel.counts_changed.connect(self._set_hub_counts)
                self.hub_page_layout.addWidget(self.hub_panel)
            self.page_stack.setCurrentWidget(self.hub_page)
            self.hub_tab_button.setChecked(True)
            if not self.hub_panel.loaded_once:
                self.hub_panel.load(force=False)
            return
        self.page_stack.setCurrentWidget(self.mine_page)
        self.my_tab_button.setChecked(True)

    def _sync_tab_counts(self):
        self.my_tab_button.setCount(str(self.game_list.count()))

    def _set_hub_counts(self, libraries: int, updates: int):
        if libraries:
            bind_text(self.hub_tab_button, '{count} 个社区词库', property='count', count=libraries)
        else:
            self.hub_tab_button.setCount("")
        if updates:
            bind_text(self.hub_tab_button, '{count} 个可更新', property='note', count=updates)
        else:
            self.hub_tab_button.setNote("")

    def _apply_cached_hub_counts(self):
        try:
            from .glossary_hub_ui import cached_counts
            counts = cached_counts(self.legacy)
        except Exception:  # noqa: BLE001 - the tab count is informative only
            counts = None
        if counts is not None:
            self._set_hub_counts(*counts)

    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._sidebar_count_cursor < self.game_list.count(): self._sidebar_counts_timer.start()
        if getattr(self, "_hub_counts_checked", False):
            return
        self._hub_counts_checked = True
        from . import glossary_hub as hub
        if hub.catalog_is_fresh(hub.cached_catalog(self.legacy)) or not hub.TRUSTED_HUB_KEYS:
            return
        from .glossary_hub_ui import _run_async

        def counted(catalog, error):
            if error is None and (self.hub_panel is None or not self.hub_panel.loaded_once):
                self._apply_cached_hub_counts()
            if error is None:
                self._refresh_share_nudge()
        _run_async(self, lambda: hub.fetch_catalog(legacy=self.legacy), counted)

    def _set_selected_header(self, game_name: str, type_label: str):
        if game_name:
            self.selected_title.setText(game_name)
            self.selected_type.setText(type_label)
            self.selected_avatar.setText(game_name[:1])
            self.selected_avatar.setStyleSheet(avatar_style(game_name, radius=11, pixels=15))
        else:
            bind_text(self.selected_title, translate('请选择游戏 / 内容', current_language()))
        self.selected_type.setVisible(bool(game_name and type_label))
        self.selected_avatar.setVisible(bool(game_name))

    def _refresh_share_nudge(self):
        from . import glossary_hub as hub
        game = self.state.get("game", "")
        key = self._library_key() if game else ""
        confirmed = len(self.state.get("mappings") or [])
        show = False
        if game and key and confirmed >= hub.SHARE_PROMPT_MIN_ROWS and not hub.share_prompt_done(key, legacy=self.legacy):
            # Only once the online catalog is known: a game that already has a
            # community library is not worth a prompt (an update goes by 投稿 anyway).
            catalog = hub.cached_catalog(self.legacy)
            if catalog is not None:
                entry = (self.legacy.load_learned_term_payload().get("games") or {}).get(key)
                on_hub = any(self._game_identity(item.get("game", "")) == self._game_identity(game)
                             for item in catalog.entries)
                show = isinstance(entry, dict) and not entry.get("hub") and not on_hub
        if show:
            bind_text(self.share_nudge_text, '这个词库有 {count} 条确认过的词。分享到线上词库，别的玩家就不用再整理一次。',
                      count=confirmed)
        self.share_nudge.setVisible(show)

    def _dismiss_share_nudge(self):
        from . import glossary_hub as hub
        key = self._library_key()
        if key:
            hub.mark_share_prompt_done(key, legacy=self.legacy)
        self.share_nudge.hide()

    # ------------------------------------------------------------ 2026-11-03 card wall

    def _choose_status_filter(self, value: str):
        index = self.filter_status.findData(value)
        if index >= 0 and index != self.filter_status.currentIndex():
            self.filter_status.setCurrentIndex(index)
        self._sync_status_segment()

    def _sync_status_segment(self, *_args):
        current = str(self.filter_status.currentData() or "")
        button = self.status_buttons.get(current)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _update_status_counts(self, stats: dict):
        counts = {"": stats.get("total", 0) - stats.get("hidden", 0), "confirmed": stats.get("confirmed", 0),
                  "reference": stats.get("reference", 0), "hidden": stats.get("hidden", 0)}
        for value, button in self.status_buttons.items():
            label = translate(str(button.property("statusLabel") or ""), current_language())
            button.setText(f"{label} {counts.get(value, 0)}")
            button.setMinimumWidth(max(button.sizeHint().width(), button.fontMetrics().horizontalAdvance(button.text()) + 32))

    def _refresh_term_guide(self):
        from . import glossary_hub as hub
        show = bool(self.state.get("game")) and not hub.term_guide_done(legacy=self.legacy)
        self.term_guide.setVisible(show)

    def _dismiss_term_guide(self):
        from . import glossary_hub as hub
        hub.mark_term_guide_done(legacy=self.legacy)
        self.term_guide.hide()

    def _card_anchor(self, index: QModelIndex):
        """The card's rectangle in this page's coordinates (for the edit box)."""
        if not index.isValid():
            return None
        rect = self.listing.card_rect(index)
        if not rect.isValid():
            return None
        top_left = self.listing.viewport().mapTo(self, rect.topLeft())
        return QRect(top_left, rect.size())

    def _on_card_clicked(self, index: QModelIndex):
        """A plain click on a confirmed card edits it in place; Ctrl / Shift select."""
        if not index.isValid():
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.MetaModifier):
            return
        row = self._term_model.data_for_row(index.row())
        if row and row.get("status") == "confirmed" and row.get("raw"):
            anchor = self._card_anchor(index)
            self.listing.clearSelection()
            self.edit_mapping(row["raw"], anchor=anchor, members=self._member_rows(row))

    @glossary_write_errors
    def _on_card_action(self, index: QModelIndex):
        """The 收下 / 恢复 button painted on reference and hidden cards."""
        row = self._term_model.data_for_row(index.row()) if index.isValid() else None
        if row:
            self._run_row_action(row)

    def _toggle_learning_list(self):
        self.learning_panel._toggle()

    def _sync_batch_switch(self):
        in_batch = bool(self.state.get("game")) and self._current_game_in_batch()
        blocked = self.use_game.blockSignals(True)
        self.use_game.setChecked(in_batch)
        self.use_game.blockSignals(blocked)
        bind_text(self.selected_batch, '本批使用中' if in_batch else '本批未使用')
        # 2026-11-03: the switch beside the name already says it.
        self.selected_batch.setVisible(False)
        self._meta_dot_batch.setVisible(False)
        self._refresh_in_use_badges()

    def _refresh_in_use_badges(self):
        enabled = set(getattr(self.owner, "_enabled_glossary_ids", lambda: ())() or ())
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            row = self.game_list.itemWidget(item)
            if isinstance(row, TermGameListRow):
                name = str(item.data(Qt.ItemDataRole.UserRole) or "")
                row.set_in_use(str(item.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(name)) in enabled)

    def _on_batch_switch(self, *_args):
        if self.use_game.isChecked():
            self.use_selected_game()
        elif self._current_game_in_batch():
            self.toggle_current_game_in_batch()
        self._sync_batch_switch()

    def _close_hosted(self):
        if not self.prepare_for_task():
            return
        if self.page_mode:
            self.owner._return_to_settings()
            return
        # Hosted path: traverse all ancestors before using a local fallback.
        containing_dialog = None
        p = self.parentWidget()
        while p:
            request_close = getattr(p, "_request_close", None)
            if callable(request_close):
                try:
                    request_close()
                    return
                except Exception:
                    pass
            if containing_dialog is None and isinstance(p, QDialog):
                containing_dialog = p
            p = p.parentWidget()
        if containing_dialog is not None:
            containing_dialog.reject()
            return
        self.hide()

    def _sync_term_toolbar(self):
        if not hasattr(self, 'term_toolbar'):
            return
        if self._diagnostics is not None:
            self._diagnostics['toolbar'] += 1
        if hasattr(self, 'listing') and self.listing.isVisibleTo(self):
            from ..app.ui_zoom import zoom_factor
            factor = zoom_factor()
            normal_min, normal_max = round(210*factor), round(236*factor)
            needed = 1 + self.listing.COLUMNS * (self.listing.MIN_CARD_WIDTH + self.listing.GAP)
            # Use the outer content allocation. The transient viewport width
            # changes while QListView decides whether a scrollbar is needed.
            margins = self.listing.viewportMargins()
            card_width = (self.listing.contentsRect().width() - margins.left() - margins.right()
                          - self.listing.verticalScrollBar().sizeHint().width())
            target_max = max(180, min(normal_max,
                card_width + self.library_sidebar.width() - needed))
            target_min = normal_min if target_max >= normal_min else 180
            changed = (self.library_sidebar.minimumWidth(), self.library_sidebar.maximumWidth()) != (target_min,target_max)
            if changed:
                if target_min < self.library_sidebar.minimumWidth(): self.library_sidebar.setMinimumWidth(target_min)
                self.library_sidebar.setMaximumWidth(target_max)
                self.library_sidebar.setMinimumWidth(target_min)
                self._queue_term_toolbar()
        header_required = (self.selected_title.sizeHint().width() + self.selected_type.sizeHint().width()
                           + self.header_meta.sizeHint().width() + self.use_game.sizeHint().width()
                           + sum(button.sizeHint().width() for button in (self.confirm_all_button, self.ai_menu_button, self.import_terms)
                                 if not button.isHidden())
                           + self.share_button.sizeHint().width() + self.more_button.width() + 130)
        header_narrow = self.library_content.width() < header_required
        if header_narrow != self._header_narrow:
            self._header_narrow = header_narrow
            actions = (self.use_game, self.confirm_all_button, self.ai_menu_button,
                       self.import_terms, self.share_button, self.more_button)
            if header_narrow:
                self._header_name_row.removeWidget(self.header_meta)
                self._header_title_column.addWidget(self.header_meta)
                for action in actions:
                    self._header_row.removeWidget(action)
                    self._header_actions_flow.addWidget(action)
                self._header_actions_bar.show()
            else:
                self._header_title_column.removeWidget(self.header_meta)
                self._header_name_row.insertWidget(self._header_name_row.indexOf(self.selected_type) + 1, self.header_meta)
                for action in actions:
                    self._header_actions_flow.removeWidget(action)
                    self._header_row.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
                self._header_actions_bar.hide()
        status_width = max(self.status_segment.sizeHint().width(),
                           self.status_segment.minimumSizeHint().width())
        required = (self.term_filter_pair.minimumSizeHint().width() + status_width
                    + self.term_actions.sizeHint().width() + 30)
        split_filters = self.term_toolbar.width() < self.term_filter_pair.minimumSizeHint().width() + status_width + 12
        if split_filters != getattr(self, '_term_filters_split', False):
            self._term_filters_split = split_filters
            if split_filters:
                self.term_tools_layout.removeWidget(self.status_segment)
                self.term_toolbar_stack.insertWidget(1, self.status_segment)
            else:
                self.term_toolbar_stack.removeWidget(self.status_segment)
                self.term_tools_layout.insertWidget(1, self.status_segment)
        narrow = self.term_toolbar.width() < required
        if narrow == self._term_toolbar_narrow:
            return
        self._term_toolbar_narrow = narrow
        if narrow:
            self.term_tools_layout.removeWidget(self.term_actions)
            self.term_toolbar_stack.addWidget(self.term_actions, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.term_toolbar_stack.removeWidget(self.term_actions)
            self.term_tools_layout.addWidget(self.term_actions)

    def _queue_term_toolbar(self):
        if not self._toolbar_timer.isActive():
            self._toolbar_timer.start(0)

    def _align_heading(self):
        """Put 「术语库」 on the same baseline as the tab labels (2026-11-13).

        A tab draws its label at the top and its underline 14px lower, while
        the title sits on the bottom of the row; without this the tab labels
        float about 12px above the title's baseline."""
        title, tab = getattr(self, '_page_title', None), getattr(self, 'my_tab_button', None)
        if title is None or tab is None:
            return
        title.ensurePolished()
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        label_font, _small = tab._fonts()
        tab_from_bottom = tab.sizeHint().height() - (QFontMetrics(label_font).ascent() + 2)
        bottom = max(0, tab_from_bottom - QFontMetrics(title.font()).descent())
        if title.contentsMargins().bottom() != bottom:
            title.setContentsMargins(0, 0, 0, bottom)

    def apply_ui_zoom(self, _factor):
        self._align_heading()
        if hasattr(self, 'term_toolbar'):
            self._queue_term_toolbar()
            self.listing.request_layout('zoom')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._align_heading()
        if hasattr(self, 'term_toolbar'):
            # 2026-11-13 (user): re-wrap now, not only after the event loop;
            # Qt paints before a 0 ms timer, so every resize step showed the
            # old one-row toolbar squeezed (cut words, dark-on-dark segment).
            # The queued pass still follows for sizes that settle later.
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self._sync_term_toolbar()
            self._queue_term_toolbar()
        # P0 Resize: do NOT force fixed width on sidebar; let it keep a comfortable min and let content grow.
        # The sidebar has a reasonable initial fixed in _build; here we only ensure minimums for usability.
        # The toolbar reflow owns sidebar constraints, including UI zoom.
        # Resetting the minimum here would override its compact desktop mode.

    # ------------------------------------------------------------ 列表与刷新

    def add_game_item(self, game_name, select=False, *, library_id=None):
        game_name = self._canonical(game_name)
        if library_id is None:
            catalog = getattr(self.legacy, 'glossary_catalog', lambda: [])()
            matches = [row for row in catalog if self.legacy.runtime_game_identity(row['name']) == self.legacy.runtime_game_identity(game_name)]
            if len(matches) > 1:
                return None  # catalog adds each distinct stable ID below
        identity = str(library_id or self._game_identity(game_name))
        if not game_name or not identity:
            return None
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(item.data(Qt.ItemDataRole.UserRole))) == identity:
                item.setData(Qt.ItemDataRole.UserRole, game_name)
                item.setData(Qt.ItemDataRole.UserRole + 1, identity)
                item.setText("")
                item.setToolTip(self._game_item_tooltip(game_name))
                row = self.game_list.itemWidget(item)
                if isinstance(row, TermGameListRow):
                    row.update_content(
                        game_name,
                        self._game_term_count(game_name, identity),
                        self._game_type_label(game_name, identity),
                        self._game_reference_count(game_name, identity),
                    )
                if select:
                    self.game_list.setCurrentItem(item)
                return item
        item = QListWidgetItem("")
        item.setData(Qt.ItemDataRole.UserRole, game_name)
        item.setData(Qt.ItemDataRole.UserRole + 1, identity)
        item.setToolTip(self._game_item_tooltip(game_name))
        item.setSizeHint(QSize(0, 54))
        self.game_list.addItem(item)
        row = TermGameListRow(
            game_name,
            self._game_term_count(game_name, identity),
            self._game_type_label(game_name, identity),
            self._game_reference_count(game_name, identity),
            parent=self.game_list,
        )
        row.clicked.connect(lambda target=item: self.game_list.setCurrentItem(target))
        row.menu_requested.connect(lambda pos, target=item: self._show_game_menu(target, pos))
        self.game_list.setItemWidget(item, row)
        if hasattr(self, "my_tab_button"):
            self._sync_tab_counts()
        if select:
            self.game_list.setCurrentItem(item)
        return item

    def _library_stats(self, game_name, library_id=None):
        identity = str(library_id or self._library_key(game_name))
        if identity not in self._library_stats_cache:
            mappings = getattr(self.legacy, 'user_confirmed_mappings_for_game', self.legacy.learned_mappings_for_game)(identity) if game_name else []
            self._library_stats_cache[identity] = self._count_term_cards(self._group_term_rows(self._unified_term_rows(game_name, mappings)))
        return self._library_stats_cache[identity]

    def _game_term_count(self, game_name, library_id=None):
        if self._building_game_index:
            return '…'
        return self._library_stats(game_name, library_id)['confirmed']

    def _game_reference_count(self, game_name, library_id=None):
        if self._building_game_index:
            return '…'
        return self._library_stats(game_name, library_id)['reference'] if game_name else 0

    def _fill_next_sidebar_count(self):
        if not self.isVisible(): return
        if self._row_build_running:
            self._sidebar_counts_timer.start()
            return
        if self._sidebar_count_cursor >= self.game_list.count(): return
        item = self.game_list.item(self._sidebar_count_cursor)
        self._sidebar_count_cursor += 1
        name = str(item.data(Qt.ItemDataRole.UserRole) or '')
        identity = str(item.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(name))
        row = self.game_list.itemWidget(item)
        if isinstance(row, TermGameListRow):
            stats = self._library_stats(name, identity)
            row.update_content(name, stats['confirmed'], self._game_type_label(name, identity), stats['reference'])
        self._sidebar_counts_timer.start()

    def _game_type_label(self, game_name, library_id=None):
        content_type = getattr(
            self.legacy, "learned_content_type", lambda _name: "game"
        )(library_id or self._library_key(game_name))
        return self._type_labels().get(content_type, translate("其它内容", current_language()))

    def _game_item_text(self, game_name):
        return str(game_name)

    def _game_item_tooltip(self, game_name):
        type_labels = self._type_labels()
        current_type = getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
        return (
            f"类型：{type_labels.get(current_type, '其它内容')}\n"
            f"已确认术语 {self._library_stats_cache.get(self._library_key(game_name), {}).get('confirmed', '…')} 条\n"
            f"查看《{game_name}》的已学习术语与内置词库"
        )

    def _refresh_game_item_counts(self):
        enabled = set(getattr(self.owner, "_enabled_glossary_ids", lambda: ())() or ())
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            identity = str(item.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(name))
            if not name:
                continue
            item.setText("")
            item.setToolTip(self._game_item_tooltip(name))
            row = self.game_list.itemWidget(item)
            if isinstance(row, TermGameListRow):
                stats = self._library_stats_cache.get(identity, {})
                row.update_content(
                    name,
                    stats.get('confirmed', '…'),
                    self._game_type_label(name, identity),
                    stats.get('reference', '…'),
                )
                row.set_in_use(identity in enabled)
        self._sidebar_count_cursor = 0
        self._sidebar_counts_timer.start()

    def _filter_games(self, text=""):
        query = text.strip().casefold()
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
            item.setHidden(bool(query) and query not in name.casefold())

    @staticmethod
    def _mapping_origin(item: dict) -> str:
        explicit = str(item.get("origin") or "").strip()
        if explicit:
            return explicit
        verification = str(item.get("verification") or "")
        sources = " ".join(map(str, item.get("sources", ())))
        if verification == "web_official" or "official" in sources.casefold():
            return "官方"
        if verification.startswith("ai_"):
            return "AI 学习"
        if verification == "user_manual":
            return "手动"
        if item.get("confirmed"):
            return "用户确认"
        if verification or sources:
            return "AI 学习"
        return "手动"

    @staticmethod
    def _mapping_category(item: dict) -> str:
        from twobyteasr.design.ui_widgets import category_label

        raw = _reference_category_label(str(item.get('category') or '其他').strip())
        label = category_label(raw)
        # Real libraries may introduce categories beyond the composer defaults.
        return raw if label == '其他' and raw.casefold() not in {'other', '其他', '其它'} else label

    def _unified_term_rows(self, game_name=None, mappings=None) -> list[dict]:
        """Merge learned mappings and builtin references into one row universe.

        来源/状态/启用是三个概念：来源标签可叠加（内置参考 + 已确认），
        状态列表达参考/已确认/已隐藏，是否用于本批由底部开关控制。
        VII 轮：仅差包裹引号的条目（「11号」vs「「11号」」）按归一键合并，
        别名与主词相同（席德（别名 席德））不再重复展示。
        """
        from .glossary_skill import quote_normalize_term

        game_name = self.state['game'] if game_name is None else game_name
        if not game_name:
            return []
        mappings = (self.state.get('mappings') or []) if mappings is None else mappings
        if game_name not in self._builtin_cache:
            self._builtin_cache[game_name] = self.builtin_for_game(game_name)
        references = self._reference_entries_for_game(game_name)
        reference_by_name = {quote_normalize_term(entry["name"]): entry for entry in references}
        rows: list[dict] = []
        confirmed_names = set()
        for item in mappings:
            if not isinstance(item, dict):
                continue
            source = str(item.get("from", ""))
            target = str(item.get("to", ""))
            if not source or not target:
                continue
            confirmed_names.add(quote_normalize_term(target))
            origin_label = self._mapping_origin(item)
            category = self._mapping_category(item)
            reason = str(item.get("reason", ""))
            updated = str(item.get("updated", ""))
            if quote_normalize_term(source) == quote_normalize_term(target):
                target_key = quote_normalize_term(target)
                confirmed_names.add(target_key)
                reference = reference_by_name.get(target_key)
                origin_labels = [origin_label]
                if reference is not None:
                    origin_labels.append("内置参考")
                aliases = [
                    alias
                    for alias in ((reference or {}).get("aliases", ()) or [])
                    if quote_normalize_term(alias) != target_key
                ]
                term_text = target + (f"（别名 {'、'.join(aliases[:3])}）" if aliases else "")
                rows.append({
                    "term_text": term_text,
                    "category": (reference or {}).get("category") or category,
                    "origin_labels": origin_labels,
                    "status": "confirmed",
                    "raw": dict(item),
                    "source": source,
                    "target": target,
                    "reference": reference,
                    "actions": ("编辑", "删除"),
                    "tooltip": "\n".join(filter(None, [
                        f"来源：{' / '.join(origin_labels)}",
                        f"更新：{updated}" if updated else "",
                        (reference or {}).get("source", "") if reference else "",
                    ])),
                    "searchable": " ".join([target, *aliases, category, *origin_labels, reason]).lower(),
                })
            else:
                rows.append({
                    "term_text": f"{source} → {target}",
                    "category": category,
                    "origin_labels": [origin_label],
                    "status": "confirmed",
                    "raw": dict(item),
                    "source": source,
                    "target": target,
                    "reference": None,
                    "actions": ("编辑", "删除"),
                    "tooltip": "\n".join(filter(None, [
                        f"纠错映射：{source} → {target}",
                        f"来源：{origin_label}",
                        f"更新：{updated}" if updated else "",
                    ])),
                    "searchable": f"{source} {target} {category} {origin_label}".lower(),
                })
        seen_reference_keys: set[str] = set()
        for entry in references:
            name = entry["name"]
            name_key = quote_normalize_term(name)
            if name_key in confirmed_names or name_key in seen_reference_keys:
                continue  # already shown as a confirmed row / 引号变体已合并
            seen_reference_keys.add(name_key)
            hidden = bool(entry.get("hidden"))
            aliases = [
                alias
                for alias in (entry.get("aliases", ()) or [])
                if quote_normalize_term(alias) != name_key
            ]
            term_text = name + (f"（别名 {'、'.join(aliases[:3])}）" if aliases else "")
            rows.append({
                "term_text": term_text,
                "category": entry.get("category", "其他"),
                "origin_labels": ["内置参考"],
                "status": "hidden" if hidden else "reference",
                "raw": None,
                "source": name,
                "target": name,
                "reference": entry,
                "actions": ("恢复",) if hidden else ("确认", "隐藏"),
                "tooltip": "\n".join(filter(None, [
                    f"资料：{entry.get('source', '')}",
                    "用户已隐藏，不参与识别弱候选" if hidden else "参考词条：按本批声音证据筛选为弱候选，不会直接机械替换字幕",
                ])),
                "searchable": " ".join([name, *aliases, entry.get("category", ""), entry.get("source", "")]).lower(),
            })
        # Keep builtin reference behavior; learned concepts replace their legacy
        # display rows. Stable concept IDs prevent homonym cards merging.
        from .multilingual_terms import read_concepts, card_rows
        concepts = read_concepts(self.legacy, self._library_key(game_name))
        represented = {n['name'] for c in concepts for n in c['names'].values()}
        represented.update(k[1] for c in concepts for k in c.get('legacy_keys', ()))
        rows = [r for r in rows if r.get('raw') is None and r.get('target') not in represented]
        rows.extend(card_rows(concepts))
        return rows

    @staticmethod
    def _group_term_rows(rows: list[dict]) -> list[dict]:
        """One card per correct spelling (2026-11-03): confirmed mappings that
        lead to the same target become one row whose ``heard`` lists every
        spelling recognition turns into it; ``members`` keeps the original
        mapping rows for editing, selection and deletion.  A target with one
        mapping keeps its original row unchanged."""
        from .glossary_skill import quote_normalize_term

        groups: dict[str, list[dict]] = {}
        order: list[object] = []
        for row in rows:
            if row.get('concept_id'):
                order.append(row)
                continue
            if row.get("status") == "confirmed" and row.get("raw") is not None:
                key = quote_normalize_term(str(row.get("target") or ""))
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(row)
            else:
                order.append(row)
        result = []
        for entry in order:
            if isinstance(entry, dict):
                result.append(entry)
                continue
            members = groups[entry]
            if len(members) == 1:
                row = dict(members[0])
                row["members"] = [members[0]]
                row["heard"] = [str(row["source"])] if row.get("source") != row.get("target") else []
                result.append(row)
                continue
            base = next((m for m in members if m.get("source") == m.get("target")), members[0])
            heard = list(dict.fromkeys(str(m["source"]) for m in members if m.get("source") != m.get("target")))
            row = dict(base)
            labels = list(dict.fromkeys(label for m in members for label in m.get("origin_labels", ())))
            row.update({
                "members": members,
                "heard": heard,
                "origin_labels": labels,
                "term_text": f"{base['target']}（听成 {'、'.join(heard[:3])}）" if heard else str(base.get("term_text", "")),
                "searchable": " ".join(str(m.get("searchable", "")) for m in members),
                "tooltip": "\n".join(dict.fromkeys(str(m.get("tooltip", "")) for m in members if m.get("tooltip"))),
            })
            result.append(row)
        return result

    @staticmethod
    def _member_rows(row: dict) -> list[dict]:
        return list(row.get("members") or [row])

    @staticmethod
    def _count_term_cards(cards):
        stats = {'total': len(cards), 'confirmed': 0, 'reference': 0, 'hidden': 0}
        for row in cards:
            status = str(row.get('status', 'reference'))
            stats[status] = stats.get(status, 0) + 1
        return stats

    def _term_stats(self) -> dict[str, int]:
        return self._count_term_cards(self._group_term_rows(self._unified_term_rows()))

    def _choose_category_filter(self, category):
        index = self.filter_category.findData(category)
        if index >= 0:
            self.filter_category.setCurrentIndex(index)

    def _update_confirm_all_button(self):
        count = getattr(self, '_card_stats', {}).get('reference', 0)
        busy = self._confirming_references
        self.confirm_all_button.setText('正在确认…' if busy else f'全部确认参考词（{count}）')
        self.confirm_all_button.setEnabled(bool(self.state.get('game') and count and not busy))
        self.confirm_all_button.setVisible(bool(count or busy))
        if hasattr(self, 'reference_chip'):
            self.reference_chip.setText(f'{count} 条参考词可确认')
            self.reference_chip.setVisible(bool(count))

    def _confirm_reference_rows(self, rows, *, library_key=None):
        references = [dict(row.get('reference') or {}, name=(row.get('reference') or {}).get('name') or row.get('source', ''))
                      for row in rows if row.get('status') == 'reference']
        count = self.legacy.confirm_reference_terms(library_key or self._library_key(), references)
        if count:
            self._notify_library_changed()
            self.refresh_current_game()
        return count

    @glossary_write_errors
    def confirm_all_references(self):
        if self._confirming_references or not self.state.get('game'):
            return
        rows = [row for row in self._unified_term_rows() if row.get('status') == 'reference']
        if not rows:
            self._update_confirm_all_button()
            return
        self._confirming_references = True
        self.game_list.setEnabled(False)
        self._update_confirm_all_button()
        library_key = self._library_key()
        # Paint the busy state once, then perform one transaction and one refresh.
        QTimer.singleShot(0, lambda: self._finish_confirm_all_references(rows, library_key))

    @glossary_write_errors
    def _finish_confirm_all_references(self, rows, library_key):
        try:
            count = self._confirm_reference_rows(rows, library_key=library_key)
            self._show_toast(f'已确认当前词库 {count} 条参考词。')
        finally:
            self._confirming_references = False
            self.game_list.setEnabled(True)
            self._update_confirm_all_button()

    def refresh_learned(self):
        if self._filter_running:
            self._filter_pending = True
            return
        self._filter_running = True
        try:
            self._apply_term_filter()
        finally:
            self._filter_running = False
            if self._filter_pending:
                self._filter_pending = False
                QTimer.singleShot(0, self.refresh_learned)

    def _prepare_term_rows(self, data_state, rows):
        if self._row_build_state is not None and data_state == self._row_build_state:
            return
        self._row_generation += 1
        generation = self._row_generation
        self._row_build_state = data_state
        # One running preparation and one replacement, never an unbounded queue.
        self._row_build_queued = (generation, data_state, rows)
        self.listing.setEnabled(False)
        bind_text(self.selected_stats, '正在准备术语…')
        self._start_term_rows()

    def _start_term_rows(self):
        if self._row_build_running or self._row_build_queued is None: return
        generation, state, rows = self._row_build_queued
        self._row_build_queued = None
        self._row_build_running = True
        signal = self._term_rows_prepared
        group = type(self)._group_term_rows
        def work():
            try:
                result = (deepcopy(state), rows, deepcopy(group(rows)))
            except Exception as exc:
                result = exc
            try: signal.emit(generation, result)
            except RuntimeError: pass
        threading.Thread(target=work, name='term-row-preparation', daemon=True).start()

    def _receive_term_rows(self, generation, result):
        self._row_build_running = False
        if generation == self._row_generation:
            self._row_build_state = None
            self.listing.setEnabled(True)
            if isinstance(result, Exception):
                bind_text(self.selected_stats, '术语读取失败，请重新选择词库')
            elif result[0] == self._term_data_state():
                self._term_rows_cache = result
                self._rows_prepared_async = True
                self._filter_key = None
                if self.isVisible():
                    self.refresh_learned()
                    stats = self._card_stats
                    bind_text(self.selected_stats, '{value0} 条已确认', value0=stats['confirmed'])
                    bind_text(self.official_stats, '{value0} 条参考{value1}', value0=stats['reference'],
                        value1=f" · {stats['hidden']} 已隐藏" if stats['hidden'] else '')
                    QTimer.singleShot(100, self, self.refresh_learning_suggestions)
        self._start_term_rows()

    def _apply_term_filter(self):
        """Populate the unified term table (learned + builtin references)."""
        import time as _t
        _t_rows0 = _t.perf_counter()
        game_name = self.state["game"]
        self._term_model.set_language(current_language())
        query = self.search.text().strip().lower()
        data_state = self._term_data_state()
        if self._term_rows_cache is None or data_state != self._term_rows_cache[0]:
            rows = self._unified_term_rows() if game_name else []
            if len(rows) > 1000:
                self._prepare_term_rows(self._term_data_state(), rows)
                return
            cards = self._group_term_rows(rows)
            self._rows_prepared_async = False
            self._term_rows_cache = (deepcopy(self._term_data_state()), rows, cards)
            self._filter_key = None
            if self._diagnostics is not None:
                self._diagnostics['rows_built'] += 1
        _, rows, cards = self._term_rows_cache
        # 分类筛选（保持当前选择，重建列表）
        categories = sorted({str(row.get("category", "")) for row in rows if row.get("category")})
        current_category = str(self.filter_category.currentData() or "")
        existing_categories = [
            str(self.filter_category.itemData(index) or "")
            for index in range(self.filter_category.count())
        ]
        desired_categories = ["", *categories]
        if existing_categories != desired_categories:
            self.filter_category.blockSignals(True)
            self.filter_category.clear()
            self.filter_category.addItem(tr("全部分类"), "")
            for category in categories:
                self.filter_category.addItem(tr(category), category)
            category_index = self.filter_category.findData(current_category)
            self.filter_category.setCurrentIndex(max(0, category_index))
            self.filter_category.blockSignals(False)
        category_filter = str(self.filter_category.currentData() or "")
        status_filter = str(self.filter_status.currentData() or "")
        display_language = self.term_display_language.currentData() if hasattr(self, 'term_display_language') else ''
        language_filter = self.term_language_filter.currentData() if hasattr(self, 'term_language_filter') else ''
        self.listing.set_translation_line(bool(display_language))
        from .multilingual_terms import translation_state
        if display_language:
            presentation_key = (id(cards), display_language)
            if getattr(self, '_language_cards_key', None) != presentation_key:
                from .multilingual_terms import card_rows
                self._language_cards = [card_rows([r['concept']], display_language)[0] if r.get('concept') else r for r in cards]
                self._language_cards_key = presentation_key
            cards = self._language_cards
        key = (self._library_key(), query, category_filter, status_filter, current_language(), id(cards), display_language, language_filter)
        if key == self._filter_key:
            return
        self._filter_key = key
        if self._diagnostics is not None:
            self._diagnostics['filtered'] += 1
        items_for_model = []
        self._card_stats = self._count_term_cards(cards)
        if game_name:
            self._library_stats_cache[self._library_key()] = dict(self._card_stats)
        self._update_confirm_all_button()
        for row in cards:
            if row.get('concept'):
                if language_filter == 'missing' and (not display_language or display_language in row['languages']): continue
                if language_filter == 'has' and display_language and display_language not in row['languages']: continue
                if language_filter == 'pending' and (
                        translation_state(row['concept'], display_language) not in ('pending', 'candidate')
                        if display_language else not row.get('pending_languages')): continue
            if query and query not in str(row.get("searchable", "")):
                continue
            if category_filter and category_filter not in row.get('categories', [str(row.get("category", ""))]):
                continue
            if status_filter and str(row.get("status", "")) != status_filter:
                continue
            items_for_model.append(row)
        _t_model0 = _t.perf_counter()
        changed = self._term_model.set_data(items_for_model, prepared=self._rows_prepared_async)
        if changed and self._diagnostics is not None:
            self._diagnostics['results_applied'] += 1
        _t_model1 = _t.perf_counter()
        # 标题计数（统一口径：去重后的词条宇宙）
        stats = self._card_stats
        if current_language() == "en":
            title = f"Terms · {stats['total']} total"
            title += f" · {stats['confirmed']} confirmed · {stats['reference']} reference"
            if stats["hidden"]:
                title += f" · {stats['hidden']} hidden"
            if query or category_filter or status_filter:
                title += f" · showing {len(items_for_model)}"
        else:
            title = f"术语列表 · 共 {stats['total']} 词条（{stats['confirmed']} 已确认 · {stats['reference']} 参考"
            title += f" · {stats['hidden']} 已隐藏" if stats["hidden"] else ""
            title += "）"
            if query or category_filter or status_filter:
                title += f"，当前显示 {len(items_for_model)} 条"
        self.learned_title.setText(title)
        if any(row.get('concept') for row in cards):
            names_count = sum(len(row.get('languages', ())) for row in cards)
            pending_count = sum(row.get('pending_name_count', 0) for row in cards)
            self.learned_title.setText(title + f' · {names_count} 个语言名称 · {pending_count} 个待确认译名')
            if hasattr(self, 'name_counts'):
                self.name_counts.setText(f'· {names_count} 个语言名称')
        if hasattr(self, 'translation_chips'):
            from .multilingual_terms_ui import update_pending
            update_pending(self, cards, display_language)
        self._update_status_counts(self._card_stats)
        self._queue_term_toolbar()
        has_rows = len(items_for_model) > 0
        # Keep the resident view shown while data is prepared. Its empty
        # overlay avoids repeated view hide/show and layout work on filtering.
        self.listing.setVisible(True)
        # 空态区分：完全没词 vs 筛选后没词
        self.listing_empty.setVisible(not has_rows)
        if rows:
            bind_text(self.listing_empty_title, '没有符合筛选条件的词条')
            bind_text(self.listing_empty_label, '调整搜索词或筛选条件，即可看到全部词条。')
            self.start_cards.hide()
        else:
            bind_text(self.listing_empty_title, '让识别更懂你的游戏')
            bind_text(self.listing_empty_label, '加入角色名、地点和专有词，可以减少同音词误识别。')
            self.start_cards.show()
            self.listing_empty_import.setVisible(bool(game_name))
            self.listing_empty_smart.setVisible(bool(game_name))
        _t_rows1 = _t.perf_counter()
        try:
            if GUI_PROFILE_ENABLED:
                print(f"[perf] Term rows model_set ~{int((_t_model1-_t_model0)*1000)}ms  total_refresh_learned ~{int((_t_rows1-_t_rows0)*1000)}ms  shown={len(items_for_model)}")
        except Exception:
            pass
        self.update_remove_action()

    def _term_data_state(self):
        game = self.state['game']
        return (self._library_key(), self.state['mappings'], self.state['builtin_names'],
                self._builtin_cache.get(game), self._builtin_entry_cache.get(game))

    def refresh_learning_suggestions(self):
        self.learning_panel.refresh()

    def _selected_learning_ids(self):
        return self.learning_panel.checked_ids()

    def _accept_learning_suggestions(self, mode=None):
        self.learning_panel.commit(self._selected_learning_ids())

    def _ignore_learning_suggestions(self):
        self.learning_panel.ignore_selected()

    # ------------------------- unified table bulk actions -------------------------

    def _selected_rows_by_status(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for idx in self.listing.selectionModel().selectedRows(0):
            card = self._term_model.data_for_row(idx.row())
            for row in self._member_rows(card) if card else ():
                status = str(row.get("status", ""))
                if status == "confirmed" and row.get("raw") is None:
                    continue
                result.setdefault(status, []).append(row)
        return result

    @glossary_write_errors
    def confirm_selected_references(self):
        """把所选内置参考加入已确认（from==to 的用户确认映射）。"""
        game_name = self.state.get("game", "")
        if not game_name:
            return
        rows = self._selected_rows_by_status().get("reference", [])
        added = self._confirm_reference_rows(rows)
        if added:
            self._show_toast(tr('已确认 {value0} 条参考词条。', value0=added))
        elif rows:
            self._show_toast("所选参考已在已确认词条中。")

    def hide_selected_references(self):
        """隐藏/恢复所选参考词：隐藏词不再进入识别弱候选，也不会被更新复活。"""
        game_name = self.state.get("game", "")
        if not game_name:
            return
        by_status = self._selected_rows_by_status()
        setter = getattr(self.legacy, "set_reference_terms_hidden", None)
        if setter is None:
            self._show_toast("当前版本不支持隐藏参考词条。")
            return
        hidden_count = 0
        restored_count = 0
        to_hide = [
            str((row.get("reference") or {}).get("name") or row.get("source") or "")
            for row in by_status.get("reference", [])
        ]
        to_restore = [
            str((row.get("reference") or {}).get("name") or row.get("source") or "")
            for row in by_status.get("hidden", [])
        ]
        to_hide = [name for name in to_hide if name.strip()]
        to_restore = [name for name in to_restore if name.strip()]
        if to_hide:
            hidden_count = setter(game_name, to_hide, True) or 0
        if to_restore:
            restored_count = setter(game_name, to_restore, False) or 0
        if hidden_count or restored_count:
            self._notify_library_changed()
            self._builtin_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()
            self._refresh_game_item_counts()
            message = []
            if hidden_count:
                message.append(f"已隐藏 {hidden_count} 条")
            if restored_count:
                message.append(f"已恢复 {restored_count} 条")
            self._show_toast("；".join(message) + "。")
        elif to_hide or to_restore:
            self._show_toast("没有可更改的参考词条。")

    def refresh_current_game(self):
        import time as _t
        _t0 = _t.perf_counter()
        try:
            stat = Path(self.legacy.LEARNED_TERMS_PATH).stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except (AttributeError, OSError):
            stamp = None
        if self._library_stamp_observed and stamp != self._library_read_stamp:
            # Home additions and imports can mutate the same store while this
            # resident page is hidden; keep filters/scroll but reject old rows.
            self._notify_library_changed()
        self._library_read_stamp = stamp
        self._library_stamp_observed = True
        game_name = self.state["game"]
        library_id = self._library_key(game_name)
        self._sync_ai_note_button()
        type_labels = self._type_labels()
        selected_type = (
            getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
            if game_name
            else ""
        )
        self._set_selected_header(game_name, type_labels.get(selected_type, translate('其它内容', current_language())))
        # P0-5: MUST profile real timings for "点击 原神 → 650 条首次显示".
        # Segments (as requested): click handler, disk read, JSON parse (if any inside legacy), library lookup,
        # model reset (state), row creation (model list), style/polish (delegate paint), first paint.
        t_click = getattr(self, "_term_click_ts", None)
        if GUI_PROFILE_ENABLED and t_click:
            print(f"[perf] Term click→handler ~{int((_t.perf_counter()-t_click)*1000)}ms game={game_name!r}")
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term switch start game={game_name!r} cached={'yes' if game_name in self._mappings_cache else 'no'}")
        t0 = _t.perf_counter()
        if game_name:
            if library_id in self._mappings_cache:
                t_lookup0 = _t.perf_counter()
                self.state["mappings"] = self._mappings_cache[library_id]
                t_lookup1 = _t.perf_counter()
                if GUI_PROFILE_ENABLED:
                    print(f"[perf] Term mappings cache hit {game_name!r} lookup~{int((t_lookup1-t_lookup0)*1000)}ms")
            else:
                t_disk0 = _t.perf_counter()
                raw = getattr(
                    self.legacy,
                    "user_confirmed_mappings_for_game",
                    self.legacy.learned_mappings_for_game,
                )(library_id)
                t_disk1 = _t.perf_counter()
                self.state["mappings"] = raw or []
                self._mappings_cache[library_id] = self.state["mappings"]
                if GUI_PROFILE_ENABLED:
                    print(f"[perf] Term disk+parse {game_name!r} ~{int((t_disk1-t_disk0)*1000)}ms rows={len(self.state['mappings'])}")
                # "JSON parse" is inside legacy call for this baseline; we log disk+parse combined as requested.
            # model "reset" = state assignment above; now row creation (model) + paint below
            if game_name in self._builtin_cache:
                cached = self._builtin_cache[game_name]
                self.state["builtin_names"], self.state["loaded"] = cached[0], cached[1]
            else:
                t_b0 = _t.perf_counter()
                names, loaded, hidden = self.builtin_for_game(game_name)
                t_b1 = _t.perf_counter()
                self.state["builtin_names"], self.state["loaded"] = names, loaded
                self._builtin_cache[game_name] = (names, loaded, hidden)
                if GUI_PROFILE_ENABLED:
                    print(f"[perf] Term builtin load {game_name!r} ~{int((t_b1-t_b0)*1000)}ms")
        else:
            self.state["builtin_names"], self.state["loaded"] = [], []
        t_state = _t.perf_counter()
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term state+lookup ~{int((t_state-t0)*1000)}ms")
        # Now the visible "row creation" step: populate model (no QWidget per row)
        t_row0 = _t.perf_counter()
        self.refresh_learned()
        if not self._row_build_running:
            self.refresh_learning_suggestions()
        t_row1 = _t.perf_counter()
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term row creation (model set) ~{int((t_row1-t_row0)*1000)}ms")
        stats = dict(getattr(self, "_card_stats", None) or (
            {'confirmed': 0, 'reference': 0, 'hidden': 0} if self._row_build_running else self._term_stats()))
        ((bind_text(self.selected_stats, f"{stats['confirmed']} confirmed") if current_language() == 'en' else bind_text(self.selected_stats, '{value0} 条已确认', value0=stats['confirmed'])) if game_name else bind_text(self.selected_stats, translate('尚未选择', current_language())))
        ((bind_text(self.official_stats, f"{stats['reference']} references" + (f" · {stats['hidden']} hidden" if stats['hidden'] else '')) if current_language() == 'en' else bind_text(self.official_stats, '{value0} 条参考{value1}', value0=stats['reference'], value1=f" · {stats['hidden']} 已隐藏" if stats['hidden'] else '')) if game_name else bind_text(self.official_stats, translate('0 条参考', current_language())))
        if self._row_build_running:
            bind_text(self.selected_stats, '正在准备术语…')
            self.official_stats.setText('…')
        # Schedule the viewport paint without entering a nested event loop from
        # a selection handler.
        try:
            vp = self.listing.viewport()
            if vp is not None:
                vp.update()
        except Exception:
            pass
        t_paint = _t.perf_counter()
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term viewport update scheduled ~{int((t_paint-t_row1)*1000)}ms")
        total = (t_paint - (t_click or t0)) * 1000 if (t_click or t0) else (t_paint - t0) * 1000
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term TOTAL click→update scheduled ~{int(total)}ms game={game_name!r} rows={len(self.state.get('mappings',[]))}")
        _dt = (_t.perf_counter() - _t0) * 1000
        try:
            # P0-5: always emit real measured timing for 650-row switch (disk vs cache)
            if GUI_PROFILE_ENABLED:
                print(f"[perf] Term refresh_current_game {game_name or ''} ~{int(_dt)}ms (mappings={len(self.state.get('mappings',[]))}, builtin={len(self.state.get('builtin_names',[]))})")
            if GUI_PROFILE_ENABLED and hasattr(self, "_term_click_ts") and self._term_click_ts:
                _total = (_t.perf_counter() - self._term_click_ts) * 1000
                print(f"[perf] Term click→first table ~{int(_total)}ms game={game_name!r}")
                self._term_click_ts = None
        except Exception:
            pass
        enabled = bool(game_name)
        for widget in (
            self.search,
            self.listing,
            self.status_segment,
            self.term_try_toggle,
            self.filter_category,
            self.filter_status,
            self.term_editor,
            self.term_alias_editor,
            self.term_category,
            self.add_term_button,
            self.smart_build_button,
            self.import_terms,
            self.export_terms,
            self.ai_history_button,
        ):
            widget.setEnabled(enabled)
        # AI 更新按钮语义由全局任务管理器推导（VII 轮）：切游戏不得把运行中任务刷没。
        self._ensure_task_manager()
        self._refresh_ai_update_buttons()
        self.use_game.setEnabled(enabled)
        self._sync_batch_switch()
        self.share_button.setEnabled(enabled and bool(self.state.get("mappings")))
        self.more_button.setEnabled(enabled)
        # 2026-10-25: built-in libraries can be deleted too (hidden; 新建 → 恢复 brings them back).
        protected = self._game_identity(game_name) in self.protected_game_ids
        self.delete_game_button.setEnabled(enabled)
        self.rename_game_button.setEnabled(enabled and not protected)
        bind_text(self.delete_game_button, translate('从列表删除这个自带词库；软件自带的内容不会被改动，以后可在「新建」里恢复' if protected else '删除当前游戏及其术语', current_language()), property='toolTip')
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))
        self._sync_tab_counts()
        self._refresh_game_item_counts()
        self._refresh_batch_bar()
        self.update_remove_action()
        self._refresh_share_nudge()
        self._refresh_term_guide()
        keep = {self._library_key(), self.state.get('game','')}
        for cache, limit in ((self._mappings_cache,8), (self._builtin_cache,8),
                             (self._builtin_entry_cache,8), (self._library_stats_cache,64)):
            for key in list(cache):
                if len(cache) <= limit: break
                if key not in keep: cache.pop(key, None)

    def update_remove_action(self):
        by_status = self._selected_rows_by_status()
        confirmed_rows = by_status.get("confirmed", [])
        reference_rows = by_status.get("reference", [])
        hidden_rows = by_status.get("hidden", [])
        selected = len(confirmed_rows) + len(reference_rows) + len(hidden_rows)
        ((bind_text(self.remove_terms, f'Delete selected terms ({selected})') if selected else bind_text(self.remove_terms, 'Delete selected terms')) if current_language() == 'en' else (bind_text(self.remove_terms, '删除所选术语（{value0}）', value0=selected) if selected else bind_text(self.remove_terms, '删除所选术语')))
        self.remove_terms.setEnabled(bool(confirmed_rows))
        self.remove_terms.setToolTip(f"只作用于当前可见表格中选中的 {len(confirmed_rows)} 行；筛选隐藏项不会删除。")
        if hasattr(self, "bulk_confirm"):
            self.bulk_confirm.setEnabled(bool(reference_rows))
        if hasattr(self, "bulk_hide"):
            (bind_text(self.bulk_hide, '恢复所选') if hidden_rows and (not reference_rows) else bind_text(self.bulk_hide, '隐藏所选'))
            self.bulk_hide.setEnabled(bool(reference_rows or hidden_rows))
        rows = len(self.listing.selectionModel().selectedRows(0)) if self.listing.selectionModel() else 0
        bar = getattr(self, "selection_bar", None)
        if bar is not None:
            bind_text(self.selection_label, '已选 {count} 条', count=rows)
            self.bulk_confirm.setVisible(bool(reference_rows))
            self.bulk_hide.setVisible(bool(reference_rows or hidden_rows))
            self.remove_terms.setVisible(bool(confirmed_rows))
            bar.setVisible(rows > 0)
            if rows and hasattr(self.listing, "place_overlay"):
                self.listing.place_overlay()

    # ------------------------------------------------------------ 交互

    def select_game(self, current, _previous=None):
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            row = self.game_list.itemWidget(item)
            if isinstance(row, TermGameListRow):
                row.set_selected(item is current)
        game_name = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        self.state["game"] = game_name
        self.state["library_id"] = str(current.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(game_name)) if current else ""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.filter_category.blockSignals(True)
        self.filter_category.setCurrentIndex(0)
        self.filter_category.blockSignals(False)
        # P0 perf: switch header instantly (<100ms feel), defer the 650-row table build.
        type_labels = self._type_labels()
        selected_type = (
            getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
            if game_name else ""
        )
        self._set_selected_header(game_name, type_labels.get(selected_type, translate('其它内容', current_language())))
        # Use cached counts if available for instant badge
        mcount = len(self._mappings_cache.get(game_name, [])) if game_name else 0
        cached_builtin = self._builtin_cache.get(game_name)
        bcount = (
            len([name for name in cached_builtin[0] if name not in set(cached_builtin[2])])
            if cached_builtin and len(cached_builtin) > 2
            else 0
        )
        if game_name:
            ((bind_text(self.selected_stats, f'{mcount} confirmed') if current_language() == 'en' else bind_text(self.selected_stats, '{value0} 条已确认', value0=mcount)) if mcount or bcount else bind_text(self.selected_stats, translate('加载中…', current_language())))
        else:
            bind_text(self.selected_stats, translate('尚未选择', current_language()))
        # Defer the real table + builtin list population to next tick for instant switch feel.
        # P0-5: record click->handler time here (select_game is the click handler for sidebar).
        import time as _t
        self._term_click_ts = _t.perf_counter()
        try:
            if GUI_PROFILE_ENABLED:
                print(f"[perf] Term select_game handler enter game={game_name!r}")
        except Exception:
            pass
        if hasattr(self, 'term_input_language'):
            from .multilingual_terms import default_language
            code = default_language(self.legacy, self._library_key())
            self.term_input_language.setCurrentIndex(max(0, self.term_input_language.findData(code)))
        QTimer.singleShot(0, self.refresh_current_game)

    def apply_filter(self, _text=""):
        if self._diagnostics is not None:
            self._diagnostics['search_triggered'] += 1
        self.refresh_learned()
        if self.state["game"]:
            stats = dict(getattr(self, "_card_stats", None) or self._term_stats())
            (bind_text(self.selected_stats, f"{stats['confirmed']} confirmed") if current_language() == 'en' else bind_text(self.selected_stats, '{value0} 条已确认', value0=stats['confirmed']))

    def search_diagnostics(self):
        return dict(counts=dict(self._diagnostics or {}), library=self._library_key(),
                    query=self.search.text(), result_count=self._term_model.rowCount(),
                    layout=self.listing.layout_diagnostics())

    def _toggle_search(self):
        self.search.setVisible(True)
        self.search.setFocus()
        self.search.selectAll()

    @glossary_write_errors
    def create_game(self):
        game_name = self._canonical(self.game_input.text())
        if not game_name:
            self.game_input.setFocus()
            return
        if not getattr(self.legacy, "ensure_learned_content", lambda *_args: True)(
            game_name, str(self.content_type.currentData() or "game")
        ):
            self._show_toast("词库创建未保存，请检查文件写入权限。", 5000)
            return
        self._notify_library_changed()
        self.add_game_item(game_name, select=True)
        self.game_input.clear()
        self.new_library_panel.hide()
        self._sync_tab_counts()
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))
        (bind_text(self.owner.term_hint, f'Created the {game_name} term library') if current_language() == 'en' else bind_text(self.owner.term_hint, '已创建《{value0}》术语库', value0=game_name))

    def rename_current_game(self):
        game = self.state.get("game", "")
        library_id = self._library_key()
        if not game or self._game_identity(game) in self.protected_game_ids:
            self._show_toast("内置词库保持原名称；可另建用户词库。")
            return
        sheet = QFrame(self)
        sheet.setObjectName('termRenameSheet')
        theme = _sheet_theme()
        sheet.setStyleSheet(f'QFrame#termRenameSheet {{ background:{theme.surface}; border:1px solid {theme.border}; border-radius:12px; }}')
        layout = QVBoxLayout(sheet)
        layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel('词库显示名称（本批启用的稳定 ID 保持）')
        label.setWordWrap(True)
        layout.addWidget(label)
        editor = QLineEdit(game)
        layout.addWidget(editor)
        actions = QHBoxLayout()
        cancel = QPushButton('取消')
        save = QPushButton('保存')
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        sheet.setGeometry(max(12, (self.width()-460)//2), max(32, (self.height()-150)//2), 460, 150)
        sheet.show()
        sheet.raise_()
        editor.setFocus()
        editor.selectAll()
        def apply():
            if editor.text().strip():
                self._rename_library(library_id, editor.text().strip())
                sheet.deleteLater()
        cancel.clicked.connect(sheet.deleteLater)
        save.clicked.connect(apply)
        editor.returnPressed.connect(apply)

    AI_NOTE_TEMPLATES = (
        ('数学 / 理科科普', '这是数学科普内容。字幕里用 $…$ 写的是 LaTeX 数学公式（如 $x^2$、$\\frac{1}{2}$），'
                          '保持原样，不要改成中文读法；也不要把口语里的“x 的平方”擅自改写成公式。'
                          '数学名词按本术语库的写法统一，例如“谢尔宾斯基三角形”“帕斯卡三角形”。'),
        ('游戏实况', '这是游戏实况。选手、角色、技能名按本术语库统一；直播口语、语气词和玩笑保持原样，'
                   '不要改成书面语。不认识的外号先保留，不要硬套术语库里的名字。'),
    )

    def _sync_ai_note_button(self):
        button = getattr(self, 'ai_note_button', None)
        if button is None:
            return
        game = self.state.get("game", "")
        button.setEnabled(bool(game))
        note = getattr(self.legacy, "learned_content_note", lambda _id: "")(self._library_key()) if game else ""
        bind_text(button, '给 AI 的说明（已写）' if note else '给 AI 的说明')

    def edit_ai_note(self):
        """An in-page sheet: the note sent to AI with this library (ADR 0124)."""
        game = self.state.get("game", "")
        if not game:
            return
        from ..glossary.terminology import AI_NOTE_LIMIT
        library_id = self._library_key()
        sheet = QFrame(self)
        sheet.setObjectName('termAiNoteSheet')
        theme = _sheet_theme()
        sheet.setStyleSheet(f'QFrame#termAiNoteSheet {{ background:{theme.surface}; border:1px solid {theme.border}; border-radius:12px; }}')
        layout = QVBoxLayout(sheet)
        layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(tr('给 AI 的说明 · {value0}', value0=game))
        label.setObjectName('termQuickAddTitle')
        layout.addWidget(label)
        hint = QLabel(tr('AI 校对用这个术语库时，会把这段话当作你的说明一起发给 AI：写清这是什么内容、哪些写法要保持、名字怎么统一。'
                         'AI 仍只改错字，不会因此改写整句。'))
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        layout.addWidget(hint)
        editor = QPlainTextEdit()
        editor.setObjectName('termAiNoteEditor')
        editor.setPlainText(getattr(self.legacy, "learned_content_note", lambda _id: "")(library_id))
        editor.setPlaceholderText(tr('例如：这是数学科普，字幕里 $…$ 是公式，保持原样；人名按术语库统一。'))
        layout.addWidget(editor, 1)
        actions = QHBoxLayout()
        examples = QComboBox()
        examples.setObjectName('termAiNoteExamples')
        examples.addItem(tr('插入范例…'), '')
        for title, text in self.AI_NOTE_TEMPLATES:
            examples.addItem(tr(title), text)

        def insert_example(index):
            text = examples.itemData(index)
            if text:
                current = editor.toPlainText().strip()
                editor.setPlainText((current + '\n' if current else '') + str(tr(text)))
                examples.setCurrentIndex(0)
        examples.currentIndexChanged.connect(insert_example)
        actions.addWidget(examples)
        count = QLabel()
        count.setObjectName('muted')
        actions.addWidget(count)
        actions.addStretch(1)
        cancel = QPushButton(tr('取消'))
        save = QPushButton(tr('保存'))
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

        def update_count():
            used = len(editor.toPlainText().strip())
            count.setText(f'{used} / {AI_NOTE_LIMIT}')
            save.setEnabled(used <= AI_NOTE_LIMIT)
        editor.textChanged.connect(update_count)
        update_count()
        width, height = min(620, max(420, self.width() - 48)), 340
        sheet.setGeometry(max(12, (self.width() - width) // 2), max(32, (self.height() - height) // 2), width, height)
        sheet.show()
        sheet.raise_()
        editor.setFocus()
        self._ai_note_sheet = sheet

        def apply():
            if self._save_ai_note(game, library_id, editor.toPlainText()):
                sheet.deleteLater()
                self._ai_note_sheet = None
        cancel.clicked.connect(sheet.deleteLater)
        save.clicked.connect(apply)

    @glossary_write_errors
    def _save_ai_note(self, game, library_id, text):
        if not getattr(self.legacy, "set_learned_content_note", lambda *_args: False)(game, library_id, text):
            self._show_toast("说明没有保存，请检查文件写入权限。", 5000)
            return False
        self._notify_library_changed()
        self._sync_ai_note_button()
        self._show_toast("已保存；AI 校对用这个术语库时会带上这段说明" if text.strip() else "已清空给 AI 的说明", 2600)
        return True

    @glossary_write_errors
    def _rename_library(self, library_id, name):
        if getattr(self.legacy, "rename_learned_content", lambda *_args: False)(library_id, name):
            self.state.update({"game": name, "library_id": library_id})
            self.add_game_item(name, select=True, library_id=library_id)
            self._notify_library_changed()
            self.refresh_current_game()

    def delete_current_game(self):
        game_name = self.state["game"]
        if not game_name:
            return
        self._show_delete_game_confirm(game_name)

    def _show_game_menu(self, item, global_pos):
        """Right click on a library in the list: the same actions as 「⋯」 (2026-10-25)."""
        if item is None:
            return
        self.game_list.setCurrentItem(item)
        game_name = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not game_name:
            return
        menu = QMenu(self)
        menu.setObjectName("termGameMenu")
        if self._game_identity(game_name) not in self.protected_game_ids:
            menu.addAction(tr("改名…")).triggered.connect(lambda _=False: self.rename_current_game())
        menu.addAction(tr("导出词库")).triggered.connect(lambda _=False: self.export_current_library())
        menu.addSeparator()
        menu.addAction(tr("删除词库…")).triggered.connect(lambda _=False: self.delete_current_game())
        self._game_menu = menu
        menu.popup(global_pos)

    def _refresh_restore_builtin(self):
        names = list(getattr(self.legacy, "hidden_runtime_game_profile_names", lambda: [])())
        self.restore_builtin_popup.clear_items()
        for name in names:
            button = AnimatedButton(name)
            button.clicked.connect(lambda _=False, value=name: self.restore_builtin_library(value))
            self.restore_builtin_popup.add_button(button)
        self.restore_builtin_button.setVisible(bool(names))
        bind_text(self.restore_builtin_button, '恢复自带词库（{count}）', count=len(names))

    @glossary_write_errors
    def restore_builtin_library(self, game_name):
        if not getattr(self.legacy, "unhide_runtime_game_profile", lambda _name: False)(game_name):
            self._show_toast("没能恢复这个词库，请检查文件写入权限。", 5000)
            return
        getattr(self.legacy, "migrate_user_verified_profile_terms", lambda: 0)()
        self._notify_library_changed()
        self.add_game_item(game_name, select=True)
        self.new_library_panel.hide()
        self._refresh_restore_builtin()
        self._sync_tab_counts()
        bind_text(self.owner.term_hint, '已恢复《{value0}》', value0=game_name)

    def _show_delete_game_confirm(self, game_name: str):
        """Warm in-app confirm for deleting a game term set (no native black dialog)."""
        if hasattr(self, "_del_game_sheet") and self._del_game_sheet is not None:
            try:
                self._del_game_sheet.setParent(None)
            except Exception:
                pass
        dim = QFrame(self)
        dim.setObjectName("termDelDim")
        dim.setStyleSheet(f"background: {_sheet_theme().overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termDelSheet")
        sheet.setStyleSheet(
            f"QFrame#termDelSheet {{ background:{_sheet_theme().surface}; border:1px solid {_sheet_theme().border}; border-radius:12px; }}"
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        identity = self._library_key(game_name)
        own_terms = self._game_term_count(game_name, identity)
        if identity in self.profile_game_ids:
            # Rows migrated from the built-in profile come back with it; only
            # the user's own rows are lost.
            own_terms = sum(1 for row in getattr(self.legacy, "user_confirmed_mappings_for_game",
                                                 self.legacy.learned_mappings_for_game)(identity)
                            if row.get("verification") != "user_profile_migration")
            # 2026-10-25: a built-in library is hidden, never edited; 新建 → 恢复 brings it back.
            q = bind_text(QLabel(), '要删除软件自带的《{game_name}》吗？', game_name=game_name)
            detail = (bind_text(QLabel(), '它不再出现在列表里，也不再用于识别。你自己加的 {count} 条术语会一起删除；软件自带的内容不会被改动，以后可在「新建」→「恢复自带词库」里放回来。', count=own_terms)
                      if own_terms else
                      bind_text(QLabel(), '它不再出现在列表里，也不再用于识别。软件自带的内容不会被改动，以后可在「新建」→「恢复自带词库」里放回来。'))
        else:
            q = bind_text(QLabel(), '要删除《{game_name}》以及它的术语吗？', game_name=game_name)
            detail = bind_text(QLabel(), '{count} 条术语会一起删除，删除后不能撤销。', count=own_terms)
        q.setWordWrap(True)
        q.setStyleSheet(emphasis_qss("font-weight:600;"))
        lay.addWidget(q)
        detail.setWordWrap(True)
        detail.setObjectName("termHint")
        lay.addWidget(detail)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_del = QPushButton("删除")
        do_del.setStyleSheet(
            emphasis_qss("QPushButton { background:#f6e9e5; color:#8a5a4c; border:1px solid #e3c9c2; border-radius:10px; padding:6px 14px; font-weight:700; }"
            "QPushButton:hover { background:#f3e0db; }")
        )
        row.addWidget(cancel)
        row.addWidget(do_del)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            sw = 440
            sh = max(140, lay.totalHeightForWidth(sw) if lay.hasHeightForWidth() else sheet.sizeHint().height())
            sheet.setGeometry((pr.width() - sw)//2, max(40, (pr.height() - sh)//2 - 10), sw, sh)

        _place()
        sheet.show()
        sheet.raise_()

        def _cleanup():
            try:
                dim.deleteLater()
            except Exception:
                pass
            try:
                sheet.deleteLater()
            except Exception:
                pass
            self._del_game_sheet = None
            self._del_game_dim = None

        self._del_game_sheet = sheet
        self._del_game_dim = dim

        def _confirm():
            identity = self._library_key(game_name)
            learned_deleted = getattr(
                self.legacy, "delete_learned_game", lambda _name: False
            )(identity)
            getattr(self.legacy, "delete_runtime_game_history", lambda _name: False)(game_name)
            profile_hidden = False
            if identity in self.profile_game_ids:
                profile_hidden = getattr(
                    self.legacy, "hide_runtime_game_profile", lambda _name: False
                )(game_name)
            enabled_ids = [
                item for item in self.owner._enabled_glossary_ids()
                if item != identity
            ]
            self.owner.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
            self.owner.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled_ids
            self.owner._save_glossary_settings()
            if self._game_identity(self.game_box_text()) == self._game_identity(game_name):
                self.owner.game_box.setCurrentText("")
                self.owner.terms.setChecked(False)
            # remove from list if present
            for i in range(self.game_list.count()):
                it = self.game_list.item(i)
                if it and str(it.data(Qt.ItemDataRole.UserRole + 1) or self._game_identity(it.data(Qt.ItemDataRole.UserRole) or it.text())) == identity:
                    self.game_list.takeItem(i)
                    break
            self.state["game"] = ""
            self.state["library_id"] = ""
            self._notify_library_changed()
            _cleanup()
            if self.game_list.count():
                self.game_list.setCurrentRow(0)
            else:
                self.refresh_current_game()
            (bind_text(self.owner.term_hint, f'Deleted {game_name} and its terms') if current_language() == 'en' else (bind_text(self.owner.term_hint, '已删除《{value0}》及其术语', value0=game_name) if learned_deleted or profile_hidden else bind_text(self.owner.term_hint, '《{value0}》没有可删除的用户术语', value0=game_name)))

        def _cancel():
            _cleanup()

        do_del.clicked.connect(_confirm)
        cancel.clicked.connect(_cancel)
        sheet.installEventFilter(self)
        self._del_game_cleanup = _cleanup

    @glossary_write_errors
    def add_single_term(self):
        if hasattr(self, 'term_input_language'):
            from .multilingual_terms import concept, save_concept, read_concepts
            from .multilingual_terms_ui import refresh
            target, mishearings = self._parsed_quick_terms()
            if not target: self._show_toast('请填写正确写法'); return False
            identity = getattr(self, '_quick_draft_library_id', '') or self._library_key() or '通用词库'
            value = concept(target, self.term_input_language.currentData(), category=str(self.term_category.currentData() or '其他'))
            name = next(iter(value['names'].values()))
            name.update(mishearings=mishearings, user_modified=True, sources=['手动'])
            code = self.term_input_language.currentData()
            for existing in read_concepts(self.legacy, identity):
                old = existing['names'].get(code)
                if old and old['name'] != target and any(a.casefold() in {s.casefold() for s in (old['name'], *old.get('mishearings', ()))} for a in mishearings):
                    self._show_toast('误听写法已指向另一个词条；请在详情中检查冲突或关联。输入已保留。')
                    return False
            try:
                save_concept(self.legacy, identity, value, input_language=self.term_input_language.currentData())
                self.term_editor.clear(); self.term_alias_editor.clear(); refresh(self)
                self._show_toast('已保存；在“名称与译名”中补充其他语言。')
                return True
            except Exception as exc: self._show_toast(str(exc)); return False
        # 2026-09-02：未选择游戏/内容时不再静默返回（表现为"没办法添加词语"）——
        # 落到「通用词库」并提示；输入为空也给 toast 反馈。
        draft_id = getattr(self, '_quick_draft_library_id', '') or self._library_key()
        game_name = getattr(self.legacy, 'glossary_display_name', str)(draft_id) if draft_id else ''
        if not game_name:
            game_name = "通用词库"
            self._show_toast("未选择游戏/内容，已添加到「通用词库」")
        value = self.term_editor.text().strip()
        if not value:
            self._show_toast("请先输入术语内容（原文或 原文=译名）")
            return False
        target, aliases = self._parsed_quick_terms()
        if not target:
            self._show_toast('规范词不能为空；输入已保留。')
            return False
        category = str(self.term_category.currentData() or "其他")
        # A quick arrow alone remains a single mapping for compatibility.
        source, quick_target = self.parse_term(value)
        parsed = parse_term_line(value)
        if parsed.get('parse_error') or not source:
            self._show_toast('别名或规范词不能为空；输入已保留。')
            return False
        pairs = [(target, target)] if source == quick_target or self.term_alias_editor.text().strip() else []
        pairs.extend((alias, target) for alias in aliases)
        checked = validate_term_records([{'from': left, 'to': right, 'category': category}
            for left, right in pairs], self.legacy.learned_mappings_for_game(draft_id or self._library_key(game_name)))
        if any(row['status'] in {'invalid', 'conflict'} for row in checked):
            self._show_toast('；'.join(row['reason'] for row in checked if row['status'] in {'invalid', 'conflict'}) + '；输入已保留。')
            return False
        added = 0
        for from_text, to_text in pairs:
            added += bool(self.legacy.add_learned_mapping(
                draft_id or self._library_key(game_name), from_text, to_text, category=category, origin="手动"))
        stored = self.legacy.learned_mappings_for_game(draft_id or self._library_key(game_name))
        all_saved = all(any(row.get('from') == source and row.get('to') == canonical
                       and row.get('confirmed', True) for row in stored) for source, canonical in pairs)
        if added or all_saved:
            self.term_editor.clear()
            self.term_alias_editor.clear()
            self._notify_library_changed()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            if not self.state.get("game"):
                self.state["game"] = game_name
                self.add_game_item(game_name, select=True)
            self.refresh_current_game()
            (bind_text(self.owner.term_hint, f'Added term: {target} ({game_name})') if current_language() == 'en' else bind_text(self.owner.term_hint, '已添加术语：{value0}（《{value1}》）', value0=target, value1=game_name))
            if (draft_id or self._library_key(game_name)) not in self.owner._enabled_glossary_ids():
                self.owner.term_hint.setText(self.owner.term_hint.text() + '；已保存，尚未用于本批，请点击「用于本批字幕」。')
            return True
        else:
            # Replace native info with a small warm in-app toast sheet.
            self._show_toast(tr('添加术语失败：该术语已存在或内容为空。'))
            return False

    def _show_toast(self, text: str, ms: int = 1600):
        """Tiny warm toast over current view (no native dialog)."""
        try:
            t = bind_text(QLabel(self), text)
            t.setObjectName("termToast")
            toast_theme = _sheet_theme()
            t.setStyleSheet(f"background:{toast_theme.surface_elevated}; color:{toast_theme.text}; border:1px solid {toast_theme.border}; border-radius:10px; padding:8px 12px;")
            t.setWordWrap(True)
            t.adjustSize()
            pr = self.rect()
            tw, th = t.sizeHint().width(), t.sizeHint().height()
            t.setGeometry((pr.width() - tw)//2, pr.height() - th - 16, tw, th)
            t.show()
            t.raise_()
            QTimer.singleShot(ms, lambda: (t.hide(), t.deleteLater()))
        except Exception:
            pass

    def _show_association_sheet(self):
        """Explicit, generic alias association; no suggested hardcoded mappings."""
        if not self.prepare_for_task():
            return
        library_id = self._library_key()
        if not library_id:
            self._show_toast('请先选择要保存关联的词库。')
            return
        game_name = self.state['game']
        dialog = QDialog(self)
        from ..design.studio_theme import apply_secondary_surface_theme
        apply_secondary_surface_theme(dialog)
        dialog.setWindowTitle('确认别名关联')
        layout = QVBoxLayout(dialog)
        note = QLabel(f'保存到《{game_name}》。规范词保持已有拼写；新增拼写会作为独立词条保存。')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        alias = QLineEdit()
        alias.setPlaceholderText('请输入字幕中实际出现的昵称或错词')
        target = QComboBox()
        target.setEditable(True)
        existing = self.legacy.learned_mappings_for_game(library_id)
        target.addItems(list(dict.fromkeys(str(row.get('to', '')) for row in existing if row.get('to'))))
        target.setCurrentText(self.term_try_expected.text().strip())
        form.addRow('别名 / 常见错词', alias)
        form.addRow('规范词（逐字保存）', target)
        layout.addLayout(form)
        preview = QLabel()
        preview.setWordWrap(True)
        layout.addWidget(preview)
        actions = QHBoxLayout()
        cancel = QPushButton('取消')
        save = QPushButton('确认关联并保存')
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        self.association_alias = alias
        self.association_target = target
        self.association_preview = preview
        self.association_save_button = save
        self.association_dialog = dialog
        proposed = []

        def update_preview(*_args):
            nonlocal proposed
            a, t = alias.text().strip(), target.currentText().strip()
            proposed = preview_term_import(json.dumps({'mappings': [
                {'from': t, 'to': t, 'category': str(self.term_category.currentData() or '其他')},
                {'from': a, 'to': t, 'category': str(self.term_category.currentData() or '其他')}]
                }, ensure_ascii=False), self.legacy.learned_mappings_for_game(library_id))
            preview.setText('\n'.join(f"{row['from']} → {row['to']}：{row['reason']}" for row in proposed))
            save.setEnabled(bool(a and t) and all(row['status'] in {'ready', 'duplicate'} for row in proposed))

        @glossary_write_errors(owner=self)
        def submit():
            update_preview()
            if not save.isEnabled():
                return
            for row in proposed:
                if row['status'] == 'ready':
                    self.legacy.add_learned_mapping(library_id, row['from'], row['to'],
                        category=row['category'], origin='用户确认')
            self._notify_library_changed()
            self.refresh_current_game()
            dialog.accept()
            self.try_sentence()

        alias.textChanged.connect(update_preview)
        target.currentTextChanged.connect(update_preview)
        save.clicked.connect(submit)
        cancel.clicked.connect(dialog.reject)
        dialog.finished.connect(lambda *_args: setattr(self, 'association_dialog', None))
        update_preview()
        dialog.resize(600, dialog.sizeHint().height())
        dialog.open()
        alias.setFocus()

    # ------------------------- P0: Warm in-app Edit / Delete (no native black dialogs) -------------------------

    def _show_edit_sheet(self, mapping: dict, anchor: QRect | None = None, members: list[dict] | None = None):
        """Edit one term in a small card.

        2026-11-03: with ``anchor`` (the clicked card in page coordinates) the
        card opens on top of that term card and the page is not dimmed, so the
        pointer does not travel; a press outside, Esc or 取消 closes it.
        Without an anchor (MCP, audits) it is centred as before.  ``members``
        (the mapping rows of one card) edits the whole card: the correct
        spelling and every 「常被听成」 spelling, separated by 、.
        """
        game_name = self.state["game"]
        if not game_name:
            return
        source = str(mapping.get("from") or "")
        target = str(mapping.get("to") or "")
        current = target
        theme = _sheet_theme()

        # Local dim layer + card (child of this content so no new HWND).
        if getattr(self, "_edit_sheet", None) is not None:
            cleanup = getattr(self, "_edit_cleanup", None)
            if callable(cleanup):
                cleanup()
            else:
                self._edit_sheet.setParent(None)

        dim = _SheetDim(self)
        dim.setObjectName("termEditDim")
        dim.setStyleSheet("background: transparent; border:0;" if anchor is not None
                          else f"background: {theme.overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termEditSheet")
        sheet.setStyleSheet(
            emphasis_qss(f"QFrame#termEditSheet {{ background:{theme.surface}; border:1.5px solid {theme.accent}; border-radius:14px; }}"
            f"QFrame#termEditSheet QLabel {{ background: transparent; border: 0; }}"
            f"QLabel#termEditLabel {{ color:{theme.text_muted}; font-size:12px; font-weight:600; }}"
            f"QLabel#termEditSource {{ color:{theme.text_muted}; font-size:12px; }}")
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        title_row = QHBoxLayout()
        title = bind_text(QLabel(), '修改「{term}」', term=current)
        title.setStyleSheet(emphasis_qss("font-weight:700; font-size:14px;"))
        title_row.addWidget(title)
        title_row.addStretch(1)
        source_note = bind_text(QLabel(), '来源：{origin}', origin=self._mapping_origin(mapping))
        source_note.setObjectName("termEditSource")
        title_row.addWidget(source_note)
        lay.addLayout(title_row)

        from PySide6.QtWidgets import QCheckBox, QGridLayout
        fields = QGridLayout()
        fields.setHorizontalSpacing(10)
        fields.setVerticalSpacing(4)
        term_edit = QLineEdit(current)
        bind_text(term_edit, '最终字幕使用的准确写法（大小写原样保留）', property='placeholderText')
        if members is not None:
            heard = list(dict.fromkeys(str(m.get("source")) for m in members if m.get("source") != m.get("target")))
            alias_edit = QLineEdit("、".join(heard))
            bind_text(alias_edit, '多个用顿号隔开；留空表示只帮识别写对', property='placeholderText')
        else:
            alias_edit = QLineEdit("" if source == target else source)
            bind_text(alias_edit, '识别常写错成什么；留空表示只帮识别写对', property='placeholderText')
        for column, (text, editor) in enumerate((("正确写法", term_edit), ("常被听成", alias_edit))):
            label = bind_text(QLabel(), text)
            label.setObjectName("termEditLabel")
            fields.addWidget(label, 0, column)
            fields.addWidget(editor, 1, column)
        lay.addLayout(fields)
        self.edit_canonical = term_edit
        self.edit_alias = alias_edit

        options = QHBoxLayout()
        options.setSpacing(10)
        cat = FramelessPopupCombo()
        for c in ("选手 ID", "人物", "角色", "Boss", "物品", "方块", "阵营", "地点", "模型", "技能", "事件", "其他"):
            cat.addItem(c, c)
        cur_cat = self._mapping_category(mapping) or "其他"
        idx = cat.findData(cur_cat)
        if idx < 0:
            cat.addItem(cur_cat, cur_cat)
            idx = cat.findData(cur_cat)
        cat.setCurrentIndex(idx)
        cat.setFixedWidth(116)
        self.edit_category = cat
        category_label = bind_text(QLabel(), '分类')
        category_label.setObjectName("termEditLabel")
        options.addWidget(category_label)
        options.addWidget(cat)
        options.addStretch(1)
        lay.addLayout(options)
        uses = QHBoxLayout()
        uses.setSpacing(14)
        correction = QCheckBox('用于校对／替换')
        emphasis = QCheckBox('用于字幕视觉强调')
        correction.setChecked(bool(mapping.get('correction_enabled', True)))
        emphasis.setChecked(bool(mapping.get('emphasis_enabled', False)))
        self.edit_correction_enabled, self.edit_emphasis_enabled = correction, emphasis
        uses.addWidget(correction)
        uses.addWidget(emphasis)
        uses.addStretch(1)
        lay.addLayout(uses)

        row = QHBoxLayout()
        delete = AnimatedButton("删除")
        delete.setObjectName("termDangerButton")
        bind_text(delete, '删除这条词', property='toolTip')
        self.edit_delete_button = delete
        row.addWidget(delete)
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        save = QPushButton("保存")
        self.edit_save_button = save
        save.setObjectName("workshopAction")
        save.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            if anchor is None:
                sw, sh = 480, max(sheet.sizeHint().height(), 220)
                sheet.setGeometry((pr.width() - sw)//2, max(40, (pr.height() - sh)//2 - 20), sw, sh)
                return
            sw = min(max(anchor.width() * 2 + 8, 400), 540, max(320, pr.width() - 16))
            sh = sheet.sizeHint().height()
            x = min(max(8, anchor.x()), max(8, pr.width() - sw - 8))
            y = anchor.y() if anchor.y() + sh <= pr.height() - 8 else max(8, anchor.bottom() - sh)
            sheet.setGeometry(x, y, sw, sh)

        _place()
        sheet.show()
        sheet.raise_()
        term_edit.setFocus()
        term_edit.selectAll()

        def _cleanup():
            try:
                dim.deleteLater()
            except Exception:
                pass
            try:
                sheet.deleteLater()
            except Exception:
                pass
            self._edit_sheet = None
            self._edit_dim = None
            self._edit_pending = None
            self._edit_submit = None
            self._edit_preview = None

        self._edit_sheet = sheet
        self._edit_dim = dim
        def _save_group():
            """One card = one correct spelling and every spelling heard as it."""
            new_target = term_edit.text().strip()
            aliases = list(dict.fromkeys(a.strip() for a in __import__("re").split(r"[、,，;；\n]+", alias_edit.text())
                                         if a.strip() and a.strip() != new_target))
            key = self._library_key(game_name)
            member_keys = {(m.get("source"), m.get("target")) for m in members}
            existing = [r for r in self.legacy.learned_mappings_for_game(key)
                        if (r.get("from"), r.get("to")) not in member_keys]
            category = str(cat.currentData() or "其他")
            category_changed = category != self._mapping_category(mapping)
            sources = {str(m.get("source")) for m in members}
            new_pairs = [(alias, new_target) for alias in aliases if alias not in sources]
            checked = validate_term_records([{"from": a, "to": t, "category": category} for a, t in new_pairs], existing)
            problems = [row["reason"] for row in checked if row["status"] in {"invalid", "conflict"}]
            if problems:
                self._show_toast("；".join(problems) + "；输入已保留。")
                return False
            correction_flag = correction.isChecked() if correction.isChecked() != bool(mapping.get("correction_enabled", True)) else None
            emphasis_flag = emphasis.isChecked() if emphasis.isChecked() != bool(mapping.get("emphasis_enabled", False)) else None
            removed = []
            for member in members:
                raw = member.get("raw") or {}
                old_source, old_target = str(member.get("source")), str(member.get("target"))
                if old_source == old_target:
                    new_source = new_target
                elif old_source in aliases:
                    new_source = old_source
                else:
                    removed.append((old_source, old_target))
                    continue
                member_category = category if category_changed else self._mapping_category(raw)
                if ((new_source, new_target) == (old_source, old_target) and not category_changed
                        and correction_flag is None and emphasis_flag is None):
                    continue
                if not self.legacy.edit_learned_mapping(
                        key, (old_source, old_target), new_source, new_target, category=member_category,
                        origin=self._mapping_origin(raw), correction_enabled=correction_flag,
                        emphasis_enabled=emphasis_flag):
                    bind_text(self.owner.term_hint, '修改后的术语已存在或内容为空')
                    self._show_toast(tr('「{value0}」没有改成功：修改后的术语已存在或内容为空。', value0=old_source))
                    return False
            if removed:
                self.legacy.delete_learned_mappings(key, removed)
            for alias, target_text in new_pairs:
                self.legacy.add_learned_mapping(key, alias, target_text, category=category, origin="手动")
            _cleanup()
            self._notify_library_changed()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()
            return True

        @glossary_write_errors(owner=self)
        def _save():
            val = term_edit.text().strip()
            if not val:
                self._show_toast('规范词不能为空；输入已保留。')
                return False
            if members is not None:
                return _save_group()
            new_target = val
            new_source = alias_edit.text().strip() or val
            if (new_source, new_target) == (source, target) and (cat.currentData() or "其他") == self._mapping_category(mapping) and correction.isChecked() == bool(mapping.get("correction_enabled", True)) and emphasis.isChecked() == bool(mapping.get("emphasis_enabled", False)):
                _cleanup()
                return True
            ok = self.legacy.edit_learned_mapping(
                self._library_key(game_name), (source, target), new_source, new_target,
                category=str(cat.currentData() or "其他"), origin=self._mapping_origin(mapping),
                correction_enabled=correction.isChecked(), emphasis_enabled=emphasis.isChecked())
            if not ok:
                # keep simple; surface via owner hint
                bind_text(self.owner.term_hint, '修改后的术语已存在或内容为空')
                return False
            _cleanup()
            self._notify_library_changed()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()
            return True

        def _cancel():
            _cleanup()

        def _delete():
            key = (source, target)
            _cleanup()
            if members is not None:
                self._show_delete_confirm((target, target), keys=[(str(m.get("source")), str(m.get("target")))
                                                                  for m in members])
            else:
                self.delete_mapping(key)

        save.clicked.connect(_save)
        cancel.clicked.connect(_cancel)
        delete.clicked.connect(_delete)
        term_edit.returnPressed.connect(_save)
        alias_edit.returnPressed.connect(_save)
        from PySide6.QtGui import QKeySequence, QShortcut
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), sheet)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(_cancel)
        # A press outside closes it — but not the second press of the
        # double-click that may have opened it.
        import time as _time
        opened_at = _time.monotonic()
        dim.pressed.connect(lambda: _cancel() if _time.monotonic() - opened_at
                            >= QApplication.doubleClickInterval() / 1000 else None)

        # keep refs so we can close on resize etc.
        self._edit_cleanup = _cleanup
        if members is not None:
            initial = (alias_edit.text(), term_edit.text(), cat.currentData(), correction.isChecked(), emphasis.isChecked())
            self._edit_pending = lambda: (alias_edit.text(), term_edit.text(), cat.currentData(),
                                          correction.isChecked(), emphasis.isChecked()) != initial
            self._edit_preview = lambda: (f"《{game_name}》：{term_edit.text().strip()}"
                                          + (f"（听成 {alias_edit.text().strip()}）" if alias_edit.text().strip() else ""))
        else:
            self._edit_pending = lambda: ((alias_edit.text().strip() or term_edit.text().strip(), term_edit.text().strip(),
                cat.currentData() or '其他', correction.isChecked(), emphasis.isChecked()) != (source, target, self._mapping_category(mapping), bool(mapping.get('correction_enabled', True)), bool(mapping.get('emphasis_enabled', False))))
            self._edit_preview = lambda: f"《{game_name}》：{alias_edit.text().strip() or term_edit.text().strip()} → {term_edit.text().strip()}"
        self._edit_submit = _save

    def _show_delete_confirm(self, key, keys: list | None = None):
        """Small warm delete confirm, replacing QMessageBox.question.

        ``keys`` (2026-11-03): every mapping of one card, deleted together."""
        game_name = self.state["game"]
        if not game_name:
            return
        source, target = key
        label = target if source == target else f"{source} → {target}"
        keys = list(keys or [key])

        if hasattr(self, "_del_sheet") and self._del_sheet is not None:
            try:
                self._del_sheet.setParent(None)
            except Exception:
                pass

        dim = QFrame(self)
        dim.setObjectName("termDelDim")
        dim.setStyleSheet(f"background: {_sheet_theme().overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termDelSheet")
        sheet.setStyleSheet(
            f"QFrame#termDelSheet {{ background:{_sheet_theme().surface}; border:1px solid {_sheet_theme().border}; border-radius:12px; }}"
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        q = bind_text(QLabel(), '确定删除「{label}」吗？', label=label)
        q.setWordWrap(True)
        q.setStyleSheet(emphasis_qss("font-weight:600;"))
        lay.addWidget(q)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_del = QPushButton("删除")
        # low-saturation danger
        do_del.setStyleSheet(
            emphasis_qss("QPushButton { background:#f6e9e5; color:#8a5a4c; border:1px solid #e3c9c2; border-radius:10px; padding:6px 14px; font-weight:700; }"
            "QPushButton:hover { background:#f3e0db; }")
        )
        row.addWidget(cancel)
        row.addWidget(do_del)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            sw, sh = 360, 120
            sheet.setGeometry((pr.width() - sw)//2, max(40, (pr.height() - sh)//2 - 10), sw, sh)

        _place()
        sheet.show()
        sheet.raise_()

        def _cleanup():
            try:
                dim.deleteLater()
            except Exception:
                pass
            try:
                sheet.deleteLater()
            except Exception:
                pass
            self._del_sheet = None
            self._del_dim = None

        self._del_sheet = sheet
        self._del_dim = dim

        def _confirm():
            self.legacy.delete_learned_mappings(self._library_key(game_name), keys)
            self._notify_library_changed()
            _cleanup()
            self.refresh_current_game()

        def _cancel():
            _cleanup()

        do_del.clicked.connect(_confirm)
        cancel.clicked.connect(_cancel)
        sheet.installEventFilter(self)
        self._del_cleanup = _cleanup

    def edit_mapping(self, mapping: dict, anchor: QRect | None = None, members: list[dict] | None = None):
        if mapping.get('concept_id'):
            from .multilingual_terms_ui import open_editor
            open_editor(self, mapping['concept_id'])
            return
        self._show_edit_sheet(mapping, anchor=anchor, members=members)

    def delete_mapping(self, key):
        self._show_delete_confirm(key)

    def remove_selected_terms(self):
        """Delete user-confirmed mappings; builtin reference rows revert to 参考 status."""
        identities = [self._term_model.data_for_row(i.row()).get('concept_id')
                      for i in self.listing.selectionModel().selectedRows(0)]
        identities = [i for i in identities if i]
        if identities:
            if QMessageBox.question(self, '删除概念词条', f'删除所选 {len(identities)} 个词条及其所有语言名称？') == QMessageBox.StandardButton.Yes:
                from .multilingual_terms import delete_concept
                from .multilingual_terms_ui import refresh
                for identity in identities: delete_concept(self.legacy, self._library_key(), identity)
                refresh(self)
            return
        game_name = self.state["game"]
        if not game_name:
            return
        keys = []
        for idx in self.listing.selectionModel().selectedRows(0):
            card = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
            for rd in self._member_rows(card) if card else ():
                if rd.get("status") == "confirmed" and rd.get("raw"):
                    st = (rd.get("source"), rd.get("target"))
                    if st[0] and st[1]:
                        keys.append(st)
        if keys and self.legacy.delete_learned_mappings(self._library_key(game_name), keys):
            self._notify_library_changed()
            self.refresh_current_game()

    # P0-5: action handlers for the table (no per-row QWidgets)
    def _on_table_double_click(self, idx: QModelIndex):
        if not idx.isValid():
            return
        rd = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
        if rd and rd.get("raw") and getattr(self, "_edit_sheet", None) is None:
            self.edit_mapping(rd["raw"], anchor=self._card_anchor(idx), members=self._member_rows(rd))

    @glossary_write_errors
    def _on_table_clicked(self, idx: QModelIndex):
        if not idx.isValid():
            return
        # Only react on the 操作 column (col 4) for the row's primary action.
        if idx.column() != 4:
            return
        rd = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
        if rd:
            self._run_row_action(rd)

    def _run_row_action(self, rd: dict):
        """The row's primary action: edit a confirmed term, 收下 a reference, 恢复 a hidden one."""
        if rd.get('concept_id'):
            from .multilingual_terms_ui import open_editor
            open_editor(self, rd['concept_id']); return
        status = str(rd.get("status", ""))
        if status == "confirmed" and rd.get("raw"):
            self.edit_mapping(rd["raw"], members=rd.get("members"))
        elif status == "reference":
            # 确认单条参考（from==to 用户确认映射）
            game_name = self.state.get("game", "")
            reference = rd.get("reference") or {}
            name = str(reference.get("name") or rd.get("source") or "").strip()
            if game_name and name and self._confirm_reference_rows([rd]):
                self._show_toast(tr('已确认「{value0}」。', value0=name))
        elif status == "hidden":
            game_name = self.state.get("game", "")
            name = str((rd.get("reference") or {}).get("name") or rd.get("source") or "")
            setter = getattr(self.legacy, "set_reference_terms_hidden", None)
            if game_name and name and setter and setter(game_name, [name], False):
                self._notify_library_changed()
                self._builtin_cache.pop(game_name, None)
                self._builtin_entry_cache.pop(game_name, None)
                self.refresh_current_game()
                self._show_toast(tr('已恢复「{value0}」。', value0=name))

    def show_import_dialog(self, *, mapping_mode=False):
        """P0: Warm hosted import sheet inside TermLibrary content (no native SpringDialog)."""
        game_name = self.state["game"]
        if not game_name:
            return
        library_id = self._library_key(game_name)

        # Avoid stacking multiple import sheets
        if hasattr(self, "_import_sheet") and self._import_sheet is not None:
            self._import_sheet.raise_()
            self.import_editor.setFocus()
            return

        dim = QFrame(self)
        dim.setObjectName("termImportDim")
        dim.setStyleSheet(f"background: {_sheet_theme().overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termImportSheet")
        sheet.setStyleSheet(
            f"QFrame#termImportSheet {{ background:{_sheet_theme().surface}; border:1px solid {_sheet_theme().border}; border-radius:12px; }}"
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        title = bind_text(QLabel(), '批量导入术语｜{game_name}', game_name=game_name)
        title.setStyleSheet(emphasis_qss("font-weight:700; font-size:14px;"))
        lay.addWidget(title)

        mode = QComboBox()
        mode.addItem('普通术语（保留完整多词名称）', False)
        mode.addItem('快捷纠错 / 批量映射（别名 → 规范词）', True)
        mode.setCurrentIndex(1 if mapping_mode else 0)
        self.import_mode = mode
        lay.addWidget(mode)
        hint = QLabel('快捷映射支持 →、->、=>、两侧有空格的 -、Tab 或两个词之间的空格。多词名称请用引号或明确分隔符；名称内连字符不会自动拆分。可直接编辑下表，冲突不会静默覆盖。')
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lay.addWidget(hint)

        editor = QPlainTextEdit()
        editor.setTabChangesFocus(False)
        bind_text(editor, '别名 -> 规范词\n"多词别名" "多词规范词"', property='placeholderText')
        lay.addWidget(editor, 1)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(['行', '别名 / 常见错词', '规范写法 / 最终输出', '预览与结果'])
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(table, 2)
        self.import_table = table
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setMaximumHeight(70)
        lay.addWidget(preview)
        self.import_editor = editor
        self.import_preview = preview

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_imp = QPushButton("确认导入可用项")
        self.import_save_button = do_imp
        do_imp.setObjectName("workshopAction")
        row.addWidget(cancel)
        row.addWidget(do_imp)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            sw = min(920, max(340, pr.width() - 48))
            sh = min(720, max(400, pr.height() - 60))
            sheet.setGeometry((pr.width() - sw)//2, max(24, (pr.height() - sh)//2 - 10), sw, sh)

        _place()
        sheet.show()
        sheet.raise_()
        editor.setFocus()

        def _cleanup():
            try:
                dim.deleteLater()
            except Exception:
                pass
            try:
                sheet.deleteLater()
            except Exception:
                pass
            self._import_sheet = None
            self._import_dim = None
            self._import_pending = None
            self._import_submit = None
            self._import_cleanup = None

        self._import_sheet = sheet
        self._import_dim = dim

        def _render_rows(rows):
            self._import_rows = rows
            table.blockSignals(True)
            table.setRowCount(len(rows))
            for index, record in enumerate(rows):
                for column, value in enumerate((record.get('line', index+1), record['from'], record['to'], record['reason'])):
                    item = QTableWidgetItem(str(value))
                    if column in (0, 3):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(record.get('raw', '') + '\n' + record['reason'])
                    table.setItem(index, column, item)
            table.blockSignals(False)
            preview.setPlainText('\n'.join(f"第{row.get('line', index+1)}行：{row['from']} → {row['to']}｜{row['reason']}"
                for index, row in enumerate(rows)))
            do_imp.setEnabled(any(row['status'] == 'ready' for row in rows))

        def _preview():
            try:
                _render_rows(preview_term_import(editor.toPlainText(), self.legacy.learned_mappings_for_game(library_id),
                    mapping_mode=bool(mode.currentData())))
            except (ValueError, TypeError) as exc:
                self._import_rows = []
                table.setRowCount(0)
                preview.setPlainText("导入格式无效：" + str(exc))
                do_imp.setEnabled(False)
        def _edited(item):
            if item.column() not in (1, 2):
                return
            records = [dict(row) for row in self._import_rows]
            record = records[item.row()]
            record['from'] = table.item(item.row(), 1).text().strip()
            record['to'] = table.item(item.row(), 2).text().strip()
            record.pop('parse_error', None)
            _render_rows(validate_term_records(records, self.legacy.learned_mappings_for_game(library_id)))
        table.itemChanged.connect(_edited)
        editor.textChanged.connect(_preview)
        mode.currentIndexChanged.connect(_preview)
        _preview()

        @glossary_write_errors(owner=self)
        def _save():
            added = 0
            # Finish an in-cell edit, then recheck the exact reviewed rows at
            # the real store. Re-parsing here would silently discard edits.
            table.clearFocus()
            QApplication.processEvents()
            _render_rows(validate_term_records(self._import_rows, self.legacy.learned_mappings_for_game(library_id)))
            if not any(row['status'] == 'ready' for row in self._import_rows):
                self._show_toast('没有可保存的新增内容；请检查逐行预览。')
                return False
            skipped = sum(row['status'] != 'ready' for row in self._import_rows)
            for record in self._import_rows:
                if record['status'] != 'ready':
                    continue
                if self.legacy.add_learned_mapping(
                    library_id, record['from'], record['to'], category=record['category'], origin="批量导入"
                ):
                    added += 1
            _cleanup()
            self._notify_library_changed()
            self.refresh_current_game()
            (bind_text(self.owner.term_hint, f'Imported {added} terms into {game_name}') if current_language() == 'en' else bind_text(self.owner.term_hint, '已批量导入 {value0} 条术语到《{value1}》', value0=added, value1=game_name))
            if skipped:
                self.owner.term_hint.setText(self.owner.term_hint.text() + f"；跳过 {skipped} 条重复或冲突")
            return True

        def _cancel():
            _cleanup()

        do_imp.clicked.connect(_save)
        cancel.clicked.connect(_cancel)
        sheet.installEventFilter(self)
        self._import_cleanup = _cleanup
        self._import_pending = lambda: bool(editor.toPlainText().strip())
        self._import_submit = _save

    def open_glossary_hub(self):
        """The 「线上词库」 tab (the redesign replaced the hub sheet)."""
        self.show_page("hub")

    def open_glossary_submit(self):
        from .glossary_hub_ui import open_submit_sheet
        open_submit_sheet(self)

    def export_current_library(self):
        from PySide6.QtWidgets import QFileDialog
        game = self.state.get('game', '')
        if not game:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出术语库", f"{game}-术语库.json", "JSON (*.json)")
        if path:
            self._export_library_to(path)

    @glossary_write_errors
    def _export_library_to(self, path):
        library_id = self._library_key()
        from .multilingual_terms import export_library
        data = export_library(self.legacy, library_id)
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        self._show_toast("已导出完整多语言名称、候选、规则与概念关联。")

    def use_selected_game(self):
        if not self.prepare_for_task():
            return
        game_name = self.state["game"]
        if not game_name:
            return
        identity = self._library_key()
        enabled = list(self.owner._enabled_glossary_ids())
        if identity and identity not in enabled:
            enabled.append(identity)
        self.owner.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
        self.owner.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled
        self.owner.game_box.setCurrentText(game_name)
        self.owner.terms.setChecked(True)
        self.legacy.save_runtime_game_history(game_name)
        self.owner._save_glossary_settings()
        self._notify_library_changed()
        (bind_text(self.owner.term_hint, f'This batch will use the {game_name} term library') if current_language() == 'en' else bind_text(self.owner.term_hint, '本批字幕将使用《{value0}》术语库', value0=game_name))
        self.refresh_current_game()

    def _current_game_in_batch(self) -> bool:
        game_name = self.state["game"]
        if not game_name:
            return False
        identity = self._library_key()
        return bool(identity) and identity in self.owner._enabled_glossary_ids()

    def _refresh_batch_bar(self):
        enabled_ids = tuple(self.owner._enabled_glossary_ids())
        terms_widget = getattr(self.owner, 'terms', None)
        terms_active = terms_widget is None or terms_widget.isChecked()
        def stamp(name):
            try:
                value = Path(getattr(self.legacy, name, '')).stat()
                return value.st_mtime_ns, value.st_size
            except OSError:
                return None
        key = (enabled_ids, terms_active, self._library_key(), self.state.get('game', ''),
               self._batch_revision, current_language(), stamp('LEARNED_TERMS_PATH'), stamp('GAME_PROFILES_PATH'))
        self._batch_request_key = key
        cached = self._batch_summary_cache.get(key)
        if cached is not None:
            self._apply_batch_summary(key, cached)
        elif self._batch_queued is None or self._batch_queued != key:
            self.batch_status.setText(tr('正在统计本批词库…'))
            self._batch_queued = key
            QTimer.singleShot(500, self, self._start_batch_summary)
        self.use_game.setEnabled(bool(self.state['game']))
        self._sync_batch_switch()

    def _start_batch_summary(self):
        if self._batch_running or self._batch_queued is None: return
        key, self._batch_queued = self._batch_queued, None
        self._batch_running = True
        legacy, signal, cancel = self.legacy, self._batch_summary_ready, self._summary_cancel
        def work():
            try:
                from .terminology import snapshot_glossaries
                enabled, active, current_id = key[:3]
                snapshot = snapshot_glossaries(legacy, enabled if active else ())
                from .summary_process import summarize
                same = active and enabled == (current_id,)
                snapshots = [snapshot]
                if current_id and not same:
                    snapshots.append(snapshot_glossaries(legacy, (current_id,)))
                # Tiny summaries finish in a few milliseconds; only the large
                # regex/index build needs a separate interpreter and its GIL.
                term_count = sum(len(library.terms) for item in snapshots for library in item.libraries)
                summaries = [item.summary() for item in snapshots] if term_count <= 800 else summarize(snapshots, cancel)
                summary = summaries[0]
                current_summary = summary if same else summaries[1] if len(summaries)>1 else {}
                result = ([item.name for item in snapshot.libraries], summary, current_summary)
            except Exception as exc:
                result = exc
            try: signal.emit(key, result)
            except RuntimeError: pass
        threading.Thread(target=work, name='term-batch-summary', daemon=True).start()

    def _receive_batch_summary(self, key, result):
        self._batch_running = False
        if not isinstance(result, Exception):
            self._batch_summary_cache[key] = result
            while len(self._batch_summary_cache) > 8:
                self._batch_summary_cache.pop(next(iter(self._batch_summary_cache)))
            if key == self._batch_request_key:
                self._apply_batch_summary(key, result)
        elif key == self._batch_request_key:
            self.batch_status.setText(tr('词库统计暂不可用，请重新进入页面'))
        if self._batch_queued == key: self._batch_queued = None
        self._start_batch_summary()

    def _apply_batch_summary(self, key, result):
        enabled_ids, terms_active, library_id, game = key[:4]
        names, summary, current_summary = result
        in_batch = library_id in enabled_ids
        count = int(summary.get('effective_terms', 0))
        label = f"本批已启用 {len(enabled_ids)} 个词库 · 有效规范词 {count} 个"
        if enabled_ids and not terms_active:
            label = f"本批已选择 {len(enabled_ids)} 个词库；术语增强已关闭，实际生效 0 词"
        if names:
            label += "：" + "、".join(names)
        if enabled_ids and terms_active and count == 0:
            label += "；没有已确认规范词，请添加或确认参考。"
        if summary.get('conflicts'):
            label += f"；{len(summary['conflicts'])} 处冲突未执行"
        if game:
            current_count = int(current_summary.get('effective_terms', 0))
            if current_count == 0:
                label += f"；当前浏览《{game}》有效 0 词"
                if in_batch:
                    label += "（已加入本批，但请先添加或确认词条）"
        self.batch_status.setText(label)

    def toggle_current_game_in_batch(self):
        if not self.prepare_for_task():
            return
        game_name = self.state["game"]
        if not game_name:
            return
        identity = self._library_key()
        if not identity:
            return
        enabled = list(self.owner._enabled_glossary_ids())
        if identity in enabled:
            enabled = [item for item in enabled if item != identity]
            (bind_text(self.owner.term_hint, f'Removed {game_name} from this batch') if current_language() == 'en' else bind_text(self.owner.term_hint, '已从本批移除《{value0}》', value0=game_name))
        else:
            enabled.append(identity)
            (bind_text(self.owner.term_hint, f'Added {game_name} to this batch') if current_language() == 'en' else bind_text(self.owner.term_hint, '已将《{value0}》加入本批', value0=game_name))
        self.owner.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
        self.owner.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled
        self.owner._save_glossary_settings()
        self._notify_library_changed()
        self._refresh_batch_bar()

    def open_smart_build(self):
        game_name = self.state["game"]
        if not game_name:
            return
        # P0: host inside ModalHost (no new native window). Content at final size; backdrop fade only.
        content = SmartGlossaryDialog(self.owner, game_name, self.owner._modal_host.body if hasattr(self.owner, "_modal_host") else self, library_id=self._library_key())
        mw = self.owner
        if hasattr(mw, "_modal_host"):
            def _after():
                self.refresh_current_game()
            mw._modal_host.show_content(
                content,
                title=f"智能建词｜{game_name}",
                size=(980, 720),
                min_size=(760, 560),
                on_closed=_after,
            )
        else:
            # Fallback path (tests/capture): wrap
            from twobyteasr.design.main_ui_dialogs import SpringDialog
            host = SpringDialog(self)
            bind_text(host, '智能建词｜{game_name}', property='windowTitle', game_name=game_name)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(content, 1)
            host.resize(980, 720)
            host.show()
            QTimer.singleShot(0, self.refresh_current_game)

    # ------------------------- AI 联网更新（game-term-search Skill） -------------------------

    def _refresh_ai_choices(self):
        """填充 AI 服务/模型选择器：跟随全局 + 各已配置服务（复用现有凭证）。"""
        from .glossary_skill_ui import list_ai_services
        from ..i18n_widgets import add_combo_item

        settings = self.legacy.RUNTIME_SETTINGS
        services = list_ai_services(settings)
        current_service = str(self.ai_service_combo.currentData() or "")
        self.ai_service_combo.blockSignals(True)
        self.ai_service_combo.clear()
        self.ai_service_combo.addItem("跟随全局校对 AI", "")
        for service in services:
            label = tr(service["label"])
            if not service["ready"]:
                label = tr("{service}（未配置）", service=label)
            elif not service["search"]:
                label = tr("{service}（无联网）", service=label)
            add_combo_item(self.ai_service_combo, label, service["service"])
        self.ai_service_combo.blockSignals(False)
        if current_service:
            index = self.ai_service_combo.findData(current_service)
            if index >= 0:
                self.ai_service_combo.setCurrentIndex(index)
        self._on_ai_service_changed()

    def _on_ai_service_changed(self, *_args):
        """换服务 → 填充该服务可用模型目录（不发起网络请求）。"""
        from ..providers.llm_config import active_service_values, resolved_service_values

        settings = self.legacy.RUNTIME_SETTINGS
        service_id = str(self.ai_service_combo.currentData() or "")
        previous_model = str(self.ai_model_combo.currentText() or "")
        values = (
            active_service_values(settings)
            if not service_id
            else resolved_service_values(settings, service_id)
        )
        models = [str(model) for model in values.get("models", ()) if str(model).strip()]
        self.ai_model_combo.blockSignals(True)
        self.ai_model_combo.clear()
        model = str(values.get("model") or "")
        for candidate in ([model] if model else []) + [
            item for item in models if item != model
        ]:
            self.ai_model_combo.addItem(candidate)
        if not self.ai_model_combo.count() and previous_model:
            self.ai_model_combo.addItem(previous_model)
        self.ai_model_combo.blockSignals(False)
        self._refresh_ai_capability_label()

    def _refresh_ai_capability_label(self, *_args):
        from .glossary_skill import detect_search_capability

        capability = detect_search_capability(self._ai_update_settings())
        self._ai_capability = capability
        # 2026-11-13 (user): say in plain words what the chosen AI can do, and
        # mark the entries that need it, instead of one "无服务端搜索" line.
        if capability["provider_search"]:
            bind_text(self.ai_capability_label, '● 支持联网检索')
            self.ai_capability_label.setToolTip(capability["reason"])
        elif capability.get("tool_search"):
            bind_text(self.ai_capability_label, '● 支持联网：用 DeepSeek 搜索查外语名')
            self.ai_capability_label.setToolTip(capability["reason"])
        else:
            bind_text(self.ai_capability_label, '○ 不能上网：查新词和外语名要换一个 AI')
            bind_text(self.ai_capability_label, '{value0}；AI 完整建库仍可抓取资料并调用模型整理文本。', property='toolTip', value0=capability['reason'])
        web = bool(capability["provider_search"] or capability.get("tool_search"))
        self.ai_bar.setProperty("web", "yes" if web else "no")
        self.ai_bar.style().unpolish(self.ai_bar)
        self.ai_bar.style().polish(self.ai_bar)
        if capability["provider_search"]:
            self.ai_update_button.set_badge("")
        else:
            bind_text(self.ai_update_button, '🔒 需换 AI',
                      property='badge')
            self.ai_update_button.set_badge(self.ai_update_button.badge.text(), "warn")
        names = getattr(self, "name_completion_button", None)
        if names is not None and hasattr(names, "set_badge"):
            if web:
                names.set_badge("")
            else:
                bind_text(names, '🔒 不能上网，只会猜', property='badge')
                names.set_badge(names.badge.text(), "warn")

    def _ai_update_needs_key(self, settings) -> bool:
        """The chosen AI service has no key: explain before a task is queued (2026-10-15)."""
        from ..app.api_key_explainer import ask_for_key_if_missing

        def status():
            bind_text(self.ai_update_status, 'AI 建库没有运行：还没填 API Key')
            self.ai_update_status.show()
        return ask_for_key_if_missing(self, settings, "polish", status=status)

    def _ai_update_settings(self) -> dict:
        from .glossary_skill import settings_with_service_override

        service_id = str(self.ai_service_combo.currentData() or "")
        model = str(self.ai_model_combo.currentText() or "").strip()
        settings = dict(self.legacy.RUNTIME_SETTINGS)
        if not service_id:
            from ..providers.llm_config import active_service_values
            service_id = str(active_service_values(settings, stage="polish").get("service") or "")
        if service_id:
            settings = settings_with_service_override(settings, service_id, model)
        return settings

    # ------------------------------------------------------------ 任务管理（VII 轮：全局任务状态）

    def _ensure_task_manager(self):
        """惰性创建应用级任务管理器 + 常驻任务栏（切换词库后状态仍可见）。"""
        if self._task_manager is None:
            from .glossary_task_manager import GlossaryUpdateManager

            self._task_manager = GlossaryUpdateManager.instance(self.legacy)
        if not self._task_manager_wired:
            manager = self._task_manager
            manager.task_added.connect(lambda _tid: self._on_task_structure_changed())
            manager.task_removed.connect(lambda _tid: self._on_task_structure_changed())
            manager.task_progress.connect(lambda _tid: self._on_task_progress())
            manager.task_finished.connect(self._on_task_finished)
            manager.task_failed.connect(self._on_task_failed)
            self._task_manager_wired = True
        if self.ai_task_strip is None:
            from .glossary_skill_ui import GlossaryTaskStrip

            self.ai_task_strip = GlossaryTaskStrip(self._task_manager, self)
            self.ai_task_strip.request_review.connect(self._on_task_review)
            self.ai_task_strip.request_cancel.connect(self._on_task_cancel)
            self.ai_task_strip.request_resume.connect(self._on_task_resume)
            self.ai_task_strip.request_remove.connect(
                lambda tid: self._task_manager.remove(tid)
            )
            host = self.ai_update_status.parent()
            if host is not None:
                host.layout().insertWidget(host.layout().indexOf(self.ai_update_status), self.ai_task_strip)
        return self._task_manager

    def _on_task_structure_changed(self):
        strip = getattr(self, "ai_task_strip", None)
        if strip is not None:
            strip.refresh()
        self._refresh_ai_update_buttons()

    def _on_task_progress(self):
        strip = getattr(self, "ai_task_strip", None)
        if strip is not None:
            strip.refresh()

    def _on_task_cancel(self, task_id: str):
        manager = self._ensure_task_manager()
        manager.cancel(task_id)

    def _on_task_resume(self, task_id: str):
        from .glossary_skill import detect_search_capability

        manager = self._ensure_task_manager()
        task = manager.get(task_id)
        if task is None:
            return
        settings = self._ai_update_settings()
        if self._ai_update_needs_key(settings):
            return
        new_id, created = manager.submit(
            task.game,
            "full",
            settings,
            service_label=str(detect_search_capability(settings).get("service") or ""),
            model_label=str(detect_search_capability(settings).get("model") or ""),
            resume_task_id=task_id,
            library_id=task.library_id,
        )
        if created:
            self._show_toast(tr('已从检查点继续「{value0}」完整建库。', value0=task.game))
        else:
            self._show_toast(tr('「{value0}」已有同模式任务在队列/运行中。', value0=task.game))

    def _on_task_review(self, task_id: str):
        manager = self._ensure_task_manager()
        task = manager.get(task_id)
        if task is None:
            return
        if task.status in {"finished", "partial"} and task.result:
            self._open_update_review(task.game, task.result)
        elif task.status in {"running", "queued", "cancelled", "failed"}:
            self._open_task_candidates(task)

    def _open_task_candidates(self, task):
        from .glossary_skill_ui import GlossaryTaskCandidatesDialog

        mw = self.owner
        content = GlossaryTaskCandidatesDialog(
            self.owner, task, mw._modal_host.body if hasattr(mw, "_modal_host") else self
        )
        if hasattr(mw, "_modal_host"):
            mw._modal_host.show_content(
                content,
                title=f"实时候选｜{task.game}",
                size=(900, 620),
                min_size=(640, 420),
            )

    def _on_task_finished(self, task_id: str, game: str, result):
        self._on_task_structure_changed()
        outcome=(result or {}).get('outcome') or {}
        if outcome.get('status') in {'blocked','failed','no_verified_content'}:
            self.ai_update_status.setText(f'「{game}」'+outcome['message'])
            if game==self.state.get('game'):self._open_update_review(game,result)
            self._show_toast(f'「{game}」'+outcome['message'])
            return
        if outcome.get('status') == 'no_changes':
            if game == self.state.get('game'):
                self._open_update_review(game, result)
            self._show_toast(f'「{game}」成功无新增：' + outcome.get('message', '本次核对范围内无变化'))
            return
        diffs = (result or {}).get("diffs", ()) or ()
        new = sum(1 for d in diffs if getattr(d, "change_type", "") == "new")
        alias = sum(1 for d in diffs if getattr(d, "change_type", "") == "alias_supplement")
        mode_label = "完整建库" if (result or {}).get("mode") == "full" else "更新"
        if (result or {}).get('partial'):
            mode_label += '部分'
        if game == self.state.get("game"):
            self._open_update_review(game, result)
            self._show_toast(tr('「{value0}」{value1}完成：新增候选 {value2} · 别名补充 {value3}。', value0=game, value1=tr(mode_label), value2=new, value3=alias))
        else:
            # 归属正确：无论当前页选中哪个游戏，完成提示都指向任务自己的游戏。
            self._show_toast(
                tr('「{value0}」{value1}完成：新增候选 {value2} · 别名补充 {value3}（在任务栏点「查看」审阅）。', value0=game, value1=tr(mode_label), value2=new, value3=alias)
            )

    def _on_task_failed(self, task_id: str, game: str, code: str, message: str):
        self._on_task_structure_changed()
        if code == "cancelled":
            self._show_toast(tr('「{value0}」更新已取消（已完成批次保留在检查点）。', value0=game))
            return
        bind_text(self.ai_update_status, '「{game}」更新失败（{code}）：{message}', game=game, code=code, message=message)
        self.ai_update_status.show()
        self._show_toast(tr('「{value0}」更新失败：{value1}', value0=game, value1=message[:80]))

    def _refresh_ai_update_buttons(self):
        """按钮语义由全局任务状态推导，不再被 refresh_current_game 重置。"""
        manager = self._task_manager
        if manager is None:
            has_game = bool(self.state.get("game"))
            self.ai_update_button.setEnabled(has_game)
            self.ai_full_button.setEnabled(has_game)
            self.ai_batch_button.setEnabled(has_game)
            return
        game = self.state.get("game")
        pending = manager.pending_for_game(game) if game else None
        self.ai_update_button.setEnabled(bool(game))
        self.ai_full_button.setEnabled(bool(game))
        if pending is not None:
            label = "更新中（查看任务）" if pending.status == "running" else "已排队（查看任务）"
            # 只改同模式按钮；另一模式仍可发起（提交后进队列）
            if pending.mode == "full":
                self.ai_full_button.setText(label)
                bind_text(self.ai_update_button, '补上最近版本的新词')
            else:
                self.ai_update_button.setText(label)
                bind_text(self.ai_full_button, '从零整理一整个词库')
        else:
            bind_text(self.ai_update_button, '补上最近版本的新词')
            bind_text(self.ai_full_button, '从零整理一整个词库')

    def _start_ai_update(self, mode: str = "incremental", *, execution_mode='full'):
        from .glossary_skill import detect_search_capability

        game_name = self.state.get("game", "")
        if not game_name:
            self._show_toast("请先选择要更新的游戏词库。")
            return
        settings = self._ai_update_settings()
        if self._ai_update_needs_key(settings):
            return
        manager = self._ensure_task_manager()
        import copy
        settings = copy.deepcopy(settings)
        if mode == 'full':
            settings.setdefault('models', {})['glossary_execution_mode'] = 'full'
        capability = detect_search_capability(settings)
        if mode != 'full' and not capability["provider_search"]:
            self._show_toast(
                "「补上最近版本的新词」要用能自己联网的 AI：在「AI 帮忙」底部换成百炼、Grok 或 Antigravity；"
                "也可以用「从一段文字里挑词」。"
            )
            return
        service_label = self.ai_service_combo.currentText() or str(capability.get("service") or "")
        task_id, created = manager.submit(
            game_name,
            mode,
            settings,
            service_label=service_label,
            model_label=str(capability.get("model") or ""),
            library_id=self._library_key(game_name),
        )
        if not created:
            # 同游戏+同模式去重：点击直接带用户去看任务，而不是抛一句"已有任务"。
            task = manager.get(task_id)
            if task is not None and task.status in {"finished", "partial"} and task.result:
                self._open_update_review(task.game, task.result)
            elif task is not None:
                self._open_task_candidates(task)
            return
        mode_label = "从零整理一整个词库" if mode == "full" else "补上最近版本的新词"
        self._show_toast(tr('「{value0}」{value1}已提交。切到其它词库也能在任务栏看到进度。', value0=game_name, value1=tr(mode_label)))
        self._on_task_structure_changed()

    def _open_update_review(self, game_name: str, result):
        from .glossary_skill_ui import GlossaryUpdateReviewDialog

        mw = self.owner
        content = GlossaryUpdateReviewDialog(
            self.owner, game_name, result, mw._modal_host.body if hasattr(mw, "_modal_host") else self
        )

        def on_applied(_game, session):
            added, duplicates = session.get("added", 0), session.get("duplicates", 0)
            self._notify_library_changed()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()
            self._refresh_game_item_counts()
            extra = tr("（{count} 条已存在，未重复入库）", count=duplicates) if duplicates else ""
            failure = tr("；{count} 条保存失败，请在预览中重试", count=session["failed"]) if session.get("failed") else ""
            history = tr("；撤销记录未保存") if session.get("history_saved") is False else ""
            self._show_toast(tr('已应用 {value0} 条更新{value1}{value2}{value3}。', value0=added, value1=extra, value2=failure, value3=history))

        content.application_result.connect(on_applied)
        if hasattr(mw, "_modal_host"):
            mw._modal_host.show_content(
                content,
                title=f"联网更新预览｜{game_name}",
                size=(1180, 760),
                min_size=(900, 600),
            )
        else:
            from twobyteasr.design.main_ui_dialogs import SpringDialog
            host = SpringDialog(self)
            bind_text(host, '联网更新预览｜{game_name}', property='windowTitle', game_name=game_name)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(content, 1)
            host.resize(1180, 760)
            host.show()

    def _open_batch_update(self):
        from .glossary_skill_ui import BatchUpdateDialog

        games = []
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if name and name != self.state.get("game"):
                games.append(name)
        games.sort()
        mw = self.owner
        content = BatchUpdateDialog(
            self.owner, games, self._ai_update_settings,
            mw._modal_host.body if hasattr(mw, "_modal_host") else self,
        )

        def on_batch_finished(_summary):
            self._mappings_cache.clear()
            self._builtin_entry_cache.clear()
            self._builtin_cache.clear()
            self.refresh_current_game()
            self._refresh_game_item_counts()

        content.batch_finished.connect(on_batch_finished)
        if hasattr(mw, "_modal_host"):
            mw._modal_host.show_content(
                content,
                title="批量更新游戏词库",
                size=(640, 560),
                min_size=(520, 440),
            )
        else:
            from twobyteasr.design.main_ui_dialogs import SpringDialog
            host = SpringDialog(self)
            bind_text(host, '批量更新游戏词库', property='windowTitle')
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(content, 1)
            host.resize(640, 560)
            host.show()

    def _open_update_history(self):
        from .glossary_skill_ui import GlossaryUpdateHistoryDialog

        game_name = self.state.get("game", "")
        if not game_name:
            self._show_toast("请先选择游戏。")
            return
        mw = self.owner
        content = GlossaryUpdateHistoryDialog(
            self.owner, game_name, mw._modal_host.body if hasattr(mw, "_modal_host") else self
        )
        if hasattr(mw, "_modal_host"):
            def _after():
                self.refresh_current_game()
            mw._modal_host.show_content(
                content, title=f"更新记录｜{game_name}", size=(640, 520), on_closed=_after,
            )
        else:
            content.show()
