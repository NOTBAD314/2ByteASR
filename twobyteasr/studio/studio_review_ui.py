"""Review presentation behavior for Subtitle Studio."""

from __future__ import annotations

import difflib
import html
from datetime import datetime, timezone
from time import perf_counter

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from .studio_cards import ReviewCandidateCard
from ..timeline.studio_commands import AdoptReviewCandidateCommand
from ..projects.studio_project import StudioCue
from ..subtitle_rules.studio_qc import QCResult, QCSeverity, review_candidates
from ..subtitle_rules.studio_review import (
    REVIEW_NEXT_GUARD_MS,
    REVIEW_TAIL_MS,
    ReviewEvidenceAggregator,
    ReviewPlayback,
    cached_qc_result,
    cached_review_risks,
    review_playback_window,
    review_risks_from_qc,
)
from ..projects.studio_runtime_state import state_for
from ..design.studio_theme import create_studio_menu
from ..design.components import format_model_evidence_coverage

from ..i18n import bind_text

from ..i18n import tr


class StudioReviewMixin:
    def _show_current_issue_details(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QToolButton
        from ..subtitle_rules.current_issues import current_issue_view
        view = current_issue_view(self.project)
        rows = view.for_cue(self.selected_cue_id)
        diagnostic = view.diagnostics.get(self.selected_cue_id, ())
        dialog = QDialog(self)
        dialog.setWindowTitle('当前字幕问题与诊断')
        dialog.resize(700, 420)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        parts = ['<b>当前待办</b>']
        for index, row in enumerate(rows):
            parts.append(f"<p>{html.escape(row.layer + ' · ' + row.language + ' · ' + row.label)}<br>{html.escape(row.detail)}<br>"
                f"<a href='locate:{index}'>定位试听</a> · <a href='edit:{index}'>编辑此语言层</a> · <a href='timing:{index}'>调整时间</a></p>")
        if not rows:
            parts.append('<p>当前没有需要处理的问题。</p>')
        browser.setHtml(''.join(parts))
        browser.setOpenLinks(False)
        project = self.project
        def action(url):
            try:
                kind, number = url.toString().split(':', 1)
                row = rows[int(number)]
            except (ValueError, IndexError):
                return
            if kind not in {'locate', 'edit', 'timing'}:
                return
            dialog.accept()
            def perform():
                if self.project is not project:
                    return
                cue = self._cue_lookup.get(row.cue_id)
                if cue is None:
                    return
                self.select_cue(cue.id)
                self._seek(cue.start_ms/1000)
                if kind == 'edit':
                    self._open_caption_editor(cue.id, row.layer)
                elif kind == 'locate':
                    self._play_review_context()
                else:
                    self._show_context_panel()
                    self.start_ms.setFocus()
            QTimer.singleShot(0, perform)
        browser.anchorClicked.connect(action)
        layout.addWidget(browser)
        toggle = QToolButton(dialog)
        toggle.setText(f'诊断说明（{len(diagnostic)}，不计入待办）')
        toggle.setCheckable(True)
        extra = QTextBrowser(dialog)
        extra.setHtml(''.join(f'<p>{html.escape(r.label)}：{html.escape(r.detail)}</p>' for r in diagnostic))
        extra.hide()
        toggle.toggled.connect(extra.setVisible)
        layout.addWidget(toggle)
        layout.addWidget(extra)
        dialog.exec()

    def _adopt_highlighted_suggestion(self):
        if getattr(self, '_caption_draft', None) is not None:
            return self._apply_editor_suggestion()
        target=self._resolve_caption_edit_target()
        if target is None or target.layer!='original':
            bind_text(self.save_state,'当前选中译文；按 E 查看这一层的建议')
            return False
        rows=getattr(self,'_review_suggestions',())
        layout=getattr(self,'review_dock_candidate_layout',None)
        if layout is not None:
            for i in range(layout.count()):
                widget=layout.itemAt(i).widget();label=getattr(widget,'text_label',None)
                hit=getattr(label,'_hover',None)
                if hit and hit[1]>=0:
                    return self._apply_review_suggestion(hit[0],hit[1])
        choices=[(i,j) for i,r in enumerate(rows) if r.kind!='pronoun' for j in range(len(r.options))]
        if len(choices)==1:return self._apply_review_suggestion(*choices[0])
        if choices:bind_text(self.save_state,'请先高亮一个具体候选，再按 Shift+R')
        return False

    def _set_cue_filter(self, status: str) -> None:
        restart_review = bool(self._review_mode)
        if restart_review:
            self._set_review_mode(False)
        self._review_all_explicit = ((self.project.project_id, self.session.generation)
                                     if status == 'all' and self.project else None)
        if status in {"priority", "critical"} and self.project:
            self._refresh_review_risks()
            self._show_teach_hint("priority_review")
        self.cue_model.set_filter(status)
        if hasattr(self, "review_summary_strip"):
            self.review_summary_strip.setVisible(self._review_mode)
            self._refresh_review_summary_strip()
        self._refresh_cue_list_summary()
        cue = self._cue_lookup.get(self.selected_cue_id)
        if cue is not None:
            self._refresh_current_review_context(cue)
        if restart_review:
            self._set_review_mode(True)

    def _toggle_review_dock(self, collapsed: bool) -> None:
        for widget in (
            getattr(self, "review_dock_scroll", None) or getattr(self, "review_dock_candidates", None),
            getattr(self, "review_legend", None),
        ):
            if widget is not None:
                widget.setVisible(not collapsed)
        button = self.findChild(QToolButton, "reviewCollapseButton")
        if button is not None:
            button.setText("⌄" if collapsed else "⌃")

    def _show_filter_menu(self) -> None:
        menu = create_studio_menu(self)
        for key, caption in (("all", "全部"), ("priority", "建议确认"), ("critical", "仅需要检查"), ("pending", "未审核"), ("issue", "有问题"), ("done", "已处理")):
            action = menu.addAction(caption)
            action.setCheckable(True)
            action.setChecked(self.cue_model.filter_status == key)
            action.triggered.connect(lambda _checked=False, value=key: self._activate_filter(value))
        button = getattr(self, "cue_filter_button", None)
        if button is None:
            menu.exec(self.cue_search.mapToGlobal(QPoint(0, self.cue_search.height())))
            return
        menu_size = menu.sizeHint()
        bottom_right = button.mapToGlobal(QPoint(button.width(), button.height()))
        top_left = QPoint(bottom_right.x() - menu_size.width(), bottom_right.y())
        screen = QApplication.screenAt(bottom_right) or QApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            top_left.setX(max(bounds.left(), min(top_left.x(), bounds.right() - menu_size.width() + 1)))
            top_left.setY(max(bounds.top(), min(top_left.y(), bounds.bottom() - menu_size.height() + 1)))
        menu.exec(top_left)

    def _activate_filter(self, status: str) -> None:
        button = self.cue_filter_buttons.get(status)
        if button is not None:
            button.setChecked(True)
        self._set_cue_filter(status)

    def _jump_to_row(self) -> None:
        # Leaving the box without changing the number is not a jump.
        if not getattr(self, "_jump_pending", False):
            return
        self._jump_pending = False
        order = getattr(self, "_cue_jump_order", None)
        if not self.project or not order:
            return
        row = min(len(order), max(1, self.jump_spin.value())) - 1
        self._go_to_listed_cue(order[row])

    def _go_to_listed_cue(self, cue) -> None:
        # The seek re-picks the caption at the playhead; where captions
        # overlap it would take the one on the current track and 下一条 kept
        # landing on the previous caption (2026-10-18). Its track goes first.
        self.session.preferred_subtitle_speaker = cue.speaker_id
        self.select_cue(cue.id)
        self._seek(cue.start_ms / 1000.0)

    def _sync_jump_position(self) -> None:
        """The 跳转 box shows the selected caption's number (2026-10-18, user:
        after 上一条 / 下一条 it kept the old number)."""
        spin = getattr(self, "jump_spin", None)
        if spin is None or getattr(self, "_jump_pending", False):
            return  # a number the user is typing stays until they jump
        lookup = getattr(self, "_cue_jump_index", None) or {}
        cue_id = str(self.selected_cue_id or "")
        index = lookup.get(cue_id)
        if index is None and cue_id:
            from ..timeline.studio_edit_sequence import source_cue_id_of
            index = lookup.get(source_cue_id_of(cue_id))
        if index is None or spin.value() == index + 1:
            return
        spin.blockSignals(True)
        spin.setValue(index + 1)
        spin.blockSignals(False)

    def _step_cue(self, delta: int) -> None:
        if self._review_mode:
            return self._step_priority(delta)
        if not self.project or not self.cue_model.rowCount():
            return
        index = self.cue_model.row_for_cue_id(self.selected_cue_id)
        index = 0 if index < 0 else index
        target = min(self.cue_model.rowCount() - 1, max(0, index + int(delta)))
        self._go_to_listed_cue(self.cue_model.cue_at(target))


    def _focus_review_editor(self) -> None:
        if self.selected_cue_id:
            self._begin_canvas_inline_edit()

    def _refresh_current_review_context(self, cue: StudioCue) -> None:
        # Candidate evidence belongs to the existing review strip/list. The
        # deleted checks page has no widgets or delayed callbacks to refresh.
        if self.project and self._review_mode:
            self._refresh_review_summary_strip()

    def _refresh_review_summary_strip(self) -> None:
        if not hasattr(self, "review_summary_text") or not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        if cue is None:
            return
        issues = cached_qc_result(self.project).for_cue(cue.id)
        candidates = tuple(c for c in review_candidates(self.project, cue) if not c.context_only)
        self._review_candidates = candidates
        severity_order = {QCSeverity.CRITICAL: 0, QCSeverity.WARNING: 1, QCSeverity.INFO: 2}
        ordered_issues = sorted(issues, key=lambda issue: severity_order.get(issue.severity, 9))
        aggregate = getattr(self, "_review_evidence_aggregate", None)
        if aggregate is None or getattr(aggregate, "cue_id", "") != cue.id:
            aggregate = ReviewEvidenceAggregator().aggregate(self.project, cue)
        self._review_evidence_aggregate = aggregate
        if aggregate.boundary_only and not aggregate.requires_review:
            bind_text(self.review_summary_text, '✓ 文本一致 · 仅断句差异')
        elif aggregate.speaker_only:
            bind_text(self.review_summary_text, '说话人候选不同')
        elif not aggregate.models_agree_text:
            bind_text(self.review_summary_text, '⚠ 候选文本存在差异')
        elif len(candidates) == 1 or aggregate.models_agree_text:
            coverage = format_model_evidence_coverage(aggregate.hypotheses)
            self.review_summary_text.setText(
                coverage["headline"] if aggregate.requires_review or coverage["single_source"] else f"✓ {coverage['headline']}"
            )
        elif ordered_issues:
            self.review_summary_text.setText("  ".join(
                ("⚠ " if issue.severity != QCSeverity.INFO else "● ") + issue.label
                for issue in ordered_issues[:3]
            ))
        else:
            bind_text(self.review_summary_text, '⚠ 候选文本存在差异')

        session = getattr(self, "_review_session", None)
        row = self.cue_model.row_for_cue_id(cue.id)
        total = session.total if self._review_mode and session is not None else self.cue_model.rowCount()
        completed = session.completed if self._review_mode and session is not None else max(0, row)
        (bind_text(self.review_queue_label, '审核进度  {value0} / {value1}', value0=min(total, completed + 1) if total else 0, value1=total) if self._review_mode else bind_text(self.review_queue_label, '需要检查  - / -'))
        reason = ""
        if ordered_issues:
            issue = ordered_issues[0]
            if issue.issue_type == "model_disagreement" and len(candidates) > 1:
                left, right = candidates[0].text, candidates[1].text
                matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
                differences = []
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag != "equal" and (left[i1:i2] or right[j1:j2]):
                        differences.append(f"{left[i1:i2] or '-'} / {right[j1:j2] or '-'}")
                reason = f"模型对「{'；'.join(differences[:2])}」存在分歧" if differences else issue.label
            elif "duplicate" in issue.issue_type or "repeat" in issue.issue_type:
                reason = "发现疑似重复内容"
            else:
                reason = (issue.description or issue.label).split("。")[0]
        elif aggregate.boundary_only and not aggregate.requires_review:
            reason = "文本一致，仅断句不同；无需进行文字二选一"
        elif aggregate.speaker_only:
            reason = "文本一致，请确认说话人候选"
        elif aggregate.source_coverage.get('missing'):
            reason = "来源范围信息未记录；仅作说明，当前字幕默认可用"
        elif aggregate.source_coverage.get('coverage_unknown'):
            reason = "字级覆盖尚未完整记录；仅作说明，当前字幕默认可用"
        elif aggregate.source_coverage.get('partial'):
            reason = "局部范围缺少额外来源覆盖；仅作说明，当前字幕默认可用"
        elif len(candidates) > 1:
            reason = "模型输出存在文本差异，请选择更可信的文本"
        else:
            reason = "当前没有需要人工处理的问题"
        from ..subtitle_rules.current_issues import current_issue_view
        view = current_issue_view(self.project)
        current = view.for_cue(cue.id)
        if current:
            self.review_summary_text.setText(' · '.join(dict.fromkeys(r.label for r in current)))
            reason = '；'.join(f"{'译文' if r.layer == 'translation' else '原文'} · {r.language}：{r.detail}" for r in current)
        else:
            bind_text(self.review_summary_text, '当前字幕没有待处理建议')
            reason = '来源、覆盖和格式记录可在“详情”展开；未人工看过仅表示审核进度。'
        self.review_reason_label.setText(reason)
        self.review_reason_label.setToolTip(reason)
        if self._review_mode and session is not None:
            from ..subtitle_rules.current_issues import reviewed_version, DECISIONS
            decisions = self.project.studio_state.get(DECISIONS, {})
            if session.scope.filter_mode in {'priority', 'critical'}:
                session.resolved_ids = {key for key in session.scope.visible_cue_ids if not view.for_cue(key)}
            else:
                session.resolved_ids = {key for key in session.scope.visible_cue_ids
                    if decisions.get('reviewed:'+key) and decisions['reviewed:'+key].get('input_version') == reviewed_version(self.project, self._cue_lookup[key])}
            remaining = session.total - session.completed
            moved=0
            if session.scope.filter_mode in {'priority','critical'}:
                expected='high' if session.scope.filter_mode=='critical' else 'suggested'
                moved=sum(bool(view.for_cue(key)) and view.level(key)!=expected for key in session.scope.visible_cue_ids)
                remaining-=moved
            self.review_queue_label.setText(f'本轮已处理 {session.completed} / {session.total} · 当前剩余 {remaining}'
                                           +(f' · 已转其他分类 {moved}' if moved else ''))
        if hasattr(self, "review_dock_candidate_layout"):
            text_types={'model_disagreement','suspected_word'}
            if (not any(r.layer=='original' and r.kind in text_types for r in current)
                    and any(r.cue_id==cue.id and r.layer=='original' and r.kind in text_types
                            and r.disposition=='handled' for r in view.records)):
                from ..subtitle_rules.studio_qc import QCCandidate
                candidates=(next((c for c in candidates if c.text==cue.text),QCCandidate(cue.text,('Current',))),)
                self._review_candidates=candidates
            speaker_only = bool(aggregate.speaker_only and aggregate.models_agree_text)
            card_mode = (not speaker_only and len(candidates) > 1
                         and not (aggregate.boundary_only and not aggregate.requires_review))
            # 2026-10-15: click-to-fix marks live on card 1 only (user: with
            # three results, mark just the first).
            suggestions = () if speaker_only else self._review_suggestions_for(cue, candidates if card_mode else ())
            self._review_suggestions = suggestions
            # The row has a fixed height (studio_workspace.REVIEW_DOCK_ROW_HEIGHT):
            # up to four cards share it when there is room, the rest scrolls.
            width = max(self.review_summary_strip.width(), self.review_dock_candidates.width())
            columns = (max(1, min(4, len(candidates[:4]), width // 260)) if card_mode
                       else max(1, min(2, width // 260)) if suggestions else 1)
            signature = (cue.id, cue.text, cue.speaker_id, speaker_only, card_mode, columns,
                         bool(aggregate.requires_review),
                         tuple((c.text, tuple(c.sources or ()), bool(c.context_only)) for c in candidates[:5]),
                         tuple(sorted(str(row.get("speaker_id") or row.get("speaker") or "")
                                      for row in aggregate.hypotheses)) if speaker_only else (),
                         format_model_evidence_coverage(aggregate.hypotheses)['display'] if not card_mode else "",
                         tuple((row.kind, row.start, row.end, row.original, tuple(option.text for option in row.options))
                               for row in suggestions))
            binding=(id(self.project),self.session.generation,cue.id,cue.text,cue.start_ms,cue.end_ms,signature)
            self._review_suggestions_binding=binding
            if signature == getattr(self, "_review_cards_signature", None) and self.review_dock_candidate_layout.count():
                # Same caption, same width bucket: keep the cards (resize events
                # and repeated hydration of one caption used to rebuild them).
                return
            self._review_cards_signature = signature
            while self.review_dock_candidate_layout.count():
                item = self.review_dock_candidate_layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            for column in range(4):
                self.review_dock_candidate_layout.setColumnStretch(column, 1 if column < columns else 0)
            scroll = getattr(self, "review_dock_scroll", None)
            if scroll is not None:
                scroll.verticalScrollBar().setValue(0)

            if speaker_only:
                speaker_ids = sorted({
                    str(row.get("speaker_id") or row.get("speaker") or "").strip()
                    for row in aggregate.hypotheses
                    if str(row.get("speaker_id") or row.get("speaker") or "").strip()
                } | {str(cue.speaker_id or "").strip()})
                speaker_text = " / ".join(item for item in speaker_ids if item) or "未标注"
                speaker_banner = bind_text(QLabel(), '文本一致：{value0}<br>说话人候选：{value1}', value0=html.escape(cue.text), value1=html.escape(speaker_text))
                speaker_banner.setTextFormat(Qt.TextFormat.RichText)
                speaker_banner.setObjectName("checkWarning")
                speaker_banner.setWordWrap(True)
                self.review_dock_candidate_layout.addWidget(
                    speaker_banner, 0, 0, 1, columns
                )
            elif len(candidates) > 1 and not (aggregate.boundary_only and not aggregate.requires_review):
                try:
                    from ..subtitle_rules.studio_qc import normalize_candidate_text
                    current_text_norm = normalize_candidate_text(cue.text)
                except Exception:
                    normalize_candidate_text = None
                    current_text_norm = None

                for index, candidate in enumerate(candidates[:4]):
                    if normalize_candidate_text is not None and current_text_norm is not None:
                        is_cur = normalize_candidate_text(candidate.text) == current_text_norm
                    else:
                        is_cur = index == 0
                    card = ReviewCandidateCard(
                        index,
                        candidate,
                        is_current=is_cur,
                        current_text=cue.text,
                        parent=self,
                        suggestions=suggestions if index == 0 else (),
                        key_text=self._shortcut_key_text,
                    )
                    card.clicked.connect(lambda row=index, bound=binding: self._adopt_review_candidate(row,binding=bound))
                    if index == 0 and suggestions:
                        card.suggestion_activated.connect(lambda mark,option,bound=binding:self._apply_review_suggestion(mark,option,binding=bound))
                        card.suggestion_menu_requested.connect(lambda mark,pos,bound=binding:self._show_review_suggestion_menu(mark,pos,binding=bound))
                    if candidate.context_only:
                        card.setEnabled(False)
                        card.setToolTip('原始段落上下文；缺少本条精确字词边界，请结合原音编辑，不能整段替换。')
                    self.review_dock_candidate_layout.addWidget(
                        card, index // columns, index % columns
                    )
                if len(candidates) > 4:
                    more = QLabel("其余证据已保存在字幕来源记录中")
                    more.setObjectName("cardMeta")
                    self.review_dock_candidate_layout.addWidget(more, (3 // columns) + 1, 0, 1, columns)
            else:
                # Consistent banner
                coverage = format_model_evidence_coverage(aggregate.hypotheses)
                banner = QLabel(reason)
                banner.setToolTip(coverage['display'])
                banner.setWordWrap(True)
                banner.setObjectName("checkWarning" if current else "checkPass")
                if suggestions:
                    # Nothing to choose between, but the caption still has
                    # glossary fixes or 他/她 to flip: card 1 next to the banner.
                    from ..subtitle_rules.studio_qc import QCCandidate
                    card = ReviewCandidateCard(0, QCCandidate(cue.text, ("Current",)), is_current=True,
                                               current_text=cue.text, parent=self, suggestions=suggestions,
                                               key_text=self._shortcut_key_text)
                    card.clicked.connect(lambda _=0,bound=binding: self._adopt_review_candidate(0,binding=bound))
                    card.suggestion_activated.connect(lambda mark,option,bound=binding:self._apply_review_suggestion(mark,option,binding=bound))
                    card.suggestion_menu_requested.connect(lambda mark,pos,bound=binding:self._show_review_suggestion_menu(mark,pos,binding=bound))
                    self.review_dock_candidate_layout.addWidget(card, 0, 0)
                    self.review_dock_candidate_layout.addWidget(banner, 0 if columns > 1 else 1, 1 if columns > 1 else 0)
                else:
                    self.review_dock_candidate_layout.addWidget(banner, 0, 0, 1, columns)

    def _review_entry_target(self):
        """Capture explicit active identity before a filter resets selection."""
        if self.project is None:
            return None
        timeline = self.timeline
        cues = self._cue_lookup
        explicit = str(timeline.explicit_subtitle_id or '')
        layer = str(timeline.active_subtitle_layer or 'original')
        scope = timeline.selection_scope
        active = str(getattr(scope,'active_id','') or timeline.selected_id or '')
        if explicit and active in cues and scope.contains(active):
            return active, layer
        hidden = self.project.hidden_speaker_ids() | frozenset(getattr(timeline,'hidden_speakers',()))
        visibility = getattr(self,'_subtitle_track_visibility',{})
        available = [cue for cue in cues.values() if cue.speaker_id not in hidden and visibility.get(cue.speaker_id,True)]
        if not available:
            return None
        ms = int(timeline.playhead_ms)
        preferred = str(getattr(self.session, 'preferred_subtitle_speaker', '') or '')
        header=getattr(timeline,'selected_track_header',None)
        if header and header[0]=='subtitle':preferred=str(header[1])
        hits = [cue for cue in available if cue.start_ms <= ms < cue.end_ms]
        if hits:
            cue = min(hits, key=lambda c:(c.speaker_id != preferred, abs(ms-c.start_ms), c.start_ms, c.id))
        else:
            # Closest interval; ties prefer the current track, then the following subtitle.
            cue = min(available, key=lambda c:(min(abs(ms-c.start_ms), abs(ms-c.end_ms)),
                c.speaker_id != preferred, c.start_ms < ms, c.start_ms, c.id))
        return cue.id, layer

    def _set_review_mode(self, enabled: bool) -> None:
        entering = bool(enabled) and not self._review_mode
        leaving = not bool(enabled) and self._review_mode
        identity = (id(self.project), self.session.generation)
        if entering and self.project:
            saved = getattr(self, '_review_entry_anchor', None)
            if saved is None or saved[:2] != identity or saved[2] not in self._cue_lookup:
                target = self._review_entry_target()
                self._review_entry_anchor = (*identity, *target) if target else None
        if (entering and self.project and getattr(self, '_pending_review_start', None)
                == (id(self.project), self.session.generation)):
            self._pending_review_start = None
            self._review_entry_anchor = None
            bind_text(self.save_state, '已取消等待审核')
            return
        if not enabled:
            self._pending_review_start = None
            self._review_entry_anchor = None
        if entering and self.project and not hasattr(self.project, '_qc_result'):
            self._pending_review_start = (id(self.project), self.session.generation)
            self.review_mode_button.blockSignals(True)
            self.review_mode_button.setChecked(False)
            self.review_mode_button.blockSignals(False)
            bind_text(self.save_state, '正在核对当前问题，完成后开始审核…')
            return
        entry = getattr(self, '_review_entry_anchor', None)
        if entering:
            self.cue_model.review_anchor_id = entry[2] if entry and entry[:2] == identity else ''
        if (entering and self.project and self.cue_model.filter_status == 'all'
                and getattr(self, '_review_all_explicit', None) != (self.project.project_id, self.session.generation)):
            # A fresh project displays All, but starting review defaults to
            # actual issues. Whole-project review requires choosing All.
            from ..subtitle_rules.current_issues import current_issue_view
            mode = 'critical' if current_issue_view(self.project).counts()['critical'] else 'priority'
            self.cue_model.set_filter(mode)
            self.cue_filter_buttons[mode].setChecked(True)
            self._refresh_cue_list_summary()
        if entering or leaving:
            self._release_review_playback()
        if entering:
            from ..subtitle_rules.studio_review import ReviewScopeSnapshot, ReviewSession
            self.cue_model.refresh()
            visible_ids = tuple(
                self.cue_model.cue_at(row).id
                for row in range(self.cue_model.rowCount())
            )
            snapshot = ReviewScopeSnapshot(
                filter_mode=str(self.cue_model.filter_status),
                search_query=str(self.cue_model.query),
                speaker_filter="",
                review_severity=str(self.cue_model.filter_status),
                visible_cue_ids=visible_ids,
            )
            self._review_session = ReviewSession(snapshot)
            self.cue_model.set_scope_ids(visible_ids)
        self._review_mode = bool(enabled)
        self.review_mode_button.blockSignals(True)
        self.review_mode_button.setChecked(self._review_mode)
        (bind_text(self.review_mode_button, '退出审核模式') if self._review_mode else bind_text(self.review_mode_button, '进入审核模式'))
        if hasattr(self, "review_entry_button"):
            (bind_text(self.review_entry_button, '■ 退出审核') if self._review_mode else bind_text(self.review_entry_button, '▶ 开始审核'))
            (bind_text(self.review_entry_button, '退出审核模式', property='toolTip') if self._review_mode else bind_text(self.review_entry_button, '进入优先审核；快捷键 R', property='toolTip'))
        self.review_mode_button.blockSignals(False)
        self.review_summary_strip.setVisible(self._review_mode)
        if leaving:
            session = getattr(self, "_review_session", None)
            self.cue_model.review_anchor_id = ''
            self.cue_model.set_scope_ids(None)
            if session is not None:
                self.cue_model.set_filter(session.scope.filter_mode)
                self.cue_model.set_query(session.scope.search_query)
            self._review_session = None
        if not self._review_mode:
            return
        if entering and entry and entry[:2] == identity:
            self.select_cue(entry[2])
            self.timeline.set_subtitle_layer(entry[3])
            self._remember_canvas_edit_target(entry[2], entry[3])
        if self.cue_model.rowCount():
            cue = self._cue_lookup.get(self.selected_cue_id)
            if cue is not None:
                self._seek(cue.start_ms / 1000.0)
            self._warm_review_neighbors(self.cue_model.row_for_cue_id(self.selected_cue_id))
        self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._refresh_review_summary_strip()

    def _refresh_review_risks(self, cue_ids: set[str] | None = None, *, sync: bool = False) -> None:
        if not self.project:
            return
        if cue_ids and hasattr(self.project, "_qc_result"):
            result = cached_qc_result(self.project)
            # analyze_incremental() falls back to a full analyze when given a
            # cue that no longer exists (undo of split, delete). Filter those
            # out and drop their stale issues instead, then rescan survivors.
            present = {
                cue_id for cue_id in cue_ids
                if cue_id in self._cue_lookup
            }
            stale = set(cue_ids) - present
            if stale:
                result = QCResult(
                    {
                        key: value
                        for key, value in result.issues_by_cue.items()
                        if key not in stale
                    }
                )
            # One context build over the union of the edited windows; folding
            # analyze_incremental() per cue rebuilt it for every cue.
            result = self._qc_engine.analyze_incremental_many(
                self.project,
                present,
                result,
                terminology=self._qc_terminology,
            )
            # Risks derive purely from each cue's own issues, so recompute
            # exactly the edited window instead of rebuilding the cached
            # dict for every cue in the project (measured ~150ms at 1k cues).
            changed_ids = set(cue_ids)
            delta_risks = review_risks_from_qc(
                QCResult(
                    {
                        cue_id: result.issues_by_cue.get(cue_id, ())
                        for cue_id in changed_ids
                    }
                )
            )
            risks_cache = dict(getattr(self.project, "_review_risks_cache", {}) or {})
            for cue_id in changed_ids:
                risks_cache.pop(cue_id, None)
            risks_cache.update(
                {cue_id: risk.to_dict() for cue_id, risk in delta_risks.items()}
            )
            setattr(self.project, "_qc_result", result)
            setattr(self.project, "_review_risks_cache", risks_cache)
        else:
            self._start_chunked_qc_scan(sync=bool(sync))
            return
        self._qc_full_scan_pending = False
        self._pending_qc_cue_ids.difference_update(cue_ids or set())
        if self.selected_cue_id:
            cue = self._cue_lookup.get(self.selected_cue_id)
            if cue is not None:
                self._refresh_current_review_context(cue)


    _QC_SCAN_CHUNK = 400
    _QC_SCAN_MINI = 1
    _QC_SCAN_BUDGET_S = 0.012

    def _start_chunked_qc_scan(self, *, sync: bool = False, _fallback: bool = False) -> None:
        """全量 QC 分片执行：每片 400 cue，QTimer 链让事件循环呼吸。

        2026-09-18 进入路径实测（3839 cue 真实工程）：同步全扫即使有
        纯函数缓存仍阻塞 GUI ~600-900ms，且发生在首帧就绪前——mpv 早已
        loadfile，首帧 IPC 事件却在等 GUI 线程释放。分片后无 >150ms 单段
        阻塞；编辑/切工程通过 token 失效让旧扫描作废重扫，语义与同步版
        一致（小编辑走增量路径不受影响）。
        """
        project = self.project
        if project is None:
            return
        self._qc_scan_token = getattr(self, "_qc_scan_token", 0) + 1
        token = self._qc_scan_token
        self._qc_scan_started_at = perf_counter()
        engine = self._qc_engine
        terminology = tuple(self._qc_terminology or ())
        store = getattr(self, '_revision_store', None)
        if not sync and not _fallback and store is not None and store.project is project:
            from .studio_qc_worker import StudioQCWorker
            from ..projects.studio_runtime_state import state_for
            worker = getattr(self, '_qc_worker', None)
            if worker is None:
                worker = self._qc_worker = StudioQCWorker(self)
                worker.ready.connect(self._background_qc_ready)
                worker.failed.connect(self._background_qc_failed)
            capture_started = perf_counter()
            snapshot = store.persistence
            identity = (id(project), self.session.generation,
                        state_for(project).playback_revision, token)
            self._qc_worker_snapshot_ms = (perf_counter()-capture_started)*1000
            worker.submit(snapshot,engine.config,terminology,identity)
            return
        context = engine.build_context(project, terminology=terminology)
        ordered = list(context.ordered)
        collected: dict[str, tuple] = {}
        cursor = 0
        timer = getattr(self, "_qc_scan_timer", None)
        if timer is None:
            timer = self._qc_scan_timer = QTimer(self)
            timer.setSingleShot(True)
        try:
            timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass

        def step() -> None:
            nonlocal cursor
            if token != getattr(self, "_qc_scan_token", 0) or self.project is not project:
                return
            # A time budget, not a cue count: model-evidence rules cost very
            # different amounts per cue (one 400-cue slice measured 0.3 s).
            started = perf_counter()
            limit = cursor + self._QC_SCAN_CHUNK
            while cursor < min(limit, len(ordered)):
                # Check the budget after each cue: sixteen evidence-heavy cues
                # exceeded two seconds on the reported 134-cue project.
                chunk = ordered[cursor:cursor + self._QC_SCAN_MINI]
                cursor += len(chunk)
                collected.update(engine.evaluate_cues(context, chunk))
                if not sync and perf_counter() - started >= self._QC_SCAN_BUDGET_S:
                    break
            if cursor < len(ordered):
                timer.start(0)
                return
            self._finish_chunked_qc_scan(project, QCResult(collected))

        timer.timeout.connect(step)
        if sync:
            # 同步模式（测试/需要立即可用的调用方）：直接跑完全部分片。
            # 末片之前的 step 会 arm 定时器，循环后必须停掉，避免额外一拍
            # 触发二次 finish。
            while (token == getattr(self, "_qc_scan_token", 0)
                   and self.project is project
                   and cursor < len(ordered)):
                step()
            timer.stop()
            return
        timer.start(0)

    def _background_qc_current(self, identity):
        return (self.project is not None and identity[0] == id(self.project)
                and identity[1] == self.session.generation
                and identity[3] == getattr(self, '_qc_scan_token', 0))

    def _background_qc_ready(self, identity, result, timings):
        if not self._background_qc_current(identity):
            return
        from ..projects.studio_runtime_state import state_for
        if identity[2] != state_for(self.project).playback_revision:
            self._start_chunked_qc_scan()
            return
        began = perf_counter()
        self._finish_chunked_qc_scan(self.project,result)
        self._qc_worker_timings = {**timings,'snapshot_ms':self._qc_worker_snapshot_ms,
                                   'gui_commit_ms':(perf_counter()-began)*1000}

    def _background_qc_failed(self, identity, error):
        if not self._background_qc_current(identity):
            return
        self._studio_trace('QC_WORKER_FAILED', error=error, fallback='budgeted_gui_scan')
        self._start_chunked_qc_scan(_fallback=True)

    def _finish_chunked_qc_scan(self, project, result: QCResult) -> None:
        if self.project is not project:
            return
        risks = review_risks_from_qc(result)
        setattr(project, "_qc_result", result)
        setattr(
            project,
            "_review_risks_cache",
            {cue_id: risk.to_dict() for cue_id, risk in risks.items()},
        )
        self._qc_full_scan_pending = False
        self._pending_qc_cue_ids.clear()
        self._studio_trace(
            "QC_SCAN_FINISHED",
            cues=len(result.issues_by_cue),
            elapsed_ms=round((perf_counter() - float(getattr(self, "_qc_scan_started_at", 0.0) or 0.0)) * 1000, 1),
        )
        if getattr(self.cue_model, "filter_status", "") in {"priority", "critical"}:
            self.cue_model.refresh()
        self.cue_model.refresh_cues((c.id for c in project.cues), (4,), recheck_filter=False)
        self._refresh_cue_list_summary()
        if self.selected_cue_id:
            cue = self._cue_lookup.get(self.selected_cue_id)
            if cue is not None:
                self._refresh_current_review_context(cue)
        if getattr(self, '_pending_review_start', None) == (id(project), self.session.generation):
            self._pending_review_start = None
            self._set_review_mode(True)


    def _set_continuous_review(self, enabled: bool) -> None:
        if not self.project:
            return
        self.project.studio_state["continuous_review"] = bool(enabled)
        if enabled:
            self._activate_filter("priority")
            if self.cue_model.rowCount():
                self.select_cue(self.cue_model.cue_at(0).id)
                self._play_review_context()

    def _play_review_context(self) -> None:
        if not self.project or not self.selected_cue_id or not self.video.controller:
            return
        cue_id = self.selected_cue_id
        runtime = state_for(self.project)
        # Timeline time: _cue_lookup resolves an edited project's derived ids
        # back to source captions, and _seek takes timeline seconds.
        cue = runtime.view_cue(cue_id) or self._cue_lookup.get(cue_id)
        if cue is None:
            return
        try:
            playback = self.video.playback_position_snapshot()
            if not bool(playback.paused) or self._review_space_playing:
                # Space is a true play/pause toggle in Review as well. In
                # particular, a second press must not seek and restart the
                # context window while it is already playing.
                self.video.set_paused(True)
                self._sync_play_button(True)
                self._review_space_playing = False
                self._review_play_generation = getattr(self, "_review_play_generation", 0) + 1
                self._park_review_playback()
                return
        except (RuntimeError, AttributeError):
            pass
        start, stop = review_playback_window(
            cue, runtime.visible_cues(cue.end_ms, cue.end_ms + REVIEW_TAIL_MS + REVIEW_NEXT_GUARD_MS + 1))
        generation = getattr(self, "_review_play_generation", 0) + 1
        self._review_play_generation = generation
        # Set before the seek: the lead-in and tail cross neighbouring
        # captions, and the playhead-follow selection must stay on this one.
        self._review_playback = ReviewPlayback(str(cue_id), start, stop, generation)
        self._review_fallback_playhead = None
        self._review_seeking = True
        try:
            self._seek(start / 1000.0)
        finally:
            self._review_seeking = False
        try:
            self.video.set_paused(False)
            self._sync_play_button(False)
            self._review_space_playing = True
        except RuntimeError as exc:
            self._release_review_playback()
            self._show_video_error(str(exc))
            return
        self._arm_review_fallback(generation)

    def _arm_review_fallback(self, generation: int) -> None:
        """Safety stop if the playhead never reports the end (stalled source)."""
        review = getattr(self, "_review_playback", None)
        if review is None or review.generation != generation:
            return
        rate = max(0.25, float(getattr(self.video, "_playback_rate", 1.0) or 1.0))
        remaining = max(0, review.stop_ms - int(getattr(self.timeline, "playhead_ms", review.start_ms)))
        QTimer.singleShot(int(remaining / rate) + 1500,
                          lambda token=generation: self._review_fallback_due(token))

    def _review_fallback_due(self, generation: int) -> None:
        review = getattr(self, "_review_playback", None)
        if review is None or review.generation != generation or review.finished:
            return
        playhead = int(getattr(self.timeline, "playhead_ms", 0))
        if (not bool(getattr(self.video, "_paused", True)) and review.start_ms <= playhead < review.stop_ms
                and playhead != getattr(self, "_review_fallback_playhead", None)):
            # Still advancing towards the stop (a slow seek delayed the start).
            self._review_fallback_playhead = playhead
            self._arm_review_fallback(generation)
            return
        self._pause_review_context(generation)

    def _review_playback_tick(self, milliseconds: int) -> None:
        """Stop a review replay on media time, before the next caption."""
        review = getattr(self, "_review_playback", None)
        if review is None:
            return
        if review.finished:
            # Jumps, frame steps or ordinary playback that leave the replayed
            # stretch end the hold; until then the reviewed caption stays.
            if not review.start_ms - 1 <= int(milliseconds) <= review.stop_ms + 250:
                self._release_review_playback()
            return
        if bool(getattr(self.video, "_paused", True)):
            return
        clock = getattr(self.video, "_playback_clock", None)
        if clock is not None and getattr(clock, "exact_seek_pending", False):
            return
        remaining = review.stop_ms - int(milliseconds)
        if remaining <= 0:
            self._pause_review_context(review.generation)
            return
        rate = max(0.25, float(getattr(self.video, "_playback_rate", 1.0) or 1.0))
        wall = remaining / rate
        if wall <= 40:
            # The next 16 ms UI sample may already be past the stop at 2x.
            timer = getattr(self, "_review_stop_timer", None)
            if timer is None:
                timer = self._review_stop_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setTimerType(Qt.TimerType.PreciseTimer)
                timer.timeout.connect(lambda: self._review_stop_due())
            if not timer.isActive():
                self._review_stop_generation = review.generation
                timer.start(max(1, int(wall)))

    def _review_stop_due(self) -> None:
        generation = getattr(self, "_review_stop_generation", None)
        review = getattr(self, "_review_playback", None)
        if review is not None and review.generation == generation:
            self._pause_review_context(generation)

    def _pause_review_context(self, generation: int) -> None:
        if generation != getattr(self, "_review_play_generation", 0) or not self.video.controller:
            return
        try:
            self.video.set_paused(True)
            self._sync_play_button(True)
            self._review_space_playing = False
        except RuntimeError as exc:
            self._show_video_error(str(exc))
        self._park_review_playback()

    def _park_review_playback(self) -> None:
        """Keep the reviewed caption selected after its replay stops."""
        review = getattr(self, "_review_playback", None)
        if review is not None and not review.finished:
            from dataclasses import replace
            self._review_playback = replace(review, finished=True)

    def _release_review_playback(self) -> None:
        """The user moved on (seek, transport play, new selection, left Review)."""
        self._review_playback = None
        timer = getattr(self, "_review_stop_timer", None)
        if timer is not None:
            timer.stop()

    def _review_held_cue_id(self) -> str:
        review = getattr(self, "_review_playback", None)
        return review.cue_id if review is not None else ""

    def _confirm_current_review(self, play_next: bool = False) -> None:
        if getattr(self, '_caption_draft', None) is not None:
            return self._submit_caption_draft()
        if not self.project or not self.selected_cue_id:
            return
        from ..subtitle_rules.current_issues import current_issue_view, reviewed_version
        from .caption_editor import IssueDecisionsCommand
        cue_id = self.selected_cue_id
        cue = self._cue_lookup.get(cue_id)
        if cue is None:
            return
        view = current_issue_view(self.project)
        changes = {r.issue_id: {'input_version': r.input_version, 'status': 'resolved'}
                   for r in view.for_cue(cue_id)}
        changes['reviewed:'+cue_id] = {'input_version': reviewed_version(self.project, cue), 'status': 'resolved'}
        session = getattr(self, '_review_session', None)
        next_id = session.next_id(cue_id,eligible_ids=(self.cue_model.cue_at(i).id for i in range(self.cue_model.rowCount()))) if self._review_mode and session else ''
        self.undo_stack.push(IssueDecisionsCommand(self.project, changes,
            lambda: self._caption_issue_decisions_changed(cue_id)))
        if next_id:
            self._select_review_cue_immediately(next_id, play=play_next)
        else:
            self._refresh_review_summary_strip()

    def _select_review_cue_immediately(self,cue_id,*,play=False):
        """Commit selection now. Latest selection alone may seek/hydrate later."""
        project=self.project
        self._review_fast_select=True
        try:self.select_cue(cue_id,hydrate=False)
        finally:self._review_fast_select=False
        generation=getattr(self,'_review_selection_generation',0)+1
        self._review_selection_generation=generation
        bind_text(self.save_state, '已切换 · 正在定位')
        def current():return self.project is project and self.selected_cue_id==cue_id and self._review_selection_generation==generation and not self._close_requested
        def locate():
            if not current():return
            cue=self._cue_lookup.get(cue_id)
            if cue:self._seek(cue.start_ms/1000)
        def hydrate():
            if not current():return
            self.cue_controller._select_cue_ui(cue_id,hydrate=True)
            self._refresh_cue_list_summary()
            self._warm_review_neighbors(self.cue_model.row_for_cue_id(cue_id))
            if play or self.continuous_review_toggle.isChecked():self._play_review_context()
        QTimer.singleShot(0,locate)
        QTimer.singleShot(80,hydrate)

    def _mark_review_resolved(self, cue_id: str) -> None:
        if not self.project:
            return
        statuses = self.project.studio_state.setdefault("cue_statuses", {})
        confirmations = self.project.studio_state.setdefault("review_confirmations", {})
        if isinstance(statuses, dict) and isinstance(confirmations, dict):
            statuses[str(cue_id)] = "done"
            confirmations[str(cue_id)] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _exit_review(self) -> None:
        if self._review_mode:
            self._set_review_mode(False)
            self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.cue_controller.cancel_selection()

    def _skip_current_review(self) -> None:
        if not self.project or not self.selected_cue_id:
            return
        session = getattr(self, "_review_session", None)
        if self._review_mode and session is not None:
            next_id = session.next_id(self.selected_cue_id, include_resolved=True,
                eligible_ids=(self.cue_model.cue_at(i).id for i in range(self.cue_model.rowCount())))
            if next_id:
                self.select_cue(next_id)
            return
        if self.cue_model.filter_status not in {"priority", "critical"}:
            self._activate_filter("priority")
        rows = self.cue_model.rowCount()
        if rows <= 1:
            return
        current = self.cue_model.row_for_cue_id(self.selected_cue_id)
        next_row = min(rows - 1, max(0, current) + 1)
        self.select_cue(self.cue_model.cue_at(next_row).id)
        if self.continuous_review_toggle.isChecked():
            self._play_review_context()

    def _adopt_model_text(self, value: str, label: str) -> bool:
        from ..timeline.studio_commands import MutationOrigin
        if not self.project or not self.selected_cue_id:
            return False
        cue = self._cue_lookup.get(self.selected_cue_id)
        value = str(value or '').strip()
        if cue is None or not value:
            return False
        draft = getattr(self, '_caption_draft', None)
        if draft is not None:
            if draft.target.cue_id != cue.id or draft.target.layer != 'original':
                return False
            self.subtitle_edit_input.setPlainText(value)
            self._flush_caption_editor_preview()
            return True
        if value == cue.text:
            self._confirm_current_review()
            return False
        from ..subtitle_rules.current_issues import current_issue_view
        from .caption_editor import IssueDecisionsCommand
        types={'model_disagreement','suspected_word'}
        before={r.issue_id for r in current_issue_view(self.project).for_cue(cue.id,layer='original') if r.kind in types}
        self.undo_stack.beginMacro('采用完整原文候选')
        try:
            self.undo_stack.push(AdoptReviewCandidateCommand(self.project, cue.id, value, '',
                lambda: self._cue_changed(cue.id, columns=(3,4)), resolve_review=False,
                text_applied=lambda text: self._manual_text_baselines.__setitem__(cue.id, text)))
            changes={r.issue_id:dict(status='resolved',input_version=r.input_version)
                     for r in current_issue_view(self.project).records if r.cue_id==cue.id and r.issue_id in before}
            if changes:self.undo_stack.push(IssueDecisionsCommand(self.project,changes,
                lambda:self._caption_issue_decisions_changed(cue.id)))
        finally:self.undo_stack.endMacro()
        return True


    def _adopt_review_candidate(self, index: int, *, binding=None) -> None:
        current=getattr(self,'_review_suggestions_binding',None)
        if binding is not None and binding!=current:return
        active=self._cue_lookup.get(self.selected_cue_id)
        if current is None or active is None:return
        if current[:6]!=(id(self.project),self.session.generation,active.id,active.text,active.start_ms,active.end_ms):return
        candidates = getattr(self, "_review_candidates", ())
        if not 0 <= int(index) < len(candidates):
            return
        candidate = candidates[int(index)]
        if candidate.context_only:
            bind_text(self.save_state, '这是原始段落上下文，不能直接替换当前字幕；请结合原音编辑。')
            return
        if not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        if cue is None:
            return
        previous_row = self.cue_model.row_for_cue_id(cue.id)
        if self._adopt_model_text(candidate.text, " · ".join(candidate.sources)):
            bind_text(self.save_state, '已采用候选 {value0}；其他问题保留', value0=int(index) + 1)
            self._refresh_review_summary_strip()

    # click-to-fix marks on card 1 (2026-10-15) ------------------------------
    def _review_suggestions_for(self, cue: StudioCue, candidates) -> tuple:
        """Marks for the current caption: other recognizers' local differences,
        confirmed glossary aliases and (Chinese projects) 他/她/它."""
        from ..subtitle_rules.language_rules import EN, JA, project_language
        from ..subtitle_rules.review_suggestions import review_suggestions
        try:
            language = project_language(self.project)
        except Exception:
            language = ""
        others = [(candidate.text, tuple(candidate.sources or ())) for candidate in tuple(candidates)[1:]
                  if not candidate.context_only]
        try:
            rows = tuple(review_suggestions(cue.text, others, resolver=self._review_term_resolver(),
                                             pronouns=language in ("", "zh")))
            from ..subtitle_rules.current_issues import DECISIONS, suggestion_handled
            target = self._resolve_caption_edit_target(cue.id, 'original')
            decisions = self.project.studio_state.get(DECISIONS, {})
            return tuple(row for row in rows if target is not None and not suggestion_handled(target.__dict__,row,cue.text,decisions))
        except Exception:  # marks are a convenience; review itself must keep working
            return ()

    def _review_term_resolver(self):
        """TermResolver over the project's glossaries, rebuilt when they change on disk."""
        project = self.project
        ids = tuple(str(item) for item in (getattr(project, "glossary_ids", None) or ()) if str(item).strip())
        if not ids:
            return None
        import os
        import subtitle_core as legacy
        try:
            stamp = os.stat(legacy.LEARNED_TERMS_PATH).st_mtime_ns
        except OSError:
            stamp = 0
        # 繁體 project (2026-10-19): 简体 glossary terms match 繁體 captions, marks offer 繁體.
        from ..subtitle_rules.chinese_script import glossary_script
        script = glossary_script(project)
        cached = getattr(self, "_review_term_resolver_cache", None)
        if cached is not None and cached[0] == (ids, stamp, script):
            return cached[1]
        from ..glossary.terminology import TermResolver, snapshot_glossaries
        try:
            resolver = TermResolver(snapshot_glossaries(legacy, ids), script=script)
        except Exception:
            resolver = None
        self._review_term_resolver_cache = ((ids, stamp, script), resolver)
        return resolver

    def _apply_review_suggestion(self, mark: int, option: int = 0, *, binding=None) -> bool:
        """One mark's option written into the caption as a user edit (undoable);
        review stays on this caption so several marks can be fixed."""
        suggestions = getattr(self, "_review_suggestions", ())
        cue = self._cue_lookup.get(self.selected_cue_id) if self.project else None
        current=getattr(self,'_review_suggestions_binding',None)
        if (current is None or cue is None or current[:6]!=(id(self.project),self.session.generation,cue.id,cue.text,cue.start_ms,cue.end_ms)
                or binding is not None and binding!=current):return False
        if cue is None or not 0 <= int(mark) < len(suggestions):
            return False
        row = suggestions[int(mark)]
        draft = getattr(self, '_caption_draft', None)
        if draft is not None:
            if draft.target.cue_id != cue.id or draft.target.layer != 'original':
                return False
            matching = next((i for i, value in enumerate(draft.suggestions) if value == row), -1)
            return self._apply_editor_suggestion(matching, option) if matching >= 0 else False
        if not 0 <= int(option) < len(row.options):
            return False
        value = row.apply(cue.text, int(option))
        if value == cue.text or not value.strip():
            return False
        target=self._resolve_caption_edit_target(cue.id,'original')
        if not self._commit_target_text_patch(target,row.start,row.end,row.options[int(option)].text,
                kind=row.kind,options={row.original,*(o.text for o in row.options)},label=tr('审核改字')):
            return False
        self._remember_canvas_edit_target(cue.id,'original')
        bind_text(self.save_state, '已改为「{new}」· {key} 撤销', new=row.options[int(option)].text or "∅",
                  key=self._shortcut_key_text("undo"))
        self._refresh_review_summary_strip()
        return True

    def _show_review_suggestion_menu(self, mark: int, global_pos, *, binding=None) -> None:
        current=getattr(self,'_review_suggestions_binding',None)
        if binding is not None and binding!=current:return
        suggestions = getattr(self, "_review_suggestions", ())
        if not 0 <= int(mark) < len(suggestions):
            return
        row = suggestions[int(mark)]
        menu = create_studio_menu(self)
        for index, option in enumerate(row.options):
            sources = " · ".join(option.sources)
            caption = f"「{row.original or '∅'}」→「{option.text or '∅'}」" + (f"  ({sources})" if sources else "")
            action = menu.addAction(caption)
            action.triggered.connect(lambda _checked=False,value=index,bound=current:self._apply_review_suggestion(mark,value,binding=bound))
        menu.exec(global_pos)

    def _flip_review_pronouns(self) -> bool:
        if getattr(self, '_caption_draft', None) is not None:
            return self._flip_editor_pronoun()
        target = self._resolve_caption_edit_target()
        if target is None:
            return False
        from ..subtitle_rules.pronouns import pronoun_positions, toggle_pronoun
        text = target.read(self.project)
        positions = pronoun_positions(text)
        if len(positions) != 1:
            self._open_caption_editor()
            self.caption_editor_hint.setText('请选中一个人称，或将光标放到该人称旁，再按 Shift+P')
            return False
        at = positions[0]
        value = text[:at] + toggle_pronoun(text[at]) + text[at+1:]
        if target.track_id in self.timeline.locked_speakers:
            return False
        changed=self._commit_target_text_patch(target,at,at+1,toggle_pronoun(text[at]),
            kind='pronoun',options=('他','她','它'),label='切换目标人称')
        if changed:
            bind_text(self.save_state, '人称已切换 · {key} 撤销', key=self._shortcut_key_text('undo'))
        return changed

    def _advance_review_after_resolution(self, previous_row: int, *, play: bool = False) -> None:
        session = getattr(self, "_review_session", None)
        if self._review_mode and session is not None:
            current_id = self.selected_cue_id
            session.resolve(current_id)
            next_id = session.next_id(current_id,eligible_ids=(self.cue_model.cue_at(i).id for i in range(self.cue_model.rowCount())))
            if next_id:
                self._select_review_cue_immediately(next_id,play=play)
            else:
                bind_text(self.review_queue_label, '审核完成  {value0} / {value1}', value0=session.completed, value1=session.total)
            return
        if not self._review_mode or self.cue_model.filter_status not in {"priority", "critical"}:
            return
        self.cue_model.refresh()
        self._refresh_cue_list_summary()
        if not self.cue_model.rowCount():
            return
        next_row = max(0, min(self.cue_model.rowCount() - 1, previous_row))
        self.select_cue(self.cue_model.cue_at(next_row).id)
        if play or self.continuous_review_toggle.isChecked():
            self._play_review_context()
