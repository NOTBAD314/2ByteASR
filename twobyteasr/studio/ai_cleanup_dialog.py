"""AI 清理, one page (2026-10-26, the user picked design A "一页清单").

Top to bottom: the range and 「开始整理」; two groups of steps — 本地整理 (no AI,
instant: remove ``[Music]``-style labels, strictly re-break word-timed
captions) and AI 校对 (batched: fillers, needless repeats, typos and terms,
punctuation); the batch progress; type filters; one list of every proposed
change with its time, type and the change inline; 「应用 N 处」.

The local steps and the AI batches run in the background on a copy of the
project. Applying is one undo step: the chosen AI text changes first, then the
chosen re-breaks, planned again on the edited text (so an AI edit inside a
caption that is also re-broken is kept). The window has the rounded frame of
the link download window (``app/rounded_window``).

The class keeps the old dialog's attribute names (``ai_scope``,
``ai_option_boxes``, ``ai_run_button``, ``preview``, ``status_label``,
``all_button``, ``_do_ai_preview``, ``_do_apply_preview``): acceptance scripts
and tests drive the window through them.
"""
from __future__ import annotations

import copy
import difflib
import html
import queue
import threading
import unicodedata

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..diagnostics.studio_events import observed
from ..i18n import bind_text, tr
from .studio_find_replace import (PREVIEW_HTML_ROLE, PreviewBinding, _PreviewRowDelegate, _TextPreviewDialog,
                                  _preview_colors, occurrence_conflicts)
from .studio_text_tools import clock_ms, scope_cue_ids, values_from_occurrences

ROW_ROLE = Qt.ItemDataRole.UserRole + 5      # ("ai" | "local", index)
KIND_ROLE = Qt.ItemDataRole.UserRole + 6     # "break" | "delete" | "text"
TIME_ROLE = Qt.ItemDataRole.UserRole + 7

LOCAL_STEPS = (("labels", "删除 [Music]、♪、>> 等标注"), ("regroup", "按词严格重排断句"))
# Chip key, label, the request_text_cleanup options it asks for.
AI_STEPS = (("fillers", "口癖", ("fillers", "particles")), ("repeats", "无意义重复", ("repeats",)),
            ("glossary", "错字与术语", ("glossary",)), ("punctuation", "标点", ("punctuation",)))
FILTERS = (("all", "全部"), ("break", "断句"), ("delete", "删除"), ("text", "文字"))


def _diff_tokens(text: str) -> list[str]:
    """Words and spaces; punctuation and Chinese / Japanese characters one by one."""
    out, word = [], ""
    for char in text:
        if (char.isspace() or unicodedata.east_asian_width(char) in ("W", "F")
                or (unicodedata.category(char).startswith("P") and char != "'")):
            if word:
                out.append(word)
                word = ""
            out.append(char)
        else:
            word += char
    if word:
        out.append(word)
    return out


def diff_html(old: str, new: str, colors: dict) -> str:
    """``old`` → ``new`` in one line: removed words struck through, added underlined."""
    a, b = _diff_tokens(old), _diff_tokens(new)
    parts = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            parts.append(html.escape("".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            parts.append(f'<span style="background-color:{colors["removed"]}; text-decoration:line-through;">'
                         f'{html.escape("".join(a[i1:i2]))}</span>')
        if op in ("insert", "replace"):
            parts.append(f'<span style="background-color:{colors["added"]}; text-decoration:underline;">'
                         f'{html.escape("".join(b[j1:j2]))}</span>')
    return "".join(parts)


def _ai_kind(reason: str) -> str:
    text = str(reason or "")
    for needle, label in (("口癖", "口癖"), ("语气", "口癖"), ("重复", "重复"), ("标点", "标点"),
                          ("术语", "术语"), ("错字", "错字")):
        if needle in text:
            return label
    return "文字"


def cleanup_qss(t) -> str:
    from ..design.soft_qss import soft_tokens
    k = soft_tokens(t)
    return f"""
QWidget#cleanupRoot {{ background: {t.app_background}; color: {t.text}; }}
QFrame#cleanupTitleBar {{ background: {t.surface}; border: 0; border-bottom: 1px solid {t.border}; }}
QLabel#cleanupMark {{ background: {t.accent}; border-radius: 7px; }}
QLabel#cleanupTitle {{ color: {t.text}; font-size: 14px; font-weight: 700; }}
QLabel#cleanupFieldLabel {{ color: {t.text_secondary}; font-size: 13px; font-weight: 600; }}
QFrame#cleanupCard {{ background: {k.card}; border: 1px solid {t.border}; border-radius: 12px; }}
QLabel#cleanupCardTitle {{ color: {t.text}; font-size: 13px; font-weight: 700; background: transparent; }}
QLabel#cleanupCardNote {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QFrame#cleanupCard QCheckBox {{ color: {t.text}; font-size: 13px; background: transparent; }}
QFrame#cleanupCard QCheckBox:disabled {{ color: {t.text_muted}; }}
QPushButton#cleanupChip {{
    background: {k.card_fill}; color: {t.text_secondary}; border: 1px solid transparent; border-radius: 13px;
    min-height: 26px; max-height: 26px; padding: 0 12px; font-size: 13px;
}}
QPushButton#cleanupChip:hover {{ background: {k.card_fill_hover}; color: {t.text}; }}
QPushButton#cleanupChip:checked {{ background: {k.chip}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#cleanupPrimary {{
    background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 17px;
    min-height: 34px; max-height: 34px; padding: 0 18px; font-size: 14px; font-weight: 700;
}}
QPushButton#cleanupPrimary:hover {{ background: {t.accent_hover}; }}
QPushButton#cleanupPrimary:disabled {{ background: {k.fill}; color: {t.text_muted}; }}
QPushButton#cleanupGhost {{
    background: {k.fill}; color: {t.text}; border: 0; border-radius: 17px;
    min-height: 34px; max-height: 34px; padding: 0 16px; font-size: 14px;
}}
QPushButton#cleanupGhost:hover {{ background: {k.fill_hover}; }}
QPushButton#cleanupLink {{ background: transparent; color: {t.accent_text}; border: 0; padding: 0 6px;
    font-size: 13px; font-weight: 700; min-height: 24px; }}
QFrame#cleanupProgress {{ background: {k.fill}; border: 0; border-radius: 10px; }}
QLabel#cleanupStatus {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
QProgressBar#cleanupBar {{ background: {k.fill_strong}; border: 0; border-radius: 3px;
    min-height: 6px; max-height: 6px; }}
QProgressBar#cleanupBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
QPushButton#cleanupFilter {{
    background: {k.fill}; color: {t.text_secondary}; border: 0; border-radius: 14px;
    min-height: 28px; max-height: 28px; padding: 0 12px; font-size: 13px;
}}
QPushButton#cleanupFilter:checked {{ background: {t.text}; color: {t.app_background}; font-weight: 600; }}
QListWidget#cleanupList {{ background: {k.card}; border: 1px solid {t.border}; border-radius: 12px;
    padding: 4px; outline: 0; }}
QListWidget#cleanupList::item {{ padding: 8px 6px; border: 0; border-bottom: 1px solid {t.border}; }}
QListWidget#cleanupList::item:selected {{ background: {k.fill}; color: {t.text}; }}
QLabel#cleanupCount {{ color: {t.text_secondary}; font-size: 13px; background: transparent; }}
"""


class _RowList(QListWidget):
    """The change list; empty, it says where the changes will appear."""

    placeholder = "点「开始整理」后，要改的地方会一条条列在这里"

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count():
            return
        from PySide6.QtGui import QColor, QPainter
        from ..design.theme_manager import theme_definition, theme_key
        painter = QPainter(self.viewport())
        painter.setPen(QColor(theme_definition(theme_key()).text_muted))
        painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, tr(self.placeholder))
        painter.end()


class _Runner(QObject):
    """Background work for one 「开始整理」; the timer hands results back."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.mailbox = queue.SimpleQueue()
        self.closed = threading.Event()
        self.delivery_lock = threading.Lock()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        dialog.finished.connect(self.cancel)
        QApplication.instance().aboutToQuit.connect(self.cancel)

    def cancel(self, *_):
        self.dialog._cleanup_cancel.set()
        self.dialog._run_generation += 1
        self.dialog._closed = True
        with self.delivery_lock:
            self.closed.set()
            while not self.mailbox.empty():
                self.mailbox.get_nowait()
        self.timer.stop()
        # Closed parent-owned dialogs can outlive their modal exec(). Release
        # large preview/project references and discard delayed worker payloads.
        self.dialog._preview_hits = []
        self.dialog._local_splices = []
        self.dialog._preview_binding = None
        self.dialog._project = None

    def start(self, source, ids, local, options, settings):
        cancel = self.dialog._cleanup_cancel
        mailbox = self.mailbox
        closed = self.closed
        delivery_lock = self.delivery_lock
        generation = self.dialog._run_generation
        self.timer.start()
        # Imported before the thread starts: an importing thread waits for the
        # interpreter lock after every file it reads.
        from ..media.link_download import redact
        from ..recognition import cue_word_alignment  # noqa: F401
        from ..subtitle_rules import english_segmentation  # noqa: F401
        from ..timeline.caption_tidy import plan_caption_tidy
        from . import link_caption_cleanup as module   # tests replace its request_text_cleanup

        def send(message):
            with delivery_lock:
                if not closed.is_set():
                    mailbox.put((generation, message))

        def progress(state):
            send(("progress", state))

        def work():
            try:
                if local:
                    plan = plan_caption_tidy(source, ids, labels="labels" in local, regroup="regroup" in local)
                    send(("local", plan))
                hits, error = None, ""
                if options and not cancel.is_set():
                    hits = module.request_text_cleanup(source, ids, options, settings, cancel_check=cancel.is_set,
                                                       progress=progress)
                    error = redact(hits.error) if getattr(hits, "error", "") else ""
                send(("done", hits, error))
            except Exception as exc:
                send(("failed", redact(exc)))

        threading.Thread(target=work, daemon=True, name="caption-cleanup").start()

    def poll(self):
        # A long batch must not monopolize the GUI when its progress arrives.
        for _ in range(64):
            try:
                generation, message = self.mailbox.get_nowait()
            except queue.Empty:
                break
            self.dialog._message(message, generation=generation)


class AiCleanupDialog(_TextPreviewDialog):
    """AI 清理 (see the module note)."""

    _title = "AI 清理"
    _download_defaults = False

    def __init__(self, page, parent=None):
        super().__init__(page, parent)
        self.setMinimumSize(640, 540)
        self.resize(760, 660)
        self._local_splices: list = []
        self._local_used: set[str] = set()
        self._filter = "all"
        self._no_word_times = False
        self._cleanup_running = False
        self._cleanup_cancel = threading.Event()
        self._run_generation = 0
        self._applying = False
        self._closed = False
        project = page.session.project if page is not None else None
        self._project = project
        self._session_generation = getattr(page.session, "generation", None) if page is not None else None
        imported = bool(project and project.studio_state.get("link_imports"))
        downloads = imported or self._download_defaults
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName("cleanupRoot")
        outer.addWidget(self.root)
        column = QVBoxLayout(self.root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._title_bar())
        body = QVBoxLayout()
        body.setContentsMargins(18, 14, 18, 0)
        body.setSpacing(12)
        column.addLayout(body, 1)

        top = QHBoxLayout()
        top.setSpacing(10)
        scope_label = QLabel(tr("范围"))
        scope_label.setObjectName("cleanupFieldLabel")
        top.addWidget(scope_label)
        self.ai_scope = self._scope_box()
        self.ai_scope.setMinimumWidth(180)
        top.addWidget(self.ai_scope)
        top.addStretch(1)
        self.ai_run_button = QPushButton(tr("开始整理"))
        self.ai_run_button.setObjectName("cleanupPrimary")
        self.ai_run_button.clicked.connect(self._do_ai_preview)
        top.addWidget(self.ai_run_button)
        body.addLayout(top)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        local_card, local_rows = self._card("本地整理", "不用 AI · 马上完成")
        self.local_boxes: dict[str, QCheckBox] = {}
        language_ok = self._regroup_available(project)
        for key, label in LOCAL_STEPS:
            box = QCheckBox(tr(label))
            box.setChecked(key == "labels" or (downloads and language_ok))
            if key == "regroup" and not language_ok:
                box.setEnabled(False)
                bind_text(box, "按词重排目前支持英语和西、德、法、葡、意、俄语；中文、日文暂不重排", property="toolTip")
            self.local_boxes[key] = box
            local_rows.addWidget(box)
        local_rows.addStretch(1)
        cards.addWidget(local_card, 0, 0)
        ai_card, ai_rows = self._card("AI 校对", "分批进行 · 长工程也能跑完")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.ai_option_boxes: dict[str, QPushButton] = {}
        defaults = {"glossary", "punctuation"} if downloads else {"fillers", "repeats", "punctuation"}
        for key, label, _options in AI_STEPS:
            chip = QPushButton(tr(label))
            chip.setObjectName("cleanupChip")
            chip.setCheckable(True)
            chip.setChecked(key in defaults)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setProperty("flexibleWidth", True)
            self.ai_option_boxes[key] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        ai_rows.addLayout(chips)
        ai_rows.addStretch(1)
        cards.addWidget(ai_card, 0, 1)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        body.addLayout(cards)

        translation = QHBoxLayout()
        translation.addWidget(QLabel(tr("译文语言")))
        self.translation_target = QComboBox()
        self.translation_target.setObjectName("cleanupTranslationTarget")
        from ..subtitle_rules.language_rules import project_language
        from ..subtitle_rules.subtitle_translation import TARGET_LABELS, targets_for
        for target in targets_for(project_language(project) if project is not None else ""):
            self.translation_target.addItem(TARGET_LABELS[target], target)
        self.translation_target.setCurrentIndex(max(0, self.translation_target.findData("zh-Hans")))
        translation.addWidget(self.translation_target)
        self.translation_button = QPushButton(tr("翻译当前范围…"))
        self.translation_button.setObjectName("cleanupGhost")
        self.translation_button.clicked.connect(self._open_translation)
        bind_text(self.translation_button, "在翻译窗口中确认并开始；译文与原文分开保存，可一次撤销。", property="toolTip")
        translation.addWidget(self.translation_button)
        translation.addStretch(1)
        body.addLayout(translation)

        self.progress_box = QFrame()
        self.progress_box.setObjectName("cleanupProgress")
        strip = QHBoxLayout(self.progress_box)
        strip.setContentsMargins(12, 7, 8, 7)
        strip.setSpacing(12)
        self.status_label = QLabel(tr("选好要做的整理后点「开始整理」"))
        self.status_label.setObjectName("cleanupStatus")
        self.status_label.setWordWrap(True)
        strip.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setObjectName("cleanupBar")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(200)
        self.progress.hide()
        strip.addWidget(self.progress)
        self.cancel_button = QPushButton(tr("取消"))
        self.cancel_button.setObjectName("cleanupLink")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        strip.addWidget(self.cancel_button)
        body.addWidget(self.progress_box)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in FILTERS:
            button = QPushButton(tr(label))
            button.setObjectName("cleanupFilter")
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.setProperty("flexibleWidth", True)
            button.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.filter_buttons[key] = button
            filters.addWidget(button)
        filters.addStretch(1)
        # Kept for callers of the old dialog; the footer count says how many are chosen.
        self.select_all_button = QPushButton(tr("全选"))
        self.select_none_button = QPushButton(tr("全不选"))
        for button, value in ((self.select_all_button, True), (self.select_none_button, False)):
            button.setObjectName("cleanupLink")
            button.clicked.connect(lambda _=False, v=value: self._set_all_preview_checked(v))
            filters.addWidget(button)
        body.addLayout(filters)

        self.preview = _RowList()
        self.preview.setObjectName("cleanupList")
        self.preview.setWordWrap(True)
        self.preview.setResizeMode(QListView.ResizeMode.Adjust)
        self.preview.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.preview.setItemDelegate(_PreviewRowDelegate(self.preview))
        self.preview.itemClicked.connect(self._preview_item_clicked)
        self.preview.itemChanged.connect(self._refresh_status)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.preview, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(18, 10, 18, 14)
        footer.setSpacing(10)
        self.count_label = QLabel("")
        self.count_label.setObjectName("cleanupCount")
        footer.addWidget(self.count_label, 1)
        close = QPushButton(tr("关闭"))
        close.setObjectName("cleanupGhost")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        self.all_button = QPushButton(tr("应用所选"))
        self.all_button.setObjectName("cleanupPrimary")
        self.all_button.clicked.connect(self._do_apply_preview)
        footer.addWidget(self.all_button)
        column.addLayout(footer)

        from ..app.rounded_window import RoundedWindow
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.title_bar], buttons=self.window_buttons)
        self._runner = _Runner(self)
        self._finish_setup()
        self.refresh_theme_palette()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    # ------------------------------------------------------------------ parts
    def _title_bar(self) -> QFrame:
        from ..app.link_download_widgets import icon_label
        from ..app.rounded_window import WindowButtons
        from ..app.ui_zoom import set_size
        bar = QFrame()
        bar.setObjectName("cleanupTitleBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 6, 6, 6)
        row.setSpacing(10)
        mark = icon_label("fa5s.magic", 13, "on_accent", "cleanupMark")
        set_size(mark, fixed_w=26, fixed_h=26)
        row.addWidget(mark)
        title = QLabel(tr(self._title))
        title.setObjectName("cleanupTitle")
        row.addWidget(title, 1)
        self.window_buttons = WindowButtons(self)
        row.addWidget(self.window_buttons)
        self.title_bar = bar
        return bar

    def _card(self, title: str, note: str):
        card = QFrame()
        card.setObjectName("cleanupCard")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(14, 10, 14, 12)
        rows.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(tr(title))
        name.setObjectName("cleanupCardTitle")
        head.addWidget(name)
        hint = QLabel(tr(note))
        hint.setObjectName("cleanupCardNote")
        head.addWidget(hint, 1)
        rows.addLayout(head)
        return card, rows

    @staticmethod
    def _regroup_available(project) -> bool:
        if project is None:
            return False
        from ..media.link_tidy import lexicon_for
        from ..timeline.caption_tidy import _language
        return lexicon_for(_language(project)) is not None

    def refresh_theme_palette(self):
        from ..app.ui_zoom import set_sheet
        from ..design.studio_theme import refresh_secondary_surface_theme
        from ..design.theme_manager import theme_definition, theme_key
        refresh_secondary_surface_theme(self)
        set_sheet(self.root, cleanup_qss(theme_definition(theme_key())))
        self._theme_refresh_pending = False

    def showEvent(self, event):
        if getattr(self, "_theme_refresh_pending", False):
            self.refresh_theme_palette()
        super().showEvent(event)

    # --------------------------------------------------------------- running
    def _current_scope(self) -> str:
        from .studio_text_tools import SCOPE_ALL
        return str(self.ai_scope.currentData() or SCOPE_ALL)

    def _preview_item_clicked(self, item) -> None:
        from shiboken6 import isValid
        if (self._owns_project() and not self._applying and self._preview_binding is not None
                and item is not None and isValid(item)):
            super()._preview_item_clicked(item)

    def _ai_options(self) -> list[str]:
        options = []
        for key, _label, wanted in AI_STEPS:
            if self.ai_option_boxes[key].isChecked():
                options.extend(wanted)
        return options

    def _local_steps(self) -> set[str]:
        return {key for key, box in self.local_boxes.items() if box.isChecked() and box.isEnabled()}

    def _owns_project(self) -> bool:
        from shiboken6 import isValid
        return (not self._closed and isValid(self._page)
                and not getattr(self._page, "_close_requested", False)
                and self._page.session.project is self._project
                and getattr(self._page.session, "generation", None) == self._session_generation)

    def _open_translation(self) -> None:
        if self._cleanup_running or self._applying or not self._owns_project():
            return
        page, project = self._page, self._project
        generation = self._session_generation
        ids = tuple(scope_cue_ids(page, self._current_scope()))
        target = str(self.translation_target.currentData())
        if not ids:
            bind_text(self.status_label, "当前范围没有字幕可翻译。")
            return
        # End the cleanup's modal loop before presenting the existing translator.
        # This is navigation only; sending the request remains its Start button.
        self.accept()
        def open_current():
            if (page.session.project is project
                    and getattr(page.session, "generation", None) == generation
                    and not getattr(page, "_close_requested", False)):
                page._open_translation_dialog(scope="selected", cue_ids=ids, target=target)
        QTimer.singleShot(0, page, open_current)

    def _do_ai_preview(self) -> None:
        project = self._page.session.project
        if project is None or self._cleanup_running or self._applying or not self._owns_project():
            return
        local = self._local_steps()
        options = self._ai_options()
        if not local and not options:
            bind_text(self.status_label, "请至少选择一项整理。")
            return
        settings = {}
        if options:
            from ..app.api_key_explainer import ask_for_key_if_missing
            from ..storage.settings import load_runtime_settings
            loaded = load_runtime_settings()
            settings = loaded[0] if isinstance(loaded, tuple) else loaded
            if ask_for_key_if_missing(self, settings, "polish", status=lambda: bind_text(
                    self.status_label, "AI 清理没有运行：还没填 API Key")):
                return
        self._preview_binding = PreviewBinding.capture(project)
        self._preview_hits = []
        self._local_splices = []
        self._local_used = local
        self._no_word_times = False
        self._clear_rows()
        self._run_generation += 1
        self._cleanup_running = True
        self._cleanup_cancel = threading.Event()
        self.ai_run_button.setEnabled(False)
        self.translation_button.setEnabled(False)
        self.all_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(bool(options))
        self.cancel_button.show()
        bind_text(self.status_label, "正在整理…")
        ids = scope_cue_ids(self._page, self._current_scope())
        self._runner.start(copy.deepcopy(project), ids, local, options, settings)

    def _cancel(self) -> None:
        self._cleanup_cancel.set()
        bind_text(self.status_label, "正在取消…")

    def _message(self, message, *, generation=None) -> None:
        if ((generation is not None and generation != self._run_generation)
                or not self._owns_project()):
            return
        kind = message[0]
        if kind == "progress":
            if not self._cleanup_cancel.is_set():
                state = message[1]
                self.progress.setRange(0, max(1, state["total"]))
                self.progress.setValue(state["done"])
                bind_text(self.status_label, "AI 第 {done} / {total} 批 · 已找到 {found} 处",
                          done=state["done"], total=state["total"], found=state["found"])
            return
        if kind == "local":
            if self._preview_binding is None or not self._preview_binding.matches(self._project):
                self._cleanup_cancel.set()
                return
            plan = message[1]
            self._local_splices = list(plan.splices)
            # Projects imported before word times were kept (before 2026-10-26)
            # can only lose their labels.
            self._no_word_times = "regroup" in self._local_used and plan.captions_before and not plan.word_timed
            self._rebuild_rows()
            return
        # "done" or "failed": the run is over.
        self._cleanup_running = False
        self.ai_run_button.setEnabled(True)
        self.translation_button.setEnabled(True)
        self.progress.hide()
        self.cancel_button.hide()
        if kind == "failed":
            self._refresh_status()
            bind_text(self.status_label, "AI 清理无法调用：{exc}", exc=message[1])
            return
        hits, error = message[1], message[2]
        project = self._page.session.project
        if project is None or self._preview_binding is None or not self._preview_binding.matches(project):
            self._preview_hits, self._local_splices = [], []
            self._clear_rows()
            self._refresh_status()
            bind_text(self.status_label, "工程或字幕已改变，旧校对预览未应用。")
            return
        self._preview_hits = list(hits or [])
        self._rebuild_rows()
        total = self.preview.count()
        if error:
            # A later batch failed; the batches already done stay usable.
            bind_text(self.status_label, "已完成 {done} / {total} 批，找到 {found} 处；其余没有完成：{exc}",
                      done=getattr(hits, "done", 0), total=getattr(hits, "batches", 0), found=len(hits or []),
                      exc=error)
        elif self._cleanup_cancel.is_set():
            bind_text(self.status_label, "已取消；找到的 {count} 处保留在下面。", count=total)
        elif total:
            bind_text(self.status_label, "找到 {count} 处可以整理；勾选要的，再点「应用」。", count=total)
        else:
            bind_text(self.status_label, "没有需要整理的地方。")
        if self._no_word_times and not error:
            self.status_label.setText(self.status_label.text() + " "
                                      + tr("这些字幕导入时没有保存词时间，不能按词重排。"))

    # ------------------------------------------------------------------ rows
    def _fill_preview(self, hits, binding=None) -> None:
        """AI suggestions alone (callers of the old dialog)."""
        self._preview_hits = list(hits)
        self._preview_binding = binding or PreviewBinding.capture(self._page.session.project)
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        project = self._page.session.project
        colors = _preview_colors()
        from ..design.theme_manager import theme_definition, theme_key
        theme = theme_definition(theme_key())
        texts = {cue.id: cue.text for cue in project.cues} if project is not None else {}
        rows = []
        for index, splice in enumerate(self._local_splices):
            rows.append(self._local_row(index, splice, colors, theme))
        for index, hit in enumerate(self._preview_hits):
            body = diff_html(texts.get(hit.cue_id, hit.original), hit.replacement, colors)
            rows.append((hit.start_ms, "text", _ai_kind(hit.reason), body, ("ai", index), hit.cue_id,
                         hit.default_selected))
        rows.sort(key=lambda row: row[0])
        # Rows ticked or unticked while the AI was still running keep their state.
        chosen = {tuple(self.preview.item(i).data(ROW_ROLE)): self.preview.item(i).checkState()
                  for i in range(self.preview.count())}
        self.preview.setUpdatesEnabled(False)
        self.preview.blockSignals(True)
        try:
            self.preview.clear()
            for start, kind, label, body, ref, cue_id, checked in rows:
                item = QListWidgetItem("")
                pill = (f'<span style="background-color:{theme.selected}; color:{theme.text};">'
                        f'&nbsp;{html.escape(tr(label))}&nbsp;</span>')
                item.setData(PREVIEW_HTML_ROLE, f'<span style="color:{colors["muted"]};">{clock_ms(start)}</span>'
                                                f'&nbsp;&nbsp;{pill}&nbsp;&nbsp;{body}')
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(chosen.get(tuple(ref),
                                              Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked))
                item.setData(Qt.ItemDataRole.UserRole, cue_id)
                item.setData(ROW_ROLE, ref)
                item.setData(KIND_ROLE, kind)
                item.setData(TIME_ROLE, start)
                self.preview.addItem(item)
        finally:
            self.preview.blockSignals(False)
            self.preview.setUpdatesEnabled(True)
        self._apply_filter()
        self._refresh_status()

    def _local_row(self, index, splice, colors, theme):
        from ..media.link_tidy import strip_labels
        removed = splice.removed
        old = [cue.text for cue in removed]
        new = [cue.text for cue in splice.inserted]
        stripped = [strip_labels(text) for text in old]
        labels = sum(count for _text, _speaker, count in stripped)
        muted = colors["muted"]
        ref = ("local", index)
        if new == [text for text, _speaker, _count in stripped if text]:
            # Only labels go: the change shown in place.
            body = diff_html(" / ".join(old), " / ".join(new), colors)
            if not new:
                body += f'&nbsp;<span style="color:{muted};">{html.escape(tr("（整行删除）"))}</span>'
            return removed[0].start_ms, "delete", "删除", body, ref, removed[0].id, True
        marker = f'&nbsp;<span style="color:{theme.accent_text}; font-weight:700;">｜</span>&nbsp;'
        body = marker.join(html.escape(text) for text in new)
        note = tr("{before} 条 → {after} 条", before=len(removed), after=len(new))
        if labels:
            note += " · " + tr("删除 {count} 处标注", count=labels)
        body += f'&nbsp;&nbsp;<span style="color:{muted};">{html.escape(note)}</span>'
        return removed[0].start_ms, "break", "断句", body, ref, removed[0].id, True

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for name, button in self.filter_buttons.items():
            button.setChecked(name == key)
        self._apply_filter()

    def _apply_filter(self) -> None:
        for row in range(self.preview.count()):
            item = self.preview.item(row)
            item.setHidden(self._filter != "all" and item.data(KIND_ROLE) != self._filter)

    def _checked_rows(self):
        for row in range(self.preview.count()):
            item = self.preview.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                yield item.data(ROW_ROLE)

    def _checked_hits(self):
        return [self._preview_hits[index] for kind, index in self._checked_rows() if kind == "ai"]

    def _checked_local(self):
        return [self._local_splices[index] for kind, index in self._checked_rows() if kind == "local"]

    def _set_all_preview_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.preview.count()):
            self.preview.item(row).setCheckState(state)

    def _refresh_status(self, *_args) -> None:
        if not hasattr(self, "count_label"):
            return
        total = self.preview.count()
        chosen = sum(1 for _ in self._checked_rows())
        counts = {"all": total, "break": 0, "delete": 0, "text": 0}
        for row in range(total):
            counts[self.preview.item(row).data(KIND_ROLE)] += 1
        for key, label in FILTERS:
            self.filter_buttons[key].setText(f"{tr(label)} {counts[key]}" if total else tr(label))
        self.all_button.setEnabled(bool(chosen) and not self._cleanup_running and not self._applying and not self._closed)
        if chosen:
            bind_text(self.all_button, "应用 {count} 处", count=chosen)
        else:
            bind_text(self.all_button, "应用所选")
        if total:
            bind_text(self.count_label, "已选 {chosen} / {total} · 一步撤销", chosen=chosen, total=total)
        else:
            self.count_label.setText("")
        for button in (self.select_all_button, self.select_none_button):
            button.setVisible(total > 0)

    # ------------------------------------------------------------------ apply
    @observed('cue.ai_apply')
    def _do_apply_preview(self) -> None:
        self._apply_checked()

    def _apply_checked(self) -> None:
        from ..diagnostics.event_log import emit, exception_info
        from ..projects.studio_runtime_state import state_for
        if self._applying or self._cleanup_running or not self._owns_project():
            emit("cleanup.apply", stage="rejected_lifecycle", result="skipped")
            return
        project = self._page.session.project
        if self._preview_binding is None or project is None or not self._preview_binding.matches(project):
            self.status_label.setText(tr("工程或文字已改变，请重新预览；本次没有修改字幕。"))
            return
        hits = self._checked_hits()
        splices = self._checked_local()
        if not hits and not splices:
            bind_text(self.status_label, "没有可应用的预览")
            return
        if occurrence_conflicts(hits):
            self.status_label.setText(tr("同一位置选中了不同候选，请只保留一个后再应用；本次没有修改字幕。"))
            return
        binding = self._preview_binding
        self._applying = True
        self.all_button.setEnabled(False)
        self.ai_run_button.setEnabled(False)
        self.translation_button.setEnabled(False)
        try:
            emit("cleanup.apply", stage="validate", result="started", project_id=project.project_id,
                 revision_before=state_for(project).revision, ai_changes=len(hits), local_changes=len(splices))
            from ..timeline.caption_tidy import prepare_cleanup_command
            values = values_from_occurrences(project, hits, strict=True)
            command = prepare_cleanup_command(
                project, values, splices, self._local_used, getattr(self._page, "_changed", None), label=tr(self._title))
            total, cue_count = len(hits) + len(splices), len(values)
            if not self._owns_project() or not binding.matches(project):
                raise ValueError(tr("工程或文字已改变，整批清理没有应用。"))
            self._preview_binding = None  # Reentrant/rapid apply cannot submit these rows again.
            emit("cleanup.apply", stage="push", result="started", project_id=project.project_id)
            outcome = command.outcome
            self._page.session.undo_stack.push(command)
            if not outcome["applied"]:
                raise outcome["error"] or RuntimeError(tr("清理事务没有提交。"))
            emit("cleanup.apply", stage="committed", result="completed", project_id=project.project_id,
                 revision_after=state_for(project).revision)
            self._after_apply(total, cue_count)
        except Exception as exc:
            emit("cleanup.apply", stage="failed", result="failed", level="ERROR", exception=exception_info(exc))
            if self._owns_project() and binding.matches(project):
                self._preview_binding = binding
            bind_text(self.status_label, "清理没有完成：{error}", error=str(exc))
        finally:
            self._applying = False
            if self._owns_project():
                self.ai_run_button.setEnabled(True)
                self.translation_button.setEnabled(True)
                self._refresh_status()

    def _clear_rows(self) -> None:
        # Clear item/model handles without callbacks inspecting half-deleted rows.
        blocker = QSignalBlocker(self.preview)
        self.preview.clear()
        del blocker

    def _after_apply(self, total: int, cue_count: int) -> None:
        self._preview_hits, self._local_splices = [], []
        self._preview_binding = None
        self._clear_rows()
        self._refresh_status()
        from ..diagnostics.event_log import emit
        emit("cleanup.apply", stage="rows_cleared", result="completed", applied_count=total)
        if total:
            bind_text(self.status_label, "已应用 {count} 处（可 Ctrl+Z 一次撤销）", count=total)
            hint = getattr(self._page, "_show_studio_hint", None)
            if callable(hint):
                hint(tr("AI 清理已应用 {count} 处（可 Ctrl+Z 一次撤销）", count=total))

    def reject(self) -> None:
        self._cleanup_cancel.set()
        super().reject()
