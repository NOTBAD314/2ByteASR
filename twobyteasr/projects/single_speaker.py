"""Explicit, undoable identity confirmation without replaying ASR or changing text."""
from __future__ import annotations

import copy
from dataclasses import asdict, replace


def confirm_single_speaker_command(project, *, target_id=None, changed=None):
    """The caller explicitly confirms one person; automatic analysis never calls this.

    Keep every cue's authored appearance. A missing cue style that fell back
    to its former speaker's style is pinned before removing that speaker.
    Only small identity metadata branches are copied; ASR/translation archives
    are never rewritten or materialized by this operation.
    """
    from ..timeline.studio_commands import SpeakerStateCommand
    if not project.speakers:
        raise ValueError('当前工程没有说话人标签。')
    target_id = str(target_id or project.speakers[0].id)
    speakers = {s.id:s for s in project.speakers}
    if target_id not in speakers:
        raise ValueError('目标说话人已经不存在。')
    if len(speakers)==1:
        raise ValueError('当前工程已经只有一个说话人标签。')
    styles = {s.id for s in project.styles}
    cues = []
    for cue in project.cues:
        style_id = cue.style_id
        if style_id not in styles and cue.base_preset_id not in styles:
            old = speakers.get(cue.speaker_id)
            style_id = old.style_id if old and old.style_id in styles else 'default'
        cues.append(replace(cue,speaker_id=target_id,style_id=style_id))
    target = replace(speakers[target_id],is_host=True)
    recovery = project.generation_metadata.get('speaker_recovery') or {}
    organization = project.generation_metadata.get('speaker_organization') or {}
    labels = set(speakers) | set(recovery.get('roles') or {})
    decisions = dict(organization.get('decisions') or {})
    decisions.update({label:'main' if label==target_id else 'merge:'+target_id for label in labels})
    originals = dict(organization.get('original_speakers') or {})
    originals.update({key:asdict(value) for key,value in speakers.items() if key!=target_id})
    changes = {
        ('speaker_recovery','roles'):{label:'main' if label==target_id else 'merge:'+target_id for label in labels},
        ('speaker_recovery','confirmed_by'):'user_single_speaker',
        ('speaker_recovery','needs_confirmation'):False,
        ('speaker_recovery','unconfirmed_candidates'):[],
        ('speaker_organization','needs_manual_host_selection'):False,
        ('speaker_organization','decisions'):decisions,
        ('speaker_organization','original_speakers'):originals,
        ('speaker_organization','single_speaker_confirmation'):{
            'target':target_id,'members':sorted(labels),'confirmed_by':'user',
            'cue_origins':{cue.id:cue.speaker_id for cue in project.cues},
            'style_rule':'preserve_each_cue_effective_style'},
    }
    before = {path:(path[1] in (project.generation_metadata.get(path[0]) or {}),
                   copy.deepcopy((project.generation_metadata.get(path[0]) or {}).get(path[1]))) for path in changes}
    old_roots = {key:key in project.generation_metadata for key,_ in changes}
    old_view = {key:(key in project.studio_state,copy.deepcopy(project.studio_state.get(key)))
                for key in ('speaker_track_order','speaker_roles')}
    roles = dict(project.studio_state.get('speaker_roles') or {})
    roles.update(grouped=False,expanded=False,auto={target_id:'main'},manual={target_id:'main'})

    class Command(SpeakerStateCommand):
        def __init__(self):
            super().__init__(project,[target],cues,'确认全片为同一位说话人',changed)
            self.error = ''

        def _apply_identity(self, forward):
            backup = project.generation_metadata,project.studio_state,project.cues,project.speakers
            metadata = dict(project.generation_metadata)
            for root in old_roots:
                branch = dict(metadata.get(root) or {})
                for path, value in changes.items():
                    if path[0]!=root:continue
                    present, desired = (True,value) if forward else before[path]
                    if present:branch[path[1]]=copy.deepcopy(desired)
                    else:branch.pop(path[1],None)
                if branch or old_roots[root]:metadata[root]=branch
                else:metadata.pop(root,None)
            state = dict(project.studio_state)
            for key,value in (('speaker_track_order',[target_id]),('speaker_roles',roles)):
                present,desired = (True,value) if forward else old_view[key]
                if present:state[key]=copy.deepcopy(desired)
                else:state.pop(key,None)
            project.generation_metadata,project.studio_state = metadata,state
            self.error = ''
            try:
                self._apply(forward)
            except Exception as error:
                project.generation_metadata,project.studio_state,project.cues,project.speakers = backup
                self.error = f'{type(error).__name__}: {error}'
                if changed:changed()

        def redo(self):self._apply_identity(True)
        def undo(self):self._apply_identity(False)
    return Command()
