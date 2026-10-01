"""Studio subtitle text toolbox: find/replace, tidy, glossary, AI cleanup."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .i18n import apply_ui_language, current_language
from .studio_commands import BatchReplaceTextCommand, MutationOrigin, SetCueFieldsCommand
from .studio_text_tools import (
    AI_CLEANUP_OPTIONS,
    PAUSE_KEEP_LONG,
    PAUSE_LIGHT_TO_SPACE,
    PAUSE_SKIP,
    SCOPE_ALL,
    SCOPE_CURRENT,
    SCOPE_RANGE,
    SCOPE_SELECTED,
    SCOPE_SPEAKER,
    SCOPE_TRACK,
    TextOccurrence,
    find_occurrences,
    format_preview_row,
    glossary_occurrences,
    request_text_cleanup,
    scope_cue_ids,
    tidy_occurrences,
    values_from_occurrences,
)

from .i18n import bind_text

from .i18n import tr


def _locked_ids(page) -> list[str]:
    project = page.session.project if page is not None else None
    if project is None:
        return []
    state = getattr(project, "studio_state", {}) or {}
    raw = state.get("locked_cue_ids") if isinstance(state, dict) else []
    return [str(item) for item in (raw or [])]


def _scope_cue_ids(page, scope: str) -> list[str]:
    return scope_cue_ids(page, scope)


def _match_counts(page, cue_ids, needle: str) -> dict[str, int]:
    project = page.session.project
    if project is None or not needle:
        return {}
    hits = find_occurrences(project, cue_ids, needle, needle, case_sensitive=True)
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.cue_id] = counts.get(hit.cue_id, 0) + 1
    return counts


def _search_replace_learning(page, needle: str, replacement: str) -> dict | None:
    """Manual find & replace is learnable human evidence; regex patterns are not."""
    if page is None or getattr(page, "cue_controller", None) is None:
        return None
    if not needle or not replacement or needle == replacement:
        return None
    from .glossary_learning import new_evidence_token

    return {
        "token": new_evidence_token(),
        "pair": (needle, replacement),
        "origin": "search_replace",
    }


def replace_next(page, *, needle: str, replacement: str, scope: str) -> bool:
    """Replace the next occurrence at/after the current cue (wraps around)."""
    if not needle or page.session.project is None:
        return False
    cue_ids = _scope_cue_ids(page, scope)
    hits = find_occurrences(page.session.project, cue_ids, needle, replacement, case_sensitive=True)
    if not hits:
        return False
    current = page.session.selected_cue_id
    ordered = list(dict.fromkeys(hit.cue_id for hit in hits))
    if current in ordered:
        target_id = current
    else:
        start = ordered.index(current) if current in ordered else -1
        target_id = ordered[(start + 1) % len(ordered)]
    cue = next(item for item in page.session.project.cues if item.id == target_id)
    page.session.undo_stack.push(SetCueFieldsCommand(
        page.session.project,
        target_id,
        {"text": cue.text.replace(needle, replacement, 1)},
        text="批量替换：下一条",
        changed=page._changed,
        origin=MutationOrigin.SEARCH_REPLACE,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=_search_replace_learning(page, needle, replacement),
    ))
    page.select_cue(target_id)
    return True


def replace_all(page, *, needle: str, replacement: str, scope: str) -> tuple[int, int]:
    """Replace every occurrence in scope; one undo step."""
    if not needle or page.session.project is None:
        return 0, 0
    cue_ids = _scope_cue_ids(page, scope)
    hits = find_occurrences(page.session.project, cue_ids, needle, replacement, case_sensitive=True)
    values = values_from_occurrences(page.session.project, hits)
    if not values:
        return 0, 0
    page.session.undo_stack.push(BatchReplaceTextCommand(
        page.session.project,
        values,
        needle=needle,
        changed=page._changed,
        origin=MutationOrigin.SEARCH_REPLACE,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=_search_replace_learning(page, needle, replacement),
    ))
    return len(hits), len(values)


def apply_occurrences(
    page,
    hits: list[TextOccurrence],
    *,
    title: str,
    learn_pair: tuple[str, str] | None = None,
) -> tuple[int, int]:
    if page.session.project is None or not hits:
        return 0, 0
    values = values_from_occurrences(page.session.project, hits)
    if not values:
        return 0, 0
    origin = MutationOrigin.SEARCH_REPLACE if learn_pair else MutationOrigin.SYSTEM
    learning_meta = None
    if learn_pair is not None:
        learning_meta = _search_replace_learning(page, learn_pair[0], learn_pair[1])
    page.session.undo_stack.push(BatchReplaceTextCommand(
        page.session.project,
        values,
        needle=title,
        changed=page._changed,
        origin=origin,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=learning_meta,
    ))
    return len(hits), len(values)


class FindReplaceDialog(QDialog):
    """Find / replace / tidy / AI cleanup, always previewed, one undo step."""

    def __init__(self, page, parent=None):
        super().__init__(parent or page)
        self._page = page
        bind_text(self, '字幕文本工具', property='windowTitle')
        self.setObjectName("toolDialog")
        self.setMinimumSize(680, 540)
        self.resize(800, 640)
        self._preview_hits: list[TextOccurrence] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        from .studio_theme import apply_secondary_surface_theme

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.tabs.addTab(self._find_tab(), "查找 / 替换")
        self.tabs.addTab(self._tidy_tab(), "文本整理")
        self.tabs.addTab(self._ai_tab(), "AI 清理")
        layout.addWidget(self.tabs, 0)

        results = QFrame()
        results.setObjectName("findResultFrame")
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(10, 8, 10, 8)
        results_layout.setSpacing(6)
        self.status_label = QLabel("匹配结果")
        self.status_label.setObjectName("findResultTitle")
        self.status_label.setWordWrap(True)
        results_layout.addWidget(self.status_label)
        self.preview = QListWidget()
        self.preview.setObjectName("findResultList")
        self.preview.setMinimumHeight(280)
        self.preview.setSpacing(4)
        self.preview.setAlternatingRowColors(True)
        self.preview.setWordWrap(True)
        self.preview.itemClicked.connect(self._preview_item_clicked)
        results_layout.addWidget(self.preview, 1)
        layout.addWidget(results, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._live_search)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览")
        self.preview_button.setMinimumHeight(34)
        self.preview_button.clicked.connect(self._do_preview)
        self.next_button = QPushButton("替换下一个")
        self.next_button.setMinimumHeight(34)
        self.next_button.clicked.connect(self._do_replace_next)
        self.all_button = QPushButton("应用所选预览")
        self.all_button.setProperty("studioPrimary", True)
        bind_text(self.preview_button, '立即刷新预览（输入时会自动搜索）', property='toolTip')
        self.all_button.setMinimumHeight(34)
        self.all_button.clicked.connect(self._do_apply_preview)
        close_button = QPushButton("关闭")
        close_button.setMinimumHeight(34)
        close_button.clicked.connect(self.reject)
        actions.addWidget(self.preview_button)
        actions.addStretch(1)
        actions.addWidget(self.next_button)
        actions.addWidget(self.all_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

        apply_secondary_surface_theme(self)
        apply_ui_language(self, current_language())
        self._refresh_status()
        self.tabs.currentChanged.connect(self._tab_changed)

    def _scope_box(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("当前字幕", SCOPE_CURRENT)
        combo.addItem("选中字幕", SCOPE_SELECTED)
        combo.addItem("当前说话人", SCOPE_SPEAKER)
        combo.addItem("当前轨道", SCOPE_TRACK)
        combo.addItem("当前时间范围", SCOPE_RANGE)
        combo.addItem("全工程", SCOPE_ALL)
        combo.setCurrentIndex(combo.findData(SCOPE_ALL))
        selected_count = len(self._page.selected_cue_ids()) if self._page is not None else 0
        if selected_count < 2:
            combo.model().item(combo.findData(SCOPE_SELECTED)).setEnabled(False)
        return combo

    def _find_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 6, 4, 4)
        layout.setSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("查找"), 0, 0)
        self.find_edit = QLineEdit()
        bind_text(self.find_edit, '要查找的文字，例如：尼奈', property='placeholderText')
        self.find_edit.setMinimumHeight(32)
        self.find_edit.textChanged.connect(self._queue_live_search)
        grid.addWidget(self.find_edit, 0, 1)
        grid.addWidget(QLabel("替换"), 1, 0)
        self.replace_edit = QLineEdit()
        bind_text(self.replace_edit, '替换为，例如：她', property='placeholderText')
        self.replace_edit.setMinimumHeight(32)
        self.replace_edit.textChanged.connect(self._queue_live_search)
        grid.addWidget(self.replace_edit, 1, 1)
        grid.addWidget(QLabel("范围"), 0, 2)
        self.scope_combo = self._scope_box()
        self.scope_combo.currentIndexChanged.connect(lambda *_args: self._queue_live_search())
        grid.addWidget(self.scope_combo, 0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(4)
        self.case_box = QCheckBox("区分大小写")
        self.word_box = QCheckBox("全词匹配")
        self.regex_box = QCheckBox("正则表达式")
        self.body_box = QCheckBox("仅正文")
        self.lock_box = QCheckBox("不修改锁定字幕")
        self.lock_box.setChecked(True)
        for index, box in enumerate(
            (self.case_box, self.word_box, self.regex_box, self.body_box, self.lock_box)
        ):
            box.toggled.connect(self._queue_live_search)
            options.addWidget(box, index // 3, index % 3)
        layout.addLayout(options)
        return tab

    def _tidy_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        row_scope = QHBoxLayout()
        row_scope.addWidget(QLabel("范围"))
        self.tidy_scope = self._scope_box()
        row_scope.addWidget(self.tidy_scope, 1)
        layout.addLayout(row_scope)
        punct = QHBoxLayout()
        punct.addWidget(QLabel("标点统一"))
        self.punct_combo = QComboBox()
        self.punct_combo.addItem("不处理", "")
        self.punct_combo.addItem("中文标点", "cn")
        self.punct_combo.addItem("英文标点", "en")
        self.punct_combo.addItem("全角 / 半角（半角化）", "halfwidth")
        punct.addWidget(self.punct_combo, 1)
        layout.addLayout(punct)
        self.whitespace_box = QCheckBox("空白整理（去多余空格 / 合并连续空格 / 去首尾空格）")
        self.whitespace_box.setChecked(True)
        layout.addWidget(self.whitespace_box)
        pause = QHBoxLayout()
        pause.addWidget(QLabel("停顿整理"))
        self.pause_combo = QComboBox()
        self.pause_combo.addItem("不处理", PAUSE_SKIP)
        self.pause_combo.addItem("口语轻停顿 → 空格", PAUSE_LIGHT_TO_SPACE)
        self.pause_combo.addItem("长停顿 → 保留标点", PAUSE_KEEP_LONG)
        pause.addWidget(self.pause_combo, 1)
        layout.addLayout(pause)
        self.glossary_box = QCheckBox("术语标准化（词库 canonical form）")
        self.glossary_box.setChecked(True)
        layout.addWidget(self.glossary_box)
        return tab

    def _ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        note = QLabel("AI 只建议文本清理，不会偷偷改字幕意思。每条都可接受或拒绝。")
        note.setWordWrap(True)
        note.setObjectName("cardMeta")
        layout.addWidget(note)
        row_scope = QHBoxLayout()
        row_scope.addWidget(QLabel("范围"))
        self.ai_scope = self._scope_box()
        row_scope.addWidget(self.ai_scope, 1)
        layout.addLayout(row_scope)
        self.ai_option_boxes: dict[str, QCheckBox] = {}
        ai_grid = QGridLayout()
        ai_grid.setHorizontalSpacing(12)
        ai_grid.setVerticalSpacing(4)
        for index, (key, label) in enumerate(AI_CLEANUP_OPTIONS):
            box = QCheckBox(label)
            box.setChecked(key in {"fillers", "repeats", "punctuation"})
            self.ai_option_boxes[key] = box
            ai_grid.addWidget(box, index // 2, index % 2)
        layout.addLayout(ai_grid)
        ai_actions = QHBoxLayout()
        self.ai_run_button = QPushButton("生成 AI 预览")
        self.ai_run_button.clicked.connect(self._do_ai_preview)
        self.accept_item_button = QPushButton("接受此条")
        self.accept_item_button.clicked.connect(self._accept_selected)
        self.reject_item_button = QPushButton("拒绝此条")
        self.reject_item_button.clicked.connect(self._reject_selected)
        self.accept_all_button = QPushButton("全部接受")
        self.accept_all_button.clicked.connect(lambda: self._set_all_preview_checked(True))
        self.reject_all_button = QPushButton("全部拒绝")
        self.reject_all_button.clicked.connect(lambda: self._set_all_preview_checked(False))
        for button in (
            self.ai_run_button, self.accept_item_button, self.reject_item_button,
            self.accept_all_button, self.reject_all_button,
        ):
            ai_actions.addWidget(button)
        layout.addLayout(ai_actions)
        return tab

    def _current_scope(self) -> str:
        tab = self.tabs.currentIndex()
        combo = self.scope_combo if tab == 0 else (self.tidy_scope if tab == 1 else self.ai_scope)
        return str(combo.currentData() or SCOPE_ALL)

    def _fill_preview(self, hits: list[TextOccurrence]) -> None:
        self._preview_hits = list(hits)
        self.preview.clear()
        for hit in hits:
            item = QListWidgetItem(format_preview_row(hit))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, hit.cue_id)
            self.preview.addItem(item)
        if hits:
            bind_text(self.status_label, '找到 {value0} 处', value0=len(hits))
        elif self.tabs.currentIndex() == 0 and not self.find_edit.text().strip():
            bind_text(self.status_label, '输入查找文字后显示匹配数量')
        else:
            bind_text(self.status_label, '没有匹配的字幕')

    def _preview_item_clicked(self, item: QListWidgetItem) -> None:
        cue_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if cue_id and self._page is not None:
            self._page.select_cue(cue_id)

    def _checked_hits(self) -> list[TextOccurrence]:
        hits = []
        for index, hit in enumerate(self._preview_hits):
            item = self.preview.item(index)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                hits.append(hit)
        return hits

    def _set_all_preview_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.preview.count()):
            item = self.preview.item(index)
            if item is not None:
                item.setCheckState(state)

    def _queue_live_search(self, *_args) -> None:
        self._refresh_status()
        self._search_timer.start()

    def _live_search(self) -> None:
        if self.tabs.currentIndex() == 0:
            self._do_preview()

    def _tab_changed(self, index: int) -> None:
        if index == 0:
            self._queue_live_search()

    def _refresh_status(self, *_args) -> None:
        needle = self.find_edit.text()
        enabled = bool(needle) and self._page.session.project is not None
        self.next_button.setEnabled(enabled)
        self.all_button.setEnabled(True)
        if self.tabs.currentIndex() != 0:
            return
        if not enabled:
            bind_text(self.status_label, '输入查找文字后显示匹配数量')
            return
        hits = find_occurrences(
            self._page.session.project,
            _scope_cue_ids(self._page, self._current_scope()),
            needle,
            self.replace_edit.text(),
            case_sensitive=self.case_box.isChecked(),
            whole_word=self.word_box.isChecked(),
            regex=self.regex_box.isChecked(),
            body_only=self.body_box.isChecked(),
            skip_locked=self.lock_box.isChecked(),
            locked_ids=_locked_ids(self._page),
        )
        if not hits:
            bind_text(self.status_label, '没有匹配的字幕')
            self.next_button.setEnabled(False)
            return
        cues = {hit.cue_id for hit in hits}
        bind_text(self.status_label, '匹配 {value0} 条字幕 · {value1} 处', value0=len(cues), value1=len(hits))

    def _do_preview(self) -> None:
        project = self._page.session.project
        if project is None:
            return
        tab = self.tabs.currentIndex()
        cue_ids = _scope_cue_ids(self._page, self._current_scope())
        locked = _locked_ids(self._page)
        if tab == 0:
            if not self.find_edit.text().strip():
                self._fill_preview([])
                return
            hits = find_occurrences(
                project, cue_ids, self.find_edit.text(), self.replace_edit.text(),
                case_sensitive=self.case_box.isChecked(),
                whole_word=self.word_box.isChecked(),
                regex=self.regex_box.isChecked(),
                body_only=self.body_box.isChecked(),
                skip_locked=self.lock_box.isChecked(),
                locked_ids=locked,
            )
        elif tab == 1:
            hits = tidy_occurrences(
                project, cue_ids,
                punctuation=str(self.punct_combo.currentData() or ""),
                whitespace=self.whitespace_box.isChecked(),
                pause=str(self.pause_combo.currentData() or PAUSE_SKIP),
                skip_locked=True, locked_ids=locked,
            )
            if self.glossary_box.isChecked():
                hits.extend(glossary_occurrences(project, cue_ids, locked_ids=locked))
        else:
            bind_text(self.status_label, '请使用「生成 AI 预览」')
            return
        self._fill_preview(hits)

    def _do_replace_next(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        ok = replace_next(
            self._page, needle=needle, replacement=self.replace_edit.text(),
            scope=self._current_scope(),
        )
        if ok:
            self._page._show_studio_hint(tr('已替换下一条（可 Ctrl+Z 撤销）'))
        self._refresh_status()

    def _do_replace_all(self) -> None:
        self._do_preview()
        self._do_apply_preview()

    def _do_apply_preview(self) -> None:
        hits = self._checked_hits()
        if not hits:
            bind_text(self.status_label, '没有可应用的预览')
            return
        learn_pair = None
        if self.tabs.currentIndex() == 0 and not self.regex_box.isChecked():
            # Only the plain find & replace tab is manual term evidence;
            # regex patterns, tidy rules and AI cleanup are not corrections.
            needle = self.find_edit.text().strip()
            replacement = self.replace_edit.text().strip()
            if needle and replacement:
                learn_pair = (needle, replacement)
        total, cue_count = apply_occurrences(
            self._page, hits,
            title=self.find_edit.text() or "字幕文本工具",
            learn_pair=learn_pair,
        )
        if total:
            self._page._show_studio_hint(tr('已替换 {value0} 处，涉及 {value1} 条字幕（可 Ctrl+Z 一次撤销）', value0=total, value1=cue_count))
        self._do_preview()
        self._refresh_status()

    def _do_ai_preview(self) -> None:
        project = self._page.session.project
        if project is None:
            return
        options = [key for key, box in self.ai_option_boxes.items() if box.isChecked()]
        bind_text(self.status_label, '正在调用已配置的 AI…')
        try:
            hits = request_text_cleanup(
                project,
                _scope_cue_ids(self._page, self._current_scope()),
                options,
            )
        except Exception as exc:
            bind_text(self.status_label, 'AI 清理无法调用：{exc}', exc=exc)
            return
        self._fill_preview(hits)

    def _accept_selected(self) -> None:
        item = self.preview.currentItem()
        if item is not None:
            item.setCheckState(Qt.CheckState.Checked)

    def _reject_selected(self) -> None:
        item = self.preview.currentItem()
        if item is not None:
            item.setCheckState(Qt.CheckState.Unchecked)
