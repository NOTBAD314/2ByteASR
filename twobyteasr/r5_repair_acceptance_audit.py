"""Opt-in normal-entry verification; exactly two explicitly budgeted requests."""
import json
import os
import sys
import threading
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, Signal, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from .build_identity import load_build_identity
    from .studio_acceptance_audit import require
    from .glossary_task_manager import GlossaryTaskState
    from .glossary_skill_ui import GlossaryTaskCandidatesDialog
    from .provider_diagnostics import redact_diagnostics
    from .task_execution_events import ExecutionObserver
    from .theme_manager import apply_theme
    apply_theme('grape',QApplication.instance())

    class Audit(QObject):
        event = Signal(object)
        done = Signal()

        def __init__(self):
            super().__init__(window)
            self.result = dict(build=vars(load_build_identity()),executable=sys.executable,
                environment='normal Windows entry on isolated desktop; no human acceptance',checks=[],calls=[])
            self.task = GlossaryTaskState('r5-live','我的世界','full','grok_account','grok-4.7',time.time(),status='running')
            self.event.connect(self.add_event)
            self.done.connect(self.finish)
            self.dialog = GlossaryTaskCandidatesDialog(window,self.task)
            self.dialog.setWindowFlag(Qt.WindowType.Window,True)
            self.dialog.resize(1100,800)
            self.dialog.show()
            self.dialog.process_view.toggle.setChecked(True)
            threading.Thread(target=self.work,daemon=True,name='r5-budgeted-audit').start()

        def add_event(self,row):
            row=dict(row,seq=len(self.task.events)+1)
            self.task.events.append(row)
            if row.get('kind')=='stage':
                self.task.stage=row.get('stage','')
                self.task.message=str(row.get('payload',''))
            if row.get('source') in {'provider','http'}:self.task.last_event_at=time.time()
            with (output/'execution-events.jsonl').open('a',encoding='utf8') as f:
                f.write(json.dumps(redact_diagnostics(row),ensure_ascii=False)+'\n')

        def save(self):
            (output/'result.json').write_text(json.dumps(redact_diagnostics(self.result),ensure_ascii=False,indent=2,default=str),'utf8')

        def work(self):
            from . import network_policy
            from .glossary_skill import settings_with_service_override
            from .ai_providers import provider_for_stage
            from .glossary_build import run_full_library_update,serialize_term,CATALOG_SCHEMA,build_catalog_messages
            from .llm_config import active_service_values
            import subtitle_core as legacy
            try:
                self.result['network']=network_policy.snapshot()
                settings=settings_with_service_override(legacy.RUNTIME_SETTINGS,'deepseek','deepseek-v4-pro')
                provider=provider_for_stage(settings,'polish')
                try:
                    self.result['models']=list(provider.discover_models(timeout=20,refresh=True))
                    self.result['models_fresh']=True
                except Exception as exc:
                    self.result['models_error']=dict(category=getattr(exc,'category','error'),message=str(exc))
                    self.result['models_fresh']=False
                config=json.loads((output/'run-config.json').read_text('utf8'))
                tls=config.get('local_tls',{})
                self.result['tls_controls']=[]
                for key,host,ca in [('valid','localhost',tls.get('ca')),('untrusted','localhost',None),('hostname','127.0.0.1',tls.get('ca'))]:
                    if not tls:break
                    try:
                        response=network_policy.get(f'https://{host}:{tls["port"]}/',timeout=5,**({'verify':ca} if ca else {}))
                        self.result['tls_controls'].append(dict(case=key,status=response.status_code,accepted=True))
                    except Exception as exc:
                        self.result['tls_controls'].append(dict(case=key,accepted=False,category=getattr(exc,'category',type(exc).__name__)))
                if os.environ.get('TWOBYTEASR_R5_LIVE')=='1':
                    self.budgeted('deepseek_short',provider,lambda:provider.complete(
                        [{'role':'user','content':'Return exactly: 2ByteASR_OK'}],stage='provider_readiness',
                        operation_kind='generate',max_tokens=32,temperature=0,timeout=(8,60)))
                    grok=settings_with_service_override(legacy.RUNTIME_SETTINGS,'grok_account','grok-4.7')
                    client=provider_for_stage(grok,'polish')
                    self.result['grok_account']=vars(client.validate(timeout=20,use_cache=False))
                    observer=ExecutionObserver(self.event.emit,dict(service='grok_account',model='grok-4.7',transport='grok_cli'))
                    diag={}
                    self.budgeted('grok_search',client,lambda:client.structured_complete(
                        build_catalog_messages('我的世界'),CATALOG_SCHEMA,stage='glossary_directory',
                        operation_kind='glossary_update',enable_search=True,max_tokens=4000,temperature=0,
                        timeout=360,first_response_timeout=90,idle_timeout=180,request_diagnostics=diag,
                        on_stream_event=observer.stream))
                    self.result['grok_search_diagnostics']=diag
                settings=settings_with_service_override(legacy.RUNTIME_SETTINGS,'grok_account','grok-4.7')
                settings['models'].update(glossary_include_wordlists=False,glossary_include_community=False,glossary_enrich_names=False)
                def checkpoint(row):
                    (output/'minecraft-checkpoint.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),'utf8')
                result=run_full_library_update(legacy,'我的世界',settings,checkpoint_writer=checkpoint,on_event=self.event.emit)
                result['diffs']=[dict(change_type=d.change_type,term=serialize_term(d.term)) for d in result['diffs']]
                self.result['minecraft']=result
                self.task.candidates=result['candidate_count']
                self.result['completed']=True
            except Exception:
                self.result['error']=traceback.format_exc()
                self.result['completed']=False
            finally:
                self.save()
                self.done.emit()

        def budgeted(self,kind,provider,call):
            require(not any(c['kind']==kind for c in self.result['calls']),'No retries authorized')
            row=dict(kind=kind,started=time.time(),model=provider.model,status='started')
            self.result['calls'].append(row)
            self.save()  # Persist before sending. A restart cannot be mistaken for a free retry.
            began=time.monotonic()
            try:
                row.update(status='returned',response=call())
            except Exception as exc:
                row.update(status='failed',category=getattr(exc,'category',type(exc).__name__),message=str(exc))
            finally:
                row.update(elapsed_seconds=time.monotonic()-began,trace=provider.invocation_trace())
                self.save()

        def finish(self):
            try:
                self.task.status='completed'
                view=self.dialog.process_view
                QApplication.processEvents()
                view.refresh(force=True)
                self.dialog.grab().save(str(output/'execution-expanded.png'))
                QTest.mouseClick(view.toggle,Qt.LeftButton)
                require(not view.body.isVisible(),'collapse process')
                QTest.mouseClick(view.toggle,Qt.LeftButton)
                self.dialog.hide();self.dialog.show();QApplication.processEvents()
                require(bool(self.task.events),'process retained across hide/show')
                view.search.setText('web_search');view.refresh(force=True)
                self.dialog.grab().save(str(output/'execution-search.png'))
                view.search.clear()
                self.dialog.resize(1000,720);QApplication.processEvents()
                self.dialog.grab().save(str(output/'execution-compact.png'))
                require(view.text.horizontalScrollBar().maximum()==0,'no horizontal process scrolling')
                self.result['checks'].extend(['collapse/expand','hide/show preserves events','search','compact no horizontal scrollbar'])
                # The same optional view must stay bounded when a long task has
                # accumulated many events. These rows are explicitly synthetic.
                real_events=list(self.task.events)
                self.task.events=[dict(seq=i,timestamp=time.time(),source='application',kind='synthetic stress fixture',
                    payload='本地性能夹具，无外部调用 '+('x'*300)) for i in range(1500)]
                began=time.perf_counter();view.refresh(force=True)
                self.result['1500_event_render_ms']=(time.perf_counter()-began)*1000
                require(self.result['1500_event_render_ms']<1500,'bounded process view rendering')
                self.task.events=real_events;view.refresh(force=True)
                page=window.studio_page
                marker=page.audio_diagnostic_marker
                marker.activate();marker.sample();marker.finish('isolated_marker_smoke')
                self.result['audio_marker_smoke']=True
                self.result['ui_verified']=True
            except Exception:
                self.result['ui_error']=traceback.format_exc()
            self.save()
            self.dialog.hide();self.dialog.deleteLater()
            window.studio_page.undo_stack.setClean()
            window.close()

    def ready():
        gate=getattr(window.studio_page,'_readiness',None)
        if gate is not None and gate.active:QTimer.singleShot(100,ready);return
        window._r5_repair_audit=Audit()
    QTimer.singleShot(1200,ready)
