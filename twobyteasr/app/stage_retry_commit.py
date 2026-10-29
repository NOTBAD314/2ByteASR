"""GUI-thread commit: validate input, save results, then publish one undo step."""
from __future__ import annotations
import copy
from PySide6.QtGui import QUndoCommand
from ..recognition.processing_recovery import KEY,input_matches
from ..projects.studio_runtime_state import DirtyDomain
from ..timeline.studio_commands import _commit_mutation


class StageResultCommand(QUndoCommand):
    def __init__(self,project,candidate,changed):
        super().__init__('应用已验证的阶段重试结果');self.project=project;self.changed=changed
        self.before=(copy.deepcopy(project.cues),copy.deepcopy(project.generation_metadata),copy.deepcopy(project.studio_state))
        self.after=(copy.deepcopy(candidate.cues),copy.deepcopy(candidate.generation_metadata),copy.deepcopy(candidate.studio_state))
        old={c.id:c for c in self.before[0]};new={c.id:c for c in self.after[0]}
        self.ids=[k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)]
    def _apply(self,value):
        def mutate():
            self.project.cues=copy.deepcopy(value[0]);self.project.generation_metadata=copy.deepcopy(value[1]);self.project.studio_state=copy.deepcopy(value[2])
        _commit_mutation(self.project,action_id=self.text(),cue_ids=self.ids,changed=self.changed,mutate=mutate,
            dirty=DirtyDomain.CUE_MODEL|DirtyDomain.CUE_CONTENT|DirtyDomain.CUE_TIMING|DirtyDomain.TIMELINE_INDEX|
            DirtyDomain.TIMELINE_PIXELS|DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.ADVANCED_PREVIEW|DirtyDomain.AUTOSAVE)
    def redo(self):self._apply(self.after)
    def undo(self):self._apply(self.before)


def commit_unit_result(studio,report,unit):
    project=studio.session.project
    if project is None or str(project.project_id)!=unit['project_id']:raise ValueError('当前工程已切换，重试结果未写入')
    if unit.get('input') and not input_matches(project,unit['input']):raise ValueError('重试范围或译文已被编辑；未覆盖新修改')
    path=getattr(studio,'project_path',None) or getattr(studio.session,'project_path',None)
    if path is None:raise ValueError('当前工程没有保存路径，不能清除失败状态')
    from ..projects.studio_project import SubtitleProject,StudioCue,save_project
    candidate=SubtitleProject.from_dict(copy.deepcopy(project.to_dict()))
    result=copy.deepcopy(unit);translation=result.pop('translation_result',None)
    replacements=result.pop('replacements',{})
    if replacements:
        from ..timeline.studio_commands import SpliceCuesCommand
        index={c.id:i for i,c in enumerate(candidate.cues)}
        for cue_id,rows in sorted(replacements.items(),key=lambda p:-index[p[0]]):
            cues=[StudioCue(**row) for row in rows]
            SpliceCuesCommand(candidate,index[cue_id],1,cues,'阶段断句重试').redo()
    if unit['stage']=='grouping':
        succeeded=set(unit.get('cue_ids',()))-set(result.get('failed_cue_ids',()))
        result['completed_cue_ids']=sorted(set(unit.get('completed_cue_ids',()))|succeeded)
        if result.get('failed_cue_ids'):
            result.update(cue_ids=result['failed_cue_ids'],capture_by_id=True)
            from ..recognition.processing_recovery import capture_unit
            result['input']=capture_unit(candidate,result)
        refine=candidate.studio_state.get('ai_sentence_refine') or {}
        if refine:
            refine['failed_cue_ids']=[k for k in refine.get('failed_cue_ids',()) if k not in succeeded]
            refine['last_status']='partial' if refine['failed_cue_ids'] else 'completed'
    if translation is not None:
        from ..subtitle_rules.subtitle_translation import apply_translation_result
        # The captured input/translation version was checked on the live
        # project above. The target clone is the transaction's own instance.
        translation.project_instance=id(candidate);translation.project_id=str(candidate.project_id)
        translation.content_revisions={};translation.revisions={}
        apply_translation_result(candidate,translation)
        if translation.discarded or translation.suggestions:
            result.update(status='failed',reason='译文在重试期间已编辑；AI结果未覆盖人工译文')
    ledger=candidate.generation_metadata.setdefault(KEY,{'version':1,'units':{}})
    ledger.setdefault('units',{})[result['key']]=result
    # Save must succeed before a resolved unit becomes visible in any UI.
    save_project(candidate,path)
    if replacements or translation is not None:
        studio.session.undo_stack.push(StageResultCommand(project,candidate,getattr(studio,'_changed',None)))
    else:
        from ..projects.studio_runtime_state import state_for
        with state_for(project).transaction(project,action_id='保存阶段重试状态',dirty=DirtyDomain.AUTOSAVE,
                affected_cue_ids=tuple(result.get('cue_ids',()))):
            project.generation_metadata=copy.deepcopy(candidate.generation_metadata)
            project.studio_state=copy.deepcopy(candidate.studio_state)
    return result
