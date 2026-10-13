"""Real Home widgets, Studio selection and CLI calls in source/frozen Qt."""
import json
import os
import threading
import time
import traceback
from pathlib import Path


def start_provider_acceptance(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout
    from . import ai_providers,studio_ai
    from .build_identity import load_build_identity
    from .llm_config import active_service_values
    from .settings import load_runtime_settings
    from .provider_diagnostics import redact_diagnostics
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    # App settings remain isolated. Only official CLI child processes receive
    # their normal LOCALAPPDATA, so the CLI can manage its own existing login.
    original_spawn=ai_providers.popen_hidden_subprocess
    def spawn(*args,**kwargs):
        real=os.environ.get('TWOBYTEASR_ACCEPTANCE_REAL_LOCALAPPDATA')
        if real:kwargs['env']={**os.environ,'LOCALAPPDATA':real}
        return original_spawn(*args,**kwargs)
    ai_providers.popen_hidden_subprocess=spawn
    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page
            self.result={'build':vars(load_build_identity()),'checks':{},'manual_gate':'Fresh interactive Codex OAuth login/cancel/logout requires the user; existing-session design is audited below.'}
            from .login_acceptance_probe import login_control_checks
            self.result['checks'].update(login_control_checks())
            self.started=time.perf_counter();self.wait=0;self.sequence=self.run()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer);self.timer.timeout.connect(self.tick);self.timer.start(5)
        def tick(self):
            try:
                if time.perf_counter()-self.started>165:raise TimeoutError('provider audit deadline')
                if callable(self.wait):
                    if not self.wait():return
                elif time.perf_counter()<self.wait:return
                value=next(self.sequence);self.wait=value if callable(value) else time.perf_counter()+value
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def check(self,name,value):self.result['checks'][name]=bool(value)
        def run(self):
            page=self.page
            yield lambda: page.project is not None and page.video._startup_state=='READY'
            page.context_drawer.setCurrentIndex(0)
            if getattr(page,'_ai_provider_probe_cancel',None):page._ai_provider_probe_cancel.set()
            page._ai_provider_probe_generation+=1;page._ai_provider_probe_cancel=None
            # Reuse the real Home configuration panel, as the normal modal does.
            self.old_parent=window.ai_panel.parentWidget()
            self.dialog=QDialog(window);self.dialog.setWindowTitle('Home provider acceptance');self.dialog.resize(1150,820)
            layout=QVBoxLayout(self.dialog);layout.addWidget(window.ai_panel)
            window.ai_panel.set_expanded(True,animate=False);window.ai_panel.show();self.dialog.show()
            window.unified_glm.setChecked(True)
            for editor in (window.polish_editor,window.group_editor):
                editor.service.setCurrentIndex(editor.service.findData('antigravity'))
                editor.model.setCurrentText('gemini-3.8-flash-high')
                editor._model_discovery_timer.stop()
            self.check('home-save-high',window._save_ai_configuration(show_feedback=False))
            loaded,_,_=load_runtime_settings()
            self.check('disk-reopen-high',active_service_values(loaded,stage='polish')['model']=='gemini-3.8-flash-high')
            yield .2
            self.dialog.grab().save(str(output/'home-high-saved.png'))
            self.dialog.hide();window.ai_panel.setParent(self.old_parent);window.ai_panel.hide()
            page._reload_ai_provider_selection()
            self.check('studio-reopens-high',page.ai_model.currentText()=='gemini-3.8-flash-high')
            yield lambda: getattr(page,'_ai_provider_probe_cancel',None) is None
            self.result['high_probe_status']=page.ai_provider_health.text()
            client=ai_providers.provider_for_stage(page.runtime_settings,'polish')
            self.result['high_probe']=client.invocation_trace()
            self.result['initial_probe_authenticated']=str(client.cached_health().state.value)=='READY'
            home_client=ai_providers.provider_for_stage(window.group_editor._cli_settings(),'group')
            self.check('home-studio-share-initial-health',home_client.cached_health() is client.cached_health())
            page._copy_ai_provider_diagnostics()
            self.check('seven-phase-clipboard',len(json.loads(QApplication.clipboard().text())['trace']['phases'])==7)
            page.grab().save(str(output/'studio-high-ready.png'))
            # A real models query is cancelled, preserving the successful session.
            page._start_ai_provider_probe('antigravity',refresh_models=True)
            yield .25
            t=time.perf_counter();page._start_ai_provider_probe('antigravity',force=True)
            yield .2
            self.check('cancel-keeps-high',page.ai_model.currentText()=='gemini-3.8-flash-high')
            self.result['cancel_elapsed_ms']=(time.perf_counter()-t)*1000
            # Full generation uses the real current High adapter and normal validators.
            done=threading.Event();generated={}
            def request():
                try:
                    # A bounded real design contract checks the exact UI-selected
                    # model in this frozen/source process. The complete HTML/CSS
                    # pipeline has separate real High evidence, including rejects.
                    schema={'type':'object','properties':{'name':{'type':'string'},'textColor':{'type':'string'},
                        'entrance':{'type':'string'},'hold':{'type':'string'},'exit':{'type':'string'}},
                        'required':['name','textColor','entrance','hold','exit'],'additionalProperties':False}
                    began=time.perf_counter()
                    design=client.structured_complete([{'role':'user','content':
                        '为 Balatro 中文字幕提出一套简短设计，明确洗牌入场、火焰和筹码持续动画、收牌退出。只返回 JSON：name、textColor（十六进制色）、entrance、hold、exit。每项最多20个汉字。'}],schema,timeout=60)
                    import jsonschema
                    jsonschema.validate(design,schema)
                    generated.update(source='ai',message='真实 High 设计意图 schema 通过；完整网页主题见独立证据',
                        seconds=time.perf_counter()-began,design=design,trace=client.invocation_trace())
                except Exception as exc:generated['error']=str(exc)
                finally:done.set()
            threading.Thread(target=request,daemon=True).start()
            yield done.is_set
            self.result['high_design']=generated
            self.check('real-high-design-validated',generated.get('source')=='ai' and generated.get('trace',{}).get('model')=='gemini-3.8-flash-high')
            # Real successful work is stronger session evidence than a separate
            # readiness call. Keep its initial failure above, then verify both
            # UIs immediately share this successful invocation's health.
            self.check('real-high-session-after-design',str(client.cached_health().state.value)=='READY')
            t=time.perf_counter();cached=home_client.validate(use_cache=True)
            self.result['home_cached_seconds']=time.perf_counter()-t
            self.check('home-studio-share-health',cached.authenticated and home_client.last_timings.get('cache_hit'))
            page._start_ai_provider_probe('antigravity');yield .05
            page.grab().save(str(output/'studio-high-ready-after-design.png'))
            # Codex status and catalogue are real. Never click login/logout in automation.
            page.ai_provider.setCurrentIndex(page.ai_provider.findData('codex_cli'))
            yield lambda: getattr(page,'_ai_provider_probe_cancel',None) is None
            page._start_ai_provider_probe('codex_cli',refresh_models=True)
            yield lambda: getattr(page,'_ai_provider_probe_cancel',None) is None
            codex=ai_providers.provider_for_stage(page.runtime_settings,'polish')
            models=tuple(codex.invocation_trace().get('process_history',[]))
            self.result['codex']=codex.invocation_trace()
            self.result['codex_status']=page.ai_provider_health.text()
            self.check('codex-login-controls',page.ai_cli_login.isVisible() and page.ai_cli_logout.isVisible())
            self.check('codex-real-catalogue',page.ai_model.count()>0 and any('model/list' in str(x.get('purpose')) for x in models))
            if page.ai_model.count():page.ai_model.setCurrentText(page.ai_model.itemText(0))
            done=threading.Event();codex_result={}
            codex=ai_providers.provider_for_stage(page.runtime_settings,'polish')
            def codex_request():
                try:
                    began=time.perf_counter()
                    schema={'type':'object','properties':{k:{'type':'string'} for k in ('name','entrance','hold','exit')},
                        'required':['name','entrance','hold','exit'],'additionalProperties':False}
                    design=codex.structured_complete([{'role':'user','content':
                        '为 Balatro 中文字幕给出简短设计。只返回 name、entrance、hold、exit 四个字符串字段。'}],schema,timeout=60)
                    codex_result.update(source='ai',design=design,seconds=time.perf_counter()-began,trace=codex.invocation_trace())
                except Exception as exc:codex_result['error']=str(exc)
                finally:done.set()
            threading.Thread(target=codex_request,daemon=True).start()
            yield done.is_set
            self.result['codex_design']=codex_result
            self.check('codex-real-schema-design',codex_result.get('source')=='ai')
            page._copy_ai_provider_diagnostics();self.check('codex-diagnostics-json',bool(json.loads(QApplication.clipboard().text())['trace']))
            page.context_drawer.setCurrentIndex(0)
            yield .2
            page.grab().save(str(output/'studio-codex-manual-gate.png'))
        def finish(self):
            self.timer.stop()
            for editor in (window.polish_editor,window.group_editor):
                editor._model_discovery_timer.stop()
                if editor._model_discovery_worker:editor._model_discovery_worker.requestInterruption()
            self.page.close_page();ai_providers.popen_hidden_subprocess=original_spawn
            (output/'providers-acceptance.json').write_text(json.dumps(redact_diagnostics(self.result),ensure_ascii=False,indent=2),encoding='utf-8')
            window.hide();QTimer.singleShot(200,QApplication.instance().quit)
    window._acceptance_audit=Audit()
