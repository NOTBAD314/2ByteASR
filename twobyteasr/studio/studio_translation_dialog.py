"""Translate / generate bilingual subtitles for the open project (Japanese -> Chinese).

One dialog for the whole workflow: choose the scope (all, selected, or only
cues that are untranslated / failed / need an update), the Chinese script and
optional context and term pairs, then run the configured AI text service.
Only subtitle text (with a few neighbouring lines as context) is sent; audio,
timing and speakers stay local and unchanged. Results are applied as one
undoable edit; manual translations are never overwritten silently.
"""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget, QApplication)

from ..i18n import bind_text, tr, user_text
from .translation_dialog_parts import (LayoutButton, ScopeCard, StatusBar, build_translation_dialog_qss, chip,
                                       passive, step_badge)

from ..subtitle_rules.recognition_translation import load_cache, save_cache  # noqa: E402

# Derived per-cue states (subtitle_translation.STATUSES), in display order.
STATUS_LABELS = (("untranslated", "未翻译"), ("done", "已翻译"), ("manual", "人工译文"),
                 ("needs_update", "需更新 / 合并后部分缺译"), ("failed", "失败"))


def failure_reason(code) -> str:
    """Plain words for a failed record's ``error`` code (subtitle_translation.validate_translation)."""
    code = str(code or "")
    if code.startswith("provider_error"):
        return "请求出错"
    if code in ("empty", "missing", "unknown_id", "duplicate_id"):
        return "模型没有给出这一条"
    if code == "echo_source":
        return "模型照抄了原文"
    if code in ("too_long", "timestamp"):
        return "译文格式不对"
    if code.endswith("_output") or code.startswith("not_") or code == "no_chinese":
        return "译文不是所选语言"
    return "没有通过检查"


def _flag_text(code: str) -> str:
    """Two letters for a language pill: 简 / 繁 for Chinese scripts, else the code (IT, JA, EN …)."""
    code = str(code or "")
    if code in ("zh-Hans", "zh"):
        return "简" if code == "zh-Hans" else "中"
    if code == "zh-Hant":
        return "繁"
    return code.split("-")[0][:2].upper() or "?"


def _european_label(language: str) -> str:
    """西班牙语 / 德语 / 法语 / 葡萄牙语 / 意大利语 / 俄语, or '' (2026-10-19)."""
    from ..subtitle_rules.european_text import LABELS
    return LABELS.get(str(language or ""), "")


def parse_glossary(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in str(text or "").splitlines():
        for separator in ("=", "＝", "→", "->", "\t"):
            if separator in line:
                left, right = line.split(separator, 1)
                if left.strip() and right.strip():
                    pairs.append((left.strip(), right.strip()))
                break
    return pairs


class _Signals(QObject):
    progress = Signal(int, int, str)
    event = Signal(object)
    finished = Signal(object)


class SubtitleTranslationDialog(QDialog):
    translation_finished = Signal(bool, dict)

    def __init__(self, page, parent=None, *, scope=None, cue_ids=None, target=None, atomic_display=False) -> None:
        super().__init__(parent)
        bind_text(self, '翻译 / 生成双语字幕', property='windowTitle')
        # 2026-11-11 (user picked 方案 A): three steps instead of one long column of text.
        self.setObjectName('translationDialog')
        # 2026-11-11 (user): not the Windows title bar; a round card in the app's own style.
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(580 + 2 * self.SHADOW)
        from ..design.studio_theme import _active_theme, apply_secondary_surface_theme, build_secondary_surface_qss
        apply_secondary_surface_theme(self)
        self._theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(self._theme) + build_translation_dialog_qss(self._theme))
        self._phase = 'idle'
        self.page = page
        self.project = page.project
        self._atomic_display = bool(atomic_display)
        self._session_generation = getattr(getattr(page, 'session', None), 'generation', None)
        self._cancel = threading.Event()
        self._thread = None
        self._result = None
        self._log = None
        self._signals = _Signals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.event.connect(self._on_event)
        from ..subtitle_rules.subtitle_translation import migrate
        migrate(self.project)
        frame = QVBoxLayout(self)
        frame.setContentsMargins(self.SHADOW, self.SHADOW - 4, self.SHADOW, self.SHADOW + 4)
        self._card = QFrame()
        self._card.setObjectName('translationCard')
        frame.addWidget(self._card)
        outer = QVBoxLayout(self._card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        from ..subtitle_rules.language_rules import project_language
        from ..subtitle_rules.subtitle_translation import _translation_language
        language = _translation_language(self.project)
        self._language = language
        from ..projects.subtitle_import import language_label
        theme = self._theme
        from ..design.themed_icons import colored_icon

        # -- header: what goes into what ------------------------------------
        header = QFrame()
        header.setObjectName('translationHeader')
        head = QVBoxLayout(header)
        head.setContentsMargins(24, 20, 24, 12)
        head.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        badge = QLabel()
        badge.setObjectName('translationBadge')
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(colored_icon('ph.translate', theme.text_on_accent).pixmap(20, 20))
        title = QLabel()
        title.setObjectName('translationTitle')
        bind_text(title, '翻译字幕')
        title_row.addWidget(badge)
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.window_close_button = QPushButton('×')
        self.window_close_button.setObjectName('translationWindowClose')
        self.window_close_button.setFixedSize(34, 34)
        self.window_close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.window_close_button, '关闭', property='toolTip')
        self.window_close_button.clicked.connect(lambda: self._cancel_or_close())
        title_row.addWidget(self.window_close_button, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(title_row)
        pair = QHBoxLayout()
        pair.setSpacing(10)
        source_pill, _flag = self._language_pill(_flag_text(language) if language else '?', target=False)
        self.source_language_label = QLabel(language_label(language) if language else tr('未记录'))
        self.source_language_label.setObjectName('translationLangName')
        source_pill.layout().addWidget(self.source_language_label)
        arrow = QLabel('→')
        arrow.setObjectName('translationArrow')
        target_pill, self.target_flag = self._language_pill('', target=True)
        # Any target in another language than the source (2026-10-14); native names.
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, targets_for
        self.script = user_text(QComboBox())
        self.script.setObjectName('translationTargetCombo')
        self.script.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for language_target in targets_for(language):
            self.script.addItem(TARGET_LABELS[language_target], language_target)
        stored = (target or (self.project.generation_metadata.get("translation_records") or {}).get("target")
                  or (self.project.generation_metadata.get("subtitle_output") or {}).get("translation_script")
                  or "zh-Hans")
        self.script.setCurrentIndex(max(0, self.script.findData(stored)))
        target_pill.layout().addWidget(self.script)
        pair.addWidget(source_pill)
        pair.addWidget(arrow)
        pair.addWidget(target_pill)
        pair.addStretch(1)
        head.addLayout(pair)
        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        lock = QLabel()
        lock.setPixmap(colored_icon('ph.lock-simple', theme.text_muted).pixmap(13, 13))
        lock.setAlignment(Qt.AlignmentFlag.AlignTop)
        lock.setContentsMargins(0, 2, 0, 0)
        self.language_note = QLabel()
        self.language_note.setObjectName('translationSafeNote')
        self.language_note.setWordWrap(True)
        bind_text(self.language_note, '只发字幕文字，不发音频；译文单独保存，原文、说话人和时间都不动。')
        bind_text(self.language_note, '翻译读取已提交的正文。', property='toolTip')
        if not language:
            self.language_note.setText(self.language_note.text() + str(tr('旧工程没有记录原文语言，按日语处理，请确认。')))
        elif not project_language(self.project):
            self.language_note.setText(self.language_note.text() + str(tr('语言依据导入标记或明确词库方向，请确认。')))
        note_row.addWidget(lock)
        note_row.addWidget(self.language_note, 1)
        head.addLayout(note_row)
        outer.addWidget(header)
        header.mousePressEvent = self._drag_window   # no title bar: the header moves the window

        self._header = header
        body = QWidget()
        body.setObjectName('translationBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 4, 24, 12)
        layout.setSpacing(16)
        self._body = body
        # Small screens: the steps scroll, header and buttons stay (_fit_height).
        self._scroll = QScrollArea()
        self._scroll.setObjectName('translationScroll')
        self._scroll.viewport().setObjectName('translationScrollViewport')
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(160)
        self._scroll.setWidget(body)
        outer.addWidget(self._scroll, 1)

        # -- 1 翻译哪些 ------------------------------------------------------
        self.scope_section = QWidget()
        section = QVBoxLayout(self.scope_section)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(10)
        section.addWidget(self._section_header(1, '翻译哪些'))
        self.scope_group = QButtonGroup(self)
        self.scope_group.setExclusive(True)
        selected = list(cue_ids if cue_ids is not None else (getattr(page, "selected_cue_ids", lambda: [])() or []))
        self._selected = selected
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.scope_buttons = {}
        for key, label in (("pending", tr("待处理")), ("all", tr("全部")), ("selected", tr("选中的"))):
            card = ScopeCard(key, label)
            self.scope_group.addButton(card)
            self.scope_buttons[key] = card
            cards.addWidget(card, 1)
        section.addLayout(cards)
        layout.addWidget(self.scope_section)
        self.scope_buttons["selected"].set_values(len(selected), tr("时间轴上选中的") if selected
                                                  else tr("先在列表或时间轴上选中"))
        self.scope_buttons["selected"].setEnabled(bool(selected))
        initial_scope = scope if scope in ('all', 'pending') else ('selected' if selected else 'pending')
        self.scope_buttons[initial_scope].setChecked(True)
        self.scope_group.buttonToggled.connect(lambda *_args: self._refresh_start_label())

        # -- 2 让 AI 更懂这部作品（默认收起） ---------------------------------
        self.advanced_section = QWidget()
        section = QVBoxLayout(self.advanced_section)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(10)
        self.advanced_toggle = LayoutButton()
        self.advanced_toggle.setObjectName('translationSectionToggle')
        self.advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_row = self._header_row(self.advanced_toggle, 2, '让 AI 更懂这部作品')
        toggle_row.addWidget(chip(tr('可选')))
        toggle_row.addStretch(1)
        self.context_chip, self.terms_chip = chip(), chip()
        toggle_row.addWidget(self.context_chip)
        toggle_row.addWidget(self.terms_chip)
        self.advanced_caret = passive(QLabel())
        toggle_row.addWidget(self.advanced_caret)
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        section.addWidget(self.advanced_toggle)
        self.advanced = QFrame()
        self.advanced.setObjectName('translationAdvanced')
        inner = QVBoxLayout(self.advanced)
        inner.setContentsMargins(14, 12, 14, 14)
        inner.setSpacing(10)
        self.context = QLineEdit(str(self.project.generation_metadata.get("translation_context")
                                     or getattr(page, "_content_name", "") or ""))
        self.context.setObjectName('translationContext')
        bind_text(self.context, '背景（可选）：作品 / 游戏名、角色关系，帮助译名一致', property='placeholderText')
        inner.addWidget(self.context)
        from ..glossary.translation_terms_ui import project_widget
        self.term_libraries = project_widget(page, self)
        self.term_libraries.summary.setObjectName('translationLibText')
        self.term_libraries.manage.setObjectName('translationSecondary')
        self.term_libraries.manage.clicked.connect(self._refresh_advanced_summary)
        inner.addWidget(self._library_row('ph.book-open', self.term_libraries))
        import subtitle_core as legacy
        catalog = {str(row['id']): str(row['name']) for row in legacy.glossary_catalog()}
        source_names = '、'.join(catalog.get(identity, identity) for identity in self.project.glossary_ids) or tr('未选择')
        if not self.project.generation_metadata.get('source_glossary_enabled', True):
            source_names = tr('已关闭') + ' · ' + source_names
        self.source_terms_label = QLabel(tr('原文校对术语库') + '：' + source_names)
        self.source_terms_label.setObjectName('translationLibText')
        self.source_terms_label.setWordWrap(True)
        inner.addWidget(self._library_row('ph.check-bold', self.source_terms_label))
        self.glossary = QPlainTextEdit()
        self.glossary.setObjectName('translationGlossary')
        self.glossary.setMaximumHeight(90)
        self._glossary_hint()
        pairs = self.project.generation_metadata.get("translation_glossary") or []
        self.glossary.setPlainText("\n".join(f"{a} = {b}" for a, b in pairs if a and b))
        inner.addWidget(self.glossary)
        self.advanced.hide()
        section.addWidget(self.advanced)
        layout.addWidget(self.advanced_section)
        self.context.textChanged.connect(self._refresh_advanced_summary)
        self.glossary.textChanged.connect(self._refresh_advanced_summary)

        # -- 翻译中 -----------------------------------------------------------
        self.run_box = QFrame()
        self.run_box.setObjectName('translationRunBox')
        run = QVBoxLayout(self.run_box)
        run.setContentsMargins(16, 14, 16, 14)
        run.setSpacing(10)
        run_top = QHBoxLayout()
        run_top.setSpacing(10)
        self.run_percent = QLabel('0%')
        self.run_percent.setObjectName('translationRunPercent')
        self.run_detail = QLabel()
        self.run_detail.setObjectName('translationRunDetail')
        self.run_detail.setWordWrap(True)
        run_top.addWidget(self.run_percent, 0, Qt.AlignmentFlag.AlignBottom)
        run_top.addWidget(self.run_detail, 1, Qt.AlignmentFlag.AlignBottom)
        run.addLayout(run_top)
        self.progress = QProgressBar()
        self.progress.setObjectName('translationProgress')
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        run.addWidget(self.progress)
        run_hint = QLabel()
        run_hint.setObjectName('translationHint')
        run_hint.setWordWrap(True)
        bind_text(run_hint, '可以先去编辑别的字幕；结束后一起写入，期间改过的字幕不会被覆盖。')
        run.addWidget(run_hint)
        self.run_box.hide()
        layout.addWidget(self.run_box)

        # -- 结果 / 提示 --------------------------------------------------------
        self.result_card = QFrame()
        self.result_card.setObjectName('translationResultCard')
        result = QVBoxLayout(self.result_card)
        result.setContentsMargins(16, 12, 16, 14)
        result.setSpacing(6)
        self.result_title = QLabel()
        self.result_title.setObjectName('translationResultTitle')
        self.result_title.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName('translationStatus')
        self.status.setWordWrap(True)
        self.accept_suggestions_button = QPushButton(tr("用 AI 结果替换这些人工译文"))
        self.accept_suggestions_button.setObjectName('translationSecondary')
        self.accept_suggestions_button.hide()
        self.accept_suggestions_button.clicked.connect(self._accept_suggestions)
        result.addWidget(self.result_title)
        result.addWidget(self.status)
        result.addWidget(self.accept_suggestions_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.result_card.hide()
        layout.addWidget(self.result_card)

        # -- 3 这个工程翻到哪了 -------------------------------------------------
        self.overview = QWidget()
        section = QVBoxLayout(self.overview)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(10)
        section.addWidget(self._section_header(3, '这个工程翻到哪了'))
        self.status_bar = StatusBar()
        section.addWidget(self.status_bar)
        self.counts = QLabel()
        self.counts.setObjectName('translationLegend')
        self.counts.setTextFormat(Qt.TextFormat.RichText)
        self.counts.setWordWrap(True)
        section.addWidget(self.counts)
        # 2026-10-27 (user): in a long video one failed line was impossible to find.
        self.failed_box = QFrame()
        self.failed_box.setObjectName('translationAlert')
        failed_row = QHBoxLayout(self.failed_box)
        failed_row.setContentsMargins(12, 10, 12, 10)
        failed_row.setSpacing(12)
        alert_icon = QLabel()
        alert_icon.setObjectName('translationAlertIcon')
        alert_icon.setFixedSize(32, 32)
        alert_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alert_icon.setPixmap(colored_icon('ph.warning-circle', theme.surface).pixmap(18, 18))
        failed_text = QVBoxLayout()
        failed_text.setSpacing(2)
        self.failed_title = QLabel()
        self.failed_title.setObjectName('translationAlertTitle')
        self.failed_title.setTextFormat(Qt.TextFormat.RichText)
        self.failed_note = QLabel()
        self.failed_note.setWordWrap(True)
        self.failed_note.setObjectName("translationAlertDetail")
        failed_text.addWidget(self.failed_title)
        failed_text.addWidget(self.failed_note)
        self.locate_failed_button = QPushButton(tr("定位"))
        self.locate_failed_button.setObjectName('translationPillButton')
        self.locate_failed_button.setIcon(colored_icon('ph.crosshair', theme.text))
        self.locate_failed_button.clicked.connect(self._locate_failed)
        failed_row.addWidget(alert_icon, 0, Qt.AlignmentFlag.AlignTop)
        failed_row.addLayout(failed_text, 1)
        failed_row.addWidget(self.locate_failed_button, 0, Qt.AlignmentFlag.AlignVCenter)
        section.addWidget(self.failed_box)
        self._failed_ids, self._failed_cursor = [], 0
        layout.addWidget(self.overview)

        # -- 请求日志与用量（默认收起） -------------------------------------------
        self.log_toggle = QPushButton()
        self.log_toggle.setObjectName('translationLogToggle')
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_toggle.setIcon(colored_icon('ph.list-bullets', theme.text_muted))
        self.log_toggle.clicked.connect(self._toggle_log)
        self.log_panel = QWidget()
        log = QVBoxLayout(self.log_panel)
        log.setContentsMargins(0, 0, 0, 0)
        log.setSpacing(6)
        self.log_note = QLabel(tr("请求日志只保留批次、用量与验证摘要；要分享字幕内容，请在「回报问题」中选择。"))
        self.log_note.setObjectName('translationHint')
        self.log_note.setWordWrap(True)
        self.request_log = QPlainTextEdit()
        self.request_log.setObjectName('translationLog')
        self.request_log.setReadOnly(True)
        self.request_log.setMaximumBlockCount(1000)
        self.request_log.setFixedHeight(125)
        self.request_log.setPlaceholderText(tr("开始后显示每批请求、耗时、用量、失败原因和重试过程。"))
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.copy_log_button = QPushButton(tr("复制请求日志"))
        self.copy_log_button.setObjectName('translationSecondary')
        self.copy_log_button.setIcon(colored_icon('ph.copy', theme.text))
        self.copy_log_button.setEnabled(False)
        self.copy_log_button.clicked.connect(self._copy_log)
        self.usage_button = QPushButton(tr('用量与估算费用'))
        self.usage_button.setObjectName('translationSecondary')
        self.usage_button.clicked.connect(self._show_usage)
        tools.addWidget(self.copy_log_button)
        tools.addWidget(self.usage_button)
        tools.addStretch(1)
        self._usage_task_id = ''
        log.addLayout(tools)
        log.addWidget(self.request_log)
        log.addWidget(self.log_note)
        self.log_panel.hide()
        layout.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.log_panel)
        layout.addStretch(1)  # spare height stays below the steps

        # -- footer: which service, start / close --------------------------------
        footer = QFrame()
        footer.setObjectName('translationFooter')
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 12, 24, 16)
        buttons.setSpacing(8)
        self.service_dot = QLabel()
        self.service_dot.setObjectName('translationServiceDot')
        self.service_dot.setFixedSize(8, 8)
        self.service = QLabel()
        self.service.setObjectName("translationService")
        # 2026-11-11 (user: the service name was cut off): it wraps onto a second line instead.
        self.service.setWordWrap(True)
        self.service.setMinimumWidth(150)
        self.service.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.settings_button = QPushButton(tr('更换'))
        self.settings_button.setObjectName('translationLink')
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip(tr('前往设置：AI 文字翻译服务 / API Key'))
        self.settings_button.clicked.connect(self._go_to_settings)
        self.start_button = QPushButton(tr("开始翻译"))
        self.start_button.setObjectName("translationStart")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton(tr("关闭"))
        self.cancel_button.setObjectName('translationClose')
        self.cancel_button.clicked.connect(self._cancel_or_close)
        buttons.addWidget(self.service_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addSpacing(2)
        buttons.addWidget(self.service, 1)
        buttons.addWidget(self.settings_button)
        buttons.addSpacing(8)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)
        outer.addWidget(footer)
        self._footer = footer

        self._provider_ready = self._describe_service()
        self._refresh_counts()
        self._refresh_target_flag()
        self._refresh_advanced_summary()
        self._refresh_log_toggle()
        self.script.currentIndexChanged.connect(self._target_changed)
        self._fit_height()

    def _go_to_settings(self):
        from .translation_actions import open_translation_settings
        open_translation_settings(self)

    def _show_usage(self):
        from .usage_dialog import open_usage
        open_usage(self, project=self.project, task_id=self._usage_task_id)

    # -- layout pieces -------------------------------------------------------
    def _language_pill(self, flag_text: str, *, target: bool):
        pill = QFrame()
        pill.setObjectName('translationLangPill')
        pill.setProperty('target', target)
        row = QHBoxLayout(pill)
        row.setContentsMargins(7, 6, 16, 6)
        row.setSpacing(8)
        flag = QLabel(flag_text)
        flag.setObjectName('translationLangFlag')
        flag.setProperty('target', target)
        flag.setFixedSize(30, 30)
        flag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(flag)
        return pill, flag

    @staticmethod
    def _header_row(owner: QWidget, number: int, title: str) -> QHBoxLayout:
        """Step badge + title at x = 0 of ``owner``: the three steps line up (2026-11-11 user)."""
        row = QHBoxLayout(owner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = passive(QLabel())
        label.setObjectName('translationSectionTitle')
        bind_text(label, title)
        row.addWidget(step_badge(number))
        row.addWidget(label)
        return row

    def _section_header(self, number: int, title: str) -> QWidget:
        header = QWidget()
        header.setObjectName('translationSectionHeader')
        self._header_row(header, number, title).addStretch(1)
        return header

    def _library_row(self, icon: str, content: QWidget) -> QFrame:
        from ..design.themed_icons import colored_icon
        frame = QFrame()
        frame.setObjectName('translationLibRow')
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(colored_icon(icon, self._theme.text_secondary).pixmap(16, 16))
        row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(content, 1)
        return frame

    def _toggle_advanced(self) -> None:
        self.advanced.setVisible(self.advanced.isHidden())
        self._refresh_advanced_summary()
        self._fit_height()

    def _refresh_advanced_summary(self) -> None:
        from ..design.themed_icons import colored_icon
        from ..glossary.translation_terms import normalize, policy_of
        opened = not self.advanced.isHidden()
        self.advanced_caret.setPixmap(colored_icon('ph.caret-up' if opened else 'ph.caret-down',
                                                   self._theme.text_muted).pixmap(14, 14))
        self.context_chip.setVisible(not opened)
        self.terms_chip.setVisible(not opened)
        bind_text(self.context_chip, '背景 已填' if self.context.text().strip() else '背景 未填')
        try:
            policy = normalize(policy_of(self.project))
            libraries = len(policy['selected_ids']) if policy['enabled'] else 0
        except Exception:  # noqa: BLE001 - only a summary chip
            libraries = 0
        libraries += len(self.project.glossary_ids or ()) if self.project.generation_metadata.get(
            'source_glossary_enabled', True) else 0
        if libraries or parse_glossary(self.glossary.toPlainText()):
            bind_text(self.terms_chip, '术语 已设')
        else:
            bind_text(self.terms_chip, '术语库 未选')

    def _toggle_log(self) -> None:
        self.log_panel.setVisible(self.log_panel.isHidden())
        self._refresh_log_toggle()
        self._fit_height()

    def _refresh_log_toggle(self) -> None:
        lines = self.request_log.blockCount() if self.request_log.toPlainText() else 0
        arrow = '▴' if not self.log_panel.isHidden() else '▾'
        if lines:
            bind_text(self.log_toggle, '请求日志与用量 · {count} 行 {arrow}', count=lines, arrow=arrow)
        else:
            bind_text(self.log_toggle, '请求日志与用量 {arrow}', arrow=arrow)

    def _refresh_target_flag(self) -> None:
        self.target_flag.setText(_flag_text(self._target()))

    def _refresh_start_label(self) -> None:
        card = next((card for card in self.scope_buttons.values() if card.isChecked()), None)
        bind_text(self.start_button, '开始翻译 · {count} 条', count=card.count() if card is not None else 0)

    SHADOW = 14                                          # room around the round card for its soft shadow
    RADIUS = 26

    def _drag_window(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        card = QRectF(self._card.geometry()) if hasattr(self, '_card') else QRectF(self.rect())
        for spread, alpha in ((14, 14), (9, 22), (4, 34)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(card.adjusted(-spread / 2, -spread / 2 + 3, spread / 2, spread / 2 + 5),
                                    self.RADIUS + spread / 2, self.RADIUS + spread / 2)
        painter.end()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # Sizes before the first show predate the style sheet's fonts and paddings.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self) -> None:
        """Grow to the content, at most the screen's free height; the steps scroll beyond that."""
        if not hasattr(self, '_footer'):
            return
        def height(widget, width):
            # Wrapped labels: the height at the real width, not the size hint's guess.
            layout = widget.layout()
            if layout is not None and layout.hasHeightForWidth():
                return layout.totalHeightForWidth(width)
            return widget.sizeHint().height()

        width = max(self.width(), self.minimumWidth())
        inner = width - 2 * self.SHADOW
        wanted = (height(self._header, inner) + height(self._body, inner) + height(self._footer, inner) + 2
                  + 2 * self.SHADOW)
        screen = self.screen() or QApplication.primaryScreen()
        limit = screen.availableGeometry().height() - 80 if screen is not None else wanted
        self.resize(max(self.width(), self.minimumWidth()), max(360, min(wanted, limit)))

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _set_phase(self, phase: str) -> None:
        """idle / run / done: what the dialog shows around the same controls."""
        self._phase = phase
        running = phase == 'run'
        for widget in (self.scope_section, self.advanced_section, self.overview):
            widget.setVisible(not running)
        self.run_box.setVisible(running)
        self.start_button.setVisible(not running)
        if running:
            self.result_card.hide()
            self.run_percent.setText('0%')
        self.cancel_button.setProperty('stop', running)
        bind_text(self.cancel_button, '停止' if running else '关闭')
        self._repolish(self.cancel_button)
        self._fit_height()

    def _show_result(self, tone: str, title: str, **values) -> None:
        """The card above the overview: ``tone`` ok / bad / info, ``self.status`` holds the details."""
        self.result_card.setProperty('tone', tone)
        bind_text(self.result_title, title, **values)
        self._repolish(self.result_card)
        for child in self.result_card.findChildren(QLabel):
            self._repolish(child)
        self.result_card.show()
        self._fit_height()

    # -- state -------------------------------------------------------------
    def _target(self) -> str:
        return str(self.script.currentData() or "zh-Hans")

    def _target_changed(self, _index: int) -> None:
        self._glossary_hint()
        self._refresh_target_flag()
        self._refresh_counts()

    def _glossary_hint(self) -> None:
        chinese_target = self._target() in ("zh-Hans", "zh-Hant")
        if chinese_target and self._language == "en":
            hint = '术语对照（可选，每行一条）：英文 = 中文，例如 Paimon = 派蒙'
        elif chinese_target and self._language == "ko":
            hint = '术语对照（可选，每行一条）：韩文 = 中文，例如 페이몬 = 派蒙'
        elif chinese_target and _european_label(self._language):
            hint = '术语对照（可选，每行一条）：原文 = 中文，例如 Paimon = 派蒙'
        elif chinese_target:
            hint = '术语对照（可选，每行一条）：日文 = 中文，例如 ゆっこ = 由子'
        else:
            hint = '术语对照（可选，每行一条）：原文 = 译文，例如 派蒙 = Paimon'
        bind_text(self.glossary, hint, property='placeholderText')

    def _refresh_counts(self) -> None:
        from ..subtitle_rules.subtitle_translation import status_counts
        counts = status_counts(self.project, target=self._target())
        t = self._theme
        colors = {"untranslated": t.text_muted, "done": t.success, "manual": t.accent_text,
                  "needs_update": t.warning, "failed": t.danger}
        self.counts.setText("&nbsp;&nbsp;&nbsp;".join(
            f'<span style="color:{colors[key]}">●</span>&nbsp;{tr(label)}&nbsp;<b>{counts.get(key, 0)}</b>'
            for key, label in STATUS_LABELS))
        self.status_bar.set_segments([(counts.get(key, 0), colors[key])
                                      for key in ("done", "manual", "needs_update", "failed")], t.selected)
        pending = sum(counts.get(key, 0) for key in ("untranslated", "failed", "needs_update"))
        self.scope_buttons["pending"].set_values(pending, tr("失败 {failed} · 未译 {untranslated} · 需更新 {update}",
                                                             failed=counts.get("failed", 0),
                                                             untranslated=counts.get("untranslated", 0),
                                                             update=counts.get("needs_update", 0)))
        self.scope_buttons["all"].set_values(sum(counts.values()), tr("人工译文会保留"))
        self._refresh_start_label()
        self._refresh_failed()

    def _cue_number(self, cue_id: str) -> str:
        """The caption's number in the workbench list (#), else its id."""
        index = (getattr(self.page, "_cue_jump_index", None) or {}).get(str(cue_id))
        return str(index + 1) if index is not None else str(cue_id)

    def _refresh_failed(self) -> None:
        from ..subtitle_rules.subtitle_translation import ids_with_status, records_of
        failed = ids_with_status(self.project, {"failed"}, target=self._target())
        if failed != self._failed_ids:
            self._failed_ids, self._failed_cursor = failed, 0
        self.failed_note.setVisible(bool(failed))
        self.locate_failed_button.setVisible(bool(failed))
        self.failed_box.setVisible(bool(failed))
        if not failed:
            return
        self.failed_title.setText(str(tr('{count} 条没翻成功', count=f'<b style="color:{self._theme.danger}; '
                                                                   f'font-size:15px">{len(failed)}</b>')))
        records = records_of(self.project)
        items = " · ".join(f"#{self._cue_number(cue_id)} {tr(failure_reason((records.get(cue_id) or {}).get('error')))}"
                           for cue_id in failed[:3])
        if len(failed) > 3:
            items += " · " + tr("等 {count} 条", count=len(failed))
        bind_text(self.failed_note, "失败的字幕：{items}", items=items)
        if len(failed) == 1:
            bind_text(self.locate_failed_button, "定位")
        else:
            bind_text(self.locate_failed_button, "定位下一条 {index}/{total}",
                      index=self._failed_cursor % len(failed) + 1, total=len(failed))

    def _locate_failed(self) -> None:
        """Select the next failed caption in the workbench and move the playhead there; the dialog stays open."""
        if not self._failed_ids or not self._owns_project():
            return
        cue_id = self._failed_ids[self._failed_cursor % len(self._failed_ids)]
        self._failed_cursor += 1
        page = self.page
        model = getattr(page, "cue_model", None)
        if (model is not None and not getattr(page, "_review_mode", False) and model.row_for_cue_id(cue_id) < 0
                and model.filter_status != "all" and callable(getattr(page, "_activate_filter", None))):
            page._activate_filter("all")  # a list filter must not hide the caption being located
        index = (getattr(page, "_cue_jump_index", None) or {}).get(cue_id)
        order = getattr(page, "_cue_jump_order", None) or ()
        if index is not None and index < len(order) and callable(getattr(page, "_go_to_listed_cue", None)):
            page._go_to_listed_cue(order[index])
        elif callable(getattr(page, "select_cue", None)):
            page.select_cue(cue_id)
        table = getattr(page, "cue_table", None)
        row = model.row_for_cue_id(cue_id) if model is not None else -1
        if table is not None and row >= 0:
            # The selection scope marks the row before the controller's
            # scroll step runs, which then skips it: scroll here.
            from PySide6.QtWidgets import QAbstractItemView
            table.scrollTo(model.index(row, 3), QAbstractItemView.ScrollHint.EnsureVisible)
        self._refresh_failed()

    def _describe_service(self) -> bool:
        from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
        from ..providers.llm_config import text_ai_key_missing
        missing = False
        try:
            settings = GLOBAL_PROVIDER_REGISTRY.settings()
            selection = GLOBAL_PROVIDER_REGISTRY.selection(settings, stage="polish")
            ready, _source = GLOBAL_PROVIDER_REGISTRY.credential(selection)
            model = str(getattr(selection, "model", "") or "")
            name = f"{selection.service or selection.provider}{' · ' + model if model else ''}"
            missing = not ready and text_ai_key_missing(settings, "polish")
        except Exception:  # noqa: BLE001 - shown to the user as "not configured"
            ready, name = False, ""
        # 2026-11-11: one short line in the footer; the full sentence is the tooltip.
        if ready:
            bind_text(self.service, "{name} · 可能产生费用", name=name)
            bind_text(self.service, "使用已配置的 AI 文字服务：{name}。只发送字幕文字和前后几句上下文（不发送音频），"
                                    "按批请求，可能产生费用；不会改用其他模型。", name=name, property='toolTip')
            bind_text(self.settings_button, '更换')
        elif missing:
            # 2026-10-15: only the key is missing — 开始翻译 stays clickable and explains it.
            bind_text(self.service, '{name} 还没填 API Key', name=name)
            bind_text(self.service, '文字翻译服务 {name} 尚未填写 API Key。请前往“字幕校对”服务设置；不是语音识别 ASR 的 Key。',
                      name=name, property='toolTip')
            bind_text(self.settings_button, '去填写')
        else:
            bind_text(self.service, "还没有配置 AI 文字服务")
            bind_text(self.service, "还没有配置 AI 文字服务：请先在设置中配置“字幕校对”使用的服务，再回来翻译。",
                      property='toolTip')
            bind_text(self.settings_button, '前往设置')
        self.service_dot.setProperty('state', 'ready' if ready else 'missing' if missing else 'none')
        self._repolish(self.service_dot)
        self.start_button.setEnabled(ready or missing)
        return ready or missing

    def _scope_ids(self, project=None):
        from ..subtitle_rules.subtitle_translation import ids_with_status
        project = self.project if project is None else project
        if self.scope_buttons["selected"].isChecked():
            return list(self._selected)
        if self.scope_buttons["all"].isChecked():
            return None
        return ids_with_status(project, {"untranslated", "failed", "needs_update"}, target=self._target())

    # -- run ---------------------------------------------------------------
    def _owns_project(self) -> bool:
        return (not getattr(self.page, '_close_requested', False)
                and self.page.project is self.project
                and getattr(getattr(self.page, 'session', None), 'generation', None) == self._session_generation)

    def _log_disowned_result(self, result=None) -> None:
        from ..diagnostics.studio_events import background_result
        decision = ("discarded_project_changed" if self.page.project is not self.project else
                    "discarded_page_closed" if getattr(self.page, "_close_requested", False) else
                    "discarded_session_changed")
        background_result(getattr(self, "_diagnostic", {}), self.page.project,
                          decision=decision, cancelled=bool(getattr(result, "cancelled", False)),
                          applied_count=0)

    def _start(self) -> None:
        if self._thread is not None:
            return
        if not self._owns_project():
            bind_text(self.status, '工程已切换或关闭，请在当前工程重新打开翻译。')
            self._show_result('info', '没有开始')
            return
        from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
        from ..providers.ai_providers import provider_for_stage
        from ..subtitle_rules.subtitle_translation import translation_source
        from copy import copy
        pairs = parse_glossary(self.glossary.toPlainText())
        scope_project = copy(self.project)
        scope_project.generation_metadata = dict(self.project.generation_metadata,
            translation_glossary=[list(pair) for pair in pairs])
        ids = self._scope_ids(scope_project)
        source = translation_source(self.project)
        eligible = {cue.id for cue in source.cues}
        if ids is not None:
            from ..timeline.studio_edit_sequence import source_cue_id_of
            canonical = {cue.id for cue in self.project.cues}
            ids = list(dict.fromkeys(cue_id if cue_id in canonical else source_cue_id_of(cue_id) for cue_id in ids))
            ids = [cue_id for cue_id in ids if cue_id in eligible]
        if ids is not None and not ids:
            bind_text(self.status, "所选内容没有属于本次源语言的待处理原文；独立译文轨道请使用译文校对。")
            self._show_result('info', '没有要翻译的字幕')
            return
        from ..providers.llm_config import text_ai_key_missing
        if text_ai_key_missing(GLOBAL_PROVIDER_REGISTRY.settings(), 'polish'):
            self._describe_service()
            bind_text(self.status, '翻译没有运行：请点击右下角“去填写”填写当前文字服务的 API Key；保存后会检查原文并继续。')
            self._show_result('info', '还差一步：填写 API Key')
            self.settings_button.setFocus()
            return
        self.request_log.clear()
        self.accept_suggestions_button.hide()
        self._result = None
        from ..subtitle_rules.translation_diagnostics import TranslationLog
        self._log = TranslationLog()
        self.copy_log_button.setEnabled(True)
        self.request_log.appendPlainText(tr("日志文件：{path}", path=str(self._log.path)))
        self._refresh_log_toggle()
        self.project.generation_metadata["translation_glossary"] = [list(pair) for pair in pairs]
        self.project.generation_metadata["translation_context"] = self.context.text().strip()
        from dataclasses import replace
        from ..subtitle_rules.subtitle_translation import normalize_glossary
        source = replace(source, inline_pairs=normalize_glossary(pairs))
        self._session_generation = getattr(getattr(self.page, "session", None), "generation", None)
        try:
            provider = provider_for_stage(GLOBAL_PROVIDER_REGISTRY.settings(), "polish")
        except Exception as exc:
            self._log({"event": "error", "error": str(exc)})
            self._on_finished(exc)
            return
        performance = GLOBAL_PROVIDER_REGISTRY.settings().get('performance', {})
        workers = (max(1, min(4, int(performance.get('cloud_batch_workers', 4))))
                   if performance.get('parallel_cloud_batches', True) else 1)
        from ..subtitle_rules.subtitle_translation import RECOMMENDED_BATCH_ITEMS
        options = dict(entrypoint="studio", target=self._target(), game_context=self.context.text().strip(), glossary_pairs=pairs,
                       workers=workers, max_items=RECOMMENDED_BATCH_ITEMS)
        self._request_target = options['target']
        import uuid
        self._usage_task_id = uuid.uuid4().hex
        self._cancel.clear()
        self.start_button.setEnabled(False)
        self.script.setEnabled(False)
        self.settings_button.setEnabled(False)
        for button in self.scope_buttons.values():
            button.setEnabled(False)
        bind_text(self.cancel_button, "停止")
        bind_text(self.status, "正在翻译…")
        self._run_total = len(ids) if ids is not None else len(source.cues)
        bind_text(self.run_detail, '正在把 {count} 条翻成{target}', count=self._run_total, target=self.script.currentText())
        self.progress.setValue(0)
        self._set_phase('run')
        cache = load_cache()

        def record(event):
            self._log(event)
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.event.emit(event)

        def progress(done, total, message=''):
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.progress.emit(int(done), int(total), str(message or ''))

        def work():
            from ..subtitle_rules.subtitle_translation import translate
            try:
                from ..providers.usage_ledger import usage_scope
                with usage_scope(project_id=source.project_id, task_id=self._usage_task_id):
                    result = translate(source, ids, provider, cancel_check=self._cancel.is_set,
                                       progress=progress, cache=cache, suggest_for_manual=True,
                                       event=record, **options)
                try:
                    save_cache(cache)
                except OSError:
                    pass
            except Exception as exc:  # noqa: BLE001 - reported in the dialog
                from ..providers.provider_diagnostics import redact_diagnostics
                record({"event": "error", "error": str(redact_diagnostics(str(exc)))})
                result = exc
            from shiboken6 import isValid
            if isValid(self._signals):
                self._signals.finished.emit(result)

        from ..diagnostics.studio_events import background_ticket
        self._diagnostic = background_ticket(self.project,"translation",ids=ids)
        from ..diagnostics.event_log import context
        original_work = work
        def bound_work():
            with context(**self._diagnostic):
                original_work()
        self._thread = threading.Thread(target=bound_work, name="subtitle-translation", daemon=True)
        self._thread.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        percent = int(100 * done / max(1, total))
        self.progress.setValue(percent)
        self.run_percent.setText(f"{percent}%")
        bind_text(self.status, "已完成 {done}/{total} 条 {message}", done=done, total=total, message=message)
        if not self._cancel.is_set():
            bind_text(self.run_detail, "已完成 {done} / {total} 条 {message}", done=done, total=total, message=message)

    def _on_event(self, event: dict) -> None:
        from ..providers.provider_diagnostics import redact_diagnostics
        event = redact_diagnostics(event)
        kind, batch = event.get("event"), event.get("batch", "")
        prefix = f"[{event.get('at', '')}] "
        if kind == "request":
            text = tr("第 {batch} 批 · {provider} / {model} · {count} 条 · 输出上限 {tokens}",
                      batch=batch, provider=event.get("provider"), model=event.get("model"),
                      count=len(event.get("ids", [])), tokens=event.get("max_tokens"))
        elif kind == "response":
            usage = event.get("usage") or {key: value for key, value in event.get("response_metadata", {}).items()
                                          if key in {"prompt_tokens", "completion_tokens", "total_tokens"}}
            text = tr("第 {batch} 批返回 · {seconds} 秒 · 用量 {usage}", batch=batch,
                      seconds=event.get("elapsed_seconds"), usage=json.dumps(usage, ensure_ascii=False) if usage else tr("未返回用量"))
        elif kind == "validated":
            text = tr("第 {batch} 批校验 · 接受 {count} 条 · 问题 {problems}", batch=batch,
                      count=event.get("accepted"), problems=json.dumps(event.get("problems", {}), ensure_ascii=False))
        elif kind == 'terminology_conflict':
            mappings = '; '.join(f"{row['source']} → {row['target']}" for row in event.get('required', ()))
            text = tr('术语冲突 · 字幕 {cue} · AI候选「{candidate}」与用户约定「{rules}」不同，已退回重试。',
                      cue=self._cue_number(event.get('id', '')), candidate=str(event.get('offered') or ''), rules=mappings)
        elif kind == "error":
            from .translation_actions import failure_hint
            text = tr("第 {batch} 批失败 · {category} · {error}", batch=batch,
                      category=event.get("category", ""), error=event.get("error", ""))
            text += ' ' + failure_hint(event.get('category'))
        elif kind == "retry":
            text = tr("第 {batch} 批重试 · 剩余 {count} 条 · 等待 {seconds} 秒 · 输出至少 {tokens}",
                      batch=batch, count=len(event.get("ids", [])), seconds=event.get("wait_seconds"),
                      tokens=event.get("output_floor"))
        elif kind == "started":
            text = tr("开始翻译：{count} 条 · {provider} / {model}", count=event.get("requested"),
                      provider=event.get("provider"), model=event.get("model"))
        elif kind == "finished":
            summary = event.get("summary", {})
            text = tr("翻译结束：成功 {done} 条，失败 {failed} 条，请求 {requests} 批", done=summary.get("succeeded", 0),
                      failed=summary.get("failed", 0), requests=summary.get("requests", 0))
        elif kind == "cache":
            text = tr("缓存命中 {count} 条", count=event.get("count", 0))
        elif kind == "split":
            text = tr("拆分批次：{count} 条 · {reason}", count=len(event.get("ids", [])), reason=event.get("reason"))
        else:
            # Request/answer bodies stay in the copyable file; the visible log
            # remains readable while a long project is running.
            text = json.dumps({key: value for key, value in event.items()
                               if key not in {"at", "provider", "model", "target", "failed"}}, ensure_ascii=False)
        self.request_log.appendPlainText(prefix + text)
        self.request_log.verticalScrollBar().setValue(self.request_log.verticalScrollBar().maximum())
        self._refresh_log_toggle()

    def _copy_log(self) -> None:
        from ..providers.provider_diagnostics import redact_diagnostics
        text = self.request_log.toPlainText()
        if self._log is not None:
            try:
                text = self._log.path.read_text(encoding="utf-8")
            except OSError:
                pass
        QApplication.clipboard().setText(str(redact_diagnostics(text)))

    def _on_finished(self, result) -> None:
        self._thread = None
        self._set_phase('done')
        self.script.setEnabled(True)
        self.settings_button.setEnabled(True)
        for key, button in self.scope_buttons.items():
            button.setEnabled(key != 'selected' or bool(self._selected))
        if not self._owns_project():
            self._log_disowned_result(result)
            self._result = None
            self.start_button.setEnabled(False)
            self.accept_suggestions_button.hide()
            bind_text(self.cancel_button, '关闭')
            bind_text(self.status, '工程已切换或关闭，这次翻译结果未写入。')
            self._show_result('info', '结果没有写入')
            self.translation_finished.emit(False, {})
            return
        self.start_button.setEnabled(self._provider_ready)
        bind_text(self.cancel_button, "关闭")
        if self._log is not None and self._log.error:
            self.request_log.appendPlainText(tr("日志文件写入失败：{error}", error=self._log.error))
        if isinstance(result, Exception):
            from ..diagnostics.studio_events import background_result
            from ..diagnostics.event_log import emit, exception_info
            background_result(getattr(self,"_diagnostic",{}),self.page.project,decision="failed",cancelled=self._cancel.is_set())
            emit("translation.failed",level="ERROR",result="failed",exception=exception_info(result),**getattr(self,"_diagnostic",{}))
            from ..providers.provider_diagnostics import redact_diagnostics
            from .translation_actions import failure_hint
            error = failure_hint(getattr(result, 'category', '')) + str(redact_diagnostics(str(result)))
            self.request_log.appendPlainText(error)
            bind_text(self.status, "翻译没有完成：{error}。已完成的部分没有写入，可以再试。", error=error[:200])
            self._show_result('bad', '这一次没翻成功')
            self._refresh_log_toggle()
            self.translation_finished.emit(False, {})
            return
        from ..diagnostics.studio_events import background_result
        self._result = result
        if result.target != self._target():
            background_result(getattr(self,"_diagnostic",{}), self.project,
                              decision="discarded_target_changed", cancelled=result.cancelled, applied_count=0)
            bind_text(self.status, '目标语言已变化，迟到的翻译结果没有写入。')
            self._show_result('info', '结果没有写入')
            self.translation_finished.emit(False, {})
            return
        if (self.page.project is not self.project
                or getattr(self, "_session_generation", None) != getattr(getattr(self.page, "session", None), "generation", None)):
            self._log_disowned_result(result)
            bind_text(self.status, '工程已切换，迟到的翻译结果没有写入。请求用量仍保留在记录中。')
            self._show_result('info', '结果没有写入')
            self.translation_finished.emit(False, {})
            return
        from ..subtitle_rules.subtitle_translation import apply_translation_result
        from .studio_bilingual import (ApplyTranslationSnapshotCommand, apply_display, current_settings,
                                      settings_for_changes, sync_controls)
        from ..diagnostics.event_log import context
        with context(**getattr(self, "_diagnostic", {})):
            before, after = apply_translation_result(self.project, result, commit=not self._atomic_display)
            changed_ids = sorted(set(result.translations) | set(result.failed))
            if before != after:
                display = (settings_for_changes(self.project, mode="bilingual")
                           if self._atomic_display and result.translations and current_settings(self.page).mode == "original"
                           else None)
                command = ApplyTranslationSnapshotCommand(self.project, before, after, changed_ids,
                                                           label="AI 翻译字幕", display_settings=display, refresh_text_ids=result.translations)
                outcome = command.outcome
                self.page.undo_stack.push(command)
                if self._atomic_display and not outcome["applied"]:
                    from ..diagnostics.event_log import emit, exception_info
                    error = outcome["error"] or RuntimeError("translation transaction was not committed")
                    emit("translation.failed", level="ERROR", result="failed", exception=exception_info(error))
                    bind_text(self.status, "翻译结果未写入：{error}", error=str(error))
                    self._show_result('bad', '结果没有写入')
                    self.translation_finished.emit(False, {})
                    return
            decision = ("partially_accepted" if result.discarded and result.translations else
                        "discarded_stale" if result.discarded else
                        "accepted" if result.translations else
                        "waiting" if result.suggestions else
                        "cancelled" if result.cancelled else "failed" if result.failed else "skipped")
            background_result(getattr(self,"_diagnostic",{}), self.project, decision=decision,
                              cancelled=result.cancelled, stale_ids=result.discarded,
                              applied_count=len(result.translations) if before != after else 0,
                              discard_reasons=result.discarded)
        parts = [tr("成功 {count} 条", count=len(result.translations))]
        if result.terminology_warnings:
            parts.append(tr('译名或语境需核对 {count} 条；可打开AI词库校对，选择译文', count=len(result.terminology_warnings)))
        if result.discarded:
            parts.append(tr('跳过 {count} 条已修改、撤销或删除的字幕', count=len(result.discarded)))
        if result.cache_hits:
            parts.append(tr("其中 {count} 条来自翻译缓存", count=len(result.cache_hits)))
        if result.failed:
            parts.append(tr("失败 {count} 条（选“待处理”可以再试）", count=len(result.failed)))
            from ..providers.provider_diagnostics import redact_diagnostics
            reason = str(redact_diagnostics(result.fatal_error or next(iter(result.failed.values()))))
            if result.fatal_error:
                parts.append(tr("失败原因：{error}（详情见请求日志）", error=reason[:180]))
            else:
                parts.append(tr("失败原因：{reason}（{error}，详情见请求日志）", reason=tr(failure_reason(reason)),
                                error=reason[:180]))
        if result.suggestions:
            parts.append(tr("人工译文 {count} 条保留不变（AI 结果可选择替换）", count=len(result.suggestions)))
            self.accept_suggestions_button.show()
        if getattr(result, "pending", None):
            parts.append(tr("未处理 {count} 条", count=len(result.pending)))
        if result.cancelled:
            parts.append(tr("已停止；已完成的部分已保存"))
        bind_text(self.status, "；".join(parts) + "。")
        if result.failed and result.translations:
            self._show_result('bad', '翻好 {done} 条，{failed} 条没成功', done=len(result.translations),
                              failed=len(result.failed))
        elif result.failed:
            self._show_result('bad', '这一次没翻成功')
        elif result.cancelled:
            self._show_result('info', '已停止')
        elif result.translations:
            self._show_result('ok', '翻好了 {count} 条', count=len(result.translations))
        else:
            self._show_result('info', '这次没有新的译文')
        self.progress.setValue(100)
        self._refresh_counts()
        if result.translations and self._atomic_display:
            sync_controls(self.page)
            for name in ("_refresh_ass_preview", "_present_caption_scene"):
                callback = getattr(self.page, name, None)
                if callable(callback): callback()
        elif result.translations and current_settings(self.page).mode == "original":
            apply_display(self.page, mode="bilingual")
        self.translation_finished.emit(bool(result.translations), dict(result.translations))

    def _accept_suggestions(self) -> None:
        if self._result is None:
            return
        if not self._owns_project():
            self._log_disowned_result(self._result)
            return
        from ..subtitle_rules.subtitle_translation import accept_suggestions
        from .studio_bilingual import ApplyTranslationSnapshotCommand
        from ..diagnostics.studio_events import background_result
        from ..diagnostics.event_log import context
        with context(**getattr(self, "_diagnostic", {})):
            before, after = accept_suggestions(self.project, self._result)
            if before != after:
                self.page.undo_stack.push(ApplyTranslationSnapshotCommand(
                    self.project, before, after, list(self._result.suggestions), label="采用 AI 译文"))
            background_result(getattr(self,"_diagnostic",{}), self.project,
                              decision="accepted" if before != after else "skipped",
                              stale_ids=self._result.discarded, discard_reasons=self._result.discarded,
                              applied_count=len(self._result.suggestions) if before != after else 0)
        self.accept_suggestions_button.hide()
        self._refresh_counts()

    def _cancel_or_close(self) -> None:
        if self._thread is not None:
            self._cancel.set()
            bind_text(self.status, "正在停止：等待当前这一批返回…")
            bind_text(self.run_detail, "正在停止：等待当前这一批返回…")
            return
        self.reject()

    def reject(self) -> None:
        if self._thread is not None:
            self._cancel.set()
            return
        super().reject()
