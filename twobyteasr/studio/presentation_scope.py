"""One immutable target snapshot for style and caption geometry operations."""
from dataclasses import dataclass
from ..caption_style.caption_layer_transform import target_ids
from ..caption_style.bilingual_layout import translation_for_cue,translations_of
from .studio_text_tools import cue_locked


@dataclass(frozen=True)
class PresentationScope:
    project_id: str
    scope: str
    layer: str
    cue_ids: tuple[str,...]
    locked_ids: tuple[str,...]=()
    missing_layer_ids: tuple[str,...]=()


def _speaker_owners(project):
    roles=project.generation_metadata.get('speaker_recovery',{}).get('roles',{})
    decisions=project.generation_metadata.get('speaker_organization',{}).get('decisions',{})
    result={}
    for original in {cue.speaker_id for cue in project.cues}:
        identity=original;seen=set()
        while identity not in seen:
            seen.add(identity)
            role=roles.get(identity,'')
            if decisions.get(identity) in {'restored','main'} or not str(role).startswith('merge:'):
                break
            identity=role[6:]
        else:identity=original
        result[original]=identity
    return result


def capture_scope(page, *, scope=None, layer=None, ids=None):
    project=getattr(page,'project',None)
    kind=scope or (page.style_scope.currentData() if hasattr(page,'style_scope') else 'current')
    language=layer or (page.style_layer.currentData() if hasattr(page,'style_layer') else 'original') or 'original'
    if language=='linked':language='group'
    if kind not in {'current','selected','speaker','all'}:raise ValueError('Unknown presentation scope')
    if language not in {'original','translation','group'}:raise ValueError('Unknown presentation layer')
    if project is None:return PresentationScope('',kind,language,())
    cues=project.cues;current=str(getattr(page,'selected_cue_id','') or '')
    owners=_speaker_owners(project)
    if ids is not None:wanted=target_ids(project,ids)
    elif kind=='all':wanted={c.id for c in cues}
    elif kind=='current':wanted=target_ids(project,[current]) if current else set()
    elif kind=='speaker':
        current_ids=target_ids(project,[current])
        reference=next((c for c in cues if c.id in current_ids),None)
        wanted={c.id for c in cues if reference is not None and owners[c.speaker_id]==owners[reference.speaker_id]}
    else:
        selection=getattr(getattr(page,'selection_model',None),'scope',None)
        if selection is None:wanted=set()
        else:
            order=[c.id for c in getattr(getattr(page,'timeline',None),'_cues_by_start',())] or [c.id for c in cues]
            wanted=target_ids(project,selection.materialize(order))
    locked_speakers=set(project.studio_state.get('locked_speakers',()))|set(getattr(getattr(page,'timeline',None),'locked_speakers',()))
    locked=set(project.studio_state.get('locked_cue_ids',()))
    translations=translations_of(project.generation_metadata)
    eligible=[];skipped=[];missing=[]
    for cue in cues:
        if cue.id not in wanted:continue
        if (cue_locked(cue,locked) or cue.speaker_id in locked_speakers or owners[cue.speaker_id] in locked_speakers
                or language == 'translation' and 'translation' in locked_speakers):skipped.append(cue.id)
        elif language=='translation' and not translation_for_cue(translations,cue.id):missing.append(cue.id)
        else:eligible.append(cue.id)
    return PresentationScope(str(project.project_id),kind,language,tuple(eligible),tuple(skipped),tuple(missing))


def describe_scope(page, scope):
    from ..i18n import tr
    layer = tr({'original':'原文', 'translation':'译文', 'group':'双语整组'}[scope.layer])
    count = len(scope.cue_ids)
    if scope.scope == 'current':
        text = tr('当前字幕 · {layer} · 共 {count} 条', layer=layer, count=count)
    elif scope.scope == 'selected':
        text = tr('已选 {count} 条 · {layer}', count=count, layer=layer)
    elif scope.scope == 'speaker':
        cue = next((c for c in page.project.cues if c.id == page.selected_cue_id), None)
        text = tr('说话人 {speaker} · {layer} · 共 {count} 条', speaker=cue.speaker_id if cue else '—', layer=layer, count=count)
    else:
        text = tr('全部{layer} · 共 {count} 条', layer=layer, count=count)
    if scope.locked_ids:
        text += ' · ' + tr('跳过锁定 {count} 条', count=len(scope.locked_ids))
    if scope.missing_layer_ids:
        text += ' · ' + tr('缺少译文 {count} 条', count=len(scope.missing_layer_ids))
    return text


def report_scope(page,scope,*,applied=None,label=''):
    from ..i18n import tr
    count=len(scope.cue_ids) if applied is None else applied
    message=(tr('已应用 {count} 条字幕',count=count) if count else
             tr('当前范围 {count} 条字幕的该项已一致',count=len(scope.cue_ids)) if scope.cue_ids else
             tr('当前范围没有可编辑字幕'))
    if label:message=label+' · '+message
    if scope.locked_ids:message+=' · '+tr('跳过锁定 {count} 条',count=len(scope.locked_ids))
    if scope.missing_layer_ids:message+=' · '+tr('缺少译文 {count} 条',count=len(scope.missing_layer_ids))
    page._last_presentation_scope=scope
    show=getattr(page,'_show_studio_hint',None)
    if callable(show):show(message)
    return message
