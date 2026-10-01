"""Term Library presentation widgets and models."""

from __future__ import annotations

import json
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
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .glossary_learning import GlossaryLearningStore
from .i18n import current_language, translate
from .main_ui_branding import _icon
from .main_ui_helpers import GUI_PROFILE_ENABLED
from .main_ui_popup import FramelessPopupCombo
from .main_ui_smart_glossary import SmartGlossaryDialog
from .ui_theme import (
    BACKGROUND as IVORY,
    BORDER as LINE,
    GREEN,
    GREEN_SUBTLE,
    MUTED,
    SURFACE,
)
from .ui_widgets import AnimatedButton

from .i18n import bind_text

from .i18n import tr


def _sheet_theme():
    """Theme tokens for on-demand sheets/toasts created outside the QSS pipeline."""

    from .theme_manager import theme_definition, theme_key

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
    learned_payload = getattr(
        legacy, "load_learned_term_payload", lambda: {"games": {}}
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


class TermGameListRow(QFrame):
    """Two-level glossary nav row: strong name, quiet count."""

    clicked = Signal()

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
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(8)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("termGameRowIcon")
        self.icon_label.setPixmap(_icon("fa5s.book", GREEN).pixmap(QSize(18, 18)))
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("termGameRowName")
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)
        self.name_label.setToolTip(name)
        self.count_label = QLabel()
        self.count_label.setObjectName("termGameRowCount")
        meta = QHBoxLayout()
        meta.setSpacing(5)
        meta.addWidget(self.count_label)
        meta.addStretch(1)
        text.addWidget(self.name_label)
        text.addLayout(meta)
        layout.addLayout(text, 1)
        for child in (self.icon_label, self.name_label, self.count_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_content(name, count, content_type, reference_count)

    def update_content(
        self, name: str, count: int, content_type: str, reference_count: int = 0
    ):
        self.name_label.setText(name)
        self.name_label.setToolTip(name)
        (bind_text(self.count_label, f'{count} confirmed · {reference_count} references') if current_language() == 'en' else bind_text(self.count_label, '{value0} 已确认 · {value1} 参考', value0=count, value1=reference_count))

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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

    def set_data(self, items: list[dict]):
        self.beginResetModel()
        self._rows = list(items) if items else []
        self.endResetModel()

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
        return None

    def data_for_row(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


class _CategoryPillDelegate(QStyledItemDelegate):
    """Paint a compact category pill without creating a QWidget per row."""

    def paint(self, painter, option, index):
        painter.save()
        text = str(
            index.data(Qt.ItemDataRole.DisplayRole)
            or translate("其他", current_language())
        )
        bg = QColor("#e6f0df")
        fg = QColor("#4a7040")
        br = QColor("#d4e1cf")
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(GREEN_SUBTLE))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#f3f7ef"))
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
        bg, fg, br = self.PALETTE.get(status, self.PALETTE["reference"])
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(GREEN_SUBTLE))
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


class TermLibraryDialog(QWidget):
    """术语库与学习记录（C 轮重排）。

    Hosted inside MainWindow ModalHost (no new native top-level window).
    Card chrome (title + X + backdrop + Esc) is provided by the host.
    Dialog card shows at final size immediately; only backdrop fades.
    """

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
            return self.legacy.runtime_game_identity(canonical(value))

        self._canonical = canonical
        self._game_identity = game_identity
        self.state = {"game": "", "mappings": [], "builtin_names": [], "loaded": []}
        self._task_manager = None
        self._task_manager_wired = False
        self._search_visible = False
        self._builtin_expanded = False
        # P0 perf: in-memory cache so switching between games (e.g. 原神 <-> 异环) is instant after first load.
        # 650 rows should switch in <200ms when cached. We still pay the first load cost once per game.
        self._mappings_cache: dict[str, list] = {}
        self._builtin_cache: dict[str, tuple] = {}
        self._builtin_entry_cache: dict[str, list[dict[str, str]]] = {}
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
        # Do not setCurrentRow(0) here — that triggers sync heavy refresh_current_game.
        # After show(), the owner will kick refresh on next tick. If no games, just enable editor focus later.
        if not self.game_list.count():
            # Still allow manual focus on editor for empty state; no heavy load yet.
            QTimer.singleShot(0, lambda: self.term_editor.setFocus() if hasattr(self, "term_editor") else None)

    # ------------------------------------------------------------ helpers

    def game_box_text(self) -> str:
        return self.owner.game_box.currentText()

    def builtin_for_game(self, game_name):
        """(全部参考名, 资料构成, 已隐藏参考名)——统一主列表的数据底座。"""
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
                                "aliases": [],
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
        source = target = value.strip()
        for separator in ("→", "->", "=>", "\t"):
            if separator in value:
                source, target = (part.strip() for part in value.split(separator, 1))
                break
        return source, target

    def _type_labels(self):
        labels = {
            "game": "游戏", "event": "活动", "series": "系列",
            "creator": "创作者", "other": "其它内容",
        }
        return {key: translate(value, current_language()) for key, value in labels.items()}

    def _focus_new_game(self):
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)

        # C1 Header：标题 + 计数 badge + 一句副文案 + [?] + 🔍
        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        title_row = QHBoxLayout()
        title = QLabel("术语库")
        title.setObjectName("termLibraryTitle")
        title_row.addWidget(title)
        self.library_badge = QLabel()
        self.library_badge.setObjectName("termLibraryBadge")
        title_row.addWidget(self.library_badge)
        title_row.addStretch(1)
        heading_text.addLayout(title_row)
        intro = QLabel("让角色名、技能和游戏专名更容易识别正确。")
        intro.setObjectName("muted")
        heading_text.addWidget(intro)
        # P0: show skeleton immediately; heavy list population happens after show() via refresh_current_game / timers.
        heading.addLayout(heading_text, 1)
        self.help_button = AnimatedButton("?")
        self.help_button.setObjectName("flat")
        self.help_button.setFixedSize(30, 30)
        bind_text(self.help_button, '已确认/学习映射会参与纠错；内置词库只提供弱候选，不会仅凭名字相似强制改字。', property='toolTip')
        self.help_button.clicked.connect(
            lambda: QMessageBox.information(
                self,
                tr('术语库说明'),
                tr('已确认/学习映射会参与纠错；内置词库只提供弱候选，不会仅凭名字相似强制改字。\n\n专名 → 专名：拼写候选，只有读音和上下文支持时才修正；\n常见错词 → 正确词：保存明确纠错关系。'),
            )
        )
        heading.addWidget(self.help_button)
        self.search_toggle = AnimatedButton("")
        self.search_toggle.setObjectName("flat")
        self.search_toggle.setIcon(_icon("fa5s.search"))
        self.search_toggle.setFixedSize(30, 30)
        bind_text(self.search_toggle, '搜索术语', property='toolTip')
        self.search_toggle.clicked.connect(self._toggle_search)
        heading.addWidget(self.search_toggle)
        layout.addLayout(heading)

        # C2 顶部 toolbar：创建游戏 + 删除当前游戏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.content_type = FramelessPopupCombo()
        for label, value in (
            ("游戏", "game"),
            ("活动 / 嘉年华", "event"),
            ("系列 / IP", "series"),
            ("主播 / 创作者", "creator"),
            ("其它内容", "other"),
        ):
            self.content_type.addItem(label, value)
        self.content_type.setMaximumWidth(180)  # soft cap; allow CN text to breathe
        toolbar.addWidget(self.content_type)
        self.game_input = QLineEdit()
        bind_text(self.game_input, '输入游戏 / 内容名称', property='placeholderText')
        self.game_input.returnPressed.connect(self.create_game)
        toolbar.addWidget(self.game_input, 1)
        self.add_game_button = AnimatedButton("")
        self.add_game_button.setObjectName("outline")
        self.add_game_button.setIcon(_icon("fa5s.plus", GREEN))
        bind_text(self.add_game_button, '创建该游戏 / 内容的术语库', property='toolTip')
        self.add_game_button.clicked.connect(self.create_game)
        toolbar.addWidget(self.add_game_button)
        layout.addLayout(toolbar)
        # 术语搜索：常显（统一主列表的搜索+筛选入口）
        self.search = QLineEdit()
        bind_text(self.search, '搜索术语、错词、正确写法或来源…', property='placeholderText')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search)

        body = QHBoxLayout()
        body.setSpacing(12)

        # C3 左栏：左列相对固定，右侧自适应增长（P0 responsive）。用 min/max + Preferred 取代硬 setFixed* 以支持窗口自由缩放。
        # Restore classic two-pane visual with clear separation (sidebar list + main content card area).
        sidebar = QFrame()
        sidebar.setObjectName("termLibrarySidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(260)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.library_sidebar = sidebar
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(6)
        sidebar_head = QHBoxLayout()
        sidebar_head.setSpacing(4)
        games_title = QLabel("我的词库")
        games_title.setObjectName("termLibrarySectionTitle")
        sidebar_head.addWidget(games_title, 1)
        self.sidebar_new_button = AnimatedButton("新建")
        self.sidebar_new_button.setObjectName("flat")
        self.sidebar_new_button.setIcon(_icon("fa5s.plus", GREEN))
        bind_text(self.sidebar_new_button, '新建游戏 / 内容词库', property='toolTip')
        self.sidebar_new_button.clicked.connect(self._focus_new_game)
        sidebar_head.addWidget(self.sidebar_new_button)
        self.sidebar_search_button = AnimatedButton("")
        self.sidebar_search_button.setObjectName("flat")
        self.sidebar_search_button.setIcon(_icon("fa5s.search", MUTED))
        self.sidebar_search_button.setFixedSize(28, 28)
        bind_text(self.sidebar_search_button, '搜索我的词库', property='toolTip')
        self.sidebar_search_button.clicked.connect(self._toggle_game_search)
        sidebar_head.addWidget(self.sidebar_search_button)
        sidebar_layout.addLayout(sidebar_head)
        self.game_search = QLineEdit()
        bind_text(self.game_search, '搜索游戏…', property='placeholderText')
        self.game_search.setClearButtonEnabled(True)
        self.game_search.hide()
        self.game_search.textChanged.connect(self._filter_games)
        sidebar_layout.addWidget(self.game_search)
        self.game_list = QListWidget()
        self.game_list.setObjectName("termGameList")
        self.game_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.game_list.currentItemChanged.connect(self.select_game)
        sidebar_layout.addWidget(self.game_list, 1)
        self.sidebar_sync = QLabel("官方词库已同步")
        self.sidebar_sync.setObjectName("termSidebarSync")
        self.sidebar_sync.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(self.sidebar_sync)
        body.addWidget(sidebar)

        # 右侧内容区：包一个视觉 Card 容器，恢复旧参考的清晰边界和层级。
        content = QFrame()
        content.setObjectName("termLibraryContent")
        self.library_content = content
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        content_header = QFrame()
        content_header.setObjectName("termLibraryContentHeader")
        content_header_layout = QVBoxLayout(content_header)
        content_header_layout.setContentsMargins(16, 11, 16, 11)
        content_header_layout.setSpacing(9)

        selected_row = QHBoxLayout()
        self.selected_title = QLabel("请选择游戏")
        self.selected_title.setObjectName("termGameTitle")
        selected_row.addWidget(self.selected_title, 1)
        self.selected_stats = QLabel()
        self.selected_stats.setObjectName("termLibraryBadge")
        bind_text(self.selected_stats, translate('尚未选择', current_language()))
        selected_row.addWidget(self.selected_stats)
        self.official_stats = QLabel("0 条参考")
        self.official_stats.setObjectName("statusBadgeMuted")
        selected_row.addWidget(self.official_stats)
        self.delete_game_button = AnimatedButton("")
        self.delete_game_button.setObjectName("flat")
        self.delete_game_button.setIcon(
            qta.icon("fa5s.trash-alt", color="#8a5a4c", color_disabled="#8a5a4c")
        )
        bind_text(self.delete_game_button, '删除当前游戏及其术语', property='toolTip')
        self.delete_game_button.setEnabled(False)
        self.delete_game_button.setFixedSize(30, 30)
        self.delete_game_button.clicked.connect(self.delete_current_game)
        selected_row.addWidget(self.delete_game_button)
        content_header_layout.addLayout(selected_row)

        # C4 添加术语：右侧第一个输入
        quick_add_panel = QFrame()
        quick_add_panel.setObjectName("termQuickAdd")
        quick_add = QVBoxLayout(quick_add_panel)
        quick_add.setContentsMargins(10, 7, 8, 7)
        quick_add.setSpacing(5)
        quick_add_title = QLabel("添加术语")
        quick_add_title.setObjectName("termQuickAddTitle")
        quick_add.addWidget(quick_add_title)
        quick_add_row = QHBoxLayout()
        quick_add_row.setSpacing(7)
        self.term_editor = QLineEdit()
        bind_text(self.term_editor, '专名，或 错词 → 正确词', property='placeholderText')
        self.term_editor.returnPressed.connect(self.add_single_term)
        quick_add_row.addWidget(self.term_editor, 1)
        self.term_category = FramelessPopupCombo()
        for category in ("角色", "Boss", "物品", "方块", "阵营", "地点", "模型", "人物", "事件", "其他"):
            self.term_category.addItem(category, category)
        self.term_category.setMaximumWidth(140)  # soft; CN labels must not truncate
        quick_add_row.addWidget(self.term_category)
        self.add_term_button = AnimatedButton("添加术语")
        self.add_term_button.setIcon(_icon("fa5s.plus"))
        self.add_term_button.clicked.connect(self.add_single_term)
        quick_add_row.addWidget(self.add_term_button)
        quick_add.addLayout(quick_add_row)
        content_header_layout.addWidget(quick_add_panel)

        # C4b AI 更新：页面直接选 AI（复用已配置凭证，仅本次覆盖）→ 联网建立/更新词库
        ai_panel = QFrame()
        ai_panel.setObjectName("termQuickAdd")
        ai_layout = QVBoxLayout(ai_panel)
        ai_layout.setContentsMargins(10, 7, 8, 7)
        ai_layout.setSpacing(5)
        ai_title_row = QHBoxLayout()
        self.ai_update_title = QLabel("AI 联网更新")
        self.ai_update_title.setObjectName("termQuickAddTitle")
        ai_title_row.addWidget(self.ai_update_title)
        self.ai_capability_label = QLabel()
        self.ai_capability_label.setObjectName("statusBadgeMuted")
        ai_title_row.addStretch(1)
        ai_title_row.addWidget(self.ai_capability_label)
        ai_layout.addLayout(ai_title_row)
        ai_row = QHBoxLayout()
        ai_row.setSpacing(7)
        self.ai_service_combo = FramelessPopupCombo()
        bind_text(self.ai_service_combo, '使用哪个 AI 执行本次检索整理（复用已配置的登录/密钥，不改动全局设置）', property='toolTip')
        self.ai_service_combo.setMaximumWidth(170)
        self.ai_service_combo.currentIndexChanged.connect(self._on_ai_service_changed)
        ai_row.addWidget(self.ai_service_combo)
        self.ai_model_combo = FramelessPopupCombo()
        self.ai_model_combo.setEditable(True)
        self.ai_model_combo.setMaximumWidth(190)
        self.ai_model_combo.currentIndexChanged.connect(self._refresh_ai_capability_label)
        ai_row.addWidget(self.ai_model_combo)
        self.ai_full_button = AnimatedButton("完整建库…")
        self.ai_full_button.setObjectName("outline")
        self.ai_full_button.setIcon(_icon("fa5s.book-open", GREEN))
        bind_text(self.ai_full_button, '清单式补全：检索官方目录页 → 程序提取名称 → 分批整理 → 社区用语补搜；适合空白/大缺口词库', property='toolTip')
        self.ai_full_button.clicked.connect(lambda: self._start_ai_update("full"))
        build_menu = QMenu(self.ai_full_button)
        for label, execution in [('资料快速采集（允许有效缓存；不调用 AI）','fast'),
                                 ('AI 补全与实用筛选','ai'),
                                 ('重新联网核对（刷新来源）','refresh')]:
            build_menu.addAction(label).triggered.connect(
                lambda _checked=False, execution=execution: self._start_ai_update('full', execution_mode=execution))
        self.ai_full_button.setMenu(build_menu)
        ai_row.addWidget(self.ai_full_button)
        self.ai_update_button = AnimatedButton("联网更新当前词库")
        self.ai_update_button.setObjectName("primary")
        self.ai_update_button.setIcon(_icon("fa5s.globe", SURFACE))
        bind_text(self.ai_update_button, '版本增量：检索最近版本新增与高频术语（单轮，适合已建库词库）', property='toolTip')
        self.ai_update_button.clicked.connect(lambda: self._start_ai_update("incremental"))
        ai_row.addWidget(self.ai_update_button)
        self.ai_batch_button = AnimatedButton("批量更新…")
        self.ai_batch_button.setObjectName("outline")
        self.ai_batch_button.setIcon(_icon("fa5s.layer-group", GREEN))
        self.ai_batch_button.clicked.connect(self._open_batch_update)
        ai_row.addWidget(self.ai_batch_button)
        self.ai_history_button = AnimatedButton("更新记录")
        self.ai_history_button.setObjectName("flat")
        self.ai_history_button.clicked.connect(self._open_update_history)
        ai_row.addWidget(self.ai_history_button)
        ai_layout.addLayout(ai_row)
        self.ai_task_strip = None  # 延迟创建：需要 manager（见 _ensure_task_manager）
        self.ai_update_status = QLabel("")
        self.ai_update_status.setObjectName("termReferencePolicy")
        self.ai_update_status.hide()
        ai_layout.addWidget(self.ai_update_status)
        content_header_layout.addWidget(ai_panel)
        content_layout.addWidget(content_header)

        content_body = QWidget()
        content_body.setObjectName("termLibraryBody")
        content_body_layout = QVBoxLayout(content_body)
        content_body_layout.setContentsMargins(16, 10, 16, 10)
        content_body_layout.setSpacing(8)

        term_tools = QHBoxLayout()
        self.term_tools_layout = term_tools
        term_tools.setSpacing(6)
        self.smart_build_button = AnimatedButton("智能建词")
        self.smart_build_button.setObjectName("outline")
        self.smart_build_button.setIcon(_icon("fa5s.magic", GREEN))
        self.smart_build_button.clicked.connect(self.open_smart_build)
        term_tools.addWidget(self.smart_build_button)
        self.import_terms = AnimatedButton("批量导入")
        self.import_terms.setIcon(_icon("fa5s.file-import"))
        self.import_terms.clicked.connect(self.show_import_dialog)
        term_tools.addWidget(self.import_terms)
        term_tools.addStretch(1)
        content_body_layout.addLayout(term_tools)

        # 统一筛选行：分类 + 状态（内置参考默认展示，不再藏在折叠区）
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel("筛选"))
        self.filter_category = FramelessPopupCombo()
        self.filter_category.addItem("全部分类", "")
        self.filter_category.setMinimumWidth(110)
        self.filter_category.currentIndexChanged.connect(self.apply_filter)
        filter_row.addWidget(self.filter_category)
        self.filter_status = FramelessPopupCombo()
        for label, value in (
            ("全部状态", ""),
            ("已确认", "confirmed"),
            ("参考", "reference"),
            ("已隐藏", "hidden"),
        ):
            self.filter_status.addItem(label, value)
        self.filter_status.setMinimumWidth(110)
        self.filter_status.currentIndexChanged.connect(self.apply_filter)
        filter_row.addWidget(self.filter_status)
        filter_row.addStretch(1)
        self.bulk_confirm = AnimatedButton("确认所选参考")
        self.bulk_confirm.setObjectName("outline")
        self.bulk_confirm.setIcon(_icon("fa5s.check", GREEN))
        self.bulk_confirm.clicked.connect(self.confirm_selected_references)
        self.bulk_confirm.setEnabled(False)
        filter_row.addWidget(self.bulk_confirm)
        self.bulk_hide = AnimatedButton("隐藏所选")
        self.bulk_hide.setObjectName("flat")
        self.bulk_hide.clicked.connect(self.hide_selected_references)
        self.bulk_hide.setEnabled(False)
        filter_row.addWidget(self.bulk_hide)
        content_body_layout.addLayout(filter_row)

        self.learning_panel = QFrame()
        self.learning_panel.setObjectName("termLearningSuggestions")
        self.learning_panel.setMinimumHeight(92)
        learning_layout = QVBoxLayout(self.learning_panel)
        learning_layout.setContentsMargins(10, 9, 10, 9)
        learning_layout.setSpacing(7)
        learning_head = QHBoxLayout()
        self.learning_title = QLabel("待学习")
        self.learning_title.setObjectName("termLearnedTitle")
        learning_head.addWidget(self.learning_title, 1)
        self.learning_count = QLabel()
        self.learning_count.setObjectName("statusBadgeMuted")
        learning_head.addWidget(self.learning_count)
        learning_layout.addLayout(learning_head)
        self.learning_list = QListWidget()
        self.learning_list.setObjectName("termLearningList")
        self.learning_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.learning_list.setFixedHeight(40)
        learning_actions = QHBoxLayout()
        learning_actions.addWidget(self.learning_list, 1)
        self.learning_accept_project = AnimatedButton("加入项目词库")
        self.learning_accept_project.setObjectName("outline")
        bind_text(self.learning_accept_project, '批量接受所选建议并加入当前项目关联词库', property='toolTip')
        self.learning_accept_project.clicked.connect(lambda: self._accept_learning_suggestions("project"))
        learning_actions.addWidget(self.learning_accept_project)
        self.learning_accept_profile = AnimatedButton("加入 Profile 词库")
        self.learning_accept_profile.setObjectName("outline")
        bind_text(self.learning_accept_profile, '批量接受所选建议并加入当前 Profile 使用的词库', property='toolTip')
        self.learning_accept_profile.clicked.connect(lambda: self._accept_learning_suggestions("profile"))
        learning_actions.addWidget(self.learning_accept_profile)
        self.learning_ignore = AnimatedButton("忽略")
        self.learning_ignore.setObjectName("flat")
        self.learning_ignore.clicked.connect(self._ignore_learning_suggestions)
        learning_actions.addWidget(self.learning_ignore)
        learning_layout.addLayout(learning_actions)
        content_body_layout.addWidget(self.learning_panel)

        # 统一术语表 — P0-5: QTableView + model + delegate (no per-row QWidget for 650 rows)
        # 内置参考与已确认词条同表展示：来源/状态分列，隐藏词通过筛选可见可恢复。
        self.learned_title = QLabel("术语列表")
        self.learned_title.setObjectName("termLearnedTitle")
        content_body_layout.addWidget(self.learned_title)
        self.listing = QTableView()
        self.listing.setObjectName("termMappingTable")
        self._term_model = _TermMappingsModel(self)
        self.listing.setModel(self._term_model)
        self.listing.setItemDelegateForColumn(1, _CategoryPillDelegate(self.listing))
        self.listing.setItemDelegateForColumn(3, _StatusPillDelegate(self.listing))
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listing.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.listing.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listing.setShowGrid(False)
        self.listing.verticalHeader().hide()
        # Double-click row to edit (no per-cell editors)
        self.listing.doubleClicked.connect(self._on_table_double_click)
        # Click on the "操作" column (col 4) triggers the primary row action.
        self.listing.clicked.connect(self._on_table_clicked)
        header = self.listing.horizontalHeader()
        # Term stretches; category/status fixed wide enough for full labels
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setMinimumSectionSize(48)
        header.setFixedHeight(38)
        self.listing.setColumnWidth(1, 86)   # P0-5: >=72-88px guarantees full "其他/角色/Boss/物品/技能/阵营/地点"
        self.listing.setColumnWidth(3, 84)
        self.listing.setColumnWidth(4, 110)
        # Reasonable row height so it doesn't look collapsed (QTableView has no per-row setRowHeight on model rows easily; use vertical header default + stylesheet hint)
        self.listing.verticalHeader().setDefaultSectionSize(36)
        # Selection change still drives toolbar enablement
        try:
            self.listing.selectionModel().selectionChanged.connect(self.update_remove_action)
        except Exception:
            pass
        content_body_layout.addWidget(self.listing, 3)
        # 空态：区分"还没有词库内容"与"没有符合筛选条件的词条"
        self.listing_empty = QWidget()
        self.listing_empty.setObjectName("termMappingEmpty")
        empty_layout = QVBoxLayout(self.listing_empty)
        empty_layout.setContentsMargins(12, 24, 12, 24)
        empty_layout.setSpacing(6)
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
        empty_actions = QHBoxLayout()
        empty_actions.addStretch(1)
        self.listing_empty_build = AnimatedButton("新建词库")
        self.listing_empty_build.setObjectName("outline")
        self.listing_empty_build.setIcon(_icon("fa5s.plus", GREEN))
        self.listing_empty_build.clicked.connect(self._focus_new_game)
        empty_actions.addWidget(self.listing_empty_build)
        self.listing_empty_import = AnimatedButton("导入词库")
        self.listing_empty_import.setObjectName("outline")
        self.listing_empty_import.setIcon(_icon("fa5s.file-import", GREEN))
        self.listing_empty_import.clicked.connect(self.show_import_dialog)
        empty_actions.addWidget(self.listing_empty_import)
        self.listing_empty_smart = AnimatedButton("智能建词")
        self.listing_empty_smart.setObjectName("outline")
        self.listing_empty_smart.setIcon(_icon("fa5s.magic", GREEN))
        self.listing_empty_smart.clicked.connect(self.open_smart_build)
        empty_actions.addWidget(self.listing_empty_smart)
        self.listing_empty_actions = empty_actions
        empty_actions.addStretch(1)
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch(1)
        self.listing_empty.hide()
        content_body_layout.addWidget(self.listing_empty, 3)
        content_layout.addWidget(content_body, 1)

        # C7 + D1：本批词库状态 + 底部动作行（删除术语与删除游戏分离）
        footer = QFrame()
        footer.setObjectName("termLibraryFooter")
        self.library_footer = footer
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 9, 16, 10)
        footer_layout.setSpacing(7)
        batch_strip = QFrame()
        batch_strip.setObjectName("batchStrip")
        batch_bar = QHBoxLayout(batch_strip)
        batch_bar.setContentsMargins(10, 6, 10, 6)
        batch_bar.setSpacing(8)
        self.batch_status = QLabel()
        self.batch_status.setObjectName("muted")
        batch_bar.addWidget(self.batch_status, 1)
        self.batch_toggle = AnimatedButton("加入本批")
        self.batch_toggle.setObjectName("outline")
        self.batch_toggle.clicked.connect(self.toggle_current_game_in_batch)
        batch_bar.addWidget(self.batch_toggle)
        footer_layout.addWidget(batch_strip)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.remove_terms = AnimatedButton("删除所选术语")
        self.remove_terms.setObjectName("danger")
        self.remove_terms.setIcon(_icon("fa5s.trash-alt"))
        self.remove_terms.setEnabled(False)
        self.remove_terms.clicked.connect(self.remove_selected_terms)
        actions.addWidget(self.remove_terms)
        actions.addStretch(1)
        self.use_game = AnimatedButton("用于本批字幕")
        self.use_game.setObjectName("primary")
        self.use_game.setIcon(_icon("fa5s.check", SURFACE))
        self.use_game.setEnabled(False)
        self.use_game.clicked.connect(self.use_selected_game)
        actions.addWidget(self.use_game)
        if not self.page_mode:
            close = AnimatedButton("关闭")
            close.setObjectName("outline")
            close.clicked.connect(self._close_hosted)
            actions.addWidget(close)
        footer_layout.addLayout(actions)
        content_layout.addWidget(footer)
        body.addWidget(content, 1)
        layout.addLayout(body, 1)

        self.refresh_learning_suggestions()
        self._refresh_ai_choices()

        for game_name in games:
            self.add_game_item(game_name)
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))

    def _close_hosted(self):
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # P0 Resize: do NOT force fixed width on sidebar; let it keep a comfortable min and let content grow.
        # The sidebar has a reasonable initial fixed in _build; here we only ensure minimums for usability.
        if hasattr(self, "library_sidebar"):
            try:
                self.library_sidebar.setMinimumWidth(210)
            except Exception:
                pass

    # ------------------------------------------------------------ 列表与刷新

    def add_game_item(self, game_name, select=False):
        game_name = self._canonical(game_name)
        identity = self._game_identity(game_name)
        if not game_name or not identity:
            return None
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            if self._game_identity(item.data(Qt.ItemDataRole.UserRole)) == identity:
                item.setText("")
                item.setToolTip(self._game_item_tooltip(game_name))
                row = self.game_list.itemWidget(item)
                if isinstance(row, TermGameListRow):
                    row.update_content(
                        game_name,
                        self._game_term_count(game_name),
                        self._game_type_label(game_name),
                        self._game_reference_count(game_name),
                    )
                if select:
                    self.game_list.setCurrentItem(item)
                return item
        item = QListWidgetItem("")
        item.setData(Qt.ItemDataRole.UserRole, game_name)
        item.setToolTip(self._game_item_tooltip(game_name))
        item.setSizeHint(QSize(0, 58))
        self.game_list.addItem(item)
        row = TermGameListRow(
            game_name,
            self._game_term_count(game_name),
            self._game_type_label(game_name),
            self._game_reference_count(game_name),
            parent=self.game_list,
        )
        row.clicked.connect(lambda target=item: self.game_list.setCurrentItem(target))
        self.game_list.setItemWidget(item, row)
        if select:
            self.game_list.setCurrentItem(item)
        return item

    def _game_term_count(self, game_name):
        mappings = (
            getattr(
                self.legacy,
                "user_confirmed_mappings_for_game",
                self.legacy.learned_mappings_for_game,
            )(game_name)
            if game_name
            else []
        )
        return len(mappings or [])

    def _game_reference_count(self, game_name):
        if not game_name:
            return 0
        if game_name not in self._builtin_cache:
            self._builtin_cache[game_name] = self.builtin_for_game(game_name)
        names, _loaded, hidden = self._builtin_cache[game_name]
        return len([name for name in names if name not in set(hidden)])

    def _game_type_label(self, game_name):
        content_type = getattr(
            self.legacy, "learned_content_type", lambda _name: "game"
        )(game_name)
        return self._type_labels().get(content_type, translate("其它内容", current_language()))

    def _game_item_text(self, game_name):
        return str(game_name)

    def _game_item_tooltip(self, game_name):
        type_labels = self._type_labels()
        current_type = getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
        return (
            f"类型：{type_labels.get(current_type, '其它内容')}\n"
            f"已确认术语 {self._game_term_count(game_name)} 条\n"
            f"查看《{game_name}》的已学习术语与内置词库"
        )

    def _refresh_game_item_counts(self):
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not name:
                continue
            item.setText("")
            item.setToolTip(self._game_item_tooltip(name))
            row = self.game_list.itemWidget(item)
            if isinstance(row, TermGameListRow):
                row.update_content(
                    name,
                    self._game_term_count(name),
                    self._game_type_label(name),
                    self._game_reference_count(name),
                )

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
        from twobyteasr.ui_widgets import category_label

        return category_label(str(item.get("category") or "其他").strip())

    def _unified_term_rows(self) -> list[dict]:
        """Merge learned mappings and builtin references into one row universe.

        来源/状态/启用是三个概念：来源标签可叠加（内置参考 + 已确认），
        状态列表达参考/已确认/已隐藏，是否用于本批由底部开关控制。
        VII 轮：仅差包裹引号的条目（「11号」vs「「11号」」）按归一键合并，
        别名与主词相同（席德（别名 席德））不再重复展示。
        """
        from .glossary_skill import quote_normalize_term

        game_name = self.state["game"]
        if not game_name:
            return []
        mappings = self.state.get("mappings") or []
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
        return rows

    def _term_stats(self) -> dict[str, int]:
        rows = self._unified_term_rows()
        stats = {"total": len(rows), "confirmed": 0, "reference": 0, "hidden": 0}
        for row in rows:
            stats[row.get("status", "reference")] = stats.get(row.get("status", "reference"), 0) + 1
        return stats

    def refresh_learned(self):
        """Populate the unified term table (learned + builtin references)."""
        import time as _t
        _t_rows0 = _t.perf_counter()
        game_name = self.state["game"]
        self._term_model.set_language(current_language())
        query = self.search.text().strip().lower()
        rows = self._unified_term_rows() if game_name else []
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
        items_for_model = []
        for row in rows:
            if query and query not in str(row.get("searchable", "")):
                continue
            if category_filter and str(row.get("category", "")) != category_filter:
                continue
            if status_filter and str(row.get("status", "")) != status_filter:
                continue
            items_for_model.append(row)
        _t_model0 = _t.perf_counter()
        self._term_model.set_data(items_for_model)
        _t_model1 = _t.perf_counter()
        # 标题计数（统一口径：去重后的词条宇宙）
        stats = {"total": len(rows), "confirmed": 0, "reference": 0, "hidden": 0}
        for row in rows:
            stats[row.get("status", "reference")] = stats.get(row.get("status", "reference"), 0) + 1
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
        has_rows = len(items_for_model) > 0
        self.listing.setVisible(has_rows)
        # 空态区分：完全没词 vs 筛选后没词
        self.listing_empty.setVisible(not has_rows)
        if rows:
            bind_text(self.listing_empty_title, '没有符合筛选条件的词条')
            bind_text(self.listing_empty_label, '调整搜索词或筛选条件，即可看到全部词条。')
            for button in (
                getattr(self, "listing_empty_build", None),
                getattr(self, "listing_empty_import", None),
                getattr(self, "listing_empty_smart", None),
            ):
                if button is not None:
                    button.hide()
        else:
            bind_text(self.listing_empty_title, '让识别更懂你的游戏')
            bind_text(self.listing_empty_label, '加入角色名、地点和专有词，可以减少同音词误识别。')
            for button in (
                getattr(self, "listing_empty_build", None),
                getattr(self, "listing_empty_import", None),
                getattr(self, "listing_empty_smart", None),
            ):
                if button is not None:
                    button.show()
        _t_rows1 = _t.perf_counter()
        try:
            if GUI_PROFILE_ENABLED:
                print(f"[perf] Term rows model_set ~{int((_t_model1-_t_model0)*1000)}ms  total_refresh_learned ~{int((_t_rows1-_t_rows0)*1000)}ms  shown={len(items_for_model)}")
        except Exception:
            pass
        self.update_remove_action()

    def refresh_learning_suggestions(self):
        from .glossary_learning import ORIGIN_LABELS

        pending = self._learning_store.pending()
        game_name = str(self.state.get("game", "") or "")
        if game_name:
            existing = {
                (str(item.get("from", "")), str(item.get("to", "")))
                for item in getattr(
                    self.legacy,
                    "user_confirmed_mappings_for_game",
                    self.legacy.learned_mappings_for_game,
                )(game_name)
                if isinstance(item, dict)
            }
            pending = [
                item for item in pending
                if (str(item.get("original_term", "")), str(item.get("corrected_term", ""))) not in existing
            ]
        self.learning_list.clear()
        for entry in pending:
            contexts = [str(item) for item in entry.get("contexts", []) if str(item).strip()]
            projects = [Path(str(item)).stem for item in entry.get("projects", []) if str(item).strip()]
            source_note = f" · {projects[-1]}" if projects else ""
            origin_label = ORIGIN_LABELS.get(
                str(entry.get("origin") or ""), "手动修改"
            )
            item = QListWidgetItem(
                f"{entry.get('corrected_term', '')}  ·  曾由「{entry.get('original_term', '')}」修正 "
                f"{int(entry.get('occurrence_count', 0))} 次 · {origin_label}{source_note}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(entry.get("id", "")))
            confidence = float(entry.get("confidence", 0.0) or 0.0)
            tooltip = [f"置信度：{confidence:.0%}", f"修改类型：{origin_label}"]
            if projects:
                tooltip.append("来源工程：" + "、".join(projects[-3:]))
            tooltip.extend(contexts[-3:])
            bind_text(item, '\n'.join(tooltip) or f'来源：{origin_label}', property='toolTip')
            self.learning_list.addItem(item)
        bind_text(self.learning_count, '{value0} 条待学习', value0=len(pending))
        self.learning_panel.setVisible(bool(pending))
        if pending:
            self.learning_list.selectAll()

    def _selected_learning_ids(self):
        selected = self.learning_list.selectedItems()
        return [str(item.data(Qt.ItemDataRole.UserRole) or "") for item in selected]

    def _learning_destination(self, mode):
        """Project/Profile binding only — never the game that happens to be
        selected in the sidebar, so unbound corrections cannot silently land
        in an unrelated library."""
        if mode == "project":
            project = getattr(getattr(self.owner, "studio_page", None), "project", None)
            if project and project.glossary_ids:
                return str(project.glossary_ids[0])
        if mode == "profile":
            profile = getattr(self.owner, "current_project_profile", None)
            glossaries = getattr(profile, "glossary_ids", None)
            if glossaries:
                return str(glossaries[0])
        return ""

    @glossary_write_errors
    def _accept_learning_suggestions(self, mode):
        candidate_ids = self._selected_learning_ids()
        destination = self._learning_destination(mode)
        if not candidate_ids:
            self._show_toast("请选择要接受的自动学习建议。")
            return
        if not destination:
            self._show_toast(
                "该来源工程 / Profile 未绑定游戏词库，无法确定入库目标。"
                "请先在工程或 Profile 中关联词库（不会写入当前侧栏选中的游戏）。"
            )
            return
        accepted = self._learning_store.accept(
            candidate_ids,
            destination,
            add_mapping=self.legacy.add_learned_mapping,
        )
        self._mappings_cache.pop(destination, None)
        self.refresh_learning_suggestions()
        if self._game_identity(destination) == self._game_identity(self.state.get("game", "")):
            self.refresh_current_game()
        self._show_toast(tr('已将 {value0} 条建议加入《{value1}》词库。', value0=accepted, value1=destination))

    def _ignore_learning_suggestions(self):
        candidate_ids = self._selected_learning_ids()
        if not candidate_ids:
            self._show_toast("请选择要忽略的自动学习建议。")
            return
        ignored = self._learning_store.ignore(candidate_ids)
        self.refresh_learning_suggestions()
        self._show_toast(tr('已忽略 {value0} 条建议。', value0=ignored))

    # ------------------------- unified table bulk actions -------------------------

    def _selected_rows_by_status(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for idx in self.listing.selectionModel().selectedRows(0):
            row = self._term_model.data_for_row(idx.row())
            if not row:
                continue
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
        added = 0
        for row in rows:
            reference = row.get("reference") or {}
            name = str(reference.get("name") or row.get("source") or "").strip()
            if name and self.legacy.add_learned_mapping(
                game_name,
                name,
                name,
                category=str(reference.get("category") or "其他"),
                origin="用户确认",
            ):
                added += 1
        if added:
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()
            self._refresh_game_item_counts()
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
        game_name = self.state["game"]
        type_labels = self._type_labels()
        selected_type = (
            getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
            if game_name
            else ""
        )
        (bind_text(self.selected_title, f"{game_name}  ·  {type_labels.get(selected_type, translate('其它内容', current_language()))}") if game_name else bind_text(self.selected_title, translate('请选择游戏 / 内容', current_language())))
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
            if game_name in self._mappings_cache:
                t_lookup0 = _t.perf_counter()
                self.state["mappings"] = self._mappings_cache[game_name]
                t_lookup1 = _t.perf_counter()
                if GUI_PROFILE_ENABLED:
                    print(f"[perf] Term mappings cache hit {game_name!r} lookup~{int((t_lookup1-t_lookup0)*1000)}ms")
            else:
                t_disk0 = _t.perf_counter()
                raw = getattr(
                    self.legacy,
                    "user_confirmed_mappings_for_game",
                    self.legacy.learned_mappings_for_game,
                )(game_name)
                t_disk1 = _t.perf_counter()
                self.state["mappings"] = raw or []
                self._mappings_cache[game_name] = self.state["mappings"]
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
        self.refresh_learning_suggestions()
        t_row1 = _t.perf_counter()
        if GUI_PROFILE_ENABLED:
            print(f"[perf] Term row creation (model set) ~{int((t_row1-t_row0)*1000)}ms")
        stats = self._term_stats()
        ((bind_text(self.selected_stats, f"{stats['confirmed']} confirmed") if current_language() == 'en' else bind_text(self.selected_stats, '{value0} 条已确认', value0=stats['confirmed'])) if game_name else bind_text(self.selected_stats, translate('尚未选择', current_language())))
        ((bind_text(self.official_stats, f"{stats['reference']} references" + (f" · {stats['hidden']} hidden" if stats['hidden'] else '')) if current_language() == 'en' else bind_text(self.official_stats, '{value0} 条参考{value1}', value0=stats['reference'], value1=f" · {stats['hidden']}tr(' 已隐藏')" if stats['hidden'] else '')) if game_name else bind_text(self.official_stats, translate('0 条参考', current_language())))
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
            self.filter_category,
            self.filter_status,
            self.term_editor,
            self.term_category,
            self.add_term_button,
            self.smart_build_button,
            self.import_terms,
            self.ai_history_button,
        ):
            widget.setEnabled(enabled)
        # AI 更新按钮语义由全局任务管理器推导（VII 轮）：切游戏不得把运行中任务刷没。
        self._ensure_task_manager()
        self._refresh_ai_update_buttons()
        is_current = enabled and self._current_game_in_batch()
        self.use_game.setEnabled(enabled and not is_current)
        ((bind_text(self.use_game, '✓ Used in this batch') if is_current else bind_text(self.use_game, 'Use in this batch')) if current_language() == 'en' else (bind_text(self.use_game, '✓ 已用于本批字幕') if is_current else bind_text(self.use_game, '用于本批字幕')))
        # 删除游戏只对非保护游戏可用（C7 与删除术语分离）
        protected = self._game_identity(game_name) in self.protected_game_ids
        self.delete_game_button.setEnabled(enabled and not protected)
        self.delete_game_button.setIcon(
            qta.icon("fa5s.trash-alt", color="#8a5a4c", color_disabled="#8a5a4c")
        )
        bind_text(self.delete_game_button, translate('内置/受保护游戏不可删除' if protected else '删除当前游戏及其术语', current_language()), property='toolTip')
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))
        # 游戏搜索仅在列表较多时出现（C5 搜索降级）
        self.game_search.setVisible(self.game_list.count() > 8)
        self._refresh_game_item_counts()
        self._refresh_batch_bar()
        self.update_remove_action()

    def update_remove_action(self):
        by_status = self._selected_rows_by_status()
        confirmed_rows = by_status.get("confirmed", [])
        reference_rows = by_status.get("reference", [])
        hidden_rows = by_status.get("hidden", [])
        selected = len(confirmed_rows) + len(reference_rows) + len(hidden_rows)
        ((bind_text(self.remove_terms, f'Delete selected terms ({selected})') if selected else bind_text(self.remove_terms, 'Delete selected terms')) if current_language() == 'en' else (bind_text(self.remove_terms, '删除所选术语（{value0}）', value0=selected) if selected else bind_text(self.remove_terms, '删除所选术语')))
        self.remove_terms.setEnabled(bool(confirmed_rows))
        if hasattr(self, "bulk_confirm"):
            self.bulk_confirm.setEnabled(bool(reference_rows))
        if hasattr(self, "bulk_hide"):
            (bind_text(self.bulk_hide, '恢复所选') if hidden_rows and (not reference_rows) else bind_text(self.bulk_hide, '隐藏所选'))
            self.bulk_hide.setEnabled(bool(reference_rows or hidden_rows))

    # ------------------------------------------------------------ 交互

    def select_game(self, current, _previous=None):
        for index in range(self.game_list.count()):
            item = self.game_list.item(index)
            row = self.game_list.itemWidget(item)
            if isinstance(row, TermGameListRow):
                row.set_selected(item is current)
        game_name = str(current.data(Qt.ItemDataRole.UserRole)) if current else ""
        self.state["game"] = game_name
        self.search.clear()
        # P0 perf: switch header instantly (<100ms feel), defer the 650-row table build.
        type_labels = self._type_labels()
        selected_type = (
            getattr(self.legacy, "learned_content_type", lambda _name: "game")(game_name)
            if game_name else ""
        )
        (bind_text(self.selected_title, f"{game_name}  ·  {type_labels.get(selected_type, translate('其它内容', current_language()))}") if game_name else bind_text(self.selected_title, translate('请选择游戏 / 内容', current_language())))
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
        QTimer.singleShot(0, self.refresh_current_game)

    def apply_filter(self, _text=""):
        self.refresh_learned()
        if self.state["game"]:
            stats = self._term_stats()
            (bind_text(self.selected_stats, f"{stats['confirmed']} confirmed") if current_language() == 'en' else bind_text(self.selected_stats, '{value0} 条已确认', value0=stats['confirmed']))

    def _toggle_search(self):
        self.search.setVisible(True)
        self.search.setFocus()
        self.search.selectAll()

    def create_game(self):
        game_name = self._canonical(self.game_input.text())
        if not game_name:
            self.game_input.setFocus()
            return
        getattr(self.legacy, "ensure_learned_content", lambda *_args: True)(
            game_name, str(self.content_type.currentData() or "game")
        )
        self.add_game_item(game_name, select=True)
        self.game_input.clear()
        (bind_text(self.library_badge, f'{self.game_list.count()} games') if current_language() == 'en' else bind_text(self.library_badge, '{value0} 个游戏', value0=self.game_list.count()))
        (bind_text(self.owner.term_hint, f'Created the {game_name} term library') if current_language() == 'en' else bind_text(self.owner.term_hint, '已创建《{value0}》术语库', value0=game_name))

    def delete_current_game(self):
        game_name = self.state["game"]
        if not game_name or self._game_identity(game_name) in self.protected_game_ids:
            return
        self._show_delete_game_confirm(game_name)

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

        q = bind_text(QLabel(), '要从术语库中删除《{game_name}》以及它的术语吗？\n内置词库文件不会被修改。', game_name=game_name)
        q.setWordWrap(True)
        q.setStyleSheet("font-weight:600;")
        lay.addWidget(q)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_del = QPushButton("删除")
        do_del.setStyleSheet(
            "QPushButton { background:#f6e9e5; color:#8a5a4c; border:1px solid #e3c9c2; border-radius:10px; padding:6px 14px; font-weight:700; }"
            "QPushButton:hover { background:#f3e0db; }"
        )
        row.addWidget(cancel)
        row.addWidget(do_del)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            sw, sh = 420, 140
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
            identity = self._game_identity(game_name)
            learned_deleted = getattr(
                self.legacy, "delete_learned_game", lambda _name: False
            )(game_name)
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
                if it and self._game_identity(it.data(Qt.ItemDataRole.UserRole) or it.text()) == self._game_identity(game_name):
                    self.game_list.takeItem(i)
                    break
            self.state["game"] = ""
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
        # 2026-09-02：未选择游戏/内容时不再静默返回（表现为"没办法添加词语"）——
        # 落到「通用词库」并提示；输入为空也给 toast 反馈。
        game_name = str(self.state.get("game") or "").strip()
        if not game_name:
            game_name = "通用词库"
            self._show_toast("未选择游戏/内容，已添加到「通用词库」")
        value = self.term_editor.text().strip()
        if not value:
            self._show_toast("请先输入术语内容（原文或 原文=译名）")
            return
        source, target = self.parse_term(value)
        category = str(self.term_category.currentData() or "其他")
        if self.legacy.add_learned_mapping(
            game_name,
            source,
            target,
            category=category,
            origin="手动",
        ):
            self.term_editor.clear()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            if not self.state.get("game"):
                self.state["game"] = game_name
                self.add_game_item(game_name, select=True)
            self.refresh_current_game()
            (bind_text(self.owner.term_hint, f'Added term: {target} ({game_name})') if current_language() == 'en' else bind_text(self.owner.term_hint, '已添加术语：{value0}（《{value1}》）', value0=target, value1=game_name))
        else:
            # Replace native info with a small warm in-app toast sheet.
            self._show_toast(tr('添加术语失败：该术语已存在或内容为空。'))

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

    # ------------------------- P0: Warm in-app Edit / Delete (no native black dialogs) -------------------------

    def _show_edit_sheet(self, mapping: dict):
        """Show a warm styled edit sheet inside the term library card (hosted or standalone).
        Replaces QInputDialog to avoid black system dialogs.
        """
        game_name = self.state["game"]
        if not game_name:
            return
        source = str(mapping.get("from") or "")
        target = str(mapping.get("to") or "")
        current = target if source == target else f"{source} → {target}"

        # Local dim layer + card (child of this content so no new HWND).
        if hasattr(self, "_edit_sheet") and self._edit_sheet is not None:
            try:
                self._edit_sheet.setParent(None)
            except Exception:
                pass

        dim = QFrame(self)
        dim.setObjectName("termEditDim")
        dim.setStyleSheet(f"background: {_sheet_theme().overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termEditSheet")
        sheet.setStyleSheet(
            f"QFrame#termEditSheet {{ background:{_sheet_theme().surface}; border:1px solid {_sheet_theme().border}; border-radius:12px; }}"
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        title = QLabel("编辑术语")
        title.setStyleSheet("font-weight:700; font-size:14px; color:#292a27;")
        lay.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 4)
        form.setSpacing(6)

        term_edit = QLineEdit(current)
        bind_text(term_edit, '专名，或 错词 → 正确词', property='placeholderText')
        form.addRow("术语 / 错词 → 正确词", term_edit)

        cat = QComboBox()
        for c in ("角色", "Boss", "物品", "方块", "阵营", "地点", "人物", "模型", "技能", "事件", "其他"):
            cat.addItem(c, c)
        cur_cat = self._mapping_category(mapping) or "其他"
        idx = cat.findData(cur_cat)
        if idx >= 0:
            cat.setCurrentIndex(idx)
        form.addRow("分类", cat)
        lay.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        save = QPushButton("保存")
        save.setObjectName("workshopAction")
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

        def _place():
            # center sheet over current view
            pr = self.rect()
            sw, sh = 420, 180
            sheet.setGeometry((pr.width() - sw)//2, max(40, (pr.height() - sh)//2 - 20), sw, sh)

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

        self._edit_sheet = sheet
        self._edit_dim = dim
        added_by_this_edit = set()

        @glossary_write_errors(owner=self)
        def _save():
            val = term_edit.text().strip()
            if not val:
                _cleanup()
                return
            new_source, new_target = self.parse_term(val)
            if (new_source, new_target) == (source, target) and (cat.currentData() or "其他") == self._mapping_category(mapping):
                _cleanup()
                return
            key = (new_source, new_target)
            ok = key in added_by_this_edit
            if not ok:
                ok = self.legacy.add_learned_mapping(
                    game_name, new_source, new_target,
                    category=str(cat.currentData() or "其他"),
                    origin=self._mapping_origin(mapping),
                )
                if ok:
                    added_by_this_edit.add(key)
            if not ok:
                # keep simple; surface via owner hint
                bind_text(self.owner.term_hint, '修改后的术语已存在或内容为空')
                return
            self.legacy.delete_learned_mappings(game_name, [(source, target)])
            _cleanup()
            self._mappings_cache.pop(game_name, None)
            self._builtin_entry_cache.pop(game_name, None)
            self.refresh_current_game()

        def _cancel():
            _cleanup()

        save.clicked.connect(_save)
        cancel.clicked.connect(_cancel)
        # allow Esc on sheet
        sheet.installEventFilter(self)

        # keep refs so we can close on resize etc.
        self._edit_cleanup = _cleanup

    def _show_delete_confirm(self, key):
        """Small warm delete confirm, replacing QMessageBox.question."""
        game_name = self.state["game"]
        if not game_name:
            return
        source, target = key
        label = target if source == target else f"{source} → {target}"

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
        q.setStyleSheet("font-weight:600;")
        lay.addWidget(q)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_del = QPushButton("删除")
        # low-saturation danger
        do_del.setStyleSheet(
            "QPushButton { background:#f6e9e5; color:#8a5a4c; border:1px solid #e3c9c2; border-radius:10px; padding:6px 14px; font-weight:700; }"
            "QPushButton:hover { background:#f3e0db; }"
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
            self.legacy.delete_learned_mappings(game_name, [key])
            _cleanup()
            self.refresh_current_game()

        def _cancel():
            _cleanup()

        do_del.clicked.connect(_confirm)
        cancel.clicked.connect(_cancel)
        sheet.installEventFilter(self)
        self._del_cleanup = _cleanup

    def edit_mapping(self, mapping: dict):
        self._show_edit_sheet(mapping)

    def delete_mapping(self, key):
        self._show_delete_confirm(key)

    def remove_selected_terms(self):
        """Delete user-confirmed mappings; builtin reference rows revert to 参考 status."""
        game_name = self.state["game"]
        if not game_name:
            return
        keys = []
        for idx in self.listing.selectionModel().selectedRows(0):
            rd = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
            if rd and rd.get("status") == "confirmed" and rd.get("raw"):
                st = (rd.get("source"), rd.get("target"))
                if st[0] and st[1]:
                    keys.append(st)
        if keys and self.legacy.delete_learned_mappings(game_name, keys):
            self.refresh_current_game()

    # P0-5: action handlers for the table (no per-row QWidgets)
    def _on_table_double_click(self, idx: QModelIndex):
        if not idx.isValid():
            return
        rd = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
        if rd and rd.get("raw"):
            self.edit_mapping(rd["raw"])

    @glossary_write_errors
    def _on_table_clicked(self, idx: QModelIndex):
        if not idx.isValid():
            return
        # Only react on the 操作 column (col 4) for the row's primary action.
        if idx.column() != 4:
            return
        rd = self._term_model.data_for_row(idx.row()) if hasattr(self, "_term_model") else None
        if not rd:
            return
        status = str(rd.get("status", ""))
        if status == "confirmed" and rd.get("raw"):
            self.edit_mapping(rd["raw"])
        elif status == "reference":
            # 确认单条参考（from==to 用户确认映射）
            game_name = self.state.get("game", "")
            reference = rd.get("reference") or {}
            name = str(reference.get("name") or rd.get("source") or "").strip()
            if game_name and name and self.legacy.add_learned_mapping(
                game_name,
                name,
                name,
                category=str(reference.get("category") or "其他"),
                origin="用户确认",
            ):
                self._mappings_cache.pop(game_name, None)
                self._builtin_entry_cache.pop(game_name, None)
                self.refresh_current_game()
                self._show_toast(tr('已确认「{value0}」。', value0=name))
        elif status == "hidden":
            game_name = self.state.get("game", "")
            name = str((rd.get("reference") or {}).get("name") or rd.get("source") or "")
            setter = getattr(self.legacy, "set_reference_terms_hidden", None)
            if game_name and name and setter and setter(game_name, [name], False):
                self._builtin_cache.pop(game_name, None)
                self._builtin_entry_cache.pop(game_name, None)
                self.refresh_current_game()
                self._show_toast(tr('已恢复「{value0}」。', value0=name))

    def show_import_dialog(self):
        """P0: Warm hosted import sheet inside TermLibrary content (no native SpringDialog)."""
        game_name = self.state["game"]
        if not game_name:
            return

        # Avoid stacking multiple import sheets
        if hasattr(self, "_import_sheet") and self._import_sheet is not None:
            try:
                self._import_sheet.setParent(None)
            except Exception:
                pass

        dim = QFrame(self)
        dim.setObjectName("termImportDim")
        dim.setStyleSheet(f"background: {_sheet_theme().overlay_scrim}; border:0;")
        dim.setGeometry(self.rect())
        dim.show()
        dim.raise_()

        sheet = QFrame(self)
        sheet.setObjectName("termImportSheet")
        sheet.setStyleSheet(
            f"QFrame#termImportSheet {{ background:{IVORY}; border:1px solid {LINE}; border-radius:12px; }}"
        )
        sheet.setAutoFillBackground(True)

        lay = QVBoxLayout(sheet)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        title = bind_text(QLabel(), '批量导入术语｜{game_name}', game_name=game_name)
        title.setStyleSheet("font-weight:700; font-size:14px; color:#292a27;")
        lay.addWidget(title)

        hint = QLabel("每行一条。只写“角色名”表示确认正确写法；也可写“常见错词 → 正确词”。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lay.addWidget(hint)

        editor = QPlainTextEdit()
        bind_text(editor, '芙宁娜\n水神 → 芙宁娜\n星见雅', property='placeholderText')
        lay.addWidget(editor, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("workshopSecondary")
        do_imp = QPushButton("导入")
        do_imp.setObjectName("workshopAction")
        row.addWidget(cancel)
        row.addWidget(do_imp)
        lay.addLayout(row)

        def _place():
            pr = self.rect()
            sw = min(560, max(420, pr.width() - 80))
            sh = min(420, max(260, pr.height() - 120))
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

        self._import_sheet = sheet
        self._import_dim = dim

        @glossary_write_errors(owner=self)
        def _save():
            added = 0
            for raw in editor.toPlainText().splitlines():
                value = str(raw or "").strip()
                if not value or value.startswith("#"):
                    continue
                source, target = self.parse_term(value)
                if self.legacy.add_learned_mapping(
                    game_name, source, target, category="其他", origin="批量导入"
                ):
                    added += 1
            _cleanup()
            self.refresh_current_game()
            (bind_text(self.owner.term_hint, f'Imported {added} terms into {game_name}') if current_language() == 'en' else bind_text(self.owner.term_hint, '已批量导入 {value0} 条术语到《{value1}》', value0=added, value1=game_name))

        def _cancel():
            _cleanup()

        do_imp.clicked.connect(_save)
        cancel.clicked.connect(_cancel)
        sheet.installEventFilter(self)
        self._import_cleanup = _cleanup

    def use_selected_game(self):
        game_name = self.state["game"]
        if not game_name:
            return
        self.owner.game_box.setCurrentText(game_name)
        self.owner.terms.setChecked(True)
        self.legacy.save_runtime_game_history(game_name)
        identity = self._game_identity(game_name)
        enabled = list(self.owner._enabled_glossary_ids())
        if identity and identity not in enabled:
            enabled.append(identity)
        self.owner.legacy.RUNTIME_SETTINGS.setdefault("glossary", {})
        self.owner.legacy.RUNTIME_SETTINGS["glossary"]["enabled_glossary_ids"] = enabled
        self.owner._save_glossary_settings()
        (bind_text(self.owner.term_hint, f'This batch will use the {game_name} term library') if current_language() == 'en' else bind_text(self.owner.term_hint, '本批字幕将使用《{value0}》术语库', value0=game_name))
        self.refresh_current_game()

    def _current_game_in_batch(self) -> bool:
        game_name = self.state["game"]
        if not game_name:
            return False
        identity = self._game_identity(game_name)
        return bool(identity) and identity in self.owner._enabled_glossary_ids()

    def _refresh_batch_bar(self):
        enabled_ids = self.owner._enabled_glossary_ids()
        in_batch = self._current_game_in_batch()
        if in_batch:
            bind_text(self.batch_status, translate('当前词库已用于本批', current_language()))
            bind_text(self.batch_toggle, translate('从本批移除', current_language()))
        else:
            (bind_text(self.batch_status, f'{len(enabled_ids)} term libraries enabled for this batch') if current_language() == 'en' else bind_text(self.batch_status, '本批已启用 {value0} 个词库', value0=len(enabled_ids)))
            bind_text(self.batch_toggle, translate('加入本批', current_language()))
        self.batch_toggle.setEnabled(bool(self.state["game"]))

    def toggle_current_game_in_batch(self):
        game_name = self.state["game"]
        if not game_name:
            return
        identity = self._game_identity(game_name)
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
        self._refresh_batch_bar()

    def open_smart_build(self):
        game_name = self.state["game"]
        if not game_name:
            return
        # P0: host inside ModalHost (no new native window). Content at final size; backdrop fade only.
        content = SmartGlossaryDialog(self.owner, game_name, self.owner._modal_host.body if hasattr(self.owner, "_modal_host") else self)
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
            from twobyteasr.main_ui_dialogs import SpringDialog
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
        from .i18n_widgets import add_combo_item

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
        from .llm_config import active_service_values, resolved_service_values

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
        if capability["provider_search"]:
            bind_text(self.ai_capability_label, '● 支持联网检索')
            self.ai_capability_label.setToolTip(capability["reason"])
        else:
            bind_text(self.ai_capability_label, '○ 无服务端搜索')
            bind_text(self.ai_capability_label, '{value0}；仍可用智能建词的本地资料整理。', property='toolTip', value0=capability['reason'])

    def _ai_update_settings(self) -> dict:
        from .glossary_skill import settings_with_service_override

        service_id = str(self.ai_service_combo.currentData() or "")
        model = str(self.ai_model_combo.currentText() or "").strip()
        settings = dict(self.legacy.RUNTIME_SETTINGS)
        if not service_id:
            from .llm_config import active_service_values
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
        new_id, created = manager.submit(
            task.game,
            "full",
            settings,
            service_label=str(detect_search_capability(settings).get("service") or ""),
            model_label=str(detect_search_capability(settings).get("model") or ""),
            resume_task_id=task_id,
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
                bind_text(self.ai_update_button, '联网更新当前词库')
            else:
                self.ai_update_button.setText(label)
                bind_text(self.ai_full_button, '完整建库…')
        else:
            bind_text(self.ai_update_button, '联网更新当前词库')
            bind_text(self.ai_full_button, '完整建库…')

    def _start_ai_update(self, mode: str = "incremental", *, execution_mode='auto'):
        from .glossary_skill import detect_search_capability

        game_name = self.state.get("game", "")
        if not game_name:
            self._show_toast("请先选择要更新的游戏词库。")
            return
        manager = self._ensure_task_manager()
        settings = self._ai_update_settings()
        import copy
        settings = copy.deepcopy(settings)
        if mode == 'full':
            settings.setdefault('models', {})['glossary_execution_mode'] = execution_mode
            if execution_mode == 'ai':
                settings['models'].update(glossary_enrich_names=True, glossary_include_community=False,
                                          glossary_max_model_calls=1, glossary_enrich_batch_size=28)
        capability = detect_search_capability(settings)
        if not capability["provider_search"] and execution_mode not in {'fast','refresh'}:
            self._show_toast(
                "当前 AI 不支持联网检索（缺少服务端搜索）。"
                "请在左侧选择 Grok/Antigravity CLI 或百炼；或使用智能建词的本地资料整理。"
            )
            return
        service_label = self.ai_service_combo.currentText() or str(capability.get("service") or "")
        task_id, created = manager.submit(
            game_name,
            mode,
            settings,
            service_label=service_label,
            model_label=str(capability.get("model") or ""),
        )
        if not created:
            # 同游戏+同模式去重：点击直接带用户去看任务，而不是抛一句"已有任务"。
            task = manager.get(task_id)
            if task is not None and task.status in {"finished", "partial"} and task.result:
                self._open_update_review(task.game, task.result)
            elif task is not None:
                self._open_task_candidates(task)
            return
        mode_label = "完整建库（清单式分批）" if mode == "full" else "版本增量更新"
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
            from twobyteasr.main_ui_dialogs import SpringDialog
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
            from twobyteasr.main_ui_dialogs import SpringDialog
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
