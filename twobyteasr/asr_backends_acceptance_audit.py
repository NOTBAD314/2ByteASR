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
            check('independent speaker tab removed',all(b.property('role')!='speaker' for b in page.tab_group.buttons()))
            check('Nemotron registry entry removed','nemotron' not in page._cards)
            tab('api')
            check('current native API cards visible',all(not page._cards[k].isHidden() for k in ('spark_asr_v2','qwen31_filetrans')))
            window.grab().save(str(out/'workshop-api.png'))
            for preset in ('spark_asr_v2','qwen31_filetrans'):
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
            # The former short-audio fixture is retired along with its entry.
            # Paid Filetrans evidence comes from the separate production run.
            from .llm_config import validate_qwen_asr_endpoint
            refused=False
            try:
                validate_qwen_asr_endpoint(dict(model='qwen-audio-3.1-asr-flash',protocol='dashscope_asr_flash'))
            except RuntimeError:refused=True
            check('removed short-audio cannot dispatch a new task',refused)
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
