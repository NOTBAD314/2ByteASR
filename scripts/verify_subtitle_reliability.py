"""Exercise the real Windows workbench with isolated long subtitle fixtures."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--dpr', type=float, default=1)
    parser.add_argument('--cycles', type=int, default=20)
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("cycles must be positive")
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        parser.error('choose a fresh directory under source/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project)
    media = output / 'fixture.mp4'
    subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y', '-f', 'lavfi',
        '-i', 'color=c=0x283d4e:s=960x540:r=25:d=16', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-threads', '2', str(media)], check=True)
    for count in (4485, 8468):
        project = SubtitleProject(StudioMedia(str(media), duration_ms=count * 1800, width=960, height=540),
            speakers=[StudioSpeaker('S00', '人物')])
        for index in range(count):
            text = 'えBGMめっちゃいい? い? な!' if index == 0 else '字幕 evidence body ' + str(index)
            project.cues.append(StudioCue(f'cue-{index}', index * 1800, index * 1800 + 1400,
                text, 'S00', evidence_refs=[f'e-{index}']))
            project.asr_evidence[f'e-{index}'] = dict(text=text, start=index * 1.8, end=index * 1.8 + 1.4,
                words=[dict(text=char, start=index * 1.8 + part * .02,
                            end=index * 1.8 + part * .02 + .01) for part, char in enumerate(text)])
        project.generation_metadata['translations'] = {cue.id: '译文 ' + str(index) for index, cue in enumerate(project.cues)}
        save_project(project, output / f'fixture-{count}.2byteproj')
    blank = save_project(SubtitleProject(StudioMedia('')), output / 'entry.2byteproj')
    native_scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='subtitle-reliability', SUBTITLE_AUDIT_CYCLES=str(args.cycles),
        TWOBYTEASR_STARTUP_PROJECT=str(blank),
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_MAIN_PYTHON=sys.executable,
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_SIZE='1440x900',
        TWOBYTEASR_MPV=str(ROOT / 'tools/mpv/mpv.exe'), QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR=str(args.dpr / native_scale), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=600)
    path = output / 'result.json'
    result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(passed=False, error='missing GUI receipt')
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', {})),
                         exports=len(result.get('exports', [])), error=result.get('error', '')), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
