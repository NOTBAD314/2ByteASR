"""Bounded, silent normal-entry caption/review verification on tmp fixtures."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--mode', choices=['all', 'review', 'review-edit', 'style'], default='all')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp'):
        raise ValueError('output must be inside repository tmp')
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime',
        TWOBYTEASR_CAPTION_AUDIT_MODE=args.mode, TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    media = root/'tmp/visible-playback-v2/media/subtitle-safe/V1-30s.mp4'
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=30000, width=1920, height=1080),
        speakers=[StudioSpeaker('S01')], cues=[StudioCue('long', 1000, 7500, '只要打PVP顺手就给他做完了', 'S01')]+
        [StudioCue(f'review-{i:02d}', 8000+i*500, 8500+i*500, f'第{i+1}条审核字幕', 'S01') for i in range(31)])
    project.validate()
    hydrate_media_contract(project, probe_media_identity(str(media)))
    save_project(project, out/'fixture.2byteproj')
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    with (out/'process.log').open('w', encoding='utf8') as log:
        result = run_hidden_subprocess(command, cwd=str(root), env=os.environ.copy(), stdout=log,
            stderr=subprocess.STDOUT, timeout=150, purpose='bounded silent caption audit')
    payload = json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({k: payload.get(k) for k in ('passed','error','enter_summary','playback_seconds')}, ensure_ascii=False))
    return result.returncode or (0 if payload.get('passed') else 1)


if __name__ == '__main__':
    raise SystemExit(main())
