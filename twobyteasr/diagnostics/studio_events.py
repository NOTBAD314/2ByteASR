"""Cheap observation at real Studio command, transaction and view boundaries."""
from __future__ import annotations
from functools import wraps
import itertools
import sys
import time
import uuid

from .event_log import context, current_context, emit, exception_info, operation, recorder


def revision(project):
    return getattr(getattr(project,"_studio_state_runtime",None),"revision",None)


def project_fields(project):
    if project is None:return dict(project_id=None,revision=None,cue_count=None)
    return dict(project_id=getattr(project,"project_id",None),revision=revision(project),
                cue_count=len(project.cues),speaker_count=len(project.speakers),
                video_track_count=len(project.video_tracks),audio_track_count=len(project.audio_tracks))


def cue_summary(project, ids=(), *, lookup=None):
    """O(affected sample), no full-project thaw/hash/rebuild on an edit."""
    if project is None:return {}
    runtime=getattr(project,"_studio_state_runtime",None)
    lookup=lookup if lookup is not None else getattr(runtime,"cue_by_id",{})
    ids=list(itertools.islice(iter(ids or ()),32))
    cues=[lookup[c] for c in ids if c in lookup] if ids else list(itertools.islice(iter(project.cues),32))
    meta=project.generation_metadata
    view=meta.get("translations") or {}
    records=(meta.get("translation_records") or {}).get("records",{})
    rows=[]
    for cue in cues:
        record=records.get(cue.id) or {}
        from ..subtitle_rules.subtitle_translation import status_of
        rows.append(dict(subtitle_id=cue.id,track_id=cue.speaker_id,start_ms=cue.start_ms,end_ms=cue.end_ms,
                         characters=len(cue.text),translation_characters=len(str(view.get(cue.id) or "")),
                         translation_record=bool(record),translation_status=status_of(record,cue.text),
                         translation_target=record.get("target"),evidence_refs=list(cue.evidence_refs)[:8]))
    return dict(cue_count=len(project.cues),translation_view_count=len(view),translation_record_count=len(records),
                active_translation_sample_count=sum(bool(r['translation_characters']) for r in rows),
                valid_translation_sample_count=sum(bool(r['translation_characters']) and r['translation_status'] in {'done','manual'} for r in rows),
                sampled=len(cues),sample_limit=32,
                coordinate="project" if project.render_settings.get("_cue_domain")=="timeline" else "source_media",unit="ms",cues=rows)


def page_context(page):
    try:
        project=getattr(page,"project",None)
        result=project_fields(project)
        timeline=getattr(page,"timeline",None)
        table=getattr(page,"cue_table",None)
        scope=getattr(getattr(page,"selection_model",None),"scope",None)
        selected=getattr(page,"selected_cue_id",None)
        result.update(selected_subtitle_id=selected,
                      selected_ids=list(itertools.islice(iter(getattr(scope,"explicit_ids",())),32)),
                      selection_mode=str(getattr(scope,"mode","unknown")),
                      project_playhead_ms=getattr(timeline,"playhead_ms",None),
                      list_scroll=table.verticalScrollBar().value() if table else None,
                      list_rows=table.model().rowCount() if table and table.model() else None,
                      hidden_tracks=list(getattr(timeline,"hidden_speakers",()))[:32],
                      locked_tracks=list(getattr(timeline,"locked_speakers",()))[:32],
                      visibility=dict(itertools.islice(iter(getattr(page,"_subtitle_track_visibility",{}).items()),32)))
        from PySide6.QtWidgets import QApplication
        focus=QApplication.focusWidget()
        result["focus_widget"]=type(focus).__name__ if focus else None
        video=getattr(page,"video",None)
        controller=getattr(video,"controller",None)
        result["paused"]=getattr(video,"_paused",None)
        result["player"]=controller.observed_position() if controller else {"result":"not_available"}
        result['player_position_unit']='seconds'
        result["render"]=controller.applied_visual_state() if controller else {"result":"not_available"}
        if project:
            from ..caption_style.bilingual_layout import settings_from_state
            result["display_mode"]=settings_from_state(project.studio_state).mode
            result["selected_cues"]=cue_summary(project,[selected] if selected else [])
            runtime=getattr(project,"_edit_sequence_runtime",None)
            sequence=getattr(runtime,"sequence",None)
            if sequence:
                result["mapping"]=dict(version=1,revision=runtime.revision,unit="ms",coordinate_from="source_media",coordinate_to="project",
                    segment_count=len(sequence.segments),samples=[dict(clip_id=s.id,source_in_ms=s.source_in_ms,source_out_ms=s.source_out_ms,
                    project_in_ms=s.timeline_in_ms,project_out_ms=s.timeline_out_ms) for s in itertools.islice(iter(sequence.segments),8)])
        return result
    except Exception as exc:
        return {"context_result":"partial","exception_type":type(exc).__name__}


def observed(action, *, source="application", view=False):
    """Use on discrete callbacks only; never on key/mouse/frame callbacks."""
    def decorate(function):
        @wraps(function)
        def run(self,*args,**kwargs):
            if recorder() is None:return function(self,*args,**kwargs)
            page=getattr(self,"page",getattr(self,"_page",self))
            if view:
                # StateDelta already owns the command/transaction. Keep its ID
                # and one resulting view, instead of serializing four copies.
                started=time.perf_counter()
                emit('view.begin',module=function.__module__,result='started',**project_fields(getattr(page,'project',None)))
                try:answer=function(self,*args,**kwargs)
                except BaseException as exc:
                    emit('view.failed',level='ERROR',result='failed',exception=exception_info(exc));raise
                emit('view.applied',module=function.__module__,result='completed',action=action,after=page_context(page),
                     duration_ms=round((time.perf_counter()-started)*1000,3),render_result='submitted_state; pixels_not_measured')
                return answer
            before=page_context(page)
            with operation(action,module=function.__module__,source=source,
                           project_id=before.get("project_id"),revision_before=before.get("revision")) as outcome:
                emit("command.received",action=action,source=source,before=before,
                     target_ids=[v for v in args[:(2 if action=="cue.merge_pair" else 1)]
                                 if isinstance(v,str) and action in {"cue.select","cue.merge_pair","cue.split","cue.edit","cue.translation"}])
                answer=function(self,*args,**kwargs)
                after=page_context(page)
                changed=before!=after
                outcome.update(revision_after=after.get("revision"),effective=changed,
                               result="skipped" if answer is False else "completed" if changed or view else "observed",
                               reason="callback_declined" if answer is False else "state_changed" if changed else "no_observed_state_change")
                emit("view.applied" if view else "command.result",action=action,after=after,
                     result=outcome["result"],effective=changed,
                     model_rebuilt=bool(before.get("list_rows")!=after.get("list_rows")),
                     render_result="submitted_state; pixels_not_measured")
                return answer
        return run
    return decorate


def begin_transaction(tx):
    if recorder() is None:return None
    try:
        # Undo labels can contain actual text. Record the command class + method,
        # not the human label used by QUndoCommand.text().
        frame=sys._getframe(2); caller="transaction"
        for _ in range(6):
            if frame is None:break
            owner=frame.f_locals.get("self")
            if owner is not None and type(owner).__name__.endswith("Command"):
                caller=type(owner).__name__+"."+frame.f_code.co_name;break
            frame=frame.f_back
        ctx=context(operation_id=current_context().get("operation_id") or "op-"+uuid.uuid4().hex[:16],
                    project_id=tx.project.project_id,revision_before=tx.state.revision)
        ctx.__enter__()
        before=cue_summary(tx.project,tx.affected_cue_ids,lookup=tx.state.cue_by_id)
        handle=dict(context=ctx,started=time.perf_counter(),before=before,revision=tx.state.revision,action=caller)
        emit("data.begin",result="started",action=caller,before=before,
             subtitle_ids=list(itertools.islice(iter(tx.affected_cue_ids),32)),affected_count=len(tx.affected_cue_ids),
             dirty_domains=int(tx.dirty),selection_before=tx.selection_before)
        return handle
    except Exception:
        return None


def end_transaction(tx, handle, *, error=None, committed=False):
    if not handle:return
    try:
        after=cue_summary(tx.project,tx.affected_cue_ids,lookup=tx.state.cue_by_id)
        before=handle["before"]
        same_links=before.get("translation_view_count")==after.get("translation_view_count")
        decision="stored_link_count_unchanged; inspect_per_cue_validity" if same_links else "stored_link_count_changed; inspect_per_cue_validity"
        emit("data.rollback" if error else "data.commit",result="failed" if error else "completed",level="ERROR" if error else "INFO",
             action=handle["action"],before=before,after=after,
             revision_before=handle["revision"],revision_after=tx.state.revision,
             duration_ms=round((time.perf_counter()-handle["started"])*1000,3),
             affected_count=len(tx.affected_cue_ids),subtitle_ids=list(itertools.islice(iter(tx.affected_cue_ids),32)),
             clip_ids=list(itertools.islice(iter(tx.affected_sequence_ids),16)),
             selection_before=tx.selection_before,selection_after=tx.selection_after,
             translation_decision=decision,exception=exception_info(error) if error else None,
             validation="failed" if error else "passed_existing_domain_rules",error_code="transaction_validation" if error else None,
             ranges_ms=list(itertools.islice(iter(tx.affected_ranges),16)))
        if committed and (before.get("translation_view_count",0)>after.get("translation_view_count",0)):
            emit("translation.links",level="WARN",result="observed",action=handle["action"],
                 before=before.get("translation_view_count"),after=after.get("translation_view_count"),
                 reason="render_translation_count_decreased; invalidation_may_be_expected")
        invalid=[dict(subtitle_id=r["subtitle_id"],start_ms=r["start_ms"],end_ms=r["end_ms"],rule="0 <= start_ms < end_ms")
                 for r in after.get("cues",[]) if r["start_ms"]<0 or r["end_ms"]<=r["start_ms"]]
        if invalid:emit("timing.validation",level="ERROR",result="failed",samples=invalid,coordinate="source_media",unit="ms")
    except Exception:
        pass


def release_transaction(handle):
    if handle:
        try:handle["context"].__exit__(None,None,None)
        except Exception:pass


def background_ticket(project, purpose, *, ids=()):
    ticket=dict(task_id="task-"+uuid.uuid4().hex[:16],project_id=getattr(project,"project_id",None),
                revision_before=revision(project),purpose=purpose,operation_id=current_context().get("operation_id") or 'op-'+uuid.uuid4().hex[:16])
    emit("background.start",result="started",**ticket,subtitle_ids=list(itertools.islice(iter(ids or ()),32)),scope="all" if ids is None else "selected")
    return ticket


def background_result(ticket, project, *, decision, cancelled=False, stale_ids=(),
                      applied_count=None, discard_reasons=None):
    emit("background.result",**(ticket or {}),current_project_id=getattr(project,"project_id",None),
         revision_after=revision(project),result=decision,cancelled=cancelled,
         stale_ids=list(itertools.islice(iter(stale_ids),32)),
         applied_count=applied_count,
         discard_reasons=dict(itertools.islice((discard_reasons or {}).items(),32)),
         revision_changed=(ticket or {}).get("revision_before")!=revision(project))


def project_io(action):
    """Durable file boundaries, including callers outside the Studio page."""
    def decorate(fn):
        @wraps(fn)
        def run(*args,**kwargs):
            if recorder() is None:return fn(*args,**kwargs)
            subject=args[0] if args else kwargs.get("project")
            target=args[1] if len(args)>1 else kwargs.get("path",subject if action=="load" else None)
            with operation("project."+action,module="projects",project_id=getattr(subject,"project_id",None),
                           revision_before=revision(subject),target_path=target) as outcome:
                result=fn(*args,**kwargs)
                project=result if action=="load" else subject
                # Persistence DTOs intentionally contain frozen JSON tuples. An
                # observer must never turn a successful durable write into an error.
                try:
                    from collections.abc import Mapping
                    from pathlib import Path
                    metadata=getattr(project,"generation_metadata",{})
                    ref=(metadata.get("recognition_result") or {}) if isinstance(metadata,Mapping) else {}
                    stat=Path(target).stat()
                    emit("project.loaded" if action=="load" else "project.saved",result="completed",
                         project_id=getattr(project,"project_id",None),target_path=target,
                         task_id=ref.get("job_id"),revision_after=revision(project),
                         persisted_revision=getattr(subject,"generation",None),
                         file_version=dict(size_bytes=stat.st_size,modified_ns=stat.st_mtime_ns),
                         cue_count=len(project.cues) if hasattr(project,"cues") else None,
                         atomic_write_completed=action!="load")
                except Exception as exc:
                    emit("diagnostics.observer",level="WARN",result="partial",boundary=action,exception=exception_info(exc))
                return result
        return run
    return decorate
