"""Transient ASR preview ownership, separate from authored project captions."""
from __future__ import annotations
import copy
from dataclasses import asdict


def signature(project,cue):
    metadata=project.generation_metadata
    records=(metadata.get('translation_records') or {}).get('records') or {}
    return dict(cue=asdict(cue),translation=copy.deepcopy((metadata.get('translations') or {}).get(cue.id)),
                translation_record=copy.deepcopy(records.get(cue.id)))


def discard(page):
    receipts=getattr(page,'_recognition_provisional_receipts',{}) or {}
    page._recognition_provisional_receipts={}
    project=getattr(page,'project',None)
    if not receipts or project is None:return
    states=project.generation_metadata.get('asr_cue_states') or {}
    owned=[c for c in project.cues if c.id in receipts and states.get(c.id)=='provisional']
    removable={c.id for c in owned if signature(project,c)==receipts[c.id]}
    from ..projects.studio_runtime_state import DirtyDomain,state_for
    if not owned:return
    with state_for(project).transaction(project,action_id='discard_unaccepted_asr_preview',
        dirty=DirtyDomain.CUE_MODEL|DirtyDomain.CUE_TIMING|DirtyDomain.PROJECT_METADATA|DirtyDomain.TIMELINE_INDEX|DirtyDomain.TIMELINE_PIXELS|DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.AUTOSAVE,
        affected_cue_ids={c.id for c in owned}):
        project.cues=[c for c in project.cues if c.id not in removable]
        for cue in owned:
            states.pop(cue.id,None)  # a changed preview belongs to the user's edit
    if getattr(page,'selected_cue_id','') in removable and project.cues:
        page.select_cue(project.cues[0].id)
