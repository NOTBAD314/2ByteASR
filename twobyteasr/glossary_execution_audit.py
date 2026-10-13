"""Opt-in frozen provenance verification; writes only the guarded audit root."""
import copy
from dataclasses import asdict
import json
import threading
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QObject, Signal, QTimer
    from .build_identity import load_build_identity
    from .studio_acceptance_audit import require
    from . import glossary_build as gb
    from .settings import DEFAULT_SETTINGS
    from .llm_config import activate_ai_service, update_active_profile
    from .minecraft_catalogs import official_catalog
    import subtitle_core as legacy
    config=json.loads((out/'audit-config.json').read_text('utf8'))
    from pathlib import Path
    from .studio_acceptance_audit import audit_tmp_root
    budget_path=Path(config['budget_path']).resolve()
    require(budget_path.is_relative_to(audit_tmp_root()), 'Budget must remain inside the audit workspace')
    result=dict(build=vars(load_build_identity()), cases=[], completed=False)
    class Bridge(QObject):
        done=Signal(object)
    bridge=Bridge(window)
    original=gb._structured_call
    def guarded(*args, **kwargs):
        budget=json.loads(budget_path.read_text('utf8'))
        require(config.get('allow_one_public_glossary_call') is True, 'No glossary call authorized')
        require(sum(row.get('dispatched', True) for row in budget['calls'])<budget['limit']==1, 'Glossary authorization exhausted')
        call=dict(started_at=time.time(),stage='public names and source evidence only',status='started')
        budget['calls'].append(call)
        budget_path.write_text(json.dumps(budget,ensure_ascii=False,indent=2),'utf8')
        from .studio_acceptance_audit import _audit_provider_scope
        try:
            _audit_provider_scope.public_glossary=True
            payload,diag=original(*args,**kwargs)
            call.update(status='returned',diagnostics=diag)
            (out/'model-response.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
            return payload,diag
        except Exception as exc:
            call.update(status='failed',error=str(exc))
            raise
        finally:
            _audit_provider_scope.public_glossary=False
            call['completed_at']=time.time()
            budget_path.write_text(json.dumps(budget,ensure_ascii=False,indent=2,default=str),'utf8')
    def work():
        try:
            gb._structured_call=guarded
            settings=copy.deepcopy(DEFAULT_SETTINGS)
            activate_ai_service(settings,'grok_account');update_active_profile(settings,model='grok-4.7')
            settings['models'].update(glossary_include_community=False,glossary_include_wordlists=False,
                glossary_task_budget_seconds=600,glossary_max_model_calls=1,glossary_enrich_names=True,
                glossary_enrich_batch_size=28)
            # Resume seeds obey the same versioned checkpoint contract as a
            # normal saved task. Without its version the application correctly
            # rejects the seed and discovers all default community catalogs.
            seed=dict(config_version=gb.BUILD_CONFIG_VERSION,game='我的世界',
                      catalogs=[official_catalog()],candidates=[],done_urls=[])
            for name,mode in [('cold','fast'),('warm','fast'),('refresh','refresh'),('ai','ai')]:
                if name=='ai' and not config.get('allow_one_public_glossary_call'):continue
                events=[]
                def event(row):
                    events.append(row)
                    with (out/(name+'-events.jsonl')).open('a',encoding='utf8') as stream:
                        stream.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
                settings['models'].update(glossary_execution_mode=mode,glossary_task_id='frozen-'+name)
                data=gb.run_full_library_update(legacy,'我的世界',settings,resume=seed,on_event=event)
                serial=dict(data,diffs=[asdict(d) for d in data['diffs']])
                (out/(name+'-result.json')).write_text(json.dumps(serial,ensure_ascii=False,indent=2),'utf8')
                summary=data['execution'];result['cases'].append(dict(name=name,execution=summary,outcome=data['outcome']))
                require(data['candidate_count']>0, name+' must retain actual sourced candidates')
                if name=='warm':require(summary['http_requests']==0 and summary['model_calls']==0,'Warm path must explicitly reuse without new requests')
                if name in {'cold','refresh'}:require(summary['http_success']>=4 and summary['model_calls']==0,'Fresh official JSON chain required')
                if name=='ai':require(summary['model_calls']==1 and summary['model_reviewed']>0,'One actual model assessment must complete')
                seed=data['checkpoint']
                result['last_result']=serial
            # Explicit controlled outage, separate from actual network receipts.
            from . import minecraft_catalogs
            real_fetch=minecraft_catalogs.fetch_official_terms
            try:
                def offline(*a,**k):raise ConnectionError('controlled offline branch; no network attempted')
                minecraft_catalogs.fetch_official_terms=offline
                settings['models']['glossary_execution_mode']='fast'
                failed=gb.run_full_library_update(legacy,'我的世界',settings,
                    resume=dict(config_version=gb.BUILD_CONFIG_VERSION,game='我的世界',
                                catalogs=[official_catalog()],candidates=[],done_urls=[]))
                require(failed['candidate_count']==0 and failed['outcome']['verified_sources']==0,'Outage must not claim coverage')
                result['controlled_failure']=dict(outcome=failed['outcome'],execution=failed['execution'])
            finally:minecraft_catalogs.fetch_official_terms=real_fetch
            result['completed']=True
        except Exception:result['error']=traceback.format_exc()
        finally:
            gb._structured_call=original
            bridge.done.emit(result)
    def finish(value):
        from .glossary_skill import SearchedTerm,TermDiff
        from .glossary_skill_ui import GlossaryUpdateReviewDialog
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        last=value.pop('last_result',None)
        if last:
            rows=[TermDiff(**dict(d,term=SearchedTerm(**d['term']))) for d in last['diffs']]
            dlg=GlossaryUpdateReviewDialog(window,'我的世界',dict(last,diffs=rows),apply_locked=True)
            dlg.setWindowFlag(Qt.Window,True);dlg.resize(1100,730);dlg.show();QApplication.processEvents()
            dlg.grab().save(str(out/'actual-provenance-preview.png'));dlg.close()
        (out/'result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),'utf8')
        window.result_exit_code=0 if value['completed'] else 1
        QTimer.singleShot(100,window.close)
    bridge.done.connect(finish)
    QTimer.singleShot(600,lambda:threading.Thread(target=work,daemon=True,name='glossary-frozen-provenance').start())
