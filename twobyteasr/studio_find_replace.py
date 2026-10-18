"""Studio subtitle text toolbox: find/replace, tidy, glossary, AI cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import copy

from PySide6.QtCore import Qt, QTimer, QThread, Signal
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
    occurrence_conflicts,
)

from .i18n import bind_text

from .i18n import tr


@dataclass(frozen=True)
class PreviewBinding:
    project: object
    project_id: str
    revision: int
    fingerprint: str
    document_fingerprint: str

    @staticmethod
    def _document_payload(project):
        # asdict reads persisted edit data without to_dict's validate/persist
        # side effects. Runtime selection/render caches are not dataclass
        # fields; the following known bookmarks are view state only.
        payload = asdict(project)
        payload.pop('updated_at', None)
        state = payload.get('studio_state', {})
        for key in ('review_risks', 'last_selected_cue', 'playhead_ms', 'zoom',
                'scroll_ms', 'bilingual_mode', 'follow_playhead',
                'timeline_snap_enabled', 'timeline_tool',
                'timeline_track_heights', 'layout'):
            state.pop(key, None)
        return payload

    @classmethod
    def _document_fingerprint(cls, project):
        return hashlib.sha256(json.dumps(cls._document_payload(project), ensure_ascii=False,
            sort_keys=True).encode('utf8')).hexdigest()

    @staticmethod
    def _fingerprint(project):
        rows = [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues]
        # Ordinary previews retain their existing object/revision/text fence;
        # relinking/replacing source media also invalidates pending decisions.
        media = (project.media.path, project.media.fingerprint,
                 [(a.asset_id,a.canonical_source,getattr(a,'fingerprint',''))
                  for a in project.media_pool])
        return hashlib.sha256(json.dumps((media,rows), ensure_ascii=False).encode('utf8')).hexdigest()

    @classmethod
    def capture(cls, project):
        from .studio_runtime_state import state_for
        return cls(project, project.project_id, state_for(project).revision,
            cls._fingerprint(project), cls._document_fingerprint(project))

    def matches(self, project):
        from .studio_runtime_state import state_for
        return (project is self.project and project.project_id == self.project_id
                and state_for(project).revision == self.revision
                and self._fingerprint(project) == self.fingerprint
                and self._document_fingerprint(project) == self.document_fingerprint)


class _GlossaryReviewThread(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, project, cue_ids, snapshot, settings, parent):
        super().__init__(parent)
        from .service import CancellationToken
        self.token = CancellationToken()
        self.inputs = (project, cue_ids, snapshot, settings)

    def run(self):
        try:
            from .service import preview_glossary_correction
            result = preview_glossary_correction(*self.inputs, cancel_token=self.token)
            self.token.raise_if_cancelled()
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


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
    binding: PreviewBinding | None = None,
    glossary_ids=None,
    review_receipt=None,
) -> tuple[int, int]:
    if page.session.project is None or not hits:
        return 0, 0
    if binding is not None and not binding.matches(page.session.project):
        return 0, 0
    if occurrence_conflicts(hits):
        return 0, 0
    if review_receipt is not None:
        review_receipt={**copy.deepcopy(review_receipt),'applied_changes':len(hits),
            'selected_changes':[{'cue_id':hit.cue_id,'span':list(hit.span),'from':hit.original,
                'to':hit.replacement,'source':hit.source,'default_selected':hit.default_selected} for hit in hits]}
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
        glossary_ids=glossary_ids,
        review_receipt=review_receipt,
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
        self._preview_binding = None
        self._preview_library_ids = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self._glossary_review_worker = None
        self._review_close_pending = False
        self._review_generation = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        from .studio_theme import apply_secondary_surface_theme

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.tabs.addTab(self._find_tab(), "查找 / 替换")
        self.tabs.addTab(self._tidy_tab(), "文本整理")
        self.tabs.addTab(self._ai_tab(), "AI 清理")
        self.tabs.addTab(self._terms_tab(), "应用术语库")
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
        self.preview.itemChanged.connect(self._refresh_status)
        self.preview.currentItemChanged.connect(self._update_association_button)
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
        if selected_count < 1:
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
        self.project_entity_box = QCheckBox(tr('记录为本工程已确认实体'))
        bind_text(self.project_entity_box, '确认只用于本素材；其它出现位置仍需逐项预览，不写入全局词库。', property='toolTip')
        layout.addWidget(self.project_entity_box)
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
        combo = (self.scope_combo, self.tidy_scope, self.ai_scope, self.terms_scope)[tab]
        return str(combo.currentData() or SCOPE_ALL)

    def _terms_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        note = QLabel("使用当前工程词库；预览后可取消个别修改，确认后可一次撤销。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.terms_scope = self._scope_box()
        self.terms_scope.setCurrentIndex(self.terms_scope.findData(SCOPE_ALL))
        layout.addWidget(self.terms_scope)
        self.terms_libraries = QListWidget()
        self.terms_libraries.setMaximumHeight(100)
        project = self._page.session.project
        if project:
            import subtitle_core as legacy
            catalog = getattr(legacy, 'glossary_catalog', lambda: [])()
            for row in catalog:
                identity, display = row['id'], row['name']
                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, identity)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if identity in project.glossary_ids else Qt.Unchecked)
                self.terms_libraries.addItem(item)
        if not self.terms_libraries.count():
            note.setText("尚无词库。请先在术语库中建立规范词或已确认纠错。")
        elif project and not project.glossary_ids:
            note.setText("当前工程尚未启用词库。勾选词库并预览，确认应用后保存到本工程。")
        layout.addWidget(self.terms_libraries)
        self.terms_ai_button = QPushButton("按当前词库生成 AI 校对预览")
        self.terms_ai_button.setToolTip("复用原始转写，以当前所选词库和已配置校对模型生成差异；确认后应用，可一次撤销。")
        self.terms_ai_button.clicked.connect(self._do_terms_ai_preview)
        layout.addWidget(self.terms_ai_button)
        self.project_entities_button = QPushButton(tr('复核本工程已确认实体'))
        self.project_entities_button.clicked.connect(self._do_project_entities_preview)
        layout.addWidget(self.project_entities_button)
        self.associate_button = QPushButton('确认所选名称关联…')
        self.associate_button.setObjectName('glossaryAssociateButton')
        self.associate_button.setEnabled(False)
        self.associate_button.clicked.connect(self._open_term_association)
        layout.addWidget(self.associate_button)
        self.terms_libraries.itemChanged.connect(self._invalidate_term_preview)
        self.terms_scope.currentIndexChanged.connect(self._invalidate_term_preview)
        return tab

    def _invalidate_term_preview(self, *_args):
        self._review_generation += 1
        self._preview_binding = None
        self._preview_hits = []
        self._preview_library_ids = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        if hasattr(self, 'preview'):
            self.preview.clear()
            self.status_label.setText("词库或范围已改变，请重新预览。")
            self._refresh_status()

    def _do_project_entities_preview(self):
        from .project_entity_confirmations import confirmed_entity_occurrences
        project = self._page.session.project
        if project is None:
            return
        self._preview_snapshot_digest = None
        self._preview_library_ids = tuple(project.glossary_ids)
        self._glossary_review_receipt = {'kind': 'project_entity_confirmation_review',
            'source': 'user_confirmed', 'media_fingerprint': project.media.fingerprint,
            'audio_verified_by_model': False}
        cue_ids = set(_scope_cue_ids(self._page,self._current_scope()))
        conflicts = []
        hits = confirmed_entity_occurrences(project, locked_ids=_locked_ids(self._page),diagnostics=conflicts)
        self._fill_preview([h for h in hits if h.cue_id in cue_ids],
            PreviewBinding.capture(project))
        if conflicts:
            bind_text(self.status_label, '同一实体有不同确认写法，已跳过：{aliases}。请逐条确认。', aliases='、'.join(conflicts))

    def _fill_preview(self, hits: list[TextOccurrence], binding=None) -> None:
        self._preview_hits = list(hits)
        self._preview_binding = binding or PreviewBinding.capture(self._page.session.project)
        self.preview.clear()
        for hit in hits:
            item = QListWidgetItem(format_preview_row(hit))
            if self.tabs.currentIndex() == 3:
                cue = next((c for c in self._page.session.project.cues if c.id == hit.cue_id), None)
                if cue is not None:
                    changed = cue.text[:hit.span[0]] + hit.replacement + cue.text[hit.span[1]:]
                    reason = {'case_normalization':'大小写规范化','confirmed_alias':'已确认别名/纠错',
                              'user_confirmed':'用户确认（本工程）'}.get(hit.reason, hit.reason)
                    state = ('已确认规范化' if hit.source=='local_confirmed' else 'AI 自动通过（已选）') if hit.default_selected else '待确认（默认未选）'
                    extra = ' · '.join(x for x in (hit.evidence, hit.missing_evidence) if x)
                    item.setText(f"{cue.text} → {changed}\n命中：{hit.original} → {hit.replacement} · {reason} · {state}" + ('\n'+extra if extra else ''))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if hit.default_selected else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, hit.cue_id)
            item.setData(Qt.ItemDataRole.UserRole+1, {'surface':hit.original,'canonical_options':[hit.replacement],
                'state':'proposal','cue_id':hit.cue_id})
            self.preview.addItem(item)
        if hits:
            bind_text(self.status_label, '找到 {value0} 处', value0=len(hits))
        elif self.tabs.currentIndex() == 0 and not self.find_edit.text().strip():
            bind_text(self.status_label, '输入查找文字后显示匹配数量')
        else:
            bind_text(self.status_label, '没有匹配的字幕')
        self._refresh_status()

    def _show_terms_result(self, result, binding, snapshot, identities):
        self._fill_preview(list(result.hits), binding)
        self._preview_library_ids = tuple(identities)
        self._preview_snapshot_digest = snapshot.digest
        self._glossary_review_receipt = result.receipt
        for row in result.receipt.get('pending_rows', ()):
            title = '缺失名称关联（不会自动修改）' if row['state']=='missing_alias_or_candidate' else '已拒绝无效输出（不会应用）'
            item = QListWidgetItem(f"{row['original']}\n{title}：{row['surface']} · {row['reason']}")
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, row['cue_id'])
            item.setData(Qt.ItemDataRole.UserRole+1, row)
            self.preview.addItem(item)
        self._update_terms_status()
        self._refresh_status()

    def _update_terms_status(self):
        row = self._glossary_review_receipt
        if not row or row.get('kind')!='current_glossary_text_review':
            return
        states = {'request_failed':'调用失败；已保留本地预览', 'library_read_error':'所选词库未找到，请检查',
            'needs_confirmation':'待确认候选默认未选', 'missing_associations':'请选择缺失名称行并确认关联',
            'invalid_output':'无效输出已拒绝', 'changes_ready':'请确认所选修改',
            'no_changes':'已核对当前词库，范围内没有文字变化'}
        selected=len(self._checked_hits())
        summary=row['snapshot_summary']
        revisions='、'.join(f"{x['name']} r{x['revision']}" for x in row['snapshot'].get('libraries',()))
        self.status_label.setText(f"{revisions} · 有效 {summary['effective_terms']} 个规范词\n"
            f"已核对 {row.get('checked_cues',0)} 条 · AI 返回 {row.get('successful_cues',0)} 条 · 回退 {row.get('fallback_cues',0)} 条 · "
            f"自动可选 {row.get('automatic_changes',0)} 处 · 待确认 {row.get('confirmation_changes',0)} 处 · "
            f"拒绝 {row.get('rejected_changes',0)} 处 · 缺失关联 {row.get('missing_associations',0)} 处 · 当前选中 {selected} 处\n"
            + states.get(row.get('empty_state'),'请逐项确认')+'；未核验原音。')
        self.status_label.setToolTip('诊断：'+str(row.get('diagnostic_path',''))+'\n'+'\n'.join(row.get('request_errors',())))

    def _selected_library_ids(self):
        return tuple(str(self.terms_libraries.item(i).data(Qt.UserRole)) for i in range(self.terms_libraries.count())
            if self.terms_libraries.item(i).checkState()==Qt.Checked)

    def _read_selected_snapshot(self):
        import subtitle_core as legacy
        from .terminology import snapshot_glossaries
        # A damaged DB must not silently become an empty library or a write target.
        legacy.load_learned_term_payload(strict=True)
        identities=self._selected_library_ids()
        return identities,snapshot_glossaries(legacy,identities)

    def _update_association_button(self, *_args):
        if not hasattr(self,'associate_button') or not hasattr(self,'preview'):
            return
        item=self.preview.currentItem()
        row=item.data(Qt.ItemDataRole.UserRole+1) if item else None
        self.associate_button.setEnabled(self.tabs.currentIndex()==3 and bool(row)
            and row.get('state') in {'proposal','missing_alias_or_candidate'}
            and bool(row.get('surface')) and bool(self._selected_library_ids())
            and not (self._glossary_review_worker and self._glossary_review_worker.isRunning()))

    def _open_term_association(self):
        item=self.preview.currentItem()
        row=item.data(Qt.ItemDataRole.UserRole+1) if item else None
        if not row or row.get('state') not in {'proposal','missing_alias_or_candidate'}:
            return
        try:
            identities,snapshot=self._read_selected_snapshot()
        except (OSError,ValueError) as exc:
            self.status_label.setText('词库读取失败，未写入：'+str(exc)); return
        if not identities or (self._preview_snapshot_digest and snapshot.digest!=self._preview_snapshot_digest):
            self.status_label.setText('词库已改变，请重新预览后确认名称。'); return
        dialog=TermAssociationDialog(row, snapshot, self)
        self._association_dialog=dialog
        dialog.saved.connect(self._term_association_saved)
        dialog.open()

    def _term_association_saved(self, identity, source, canonical):
        owner=self._page.window()
        library=getattr(getattr(owner,'term_library_page',None),'library',None)
        notify=getattr(library,'_notify_library_changed',None)
        if callable(notify):notify()
        else:
            refresh=getattr(owner,'_refresh_content_choices',None)
            if callable(refresh):refresh()
        self._invalidate_term_preview()
        self._do_preview()

    def _preview_item_clicked(self, item: QListWidgetItem) -> None:
        cue_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if cue_id and self._page is not None:
            binding = self._preview_binding
            project = self._page.session.project
            was_current = binding is not None and binding.matches(project)
            self._page.select_cue(cue_id)
            if not was_current or self._page.session.project is not project:
                return
            from .studio_runtime_state import DirtyDomain, state_for
            runtime = state_for(project)
            deltas = [delta for delta in runtime.delta_history if delta.revision > binding.revision]
            navigation = DirtyDomain.CUE_SELECTION | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.TRANSFORM
            # The TRANSFORM flag retires selection handles here. It never
            # permits a manual transform: every editable field must match.
            if (len(deltas) == runtime.revision - binding.revision
                    and all(delta.action_id == 'select_cue' and not delta.dirty & ~navigation for delta in deltas)
                    and PreviewBinding._document_fingerprint(project) == binding.document_fingerprint
                    and PreviewBinding._fingerprint(project) == binding.fingerprint):
                self._preview_binding = PreviewBinding.capture(project)

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
            if item is not None and item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)

    def _queue_live_search(self, *_args) -> None:
        self._refresh_status()
        self._search_timer.start()

    def _live_search(self) -> None:
        if self.tabs.currentIndex() == 0:
            self._do_preview()

    def _tab_changed(self, index: int) -> None:
        self._review_generation += 1
        self._preview_hits = []
        self._preview_binding = None
        self.preview.clear()
        self._preview_library_ids = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self._refresh_status()
        self._update_association_button()
        if index == 0:
            self._queue_live_search()

    def _refresh_status(self, *_args) -> None:
        if self._glossary_review_worker is not None and self._glossary_review_worker.isRunning():
            self.next_button.setEnabled(False)
            self.all_button.setEnabled(False)
            return
        needle = self.find_edit.text()
        enabled = bool(needle) and self._page.session.project is not None
        self.next_button.setEnabled(enabled)
        self.all_button.setEnabled(bool(self._checked_hits()))
        self._update_association_button()
        if self.tabs.currentIndex() != 0:
            if self.tabs.currentIndex()==3:self._update_terms_status()
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
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        tab = self.tabs.currentIndex()
        if tab == 3 or (tab == 1 and self.glossary_box.isChecked()):
            prepare = getattr(self._page.window(), '_prepare_glossary_for_task', None)
            if callable(prepare) and not prepare():
                self.status_label.setText('词库输入尚未提交，请先保存或放弃输入后重试。')
                return
        cue_ids = _scope_cue_ids(self._page, self._current_scope())
        locked = _locked_ids(self._page)
        binding = PreviewBinding.capture(project)
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
                from .terminology import TermResolver, snapshot_glossaries
                import subtitle_core as legacy
                snapshot = snapshot_glossaries(legacy, project.glossary_ids)
                resolver = TermResolver(snapshot)
                from .content_scene import resolve_content_scene
                from types import SimpleNamespace
                scene = resolve_content_scene(SimpleNamespace(enable_domain_terms=bool(snapshot.libraries),
                    glossary_snapshot=snapshot, game_name=''), snapshot)
                tidied = {hit.cue_id: hit.replacement for hit in hits}
                hits = [TextOccurrence(cue.id, cue.start_ms, cue.text, cleaned,
                                       (0,len(cue.text)), reason='文本整理与术语规范化')
                        for cue in project.cues if cue.id in cue_ids and cue.id not in locked
                        for cleaned in [resolver.resolve(tidied.get(cue.id,cue.text), scene=scene).text]
                        if cleaned != cue.text]
        elif tab == 2:
            bind_text(self.status_label, '请使用「生成 AI 预览」')
            return
        else:
            from .studio_glossary_service import preview_glossary_correction
            try:
                identities,snapshot=self._read_selected_snapshot()
                result=preview_glossary_correction(project,cue_ids,snapshot,{},use_ai=False)
            except Exception as exc:
                self._fill_preview([],binding)
                self.status_label.setText('当前词库本地预览未完成：'+str(exc)); return
            self._show_terms_result(result,binding,snapshot,identities)
            return
        self._fill_preview(hits, binding)
        if tab == 3:
            summary = snapshot.summary()
            warning = ('；冲突映射已跳过，请在词库中处理' if summary['conflicts'] else
                       '；所选词库无已确认有效词' if not summary['effective_terms'] else
                       '；范围内无可执行替换（规范词可能已正确，未确认错词不会强制修改）' if not hits else '')
            self.status_label.setText(f"有效 {summary['effective_terms']} 个规范词 · 命中 {len(hits)} 处 · 修改 {len({h.cue_id for h in hits})} 条字幕{warning}")

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
        if self._preview_binding is None or not self._preview_binding.matches(self._page.session.project):
            self.status_label.setText("工程或文字已改变，请重新预览；本次没有修改字幕。")
            return
        if self._preview_snapshot_digest is not None:
            from .terminology import snapshot_glossaries
            import subtitle_core as legacy
            if snapshot_glossaries(legacy, self._preview_library_ids or ()).digest != self._preview_snapshot_digest:
                self.status_label.setText("词库已更新，请按当前词库重新生成预览；本次没有修改字幕。")
                return
        hits = self._checked_hits()
        if not hits:
            bind_text(self.status_label, '没有可应用的预览')
            return
        if occurrence_conflicts(hits):
            self.status_label.setText('同一位置选中了不同候选，请只保留一个后再应用；本次没有修改字幕。')
            return
        learn_pair = None
        entity_receipt = None
        if self.tabs.currentIndex() == 0 and not self.regex_box.isChecked():
            # Only the plain find & replace tab is manual term evidence;
            # regex patterns, tidy rules and AI cleanup are not corrections.
            needle = self.find_edit.text().strip()
            replacement = self.replace_edit.text().strip()
            if needle and replacement:
                if self.project_entity_box.isChecked():
                    from .project_entity_confirmations import confirmation_receipt
                    entity_receipt = confirmation_receipt(self._page.session.project,
                        needle, replacement, {h.cue_id for h in hits})
                else:
                    learn_pair = (needle, replacement)
        total, cue_count = apply_occurrences(
            self._page, hits,
            title=self.find_edit.text() or "字幕文本工具",
            learn_pair=learn_pair,
            binding=self._preview_binding,
            glossary_ids=(self._page.session.project.glossary_ids if entity_receipt else
                self._preview_library_ids if self.tabs.currentIndex() == 3 else None),
            review_receipt=entity_receipt or (self._glossary_review_receipt if self.tabs.currentIndex() == 3 else None),
        )
        if total:
            self._page._show_studio_hint(tr('已替换 {value0} 处，涉及 {value1} 条字幕（可 Ctrl+Z 一次撤销）', value0=total, value1=cue_count))
        self._do_preview()
        self._refresh_status()

    def _do_terms_ai_preview(self) -> None:
        if self._glossary_review_worker is not None and self._glossary_review_worker.isRunning():
            return
        prepare = getattr(self._page.window(), '_prepare_glossary_for_task', None)
        if callable(prepare) and not prepare():
            self.status_label.setText('词库输入尚未提交，请先保存或放弃输入后重试。')
            return
        project = self._page.session.project
        if project is None:
            return
        import subtitle_core as legacy
        try:
            identities,snapshot=self._read_selected_snapshot()
        except (OSError,ValueError) as exc:
            self._fill_preview([])
            self.status_label.setText('词库读取失败，未调用 AI：'+str(exc)); return
        if not snapshot.canonical_terms:
            self.status_label.setText("请先选择有已确认规范词的词库。")
            return
        from .api_key_explainer import ask_for_key_if_missing
        if ask_for_key_if_missing(self, copy.deepcopy(legacy.RUNTIME_SETTINGS), "polish", status=lambda: bind_text(
                self.status_label, 'AI 校对没有运行：还没填 API Key')):
            return
        binding = PreviewBinding.capture(project)
        generation = self._review_generation
        settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
        from .studio_project import SubtitleProject
        copied = SubtitleProject.from_dict(copy.deepcopy(project.to_dict()))
        cue_ids = _scope_cue_ids(self._page, str(self.terms_scope.currentData() or SCOPE_ALL))
        self._preview_hits = []
        self._preview_binding = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self.preview.clear()
        self.terms_ai_button.setEnabled(False)
        self.all_button.setEnabled(False)
        self.status_label.setText("正在按当前词库校对已有转写，完成后显示差异…")
        worker = _GlossaryReviewThread(copied, cue_ids, snapshot, settings, self)
        self._glossary_review_worker = worker

        def ready(result):
            if self._review_close_pending:
                return
            if generation != self._review_generation or not binding.matches(self._page.session.project):
                self.status_label.setText("工程、文字或选择已改变，本次校对结果未应用；请重新预览。")
                return
            self._show_terms_result(result,binding,snapshot,identities)

        def failed(message):
            if not self._review_close_pending:
                self.status_label.setText("当前词库校对未完成：" + message)

        def finished():
            self.terms_ai_button.setEnabled(True)
            self._glossary_review_worker = None
            self._refresh_status()
            worker.deleteLater()
            if self._review_close_pending:
                super(FindReplaceDialog,self).reject()

        worker.ready.connect(ready)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()

    def reject(self) -> None:
        worker = self._glossary_review_worker
        if worker is not None and worker.isRunning():
            self._review_close_pending = True
            worker.token.cancel()
            self.status_label.setText("正在取消校对，请稍候…")
            return
        super().reject()

    def _do_ai_preview(self) -> None:
        project = self._page.session.project
        if project is None:
            return
        options = [key for key, box in self.ai_option_boxes.items() if box.isChecked()]
        from .api_key_explainer import ask_for_key_if_missing
        from .settings import load_runtime_settings
        settings = load_runtime_settings()
        settings = settings[0] if isinstance(settings, tuple) else settings
        if ask_for_key_if_missing(self, settings, "polish", status=lambda: bind_text(
                self.status_label, 'AI 清理没有运行：还没填 API Key')):
            return
        binding = PreviewBinding.capture(project)
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
        self._fill_preview(hits, binding)

    def _accept_selected(self) -> None:
        item = self.preview.currentItem()
        if item is not None:
            item.setCheckState(Qt.CheckState.Checked)

    def _reject_selected(self) -> None:
        item = self.preview.currentItem()
        if item is not None:
            item.setCheckState(Qt.CheckState.Unchecked)


class TermAssociationDialog(QDialog):
    """Explicit user confirmation in the selected current library, with free canonical input."""
    saved = Signal(str,str,str)

    def __init__(self,row,snapshot,parent):
        super().__init__(parent)
        self.setWindowTitle('确认名称关联')
        self.setObjectName('termAssociationDialog')
        self.setMinimumWidth(520)
        self._snapshot=snapshot
        self._selected_ids=tuple(library.id for library in snapshot.libraries)
        layout=QVBoxLayout(self)
        note=QLabel('将别名保存为当前所选词库中的用户确认映射。可以选择已有规范词，也可以明确新增；字幕随后重新预览。')
        note.setWordWrap(True);layout.addWidget(note)
        grid=QGridLayout()
        self.library_combo=QComboBox();self.library_combo.setObjectName('termAssociationLibrary')
        for library in snapshot.libraries:self.library_combo.addItem(library.name,library.id)
        self.alias_edit=QLineEdit(str(row.get('surface','')))
        self.alias_edit.setObjectName('termAssociationAlias')
        self.canonical_combo=QComboBox();self.canonical_combo.setEditable(True)
        self.canonical_combo.setObjectName('termAssociationCanonical')
        self.canonical_combo.setInsertPolicy(QComboBox.NoInsert)
        options=list(dict.fromkeys([*row.get('canonical_options',()),*snapshot.canonical_terms]))
        self.canonical_combo.addItems(options)
        # A roster is context, not a guessed canonical. Require an explicit value.
        self.canonical_combo.setCurrentIndex(-1)
        self.canonical_combo.setEditText('')
        self.canonical_combo.lineEdit().setPlaceholderText('选择已有规范词，或输入新规范词（保留大小写）')
        for index,(label,field) in enumerate((('词库',self.library_combo),('当前别名',self.alias_edit),('规范词',self.canonical_combo))):
            grid.addWidget(QLabel(label),index,0);grid.addWidget(field,index,1)
        layout.addLayout(grid)
        self.status=QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
        actions=QHBoxLayout()
        self.save_button=QPushButton('确认并保存关联');self.save_button.setObjectName('termAssociationSave')
        self.save_button.clicked.connect(self._save)
        close=QPushButton('取消');close.clicked.connect(self.reject)
        actions.addStretch(1);actions.addWidget(self.save_button);actions.addWidget(close);layout.addLayout(actions)
        self.canonical_combo.editTextChanged.connect(self._update_status)
        self.alias_edit.textChanged.connect(self._update_status)
        self.library_combo.currentIndexChanged.connect(self._update_status)
        self._update_status()

    def _update_status(self,*_args):
        canonical=self.canonical_combo.currentText().strip()
        source=self.alias_edit.text().strip()
        identity=str(self.library_combo.currentData() or '')
        library=next((library for library in self._snapshot.libraries if library.id==identity),None)
        targets={term.canonical for term in library.terms} if library else set()
        existing=canonical in targets
        self.status.setText(('已存在规范词：' if existing else '将新增规范词：')+canonical if canonical else '请输入并确认规范词；当前没有自动选择。')
        self.save_button.setEnabled(bool(source and canonical and source!=canonical and library and library.found))

    def _save(self):
        import subtitle_core as legacy
        from .terminology import snapshot_glossaries
        source=self.alias_edit.text().strip();canonical=self.canonical_combo.currentText().strip()
        identity=str(self.library_combo.currentData() or '')
        if not self.save_button.isEnabled():return
        try:
            legacy.load_learned_term_payload(strict=True)
            current=snapshot_glossaries(legacy,self._selected_ids)
            if current.digest!=self._snapshot.digest:
                raise ValueError('词库已经更新，请关闭此窗口并重新预览')
            library=next((x for x in current.libraries if x.id==identity and x.found),None)
            if library is None:raise ValueError('所选词库未找到，未写入')
            if any(term.canonical.casefold()==source.casefold() and term.canonical.casefold()!=canonical.casefold()
                    for term in library.terms):
                raise ValueError('当前别名也是独立规范词；请在术语库明确编辑，不能在此合并身份')
            legacy.add_learned_mapping(identity,source,canonical,category='选手ID',origin='手动')
        except (OSError,ValueError,TypeError) as exc:
            self.status.setText('未保存：'+str(exc));return
        self.saved.emit(identity,source,canonical)
        self.accept()
