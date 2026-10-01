"""Normal-entry, offline, silent <=8s dense cue performance fixture."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--tracks', type=int, choices=(1, 2), default=1)
    parser.add_argument('--panels', choices=('both', 'list', 'tools', 'none'), default='both')
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--metadata-project', type=Path)
    parser.add_argument('--legacy-follow', action='store_true', help='Replay original 1f1410c playback module, all other code current')
    parser.add_argument('--theme', type=Path)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--count', type=int, default=32)
    parser.add_argument('--audit', choices=('boundary','boundary-light','seek-pointer'), default='boundary')
    args = parser.parse_args()
    if not 32 <= args.count <= 120: raise ValueError('count must be 32..120 within the 30s fixture')
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp'):
        raise ValueError('output must be inside repository tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime',
        TWOBYTEASR_CAPTION_AUDIT_MODE=args.audit, TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'), TWOBYTEASR_BOUNDARY_PANELS=args.panels,
        TWOBYTEASR_BOUNDARY_BASELINE=str(int(args.baseline)))
    os.environ['TWOBYTEASR_BOUNDARY_CAPTURE']=str(int(args.capture))
    os.environ['TWOBYTEASR_BOUNDARY_COUNT']=str(args.count)
    if args.audit!='boundary':os.environ['TWOBYTEASR_PLAYBACK_PROBE']='1'
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    media = root/'tmp/visible-playback-v2/media/subtitle-safe/V1-30s.mp4'
    cues = [StudioCue(f'S{track+1}-{i:02d}', 250+i*225, 475+i*225,
                     f'第{i+1}条短字幕', f'S0{track+1}') for track in range(args.tracks) for i in range(args.count)]
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=30000, width=1920, height=1080),
        speakers=[StudioSpeaker(f'S0{i+1}') for i in range(args.tracks)], cues=cues)
    if args.metadata_project:
        # Read an existing verification copy; no source paths/media are played.
        payload = json.loads(args.metadata_project.read_text('utf8'))
        project.generation_metadata = payload.get('generation_metadata', {})
        (out/'metadata-provenance.json').write_text(json.dumps({'source': str(args.metadata_project.resolve()),
            'generation_metadata_bytes': len(json.dumps(project.generation_metadata).encode())}), encoding='utf8')
    if args.theme:
        theme = json.loads(args.theme.read_text('utf8'))
        project.style_recipes['web-benchmark']={'name':theme['name'],'engine':'remotion','webTheme':theme}
        for cue in project.cues: cue.style_id='web-benchmark'
    project.validate()
    hydrate_media_contract(project, probe_media_identity(str(media)))
    save_project(project, out/'fixture.2byteproj')
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    if args.legacy_follow:
        if args.exe: raise ValueError('legacy replay is a source diagnostic only')
        source = run_hidden_subprocess(['git', 'show', '1f1410c:twobyteasr/studio_playback_flow.py'],
            capture_output=True, text=True, encoding='utf8', check=True, purpose='read original playback source').stdout
        old = out/'original_playback.py'; old.write_text(source, encoding='utf8')
        runner = out/'replay_original.py'
        runner.write_text('import sys, importlib.util, runpy\n'+
            f'sys.path.insert(0, {str(root)!r})\n'+
            f'spec=importlib.util.spec_from_file_location("twobyteasr.studio_playback_flow", {str(old)!r})\n'+
            'module=importlib.util.module_from_spec(spec)\nsys.modules[spec.name]=module\nspec.loader.exec_module(module)\n'+
            f'runpy.run_path({str(root/"quick_start.py")!r}, run_name="__main__")\n', encoding='utf8')
        os.environ['TWOBYTEASR_BOUNDARY_LEGACY_REPLAY']='1'
        command=[sys.executable, str(runner)]
    with (out/'process.log').open('w', encoding='utf8') as log:
        completed = run_hidden_subprocess(command, cwd=str(root), env=os.environ.copy(), stdout=log,
            stderr=subprocess.STDOUT, timeout=110, purpose='silent eight-second cue-boundary audit')
    result = json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({k: result.get(k) for k in ('passed','error','summary','checks')}, ensure_ascii=False))
    return completed.returncode or (0 if result.get('passed') or args.baseline else 1)


if __name__ == '__main__':
    raise SystemExit(main())
