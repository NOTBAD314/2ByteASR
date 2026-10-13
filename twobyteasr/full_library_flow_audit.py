"""Opt-in normal-window full-build button audit; all mutable data is isolated."""
import json, time
from dataclasses import asdict, is_dataclass
from pathlib import Path

def start(owner, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require
    from .provider_diagnostics import redact_diagnostics
    output=Path(output);app=QApplication.instance()
    app.setQuitOnLastWindowClosed(False)
    result=dict(passed=False,real_network=True,checks=[],events=[],started_at=time.time())
    state=dict(phase='start',busy=False,task_id='',finished=None,error=None)
    deadline=time.monotonic()+240
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));require(value,name)
    def finish(error=None):
        timer.stop()
        if error:result['error']=str(error)
        result['passed']=error is None
        result['elapsed_seconds']=round(time.time()-result['started_at'],3)
        encode=lambda value:asdict(value) if is_dataclass(value) else str(value)
        (output/'full-library-result.json').write_text(json.dumps(redact_diagnostics(result),ensure_ascii=False,indent=2,default=encode),'utf8')
        def after_close():
            result['gui_shutdown']=True
            (output/'full-library-result.json').write_text(json.dumps(redact_diagnostics(result),ensure_ascii=False,indent=2,default=encode),'utf8')
        app.aboutToQuit.connect(after_close)
        owner.close()
    def tick():
        if state['busy']:return
        state['busy']=True
        try:
            if time.monotonic()>deadline:raise TimeoutError('actual full-build button audit timed out')
            if state['phase']=='start':
                owner._manage_terms();app.processEvents()
                page=owner.term_library_page._ensure_library();state['page']=page
                for i in range(page.game_list.count()):
                    item=page.game_list.item(i)
                    if str(item.data(Qt.ItemDataRole.UserRole + 1))=='瓦罗兰特':
                        page.game_list.setCurrentItem(item);break
                check('actual existing library selected',page._library_key()=='瓦罗兰特',page._library_key())
                selected=page.ai_service_combo.findData('deepseek')
                check('approved official provider exists',selected>=0)
                page.ai_service_combo.setCurrentIndex(selected)
                page.ai_model_combo.setCurrentText('deepseek-v4-pro')
                check('one direct full-build button',page.ai_full_button.text()=='AI 完整建库' and page.ai_full_button.menu() is None)
                check('conservative numeric label',owner.prefer_arabic_numbers.text()=='数字规范化（保留口语小数字）')
                manager=page._ensure_task_manager();state['manager']=manager
                manager.task_finished.connect(lambda tid,game,payload:state.update(task_id=tid,finished=payload))
                manager.task_failed.connect(lambda tid,game,code,detail:state.update(task_id=tid,error=dict(code=code,detail=detail)))
                manager.task_progress.connect(lambda tid:result.update(events=list(manager._tasks[tid].events)))
                _capture(owner,output/'full-build-before.png')
                QTest.mouseClick(page.ai_full_button,Qt.MouseButton.LeftButton)
                state['phase']='waiting';state['shot_at']=time.monotonic()+1
            elif state['phase']=='waiting':
                if state.get('shot_at') and time.monotonic()>state['shot_at']:
                    _capture(owner,output/'full-build-running.png');state['shot_at']=None
                if state['finished'] is None and state['error'] is None:return
                payload=state['finished']
                if payload is not None:
                    result['result']=payload
                    execution=payload.get('execution',{})
                    check('model attempt recorded',int(execution.get('model_calls') or 0)>0,execution)
                    check('task target identity recorded',payload.get('library_id')=='瓦罗兰特',payload.get('library_id'))
                    check('terminal outcome truthful',payload.get('outcome',{}).get('status') in {'new_candidates','success','success_with_new','no_changes','partial','failed','cancelled','blocked','no_effective_content'},payload.get('outcome'))
                    check('separate stage statistics',all(k in payload.get('build_stats',{}) for k in ('planned_queries','discovered_links','fetch_succeeded','parse_succeeded','verified_sources','ai_candidates','deduped_candidates','new_candidates','filtered_candidates')),payload.get('build_stats'))
                    result['actual_task_id']=payload.get('task_id')
                else:
                    result['task_failure']=state['error']
                    check('actual request or classified terminal failure visible',bool(result['events']) and bool(state['error']['code']),state['error'])
                _capture(owner,output/'full-build-terminal.png')
                state['phase']='done';finish()
        except BaseException as exc:finish(exc)
        finally:state['busy']=False
    timer=QTimer(owner);timer.setInterval(50);timer.timeout.connect(tick);timer.start()
    owner._full_library_audit_timer=timer
