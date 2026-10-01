"""Opt-in normal-entry checks. Local protocol fixtures are labelled as such."""
import copy,json,os,sys,time,traceback,threading
from dataclasses import asdict
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QComboBox,QLabel
    from .build_identity import load_build_identity
    from .studio_acceptance_audit import require
    result=dict(build=vars(load_build_identity()),executable=sys.executable,checks=[],paid_requests=0,
        environment='separate Windows desktop; no desktop switch; actual Qt controls')
    def save():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)));save();require(value,name)
    def run():
        try:
            window._open_model_workshop();page=window.workshop_page
            def tab(role):
                button=next(b for b in page.tab_group.buttons() if b.property('role')==role)
                QTest.mouseClick(button,Qt.LeftButton);QApplication.processEvents()
            tab('speaker')
            check('Nemotron appears only in speaker tab',not page._cards['nemotron'].isHidden() and page._cards['moss'].isHidden())
            window.grab().save(str(out/'workshop-speaker.png'))
            tab('api')
            check('three native API cards visible',all(not page._cards[k].isHidden() for k in ('spark_asr_v2','qwen31_flash','qwen31_filetrans')))
            window.grab().save(str(out/'workshop-api.png'))
            for preset in ('spark_asr_v2','qwen31_flash','qwen31_filetrans'):
                from .ui import ASR_API_PRESETS
                window.qwen_asr_api_provider.setCurrentIndex(window.qwen_asr_api_provider.findData(preset))
                window._apply_asr_preset_fields(preset)
                errors=[]
                def inspect_dialog(preset=preset):
                    dlg=next((d for d in QApplication.topLevelWidgets() if isinstance(d,QDialog) and d.isVisible() and d.windowTitle()=='配置在线 ASR API'),None)
                    try:
                        require(dlg is not None,'credential dialog visible')
                        check(preset+' exact model',dlg.findChild(QLineEdit,'asrCredentialModel').text()==ASR_API_PRESETS[preset]['model'])
                        check(preset+' exact URL',dlg.findChild(QLineEdit,'asrCredentialUrl').text()==ASR_API_PRESETS[preset]['url'])
                        if preset=='spark_asr_v2':
                            check('Spark three credential fields',all(dlg.findChild(QLineEdit,n).isVisible() for n in ('sparkAppId','sparkApiSecret','asrCredentialKey')))
                            require(dlg.findChild(QLineEdit,'sparkApiSecret').echoMode()==QLineEdit.Password,'secret masked')
                        dlg.grab().save(str(out/(preset+'-configuration.png')))
                    except Exception as exc:errors.append(str(exc))
                    finally:
                        if dlg:dlg.reject()
                QTimer.singleShot(350,inspect_dialog)
                window._open_api_key_dialog()
                require(not errors,'; '.join(errors))
            # Empty error is shown by the real review widget, not a screenshot
            # mock. No adopted terms are written by this check.
            from .glossary_skill_ui import GlossaryUpdateReviewDialog
            failed=dict(diffs=[],candidate_count=0,mode='full',outcome=dict(status='blocked',message='来源访问受阻；有效核对 0，覆盖率未知'))
            dlg=GlossaryUpdateReviewDialog(window,'我的世界',failed);dlg.setWindowFlag(Qt.Window,True);dlg.resize(1100,720);dlg.show()
            QApplication.processEvents()
            check('zero verified never claims coverage',any('有效核对 0' in l.text() for l in dlg.findChildren(QLabel)))
            dlg.grab().save(str(out/'glossary-blocked.png'));dlg.close()
            # Actual owned worker + HTTP parser + offsets, backed by an explicit
            # local fixture server. This is not a paid provider validation.
            from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
            posts=[]
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));posts.append(body)
                    payload=dict(output=dict(text='你好。',sentence=dict(sentence_id=1,channel_id=0,sentence_end=True,
                        begin_time=0,end_time=900,text='你好。',words=[dict(text='你好',punctuation='。',begin_time=0,end_time=900,fixed=True,speaker_id=2)])))
                    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(json.dumps(payload,ensure_ascii=False).encode())
                def log_message(self,*a):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
            results=[];errors=[]
            def owned():
                try:
                    import numpy as np
                    from .asr_api_process import transcribe
                    from .runtime import RuntimeContext,activate_runtime_context
                    context=RuntimeContext(speaker_source='native',asr_endpoint_snapshot=dict(provider='qwen31_flash',model='qwen-audio-3.1-asr-flash',
                        protocol='dashscope_asr_flash',url=f'http://127.0.0.1:{server.server_port}/api/v1/services/audio/asr/transcription',api_key='local-fixture'))
                    with activate_runtime_context(context):
                        results.extend(transcribe(str(out/'fixture.mp4'),[dict(start=0,end=1,audio=(np.zeros(16000,dtype=np.float32),16000))],publish_primary=True))
                except Exception:errors.append(traceback.format_exc())
            worker=threading.Thread(target=owned,daemon=True);worker.start();deadline=time.monotonic()+120
            while worker.is_alive() and time.monotonic()<deadline:QTest.qWait(50)
            server.shutdown();require(not worker.is_alive(),'owned worker terminates');require(not errors,'\n'.join(errors))
            check('owned process dispatches exactly one native Flash HTTP request',len(posts)==1 and posts[0]['model']=='qwen-audio-3.1-asr-flash')
            check('owned process preserves speaker and seconds',bool(results) and results[0]['speaker']=='API_S02' and results[0]['end']==.9)
            result['local_http_contract']=dict(request_count=len(posts),results=results,actual_provider=False)
            if os.environ.get('TWOBYTEASR_PUBLIC_CATALOG')=='1':
                from .glossary_task_manager import GlossaryUpdateManager
                from .llm_config import activate_ai_service
                from .settings import DEFAULT_SETTINGS
                settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'antigravity')
                settings['models'].update(glossary_enrich_names=False,glossary_include_community=False,glossary_include_wordlists=False,glossary_task_budget_seconds=120)
                manager=GlossaryUpdateManager(window.legacy,window)
                task_id,created=manager.submit('我的世界','full',settings,service_label='公开目录；禁止模型调用',model_label='无模型请求')
                deadline=time.monotonic()+160
                while manager.get(task_id).status in {'running','queued'} and time.monotonic()<deadline:QTest.qWait(100)
                task=manager.get(task_id);require(task.result is not None,'catalog task has retained result')
                data=dict(task.result);data['diffs']=[asdict(d) for d in data['diffs']]
                (out/'minecraft-result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
                result['public_catalog']=dict(task_id=task_id,status=task.status,candidates=data['candidate_count'],outcome=data.get('outcome'),seconds=data['elapsed_seconds'])
                check('real public source yields verified candidates',data['candidate_count']>0 and data['outcome']['verified_sources']>0)
                dlg=GlossaryUpdateReviewDialog(window,'我的世界',task.result);dlg.setWindowFlag(Qt.Window,True);dlg.resize(1280,850);dlg.show();QTest.qWait(300)
                dlg.grab().save(str(out/'minecraft-candidates.png'));dlg.close();manager.shutdown()
            result['completed']=True
        except Exception:result['error']=traceback.format_exc();result['completed']=False
        finally:
            save()
            # Exercise the real close path, which drains Studio/workshop workers.
            # Exiting QApplication directly skips native resource teardown.
            window.studio_page.undo_stack.setClean();window.close()
    QTimer.singleShot(3500,run)
