"""Launch normal Studio with one isolated three-second caption; silent."""
from pathlib import Path
import argparse,json,os,sys,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path);p.add_argument('--themes',type=Path,default=ROOT/'examples/web-themes/balatro-20260911');p.add_argument('--import-flow',action='store_true');a=p.parse_args()
    out=a.output.resolve();assert out.is_relative_to(ROOT/'tmp');out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime',TWOBYTEASR_CAPTION_AUDIT_MODE='balatro',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_BALATRO_THEMES=str(a.themes.resolve()),TWOBYTEASR_BALATRO_IMPORT_FLOW='1' if a.import_flow else '0')
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    from twobyteasr.processes import run_hidden_subprocess
    media=ROOT/'tmp/visible-playback-v2/media/subtitle-safe/V1-30s.mp4'
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=30000,width=1920,height=1080),cues=[StudioCue('balatro',0,3000,'啊感觉他就是你看')])
    hydrate_media_contract(project,probe_media_identity(str(media)));save_project(project,out/'fixture.2byteproj')
    command=[a.exe.resolve()] if a.exe else [sys.executable,ROOT/'quick_start.py']
    with (out/'process.log').open('w',encoding='utf8') as log:
        r=run_hidden_subprocess(command,cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,timeout=180,purpose='three silent three-second actual Studio theme checks')
    result=json.loads((out/'result.json').read_text('utf8'));print(json.dumps(dict(passed=result['passed'],error=result.get('error'),candidates=[{k:c.get(k) for k in ('id','passed','playback_seconds','web_worker_alive','frames_published')} for c in result['candidates']]),ensure_ascii=True))
    return r.returncode or int(not result['passed'])
if __name__=='__main__':raise SystemExit(main())
