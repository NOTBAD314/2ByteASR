"""Selected translation channel uses its own language and never source audio timestamps."""
import copy
from PySide6.QtGui import QUndoCommand
from ..subtitle_rules import subtitle_translation as translations
from ..projects.studio_runtime_state import DirtyDomain


class TranslationLayoutCommand(QUndoCommand):
    def __init__(self, project, values):
        super().__init__('译文换行')
        self.project, self.before = project, translations.snapshot(project)
        working = copy.deepcopy(project)
        for key, value in values.items(): translations.set_manual(working, key, value)
        self.after = translations.snapshot(working)
        self.ids = tuple(values)

    def apply(self, metadata):
        from ..timeline.studio_commands import _commit_mutation
        _commit_mutation(self.project, action_id=self.text(),
            dirty=DirtyDomain.CUE_CONTENT | DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE,
            cue_ids=self.ids, mutate=lambda:translations.restore_snapshot(self.project,metadata),
            changed=None, generation_metadata_keys=('translations','translation_records'))

    def redo(self): self.apply(self.after)
    def undo(self): self.apply(self.before)


def start(page, *, whole_project=False, retry_ids=None):
    from .studio_sentence_refine_ui import SentenceRefineWorker
    from ..storage.settings import load_runtime_settings
    from ..providers.llm_config import text_ai_key_missing
    from ..caption_style.bilingual_layout import translations_of, translation_for_cue
    from ..subtitle_rules.sentence_refine_ranges import build_range_replacement
    project = page.project
    target = translations.container_target(project)
    language = translations.TARGET_LANGUAGE.get(target, target)
    available = translations_of(project.generation_metadata)
    ids = set(retry_ids or getattr(page.timeline,'translation_selected_ids',()) or [page.selected_cue_id])
    originals = [cue for cue in project.cues if (whole_project or cue.id in ids) and translation_for_cue(available,cue.id)]
    if not originals: page.save_state.setText('译文断句：没有选中的译文'); return
    settings=load_runtime_settings();settings=settings[0] if isinstance(settings,tuple) else settings
    if text_ai_key_missing(settings,'group'):
        from ..app.api_key_explainer import offer_api_key_help
        page.save_state.setText('译文断句没有运行：还没填 API Key'); offer_api_key_help(page); return
    working=copy.deepcopy(project)
    working.cues=copy.deepcopy(originals)
    working.generation_metadata['language']={'requested':language,'code':language}
    working.studio_state['_refine_translation_projection']=True
    working.studio_state['caption_timeline']={'instances':{}}
    working.asr_evidence={}
    before={cue.id:str(translation_for_cue(available,cue.id)) for cue in originals}
    for cue in working.cues:
        cue.text=before[cue.id];cue.evidence_refs=[]
        cue.transform=dict(cue.transform, _language_materialized='translation')
    task=page._new_subtitle_task('译文断句',originals); page._refine_task=task
    worker=SentenceRefineWorker(working.cues,working,settings,page);page._refine_worker=worker
    task.cancel_action=worker.requestInterruption
    worker.progress.connect(task.update)
    def done(outcome):
        page._refine_worker=None
        current=translations_of(project.generation_metadata)
        valid=page.project is project and translations.container_target(project)==target and not task.cancelled
        actions={action.cue_id:action for action in outcome.actions};values={}
        for unit in outcome.ranges:
            row=dict(outcome.results[unit.cue.id]);action=actions.get(unit.cue.id)
            stale=not valid or any(str(translation_for_cue(current,cue.id) or '')!=before[cue.id] for cue in unit.originals)
            if stale:row.update(status='cancelled',phase='译文或工程已变化，丢弃旧结果')
            elif action and action.action=='keep':row.update(status='unchanged',phase='译文已校验，无需调整')
            elif action:
                try:
                    if action.action=='split':
                        if language.split('-')[0] != 'en':
                            raise ValueError('译文没有可靠发声词时间；保留本语言原译文与时间')
                        from ..subtitle_rules.english_refine_constraints import wrap_action
                        action=wrap_action(unit,working)
                    result=build_range_replacement(unit,action,working,set())
                    for cue in result:values[cue.id]=cue.text
                    row.update(status='applied',phase='译文已换行；保持原时间，无译文发声词时间',final_texts=[cue.text for cue in result])
                except Exception as exc:row.update(status='failed',phase='保留译文',error=str(exc))
            task.update(row)
        if values:page.undo_stack.push(TranslationLayoutCommand(project,values))
        task.finish(cancelled=task.cancelled);page.save_state.setText(task.summary())
    worker.finished_ok.connect(done)
    worker.failed.connect(lambda message:page._sentence_refine_failed(message,task=task))
    worker.finished.connect(worker.deleteLater);worker.start()
