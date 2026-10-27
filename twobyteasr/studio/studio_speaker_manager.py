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
import os
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..design.presentation import button_role
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


class SpeakerManagerDialog(QDialog):
    def __init__(self, page: "SubtitleStudioPage"):
        super().__init__(page)
        self.page = page
        self.cards: dict[str, SpeakerCard] = {}
        self._committing_name = False
        self._refreshing = False
        self._banner_dismissed = False
        self._multi = False
        self._snapshot: dict | None = None
        self._snapshot_in_project = False
        self._snapshot_error = ""
        self._staged_roles: dict[str, str] = {}
        self._stats: dict[str, dict] = {}
        self._representatives: dict[str, tuple[int, int, str]] = {}
        self._applying = False
        self._preview_card: SpeakerCard | None = None
        self._preview_video = None
        self._preview_return_rate = 1.0
        self._voiceprint_mailbox = queue.Queue()
        self._voiceprint_cancel = threading.Event()
        self._voiceprint_report = None
        self._voiceprint_timer = QTimer(self)
        self._voiceprint_timer.setInterval(150)
        self._voiceprint_timer.timeout.connect(self._voiceprint_poll)
        bind_text(self, "说话人管理", property="windowTitle")
        self.setObjectName("toolDialog")
        self.setMinimumSize(760, 520)
        self.resize(1000, 740)
        apply_secondary_surface_theme(self)
        theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(theme) + build_speaker_manager_qss(theme))
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._stop_preview)
        self.finished.connect(self._stop_preview)
        self._build_ui()
        self._load_snapshot()
        if self._snapshot:
            report = self._snapshot.get('processing', {}).get('voiceprint_review')
            if isinstance(report, dict) and report.get('groups'):
                from ..recognition.scoped_voiceprint import cue_signature
                if report.get('cue_signature') == cue_signature(self.page.project.cues):
                    self._voiceprint_report = report
                    bind_text(self.voiceprint_button, '查看声纹候选')
        self.refresh()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        page.undo_stack.indexChanged.connect(self._undo_index_changed)
        for sequence, slot in ((QKeySequence.StandardKey.Undo, page.undo_stack.undo),
                               (QKeySequence.StandardKey.Redo, page.undo_stack.redo),
                               (QKeySequence("Ctrl+Y"), page.undo_stack.redo)):
            QShortcut(sequence, self, slot)
        self._select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self,
                                              lambda: self._select_visible("all"))
        self._delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self, lambda: self._batch("delete"))
        self._sync_multi_shortcuts()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QWidget()
        body.setObjectName("speakerManagerBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(18, 14, 18, 12)
        column.setSpacing(10)
        root.addWidget(body, 1)

        self.show_names = QCheckBox(tr('在字幕前显示说话人名称'))
        self.show_names.setObjectName('speakerNameVisibility')
        self.show_names.toggled.connect(self._set_name_visibility)
        column.addWidget(self.show_names)
        self.name_scope = QLabel(tr('作用于目前工程的预览、字幕导出与压制成片；双语只在上面一行显示名称。'))
        self.name_scope.setWordWrap(True)
        self.name_scope.setObjectName('speakerMeta')
        column.addWidget(self.name_scope)
        self.name_preview = QLabel()
        self.name_preview.setObjectName('speakerNamePreview')
        self.name_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.name_preview.setWordWrap(True)
        column.addWidget(self.name_preview)

        self.banner = QFrame()
        self.banner.setObjectName("speakerBanner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 8, 8, 8)
        banner_row.setSpacing(10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setTextFormat(Qt.TextFormat.PlainText)
        banner_row.addWidget(self.banner_text, 1)
        self.rebuild_button = QPushButton()
        bind_text(self.rebuild_button, "从缓存重建轨道")
        button_role(self.rebuild_button, "primary", size="compact")
        self.rebuild_button.clicked.connect(self._apply_candidates)
        banner_row.addWidget(self.rebuild_button)
        self.banner_close = QPushButton()
        bind_text(self.banner_close, "知道了")
        button_role(self.banner_close, "ghost", size="compact")
        self.banner_close.clicked.connect(self._dismiss_banner)
        banner_row.addWidget(self.banner_close)
        column.addWidget(self.banner)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("speakerMeta")
        toolbar.addWidget(self.summary_label, 1)
        self.speaker_filter = QLineEdit()
        self.speaker_filter.setProperty("fieldWidth", "speakerFilter")
        self.speaker_filter.setMinimumWidth(200)
        self.speaker_filter.setClearButtonEnabled(True)
        bind_text(self.speaker_filter, "搜索名称或标签", property="placeholderText")
        self.speaker_filter.textChanged.connect(self._filter_rows)
        toolbar.addWidget(self.speaker_filter)
        self.voiceprint_button = QPushButton()
        bind_text(self.voiceprint_button, '声纹比对')
        bind_text(self.voiceprint_button, '比较多个独立语音样本，试听候选后再决定是否合并；字幕可撤销。', property='toolTip')
        button_role(self.voiceprint_button, 'secondary', size='compact')
        self.voiceprint_button.clicked.connect(self._voiceprint_clicked)
        toolbar.addWidget(self.voiceprint_button)
        self.multi_button = QPushButton()
        bind_text(self.multi_button, "多选")
        bind_text(self.multi_button, "勾选几位后批量归入游戏声、合并或删除", property="toolTip")
        button_role(self.multi_button, "secondary", size="compact")
        self.multi_button.setCheckable(True)
        self.multi_button.toggled.connect(self._set_multi)
        toolbar.addWidget(self.multi_button)
        column.addLayout(toolbar)

        self.batch_bar = QFrame()
        self.batch_bar.setObjectName("speakerBatchBar")
        batch = QVBoxLayout(self.batch_bar)
        batch.setContentsMargins(10, 8, 10, 8)
        batch.setSpacing(6)
        first = QHBoxLayout()
        first.setSpacing(6)
        self.selection_summary = QLabel()
        first.addWidget(self.selection_summary, 1)
        for title, mode in (("全选", "all"), ("取消选择", "none"), ("反选", "invert")):
            button = QPushButton()
            bind_text(button, title)
            button_role(button, "ghost", size="compact")
            button.clicked.connect(lambda _=False, m=mode: self._select_visible(m))
            first.addWidget(button)
        batch.addLayout(first)
        second = QHBoxLayout()
        second.setSpacing(6)
        self.batch_buttons: dict[str, QPushButton] = {}
        for title, action in (("归入游戏背景声", "background"), ("设为主要说话人", "main"), ("恢复原归属", "restore")):
            button = QPushButton()
            bind_text(button, title)
            button_role(button, "secondary", size="compact")
            button.clicked.connect(lambda _=False, a=action: self._batch(a))
            self.batch_buttons[action] = button
            second.addWidget(button)
        self.batch_merge_button = QToolButton()
        self.batch_merge_button.setObjectName("speakerMerge")
        bind_text(self.batch_merge_button, "合并到 ▾")
        self.batch_merge_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.batch_merge_menu = create_studio_menu(self.batch_merge_button)
        self.batch_merge_menu.aboutToShow.connect(self._fill_batch_merge_menu)
        self.batch_merge_button.setMenu(self.batch_merge_menu)
        second.addWidget(self.batch_merge_button)
        second.addStretch(1)
        self.delete_identity_button = QPushButton()
        bind_text(self.delete_identity_button, "删除身份，字幕移到统一轨")
        button_role(self.delete_identity_button, "secondary", size="compact")
        self.delete_identity_button.clicked.connect(lambda: self._batch("identity_delete"))
        second.addWidget(self.delete_identity_button)
        self.delete_captions_button = QPushButton()
        bind_text(self.delete_captions_button, "删除所选人物及字幕")
        button_role(self.delete_captions_button, "danger", size="compact")
        self.delete_captions_button.clicked.connect(lambda: self._batch("delete"))
        second.addWidget(self.delete_captions_button)
        batch.addLayout(second)
        self.batch_bar.hide()
        column.addWidget(self.batch_bar)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("speakerCardScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_host = QWidget()
        self.card_host.setObjectName("speakerCardHost")
        self.card_grid = QGridLayout(self.card_host)
        self.card_grid.setContentsMargins(0, 0, 4, 0)
        self.card_grid.setHorizontalSpacing(12)
        self.card_grid.setVerticalSpacing(12)
        self.card_grid.setColumnStretch(0, 1)
        self.card_grid.setColumnStretch(1, 1)
        self.scroll.setWidget(self.card_host)
        column.addWidget(self.scroll, 1)

        self.more_toggle = QToolButton()
        self.more_toggle.setObjectName("speakerMoreToggle")
        self.more_toggle.setCheckable(True)
        self.more_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind_text(self.more_toggle, "更多工具：MOSS 缓存、重新识别、整理")
        self.more_toggle.toggled.connect(self._toggle_more)
        column.addWidget(self.more_toggle)
        self.more_tools = QFrame()
        self.more_tools.setObjectName("speakerMoreTools")
        tools = QVBoxLayout(self.more_tools)
        tools.setContentsMargins(0, 8, 0, 0)
        tools.setSpacing(7)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.load_cache_button = QPushButton()
        bind_text(self.load_cache_button, "选择本素材 MOSS 缓存…")
        button_role(self.load_cache_button, "secondary", size="compact")
        self.load_cache_button.clicked.connect(self._choose_cache)
        row.addWidget(self.load_cache_button)
        self.reanalyze_button = QPushButton()
        bind_text(self.reanalyze_button, "用当前方案重新识别…")
        bind_text(self.reanalyze_button, "打开当前工程识别设置，选择当前识别方案。会重新生成字幕，不是只补标签；请先保存人工编辑的工程副本。", property="toolTip")
        button_role(self.reanalyze_button, "secondary", size="compact")
        self.reanalyze_button.clicked.connect(self._open_recognition)
        row.addWidget(self.reanalyze_button)
        self.single_button = QPushButton()
        bind_text(self.single_button, "全部合并为单轨")
        button_role(self.single_button, "secondary", size="compact")
        self.single_button.clicked.connect(lambda: self._batch("single", all_rows=True))
        row.addWidget(self.single_button)
        row.addStretch(1)
        tools.addLayout(row)
        policy = QHBoxLayout()
        policy.setSpacing(8)
        policy.addWidget(self._plain_label("原始发言超过"))
        self.utterance_threshold = QSpinBox()
        self.utterance_threshold.setRange(1, 1000)
        self.utterance_threshold.setProperty("fieldWidth", "speakerThreshold")
        self.utterance_threshold.setMinimumWidth(80)
        self.utterance_threshold.setValue(int(self.page.project.generation_metadata.get(
            "speaker_organization", {}).get("threshold", 10)))
        policy.addWidget(self.utterance_threshold)
        policy.addWidget(self._plain_label("句才算主要说话人，其余归入游戏背景声"))
        self.count_policy_button = QPushButton()
        bind_text(self.count_policy_button, "按原始发言数整理")
        button_role(self.count_policy_button, "secondary", size="compact")
        self.count_policy_button.clicked.connect(self._apply_count_policy)
        policy.addWidget(self.count_policy_button)
        policy.addStretch(1)
        tools.addLayout(policy)
        self.candidate_note = QLabel()
        self.candidate_note.setObjectName("speakerMeta")
        self.candidate_note.setWordWrap(True)
        tools.addWidget(self.candidate_note)
        self.more_tools.hide()
        column.addWidget(self.more_tools)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(18, 10, 18, 12)
        foot.setSpacing(8)
        self.status = QLabel()
        self.status.setObjectName("speakerFooterStatus")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.done_button = QPushButton()
        bind_text(self.done_button, "完成")
        button_role(self.done_button, "primary")
        self.done_button.clicked.connect(self.accept)
        foot.addWidget(self.done_button)
        root.addWidget(footer)

    @staticmethod
    def _plain_label(text: str) -> QLabel:
        label = QLabel()
        bind_text(label, text)
        return label

    def _toggle_more(self, shown: bool) -> None:
        self.more_tools.setVisible(shown)
        self.more_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def _set_multi(self, enabled: bool) -> None:
        self._multi = bool(enabled)
        if not enabled:
            for card in self.cards.values():
                card.select_check.blockSignals(True)
                card.select_check.setChecked(False)
                card.select_check.blockSignals(False)
        for card in self.cards.values():
            card.select_check.setVisible(self._multi and card.data.get("present", False))
        self.batch_bar.setVisible(self._multi)
        self._sync_multi_shortcuts()
        self._update_selection_summary()

    def _sync_multi_shortcuts(self) -> None:
        for shortcut in (getattr(self, "_select_all_shortcut", None), getattr(self, "_delete_shortcut", None)):
            if shortcut is not None:
                shortcut.setEnabled(self._multi)

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
        body = translated if translated and (settings.mode == 'translation' or
            settings.mode == 'bilingual' and settings.order == 'translation_first') else cue.text
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
            if keys != list(self.cards):
                self._rebuild_cards(keys)
            for key, card in self.cards.items():
                card.update_data(self._card_data(key))
                card.select_check.setVisible(self._multi and card.data.get("present", False))
            self._filter_rows(self.speaker_filter.text())
            self.speaker_filter.setVisible(len(self.cards) > _FILTER_THRESHOLD or bool(self.speaker_filter.text()))
            self._refresh_banner()
            self._refresh_summary()
            self._update_selection_summary()
            self.candidate_note.setText(self._snapshot_error)
            self.candidate_note.setVisible(bool(self._snapshot_error))
            if selected_id in self.cards:
                self.scroll.ensureWidgetVisible(self.cards[selected_id])
        finally:
            self._refreshing = False

    def _rebuild_cards(self, keys: list[str]) -> None:
        checked = self._selected_ids()
        for card in self.cards.values():
            self.card_grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        if self._preview_card is not None and self._preview_card.key not in keys:
            self._preview_card = None
        self.cards = {}
        while self.card_grid.count():
            self.card_grid.takeAt(0)
        for index, key in enumerate(keys):
            card = SpeakerCard(key, self, self.card_host)
            card.select_check.setChecked(key in checked)
            self.cards[key] = card
            self.card_grid.addWidget(card, index // 2, index % 2, Qt.AlignmentFlag.AlignTop)
        self.card_grid.setRowStretch(len(keys) // 2 + 1, 1)
        for button in self.card_host.findChildren(QPushButton):
            button.setAutoDefault(False)

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
            data.update(excerpt_range=(excerpt[0], excerpt[1]), excerpt_time=_clock(excerpt[0] + 150 if stats else excerpt[0]),
                        excerpt=" ".join(str(excerpt[2]).split()))
        if stats is not None:
            data["role"] = role if role in {"main", "game", "ignore"} else ""
            reason = tr((self._snapshot or {}).get("reasons", {}).get(key, ""))
            if present and role == "unconfirmed" and anonymous:
                data.update(pending=True, pill=tr("待确认"),
                            pill_tip=join_text([tr("标签不等于真人身份，请按原音确认归属。"), reason], "\n"))
            if not present:
                if role == "ignore":
                    cached = len((self._snapshot or {}).get("cue_cache", {}).get(key, []))
                    data["status"] = tr("已忽略 · {count} 条字幕留在缓存里，选「主要」就能恢复。", count=cached)
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
        for card in self.cards.values():
            if card.name_edit.isEnabled() and not self._finish_name_edit(card):
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
        state = self._snapshot or {}
        if not self._snapshot_in_project or state.get('confirmed_by'):
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
        elif report and report.get('groups'):
            self._voiceprint_report = report
            bind_text(self.voiceprint_button, '查看声纹候选')
            self.refresh()
            self._set_status(tr('发现 {count} 组相似声纹候选；卡片的 ▶ 可试听比对样本，尚未修改工程。', count=len(report['groups'])))
        else:
            self._set_status(tr('没有足够一致的候选；原有说话人保持不变。'))

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
        current = self._roles().get(card.key, "unconfirmed")
        if role == current:
            if not self._anonymous():
                card.roles.set_role(current)
                return
            role = "unconfirmed"
        self._set_role(card.key, role)

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
        try:
            result = apply_candidate_role(project, self._snapshot, label, role)
        except (ValueError, KeyError, TypeError) as exc:
            self._set_status(str(exc))
            self.refresh(label)
            return
        if result is None:
            self.refresh(label)
            return
        self._stop_preview()
        command = RecoverSpeakersCommand(project, result, self.page._speaker_structure_changed)
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
        if self._preview_card is card and self._preview_timer.isActive():
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
        if card is not None:
            card.set_playing(True)

    def _stop_preview(self, *_args) -> None:
        self._preview_timer.stop()
        card, self._preview_card = self._preview_card, None
        if card is not None:
            try:
                card.set_playing(False)
            except RuntimeError:
                pass  # The card was rebuilt while its preview ran.
        video = self._preview_video
        self._preview_video = None
        if video is not None and video.controller:
            video.set_paused(True)
            if self._preview_return_rate != 1.:
                self.page._set_speed(self._preview_return_rate)

    # ----------------------------------------------------- selection / batch
    def _card_selection_changed(self) -> None:
        self._update_selection_summary()

    def _selected_ids(self) -> set[str]:
        return {key for key, card in self.cards.items()
                if card.select_check.isChecked() and card.data.get("present", False)}

    def _select_visible(self, mode: str) -> None:
        for card in self.cards.values():
            if card.isHidden() or not card.data.get("present", False):
                continue
            checked = mode == "all" or (mode == "invert" and not card.select_check.isChecked())
            card.select_check.blockSignals(True)
            card.select_check.setChecked(checked)
            card.select_check.blockSignals(False)
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        ids = self._selected_ids()
        count = sum(cue.speaker_id in ids for cue in self.page.project.cues)
        bind_text(self.selection_summary, "已选 {value0} 人 / {count} 条字幕", value0=len(ids), count=count)
        for button in (*self.batch_buttons.values(), self.batch_merge_button,
                       self.delete_identity_button, self.delete_captions_button):
            button.setEnabled(bool(ids))

    def _filter_rows(self, text: str) -> None:
        needle = str(text or "").casefold()
        for key, card in self.cards.items():
            card.setHidden(bool(needle) and needle not in key.casefold()
                           and needle not in str(card.data.get("name", "")).casefold())

    def _fill_batch_merge_menu(self) -> None:
        menu = self.batch_merge_menu
        menu.clear()
        selected = self._selected_ids()
        for speaker in self.page.project.speakers:
            if speaker.id in selected:
                continue
            action = menu.addAction(tr("并入 {name}", name=self._display_name(speaker.id)))
            action.triggered.connect(lambda _=False, target=speaker.id: self._batch("merge", target=target))
        if menu.isEmpty():
            menu.addAction(tr("没有可并入的说话人")).setEnabled(False)

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
