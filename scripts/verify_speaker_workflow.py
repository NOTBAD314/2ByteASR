"""Launch normal quick_start / frozen app with isolated, silent short fixtures."""
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
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root / 'tmp'):
        raise ValueError('output must be under repository tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1', TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='speaker-workflow',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'v1.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, hydrate_media_contract
    from twobyteasr.studio_media_pool import add_media_asset, create_video_track, add_video_clip
    from twobyteasr.studio_helpers import probe_media_identity
    media = root/'tmp/visible-playback-v2/media/subtitle-safe'
    if not all((media/f'V{i}-30s.mp4').is_file() for i in (1,2)):
        raise ValueError('Existing silent V1/V2 30s fixtures are required; no media is regenerated')
    project = SubtitleProject(media=StudioMedia(str(media/'V1-30s.mp4'), duration_ms=30000, width=1920, height=1080),
        speakers=[StudioSpeaker('S02')], cues=[StudioCue('a',1000,3000,'alpha 回归字幕','S02')])
    project.validate()
    hydrate_media_contract(project, probe_media_identity(project.media.path))
    save_project(project, out/'v1.2byteproj')
    asset = add_media_asset(project, media/'V2-30s.mp4', duration_ms=30000,
                            video_metadata={'width':1920,'height':1080,'fps':60}, audio_metadata={'has_audio':True})
    track = create_video_track(project)
    clip = add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0, source_out_ms=30000)
    clip.transform.scale_x = clip.transform.scale_y = .45
    clip.transform.position_x = .74
    clip.transform.position_y = .28
    hydrate_media_contract(project, probe_media_identity(str(media/'V2-30s.mp4')), source_path=str(media/'V2-30s.mp4'))
    save_project(project, out/'v2.2byteproj')
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    with (out/'process.log').open('w', encoding='utf8') as log:
        result = run_hidden_subprocess(command, cwd=str(root), env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
                                       timeout=180, purpose='silent bounded speaker workflow verification')
    print('exit', result.returncode)
    payload = json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({'passed':payload.get('passed'),'check_count':len(payload.get('checks',[])),
        'failures':[row for row in payload.get('checks',[]) if not row['passed']], 'error':payload.get('error')}, ensure_ascii=False, indent=2))
    return 0 if result.returncode == 0 and payload.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
