"""Normal MainWindow, real model/runtime paths, private whitelisted settings/proofs."""
import argparse,json,os,sys,shutil,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path);args=p.parse_args()
    out=args.output.resolve();assert not out.exists() and out.is_relative_to(ROOT/'tmp');out.mkdir(parents=True)
    workspace=ROOT.parents[2];original=Path(os.environ['LOCALAPPDATA'])/'2ByteASR'
    raw=json.loads((original/'2byteasr_settings.json').read_text('utf8'))
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    import copy
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    for k in ['primary_asr_backend','qwen_asr_backend','firered_asr_backend','qwen_alignment_profile','qwen_alignment_head']:
        if k in raw.get('models',{}):settings['models'][k]=raw['models'][k]
    settings['subtitle_language']=raw.get('subtitle_language',settings['subtitle_language'])
    data=out/'local/2ByteASR';data.mkdir(parents=True);(out/'roaming').mkdir()
    (data/'2byteasr_settings.json').write_text(json.dumps(settings),'utf8')
    (data/'runtime_paths.json').write_text(json.dumps(dict(schema_version=1,install_root=str(ROOT),model_root=str(workspace/'models'),runtime_root=str(original/'runtimes'),config_root=str(data),cache_root=str(data/'cache'),project_root=str(data/'Projects'))),'utf8')
    ready=data/'model-readiness';ready.mkdir()
    for key in ['qwen_ultra_aligner','qwen_ultra_head','mfa_aligner']:
        f=original/'model-readiness'/f'{key}.json'
        if f.is_file():
            q=json.loads(f.read_text('utf8'));safe={k:q[k] for k in ['status','model','signature','inference_verified','model_loaded','files_verified','runtime_ready','alignment_receipt','ultra_directory','ultra_file_stats','runtime_python','category','checked_at','started','availability_identity'] if k in q};(ready/f.name).write_text(json.dumps(safe),'utf8')
    from twobyteasr.projects.studio_project import StudioMedia,StudioCue,SubtitleProject,save_project
    sample=out/'speech.wav';shutil.copy2(ROOT/'assets/diagnostics/speech_en.wav',sample)
    fixture=out/'fixture.2byteproj';proj=SubtitleProject(media=StudioMedia(path=str(sample),duration_ms=5974),cues=[StudioCue('test',100,5600,'Hello this is a local speech recognition test the weather is sunny today')]);proj.generation_metadata['language']={'code':'en','requested':'en'};data_proj=proj.to_dict();data_proj['media_pool'][0]['audio_metadata']={'has_audio':True,'channels':1,'sample_rate':16000,'stream_index':0};data_proj['media_pool'][0]['video_metadata']={'has_video':False};data_proj['render_settings']['_cue_domain']='timeline';proj=SubtitleProject.from_dict(data_proj);save_project(proj,fixture)
    env=dict(os.environ,LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='workshop-readiness',TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',TWOBYTEASR_MANAGED_RUNTIME_ONLY='1',PYTHONUTF8='1',PYTHONFAULTHANDLER='1',QT_QPA_PLATFORM='windows',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    env['2BYTEASR_MODEL_ROOT']=str(workspace/'models');env['2BYTEASR_RUNTIME_ROOT']=str(original/'runtimes')
    for k in ['TWOBYTEASR_TEST_ROOT','2BYTEASR_USER_DATA_ROOT','TWOBYTEASR_MAIN_PYTHON','TWOBYTEASR_DEVELOPER_RUNTIMES','TWOBYTEASR_AUDIT_OWNS_QWEN_PROOF']:env.pop(k,None)
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=360,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(passed=code==0 and result.get('passed'),checks=len(result.get('checks',[])),exit=code,error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1

if __name__=='__main__':raise SystemExit(main())
