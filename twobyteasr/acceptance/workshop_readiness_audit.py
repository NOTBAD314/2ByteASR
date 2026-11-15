"""Normal application tests of real alignment readiness, UI scope and worker use."""
from __future__ import annotations
import copy,json,os,sys,time,traceback
from pathlib import Path


def install_guards():
    from .blank_project_audit import install_offline_guards
    install_offline_guards()
    from ..storage.storage_ui import IdleStorageMaintenance
    IdleStorageMaintenance.check=lambda self:None
    from ..local_models import model_workshop
    model_workshop.cleanup_orphan_download_temps=lambda *a,**k:None


def start(window,out):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..local_models import model_workshop as w
    from ..recognition.qwen_family import head_requested
    from ..recognition.alignment_backend import selected_backend
    def _capture(target,path):
        if not target.grab().save(str(path)):raise RuntimeError('Qt window capture failed')
    from ..storage.settings import load_runtime_settings
    app=QApplication.instance();result=dict(passed=False,checks=[],pid=os.getpid(),kind='real files/runtime/actual matching receipt, private user-data copy; controlled unavailable states separated');state={};poll=QTimer(window)
    def save():(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail))
        save()
        if not ok:raise AssertionError(name)
    def finish(error=None):
        poll.stop()
        if error:result['error']=error
        save()
        try:window.studio_page.undo_stack.setClean()
        except Exception:pass
        window.close();QTimer.singleShot(400,app.quit)
    def inventory(page):
        return {m.key:dict(state=page._model_state(m,'timeline'),action=page._action_text(m,page._model_state(m,'timeline')),snapshot=getattr(page._registry,'alignment_readiness',{}).get(m.key),binding=m.adapter_bindings,download_key=m.download_key,install_keys=m.install_keys) for m in w.MODELS if m.key in {'qwen_aligner','mfa_aligner'}}
    def run():
        try:
            original=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
            window._open_model_workshop();page=window.workshop_page
            yield (lambda:page._ui_built and page._registry is not None and not page.background_busy(),20)
            check('only one common Ultra card',{'qwen_aligner','mfa_aligner'}<=page._cards.keys() and not {'qwen_ultra_head','qwen_ultra_aligner'}&page._cards.keys())
            page._set_role('timeline')
            yield (lambda:True,1)
            result['actual_initial']=inventory(page)
            check('existing matching Ultra ready without new validation',page._model_state(next(m for m in w.MODELS if m.key=='qwen_aligner'),'timeline')=='installed',result['actual_initial'])
            check('no inference or Torch loaded by GUI','torch' not in sys.modules)
            check('Head installed does not enable it',not head_requested(window.legacy.RUNTIME_SETTINGS))
            check('real base button uses current state',page._cards['qwen_aligner'].action.isEnabled() and page._cards['qwen_aligner'].action.text()=='使用')
            check('no unsupported100 score',not page._cards['qwen_aligner'].metrics_host.isVisible())
            _capture(window,out/'actual-ready.png')
            before=(window.primary_asr_backend.currentData(),window.qwen_asr_backend.currentData())
            for role in ['primary','review','timeline','primary','timeline']:
                page._set_role(role)
                yield (lambda:True,1)
                check('role transition '+role,True)
            check('returning to timeline recalculates button',page._cards['qwen_aligner'].action.text()=='使用' and page._cards['qwen_aligner'].action.isEnabled())
            from ..design.theme_manager import apply_theme
            from ..i18n import apply_ui_language
            for theme in ['warm','grape','warm']:
                apply_theme(theme,app);apply_ui_language(page)
                yield (lambda:True,1)
                check('theme/language never restores download placeholder',page._cards['qwen_aligner'].action.text()=='使用')
            # Controlled bad-state UI: no real files, environment or receipts altered.
            registry=page._registry
            for bad in ['missing','partial','runtime_missing','inference_pending','load_failed']:
                fake=copy.copy(registry);fake.alignment_readiness=copy.deepcopy(registry.alignment_readiness);fake.alignment_readiness['qwen_aligner'].update(state=bad,ready=False,reason='controlled unavailable case: '+bad)
                page.refresh(registry=fake,check_status=False)
                action=page._cards['qwen_aligner'].action
                check(bad+' cannot offer Use',action.text()!='使用' and not page._cards['qwen_aligner'].property('selected'))
                yield (lambda:True,1)
            page.refresh(registry=registry,check_status=False)
            check('base recovers immediately without restart',page._cards['qwen_aligner'].action.text()=='使用')
            window._open_model_picker('timeline')
            yield (lambda:True,1)
            panel=window._model_picker_timeline_panel
            check('picker also has one family',not {'qwen_ultra_head','qwen_ultra_aligner'}&panel.cards.keys() and 'qwen_aligner' in panel.cards)
            window._modal_host._request_close()
            yield (lambda:not window._modal_host.isVisible(),5)
            page._perform_action('qwen_aligner',role='timeline')
            yield (lambda:window.legacy.RUNTIME_SETTINGS['models']['firered_asr_backend']=='qwen_aligner',30)
            saved=load_runtime_settings()[0]
            check('selection persists to same family',saved['models']['firered_asr_backend']=='qwen_aligner')
            check('other ASR choices unchanged',before==(window.primary_asr_backend.currentData(),window.qwen_asr_backend.currentData()))
            values=[window.firered_asr_backend.itemData(i) for i in range(window.firered_asr_backend.count())]
            check('settings selector has one Ultra',values.count('qwen_aligner')==1 and 'qwen_ultra_head' not in values and 'qwen_ultra_aligner' not in values)
            check('later worker resolves base',selected_backend(window.legacy.RUNTIME_SETTINGS)=='qwen_ultra_aligner')
            check('sidebar names the same Ultra family','Ultra' in page.combo_model_labels['timeline'].text())
            check('sidebar reads effective readiness',page.combo_status_labels['timeline'].property('ready') is True)
            page._set_role('timeline');_capture(window,out/'selected-synchronized.png')
            yield (lambda:True,1)
            # Real Studio operation and frozen settings. No old project is modified.
            from ..studio.studio_realign import start_realign
            window.open_studio_project(str(Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])),mode='edit',source='workshop_readiness_audit')
            state['phase']='opening';state['deadline']=time.monotonic()+150
            poll.start(50)
        except Exception:finish(traceback.format_exc())
    def step():
        try:
            if state['phase']=='setup':
                pending=state.get('setup_pending')
                if pending is not None and not pending[0]():
                    if time.monotonic()>state['deadline']:raise TimeoutError('UI setup condition timeout')
                    return
                try:
                    condition,timeout=next(state['setup'])
                    state['setup_pending']=(condition,timeout);state['deadline']=time.monotonic()+timeout
                except StopIteration:
                    if state['phase']=='setup':raise RuntimeError('Setup ended before opening Studio')
                return
            studio=window.built_page('studio')
            if time.monotonic()>state['deadline']:raise TimeoutError('Studio actual alignment timeout')
            if state['phase']=='opening':
                if studio is None or studio.project is None or not studio.project.cues or not studio._readiness.ready:return
                cue=studio.project.cues[0];state.update(cue=cue,before=(cue.text,cue.start_ms,cue.end_ms),frozen=copy.deepcopy(window.legacy.RUNTIME_SETTINGS))
                studio.runtime_settings=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
                if studio.video.controller is not None:studio.video.controller.set_volume(0)
                studio.volume_slider.setValue(0)
                from ..studio.studio_realign import start_realign
                start_realign(studio,[cue.id]);studio.show_subtitle_tasks();state['task']=max(studio._subtitle_tasks.values(),key=lambda x:x.started);state['phase']='freeze'
                return
            task=state['task']
            if state['phase']=='freeze' and ('加载模型' in task.phase or '词级对齐' in task.phase):
                window.legacy.RUNTIME_SETTINGS['models']['qwen_alignment_head']=True
                studio.runtime_settings=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
                state['phase']='wait-real'
            if task.ended is None:return
            if state['phase'] in {'freeze','wait-real'}:
                check('real Studio operation applied',task.counts()['applied']==1,task.counts())
                from ..timeline.studio_caption_timeline import KEY
                row=studio.project.studio_state[KEY]['instances'][state['cue'].id];proof=row['forced_alignment']
                check('actual Ultra model recorded',proof['model']=='17slever17/Qwen3-ForcedAligner-Ultra')
                check('old in-flight task stays base despite new setting',proof['alignment_identity']['local_head'] is None)
                check('original cue and text not rewritten',state['before']==(state['cue'].text,state['cue'].start_ms,state['cue'].end_ms))
                window.legacy.RUNTIME_SETTINGS['models']['qwen_alignment_head']=False
                studio.runtime_settings=copy.deepcopy(window.legacy.RUNTIME_SETTINGS)
                result['worker_identity']=proof['alignment_identity']
                from ..projects.studio_project import save_project,load_project
                path=out/'roundtrip.2byteproj';save_project(studio.project,path);check('project reopens with same text',load_project(path).cues[0].text==state['cue'].text)
                words=copy.deepcopy(row.get('words'));studio.undo_stack.undo();studio.undo_stack.redo();check('word evidence undo/redo stable',studio.project.studio_state[KEY]['instances'][state['cue'].id].get('words')==words)
                from ..studio.studio_realign import start_realign
                start_realign(studio,[state['cue'].id]);state['task']=max(studio._subtitle_tasks.values(),key=lambda x:x.started);state['phase']='cache';return
            if state['phase']=='cache':
                check('repeated actual operation applied',task.counts()['applied']==1)
                progress=task.alignment_progress
                check('actual acoustic cache hit',progress.get('cached')==1 and progress.get('local')==0,progress)
                _capture(window,out/'studio-real-cache.png')
                result['actual_final']=inventory(window.workshop_page);result['passed']=True;finish()
        except Exception:finish(traceback.format_exc())
    poll.timeout.connect(step)
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
    def begin():
        state.update(phase='setup',setup=run(),setup_pending=None);poll.start(100)
    QTimer.singleShot(2500,begin)
