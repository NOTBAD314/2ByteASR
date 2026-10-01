"""Run P6.2 protections through quick_start or a complete onedir EXE."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    output = args.output.resolve()
    if not output.is_relative_to(root/'tmp') or output.exists():
        raise ValueError('A fresh repository tmp output is required')
    output.mkdir(parents=True)
    (output/'temp').mkdir()
    os.environ.update(LOCALAPPDATA=str(output/'local'),APPDATA=str(output/'roaming'),TEMP=str(output/'temp'),TMP=str(output/'temp'))
    from twobyteasr.studio_project import load_project, save_project, SubtitleProject, StudioMedia
    project = load_project(args.project)
    shutil.copyfile(project.media.path, output/'ingest-source.mp4')
    (output/'ingest-source.xml').write_text('<i><d p="1.0,1,25,16777215,0,0,audit,1">本地合成弹幕配对回归</d></i>', encoding='utf8')
    save_project(SubtitleProject(media=StudioMedia(path='')), output/'fixture.2byteproj')
    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'), QT_QPA_PLATFORM='windows',
        TEMP=str(output/'temp'),TMP=str(output/'temp'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='p62-regression',
        TWOBYTEASR_STARTUP_PROJECT=str(output/'fixture.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'))
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    with (output/'process.log').open('w', encoding='utf8') as log:
        process = run_hidden_subprocess(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
            timeout=150, purpose='Isolated normal-entry P6.2 regression')
    result = json.loads((output/'result.json').read_text('utf8'))
    print(json.dumps({k:result.get(k) for k in ('passed','checks','error','elapsed_seconds')}, ensure_ascii=False))
    return process.returncode or (0 if result.get('passed') else 1)


if __name__ == '__main__': raise SystemExit(main())
