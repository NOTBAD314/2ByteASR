"""Normal-entry, isolated source/frozen verification against a real project copy."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--presets', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--export-mode', choices=('native','advanced','html'), default='advanced')
    parser.add_argument('--html-project', type=Path)
    parser.add_argument('--completion-dpr', type=float, choices=(1.25,1.5,2.0))
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp'): raise ValueError('isolated tmp output required')
    out.mkdir(parents=True, exist_ok=True)
    (out/'temp').mkdir(exist_ok=True)
    if args.completion_dpr:
        os.environ.update(TWOBYTEASR_COMPLETION_AUDIT='1',TWOBYTEASR_COMPLETION_DPR=str(args.completion_dpr),
                          QT_SCALE_FACTOR=str(args.completion_dpr/1.75),QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    if args.export_mode=='html':
        if not args.html_project:raise ValueError('--html-project is required for HTML audit')
        shutil.copyfile(args.html_project,out/'html-fixture.2byteproj')
        os.environ['TWOBYTEASR_PRESET_AUDIT_HTML_PROJECT']=str(out/'html-fixture.2byteproj')
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        TEMP=str(out/'temp'),TMP=str(out/'temp'),
        TWOBYTEASR_PRESET_AUDIT_EXPORT_MODE=args.export_mode,
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime',
        TWOBYTEASR_CAPTION_AUDIT_MODE='preset-export', TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    from twobyteasr.studio_project import load_project, save_project, StudioSpeaker
    from twobyteasr.style_presets import StylePresetStore
    p = load_project(args.project)
    # The real media, layout, style and cue times remain; this one cue is the
    # specified 15-CJK geometry probe, and B provides a distinct speaker scope.
    next(c for c in p.cues if c.id == '3').text = '一二三四五六七八九十甲乙丙丁戊'
    p.speakers.append(StudioSpeaker('AUDIT-B'))
    for cue in p.cues[len(p.cues)//2:]: cue.speaker_id = 'AUDIT-B'
    save_project(p, out/'fixture.2byteproj')
    store = StylePresetStore(); store.path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.presets, store.path)
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    with (out/'process.log').open('w', encoding='utf8') as log:
        child = run_hidden_subprocess(command, cwd=root, env=os.environ.copy(), stdout=log,
            stderr=subprocess.STDOUT, timeout=args.timeout, purpose='preset and export normal-entry audit')
    data = json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({k:data.get(k) for k in ('passed','error','export_error','scopes')}, ensure_ascii=False))
    return child.returncode or (0 if data.get('passed') else 1)


if __name__ == '__main__': raise SystemExit(main())
