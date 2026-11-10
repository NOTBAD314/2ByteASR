"""AI 断句/句内节奏优化的页面接线（2026-09-18 III）。

入口：时间轴工具栏"AI 断句"菜单（选中范围试跑 / 全工程）。LLM 在 QThread
执行；结果按 SpliceCuesCommand 逐 cue 换血并包进单个撤销宏；已处理 cue
记入 studio_state 幂等集合，重复运行跳过。LLM 失败保留原文并显示真实错误。
"""

from __future__ import annotations
import copy
from ..i18n import bind_text, tr

from PySide6.QtCore import QThread, Signal

from ..subtitle_rules.sentence_refine import build_replacement_cues, refine_cues_with_llm
from .studio_subtitle_tasks import StudioSubtitleTaskMixin


class SentenceRefineWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, cues, project, runtime_settings, parent=None) -> None:
        super().__init__(parent)
        self._cues = copy.deepcopy(list(cues))
        self._project = copy.deepcopy(project)
        self._settings = runtime_settings

    def run(self) -> None:
        try:
            from ..system.processes import process_action_scope

            from ..diagnostics.event_log import context
            with context(**getattr(self,"_diagnostic",{})), process_action_scope("studio.sentence-refine"):
                outcome = refine_cues_with_llm(
                    self._cues,
                    project=self._project,
                    runtime_settings=self._settings,
                    cancel_check=self.isInterruptionRequested,
                    on_progress=self.progress.emit,
                    boundary_only=True,
                )
        except Exception as exc:  # LLM/网络/解析失败：保留原文，真实上报
            from ..diagnostics.event_log import emit, exception_info
            emit("background.failure",level="ERROR",result="failed",exception=exception_info(exc),**getattr(self,"_diagnostic",{}))
            self.failed.emit(" ".join(str(exc).split())[:300])
            return
        self.finished_ok.emit(outcome)


class StudioSentenceRefineMixin(StudioSubtitleTaskMixin):
    def _persist_refine_status(self):
        if self.project is None:return
        from ..projects.studio_runtime_state import state_for,DirtyDomain
        with state_for(self.project).transaction(self.project,action_id='记录断句任务状态',
                dirty=DirtyDomain.PROJECT_METADATA|DirtyDomain.AUTOSAVE,snapshot_cues=False):pass

    def _refined_cue_id_set(self) -> set[str]:
        state = (self.project.studio_state if self.project else {}).get("ai_sentence_refine") or {}
        if self.project is None:
            return set()
        from ..subtitle_rules.sentence_refine_ranges import input_version
        versions = state.get('processed_versions', {})
        configuration = self._refine_configuration()
        return {cue.id for cue in self.project.cues
                if versions.get(cue.id) == input_version([cue], self.project, configuration)}

    def _refine_configuration(self):
        from ..storage.settings import load_runtime_settings
        from ..subtitle_rules.sentence_refine_ranges import refine_glossary_snapshot
        from ..subtitle_rules.segmentation_profiles import project_language_tag, profile_for
        from ..subtitle_rules.grouping_request import custom_grouping_guidance
        from ..playback.audio_graph import audio_graph_signature
        settings = load_runtime_settings()
        settings = settings[0] if isinstance(settings, tuple) else settings
        return [settings.get('models', {}), project_language_tag(self.project),
                profile_for(project_language_tag(self.project)).fingerprint, custom_grouping_guidance(project_language_tag(self.project)),
                list(self.project.glossary_ids), refine_glossary_snapshot(self.project).digest,
                audio_graph_signature(self.project)[1:], self.project.media.path, self.project.media.duration_ms]

    def _mark_refined_cue_ids(self, cue_ids, *, configuration=None) -> None:
        if not self.project or not cue_ids:
            return
        state = dict(self.project.studio_state.get("ai_sentence_refine") or {})
        known = {str(item) for item in state.get("processed_cue_ids", [])}
        known.update(str(item) for item in cue_ids)
        state["processed_cue_ids"] = sorted(known)
        from ..subtitle_rules.sentence_refine_ranges import input_version
        configuration = self._refine_configuration() if configuration is None else configuration
        versions = state.setdefault('processed_versions', {})
        targets = set(cue_ids)
        for cue in self.project.cues:
            if cue.id in targets:
                versions[cue.id] = input_version([cue], self.project, configuration)
        state["last_run_note"] = "拆分段时间为估算值（无词级证据）" if getattr(self, "_refine_last_estimated", False) else ""
        self.project.studio_state["ai_sentence_refine"] = state
        self._persist_refine_status()

    def _collect_refine_scope(self, whole_project: bool):
        if self.project is None:
            return []
        processed = self._refined_cue_id_set()
        if whole_project:
            return [cue for cue in self.project.cues if cue.id not in processed]
        # 选中范围：字幕表多选 + 时间线选段 + 当前选中 cue
        selected: list[str] = []
        table = getattr(self, "cue_table", None)
        model = getattr(table, "model", lambda: None)()
        if table is not None and model is not None:
            from PySide6.QtCore import Qt as _Qt
            for row in table.selectionModel().selectedRows():
                cue_id = model.data(model.index(row.row(), 0), _Qt.ItemDataRole.UserRole)
                if cue_id:
                    selected.append(str(cue_id))
        selected.extend(str(item) for item in getattr(self.timeline, "selected_segment_ids", ()) or ())
        if getattr(self, "selected_cue_id", ""):
            selected.append(str(self.selected_cue_id))
        lookup = {cue.id: cue for cue in self.project.cues}
        seen: set[str] = set()
        scoped = []
        for cue_id in selected:
            cue = lookup.get(cue_id)
            if cue is not None and cue_id not in seen and cue_id not in processed:
                seen.add(cue_id)
                scoped.append(cue)
        scoped.sort(key=lambda cue: cue.start_ms)
        return scoped

    def run_sentence_refine(self, *, whole_project: bool, retry_failed: bool = False, retry_ids=None) -> None:
        if self.project is None:
            return
        if getattr(self, "_refine_worker", None) is not None and self._refine_worker.isRunning():
            bind_text(self.save_state, tr('AI 断句进行中…'))
            return
        cues = self._collect_refine_scope(whole_project)
        if retry_failed:
            failed = set((self.project.studio_state.get('ai_sentence_refine') or {}).get('failed_cue_ids', ()))
            cues = [cue for cue in self.project.cues if cue.id in failed]
        if retry_ids is not None:
            cues = [cue for cue in self.project.cues if cue.id in set(retry_ids)]
        if not cues:
            bind_text(self.save_state, tr('AI 断句：没有可处理的新字幕'))
            return
        from ..storage.settings import load_runtime_settings

        settings = load_runtime_settings()
        settings = settings[0] if isinstance(settings, tuple) else settings
        from ..providers.llm_config import text_ai_key_missing
        if text_ai_key_missing(settings, "group"):
            # 2026-10-15: no key → explain instead of a failed run; nothing is sent.
            bind_text(self.save_state, 'AI 断句没有运行：还没填 API Key')
            self._studio_trace("SentenceRefineNeedsKey", cues=len(cues))
            from ..app.api_key_explainer import offer_api_key_help
            offer_api_key_help(self)
            return
        task = self._new_subtitle_task('AI 断句', cues)
        task.configuration = self._refine_configuration()
        self._refine_task = task
        self._refine_origin_project = self.project
        self._refine_origin_cues = {cue.id:(cue.text,cue.start_ms,cue.end_ms,cue.speaker_id) for cue in cues}
        from ..diagnostics.studio_events import background_ticket
        self._refine_diagnostic = background_ticket(self.project,"sentence_refine",ids=(cue.id for cue in cues))
        worker = SentenceRefineWorker(cues, self.project, settings, self)
        worker._diagnostic = self._refine_diagnostic
        worker.progress.connect(lambda event, task=task: self._subtitle_task_event(dict(task_id=task.task_id, event=event)))
        worker.finished_ok.connect(lambda outcome, cues=cues, task=task: self._apply_sentence_refine(outcome, cues, task=task))
        worker.failed.connect(lambda message, task=task: self._sentence_refine_failed(message, task=task))
        worker.finished.connect(worker.deleteLater)
        task.cancel_action = worker.requestInterruption
        self._refine_worker = worker
        bind_text(self.save_state, tr('AI 断句中… {value0} 条{value1}', value0=len(cues), value1=tr('（全工程）' if whole_project else '（选中范围）')))
        worker.start()

    def cancel_sentence_refine(self):
        worker = getattr(self, '_refine_worker', None)
        if worker is not None and worker.isRunning():
            task = getattr(self, '_refine_task', None)
            if task:
                self._cancel_subtitle_task(task.task_id)
            else:
                worker.requestInterruption()
            bind_text(self.save_state, '正在取消 AI 断句…')

    def _sentence_refine_failed(self, message: str, *, task=None) -> None:
        if task is not None and task is not getattr(self, '_refine_task', None):
            return
        self._refine_worker = None
        if task:
            for key in task.cue_ids:
                task.update(dict(range_id=key, cue_ids=[key], status='cancelled' if task.cancelled else 'failed',
                                 error=message, phase='已取消' if task.cancelled else '请求失败'))
            task.finish(cancelled=task.cancelled)
        if self.project is not getattr(self, '_refine_origin_project', self.project):
            return
        if self.project is not None:
            self.project.studio_state.setdefault('ai_sentence_refine', {}).update(
                last_status='cancelled' if task and task.cancelled else 'failed', last_error=message[:300],
                failed_cue_ids=sorted(getattr(self, '_refine_origin_cues', {})))
        if task and task.cancelled:
            self.save_state.setText(task.summary())
            return
        bind_text(self.save_state, tr('AI 断句失败，已保留原文：{value0}', value0=message[:80]))
        self._studio_trace("SentenceRefineFailed", message=message[:200])
        self._persist_refine_status()

    def _apply_sentence_refine(self, outcome, cues, *, task=None) -> None:
        if task is not None:
            return self._commit_sentence_refine_task(outcome, cues, task)
        self._refine_worker = None
        from ..diagnostics.studio_events import background_result
        ticket = getattr(self,"_refine_diagnostic",{})
        if self.project is None:
            background_result(ticket,self.project,decision="discarded_no_project")
            return
        if self.project is not getattr(self, '_refine_origin_project', self.project):
            background_result(ticket,self.project,decision='discarded_project_changed')
            self._studio_trace('SentenceRefineDiscarded', reason='project_changed')
            return
        if outcome.llm_status == 'cancelled':
            background_result(ticket,self.project,decision='cancelled',cancelled=True)
            bind_text(self.save_state, 'AI 断句已取消，保留原字幕')
            return
        current = {cue.id:cue for cue in self.project.cues}
        stale = {key for key, value in getattr(self, '_refine_origin_cues', {}).items()
            if key not in current or (current[key].text,current[key].start_ms,current[key].end_ms,current[key].speaker_id)!=value}
        background_result(ticket,self.project,decision="partially_accepted" if stale else "accepted",stale_ids=stale)
        cues = [cue for cue in cues if cue.id not in stale]
        state = self.project.studio_state.setdefault('ai_sentence_refine', {})
        state.update(last_status=outcome.llm_status, requests=outcome.requests,
            failed_cue_ids=sorted(set(outcome.failed_cue_ids)|stale), last_error=outcome.llm_error)
        self._studio_trace('SentenceRefineResponse', status=outcome.llm_status, requests=outcome.requests,
            stale_ids=sorted(stale), failed_ids=outcome.failed_cue_ids)
        actions = {action.cue_id: action for action in outcome.actions}
        index_of = {cue.id: position for position, cue in enumerate(self.project.cues)}
        used_ids = {cue.id for cue in self.project.cues}
        replacements: list[tuple[int, list]] = []
        estimated_any = False
        timing_skipped = []
        for cue in cues:
            action = actions.get(cue.id)
            if action is None:
                continue
            replacement = build_replacement_cues(cue, action, project=self.project, used_ids=used_ids)
            if not replacement:
                if action.action == 'split' and action.estimated_timing:
                    from ..recognition.cue_word_alignment import cue_words
                    timing_skipped.append((cue.id, cue_words(self.project, cue)[1]))
                continue
            if action.action == "split" and action.estimated_timing:
                estimated_any = True
            replacements.append((index_of[cue.id], replacement))
        self._refine_last_estimated = estimated_any
        state['failed_cue_ids'] = sorted(set(state['failed_cue_ids']) | {key for key, _ in timing_skipped})
        if state['failed_cue_ids']:
            state['last_status'] = 'partial' if replacements else 'failed'
        if timing_skipped:
            state['application_errors'] = dict(timing_skipped)
        self._persist_refine_status()
        if not replacements:
            if outcome.failed_cue_ids or stale:
                bind_text(self.save_state, 'AI 断句未完成：{value0} 条保留原文，可从字幕菜单仅重试失败范围', value0=len(set(outcome.failed_cue_ids)|stale))
                return
            if timing_skipped:
                bind_text(self.save_state, tr('AI 断句：{value0} 条缺少可匹配的字词边界，保留原字幕，请试听后手动切分', value0=len(timing_skipped)))
                self._studio_trace('SentenceRefineTimingSkipped', cues=timing_skipped)
                return
            note = tr("（{count} 条建议被护栏拒绝）", count=outcome.rejected) if outcome.rejected else ""
            bind_text(self.save_state, tr('AI 断句完成：无需调整 {value0}', value0=note))
            self._mark_refined_cue_ids([a.cue_id for a in outcome.actions if a.action == 'keep'])
            return
        from ..timeline.studio_commands import SpliceCuesCommand
        stack = self.undo_stack
        stack.beginMacro(f"AI 断句优化（{len(replacements)} 条）")
        applied_new_ids: list[str] = []
        # 索引降序下推：先 splice 会使其后 cue 的位置 +1，降序不受影响。
        for index, replacement in sorted(replacements, key=lambda item: -item[0]):
            stack.push(SpliceCuesCommand(
                self.project, index, 1, replacement,
                f"AI 断句：{replacement[0].text[:12]}…",
                self._changed,
            ))
            applied_new_ids.extend(cue.id for cue in replacement)
        stack.endMacro()
        self._mark_refined_cue_ids(applied_new_ids)
        state['failed_cue_ids'] = sorted(set(state['failed_cue_ids']) | {key for key, _ in timing_skipped})
        split_count = sum(1 for _i, rep in replacements if len(rep) > 1)
        space_count = len(replacements) - split_count
        estimate_note = tr(" · {count} 条时间证据不足，未拆分", count=len(timing_skipped)) if timing_skipped else ""
        bind_text(self.save_state, tr('AI 断句完成：拆分 {value0} 条 · 节奏空格 {value1} 条 · 拒绝 {value2}{value3}', value0=split_count, value1=space_count, value2=outcome.rejected, value3=estimate_note))
        if state['failed_cue_ids']:
            self.save_state.setText(f'AI 断句部分完成：拆分 {split_count} 条 · {len(state["failed_cue_ids"])} 条未完成，保留原字幕，可重试失败范围')
        self._studio_trace(
            "SentenceRefineApplied",
            cues=len(cues), splits=split_count, spaces=space_count,
            rejected=outcome.rejected, estimated_timing=bool(estimated_any),
        )

    def _commit_sentence_refine_task(self, outcome, cues, task):
        from ..subtitle_rules.sentence_refine_ranges import input_version, build_range_replacement
        from ..subtitle_rules.sentence_refine_contract import RefineError
        if task is not getattr(self, '_refine_task', None):
            return
        self._refine_worker = None
        if not self._subtitle_task_current(task):
            task.finish(cancelled=True)
            if task.project is self.project and self.project is not None:
                self.project.studio_state.setdefault('ai_sentence_refine', {}).update(
                    last_status='cancelled', failed_cue_ids=list(task.cue_ids),
                    range_results=list(task.rows.values()), requests=outcome.requests,
                    elapsed_seconds=task.elapsed)
                self._persist_refine_status()
                self.save_state.setText(task.summary())
            return
        current = {cue.id: cue for cue in self.project.cues}
        positions = {cue.id: index for index, cue in enumerate(self.project.cues)}
        actions = {action.cue_id: action for action in outcome.actions}
        used_ids = set(current)
        configuration_changed = (getattr(task, 'configuration', None) is not None
                                 and task.configuration != self._refine_configuration())
        replacements = []
        planned = []
        kept_ids = []
        for unit in outcome.ranges:
            record = dict(outcome.results[unit.cue.id])
            originals = [current.get(cue.id) for cue in unit.originals]
            action = actions.get(unit.cue.id)
            if action is None:
                task.update(record)
                continue
            try:
                if configuration_changed:
                    raise RefineError('任务规则、模型或素材音轨已变化，旧结果已丢弃', 'stale_configuration')
                if (any(cue is None for cue in originals)
                        or input_version(originals, self.project) != record['input_version']
                        or [positions[cue.id] for cue in originals] != list(range(
                            positions[originals[0].id], positions[originals[0].id] + len(originals)))):
                    raise RefineError('运行期间字幕、时间、样式或来源已变化，旧结果已丢弃', 'stale_input')
                if action.action == 'keep':
                    record.update(status='unchanged', phase='已校验，无需调整',
                                  final_texts=[cue.text for cue in originals])
                    kept_ids.extend(cue.id for cue in originals)
                else:
                    replacement = build_range_replacement(unit, action, self.project, used_ids)
                    if not replacement:
                        raise RefineError('没有可写回的有效字幕，保留原文', 'writeback_error')
                    if ([(cue.text, cue.start_ms, cue.end_ms) for cue in replacement]
                            == [(cue.text, cue.start_ms, cue.end_ms) for cue in originals]):
                        record.update(status='unchanged', phase='已校验，无需调整',
                                      final_texts=[cue.text for cue in originals])
                        kept_ids.extend(cue.id for cue in originals)
                    else:
                        replacements.append((positions[originals[0].id], len(originals), replacement))
                        record.update(status='validated', phase='写回工程',
                                      final_texts=[cue.text for cue in replacement],
                                      output_ids=[cue.id for cue in replacement])
                        planned.append(record)
            except Exception as exc:
                record.update(status='failed', phase='保留原文',
                              category=getattr(exc, 'category', 'writeback_error'), error=str(exc))
            task.update(record)
        if replacements:
            try:
                from ..timeline.sentence_refine_command import RefineCuesCommand
                self.undo_stack.push(RefineCuesCommand(self.project, replacements, self._changed))
                for record in planned:
                    record.update(status='applied', phase='已校验并写回')
                    task.update(record)
            except Exception as exc:
                for record in planned:
                    record.update(status='failed', phase='写回失败', category='writeback_error', error=str(exc))
                    task.update(record)
        task.finish(cancelled=outcome.llm_status == 'cancelled')
        failures = sorted({key for row in task.rows.values() if row.get('status') in {'failed', 'review', 'cancelled'}
                           for key in row.get('cue_ids', ())})
        state = self.project.studio_state.setdefault('ai_sentence_refine', {})
        # Successful prior ranges remain retryable only through a new explicit scope.
        state.update(last_status='cancelled' if task.cancelled else 'partial' if failures else 'completed',
                     failed_cue_ids=failures, last_error=outcome.llm_error,
                     requests=outcome.requests, range_results=list(task.rows.values()), elapsed_seconds=task.elapsed)
        processed = [*kept_ids, *(key for record in planned if record['status'] == 'applied'
                                 for key in record.get('output_ids', ()))]
        self._mark_refined_cue_ids(processed, configuration=getattr(task, 'configuration', None))
        self.save_state.setText(task.summary() + ' · 点击任务进度查看详情')
        self._studio_trace('SentenceRefineTaskFinished', task_id=task.task_id, counts=task.counts())
