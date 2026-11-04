"""Editorial grouping; never claims that grouped voices are one person."""
import copy
from dataclasses import asdict

UNIFIED = 'SUBTITLES'
BACKGROUND = 'GAME_BACKGROUND'


def normalized_speaker_mode(mode):
    return str(mode) if mode in {'moss','ecapa','filetrans','native','nemotron','diarizen'} else 'single'


def utterance_counts(rows):
    """Count unique pre-subtitle ASR utterances, not display cue fragments."""
    counts = {}
    for row in rows:
        label = str(row.get('speaker') or 'S00')
        unit = row.get('utterance_id') or row.get('source_utterance_id')
        key = str(unit) if unit is not None else (
            round(float(row['start'])*1000),round(float(row['end'])*1000),
            ''.join(str(row.get('text','')).split()))
        counts.setdefault(label,set()).add(key)
    return {label:len(values) for label,values in counts.items()}


def organize(project, selected, action, target=None):
    """Pure complete project result for one undoable explicit operation."""
    from .studio_project import SubtitleProject, StudioSpeaker
    result = SubtitleProject.from_dict(project.to_dict())
    selected = set(selected) & {s.id for s in result.speakers}
    state = result.generation_metadata.setdefault('speaker_organization',{})
    origins = state.setdefault('cue_origins',{})
    identities = state.setdefault('original_speakers',{})
    for speaker in result.speakers:identities.setdefault(speaker.id,asdict(speaker))
    for cue in result.cues:origins.setdefault(cue.id,cue.speaker_id)
    state.setdefault('decisions',{})
    if action == 'merge' and target not in {s.id for s in result.speakers}:
        raise ValueError('请选择仍存在的目标说话人。')
    if action == 'merge':selected.discard(target)
    destination = {'single':UNIFIED,'identity_delete':UNIFIED,'background':BACKGROUND}.get(action,target)
    if action in {'single','identity_delete','background','merge'} and selected:
        if destination not in {s.id for s in result.speakers}:
            result.speakers.append(StudioSpeaker(destination,name='统一字幕' if destination==UNIFIED else '游戏背景声'))
        for cue in result.cues:
            if cue.speaker_id in selected:cue.speaker_id=destination
        result.speakers=[s for s in result.speakers if s.id not in selected or s.id==destination]
    elif action == 'delete':
        state.setdefault('deleted_cues',[]).extend(asdict(c) for c in result.cues if c.speaker_id in selected)
        result.cues=[c for c in result.cues if c.speaker_id not in selected]
        result.speakers=[s for s in result.speakers if s.id not in selected]
    elif action in {'restore','main'}:
        for cue in result.cues:
            if cue.speaker_id not in selected:continue
            original=origins.get(cue.id,cue.speaker_id)
            cue.speaker_id=original
            if original not in {s.id for s in result.speakers}:
                result.speakers.append(StudioSpeaker(**identities.get(original,{'id':original})))
            state['decisions'][original]='main' if action=='main' else 'restored'
        used={c.speaker_id for c in result.cues}
        result.speakers=[s for s in result.speakers if s.id in used or s.id not in {UNIFIED,BACKGROUND}]
    elif selected:raise ValueError('未知的说话人整理操作')
    for label in selected:state['decisions'][label]=action
    state['mode']='single' if action=='single' else state.get('mode','separated')
    valid={s.id for s in result.speakers}
    result.studio_state['speaker_track_order']=[s for s in result.studio_state.get('speaker_track_order',[]) if s in valid]
    result.validate()
    return result


def apply_new_project_policy(project):
    evidence = project.generation_metadata.get('speaker_recovery',{})
    # Keep finalized, edited caption text available before identities are grouped.
    # Raw ASR evidence is not an acceptable replacement for these captions.
    cache = evidence.setdefault('cue_cache',{})
    for label in {cue.speaker_id for cue in project.cues}:
        cache[label]=[asdict(cue) for cue in project.cues if cue.speaker_id==label]
    mode = normalized_speaker_mode(evidence.get('processing',{}).get('mode'))
    # This policy only constructs NEW projects. Recognition-stage 'single'
    # bookmarks are retired; explicit editorial merges still use organize().
    if mode == 'single':
        mode = 'native'

    state = project.generation_metadata.setdefault('speaker_organization',{})
    state.update(mode=mode,threshold=int(state.get('threshold',10)),
        counting_unit='unique original ASR utterance before caption segmentation',
        utterance_counts=utterance_counts(evidence.get('raw_segments',[])))
    if mode in {'moss','nemotron','native','filetrans','diarizen'}:
        # Explicit diarization labels have no automatic editorial host identity.
        # Keep every lane until an explicit, undoable editorial decision.
        state['needs_manual_host_selection']=len(project.speakers) > 1
        evidence['roles']={label:'unconfirmed' for label in evidence.get('roles',{})}
        evidence['needs_confirmation']=len(project.speakers) > 1
        for speaker in project.speakers:speaker.is_host=False
        return
    if mode == 'single':
        result=organize(project,[s.id for s in project.speakers],'single')
    else:
        counts=state['utterance_counts']; decisions=state.get('decisions',{})
        main={s.id for s in project.speakers if s.is_host or decisions.get(s.id)=='main'
              or counts.get(s.id,0)>state['threshold']}
        if not main:
            result=organize(project,[s.id for s in project.speakers],'single')
            result.generation_metadata['speaker_organization']['insufficient_sample']=True
        else:
            result=organize(project,[s.id for s in project.speakers if s.id not in main],'background')
    project.cues,project.speakers=result.cues,result.speakers
    project.generation_metadata=result.generation_metadata
    project.studio_state=result.studio_state


def organization_command(project, selected, action, target=None, changed=None, threshold=None):
    from PySide6.QtGui import QUndoCommand
    from .studio_runtime_state import state_for,DirtyDomain
    after=organize(project,selected,action,target)
    if threshold is not None:after.generation_metadata['speaker_organization']['threshold']=int(threshold)
    fields=('speakers','cues','generation_metadata','studio_state')
    before={k:copy.deepcopy(getattr(project,k)) for k in fields}
    desired={k:copy.deepcopy(getattr(after,k)) for k in fields}
    class Command(QUndoCommand):
        def __init__(self):super().__init__('批量整理说话人')
        def apply(self,data):
            with state_for(project).transaction(project,action_id='speaker_organization',
                    dirty=DirtyDomain.CUE_MODEL|DirtyDomain.CUE_STYLE|DirtyDomain.NATIVE_SUBTITLE
                          |DirtyDomain.ADVANCED_PREVIEW|DirtyDomain.PROJECT_METADATA|DirtyDomain.AUTOSAVE):
                for k,v in data.items():setattr(project,k,copy.deepcopy(v))
            if changed:changed()
        def redo(self):self.apply(desired)
        def undo(self):self.apply(before)
    return Command()
