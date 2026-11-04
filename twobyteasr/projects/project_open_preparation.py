"""Prepare a reader-owned document before transferring it to the GUI."""
import time

def prepare(project):
    from .subtitle_consistency import validate_project,SubtitleConsistencyError
    from ..timeline.studio_caption_timeline import ensure_independent_captions,recover_caption_words
    from ..timeline.caption_source_receipts import recover_caption_sources
    from ..recognition.speaker_roles import refresh_automatic_roles
    from .studio_project import speaker_track_preference
    from .studio_revisions import StudioRevisionStore
    from .studio_runtime_state import state_for
    started=time.perf_counter()
    first=validate_project(project,stage='load')
    if not first.ok:raise SubtitleConsistencyError(first)
    ensure_independent_captions(project)
    recover_caption_sources(project)
    words=recover_caption_words(project,allow_realign=False)
    refresh_automatic_roles(project,speaker_track_preference())
    final=validate_project(project,stage='load')
    if not final.ok:raise SubtitleConsistencyError(final)
    if not project.generation_metadata.get('speaker_recovery') and project.report_path:
        from ..recognition.speaker_recovery import load_candidate_snapshot
        try:project.generation_metadata['speaker_recovery']=load_candidate_snapshot(project)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            project.generation_metadata['speaker_recovery_error']=str(exc)
    runtime=state_for(project)
    store=StudioRevisionStore(project,revision=runtime.revision)
    if project.generation_metadata.get('display_overlap_audit',{}).get('status') != 'user_undone':
        from ..subtitle_rules.display_timing import project_display_tail_plan
        project._prepared_display_tail=(tail_key(project), project_display_tail_plan(project))
    project._prepared_open=(project.project_id,runtime.revision,final,words,store)
    project._prepared_open_ms=round((time.perf_counter()-started)*1000,3)
    return project

def prepared(project):
    value=getattr(project,'_prepared_open',None)
    runtime=getattr(project,'_studio_state_runtime',None)
    if value and value[:2]==(project.project_id,getattr(runtime,'revision',0)):
        return value
    return None


def tail_key(project):
    import marshal
    # Compare the actual inputs, not broad metadata revisions (opening the
    # same file updates view/bookkeeping revisions without changing a word).
    return (tuple((cue.id,cue.start_ms,cue.end_ms,cue.text,cue.speaker_id) for cue in project.cues),
        id(project.asr_evidence),
        marshal.dumps((project.studio_state.get('caption_timeline') or {}).get('instances',{})),
        marshal.dumps(project.studio_state.get('term_word_overrides',{})),
        tuple((speaker.id,speaker.name) for speaker in project.speakers))
