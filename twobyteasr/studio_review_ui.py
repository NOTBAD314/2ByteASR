"""Review presentation behavior for Subtitle Studio."""

from __future__ import annotations

import difflib
import html
from datetime import datetime, timezone
from time import perf_counter

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from .studio_cards import ReviewCandidateCard
from .studio_commands import AdoptReviewCandidateCommand
from .studio_project import StudioCue
from .studio_qc import QCResult, QCSeverity, review_candidates
from .studio_review import (
    REVIEW_NEXT_GUARD_MS,
    REVIEW_TAIL_MS,
    ReviewEvidenceAggregator,
    ReviewPlayback,
    cached_qc_result,
    cached_review_risks,
    review_playback_window,
    review_risks_from_qc,
)
from .studio_runtime_state import state_for
from .studio_theme import create_studio_menu
from .design.components import format_model_evidence_coverage

from .i18n import bind_text

from .i18n import tr


class StudioReviewMixin:
    def _set_cue_filter(self, status: str) -> None:
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
        for key, caption in (("all", "全部"), ("priority", "建议确认"), ("critical", "仅需要检查"), ("pending", "待确认"), ("issue", "有问题"), ("done", "已完成")):
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
        if not self.project or not self.project.cues:
            return
        row = min(len(self.project.cues), max(1, self.jump_spin.value())) - 1
        cue = self.project.cues[row]
        self.select_cue(cue.id)
        self._seek(cue.start_ms / 1000.0)

    def _step_cue(self, delta: int) -> None:
        if not self.project or not self.cue_model.rowCount():
            return
        index = self.cue_model.row_for_cue_id(self.selected_cue_id)
        index = 0 if index < 0 else index
        target = min(self.cue_model.rowCount() - 1, max(0, index + int(delta)))
        cue = self.cue_model.cue_at(target)
        self.select_cue(cue.id)
        self._seek(cue.start_ms / 1000.0)


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
        candidates = review_candidates(self.project, cue)
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
            reason = "来源范围信息缺失，现有记录需要恢复或结合音频确认"
        elif aggregate.source_coverage.get('coverage_unknown'):
            reason = "原始来源已保留，字级覆盖待核验；可对照下方原文与音频"
        elif aggregate.source_coverage.get('partial'):
            reason = "不同文本范围的独立来源覆盖不同，请检查缺少覆盖的部分"
        elif len(candidates) > 1:
            reason = "模型输出存在文本差异，请选择更可信的文本"
        else:
            reason = "当前没有需要人工处理的问题"
        self.review_reason_label.setText(reason)
        if hasattr(self, "review_dock_candidate_layout"):
            speaker_only = bool(aggregate.speaker_only and aggregate.models_agree_text)
            card_mode = (not speaker_only and len(candidates) > 1
                         and not (aggregate.boundary_only and not aggregate.requires_review))
            # The row has a fixed height (studio_workspace.REVIEW_DOCK_ROW_HEIGHT):
            # up to four cards share it when there is room, the rest scrolls.
            width = max(self.review_summary_strip.width(), self.review_dock_candidates.width())
            columns = max(1, min(4, len(candidates[:4]), width // 260)) if card_mode else 1
            signature = (cue.id, cue.text, cue.speaker_id, speaker_only, card_mode, columns,
                         bool(aggregate.requires_review),
                         tuple((c.text, tuple(c.sources or ()), bool(c.context_only)) for c in candidates[:5]),
                         tuple(sorted(str(row.get("speaker_id") or row.get("speaker") or "")
                                      for row in aggregate.hypotheses)) if speaker_only else (),
                         format_model_evidence_coverage(aggregate.hypotheses)['display'] if not card_mode else "")
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
                    from .studio_qc import normalize_candidate_text
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
                    )
                    card.clicked.connect(lambda row=index: self._adopt_review_candidate(row))
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
                banner = QLabel(
                    f"{coverage['headline']} · 建议确认"
                    if aggregate.requires_review or coverage['missing'] or coverage['partial']
                    else f"{coverage['headline']} · 无冲突证据"
                )
                banner.setText(banner.text() + '\n' + coverage['display'])
                banner.setWordWrap(True)
                banner.setObjectName("checkWarning" if aggregate.requires_review else "checkPass")
                self.review_dock_candidate_layout.addWidget(banner, 0, 0, 1, columns)

    def _set_review_mode(self, enabled: bool) -> None:
        entering = bool(enabled) and not self._review_mode
        leaving = not bool(enabled) and self._review_mode
        if entering or leaving:
            self._release_review_playback()
        if entering:
            from .studio_review import ReviewScopeSnapshot, ReviewSession

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
            self.cue_model.set_scope_ids(None)
            if session is not None:
                self.cue_model.set_filter(session.scope.filter_mode)
                self.cue_model.set_query(session.scope.search_query)
            self._review_session = None
        if not self._review_mode:
            return
        if self.cue_model.rowCount():
            if self.cue_model.row_for_cue_id(self.selected_cue_id) < 0:
                self.select_cue(self.cue_model.cue_at(0).id)
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
    _QC_SCAN_MINI = 16
    _QC_SCAN_BUDGET_S = 0.012

    def _start_chunked_qc_scan(self, *, sync: bool = False) -> None:
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
        if self.selected_cue_id:
            cue = self._cue_lookup.get(self.selected_cue_id)
            if cue is not None:
                self._refresh_current_review_context(cue)



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
        if not self.project or not self.selected_cue_id:
            return
        statuses = self.project.studio_state.setdefault("cue_statuses", {})
        confirmations = self.project.studio_state.setdefault("review_confirmations", {})
        if not isinstance(statuses, dict) or not isinstance(confirmations, dict):
            return
        previous_row = self.cue_model.row_for_cue_id(self.selected_cue_id)
        started=perf_counter()
        current_id=self.selected_cue_id
        statuses[self.selected_cue_id] = "done"
        confirmations[self.selected_cue_id] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.project.studio_state.setdefault('manual_caption_text', {})[current_id]=self._cue_lookup[current_id].text
        bind_text(self.save_state, '未保存')
        self._schedule_autosave()
        self.cue_model.refresh_cue(current_id, (4,))
        bind_text(self.save_state, '✓ 已确认 · 下一条优先字幕')
        # Preserve the established Enter behavior: confirming a priority
        # review removes it from the queue and advances to the next item.
        # Ctrl+Enter follows this same path and additionally requests playback.
        session = getattr(self, "_review_session", None)
        if self._review_mode and session is not None:
            session.resolve(self.selected_cue_id)
            next_id = session.next_id(self.selected_cue_id)
            if next_id:
                self._select_review_cue_immediately(next_id,play=play_next)
            else:
                bind_text(self.review_queue_label, '审核完成  {value0} / {value1}', value0=session.completed, value1=session.total)
            profile=getattr(self,'_review_enter_profile',[])
            profile.append({'cue_id':current_id,'next_id':next_id,'selection_ms':(perf_counter()-started)*1000,
                'autosave':'debounced','ass':'unchanged','waveform':'unchanged','thumbnail':'unchanged'})
            self._review_enter_profile=profile[-200:]
            return
        if self.cue_model.filter_status in {"priority", "critical"} and self.cue_model.rowCount():
            def advance() -> None:
                if self.cue_model.filter_status not in {"priority", "critical"} or not self.cue_model.rowCount():
                    return
                # The confirmed cue is removed from the filtered model. Its
                # former row index therefore points at the next chronological
                # visible item after refresh.
                next_row = max(0, min(self.cue_model.rowCount() - 1, previous_row))
                next_cue = self.cue_model.cue_at(next_row)
                self.select_cue(next_cue.id)
                if play_next or self.continuous_review_toggle.isChecked():
                    self._play_review_context()
            advance()

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
            next_id = session.next_id(self.selected_cue_id, include_resolved=True)
            if next_id:
                self.select_cue(next_id)
            return
        if self.cue_model.filter_status not in {"priority", "critical"}:
            self._activate_filter("priority")
        rows = self.cue_model.rowCount()
        if rows <= 1:
            return
        current = self.cue_model.row_for_cue_id(self.selected_cue_id)
        next_row = (max(0, current) + 1) % rows
        self.select_cue(self.cue_model.cue_at(next_row).id)
        if self.continuous_review_toggle.isChecked():
            self._play_review_context()

    def _adopt_model_text(self, value: str, label: str) -> bool:
        if not self.project or not self.selected_cue_id:
            return False
        cue_id = self.selected_cue_id
        cue = self._cue_lookup.get(cue_id)
        value = str(value or "").strip()
        if cue is None or not value:
            return False
        if value != cue.text:
            self._commit_manual_term_learning(cue_id)

        def changed() -> None:
            current = self._cue_lookup.get(cue_id)
            if current is not None:
                self._manual_text_baselines[cue_id] = current.text
            self._cue_changed(cue_id, columns=(3, 4))

        self.undo_stack.push(
            AdoptReviewCandidateCommand(
                self.project,
                cue_id,
                value,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                changed,
                text_applied=lambda text: self._manual_text_baselines.__setitem__(
                    cue_id, text
                ),
            )
        )
        bind_text(self.save_state, '✓ 已采用 {label}', label=label)
        return True

    def _adopt_review_candidate(self, index: int) -> None:
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
            bind_text(self.save_state, '✓ 已采用候选 {value0} · 下一条', value0=int(index) + 1)
            self._advance_review_after_resolution(previous_row)

    def _advance_review_after_resolution(self, previous_row: int, *, play: bool = False) -> None:
        session = getattr(self, "_review_session", None)
        if self._review_mode and session is not None:
            current_id = self.selected_cue_id
            session.resolve(current_id)
            next_id = session.next_id(current_id)
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
