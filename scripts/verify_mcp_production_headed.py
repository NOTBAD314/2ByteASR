"""Validate production MCP in the real isolated MainWindow and optional EXE."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--install-root', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(source / 'tmp'):
        raise ValueError('Use a new directory under this source tree/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    os.environ['2BYTEASR_INSTALL_ROOT'] = str(args.install_root.resolve())
    sys.path.insert(0, str(source))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.projects.studio_project import (
        SubtitleProject, StudioMedia, StudioCue, hydrate_media_contract, save_project,
    )
    from twobyteasr.timeline.studio_edit_sequence import identity_sequence, store_sequence
    ffmpeg = args.install_root / 'tools/ffmpeg/bin/ffmpeg.exe'
    ffprobe = ffmpeg.with_name('ffprobe.exe')
    for name, frequency in [('source', 440), ('replacement', 880)]:
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'color=c=0x234455:s=320x180:r=15:d=6', '-f', 'lavfi', '-i',
            f"aevalsrc='if(between(t,0,1)+between(t,4,5),0.25*sin(2*PI*{frequency}*t),0)':s=48000:d=6",
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest',
            str(output / (name + '.mp4'))], check=True, timeout=45)
    media = output / 'source.mp4'
    identity = MediaService(ffprobe_path=ffprobe).metadata(media)
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=identity.duration_ms,
        width=identity.width, height=identity.height, fingerprint=identity.fingerprint),
        cues=[StudioCue('acceptance-stutter', 0, 950, '再再强调一遍')])
    hydrate_media_contract(project, identity.to_dict(), source_path=media)
    store_sequence(project, identity_sequence(project.media))
    project_path = save_project(project, output / 'fixture.2byteproj')
    (output / 'input.json').write_text(json.dumps(dict(project=str(project_path),
        replacement=str(output / 'replacement.mp4'), repo=str(source)), ensure_ascii=False), 'utf8')
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_SCENARIO='mcp-production',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(project_path),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'),
        TWOBYTEASR_INVOKER_CWD=str(source), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(source / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(source / 'quick_start.py')]
    code = run_on_desktop(command, cwd=source, env=env, output=output / 'process', timeout=240)
    result_path = output / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {'passed': False}
    result['process_exit'] = code
    if result.get('video'):
        decoded = subprocess.run([str(ffmpeg), '-v', 'error', '-i', result['video'], '-f', 'null', '-'],
                                 capture_output=True, timeout=45)
        result['video_fully_decoded'] = decoded.returncode == 0
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if (result.get('passed') and result.get('gui_shutdown') and
                 result.get('video_fully_decoded') and code == 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
