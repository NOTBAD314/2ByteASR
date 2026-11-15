"""Re-measure word timing of edited captions with the selected aligner (on demand).

When a caption's text was edited (by hand or AI), its stored word timing
belongs to the old text: Studio realigns the new text to the old measured
words where it can, and otherwise reports a missing alignment. This action
measures the caption's *current* text again on its own audio, taken with the
same audio graph the preview and the export use (edits, FLV content clock),
together with adjacent captions of the same speaker as context (see
``cue_forced_alignment.plan_runs``). The result replaces only the requested
captions' receipt words, as one undoable edit; timing, text and speaker do
not change.

2026-10-22 (MFA plan step 4): every language with an aligner (it was
Japanese only), the timeline's aligner (MFA when selected), and the cut
positions are graded like recognition does (``boundary_grades``: the other
aligner and pauses), so "split at the cursor" can use them right away.
"""
from __future__ import annotations

import copy
import subprocess
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand

PAD_MS = 300
SAMPLE_RATE = 16000


def _cue_pcm(project, cue_id, ffmpeg, pre_roll_ms=PAD_MS, post_roll_ms=PAD_MS):
    import numpy as np
    from ..playback.cue_audio_preview import plan_cue_preview, preview_command
    plan = plan_cue_preview(project, cue_id, pre_roll_ms=pre_roll_ms, post_roll_ms=post_roll_ms)
    command, _receipts = preview_command(plan, ffmpeg)
    # Same mix, delivered as the aligner's 16 kHz mono float input.
    command = list(command)
    command[command.index("-ac") + 1] = "1"
    command[command.index("-ar") + 1] = str(SAMPLE_RATE)
    command[command.index("s16le")] = "f32le"
    from ..system.processes import run_hidden_subprocess
    completed = run_hidden_subprocess(command, purpose="caption realignment audio", capture_output=True,
                                      timeout=120, check=True)
    return plan, np.frombuffer(completed.stdout, dtype="<f4").copy()


CONTEXT_MS = 2000


def _runs(project, cue_ids):
    """Alignment runs holding the requested captions; unchanged neighbours are context only."""
    from ..playback.cue_audio_preview import caption_timeline_range
    from ..recognition.cue_forced_alignment import plan_runs
    wanted = {str(cue_id) for cue_id in cue_ids}
    targets = [cue for cue in project.cues if cue.id in wanted]
    if not targets:
        return [], wanted
    near = [cue for cue in project.cues
            if any(cue.end_ms >= t.start_ms - CONTEXT_MS and cue.start_ms <= t.end_ms + CONTEXT_MS for t in targets)]
    from ..recognition.alignment_items import annotate_row
    source_parts=project.generation_metadata.get('segmentation_source_spans',{}).get('cues',{})
    rows = []
    for cue in near:
        _cue, (start, end), domain = caption_timeline_range(project, cue.id)
        # Captions on different clocks (projected vs source) are never joined.
        rows.append(annotate_row({"key": cue.id, "start_ms": start, "end_ms": end, "text": cue.text,
                     "speaker": f"{cue.speaker_id}|{domain}"},source_parts.get(cue.id,{}).get("parts"),material_id=str(project.project_id),track_id=domain))
    # Separate rendered items can cross edits/mixes; no acoustic merge is inferred from display adjacency.
    for row in rows: row['break_before']=True
    runs = [run for run in plan_runs(rows, pad_ms=PAD_MS) if wanted & {member["key"] for member in run["members"]}]
    return runs, wanted


def aligner_language(project) -> str | None:
    """The aligner's language name for this project (None: no aligner for it)."""
    from ..subtitle_rules.language_rules import project_language, qwen_language_name
    return qwen_language_name(project_language(project) if project is not None else "")


class _Quiet:
    """``legacy`` for the shared second-opinion helper: Studio keeps no run log."""

    @staticmethod
    def record_run_event(*_args, **_kwargs):
        return None


def _shifted(rows, shift):
    out = []
    for row in rows:
        moved = dict(row)
        for key in ("at_ms", "second_ms", "pause_ms"):
            if moved.get(key):
                moved[key] = [int(value) + shift for value in moved[key]]
        out.append(moved)
    return out


def measure(project, cue_ids, *, language=None, cancelled=None):
    """Selected runs share a disk-backed PCM; memory stays bounded by one run."""
    import numpy as np
    from pathlib import Path
    from ..recognition.asr import run_qwen_aligner_worker
    from ..recognition.alignment_audio import alignment_scratch
    from ..recognition.boundary_grades import SpeechBand, grade_caption
    from ..recognition.cue_forced_alignment import second_opinion, split_run_row
    from ..recognition.cache import record_run_event
    from .studio_video_track import ffmpeg_executable
    language = language or aligner_language(project) or "Japanese"
    ffmpeg = str(ffmpeg_executable())
    runs, wanted = _runs(project, cue_ids)
    jobs, plans, cursor = [], {}, 0
    with alignment_scratch() as directory:
        raw_path = Path(directory) / 'selected.f32'
        with raw_path.open('wb') as stream:
            for number, run in enumerate(runs, 1):
                if cancelled and cancelled():
                    return {}
                first = run["members"][0]
                plan, pcm = _cue_pcm(project, first["key"], ffmpeg,
                    pre_roll_ms=max(0, first["start_ms"] - run["window_start_ms"]),
                    post_roll_ms=max(0, run["window_end_ms"] - first["end_ms"]))
                if pcm.size < SAMPLE_RATE // 10:
                    continue
                start_sample=cursor
                start_ms = round(cursor * 1000 / SAMPLE_RATE)
                stream.write(memoryview(np.ascontiguousarray(pcm,dtype=np.float32)).cast('B'))
                cursor += pcm.size
                job_id = f"run-{number}"
                from ..recognition.alignment_items import run_provenance
                provenance=run_provenance(run)
                provenance["material_contiguous"]=False
                provenance["available_context_samples"]=[start_sample,cursor]
                provenance["window_samples"]=[start_sample,cursor]
                jobs.append(dict(id=job_id,window_start_ms=start_ms,
                    window_end_ms=round(cursor*1000/SAMPLE_RATE),text=run["text"],language=language,**provenance))
                plans[job_id] = (plan,start_ms,run)
                del pcm
                silence = np.zeros(SAMPLE_RATE//5,dtype=np.float32)
                stream.write(memoryview(silence).cast('B'));cursor += silence.size
                record_run_event('alignment_progress',engine='QWEN3-ALIGNER',worker_state='audio_prepared',
                                 done=number,total=len(runs),label='准备局部音频')
        if not jobs:
            return {}
        npy_path = Path(directory) / 'selected.npy'
        mapped = np.lib.format.open_memmap(npy_path,mode='w+',dtype=np.float32,shape=(cursor,))
        try:
            with raw_path.open('rb') as stream:
                for offset in range(0,cursor,1024*1024):
                    if cancelled and cancelled():
                        return {}
                    block=np.frombuffer(stream.read(min(1024*1024,cursor-offset)*4),dtype=np.float32)
                    mapped[offset:offset+block.size]=block
            mapped.flush()
        finally:
            mapped._mmap.close()
        audio = np.load(npy_path,mmap_mode='r',allow_pickle=False)
        try:
            payload=run_qwen_aligner_worker(audio,jobs)
            second=None if cancelled and cancelled() else second_opinion(audio,jobs,payload,_Quiet())
            second_rows={str(row.get("id")):row for row in (second or {}).get("results") or ()}
            engine="" if second is None else "mfa" if str(second.get("protocol") or "").startswith("mfa-") else "qwen3"
            out={}
            for row in payload.get("results") or ():
                plan,offset,run=plans[str(row["id"])]
                shift=plan.play_range_ms[0]-offset
                other=second_rows.get(str(row["id"]))
                other_parts=(split_run_row(other,run,edge_shift_ms=shift)
                    if other is not None and other.get("text")==run["text"] else [None]*len(run["members"]))
                # Pause evidence is local too, never a whole-live numpy square.
                window_start=int(row['window_start_ms'])
                band=SpeechBand(audio[window_start*16:int(row['window_end_ms'])*16])
                def pause(a,b,side='gap'):
                    value=band.pause(a-window_start,b-window_start,side)
                    return (value[0]+window_start,value[1]+window_start) if value is not None else None
                for member,part,other_part in zip(run["members"],split_run_row(row,run,edge_shift_ms=shift),other_parts):
                    if member["key"] not in wanted:
                        continue
                    check=other_part["segments"] if other_part and other_part["text"]==part["text"] else None
                    graded=_shifted(grade_caption(part["text"],part["segments"],check or None,pause),shift)
                    words=[]
                    for piece in part["segments"]:
                        a,b=int(piece["start_ms"])+shift,int(piece["end_ms"])+shift
                        if b>a:
                            words.append(dict(text=part["text"][int(piece["char_start"]):int(piece["char_end"])],
                                char_start=int(piece["char_start"]),char_end=int(piece["char_end"]),
                                start_ms=a,end_ms=b,evidence_ref="realign:"+str(member["key"]),
                                granularity=piece.get("granularity"),start_basis=piece.get("start_basis"),end_basis=piece.get("end_basis")))
                    from ..recognition.alignment_measurements import effective_metadata
                    effective=effective_metadata(payload,row)
                    out[str(member["key"])]=dict(text=part["text"],words=words,status=row.get("status"),
                        stats=part["stats"],model=effective.get("model"),model_revision=effective.get("model_revision"),
                        alignment_identity=effective.get("alignment_identity"),execution_identity=effective.get("execution_identity"),
                        configured_alignment_identity=payload.get("alignment_identity"),measurement=copy.deepcopy(part.get("measurement")),compatibility_fallback=copy.deepcopy(row.get("compatibility_fallback")),
                        evidence=dict(part,timebase='concatenated-pcm-ms',project_offset_ms=shift,alignment_item=copy.deepcopy(row.get('alignment_item')),measurement=copy.deepcopy(part.get('measurement')),pure_configured_attempt=copy.deepcopy(row.get('pure_configured_attempt'))),
                        cue_range_ms=[member["start_ms"],member["end_ms"]],boundaries=graded,second=engine)
            return out
        finally:
            audio._mmap.close()


class RealignWordsCommand(QUndoCommand):
    def __init__(self, project, results, changed=None):
        super().__init__("重新对齐字词时间")
        results = {key:value for key,value in results.items() if value.get("status","aligned") == "aligned" and value.get("words")}
        from ..timeline.studio_caption_timeline import KEY
        self.project = project
        instances = project.studio_state.setdefault(KEY, {"version": 1, "instances": {}}).setdefault("instances", {})
        self.before = {cue_id: copy.deepcopy(instances.get(cue_id)) for cue_id in results}
        self.after = {}
        for cue_id, result in results.items():
            receipt = copy.deepcopy(instances.get(cue_id) or {})
            if (result.get('measurement',{}).get('state') in {'partial','unmeasured'} and receipt.get('text')==result['text'] and receipt.get('words')):
                receipt['last_alignment_attempt']=copy.deepcopy(result)
                receipt['alignment_display_origin']='previous_reliable'
                self.after[cue_id]=receipt
                continue
            words = [{key: word[key] for key in ("text", "char_start", "char_end", "start_ms", "end_ms",
                                                 "evidence_ref","granularity","start_basis","end_basis") if key in word} for word in result["words"]]
            cue = next((c for c in project.cues if c.id == cue_id), None)
            receipt.update(text=result["text"], words=words, word_alignment="exact_token_text",
                           word_base_words=copy.deepcopy(words), word_base_alignment="exact_token_text",
                           word_base_interval=[cue.start_ms, cue.end_ms] if cue else result["cue_range_ms"],
                           acoustic_word_observation=True,
                           forced_alignment={"model": result.get("model"), "revision": result.get("model_revision"),
                                             "stats": result.get("stats"),"measurement":copy.deepcopy(result.get("measurement")),
                                             "configured_alignment_identity":result.get("configured_alignment_identity"),
                                             "compatibility_fallback":result.get("compatibility_fallback"),
                                             "alignment_identity": result.get("alignment_identity"),
                                             "execution_identity": result.get("execution_identity"),
                                             "evidence": copy.deepcopy(result.get("evidence")),
                                             "pieces": copy.deepcopy(result["words"])})
            if result.get("boundaries"):
                # Graded cut positions on the project clock (boundary_grades), read by text_split.
                from ..recognition.boundary_grades import POLICY
                receipt.update(boundaries=copy.deepcopy(result["boundaries"]), boundary_policy=POLICY,
                               boundary_second=result.get("second") or "")
            else:
                for key in ("boundaries", "boundary_policy", "boundary_second"):
                    receipt.pop(key, None)
            self.after[cue_id] = receipt
        self.changed = changed

    def _apply(self, receipts):
        from ..timeline.studio_caption_timeline import KEY
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain

        def mutate():
            instances = self.project.studio_state.setdefault(KEY, {"version": 1, "instances": {}}) \
                .setdefault("instances", {})
            for cue_id, receipt in receipts.items():
                if receipt is None:
                    instances.pop(cue_id, None)
                else:
                    instances[cue_id] = copy.deepcopy(receipt)

        _commit_mutation(self.project, action_id=self.text(),
                         dirty=DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE, cue_ids=tuple(receipts),
                         mutate=mutate, changed=self.changed, sync_caption_words=False)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class _Signals(QObject):
    done = Signal(object)
    progress = Signal(object)


def alignment_audio_basis(project, cue_id):
    """The actual clipped audio graph, unaffected by background save timestamps."""
    from ..playback.cue_audio_preview import plan_cue_preview
    from ..recognition.alignment_backend import fingerprint
    from pathlib import Path
    plan = plan_cue_preview(project, cue_id)
    diagnostic = plan.diagnostic()
    for key in ('request_id', 'project_revision'):
        diagnostic.pop(key, None)
    files = {}
    for layer in plan.layers:
        for key in ('source_path', 'original_source_path'):
            value = layer.get(key)
            if not value:
                continue
            path = Path(value)
            try:
                stat = path.stat()
                files[str(path)] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                files[str(path)] = None
    return fingerprint(dict(plan=diagnostic, files=files))


def start_realign(page, cue_ids, on_done=None) -> None:
    """Context-menu action: measure in the background, apply as one undo step.

    ``on_done(results)`` runs after the receipts are applied (split at the cursor re-plans then).
    """
    from ..i18n import bind_text, tr
    project = page.project
    if not project or not cue_ids:
        return

    def message(text):
        label = getattr(page, "save_state", None)
        if label is not None:
            bind_text(label, text)

    from ..timeline.studio_caption_timeline import independent_captions
    if not independent_captions(project):
        message(tr("这个工程还没有转换成时间轴字幕，无法重新对齐"))
        return
    snapshot = copy.deepcopy(project)
    try:
        audio_revisions = {str(key):alignment_audio_basis(snapshot,key) for key in cue_ids}
    except Exception as exc:
        message(tr("无法重新对齐：{error}",error=str(exc)[:160]))
        return
    from ..recognition.service import CancellationToken
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    previous_token = getattr(page, '_realign_cancel', None)
    if previous_token is not None:
        previous_token.cancel()
    token = CancellationToken()
    page._realign_cancel = token
    page.destroyed.connect(lambda *_:token.cancel())
    settings = copy.deepcopy(getattr(page, 'runtime_settings', {}) or {})
    signals = _Signals(page)
    page._realign_signals = signals
    targets = [cue for cue in project.cues if cue.id in {str(key) for key in cue_ids}]
    task = page._new_subtitle_task('字词对齐',targets)
    task.cancel_action = token.cancel
    task.time_label = '工程时间'
    task_ranges = {cue.id:(int(cue.start_ms),int(cue.end_ms)) for cue in targets}
    progress_state = dict(done=0,total=0,cached=0,local=0,phase='准备音频')
    def progress(event):
        kind,payload=event
        if task.cancelled or task.ended is not None or page.project is not project:
            return
        if kind=='alignment_checkpoint_plan':
            progress_state.update(total=int(payload.get('jobs',0)),cached=int(payload.get('reused',0)),
                                  local=int(payload.get('missing',0)),done=int(payload.get('reused',0)))
        else:
            state=payload.get('worker_state','')
            progress_state['phase']={'loading':'加载模型','verifying':'校验模型','loaded':'模型已就绪',
                'pass_started':'词级对齐' if payload.get('pass_id')=='word' else '字级对齐',
                'progress':'处理音频窗口','audio_prepared':'准备局部音频','runtime_check':'检查运行库'}.get(state,progress_state['phase'])
            if state=='audio_prepared':
                progress_state['total']=int(payload.get('total',0))
                progress_state['local']=progress_state['total']
            if state in {'loading','progress','completed','request_completed'}:
                count=int(payload.get('total') or payload.get('jobs') or 0)
                progress_state['total']=max(progress_state['total'],progress_state['cached']+count)
                progress_state['local']=max(progress_state['local'],count)
                progress_state['done']=min(progress_state['total'],progress_state['cached']+int(
                    payload.get('done') or (count if state in {'completed','request_completed'} else 0)))
        label=tr('{phase} · 窗口 {done}/{total} · 缓存 {cached} · 局部重算 {local}',**progress_state)
        task.update(dict(phase=label))
        message(label)
        page._refresh_subtitle_task_entry()
    signals.progress.connect(progress)
    def end_task(applied=(),error='',cancelled=False):
        task.alignment_progress = dict(progress_state)
        for cue_id in task.cue_ids:
            start_ms,end_ms=task_ranges[cue_id]
            task.update(dict(range_id=cue_id,cue_ids=[cue_id],start_ms=start_ms,end_ms=end_ms,
                status='applied' if cue_id in applied else 'cancelled' if cancelled else 'review',
                error='' if cue_id in applied else error))
        task.finish(cancelled=cancelled)
        page._refresh_subtitle_task_entry()
    message(tr("正在重新对齐 {count} 条字幕，并用第二份证据检查切点…", count=len(cue_ids)))

    def finish(result):
        page._realign_signals = None
        if token.is_cancelled or getattr(page,'_realign_cancel',None) is not token:
            end_task(cancelled=True,error='已取消，已有时间保留')
            message(tr('重新对齐已取消，已有字词时间保留'))
            return
        if isinstance(result, Exception):
            end_task(error=str(result)[:160])
            message(tr("重新对齐失败：{error}", error=str(result)[:160]))
            return
        if token.is_cancelled or getattr(page, '_realign_cancel', None) is not token:
            return
        current = {cue.id: cue.text for cue in page.project.cues} if page.project is project else {}
        fresh = {}
        for cue_id,value in result.items():
            if value.get('status') != 'aligned' or not value.get('words'):
                continue
            if current.get(cue_id) != value['text']:
                continue
            try:
                if alignment_audio_basis(project,cue_id) != audio_revisions.get(cue_id):
                    continue
            except Exception:
                continue
            fresh[cue_id] = value
        if not fresh:
            end_task(error='未取得可用于当前字幕的可靠时间，已有时间保留')
            message(tr("未取得可用于当前字幕的可靠时间，已有字词时间保留；可检查原文、素材或稍后重试。"))
            return
        page.undo_stack.push(RealignWordsCommand(project, fresh))
        end_task(applied=set(fresh),error='该字幕没有新的可靠时间或已被编辑，已有时间保留')
        from ..recognition.boundary_grades import counts
        graded = counts([row for value in fresh.values() for row in value.get("boundaries") or ()])
        message(tr("已重新对齐 {count} 条字幕：可独立切 {independent} 处、只能整词 {whole} 处、不可靠 {unreliable} 处",
                   count=len(fresh), **graded))
        if callable(on_done):
            on_done(fresh)

    signals.done.connect(finish)

    def work():
        from ..runtime_paths import user_data_root
        from ..recognition.alignment_backend import fingerprint
        from ..recognition.cache import run_event_observer
        from ..storage.storage_service import cache_lease
        checkpoint_root=user_data_root()/'cache/studio-alignment'/fingerprint(str(project.project_id))[:24]
        context=RuntimeContext(asr_settings_snapshot=settings,cancellation_token=token,
                               alignment_checkpoint_dir=str(checkpoint_root))
        last=[0.]
        def observe(kind,payload):
            from ..recognition.run_context import get_runtime_context
            import time
            if get_runtime_context().job_id != context.job_id or kind not in {'alignment_progress','alignment_checkpoint_plan'}:
                return
            now=time.monotonic()
            if now-last[0]<.16 and kind!='alignment_checkpoint_plan' and payload.get('worker_state') not in {'completed','failed','request_completed'}:
                return
            last[0]=now
            signals.progress.emit((kind,payload))
        try:
            with activate_runtime_context(context),run_event_observer(observe),cache_lease(checkpoint_root):
                result=measure(snapshot,list(cue_ids),cancelled=lambda:token.is_cancelled)
        except Exception as exc:
            result=exc
        finally:
            try:
                context.close_resources()
            except Exception as exc:
                result=exc
        try:
            signals.done.emit(result)
        except RuntimeError:
            pass  # The page was destroyed; its cancellation token is already set.

    threading.Thread(target=work, name="caption-realign", daemon=True).start()
