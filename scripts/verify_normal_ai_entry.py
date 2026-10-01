"""Real Studio design-button audit with an explicit, hash-bound visual review.

The first process waits for review.json after writing review-needed.json. No
provider result or visual score is fabricated. A second, fresh process checks
the project and library saved by the ordinary UI buttons.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--isolated-desktop',action='store_true')
    parser.add_argument('--text-only',action='store_true',help='Do not capture or attach reference media in this audit')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--service', choices=('deepseek', 'antigravity', 'grok_account', 'gemini','custom','openai','bailian','codex_cli'))
    parser.add_argument('--call-budget',type=Path)
    parser.add_argument('--game-scene',action='store_true',help='Use the fictional game corridor instead of a test pattern')
    parser.add_argument('--game-frame',type=Path,help='Read-only actual game frame for a six-second composition audit')
    parser.add_argument('--cue-seconds',type=float,choices=(1.5,3,6),default=3)
    parser.add_argument('--model')
    parser.add_argument('--redo-candidate')
    parser.add_argument('--redo-feedback')
    parser.add_argument('--resume-ledger',type=Path,help='Use the ordinary saved-draft file chooser; no new three-candidate generation')
    parser.add_argument('--retry-saved-candidate',help='Restore the saved cards then click only this candidate retry button')
    parser.add_argument('--recover-candidate',default='')
    parser.add_argument('--rebuild-preview',action='store_true')
    parser.add_argument('--expected-candidates',type=int,choices=(1,3),default=3)
    parser.add_argument('--import-theme',type=Path,help='Import an existing archive through the ordinary file chooser; no model calls')
    parser.add_argument('--workbench-ledger',type=Path,help='Also select the matching saved candidate through its real workbench before applying; requires --import-theme')
    parser.add_argument('--cue-text',default='这次终于找到出口了')
    parser.add_argument('--replacement-text',default='',help='Opt-in actual subtitle editor / undo / redo and persistence audit')
    parser.add_argument('--verify-restore',action='store_true',help='Opt-in ordinary restore-to-plain button, then undo back to the exact theme')
    parser.add_argument('--wait-web-proxy',action='store_true',help='Verify adopted transparent proxy is complete before playback')
    parser.add_argument('--verify-usability',action='store_true',help='Audit automatic adoption, status and real corner scale/move gestures')
    parser.add_argument('--timeout', type=int, default=2400)
    parser.add_argument('--prepare-only',action='store_true',help='Build inspectable synthetic inputs without starting the app or a provider')
    parser.add_argument('--local-fixture',action='store_true',help='Loopback-only fixture credentials in the isolated audit store; never read the user credential store')
    parser.add_argument('--generation-timeout',type=int,help='Override the provider wait only in this isolated audit configuration (1..3600 s)')
    parser.add_argument('--prompt', default='设计三款清晰的游戏对白字幕：奶白厚字配深色轮廓，分别用折纸、细金属切面、柔和珐琅表现不同材质。主体只围绕字幕，背景透明，不做全屏板。完整保留句子，单行清楚可读；有限入场和退场，持住阶段安静。每个候选以及主题都必须有独立稳定 id 和简洁非空 name。')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to((root/'tmp').resolve()):
        raise ValueError('Audit output must be under repository tmp')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new empty audit directory; existing evidence is retained')
    out.mkdir(parents=True, exist_ok=True)
    original_local_appdata=Path(os.environ['LOCALAPPDATA'])
    # Install the inherited boundary before importing any application/Qt code.
    # Explicit QSettings constructors and spawned processes must be isolated too.
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr import settings as settings_module
    from twobyteasr.llm_config import activate_ai_service, update_active_profile, get_active_service, active_service_values
    source = (args.settings or original_local_appdata/'2ByteASR'/settings_module.SETTINGS_FILENAME).resolve()
    original = source.read_bytes()
    settings, _ = settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS, json.loads(original))
    settings = copy.deepcopy(settings)
    if args.service:activate_ai_service(settings, args.service)
    if args.model:update_active_profile(settings, model=args.model)
    args.service=get_active_service(settings)
    args.model=active_service_values(settings)['model']
    if args.generation_timeout is not None:
        if not 1<=args.generation_timeout<=3600:parser.error('--generation-timeout must be 1..3600 seconds')
        settings['models']['ai_design_cli_timeout_seconds']=args.generation_timeout
        settings['models']['ai_design_wait_mode']='configured'
    if args.service in ('grok_account','antigravity'):
        # This audit uses the CLI's existing account. No API credential (even
        # a legacy flat setting) belongs in its isolated configuration copy.
        def clear_api_credentials(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if any(token in key.lower() for token in ('api_key','access_token','refresh_token')):value[key]=''
                    else:clear_api_credentials(item)
            elif isinstance(value,list):
                for item in value:clear_api_credentials(item)
        clear_api_credentials(settings)
    config = out/'config'
    config.mkdir(exist_ok=True)
    settings_module.save_runtime_settings(settings, config)
    # Read through the application credential interface in the isolated child;
    # never export/copy even the encrypted credential store.
    secret_source = original_local_appdata/'2ByteASR'/'secrets.dat'

    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), TEMP=str(out/'temp'), TMP=str(out/'temp'),
        PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
        QT_QPA_PLATFORM='windows', TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='normal-ai',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    if not args.import_theme and not args.local_fixture and args.service not in ('grok_account','antigravity','codex_cli') and secret_source.is_file():
        env['TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE']=str(secret_source)
    if args.call_budget:env['TWOBYTEASR_AI_CALL_BUDGET']=str(args.call_budget.resolve())
    workbench_ledger=''
    if args.workbench_ledger:
        if not args.import_theme:parser.error('--workbench-ledger requires --import-theme')
        prior=json.loads(args.workbench_ledger.read_text('utf8'))
        local=out/'workbench-input';local.mkdir()
        mappings={}
        for concept in prior['partial_concepts']:
            origin=Path(concept['ledger_path']).resolve().parent.parent
            target=local/concept['id'];shutil.copytree(origin,target)
            mappings[str(origin)]=str(target)
        def move_paths(value):
            if isinstance(value,dict):return {k:move_paths(v) for k,v in value.items()}
            if isinstance(value,list):return [move_paths(v) for v in value]
            if isinstance(value,str):
                for old,new in mappings.items():
                    if value.startswith(old):return new+value[len(old):]
            return value
        for record in local.rglob('ledger.json'):
            record.write_text(json.dumps(move_paths(json.loads(record.read_text('utf8'))),ensure_ascii=False,indent=2),'utf8')
        seed=local/'ledger.json';seed.write_text(json.dumps(move_paths(prior),ensure_ascii=False,indent=2),'utf8')
        workbench_ledger=str(seed)
    if args.text_only:env['TWOBYTEASR_AI_TEXT_ONLY']='1'
    for name in ('local', 'roaming', 'temp'):
        (out/name).mkdir(exist_ok=True)
    if args.retry_saved_candidate:
        if not args.resume_ledger:parser.error('--retry-saved-candidate requires --resume-ledger')
        source_root=args.resume_ledger.resolve().parent
        seed=out/'local/2ByteASR/SubtitleStudioPreview/logs/theme-drafts/saved-input/creative'
        shutil.copytree(source_root,seed)
        prior=json.loads((seed/'ledger.json').read_text('utf8'))
        roots={str(source_root)}
        for row in prior.get('partial_concepts',[]):
            if row.get('ledger_path'):roots.add(str(Path(row['ledger_path']).parents[3]))
        def relocate(value):
            if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
            if isinstance(value,list):return [relocate(v) for v in value]
            if isinstance(value,str):
                for prefix in roots:
                    if value.lower().startswith(prefix.lower()):return str(seed)+value[len(prefix):]
            return value
        # Only relocate ledgers. Provider response JSON is immutable hashed
        # evidence, and reformatting it makes the actual recovery reject it.
        for record in seed.rglob('ledger.json'):
            try:data=json.loads(record.read_text('utf8'))
            except ValueError:continue
            record.write_text(json.dumps(relocate(data),ensure_ascii=False,indent=2),'utf8')
    os.environ.update({key: env[key] for key in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP')})
    if args.local_fixture:
        from urllib.parse import urlsplit
        from twobyteasr.llm_config import save_api_key_for
        address=active_service_values(settings)['base_url']
        if urlsplit(address).hostname not in {'127.0.0.1','::1','localhost'}:
            raise ValueError('Local fixture must use a loopback endpoint')
        save_api_key_for('custom',address,'local-fixture-only')
    from twobyteasr.processes import run_hidden_subprocess
    media = out/'synthetic.mp4'
    media_input=['-f','lavfi','-i','testsrc2=size=1280x720:rate=30']
    if args.game_scene:
        from scripts.synthetic_game_scene import create
        create(out/'synthetic-game.png')
        media_input=['-loop','1','-framerate','30','-i',out/'synthetic-game.png']
    if args.game_frame:
        from PIL import Image
        Image.open(args.game_frame).convert('RGB').resize((1920,1080)).save(out/'game-frame.png')
        media_input=['-loop','1','-framerate','30','-i',out/'game-frame.png']
    run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe', '-v', 'error', '-y', *media_input,
        '-t', str(args.cue_seconds+3), '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', media],
        check=True, timeout=45, capture_output=True, purpose='synthetic media for normal AI design UI audit')
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=6000, width=1920 if args.game_scene else 1280, height=1080 if args.game_scene else 720),
        speakers=[StudioSpeaker('AUDIT', name='测试说话人')],
        cues=[StudioCue('audit-ai', 250, 250+args.cue_seconds*1000, args.cue_text, 'AUDIT'),
              StudioCue('audit-next', 400+args.cue_seconds*1000, 2900+args.cue_seconds*1000, '接下来继续向前走', 'AUDIT')])
    hydrate_media_contract(project, probe_media_identity(str(media)))
    save_project(project, out/'fixture.2byteproj')
    (out/'run-config.json').write_text(json.dumps(dict(service=args.service, model=args.model, prompt=args.prompt,
        resume_ledger=str(args.resume_ledger.resolve()) if args.resume_ledger else '',synthetic_game=args.game_scene,
        retry_saved_candidate=args.retry_saved_candidate,recover_candidate=args.recover_candidate,rebuild_preview=args.rebuild_preview,
        expected_candidates=args.expected_candidates,
        import_theme=str(args.import_theme.resolve()) if args.import_theme else '',workbench_ledger=workbench_ledger,cue_text=args.cue_text,
        replacement_text=args.replacement_text,verify_restore=args.verify_restore,wait_web_proxy=args.wait_web_proxy,verify_usability=args.verify_usability,
        generation_timeout_override=args.generation_timeout,redo_candidate=args.redo_candidate,redo_feedback=args.redo_feedback,
        cue_seconds=args.cue_seconds,game_frame=str(args.game_frame or ''),
        review_timeout_seconds=max(60, args.timeout-180), source_settings_sha256=hashlib.sha256(original).hexdigest()),
        ensure_ascii=False, indent=2), encoding='utf8')
    if args.prepare_only:
        image=out/'synthetic-input-1500ms.png'
        run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-ss','1.5','-i',media,'-frames:v','1',image],
            check=True,timeout=15,capture_output=True,purpose='inspectable synthetic AI input; no provider call')
        (out/'provider-input-scope.json').write_text(json.dumps(dict(service=args.service,model=args.model,
            prompt=args.prompt,subtitles=[cue.text for cue in project.cues],image=str(image),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
            image_source='ffmpeg testsrc2 synthetic video',provider_calls=0,credentials_copied=False),ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(dict(prepared=True,provider_calls=0,output=str(out))))
        return 0
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    combined = dict(passed=False, source_settings_unchanged=False, processes=[])
    started = time.monotonic()
    try:
        for phase in ('generate', 'reopen'):
            env['TWOBYTEASR_NORMAL_AI_PHASE'] = phase
            if args.isolated_desktop:
                from isolated_windows_desktop import run_on_desktop
                from types import SimpleNamespace
                child=SimpleNamespace(returncode=run_on_desktop(command,cwd=root,env=env,output=out/(phase+'-process'),
                    timeout=args.timeout if phase=='generate' else 300))
            else:
                with (out/(phase+'-process.log')).open('w', encoding='utf8') as log:
                    child = run_hidden_subprocess(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                        timeout=args.timeout if phase=='generate' else 300, purpose='normal AI UI '+phase+' audit')
            row = dict(phase=phase, exit_code=child.returncode)
            path = out/(phase+'-result.json')
            # The daily root launcher exits after starting its frozen child.
            # Wait for that child's audit and orderly media shutdown, not the
            # launcher exit or an intermediate result written during progress.
            deadline=time.monotonic()+(args.timeout if phase=='generate' else 300)
            while child.returncode==0 and time.monotonic()<deadline:
                closed = (out/(phase+'-closed.txt')).is_file()
                try:
                    final=json.loads(path.read_text('utf8'))
                    if closed:
                        if not final.get('completed'):
                            row['error']='Application closed before the audit completed; intermediate results are not acceptance.'
                        break
                except (OSError,ValueError):pass
                if closed:
                    row['error']='Application closed without a readable completed audit result.'
                    break
                time.sleep(.5)
            if path.is_file(): row['result'] = json.loads(path.read_text('utf8'))
            combined['processes'].append(row)
            if child.returncode or row.get('error') or not row.get('result', {}).get('passed'):
                break
        combined['passed'] = len(combined['processes'])==2 and all(
            row['exit_code']==0 and not row.get('error') and row['result'].get('completed')
            and row['result'].get('passed') for row in combined['processes'])
    finally:
        combined['source_settings_unchanged'] = source.read_bytes()==original
        combined['elapsed_seconds'] = round(time.monotonic()-started, 3)
        combined['passed'] = combined['passed'] and combined['source_settings_unchanged']
        (out/'result.json').write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(passed=combined['passed'], phases=[r['phase'] for r in combined['processes']],
        output=str(out)), ensure_ascii=False))
    return 0 if combined['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
