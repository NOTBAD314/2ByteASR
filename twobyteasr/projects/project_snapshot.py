"""Detach document fields without copying live controllers or worker caches."""
from copy import deepcopy
from dataclasses import fields


def copy_json_value(value):
    """Detach in-memory JSON-shaped metadata without per-leaf Python deepcopy.

    No bytes from files or IPC are decoded here. Non-serializable legacy
    runtime values retain the existing deepcopy behavior.
    """
    import marshal
    try:
        return marshal.loads(marshal.dumps(value,4))
    except (TypeError,ValueError):
        return deepcopy(value)


def presentation_snapshot(project, *, cue_ids=None):
    """Detached render inputs, with evidence limited to the selected captions.

    Selection geometry consumes one caption. It must not clone recognition
    histories, source archives, runtime subscribers, or an entire document.
    """
    from .studio_project import SubtitleProject
    from ..timeline.studio_caption_timeline import KEY
    cues=[cue for cue in project.cues if cue_ids is None or cue.id in cue_ids]
    ids={cue.id for cue in cues}
    refs={ref for cue in cues for ref in cue.evidence_refs}
    refs.update('cue-align:'+key for key in ids)
    state={key:value for key,value in project.studio_state.items() if key not in
           {KEY,'term_word_overrides','glossary_proofread_review','manual_caption_text'}}
    timeline=project.studio_state.get(KEY)
    if isinstance(timeline,dict):
        state[KEY]={key:value for key,value in timeline.items() if key not in {'instances','source_archive'}}
        state[KEY]['instances']={key:value for key,value in timeline.get('instances',{}).items() if key in ids}
    state['term_word_overrides']={key:value for key,value in project.studio_state.get('term_word_overrides',{}).items() if key in ids}
    metadata={key:value for key,value in project.generation_metadata.items() if key in
              {'language','source_language','speaker_names','glossary_binding','applied_glossaries','glossary_snapshot','terminology_snapshot'}}
    metadata['translations']={key:value for key,value in project.generation_metadata.get('translations',{}).items() if key in ids}
    clone=SubtitleProject(media=deepcopy(project.media),cues=deepcopy(cues),speakers=deepcopy(project.speakers),
        styles=deepcopy(project.styles),effects=deepcopy(project.effects),style_recipes=deepcopy(project.style_recipes),
        render_settings=deepcopy(project.render_settings),studio_state=deepcopy(state),generation_metadata=deepcopy(metadata),
        asr_evidence=deepcopy({key:value for key,value in project.asr_evidence.items() if key in refs}),
        glossary_ids=list(project.glossary_ids),project_id=project.project_id)
    return clone


def document_snapshot(project, *, cues=None):
    """Called by the GUI at a committed boundary; workers own the result.

    Runtime subscribers may contain bound Qt slots, locks and native objects.
    They are not part of the saved document and must never enter deepcopy.
    """
    runtime = getattr(project, '_studio_state_runtime', None)
    if runtime is not None and runtime._active is not None:
        raise RuntimeError('不能在编辑事务提交前创建导出快照')
    from ..timeline.studio_edit_sequence import persist_sequence
    persist_sequence(project)
    clone = object.__new__(type(project))
    clone.__dict__.update({item.name: deepcopy(cues if item.name == 'cues' and cues is not None
                                               else getattr(project, item.name))
                           for item in fields(project)})
    return clone
