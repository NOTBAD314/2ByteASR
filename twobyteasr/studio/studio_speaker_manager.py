"""Speaker manager: one card per speaker (2026-10-18 redesign).

Common actions take one click on a card and apply at once as an undoable
command: rename, colour, host, visibility, preview, the role (主要 / 游戏声 /
忽略) and merging into another speaker. Rare tools (MOSS cache folder,
re-recognition, count policy, merge-all) sit behind “更多工具”; batch
organisation sits behind “多选”. Recognition data is never re-requested.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
import os
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..design.studio_theme import (
    _active_theme,
    apply_secondary_surface_theme,
    build_secondary_surface_qss,
    create_studio_menu,
    studio_message_box,
)
from ..i18n import bind_text, join_text, tr
from ..projects.speaker_names import display_speaker_name
from ..projects.studio_project import StudioSpeaker
from ..timeline.studio_commands import (
    AssignSpeakerCommand,
    RecoverSpeakersCommand,
    SetHostSpeakerCommand,
    SetSpeakerCommand,
    SetSpeakersVisibilityCommand,
    SpeakerStateCommand,
)
from .studio_cue_table import _speaker_color
from .studio_helpers import _format_ms
from ..design.themed_icons import themed_icon
from .studio_speaker_board import MergePanel, SpeakerBox, SpeakerTile, build_speaker_board_qss
from .studio_speaker_cards import SpeakerCard, build_speaker_manager_qss, swatch_menu

if TYPE_CHECKING:
    from .studio_ui import SubtitleStudioPage

BACKGROUND = "GAME_BACKGROUND"
UNIFIED = "SUBTITLES"
_GROUPS = {BACKGROUND, UNIFIED}
_FILTER_THRESHOLD = 8
_SWATCHES = ("#e0809f", "#a990e0", "#7fb8c2", "#93cdb8", "#dc9a7c", "#c9b27e", "#6186b0", "#8d70a0",
             "#5f9270", "#aa855d", "#9b7180", "#858179")


def _duration_text(milliseconds: float) -> str:
    seconds = max(0, int(float(milliseconds) / 1000 + 0.5))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return tr("{hours} 小时 {minutes} 分", hours=hours, minutes=minutes)
    if minutes:
        return tr("{minutes} 分 {seconds} 秒", minutes=minutes, seconds=f"{seconds:02d}")
    return tr("{seconds} 秒", seconds=seconds)


def _clock(milliseconds: float) -> str:
    total = max(0, int(milliseconds) // 1000)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _source_name(processing: dict) -> str:
    if processing.get("backend") == "nemotron":
        return tr("Nemotron 3 本地说话人区分")
    if processing.get("backend") == "ecapa":
        return tr("ECAPA 声学聚类")
    if processing.get("status") == "native":
        return tr("Filetrans 原生标签")
    return tr("完整 MOSS") if processing.get("moss_called") else tr("原始说话人标签")


class _LazyCards(Mapping):
    """Detail cards by key (the right-hand column), created when first looked at.

    2026-11-12 (speaker board): with many speakers only the cards a person
    opens are built; ``created()`` lists the ones that exist."""

    def __init__(self, owner):
        self.owner = owner
        self.order: list[str] = []
        self.made: dict[str, SpeakerCard] = {}

    def __getitem__(self, key):
        if key not in self.order:
            raise KeyError(key)
        card = self.made.get(key)
        return card if card is not None else self.owner._make_card(key)

    def __contains__(self, key):
        return key in self.order

    def __iter__(self):
        return iter(list(self.order))

    def __len__(self):
        return len(self.order)

    def created(self) -> list[SpeakerCard]:
        return [self.made[key] for key in self.order if key in self.made]


_HINTS = {
    "main": "拖到这里：各自有一条字幕轨",
    "secondary": "拖到这里：说话不多的人收进同一条轨",
    "game": "拖到这里归入游戏声",
    "ignore": "拖到这里就不输出",
}


class SpeakerManagerDialog(QDialog):
    WIDTH, HEIGHT = 1100, 780

    def __init__(self, page: "SubtitleStudioPage"):
        super().__init__(page)
        self.page = page
        self.cards = _LazyCards(self)
        self.tiles: dict[str, SpeakerTile] = {}
        self._data: dict[str, dict] = {}
        self._box_index: dict[str, str] = {}
        self._group: set[str] = set()
        self._selection: set[str] = set()
        self._anchor = ""
        self._focus = ""
        self._sort = "size"
        self._committing_name = False
        self._refreshing = False
        self._banner_dismissed = False
        self._snapshot: dict | None = None
        self._snapshot_in_project = False
        self._snapshot_error = ""
        self._staged_roles: dict[str, str] = {}
        self._stats: dict[str, dict] = {}
        self._representatives: dict[str, tuple[int, int, str]] = {}
        self._applying = False
        self._pending_roles = {}
        self._role_project = page.project
        self._role_timer = QTimer(self)
        self._role_timer.setSingleShot(True)
        self._role_timer.timeout.connect(self._drain_roles)
        self._preview_card = None
        self._preview_key = ""
        self._preview_video = None
        self._preview_return_rate = 1.0
        self._voiceprint_mailbox = queue.Queue()
        self._voiceprint_cancel = threading.Event()
        self._voiceprint_report = None
        self._voiceprint_timer = QTimer(self)
        self._voiceprint_timer.setInterval(150)
        self._voiceprint_timer.timeout.connect(self._voiceprint_poll)
        bind_text(self, "说话人管理", property="windowTitle")
        # 2026-11-12 (user): no Windows title bar; a round window like 翻译字幕.
        self.setObjectName("speakerManager")
        apply_secondary_surface_theme(self)
        theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(theme) + build_speaker_manager_qss(theme)
                           + build_speaker_board_qss(theme))
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._stop_preview)
        self.finished.connect(self._stop_preview)
        self._build_ui()
        from ..app.rounded_window import RoundedWindow
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.header], radius=26)
        self.setMinimumSize(980, 600)
        screen = (page.screen() if hasattr(page, "screen") else None) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        self.resize(min(self.WIDTH, area.width() - 40) if area else self.WIDTH,
                    min(self.HEIGHT, area.height() - 40) if area else self.HEIGHT)
        from ..projects.low_share_speakers import apply_low_share_policy
        grouped = apply_low_share_policy(page.project)
        if grouped is not None and grouped.generation_metadata['speaker_organization']['low_share_policy']['ignored']:
            from ..timeline.studio_commands import SetCandidateRoleCommand
            command = SetCandidateRoleCommand(page.project, grouped, page._speaker_structure_changed,
                                              automatic=True, undo_stack=page.undo_stack)
            command.setText(tr('低占比说话人默认忽略'))
            self._push(command)
        self._load_snapshot()
        if self._snapshot:
            report = self._snapshot.get('processing', {}).get('voiceprint_review')
            if isinstance(report, dict) and report.get('groups'):
                from ..recognition.scoped_voiceprint import VERSION, cue_signature
                # An earlier version's candidates cannot be applied; compare again.
                if (report.get('version') == VERSION
                        and report.get('cue_signature') == cue_signature(self.page.project.cues)):
                    report = self._undecided_groups(report)
                    if report['groups']:
                        self._voiceprint_report = report
                        bind_text(self.voiceprint_button, '查看声纹候选')
        self.refresh()
        # 2026-11-13 (user): open on the first speaker's details, not an empty column.
        order = self._visible_order()
        if order and not self._selection:
            self._tile_clicked(order[0], Qt.KeyboardModifier.NoModifier)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        page.undo_stack.indexChanged.connect(self._undo_index_changed)
        for sequence, slot in ((QKeySequence.StandardKey.Undo, page.undo_stack.undo),
                               (QKeySequence.StandardKey.Redo, page.undo_stack.redo),
                               (QKeySequence("Ctrl+Y"), page.undo_stack.redo)):
            QShortcut(sequence, self, slot)
        self._select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self,
                                              lambda: self._select_visible("all"))
        self._delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self,
                                          lambda: self._selected_ids() and self._batch("delete"))

    # ------------------------------------------------------------------ layout
    @staticmethod
    def _button(text: str, name: str, slot=None, *, icon: str = "", role: str = "secondary", tip: str = ""):
        button = QPushButton()
        button.setObjectName(name)
        bind_text(button, text)
        if tip:
            bind_text(button, tip, property="toolTip")
        if icon:
            button.setIcon(themed_icon(icon, role))
            button.setIconSize(QSize(13, 13))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoDefault(False)
        if slot is not None:
            button.clicked.connect(lambda _checked=False: slot())
        return button

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.root = QWidget()
        self.root.setObjectName("speakerManagerRoot")
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.root)
        column = QVBoxLayout(self.root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # -- header: badge, title, counts, tools, close -------------------
        self.header = QFrame()
        self.header.setObjectName("speakerHeader")
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(20, 16, 14, 10)
        head.setSpacing(12)
        badge = QLabel()
        badge.setObjectName("speakerBadge")
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(themed_icon("fa5s.users", "on_accent").pixmap(19, 19))
        head.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel()
        title.setObjectName("speakerTitle")
        bind_text(title, "说话人管理")
        titles.addWidget(title)
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("speakerMeta")
        meta.addWidget(self.summary_label)
        self.source_label = QLabel()
        self.source_label.setObjectName("speakerMetaWarn")
        meta.addWidget(self.source_label)
        meta.addStretch(1)
        titles.addLayout(meta)
        head.addLayout(titles, 1)
        self.more_toggle = QToolButton()
        self.more_toggle.setObjectName("speakerGhostButton")
        self.more_toggle.setCheckable(True)
        self.more_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_toggle.setIcon(themed_icon("fa5s.sliders-h", "secondary"))
        self.more_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.more_toggle, "更多工具")
        bind_text(self.more_toggle, "MOSS 缓存、重新识别、整理", property="toolTip")
        self.more_toggle.toggled.connect(self._toggle_more)
        head.addWidget(self.more_toggle)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("speakerWindowClose")
        self.close_button.setFixedSize(34, 34)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.close_button, "关闭", property="toolTip")
        self.close_button.clicked.connect(self.reject)
        head.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        column.addWidget(self.header)

        # -- body: boxes on the left, details on the right --------------------
        body = QWidget()
        body.setObjectName("speakerManagerBody")
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        left = QWidget()
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(20, 2, 10, 0)
        lcol.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.speaker_filter = QLineEdit()
        self.speaker_filter.setObjectName("speakerSearch")
        self.speaker_filter.setFixedWidth(230)
        self.speaker_filter.setClearButtonEnabled(True)
        bind_text(self.speaker_filter, "搜索名字或标签", property="placeholderText")
        self.speaker_filter.textChanged.connect(self._filter_rows)
        toolbar.addWidget(self.speaker_filter)
        self.pending_button = self._button("只看待确认", "speakerPillButton", icon="fa5s.filter", role="secondary")
        self.pending_button.setCheckable(True)
        self.pending_button.toggled.connect(lambda _on: self._filter_rows())
        toolbar.addWidget(self.pending_button)
        toolbar.addStretch(1)
        self.sort_button = QToolButton()
        self.sort_button.setObjectName("speakerGhostButton")
        self.sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sort_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sort_button.setIcon(themed_icon("fa5s.sort-amount-down", "secondary"))
        self.sort_menu = create_studio_menu(self.sort_button)
        for key, label in (("size", "按说话量"), ("time", "按出现先后"), ("id", "按编号")):
            action = self.sort_menu.addAction(tr(label))
            action.setData(key)
            action.triggered.connect(lambda _=False, value=key: self._set_sort(value))
        self.sort_button.setMenu(self.sort_menu)
        toolbar.addWidget(self.sort_button)
        self.voiceprint_button = QPushButton()
        self.voiceprint_button.setObjectName("speakerPillButton")
        self.voiceprint_button.setIcon(themed_icon("fa5s.fingerprint", "secondary"))
        bind_text(self.voiceprint_button, '声纹比对')
        bind_text(self.voiceprint_button, '比较多个独立语音样本，试听候选后再决定是否合并；字幕可撤销。', property='toolTip')
        self.voiceprint_button.clicked.connect(self._voiceprint_clicked)
        toolbar.addWidget(self.voiceprint_button)
        lcol.addLayout(toolbar)

        self.banner = QFrame()
        self.banner.setObjectName("speakerBanner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 6, 6, 6)
        banner_row.setSpacing(10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setTextFormat(Qt.TextFormat.PlainText)
        banner_row.addWidget(self.banner_text, 1)
        self.rebuild_button = self._button("从缓存重建轨道", "speakerPrimarySmall", self._apply_candidates)
        banner_row.addWidget(self.rebuild_button)
        self.banner_close = self._button("知道了", "speakerGhostButton", self._dismiss_banner)
        banner_row.addWidget(self.banner_close)
        lcol.addWidget(self.banner)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("speakerBoardScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.board = QWidget()
        self.board.setObjectName("speakerBoardHost")
        board = QVBoxLayout(self.board)
        board.setContentsMargins(0, 2, 8, 16)
        board.setSpacing(12)
        self.boxes = {kind: SpeakerBox(kind, self, self.board) for kind in ("main", "secondary", "game", "ignore")}
        board.addWidget(self.boxes["main"])
        board.addWidget(self.boxes["secondary"])
        pair = QHBoxLayout()
        pair.setSpacing(12)
        pair.addWidget(self.boxes["game"], 1)
        pair.addWidget(self.boxes["ignore"], 1)
        board.addLayout(pair)
        board.addStretch(1)
        self.scroll.setWidget(self.board)
        lcol.addWidget(self.scroll, 1)
        row.addWidget(left, 1)

        main_box, secondary_box = self.boxes["main"], self.boxes["secondary"]
        self.cap_button = QToolButton()
        self.cap_button.setObjectName("speakerGhostButton")
        self.cap_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.cap_menu = create_studio_menu(self.cap_button)
        self.cap_menu.aboutToShow.connect(self._fill_cap_menu)
        self.cap_button.setMenu(self.cap_menu)
        main_box.add_action(self.cap_button)
        self.organize_button = secondary_box.add_action(self._button(
            "按说话量整理", "speakerPillButton", lambda: self._organize(None),
            tip="字幕最多的几位各占一条轨，其余收进次要角色（可撤销）"))
        self.group_merge_button = secondary_box.add_action(self._button(
            "合并成一位", "speakerPrimarySmall", self._group_merge, icon="fa5s.compress-arrows-alt", role="on_accent",
            tip="选中这一组，在右侧确认后合成一位；原文和时间都保留"))
        self.group_game_button = secondary_box.add_action(self._button(
            "全部归入游戏声", "speakerPillButton", lambda: self._apply_move(self._box_keys("secondary"), "game"),
            icon="fa5s.gamepad"))
        self.group_select_button = secondary_box.add_action(self._button(
            "全选", "speakerGhostButton", lambda: self._select_box("secondary")))
        self.group_more_button = QToolButton()
        self.group_more_button.setObjectName("speakerGhostButton")
        self.group_more_button.setIcon(themed_icon("fa5s.ellipsis-h", "secondary"))
        self.group_more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.group_more_menu = create_studio_menu(self.group_more_button)
        self.group_more_menu.aboutToShow.connect(self._fill_group_menu)
        self.group_more_button.setMenu(self.group_more_menu)
        secondary_box.add_action(self.group_more_button)

        self.inspector_frame = QFrame()
        self.inspector_frame.setObjectName("speakerInspector")
        self.inspector_frame.setFixedWidth(318)
        icol = QVBoxLayout(self.inspector_frame)
        icol.setContentsMargins(0, 0, 0, 0)
        inspector_scroll = QScrollArea()
        inspector_scroll.setObjectName("speakerBoardScroll")
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector = QStackedWidget()
        self.inspector.setObjectName("speakerBoardHost")
        self.inspector.setContentsMargins(16, 4, 16, 12)
        inspector_scroll.setWidget(self.inspector)
        icol.addWidget(inspector_scroll)
        self.empty_page = QWidget()
        empty = QVBoxLayout(self.empty_page)
        empty.setContentsMargins(12, 0, 12, 0)
        empty.setSpacing(10)
        empty.addStretch(1)
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(themed_icon("fa5s.mouse-pointer", "muted").pixmap(34, 34))
        empty.addWidget(icon)
        empty_title = QLabel()
        empty_title.setObjectName("speakerEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bind_text(empty_title, "点一位看详情")
        empty.addWidget(empty_title)
        empty_text = QLabel()
        empty_text.setObjectName("speakerEmptyText")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text.setWordWrap(True)
        bind_text(empty_text, "拖到别的框换分组；拖到另一位身上，就把它并进去。按住 Ctrl 或 Shift 可多选，一起拖或合并。"
                              "次要角色的「合并成一位」会先选中整组，在这里确认。")
        empty.addWidget(empty_text)
        empty.addStretch(2)
        self.inspector.addWidget(self.empty_page)
        self.merge_panel = MergePanel(self)
        self.inspector.addWidget(self.merge_panel)
        self.selection_summary = self.merge_panel.summary
        self.batch_buttons: dict[str, QPushButton] = {}
        for key, text, slot in (
                ("background", "归入游戏声", lambda: self._apply_move(self._ordered_selection(), "game")),
                ("ignore", "忽略", lambda: self._apply_move(self._ordered_selection(), "ignore")),
                ("main", "移到主要角色", lambda: self._apply_move(self._ordered_selection(), "main")),
                ("secondary", "移到次要角色", lambda: self._apply_move(self._ordered_selection(), "secondary")),
                ("restore", "恢复原归属", lambda: self._batch("restore"))):
            self.batch_buttons[key] = self._button(text, "speakerPillButton", slot)
            self.merge_panel.add_batch_button(self.batch_buttons[key])
        self.delete_identity_button = self._button("删除身份，字幕移到统一轨", "speakerPillButton",
                                                   lambda: self._batch("identity_delete"))
        self.merge_panel.add_batch_button(self.delete_identity_button)
        self.delete_captions_button = self._button("删除所选人物及字幕", "speakerGhostButton", lambda: self._batch("delete"))
        self.merge_panel.add_batch_button(self.delete_captions_button)
        row.addWidget(self.inspector_frame)
        column.addWidget(body, 1)

        # -- rare tools: one popup under 「更多工具」 ------------------------------
        self.more_tools = QFrame(self, Qt.WindowType.Popup)
        self.more_tools.setObjectName("speakerMoreTools")
        self.more_tools.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tools = QVBoxLayout(self.more_tools)
        tools.setContentsMargins(14, 12, 14, 12)
        tools.setSpacing(8)
        self.load_cache_button = self._button("选择本素材 MOSS 缓存…", "speakerPillButton", self._choose_cache,
                                              icon="fa5s.folder-open")
        self.reanalyze_button = self._button("用当前方案重新识别…", "speakerPillButton", self._open_recognition,
                                             icon="fa5s.redo",
                                             tip="打开当前工程识别设置，选择当前识别方案。会重新生成字幕，不是只补标签；请先保存人工编辑的工程副本。")
        self.single_button = self._button("全部合并为单轨", "speakerPillButton",
                                          lambda: self._batch("single", all_rows=True), icon="fa5s.layer-group")
        self.single_identity_button = self._button(
            '确认全片只有一人', 'speakerPillButton', self._confirm_single_identity, icon="fa5s.user",
            tip='将当前标签统一到第一位说话人，保留每条字幕的文字、译文、时间和样式；可撤销。')
        self.cleanup_range_button = self._button('整理局部识别空人物（可撤销）', 'speakerPillButton', self._clean_range_speakers,
                                                 icon="fa5s.broom",
                                                 tip='只移除无有效字幕引用且未被手动配置的局部识别人物和自动空轨道')
        self.cleanup_range_button.setObjectName('cleanupRangeSpeakers')
        self.cleanup_range_button.setProperty("class", "speakerPillButton")
        for button in (self.load_cache_button, self.reanalyze_button, self.single_button, self.single_identity_button,
                       self.cleanup_range_button):
            tools.addWidget(button)
        policy = QHBoxLayout()
        policy.setSpacing(6)
        policy.addWidget(self._plain_label("原始发言超过"))
        self.utterance_threshold = QSpinBox()
        self.utterance_threshold.setRange(1, 1000)
        self.utterance_threshold.setProperty("fieldWidth", "speakerThreshold")
        self.utterance_threshold.setMinimumWidth(70)
        self.utterance_threshold.setValue(int(self.page.project.generation_metadata.get(
            "speaker_organization", {}).get("threshold", 10)))
        policy.addWidget(self.utterance_threshold)
        policy.addWidget(self._plain_label("句才算主要说话人，其余归入游戏背景声"))
        self.count_policy_button = self._button("按原始发言数整理", "speakerPillButton", self._apply_count_policy)
        policy.addWidget(self.count_policy_button)
        tools.addLayout(policy)
        self.candidate_note = QLabel()
        self.candidate_note.setObjectName("speakerMeta")
        self.candidate_note.setWordWrap(True)
        tools.addWidget(self.candidate_note)
        self.more_tools.hide()
        self.more_tools.installEventFilter(self)

        # -- footer: name display, status, undo, done --------------------------
        footer = QFrame()
        footer.setObjectName("speakerFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(20, 10, 16, 12)
        foot.setSpacing(12)
        self.show_names = QCheckBox(tr('字幕前显示名字'))
        self.show_names.setObjectName('speakerNameVisibility')
        self.show_names.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_names.setToolTip(tr('作用于目前工程的预览、字幕导出与压制成片；双语只在上面一行显示名称。'))
        self.show_names.toggled.connect(self._set_name_visibility)
        foot.addWidget(self.show_names)
        self.name_preview = QLabel()
        self.name_preview.setObjectName('speakerNamePreview')
        self.name_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.name_preview.setMaximumWidth(320)
        foot.addWidget(self.name_preview)
        self.status = QLabel()
        self.status.setObjectName("speakerFooterStatus")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        foot.addWidget(self.status, 1)
        self.undo_button = self._button("撤销", "speakerGhostButton", self.page.undo_stack.undo, icon="fa5s.undo")
        bind_text(self.undo_button, "撤销上一步（Ctrl+Z）", property="toolTip")
        foot.addWidget(self.undo_button)
        self.done_button = QPushButton()
        self.done_button.setObjectName("speakerDone")
        bind_text(self.done_button, "完成")
        self.done_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_button.clicked.connect(self.accept)
        foot.addWidget(self.done_button)
        column.addWidget(footer)

    @staticmethod
    def _plain_label(text: str) -> QLabel:
        label = QLabel()
        bind_text(label, text)
        return label

    def _toggle_more(self, shown: bool) -> None:
        if not shown:
            self.more_tools.hide()
            return
        self.more_tools.adjustSize()
        anchor = self.more_toggle.mapToGlobal(QPoint(self.more_toggle.width(), self.more_toggle.height() + 6))
        self.more_tools.move(anchor.x() - self.more_tools.width(), anchor.y())
        self.more_tools.show()

    def _dismiss_banner(self) -> None:
        self._banner_dismissed = True
        self.banner.hide()

    def _set_status(self, text: str) -> None:
        bind_text(self.status, text) if text else self.status.clear()

    # ---------------------------------------------------------------- snapshot
    def _load_snapshot(self, directory=None) -> None:
        from ..recognition.speaker_recovery import candidate_statistics, load_candidate_snapshot
        project = self.page.project
        self._snapshot_error = ""
        try:
            state = load_candidate_snapshot(project, directory)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._snapshot = None
            self._snapshot_in_project = False
            self._snapshot_error = str(exc)
            self._stats = {}
            return
        signature = (len(state["raw_segments"]), state.get("source_sha256", ""))
        if getattr(self, "_raw_signature", None) != signature:
            self._representatives = {}
            self._raw_signature = signature
        self._snapshot = state
        stored = project.generation_metadata.get("speaker_recovery")
        self._snapshot_in_project = bool(isinstance(stored, dict) and stored.get("raw_segments"))
        stats = sorted(candidate_statistics(state["raw_segments"]), key=lambda item: (item["first"], item["label"]))
        self._stats = {item["label"]: item for item in stats}
        if not self._snapshot_in_project:
            self._staged_roles = {label: state["roles"].get(label, "unconfirmed") for label in self._stats}

    def _roles(self) -> dict[str, str]:
        if self._snapshot is None:
            return {}
        if not self._snapshot_in_project:
            return dict(self._staged_roles)
        return {label: str(self._snapshot.get("roles", {}).get(label, "unconfirmed")) for label in self._stats}

    def _anonymous(self) -> bool:
        from ..recognition.speaker_recovery import anonymous_snapshot
        return bool(self._snapshot and anonymous_snapshot(self._snapshot))

    def _representative(self, label: str) -> tuple[int, int, str] | None:
        from ..recognition.speaker_recovery import representative_row
        if label not in self._representatives:
            try:
                row = representative_row(self._snapshot, label)
            except (ValueError, KeyError, TypeError):
                return None
            start = max(0, round(row["start"] * 1000) - 150)
            duration = min(4000, max(2000, round((row["end"] - row["start"]) * 1000) + 300))
            self._representatives[label] = (start, start + duration, str(row.get("text") or ""))
        return self._representatives[label]

    def _choose_cache(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("选择含 moss.json 的缓存目录"))
        if directory:
            self._load_snapshot(directory)
            if self._snapshot_error:
                self._set_status(self._snapshot_error)
            self._banner_dismissed = False
            self.refresh()

    def _open_recognition(self) -> None:
        self.close()
        QTimer.singleShot(0, self.page._open_recognition_sheet)

    def _set_name_visibility(self, shown):
        from .speaker_name_controls import SetSpeakerNamesCommand
        if self.page.project is not None:
            self.page.undo_stack.push(SetSpeakerNamesCommand(self.page.project, shown))
            self._sync_name_preview()

    def _sync_name_preview(self):
        from ..caption_style.speaker_names import enabled, prefix
        project = self.page.project
        shown = bool(project and enabled(project.studio_state))
        self.show_names.blockSignals(True)
        self.show_names.setChecked(shown)
        self.show_names.blockSignals(False)
        if not project:
            self.name_preview.clear()
            return
        speaker_id = getattr(self, '_name_preview_speaker', '')
        cue = next((c for c in project.cues if c.speaker_id == speaker_id), next(iter(project.cues), None))
        if cue is None:
            self.name_preview.setText(tr('效果预览：角色名称：好可怕，好可怕。'))
            return
        from ..caption_style.bilingual_layout import settings_from_state, translation_for_cue
        settings = settings_from_state(project.studio_state)
        translated = translation_for_cue(project.generation_metadata.get('translations', {}), cue.id)
        use_translation = bool(translated and (settings.mode == 'translation' or
            settings.mode == 'bilingual' and settings.order == 'translation_first'))
        body = translated if use_translation else cue.text
        from ..subtitle_rules.punctuation_style import (style_text, style_translation,
            project_mode, math_enabled, protected_terms_of)
        options = dict(math=math_enabled(project), protected_terms=protected_terms_of(project))
        from ..subtitle_rules.language_rules import project_language
        if use_translation:
            body = style_translation(body, project_mode(project), **options)
        else:
            body = style_text(body, project_mode(project), language=project_language(project) or "", **options).text
        self.name_preview.setText(tr('效果预览：') + (prefix(cue.speaker_id, project.speakers) if shown else '') + body)

    # ----------------------------------------------------------------- refresh
    def _undo_index_changed(self, *_args) -> None:
        if self.isVisible() and not self._applying:
            if self._snapshot_in_project:
                self._load_snapshot()
            self.refresh()

    def _card_keys(self) -> list[str]:
        project = self.page.project
        keys = list(self._stats)
        keys += [speaker.id for speaker in project.speakers if speaker.id not in self._stats]
        return keys

    def refresh(self, selected_id: str = "") -> None:
        if selected_id:
            self._name_preview_speaker = selected_id
        self._sync_name_preview()
        project = self.page.project
        if project is None or self._refreshing:
            return
        self._refreshing = True
        try:
            keys = self._card_keys()
            self._group = self._group_members()
            self._data = {key: self._card_data(key) for key in keys}
            self._box_index = {key: box for key in keys if (box := self._box_of(key))}
            self._sync_views(keys)
            self._layout_boxes()
            self._filter_rows(self.speaker_filter.text())
            self._refresh_banner()
            self._refresh_summary()
            self._refresh_box_actions()
            self.candidate_note.setText(self._snapshot_error)
            self.candidate_note.setVisible(bool(self._snapshot_error))
            self._selection &= set(keys)
            if self._focus not in self.cards:
                self._focus = ""
            for key, tile in self.tiles.items():
                tile.set_selected(key in self._selection)
            self._show_inspector()
            self.undo_button.setVisible(self.page.undo_stack.canUndo())
            if selected_id in self.tiles and not self.tiles[selected_id].isHidden():
                self.scroll.ensureWidgetVisible(self.tiles[selected_id], 20, 20)
        finally:
            self._refreshing = False

    # ------------------------------------------------------------- the board
    def _group_members(self) -> set[str]:
        """Speakers in the timeline's secondary group (role state, not identity)."""
        from ..recognition.speaker_roles import effective_roles, state_of
        project = self.page.project
        if not state_of(project).get("grouped"):
            return set()
        return {key for key, role in effective_roles(project).items() if role == "secondary"}

    def _box_of(self, key: str) -> str | None:
        """Which box shows ``key``; None for labels merged into someone else."""
        from ..recognition.speaker_recovery import candidate_destination
        data = self._data.get(key) or {}
        if key == BACKGROUND:
            return "game"
        if data.get("present"):
            return "secondary" if key in self._group and key != UNIFIED else "main"
        if key not in self._stats:
            return None
        destination = candidate_destination(self._roles(), key, self._anonymous())
        if destination is None:
            return "ignore"
        if destination == BACKGROUND:
            return "game"
        return "main" if destination == key else None

    def _make_card(self, key: str) -> SpeakerCard:
        card = SpeakerCard(key, self, self.inspector)
        self.cards.made[key] = card
        self.inspector.addWidget(card)
        card.update_data(self._data.get(key) or self._card_data(key))
        for button in card.findChildren(QPushButton):
            button.setAutoDefault(False)
        return card

    def _views(self, key: str) -> list:
        return [view for view in (self.tiles.get(key), self.cards.made.get(key)) if view is not None]

    def _sync_views(self, keys: list[str]) -> None:
        removed = [key for key in self.cards.order if key not in keys]
        self.cards.order = list(keys)
        for key in removed:
            card = self.cards.made.pop(key, None)
            if card is not None:
                if self._preview_card is card:
                    self._stop_preview()
                self.inspector.removeWidget(card)
                card.deleteLater()
        for card in self.cards.created():
            card.update_data(self._data[card.key])
        for key in list(self.tiles):
            box = self._box_index.get(key)
            tile = self.tiles[key]
            if key not in keys or box is None or tile.main != (box == "main"):
                if self._preview_card is tile:
                    self._stop_preview()
                self.tiles.pop(key)
                for owner in self.boxes.values():
                    if tile in owner.tiles:
                        owner.tiles.remove(tile)
                        owner.flow.removeWidget(tile)
                tile.hide()
                tile.deleteLater()
        for key in keys:
            box = self._box_index.get(key)
            if box is None:
                continue
            tile = self.tiles.get(key)
            if tile is None:
                tile = SpeakerTile(key, self, main=box == "main", parent=self.boxes[box].body)
                self.tiles[key] = tile
            tile.update_data(self._data[key])
            if self._preview_key == key and self._preview_timer.isActive():
                tile.set_playing(True)

    def _sort_key(self, key: str):
        data = self._data.get(key) or {}
        if self._sort == "time":
            first = min((start for start, _end in data.get("intervals") or ()), default=10 ** 12)
            return (first, key)
        if self._sort == "id":
            return (key,)
        return (-int(data.get("ms") or 0), -int(data.get("count") or 0), key)

    def _layout_boxes(self) -> None:
        order = {kind: [] for kind in self.boxes}
        for key in self.cards.order:
            box = self._box_index.get(key)
            if box:
                order[box].append(key)
        for kind, box in self.boxes.items():
            keys = sorted(order[kind], key=self._sort_key)
            if kind == "game" and BACKGROUND in keys:
                keys.remove(BACKGROUND)
                keys.insert(0, BACKGROUND)
            hint = _HINTS[kind]
            if kind == "secondary" and not self._grouped():
                hint = "还没分组：点「按说话量整理」，或把说话少的人拖到这里"
            if kind == "ignore" and not self._stats:
                hint = "只有识别出的说话人标签可以忽略"
            box.set_tiles([self.tiles[key] for key in keys], hint)
            cues = sum(int(self._data[key].get("count") or 0) for key in keys)
            desc = {"main": tr("{cues} 条字幕，各自一条字幕轨", cues=cues),
                    "secondary": tr("{cues} 条字幕，时间轴上合成一条轨", cues=cues),
                    "game": "", "ignore": ""}[kind]
            box.set_summary(len(keys), desc, [self._data[key].get("color") or "#888" for key in keys])

    def _grouped(self) -> bool:
        from ..recognition.speaker_roles import state_of
        return bool(state_of(self.page.project).get("grouped"))

    def _refresh_box_actions(self) -> None:
        from ..recognition.speaker_roles import MAIN_CAP, state_of
        state = state_of(self.page.project)
        bind_text(self.cap_button, "独立轨最多 {count} 条 ▾", count=int(state.get("cap") or MAIN_CAP))
        members = self._box_keys("secondary")
        grouped = self._grouped()
        self.organize_button.setVisible(not grouped)
        for button in (self.group_merge_button, self.group_game_button, self.group_select_button):
            button.setVisible(bool(members))
        self.group_merge_button.setEnabled(len(members) >= 2)
        self.group_more_button.setVisible(grouped)
        all_selected = bool(members) and all(key in self._selection for key in members)
        bind_text(self.group_select_button, "取消全选" if all_selected else "全选")
        pending = sum(bool(data.get("pending")) for data in self._data.values())
        bind_text(self.pending_button, "只看待确认 {count}", count=pending)
        self.pending_button.setVisible(bool(pending) or self.pending_button.isChecked())
        labels = {"size": "按说话量", "time": "按出现先后", "id": "按编号"}
        bind_text(self.sort_button, labels[self._sort])

    def _box_keys(self, kind: str) -> list[str]:
        return [tile.key for tile in self.boxes[kind].tiles if not tile.isHidden()]

    def _set_sort(self, value: str) -> None:
        self._sort = value
        self.refresh()

    def _fill_cap_menu(self) -> None:
        from ..recognition.speaker_roles import CAP_CHOICES, MAIN_CAP, state_of
        menu = self.cap_menu
        menu.clear()
        note = menu.addAction(tr("字幕最多的几位各占一条轨，其余收进次要角色"))
        note.setEnabled(False)
        current = int(state_of(self.page.project).get("cap") or MAIN_CAP)
        for value in CAP_CHOICES:
            action = menu.addAction(tr("最多 {count} 条（可撤销）", count=value))
            action.setCheckable(True)
            action.setChecked(value == current and self._grouped())
            action.triggered.connect(lambda _=False, cap=value: self._organize(cap))

    def _fill_group_menu(self) -> None:
        menu = self.group_more_menu
        menu.clear()
        menu.addAction(tr("全部忽略（可恢复）"), lambda: self._apply_move(self._box_keys("secondary"), "ignore"))
        menu.addAction(tr("全部移到主要角色"), lambda: self._apply_move(self._box_keys("secondary"), "main"))
        menu.addSeparator()
        menu.addAction(tr("重新判断主要和次要（可撤销）"), lambda: self._organize(None))
        menu.addAction(tr("取消分组，全部显示为独立轨（可撤销）"), self._ungroup)

    # -------------------------------------------------------------- selection
    def _visible_order(self) -> list[str]:
        return [key for kind in ("main", "secondary", "game", "ignore") for key in self._box_keys(kind)]

    def _ordered_selection(self) -> list[str]:
        order = self._visible_order()
        rank = {key: index for index, key in enumerate(order)}
        return sorted(self._selection, key=lambda key: (rank.get(key, len(order)), key))

    def _tile_clicked(self, key: str, modifiers) -> None:
        additive = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor:
            order = self._visible_order()
            if self._anchor in order and key in order:
                first, last = sorted((order.index(self._anchor), order.index(key)))
                self._selection |= set(order[first:last + 1])
        elif additive:
            self._selection ^= {key}
        else:
            self._selection = {key}
        self._anchor = key
        self._set_focus(key if key in self._selection else (next(iter(self._selection)) if len(self._selection) == 1 else ""))
        self._apply_selection()

    def _set_focus(self, key: str) -> None:
        previous = self.cards.made.get(self._focus)
        if previous is not None and key != self._focus and previous.name_edit.text() != previous.committed_name:
            self._finish_name_edit(previous)
        self._focus = key
        if key:
            self._name_preview_speaker = key
            self._sync_name_preview()

    def _apply_selection(self) -> None:
        for key, tile in self.tiles.items():
            tile.set_selected(key in self._selection)
        self._refresh_box_actions()
        self._show_inspector()

    def _clear_selection(self) -> None:
        self._selection = set()
        self._set_focus("")
        self._apply_selection()

    def _select_box(self, kind: str) -> None:
        keys = set(self._box_keys(kind))
        self._selection = set() if keys and keys <= self._selection else keys
        self._set_focus("")
        self._apply_selection()

    def _select_visible(self, mode: str) -> None:
        visible = set(self._visible_order())
        if mode == "all":
            self._selection = visible
        elif mode == "none":
            self._selection = set()
        else:
            self._selection = visible - self._selection
        self._apply_selection()

    def _selected_ids(self) -> set[str]:
        return {key for key in self._selection if self._data.get(key, {}).get("present")}

    def _show_inspector(self) -> None:
        if len(self._selection) >= 2:
            self._populate_merge_panel()
            self.inspector.setCurrentWidget(self.merge_panel)
        elif self._focus and self._focus in self.cards:
            self.inspector.setCurrentWidget(self.cards[self._focus])
        else:
            self.inspector.setCurrentWidget(self.empty_page)

    def _mergeable(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """(speakers that can be merged, targets every other one can merge into)."""
        mergeable = [key for key in keys if self._data.get(key, {}).get("present")]
        targets = [target for target in mergeable
                   if all(target in self._merge_targets(other) for other in mergeable if other != target)]
        targets.sort(key=lambda key: (-int(self._data[key].get("ms") or 0), -int(self._data[key].get("count") or 0)))
        return mergeable, targets

    def _populate_merge_panel(self) -> None:
        keys = self._ordered_selection()
        mergeable, targets = self._mergeable(keys)
        cues = sum(int(self._data[key].get("count") or 0) for key in keys)
        ms = sum(int(self._data[key].get("ms") or 0) for key in keys)
        self.merge_panel.populate(keys, data=self._data, targets=targets, cues=cues,
                                  seconds_text=_duration_text(ms), mergeable=mergeable)
        present = bool(self._selected_ids())
        for key in ("restore",):
            self.batch_buttons[key].setEnabled(present)
        self.delete_identity_button.setEnabled(present)
        self.delete_captions_button.setEnabled(present)
        for key, kind in (("background", "game"), ("ignore", "ignore"), ("main", "main"), ("secondary", "secondary")):
            self.batch_buttons[key].setEnabled(self._can_move(keys, kind))

    def _tile_rename(self, key: str) -> None:
        if not self._data.get(key, {}).get("present"):
            return
        self._selection = {key}
        self._set_focus(key)
        self._apply_selection()
        card = self.cards[key]
        card.name_edit.setFocus()
        card.name_edit.selectAll()

    def _tile_menu(self, tile, position) -> None:
        menu = create_studio_menu(self)
        if tile.data.get("present"):
            self._card_fill_more_menu(tile, menu)
            merge = menu.addMenu(tr("合并到"))
            self._card_fill_merge_menu(tile, merge)
        elif tile.key in self._stats:
            restore = 'unconfirmed' if self._anonymous() else 'main'
            menu.addAction(tr("恢复"), lambda: self._set_role(tile.key, restore))
        if not menu.isEmpty():
            menu.exec(position)

    def _card_fill_split_menu(self, card, menu) -> None:
        menu.clear()
        restore = 'unconfirmed' if self._anonymous() else 'main'
        for label, name in card.data.get("merged") or ():
            menu.addAction(tr("拆开 {name}", name=name), lambda value=label: self._set_role(value, restore))

    def _card_toggle_group(self, card) -> None:
        group = card.data.get("timeline_group")
        self._apply_move([card.key], "secondary" if group == "main" else "main")

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape and (self._selection or self._focus):
            self._clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ drag & drop
    def _start_drag(self, tile) -> None:
        from .studio_speaker_board import speaker_drag
        keys = self._ordered_selection() if tile.key in self._selection else [tile.key]
        label = tr("{count} 位一起", count=len(keys)) if len(keys) > 1 else str(tile.data.get("name") or tile.key)
        views = [self.tiles[key] for key in keys if key in self.tiles]
        for view in views:
            view.set_dragging(True)
        try:
            speaker_drag(tile, keys, label).exec(Qt.DropAction.MoveAction)
        finally:
            for view in views:
                try:
                    view.set_dragging(False)
                except RuntimeError:
                    pass

    def _autoscroll(self, global_pos) -> None:
        viewport = self.scroll.viewport()
        local = viewport.mapFromGlobal(global_pos)
        bar = self.scroll.verticalScrollBar()
        if local.y() < 36:
            bar.setValue(bar.value() - 16)
        elif local.y() > viewport.height() - 36:
            bar.setValue(bar.value() + 16)

    def _can_merge(self, keys: list[str], target: str) -> bool:
        sources = [key for key in keys if key != target]
        return bool(sources) and all(target in self._merge_targets(key) for key in sources)

    def _move_effect(self, key: str, kind: str):
        """What dropping ``key`` into box ``kind`` does, or None."""
        data = self._data.get(key)
        if not data or key in _GROUPS or self._box_index.get(key) == kind:
            return None
        candidate = key in self._stats and self._snapshot is not None
        present = bool(data.get("present"))
        if kind in {"main", "secondary"}:
            if present:
                return ("timeline", kind)
            return ("restore", kind) if candidate else None
        if kind == "game":
            if candidate:
                return ("role", "game")
            return ("background", None) if present else None
        if kind == "ignore" and candidate:
            return ("role", "ignore")
        return None

    def _can_move(self, keys, kind: str) -> bool:
        return any(self._move_effect(key, kind) for key in keys)

    def _drop(self, keys: list[str], kind: str, target: str = "") -> None:
        """Leave the drag's event loop first, then change the project (one undo)."""
        keys = [key for key in keys if key in self._data]
        if target:
            QTimer.singleShot(0, lambda: self._merge_many([key for key in keys if key != target], target))
        else:
            QTimer.singleShot(0, lambda: self._apply_move(keys, kind))

    def _apply_move(self, keys, kind: str) -> None:
        from .studio_speaker_board import BOX_TITLES
        roles, background, timeline = [], set(), {}
        restore = 'unconfirmed' if self._anonymous() else 'main'
        for key in keys:
            effect = self._move_effect(key, kind)
            if effect is None:
                continue
            action, value = effect
            if action == "role":
                roles.append((key, value))
            elif action == "background":
                background.add(key)
            elif action == "timeline":
                timeline[key] = value
            elif action == "restore":
                roles.append((key, restore))
                timeline[key] = value
        moved = len(roles) + len(background) + len([key for key in timeline if key not in dict(roles)])
        if not moved:
            return
        names = [self._display_name(key) for key in keys if self._move_effect(key, kind)]
        who = names[0] if len(names) == 1 else tr("{count} 位", count=len(names))
        label = tr("{who}移到「{box}」", who=who, box=tr(BOX_TITLES[kind]))
        self._execute(label, roles=roles, batch=("background", background, None) if background else None,
                      timeline=timeline)

    def _merge_many(self, keys: list[str], target: str, name: str = "") -> None:
        from ..recognition.speaker_recovery import candidate_destination
        if not keys or target not in self._data:
            return
        roles, batch = [], set()
        current = self._roles()
        for key in keys:
            if key == target or target not in self._merge_targets(key):
                continue
            if key in self._stats and self._snapshot is not None:
                if target in self._stats and (not self._snapshot_in_project
                                              or candidate_destination(current, target, self._anonymous()) == target):
                    roles.append((key, "merge:" + target))
                    continue
                if target == BACKGROUND:
                    roles.append((key, "game"))
                    continue
            if self._speaker(key) is not None:
                batch.add(key)
        count = len(roles) + len(batch)
        if not count:
            self._set_status(tr("这些说话人不能并入 {name}。", name=self._display_name(target)))
            return
        speaker = self._speaker(target)
        rename = name.strip() if speaker is not None and name.strip() and name.strip() != (speaker.name or speaker.id) else ""
        label = (tr("把 {name} 并入 {target}", name=self._display_name(keys[0]), target=rename or self._display_name(target))
                 if count == 1 else tr("把 {count} 位合成「{target}」", count=count + 1, target=rename or self._display_name(target)))
        self._selection = set()
        self._focus = target
        self._execute(label, roles=roles, batch=("merge", batch, target) if batch else None,
                      rename=(target, rename) if rename else None)

    def _merge_selection(self, target: str, name: str) -> None:
        mergeable, _targets = self._mergeable(self._ordered_selection())
        self._merge_many([key for key in mergeable if key != target], target, name)

    def _group_merge(self) -> None:
        self._selection = set(self._box_keys("secondary"))
        self._set_focus("")
        self._apply_selection()

    def _roles_state(self, changes: dict) -> dict:
        from ..projects.studio_project import speaker_track_preference
        from ..recognition.speaker_roles import decide, state_of
        project = self.page.project
        state = copy.deepcopy(state_of(project)) or decide(project, manual={}, default_cap=speaker_track_preference())
        manual = dict(state.get("manual") or {})
        manual.update(changes)
        state.update(manual=manual, grouped=True)
        return state

    def _push_roles(self, state, label: str) -> None:
        from .studio_speaker_roles import SetSpeakerRolesCommand
        self.page.undo_stack.push(SetSpeakerRolesCommand(self.page.project, state, label,
                                                         getattr(self.page, "_speaker_structure_changed", None)))
        timeline = getattr(self.page, "timeline", None)
        if timeline is not None and hasattr(timeline, "reindex_project"):
            timeline.reindex_project()

    def _organize(self, cap) -> None:
        from ..projects.studio_project import speaker_track_preference
        from ..recognition.speaker_roles import decide, group_members
        project = self.page.project
        state = decide(project, expanded=False, cap=cap, default_cap=speaker_track_preference())
        self._applying = True
        try:
            self._push_roles(state, tr("按主要/次要角色整理轨道") if cap is None else tr("调整主要角色上限"))
        finally:
            self._applying = False
        self.refresh()
        self._set_status(tr("已整理：{main} 条独立轨，{secondary} 位次要角色收进一条轨道（可撤销）",
                            main=len(self._box_keys("main")), secondary=len(group_members(project))))

    def _ungroup(self) -> None:
        from ..recognition.speaker_roles import state_of
        state = copy.deepcopy(state_of(self.page.project))
        if not state.get("grouped"):
            return
        state["grouped"] = False
        self._applying = True
        try:
            self._push_roles(state, tr("取消次要角色分组"))
        finally:
            self._applying = False
        self.refresh()

    def _execute(self, label: str, *, roles=(), batch=None, timeline=None, rename=None) -> None:
        """One user action as one undo step: label roles, then batch organisation,
        then timeline grouping, then the new name."""
        from ..projects.speaker_organization import organization_command
        from ..recognition.speaker_recovery import apply_candidate_roles
        from ..timeline.studio_commands import SetCandidateRoleCommand
        project, stack = self.page.project, self.page.undo_stack
        roles = list(roles)
        self._stop_preview()
        if roles and not self._snapshot_in_project:
            for key, role in roles:
                self._staged_roles[key] = role
            self.page._speaker_roles_pending = self._staged_roles != {
                key: self._snapshot["roles"].get(key, "unconfirmed") for key in self._stats}
            self.page._populate_speakers()
            roles = []
            timeline = {key: value for key, value in (timeline or {}).items() if self._speaker(key) is not None}
        steps = []
        if roles:
            def apply_roles():
                result = apply_candidate_roles(project, self._snapshot, roles)
                if result is not None:
                    command = SetCandidateRoleCommand(project, result, self.page._speaker_structure_changed)
                    command.setText(label)
                    self._push(command)
                    if command.error:
                        raise RuntimeError(command.error)
                    self._load_snapshot()
            steps.append(apply_roles)
        if batch and batch[1]:
            action, ids, target = batch
            steps.append(lambda: self._push(organization_command(project, set(ids), action, target,
                                                                 self.page._speaker_structure_changed)))
        if timeline:
            steps.append(lambda: self._push_roles(self._roles_state(
                {key: value for key, value in timeline.items() if self._speaker(key) is not None}), label))
        if rename:
            target, name = rename
            steps.append(lambda: self._push(SetSpeakerCommand(project, target, {"name": name}, text=tr("修改说话人名称"),
                                                              changed=self.page._speaker_structure_changed)))
        macro = len(steps) > 1
        self._applying = True
        try:
            if macro:
                stack.beginMacro(label)
            for step in steps:
                step()
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            self._set_status(tr("操作失败，当前工程已保留原状态：{error}", error=str(exc)))
        else:
            if steps or not self._snapshot_in_project:
                self._set_status(tr("{label}。可按 Ctrl+Z 撤销。", label=label))
        finally:
            if macro:
                stack.endMacro()
            self._applying = False
        if self._snapshot_in_project:
            self._load_snapshot()
        self.refresh()

    def _speaker(self, key: str) -> StudioSpeaker | None:
        return next((item for item in self.page.project.speakers if item.id == key), None)

    def _display_name(self, key: str) -> str:
        project = self.page.project
        speaker = self._speaker(key)
        if speaker is not None:
            return display_speaker_name(project, speaker)
        entries = project.generation_metadata.get("speaker_names", {}).get("entries", {})
        identity = project.generation_metadata.get("speaker_organization", {}).get("original_speakers", {}).get(key, {})
        name = (entries.get(key, {}).get("name") if isinstance(entries.get(key), dict) else "") or (
            identity.get("name") if isinstance(identity, dict) else "") or (
            (self._snapshot or {}).get("display_labels", {}).get(key)) or key
        return display_speaker_name(project, StudioSpeaker(key, name=name))

    def _card_data(self, key: str) -> dict:
        from ..recognition.speaker_recovery import candidate_destination
        project = self.page.project
        speaker = self._speaker(key)
        stats = self._stats.get(key)
        roles = self._roles()
        role = roles.get(key) if stats is not None else None
        anonymous = self._anonymous()
        present = speaker is not None
        duration = int(project.media.duration_ms or 0)
        data: dict = {"present": present, "group": key in _GROUPS, "name": self._display_name(key),
                      "color": _speaker_color(project, key).name(), "duration_ms": duration}
        if present:
            cues = [cue for cue in project.cues if cue.speaker_id == key]
            total = sum(max(0, cue.end_ms - cue.start_ms) for cue in cues)
            data["meta"] = tr("{count} 条字幕 · {duration}", count=len(cues), duration=_duration_text(total))
            data["intervals"] = [(cue.start_ms, cue.end_ms) for cue in cues]
            data.update(host=speaker.is_host, hidden=speaker.hidden)
        else:
            cues = []
            data["meta"] = tr("{count} 段 · {duration}", count=stats["segments"], duration=_duration_text(stats["seconds"] * 1000))
            data["intervals"] = [(round(start * 1000), round(end * 1000)) for start, end in stats["intervals"]]
        times = [_clock(start) for start, _end in data["intervals"][:24]]
        if times:
            more = "…" if len(data["intervals"]) > 24 else ""
            data["strip_tip"] = tr("出现在：{times}", times="、".join(times) + more) + "\n" + tr("点一段就从那里试听")
        excerpt = self._representative(key) if stats is not None else None
        # A voiceprint candidate's preview plays the same excerpt used by the
        # comparison, rather than an arbitrary start of a long request chunk.
        voice = next((item for item in (self._voiceprint_report or {}).get('sample_intervals', [])
                      if isinstance(item, dict) and item.get('label') == key), None)
        if voice is not None:
            try:
                begin,end = round(float(voice['start'])*1000),round(float(voice['end'])*1000)
                source = next((cue for cue in cues if cue.start_ms <= begin and cue.end_ms >= end), None)
                if source is not None and begin < end:
                    excerpt = (begin,end,source.text)
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        if excerpt is None and cues:
            longest = max(cues, key=lambda cue: cue.end_ms - cue.start_ms)
            length = min(4000, max(2000, longest.end_ms - longest.start_ms))
            excerpt = (longest.start_ms, longest.start_ms + length, longest.text)
        if excerpt is not None:
            from ..subtitle_rules.punctuation_style import style_text, project_mode, math_enabled, protected_terms_of
            from ..subtitle_rules.language_rules import project_language
            excerpt_text = style_text(str(excerpt[2]), project_mode(project), language=project_language(project) or "", math=math_enabled(project),
                                      protected_terms=protected_terms_of(project)).text
            data.update(excerpt_range=(excerpt[0], excerpt[1]), excerpt_time=_clock(excerpt[0] + 150 if stats else excerpt[0]),
                        excerpt=" ".join(excerpt_text.split()))
        if stats is not None:
            data["role"] = role if role in {"main", "game", "ignore"} else ""
            reason = tr((self._snapshot or {}).get("reasons", {}).get(key, ""))
            if present and role == "unconfirmed" and anonymous:
                data.update(pending=True, pill=tr("待确认"),
                            pill_tip=join_text([tr("标签不等于真人身份，请按原音确认归属。"), reason], "\n"))
            if not present:
                if role == "ignore":
                    cached = len((self._snapshot or {}).get("cue_cache", {}).get(key, []))
                    reason = (self._snapshot or {}).get('reasons', {}).get(key) or tr('用户手动忽略')
                    data["status"] = tr("{reason} {count} 条字幕保留；不参与预览和输出，点「恢复」重新启用。", reason=reason, count=cached)
                elif role == "game":
                    data["status"] = tr("已归入游戏背景声。")
                elif str(role).startswith("merge:"):
                    data["status"] = tr("已并入 {name}。", name=self._display_name(str(role)[6:]))
                else:
                    data["status"] = tr("字幕已整理到其他轨道。")
            if not self._snapshot_in_project:
                destination = candidate_destination(roles, key, anonymous)
                data["status"] = join_text([data.get("status", ""), tr("待应用：{target}", target=(
                    tr("忽略") if destination is None else self._display_name(destination)))], " ")
        if present and speaker.hidden:
            data.setdefault("pill", tr("已隐藏"))
            data.setdefault("pill_tone", "quiet")
        if key == BACKGROUND and present:
            data["status"] = tr("标成「游戏声」的人都并在这里，可以整组隐藏不输出。")
        data["can_merge"] = bool(self._merge_targets(key))
        data["count"] = len(cues) if present else int((stats or {}).get("segments") or 0)
        data["ms"] = (sum(max(0, cue.end_ms - cue.start_ms) for cue in cues) if present
                      else int(float((stats or {}).get("seconds") or 0) * 1000))
        data["merged"] = [(label, self._display_name(label)) for label, value in roles.items()
                          if value == "merge:" + key and label != key]
        group = getattr(self, "_group", set())
        data["timeline_group"] = ("secondary" if key in group else "main") if present and key not in _GROUPS else None
        return data

    def _refresh_banner(self) -> None:
        from ..recognition.speaker_recovery import recovery_preview
        snapshot = self._snapshot
        text, tip, rebuild = "", "", False
        if snapshot is not None and not self._snapshot_in_project:
            counts = recovery_preview(self.page.project, snapshot, self._staged_roles)
            text = tr("已读取缓存里的 {count} 个标签。选好每位的用途后点「从缓存重建轨道」：预计 {tracks} 条字幕轨 / {cues} 条字幕。",
                      count=len(self._stats), tracks=len(counts), cues=sum(counts.values()))
            rebuild = bool(counts) and not self._applying
        elif snapshot is not None:
            processing = snapshot.get("processing", {})
            pending = [key for key, role in self._roles().items() if role == "unconfirmed" and self._speaker(key)]
            if processing.get("status") == "failed":
                text = tr("说话人分析失败，已保留字幕文字。{error} 可在「更多工具」里重新识别。",
                          error=str(processing.get("error") or ""))
            elif pending and self._anonymous():
                text = tr("{origin} 找到 {count} 个说话人标签，{pending} 个待确认。按 ▶ 试听，再在卡片上选「主要 / 游戏声 / 忽略」；每次选择立即生效，可按 Ctrl+Z 撤销。",
                          origin=_source_name(processing), count=len(self._stats), pending=len(pending))
                tip = tr("标签不等于真人身份，请按原音确认归属。预计说话人数：{expected}。匿名标签均待确认，不按编号或发言量认定主播。",
                         expected=snapshot.get("expected_speakers") or tr("自动"))
            # Say so when recognition already merged labels by voiceprint.
            roles = self._roles()
            merged = [label for group in (snapshot.get("voiceprint_automatic") or {}).get("groups", [])
                      for label in group[1:] if str(roles.get(label, "")).startswith("merge:")]
            if merged:
                text = join_text([text, tr("其中 {count} 个标签与另一位声纹一致，识别时已自动并入；在它的卡片上点「主要」即可拆开。",
                                           count=len(merged))], " ")
        self.banner_text.setText(text)
        self.banner_text.setToolTip(tip)
        self.rebuild_button.setVisible(snapshot is not None and not self._snapshot_in_project)
        self.rebuild_button.setEnabled(rebuild)
        self.banner_close.setVisible(not self.rebuild_button.isVisible())
        self.banner.setVisible(bool(text) and not (self._banner_dismissed and not self.rebuild_button.isVisible()))

    def _refresh_summary(self) -> None:
        project = self.page.project
        pending = self._anonymous() and any(role == 'unconfirmed' for role in self._roles().values())
        text = "{speakers} 个说话人标签 · {cues} 条字幕" if pending else "{speakers} 位说话人 · {cues} 条字幕"
        bind_text(self.summary_label, text, speakers=len(project.speakers), cues=len(project.cues))

    # --------------------------------------------------------------- names
    def eventFilter(self, watched, event):
        if watched is getattr(self, "more_tools", None) and event.type() == QEvent.Type.Hide:
            self.more_toggle.blockSignals(True)
            self.more_toggle.setChecked(False)
            self.more_toggle.blockSignals(False)
        if isinstance(watched, QLineEdit) and watched.objectName() == "speakerName":
            card = watched.parent()
            if isinstance(card, SpeakerCard):
                if event.type() == QEvent.Type.InputMethod:
                    # QLineEdit.text() excludes preedit. Never commit its earlier
                    # prefix while the IME is still composing the new name.
                    card.preedit = bool(event.preeditString())
                elif event.type() == QEvent.Type.FocusOut:
                    self._finish_name_edit(card)
        return super().eventFilter(watched, event)

    def _finish_name_edit(self, card: SpeakerCard) -> bool:
        if card.preedit:
            QApplication.inputMethod().commit()
        return self._card_commit_name(card)

    def _card_commit_name(self, card: SpeakerCard) -> bool:
        if self._committing_name or not card.name_edit.isEnabled():
            return True
        if card.preedit:
            bind_text(card.name_error, "请先确认输入法中的姓名。")
            card.name_error.show()
            return False
        project = self.page.project
        speaker = self._speaker(card.key)
        if speaker is None:
            return True
        name = card.name_edit.text().strip()
        if not name:
            bind_text(card.name_error, "名称不能为空，原名称已保留。")
            card.name_error.show()
            return False
        card.name_error.hide()
        if name in {card.committed_name, speaker.name or speaker.id}:
            return True
        self._committing_name = True
        try:
            # One edit session commits once at an explicit boundary; keystrokes
            # never rebuild the cards or add undo entries.
            card.committed_name = name
            self.page.undo_stack.push(SetSpeakerCommand(project, speaker.id, {"name": name},
                                                        text=tr("修改说话人名称"),
                                                        changed=self.page._speaker_structure_changed))
        finally:
            self._committing_name = False
        self._set_status("")
        if self.isVisible():
            self.refresh(card.key)
        return True

    def done(self, result):
        self._role_timer.stop()
        self._drain_roles()
        self._stop_preview()
        for card in self.cards.created():
            if card.name_edit.isEnabled() and not self._finish_name_edit(card):
                self._selection = {card.key}
                self._set_focus(card.key)
                self._apply_selection()
                card.name_edit.setFocus()
                return
        try:
            self.page.undo_stack.indexChanged.disconnect(self._undo_index_changed)
        except (RuntimeError, TypeError):
            pass
        self._voiceprint_cancel.set()
        self._voiceprint_timer.stop()
        self.page._speaker_roles_pending = False
        self.page._populate_speakers()
        super().done(result)

    def _voiceprint_clicked(self):
        from ..recognition.scoped_voiceprint import cue_signature, sample_windows
        project = self.page.project
        if self._voiceprint_report:
            if self._voiceprint_report.get('cue_signature') != cue_signature(project.cues):
                self._voiceprint_report = None
                bind_text(self.voiceprint_button, '声纹比对')
                self._set_status(tr('字幕或说话人已变化，请重新比对。'))
                return
            self._voiceprint_apply()
            return
        # Labels a person has decided are refused per label when applying, so
        # one confirmed speaker does not block comparing the undecided ones.
        if not self._snapshot_in_project:
            self._set_status(tr('当前工程没有可安全比对的未确认分片标签；已有人工确认的身份不会被覆盖。'))
            return
        from ..timeline.studio_edit_sequence import sequence_of
        sequence = sequence_of(project)
        if (not sequence.is_identity() or len([track for track in project.video_tracks if track.clips]) != 1
                or os.path.normcase(os.path.abspath(str(sequence.source_path))) !=
                   os.path.normcase(os.path.abspath(str(project.media.path)))):
            self._set_status(tr('当前时间线已剪辑或有多个视频轨，无法安全对应原始语音；请先试听并手动合并。'))
            return
        identity = copy.deepcopy(project.generation_metadata.get('media_identity') or {})
        if identity.get('selection'):
            self._set_status(tr('此工程选择过独立音轨；自动声纹取样暂不支持该轨道，请试听后手动合并。'))
            return
        media = Path(project.media.path)
        try:
            stat = media.stat()
            if ((identity.get('size') is not None and int(identity['size']) != stat.st_size)
                    or (identity.get('mtime_ns') is not None and int(identity['mtime_ns']) != stat.st_mtime_ns)):
                raise ValueError('素材已变化')
        except (OSError, ValueError):
            self._set_status(tr('素材缺失或已变化，未执行声纹比对。'))
            return
        rows = [{'id':c.id,'speaker':c.speaker_id,'start':c.start_ms/1000,
                 'end':c.end_ms/1000,'text':c.text} for c in project.cues]
        samples = sample_windows(rows)
        if len({item['label'] for item in samples}) < 2:
            self._set_status(tr('分片中可用的独立语音样本不足，请试听后手动处理。'))
            return
        signature = cue_signature(rows)
        from ..runtime_paths import get_runtime_paths
        from ..system.runtime_registry import resolve_runtime_python
        from ..system.processes import main_python_executable
        from ..system.platform_media import ffmpeg_tool
        paths = get_runtime_paths()
        runtime = resolve_runtime_python('main') or main_python_executable()
        worker = paths.install_root/'workers'/'speaker_embed_worker.py'
        if not worker.is_file():
            worker = paths.install_root/'speaker_embed_worker.py'
        model = paths.model_root/'spkrec-ecapa-voxceleb'
        ffmpeg = ffmpeg_tool(root=paths.install_root)
        if not runtime or not Path(runtime).is_file() or not worker.is_file() or not ffmpeg.is_file():
            self._set_status(tr('本地声纹运行环境或音频工具不可用，原有说话人保持不变。'))
            return
        mailbox, cancel = self._voiceprint_mailbox, self._voiceprint_cancel
        cancel.clear()
        self.voiceprint_button.setEnabled(False)
        self._set_status(tr('正在本机比较独立语音样本，完成后可试听并确认候选。'))
        self._voiceprint_timer.start()

        def work():
            try:
                if identity.get('sha256'):
                    digest = hashlib.sha256()
                    with media.open('rb') as stream:
                        for block in iter(lambda:stream.read(2*1024*1024), b''):
                            if cancel.is_set():
                                return
                            digest.update(block)
                    if digest.hexdigest().lower() != str(identity['sha256']).lower():
                        raise ValueError('素材内容与识别时不一致')
                from ..recognition.scoped_voiceprint import analyze_samples, decode_sample_windows
                parts = decode_sample_windows(media,samples,ffmpeg=ffmpeg,cancel_check=cancel.is_set)
                report = analyze_samples(rows,samples,parts,model_dir=model,main_python=runtime,
                                         worker_path=worker,cancel_check=cancel.is_set)
                current = media.stat()
                if current.st_size != stat.st_size or current.st_mtime_ns != stat.st_mtime_ns:
                    raise ValueError('分析期间素材已变化')
                if not cancel.is_set():
                    mailbox.put((signature,report,''))
            except Exception as exc:
                if not cancel.is_set():
                    mailbox.put((signature,None,str(exc)))
        threading.Thread(target=work,name='speaker-voiceprint-review',daemon=True).start()

    def _voiceprint_poll(self):
        if not self.isVisible() or self.page.project is not self._role_project:
            self._voiceprint_timer.stop()
            return
        try:
            signature, report, error = self._voiceprint_mailbox.get_nowait()
        except queue.Empty:
            return
        self._voiceprint_timer.stop()
        self.voiceprint_button.setEnabled(True)
        from ..recognition.scoped_voiceprint import cue_signature
        if error:
            self._set_status(tr('声纹比对未完成：{error}。原有说话人保持不变。', error=error))
        elif self.page.project is None or signature != cue_signature(self.page.project.cues):
            self._set_status(tr('分析期间字幕已变化，已丢弃旧结果；请重新比对。'))
        elif report and self._undecided_groups(report)['groups']:
            self._voiceprint_report = report = self._undecided_groups(report)
            bind_text(self.voiceprint_button, '查看声纹候选')
            self.refresh()
            self._set_status(tr('发现 {count} 组相似声纹候选；卡片的 ▶ 可试听比对样本，尚未修改工程。', count=len(report['groups'])))
        else:
            self._set_status(tr('没有足够一致的候选；原有说话人保持不变。'))

    def _undecided_groups(self, report):
        """Candidate groups without speakers a person already set up; a chosen
        主要 speaker stays as the group's target."""
        from ..recognition.scoped_voiceprint import reviewable_groups
        return dict(report, groups=reviewable_groups(self.page.project, report.get('groups')))

    def _voiceprint_apply(self):
        from ..recognition.scoped_voiceprint import apply_reviewed
        report = self._voiceprint_report or {}
        groups = report.get('groups') or []
        lines = ['、'.join(self._display_name(label) for label in group) for group in groups]
        message = tr('以下标签的多段语音较相似。请先试听；确认后会按组并入第一位，保留原文和时间，可一次撤销。')
        message += '\n\n' + '\n'.join(lines)
        box = QMessageBox(QMessageBox.Icon.Question, tr('确认声纹候选'), message,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        apply_secondary_surface_theme(box)
        box.button(QMessageBox.StandardButton.Yes).setText(tr('合并这些候选'))
        box.button(QMessageBox.StandardButton.No).setText(tr('暂不合并'))
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_reviewed(self.page.project,report)
            command = RecoverSpeakersCommand(self.page.project,result,self.page._speaker_structure_changed)
            command.setText(tr('校正说话人声纹'))
            self._applying = True
            try:
                self._push(command)
                if command.error:
                    raise RuntimeError(command.error)
            finally:
                self._applying = False
            self._load_snapshot()
            self._voiceprint_report = None
            bind_text(self.voiceprint_button, '声纹比对')
            self.refresh()
            self._set_status(tr('已按确认结果合并；可按 Ctrl+Z 一次撤销。'))
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            self._set_status(tr('未应用声纹候选：{error}', error=str(exc)))

    # ------------------------------------------------------- card actions
    def _clean_range_speakers(self):
        from ..projects.range_speakers import orphan_range_speakers
        from ..timeline.speaker_cleanup import CleanRangeSpeakersCommand
        count = len(orphan_range_speakers(self.page.project))
        if not count:
            self._set_status('没有可整理的局部识别空人物')
            return
        command = CleanRangeSpeakersCommand(self.page.project, self.page._speaker_structure_changed)
        outcome = command.outcome
        self._push(command)
        if not outcome['applied']:
            self._set_status('整理失败，已保留当前工程：' + outcome['error'])
            return
        self.refresh()
        self._set_status(f'已整理 {count} 位局部识别空人物，可撤销恢复')

    def _push(self, command) -> None:
        self.page.undo_stack.push(command)
        error = getattr(command, "error", "")
        if error:
            self._set_status(tr("操作失败，当前工程已保留原状态：{error}", error=error))

    def _card_choose_color(self, card: SpeakerCard) -> None:
        speaker = self._speaker(card.key)
        if speaker is None:
            return
        current = speaker.color or _speaker_color(self.page.project, speaker.id).name()

        def pick(color: str) -> None:
            if color != current:
                self._push(SetSpeakerCommand(self.page.project, speaker.id, {"color": color},
                                             text=tr("修改说话人颜色"), changed=self.page._speaker_structure_changed))

        def more() -> None:
            from ..design.color_picker import SimpleColorDialog
            from PySide6.QtGui import QColor
            dialog = SimpleColorDialog(QColor(current), self, title=tr("选择说话人颜色"), common_colors=_SWATCHES)
            apply_secondary_surface_theme(dialog)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                chosen = dialog.selected_color()
                if chosen.isValid():
                    pick(chosen.name())

        menu = swatch_menu(card.swatch, _SWATCHES, current, pick, more)
        menu.exec(card.swatch.mapToGlobal(card.swatch.rect().bottomLeft()))

    def _card_set_host(self, card: SpeakerCard, checked: bool) -> None:
        project = self.page.project
        if self._speaker(card.key) is None:
            return
        if checked:
            self._push(SetHostSpeakerCommand(project, card.key, self.page._speaker_structure_changed))
            return
        import copy
        speakers = copy.deepcopy(project.speakers)
        for speaker in speakers:
            if speaker.id == card.key:
                speaker.is_host = False
        self._push(SpeakerStateCommand(project, speakers, project.cues, tr("取消主播"),
                                       self.page._speaker_structure_changed))

    def _card_set_visible(self, card: SpeakerCard, visible: bool) -> None:
        if self._speaker(card.key) is None:
            return
        self._push(SetSpeakerCommand(self.page.project, card.key, {"hidden": not visible},
                                     text=tr("显示说话人") if visible else tr("隐藏说话人"),
                                     changed=self.page._speaker_structure_changed))

    def _card_fill_more_menu(self, card: SpeakerCard, menu) -> None:
        menu.clear()
        project = self.page.project
        speaker = self._speaker(card.key)
        if speaker is None:
            return
        from ..caption_style.speaker_labels import SetSpeakerLabelCommand
        label = menu.addAction(tr('在模板中显示姓名'))
        label.setCheckable(True)
        label.setChecked(project.studio_state.get('speaker_labels', {}).get(card.key, True))
        label.toggled.connect(lambda visible: self.page.undo_stack.push(
            SetSpeakerLabelCommand(project, card.key, visible, self.page._changed)))
        styles = menu.addMenu(tr("默认样式"))
        for style in project.styles:
            action = styles.addAction(style.name or style.id)
            action.setCheckable(True)
            action.setChecked(style.id == speaker.style_id)
            action.triggered.connect(lambda _=False, style_id=style.id: self._set_style(card.key, style_id))
        cue_ids = self.page.selected_cue_ids() if hasattr(self.page, "selected_cue_ids") else []
        assign = menu.addAction(tr("把选中的 {count} 条字幕归给这位", count=len(cue_ids)))
        assign.setEnabled(bool(cue_ids))
        assign.triggered.connect(lambda: self._assign_selected_cues(card.key))
        keep = menu.addAction(tr("只保留这位的字幕"))
        bind_text(keep, "隐藏其他全部说话人（成片与导出不再包含；可撤销）", property="toolTip")
        keep.triggered.connect(lambda: self._keep_only(card.key))
        origins = project.generation_metadata.get("speaker_organization", {}).get("cue_origins", {})
        restore = menu.addAction(tr("恢复原归属"))
        restore.setEnabled(any(cue.speaker_id == card.key and origins.get(cue.id, card.key) != card.key
                               for cue in project.cues))
        restore.triggered.connect(lambda: self._batch("restore", ids={card.key}))
        menu.addSeparator()
        identity = menu.addAction(tr("删除身份，字幕移到统一轨"))
        identity.triggered.connect(lambda: self._batch("identity_delete", ids={card.key}))
        delete = menu.addAction(tr("删除这位及其字幕…"))
        delete.triggered.connect(lambda: self._batch("delete", ids={card.key}))

    def _set_style(self, key: str, style_id: str) -> None:
        speaker = self._speaker(key)
        if speaker is not None and speaker.style_id != style_id:
            self._push(SetSpeakerCommand(self.page.project, key, {"style_id": style_id},
                                         text=tr("修改说话人默认样式"), changed=self.page._speaker_structure_changed))

    def _merge_targets(self, key: str) -> list[str]:
        """Speakers this card can merge into, in track order."""
        from ..recognition.speaker_recovery import candidate_destination
        present = self._speaker(key) is not None
        candidate = key in self._stats and self._snapshot is not None
        roles, anonymous = self._roles(), self._anonymous()
        targets = []
        for target in (speaker.id for speaker in self.page.project.speakers if speaker.id != key):
            if candidate and not self._snapshot_in_project:
                # A cache rebuild can only merge into a label kept as 主要.
                if roles.get(target) == "main":
                    targets.append(target)
            elif candidate and target in self._stats:
                if present or candidate_destination(roles, target, anonymous) == target:
                    targets.append(target)
            elif present or (candidate and target == BACKGROUND):
                targets.append(target)
        return targets

    def _card_fill_merge_menu(self, card: SpeakerCard, menu) -> None:
        menu.clear()
        for target in self._merge_targets(card.key):
            action = menu.addAction(tr("并入 {name}", name=self._display_name(target)))
            action.triggered.connect(lambda _=False, value=target: self._merge(card.key, value))
        if menu.isEmpty():
            menu.addAction(tr("没有可并入的说话人")).setEnabled(False)

    def _merge(self, key: str, target: str) -> None:
        from ..recognition.speaker_recovery import candidate_destination
        if key in self._stats and self._snapshot is not None:
            roles = self._roles()
            if target in self._stats and (not self._snapshot_in_project
                                          or candidate_destination(roles, target, self._anonymous()) == target):
                self._set_role(key, "merge:" + target)
                return
            if target == BACKGROUND:
                self._set_role(key, "game")
                return
        if self._speaker(key) is not None:
            self._batch("merge", target=target, ids={key})

    def _card_role_clicked(self, card: SpeakerCard, role: str) -> None:
        current = self._pending_roles.get(card.key, self._roles().get(card.key, "unconfirmed"))
        if role == current:
            card.roles.set_role(current)
            return
        # Leave the native button's input dispatch before changing its model
        # and the selection/track widgets. Keep stable IDs, never card wrappers.
        self._pending_roles[card.key] = role
        self._set_status(tr("正在更新说话人用途…"))
        self._role_timer.start(0)

    def _drain_roles(self):
        pending, self._pending_roles = self._pending_roles, {}
        if self.page.project is not self._role_project:
            return
        for label, role in pending.items():
            self._set_role(label, role)

    def _set_role(self, label: str, role: str) -> None:
        from ..recognition.speaker_recovery import apply_candidate_role
        if self._snapshot is None or label not in self._stats:
            return
        self._set_status("")
        if not self._snapshot_in_project:
            self._staged_roles[label] = role
            self.page._speaker_roles_pending = self._staged_roles != {
                key: self._snapshot["roles"].get(key, "unconfirmed") for key in self._stats}
            self.page._populate_speakers()
            self.refresh(label)
            return
        project = self.page.project
        self._stop_preview()
        try:
            result = apply_candidate_role(project, self._snapshot, label, role)
        except (ValueError, KeyError, TypeError) as exc:
            self._set_status(str(exc))
            self.refresh(label)
            return
        if result is None:
            self.refresh(label)
            return
        from ..timeline.studio_commands import SetCandidateRoleCommand
        command = SetCandidateRoleCommand(project, result, self.page._speaker_structure_changed)
        command.setText(tr("设置说话人用途"))
        self._applying = True
        try:
            self._push(command)
        finally:
            self._applying = False
        self._load_snapshot()
        self.refresh(label)
        if not command.error:
            names = {"main": "主要", "game": "游戏声", "ignore": "忽略", "unconfirmed": "待确认"}
            shown = tr(names[role]) if role in names else tr("并入 {name}", name=self._display_name(role[6:]))
            self._set_status(tr("{name}：{role}。可按 Ctrl+Z 撤销。", name=self._display_name(label), role=shown))

    def _apply_candidates(self) -> None:
        """Legacy projects: rebuild every track from a chosen MOSS cache folder."""
        from ..recognition.speaker_recovery import rebuild_selected_speakers
        if self._applying or self._snapshot is None or self._snapshot_in_project:
            return
        self._applying = True
        self.rebuild_button.setEnabled(False)
        bind_text(self.rebuild_button, "正在应用…")
        self._stop_preview()
        try:
            recovered = rebuild_selected_speakers(self.page.project, self._snapshot, dict(self._staged_roles))
            command = RecoverSpeakersCommand(self.page.project, recovered, self.page._speaker_structure_changed)
            self.page.undo_stack.push(command)
            if command.error:
                raise RuntimeError(command.error)
            self.page._speaker_roles_pending = False
            self._applying = False
            self._load_snapshot()
            self._set_status(tr("应用成功：当前工程已更新为 {tracks} 条字幕轨 / {cues} 条字幕。新增原文及时间待复核；可撤销、保存和重开。",
                                tracks=len(recovered.speakers), cues=len(recovered.cues)))
        except Exception as exc:
            self._set_status(tr("应用失败，当前工程已保留原状态：{kind}: {error}", kind=type(exc).__name__, error=exc))
        finally:
            self._applying = False
            bind_text(self.rebuild_button, "从缓存重建轨道")
            self.page._populate_speakers()
            self.refresh()

    # -------------------------------------------------------------- preview
    def _card_preview(self, card: SpeakerCard) -> None:
        if self._preview_key == card.key and self._preview_timer.isActive():
            self._stop_preview()
            return
        span = card.data.get("excerpt_range")
        if span:
            self._start_preview(int(span[0]), int(span[1]), card)

    def _card_preview_at(self, card: SpeakerCard, milliseconds: int) -> None:
        intervals = card.strip.intervals()
        if not intervals:
            return
        start, end = min(intervals, key=lambda item: 0 if item[0] <= milliseconds <= item[1]
                         else min(abs(item[0] - milliseconds), abs(item[1] - milliseconds)))
        begin = max(0, start - 150)
        self._start_preview(begin, begin + min(4000, max(2000, end - start + 300)), card)

    def _start_preview(self, start, end, card: SpeakerCard | None = None) -> None:
        self._stop_preview()
        video = self.page.video
        if not video.controller:
            self._set_status(tr("请先等待媒体预览就绪，再点击试听。"))
            return
        video.set_paused(True)
        self._preview_return_rate = float(self.page.speed_box.currentData() or 1.)
        self.page._set_speed(1.)
        self.page._seek(start / 1000)
        self._preview_video = video
        video.set_paused(False)
        self._preview_timer.start(max(1, int(end - start)))
        self._preview_card = card
        self._preview_key = card.key if card is not None else ""
        if card is not None:
            for view in self._views(card.key) or [card]:
                view.set_playing(True)

    def _stop_preview(self, *_args) -> None:
        self._preview_timer.stop()
        card, self._preview_card = self._preview_card, None
        key, self._preview_key = self._preview_key, ""
        from shiboken6 import isValid
        for view in ([card] if card is not None else []) + (self._views(key) if key else []):
            if isValid(view):
                view.set_playing(False)
        video = self._preview_video
        self._preview_video = None
        if video is not None and video.controller:
            video.set_paused(True)
            if self._preview_return_rate != 1.:
                self.page._set_speed(self._preview_return_rate)

    # ----------------------------------------------------- selection / batch
    def _filter_rows(self, text=None) -> None:
        needle = str(self.speaker_filter.text() if text is None else text or "").casefold()
        pending_only = self.pending_button.isChecked()
        for key, tile in self.tiles.items():
            data = self._data.get(key) or {}
            matches = not needle or needle in key.casefold() or needle in str(data.get("name", "")).casefold()
            tile.setHidden(not (matches and (not pending_only or data.get("pending"))))
        for box in self.boxes.values():
            box.refresh_hint()

    def _confirm_single_identity(self):
        from ..projects.single_speaker import confirm_single_speaker_command
        try:
            command = confirm_single_speaker_command(self.page.project, changed=self.page._speaker_structure_changed)
            self._push(command)
            self.refresh()
        except ValueError as error:
            self._set_status(str(error))

    def _batch(self, action, target=None, all_rows=False, ids=None):
        from ..projects.speaker_organization import organization_command
        project = self.page.project
        ids = {speaker.id for speaker in project.speakers} if all_rows else set(ids or self._selected_ids())
        if not ids:
            return
        count = sum(cue.speaker_id in ids for cue in project.cues)
        if action == "delete" and studio_message_box(
                self, QMessageBox.Icon.Question, tr("删除人物及字幕"),
                tr("删除 {value0} 个身份及 {value1} 条字幕？可在 Studio 撤销。", value0=len(ids), value1=count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self._push(organization_command(project, ids, action, target, self.page._speaker_structure_changed))
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self.refresh(target or "")

    def _apply_count_policy(self) -> None:
        from ..projects.speaker_organization import organization_command, utterance_counts
        project = self.page.project
        counts = utterance_counts(project.generation_metadata.get("speaker_recovery", {}).get("raw_segments", []))
        if not counts:
            self._set_status(tr("没有完整任务的原始发言统计，保留当前整理。"))
            return
        threshold = self.utterance_threshold.value()
        decisions = project.generation_metadata.get("speaker_organization", {}).get("decisions", {})
        ids = {speaker.id for speaker in project.speakers if not speaker.is_host and decisions.get(speaker.id) != "main"
               and counts.get(speaker.id, 0) <= threshold}
        self._push(organization_command(project, ids, "background", changed=self.page._speaker_structure_changed,
                                        threshold=threshold))
        self.refresh()

    def _assign_selected_cues(self, key: str) -> None:
        project = self.page.project
        cue_ids = self.page.selected_cue_ids()
        if not cue_ids or self._speaker(key) is None:
            return
        try:
            self._push(AssignSpeakerCommand(project, cue_ids, key, self.page._speaker_structure_changed))
        except ValueError as exc:
            self._set_status(str(exc))
        self.refresh(key)

    def _keep_only(self, key: str) -> None:
        project = self.page.project
        hidden = [speaker.id for speaker in project.speakers if speaker.id != key and not speaker.hidden]
        if hidden:
            self._push(SetSpeakersVisibilityCommand(project, hidden, self.page._speaker_structure_changed))
        self.refresh(key)
