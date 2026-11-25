"""Scope-bound local re-recognition. Results remain suggestions until adopted."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import threading

from ..i18n import tr
from ..subtitle_rules.sentence_refine_ranges import input_version
from .studio_reasr import LocalReASRResult, protected_reasr_ids, run_local_reasr


def confirmed_music_overlap(cue, events):
    """Union of confirmed music notes in this project-clock caption."""
    confirmed_end = cue.start_ms
    overlap = 0
    for event in events:
        if event.start_ms >= cue.end_ms:
            break
        if event.kind != "music" or not event.confirmed or event.end_ms <= confirmed_end:
            continue
        a, b = max(confirmed_end, event.start_ms), min(cue.end_ms, event.end_ms)
        if b > a:
            confirmed_end = b
            overlap += b - a
        if confirmed_end == cue.end_ms:
            break
    return overlap


@dataclass(frozen=True)
class BatchReASREvent:
    task_id: str
    cue_id: str = ""
    result: LocalReASRResult | None = None
    error: str = ""
    phase: str = ""


def targets_for(page, cue_ids=(), *, speaker=False):
    from ..projects.studio_runtime_state import state_for

    project = page.project
    lookup = state_for(project).cue_by_id
    if speaker:
        current = lookup.get(page.selected_cue_id)
        targets = [cue for cue in project.cues if current and cue.speaker_id == current.speaker_id]
    else:
        targets = [lookup[key] for key in dict.fromkeys(map(str, cue_ids)) if key in lookup]
    protected = protected_reasr_ids(project, targets, page.timeline.locked_speakers)
    return [cue for cue in targets if cue.id not in protected]


def start_in_out(page):
    from ..recognition.range_recognition import requested_range

    points = requested_range(page.project)
    if points is None or points[0] >= points[1]:
        page._show_studio_hint(tr("请先设置入点和出点"))
        return False
    lo, hi = points
    return start(page, (cue.id for cue in page.project.cues if lo <= cue.start_ms < cue.end_ms <= hi))


def _input_version(cue, project):
    # Editing and undoing text refreshes its cached layout. That counter does
    # not describe the selected spelling, evidence or source audio.
    return input_version((replace(cue, appearance_generation=0),), project)


def start(page, cue_ids=(), *, speaker=False, voice_mode="off", retry=False):
    if voice_mode not in {"off", "auto", "prefer"}:
        raise ValueError("Unknown vocal enhancement mode")
    if page.project is None:
        return False
    active = getattr(page, "_reasr_task", None)
    if (active is not None and active.ended is None) or getattr(page, "_recognition_running", False):
        page.show_subtitle_tasks()
        return False
    targets = targets_for(page, cue_ids, speaker=speaker)
    if not targets:
        page._show_studio_hint(tr("选中的字幕已确认、锁定或没有可用字幕"))
        return False
    from ..media.vocal_enhancement import assets_present
    can_enhance = voice_mode != "off" and assets_present()
    if voice_mode == "prefer" and not can_enhance:
        page._show_studio_hint(tr("未安装受验证的本机 HTDemucs 人声增强模型"))
        return False
    settings = deepcopy(page.runtime_settings)
    models = settings.setdefault("models", {})
    review, primary = models.get("qwen_asr_backend"), models.get("primary_asr_backend")
    if review == "haas_ja" or (primary == "haas_ja" and review in ("off", None)):
        if voice_mode == "prefer":
            page._show_studio_hint(tr("人声增强后的重新识别需要本机 Qwen"))
            return False
        can_enhance = False
        models["qwen_asr_backend"] = "haas_ja"
    elif review in ("local", "qwen_local") or primary in ("qwen_local", "local"):
        models["qwen_asr_backend"] = "local"
    else:
        page._show_studio_hint(tr("批量重新识别需要已配置的本机 Qwen 或 Haas 模型"))
        return False
    from ..projects.project_snapshot import document_snapshot

    snapshot = document_snapshot(page.project, cues=targets)
    task = page._new_subtitle_task("批量重新识别", targets)
    task.is_retry = retry
    task.voice_mode = voice_mode
    task.results = {}
    task.adopted_commands = {}
    task.input_versions = {cue.id: _input_version(cue, page.project) for cue in targets}
    task.mapping_revision = page._revision_store.render.mapping_revision
    page._reasr_task = task
    ids = tuple(cue.id for cue in targets)
    for cue in targets:
        task.update(dict(range_id=cue.id, cue_ids=[cue.id], start_ms=cue.start_ms,
                         end_ms=cue.end_ms, input_text=cue.text, status="pending"))
    from ..playback.audio_engine import studio_ffmpeg_path
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    from ..recognition.service import CancellationToken

    ffmpeg = studio_ffmpeg_path()
    token = CancellationToken()
    task.cancel_action = token.cancel
    page.destroyed.connect(lambda *_: token.cancel())

    def send(event):
        try:
            page.reasr_ready_signal.emit(event)
            return True
        except RuntimeError:
            return False

    def work():
        from ..providers.provider_diagnostics import redact_diagnostics
        from ..subtitle_rules.language_rules import language_scope
        from ..subtitle_rules.segmentation_profiles import project_language_tag

        context = RuntimeContext(asr_settings_snapshot=settings, cancellation_token=token)
        try:
            with activate_runtime_context(context), language_scope(project_language_tag(snapshot)):
                from ..timeline.studio_commands import cue_by_id
                from .studio_sound_events import read_events

                events = (read_events(snapshot) if voice_mode == "auto" and can_enhance
                          and snapshot.render_settings.get('_cue_domain') == 'timeline' else ())
                for cue_id in ids:
                    if token.is_cancelled:
                        break
                    try:
                        cue = cue_by_id(snapshot, cue_id)
                        enhanced = can_enhance and (voice_mode == "prefer"
                            or bool(events and confirmed_music_overlap(cue, events) * 2 >= cue.end_ms - cue.start_ms))
                        result = run_local_reasr(snapshot, cue_id, settings, ffmpeg,
                                                 padding_ms=0, cancel_check=lambda: token.is_cancelled,
                                                 enhance_voice=enhanced,
                                                 on_progress=lambda phase: send(BatchReASREvent(
                                                     task.task_id, cue_id, phase=phase)))
                    except Exception as error:
                        public = str(redact_diagnostics(str(error)))[:200]
                        if not send(BatchReASREvent(task.task_id, cue_id, error=public)):
                            return
                    else:
                        if not send(BatchReASREvent(task.task_id, cue_id, result)):
                            return
        finally:
            try:
                context.close_resources()
            finally:
                send(BatchReASREvent(task.task_id))

    threading.Thread(target=work, daemon=True, name="studio-batch-reasr").start()
    page._refresh_subtitle_task_entry()
    page.show_subtitle_tasks()
    return True


def still_current(page, task, cue_id):
    if (page.project is not task.project
            or page._revision_store.render.mapping_revision != task.mapping_revision):
        return False
    targets = targets_for(page, (cue_id,))
    return bool(targets and _input_version(targets[0], page.project) == task.input_versions.get(cue_id))


def receive(page, event):
    task = getattr(page, "_subtitle_tasks", {}).get(event.task_id)
    if task is None or task.ended is not None:
        return
    if not event.cue_id:
        task.finish(cancelled=task.cancelled or page.project is not task.project)
        page._refresh_subtitle_task_entry()
        return
    if task.cancelled or page.project is not task.project:
        return
    if event.phase:
        task.update(dict(phase=event.phase, range_id=event.cue_id,
                         cue_ids=[event.cue_id], status="running"))
        return
    row = dict(range_id=event.cue_id, cue_ids=[event.cue_id])
    if not still_current(page, task, event.cue_id):
        row.update(status="failed", error=tr("字幕或素材已变化，请重新识别"))
    elif event.result is not None:
        task.results[event.cue_id] = event.result
        row.update(status="suggestion", recommendation=event.result.recommendation,
                   validated_texts=[event.result.recommendation],
                   primary_text=event.result.primary_text, review_text=event.result.review_text,
                   backend=event.result.backend, audio_source=event.result.audio_source,
                   separation_backend=event.result.separation_backend,
                   audio_preview=bool(event.result.preview_key),
                   original_peaks=event.result.original_peaks, enhanced_peaks=event.result.enhanced_peaks)
    else:
        row.update(status="failed", error=event.error)
    task.update(row)


def open_suggestion(page, task, cue_id):
    result = task.results.get(cue_id)
    if result is not None and still_current(page, task, cue_id):
        page._show_reasr_result(result)


def stop_preview(page):
    from shiboken6 import isValid

    player = getattr(page, "_reasr_preview_player", None)
    if player is not None and isValid(player):
        player.stop()
    page._reasr_preview_project = None


def audition(page, payload):
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from ..media.vocal_enhancement import cached_clip

    task = getattr(page, "_subtitle_tasks", {}).get(payload["task_id"])
    cue_id = str(payload["record"].get("range_id") or "")
    if not task or task.kind != "批量重新识别" or not still_current(page, task, cue_id):
        page._show_studio_hint(tr("字幕或素材已变化，请重新识别"))
        return
    result = task.results.get(cue_id)
    if result is None:
        return
    stop_preview(page)
    if not payload.get("enhanced"):
        page.select_cue(cue_id)
        page._audition_selected_cue("full")
        return
    path = cached_clip(result.preview_key)
    if path is None:
        page._show_studio_hint(tr("增强音频已清理，请重新处理所选范围"))
        return
    page.video.set_paused(True)
    page._release_review_playback()
    if not hasattr(page, "_reasr_preview_player"):
        page._reasr_preview_player = QMediaPlayer(page)
        page._reasr_preview_audio = QAudioOutput(page)
        page._reasr_preview_player.setAudioOutput(page._reasr_preview_audio)
    page._reasr_preview_project = page.project
    page._reasr_preview_player.setSource(QUrl.fromLocalFile(str(path)))
    page._reasr_preview_player.play()


def adopt_suggestion(page, payload):
    from ..storage.project_stage_history import record_stage
    from ..timeline.studio_commands import MutationOrigin

    task = getattr(page, "_subtitle_tasks", {}).get(payload["task_id"])
    cue_id = str(payload["record"].get("range_id") or "")
    if not task or task.kind != "批量重新识别" or cue_id not in task.results:
        return
    if not still_current(page, task, cue_id):
        page._show_studio_hint(tr("字幕或素材已变化，请重新识别"))
        return
    result = task.results[cue_id]
    row = task.rows[cue_id]
    if row.get("status") != "suggestion":
        return
    stack_before = page.undo_stack.index()
    changed = page.cue_controller.set_text(cue_id, result.recommendation,
        command_text=tr("采用重新识别建议"), origin=MutationOrigin.MODEL_ADOPTION)
    if changed and page.undo_stack.index() == stack_before + 1:
        task.adopted_commands[cue_id] = (stack_before, page.undo_stack.command(stack_before))
    row.update(status="applied" if changed else "unchanged",
               final_texts=[result.recommendation if changed else result.current_text])
    task.revision += 1
    record_stage(page.project.project_id, "re_asr", "completed" if changed else "unchanged",
                 applied=int(bool(changed)))
    page._refresh_subtitle_task_entry()


def reconcile_adoption_rows(page, task):
    """The review projection follows the exact command's undo/redo position."""
    stack = page.undo_stack
    for cue_id, (command_index, command) in task.adopted_commands.items():
        row = task.rows[cue_id]
        result = task.results[cue_id]
        applied = command_index < stack.index() and stack.command(command_index) is command
        if row.get("status") == "applied" and not applied:
            row.update(status="suggestion", final_texts=[])
            task.revision += 1
        elif row.get("status") == "suggestion" and applied:
            row.update(status="applied", final_texts=[result.recommendation])
            task.revision += 1
