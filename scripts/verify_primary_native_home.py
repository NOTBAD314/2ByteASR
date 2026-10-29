"""Use fresh real MOSS receipts in the normal source or frozen GUI."""
import argparse,copy,json,os,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('fresh tmp output required')
    out.mkdir();os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    # Read existing verified model assets through an audit-owned junction.
    # No download/removal operations run, and mutable state stays isolated.
    empty=out/'models'
    if any(empty.iterdir()):raise ValueError('audit models folder must be empty')
    empty.rmdir()
    subprocess.run(['powershell.exe','-NoProfile','-Command',
        "New-Item -ItemType Junction -Path '"+str(empty).replace("'","''")+
        "' -Target '"+str(ROOT/'models').replace("'","''")+"' | Out-Null"],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    os.environ['2BYTEASR_MODEL_ROOT']=str(ROOT/'models')
    from twobyteasr.projects.studio_project import project_from_runtime_cues,load_project,save_project
    from types import SimpleNamespace
    from twobyteasr.projects.speaker_organization import organize
    real=ROOT/'tmp/studio-workflow-20261004/moss-real-r1'
    infer=json.loads((real/'inference-receipt.json').read_text('utf8'))
    chain=json.loads((real/'pipeline-receipt.json').read_text('utf8'))
    if not chain['passed']:raise ValueError('fresh real MOSS chain must have passed')
    plan={}
    for sample in infer['samples']:
        name=sample['name'];media=out/(name+'.mp4')
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-nostdin','-v','error','-ss',str(sample['source_range'][0]),'-t','16','-i',sample['source'],'-vf','scale=640:360','-c:v','libx264','-preset','ultrafast','-c:a','aac','-y',str(media)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        original=load_project(real/(name+'.2byteproj'))
        cues=[SimpleNamespace(cue_id=c.id,start=c.start_ms/1000,end=c.end_ms/1000,text=c.text,speaker=c.speaker_id) for c in original.cues]
        project=project_from_runtime_cues(media,cues,generation_metadata=copy.deepcopy(original.generation_metadata))
        path=out/(name+'.2byteproj');save_project(project,path);plan[name]=str(path);plan[name+'_labels']=sorted({c.speaker_id for c in project.cues})
    old=load_project(plan['dialogue']);labels=[s.id for s in old.speakers]
    old=organize(old,[labels[1]],'merge',target=labels[0]);old.speakers[0].name='人工合轨名';old.cues[0].text='人工修改必须保持 22'
    save_project(old,out/'edited.2byteproj');plan.update(old_edited=str(out/'edited.2byteproj'),old_edited_cues=[(c.id,c.text,c.speaker_id) for c in old.cues])
    (out/'native-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,save_runtime_settings
    settings=copy.deepcopy(DEFAULT_SETTINGS);settings['models'].update(primary_asr_backend='moss',qwen_asr_backend='local',firered_asr_backend='local',speaker_source='single');settings['switches'].update(enable_ai_polish=False,use_ai_grouping=False)
    save_runtime_settings(settings,out/'config')
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore
    store=ProjectProfileStore();profile=store.create('Qwen api',recognition_plan='api',primary_asr='api',asr_config={k:settings['models'][k] for k in ('primary_asr_backend','qwen_asr_backend','firered_asr_backend')})
    store.set_last_selected(profile.id)
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='primary-native-home',TWOBYTEASR_STARTUP_PROJECT=plan['dialogue'],TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),QT_QPA_PLATFORM='windows',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(cmd,cwd=ROOT,env=env,output=out,timeout=450,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {'passed':False,'error':'no GUI receipt'}
    result['process_exit']=code;result['passed']=bool(result['passed'] and result.get('gui_shutdown') and code==0)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result.get('checks',[])),'error':result.get('error'),'code':code},ensure_ascii=False))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
