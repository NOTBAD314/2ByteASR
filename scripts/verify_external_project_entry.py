"""Exercise normal desktop argv/IPC with isolated projects and native screenshots."""
from __future__ import annotations
import argparse
import json
import hashlib
import os
from pathlib import Path
import sys
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=['project','library','home'],default='project')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--bridge',choices=['direct','startup','shell'],default='direct')
    parser.add_argument('--entity-confirmation',action='store_true')
    parser.add_argument('--project-source',type=Path,help='Read-only project copied into the owned audit directory')
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh output inside repository tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
    from twobyteasr.app.application_settings import save_hub_preferences
    project=output/'中文 (选中两条)&校对.2byteproj'
    other=output/'另一个 & (缺素材).2byteproj'
    cues=([StudioCue('entity-a',0,1000,'So还在往里走',speaker_id='S00'),
           StudioCue('entity-b',1000,2000,'So的反应',speaker_id='S00'),
           StudioCue('entity-c',2000,3000,'Somebody So2 So_player xSo',speaker_id='S00')]
          if args.entity_confirmation else
          [StudioCue(id='entry-1',start_ms=0,end_ms=1000,text='S0pp与BerLIN',speaker_id='S00')])
    media=StudioMedia(path=str(output/'entity-fixture.mp4'),display_name='确认机制验收',fingerprint='synthetic-entity-media') if args.entity_confirmation else StudioMedia(path='',display_name='入口验收')
    source_sha = None
    if args.project_source:
        source = args.project_source.resolve()
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copy2(source,project)
    else:
        save_project(SubtitleProject(media=media,
            cues=cues,
            studio_state={'project_name':'中文 & (入口工程)'}),project)
    save_project(SubtitleProject(media=StudioMedia(path=str(output/'missing-media.mp4'),display_name='素材离线'),
        cues=[StudioCue(id='missing-1',start_ms=0,end_ms=1000,text='缺少素材仍保留字幕',speaker_id='S00')]),other)
    broken=output/'损坏工程.2byteproj';broken.write_text('{broken','utf8')
    future=output/'新版工程.2byteproj'
    payload=json.loads(project.read_text('utf8'));payload['schema_version']=999
    future.write_text(json.dumps(payload,ensure_ascii=False),'utf8')
    save_hub_preferences(str(output/'projects'),True,60,9,True,True,
                         startup_page='project_library' if args.case=='library' else 'recognition')
    from twobyteasr.projects.studio_project import studio_settings_path
    (output/'studio-settings.json').write_bytes(studio_settings_path().read_bytes())
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    plan=dict(case=args.case,project=str(project),other_project=str(other),broken_project=str(broken),
              future_project=str(future),command=command,invoker_cwd=str(ROOT),bridge=args.bridge,
              protected_project_source=str(args.project_source.resolve()) if args.project_source else None,
              protected_project_sha256=source_sha)
    (output/'entry-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO=('project-entity-confirmation' if args.entity_confirmation else 'external-project-entry'),
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    bridge=[sys.executable,'-B',str(ROOT/'scripts/external_entry_launch_bridge.py'),str(output)]
    code=run_on_desktop(bridge,cwd=ROOT,env=env,
                        output=output/'process',timeout=180)
    receipt=output/'entry-result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed':False,'error':'Missing GUI receipt'}
    result['process_exit']=code
    bridge_result=json.loads((output/'bridge-result.json').read_text('utf8')) if (output/'bridge-result.json').is_file() else {}
    result['bridge']=bridge_result
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and bridge_result.get('passed'))
    if args.project_source:
        result['protected_source_unchanged'] = hashlib.sha256(args.project_source.read_bytes()).hexdigest()==source_sha
        result['passed'] = bool(result['passed'] and result['protected_source_unchanged'])
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
