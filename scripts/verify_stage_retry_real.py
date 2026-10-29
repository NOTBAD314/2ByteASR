"""One bounded real text retry on a copied project; encrypted store read-only."""
import argparse,hashlib,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--secrets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute-live',action='store_true',required=True)
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh tmp directory required')
    out.mkdir(parents=True);source=a.project.read_bytes();secret_sha=hashlib.sha256(a.secrets.read_bytes()).hexdigest()
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install,require_isolated_paths
    install();require_isolated_paths('single-stage-live-retry',emit=lambda *_:None)
    from twobyteasr.providers import llm_config
    reader=llm_config._read_secrets
    llm_config._read_secrets=lambda **_:reader(read_only_path=a.secrets)
    from twobyteasr.projects.studio_project import load_project,save_project
    from twobyteasr.recognition.processing_recovery import recover_units,failure_summary
    from twobyteasr.recognition.service import RunOptions,CancellationToken
    from twobyteasr.app.stage_retry import execute_unit
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    from types import SimpleNamespace
    import requests
    original_send=requests.Session.send;sent=[]
    def bounded_send(session,request,**kwargs):
        if len(sent)>=1:raise RuntimeError('验收请求上限1次已达到；保留未完成项')
        if not request.url.startswith('https://api.deepseek.com/'):raise RuntimeError('非原任务服务地址，拒绝请求')
        payload=json.loads(request.body)
        payload['max_tokens']=min(int(payload.get('max_tokens',2048)),2048)
        request.body=json.dumps(payload,ensure_ascii=False).encode('utf8');request.prepare_content_length(request.body)
        sent.append({'model':payload.get('model'),'max_tokens':payload['max_tokens'],'url':request.url})
        (out/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
        started=time.perf_counter();kwargs.update(stream=False,timeout=(10,60))
        response=original_send(session,request,**kwargs)
        sent[-1].update(status=response.status_code,elapsed_ms=(time.perf_counter()-started)*1000)
        (out/'raw-response.txt').write_text(response.text,'utf8')
        return response
    requests.Session.send=bounded_send
    result={'passed':False,'requests':sent,'limit':{'requests':1,'output_tokens':2048},'asr_run':False}
    app=QApplication.instance() or QApplication([])
    try:
        project=load_project(a.project);report=json.loads(a.report.read_text('utf-8-sig'))
        path=save_project(project,out/'recovery.2byteproj');units=recover_units(project,report)
        if len(units)!=1 or units[0]['stage']!='polish':raise ValueError('预期原短工程唯一文字校对失败任务')
        options=RunOptions(settings_snapshot_json=json.dumps(report['settings'],ensure_ascii=False))
        answer=execute_unit(project,report,options,units[0],CancellationToken())
        result['unit']=answer
        commit_unit_result(SimpleNamespace(session=SimpleNamespace(project=project,undo_stack=QUndoStack()),project_path=path),report,answer)
        result['summary']=failure_summary(load_project(path),report)
        result['passed']=answer['status'] in {'completed','completed_no_change','proposals_pending'} and len(sent)==1
    except Exception:
        result['error']=traceback.format_exc()
    finally:
        result['source_unchanged']=a.project.read_bytes()==source
        result['credential_store_unchanged']=hashlib.sha256(a.secrets.read_bytes()).hexdigest()==secret_sha
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
        print(json.dumps({k:result.get(k) for k in ('passed','requests','error','source_unchanged','credential_store_unchanged')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
