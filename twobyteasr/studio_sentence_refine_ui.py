"""AI 断句/句内节奏优化的页面接线（2026-09-18 III）。

入口：时间轴工具栏"AI 断句"菜单（选中范围试跑 / 全工程）。LLM 在 QThread
执行；结果按 SpliceCuesCommand 逐 cue 换血并包进单个撤销宏；已处理 cue
记入 studio_state 幂等集合，重复运行跳过。LLM 失败保留原文并显示真实错误。
"""

from __future__ import annotations
from .i18n import bind_text, tr

from PySide6.QtCore import QThread, Signal

from .sentence_refine import build_replacement_cues, refine_cues_with_llm


class SentenceRefineWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, cues, project, runtime_settings, parent=None) -> None:
        super().__init__(parent)
        self._cues = list(cues)
        self._project = project
        self._settings = runtime_settings

    def run(self) -> None:
        try:
            from .processes import process_action_scope

            with process_action_scope("studio.sentence-refine"):
                outcome = refine_cues_with_llm(
                    self._cues,
                    project=self._project,
                    runtime_settings=self._settings,
                    cancel_check=self.isInterruptionRequested,
                )
        except Exception as exc:  # LLM/网络/解析失败：保留原文，真实上报
            self.failed.emit(" ".join(str(exc).split())[:300])
            return
        self.finished_ok.emit(outcome)


class StudioSentenceRefineMixin:
    def _refined_cue_id_set(self) -> set[str]:
        state = (self.project.studio_state if self.project else {}).get("ai_sentence_refine") or {}
        return {str(item) for item in state.get("processed_cue_ids", [])}

    def _mark_refined_cue_ids(self, cue_ids) -> None:
        if not self.project or not cue_ids:
            return
        state = dict(self.project.studio_state.get("ai_sentence_refine") or {})
        known = {str(item) for item in state.get("processed_cue_ids", [])}
        known.update(str(item) for item in cue_ids)
        state["processed_cue_ids"] = sorted(known)
        state["last_run_note"] = "拆分段时间为估算值（无词级证据）" if getattr(self, "_refine_last_estimated", False) else ""
        self.project.studio_state["ai_sentence_refine"] = state

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

    def run_sentence_refine(self, *, whole_project: bool) -> None:
        if self.project is None:
            return
        if getattr(self, "_refine_worker", None) is not None and self._refine_worker.isRunning():
            bind_text(self.save_state, tr('AI 断句进行中…'))
            return
        cues = self._collect_refine_scope(whole_project)
        if not cues:
            bind_text(self.save_state, tr('AI 断句：没有可处理的新字幕'))
            return
        from .settings import load_runtime_settings

        settings = load_runtime_settings()
        settings = settings[0] if isinstance(settings, tuple) else settings
        worker = SentenceRefineWorker(cues, self.project, settings, self)
        worker.finished_ok.connect(lambda outcome, cues=cues: self._apply_sentence_refine(outcome, cues))
        worker.failed.connect(self._sentence_refine_failed)
        self._refine_worker = worker
        bind_text(self.save_state, tr('AI 断句中… {value0} 条{value1}', value0=len(cues), value1=tr('（全工程）' if whole_project else '（选中范围）')))
        worker.start()

    def _sentence_refine_failed(self, message: str) -> None:
        self._refine_worker = None
        bind_text(self.save_state, tr('AI 断句失败，已保留原文：{value0}', value0=message[:80]))
        self._studio_trace("SentenceRefineFailed", message=message[:200])

    def _apply_sentence_refine(self, outcome, cues) -> None:
        self._refine_worker = None
        if self.project is None:
            return
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
                    from .cue_word_alignment import cue_words
                    timing_skipped.append((cue.id, cue_words(self.project, cue)[1]))
                continue
            if action.action == "split" and action.estimated_timing:
                estimated_any = True
            replacements.append((index_of[cue.id], replacement))
        self._refine_last_estimated = estimated_any
        if not replacements:
            if timing_skipped:
                bind_text(self.save_state, tr('AI 断句：{value0} 条缺少可匹配的字词边界，保留原字幕，请试听后手动切分', value0=len(timing_skipped)))
                self._studio_trace('SentenceRefineTimingSkipped', cues=timing_skipped)
                return
            note = tr("（{count} 条建议被护栏拒绝）", count=outcome.rejected) if outcome.rejected else ""
            bind_text(self.save_state, tr('AI 断句完成：无需调整 {value0}', value0=note))
            self._mark_refined_cue_ids([cue.id for cue in cues])
            return
        from .studio_commands import SpliceCuesCommand
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
        split_count = sum(1 for _i, rep in replacements if len(rep) > 1)
        space_count = len(replacements) - split_count
        estimate_note = tr(" · {count} 条时间证据不足，未拆分", count=len(timing_skipped)) if timing_skipped else ""
        bind_text(self.save_state, tr('AI 断句完成：拆分 {value0} 条 · 节奏空格 {value1} 条 · 拒绝 {value2}{value3}', value0=split_count, value1=space_count, value2=outcome.rejected, value3=estimate_note))
        self._studio_trace(
            "SentenceRefineApplied",
            cues=len(cues), splits=split_count, spaces=space_count,
            rejected=outcome.rejected, estimated_timing=bool(estimated_any),
        )
