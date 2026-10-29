"""Same-input timeline/proofread audit through the normal application entry."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--profile', action='store_true')
    p.add_argument('--visible', action='store_true')
    p.add_argument('--cycles', type=int, default=2)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--hold', type=float, default=0)
    p.add_argument('--span', type=int, default=60000)
    p.add_argument('--quick', action='store_true')
    p.add_argument('--review-only', action='store_true')
    p.add_argument('--strip', action='store_true', help='Brief topmost timeline-only pixel audit; same window geometry')
    p.add_argument('--phases', default='', help='Optional comma-separated functional/performance cases')
    a = p.parse_args()
    out = a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        p.error('Fresh directory under repository tmp required')
    out.mkdir(parents=True)
    # Match the selected real library contents without allowing writes to the
    # user's file. API/settings credentials are not copied.
    import shutil
    glossary=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'2ByteASR/learned_game_terms.json'
    if glossary.is_file():
        target=out/'local/2ByteASR/learned_game_terms.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(glossary,target)
    data = a.project.read_bytes()
    (out / 'project.2byteproj').write_bytes(data)
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_SIZE='1600x950', TWOBYTEASR_STARTUP_PROJECT=str(out / 'project.2byteproj'),
        TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek'), TWOBYTEASR_ACCEPTANCE_SCENARIO='controls-timeline',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TIMELINE_AUDIT_PROFILE=str(int(a.profile)),
        TIMELINE_AUDIT_VISIBLE=str(int(a.visible)), TIMELINE_AUDIT_CYCLES=str(a.cycles),
        TIMELINE_AUDIT_HOLD=str(a.hold),TIMELINE_AUDIT_SPAN=str(a.span),
        TIMELINE_AUDIT_QUICK=str(int(a.quick)),
        TIMELINE_AUDIT_REVIEW_ONLY=str(int(a.review_only)),
        TIMELINE_AUDIT_STRIP=str(int(a.strip)),
        TIMELINE_AUDIT_PHASES=a.phases,
        QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    for key in ('QT_SCALE_FACTOR', 'QT_FONT_DPI', 'QT_ENABLE_HIGHDPI_SCALING'):
        env.pop(key, None)
    entry = ROOT / 'quick_start.py'
    if a.baseline:
        # Swap only changed product modules before their first import. The
        # harness, remaining source, input and settings stay identical.
        before = a.baseline.resolve()
        modules = {}
        for source in (before / 'twobyteasr').rglob('*.py'):
            rel = source.relative_to(before)
            current = ROOT / rel
            if 'acceptance' not in rel.parts and current.is_file() and source.read_bytes() != current.read_bytes():
                modules['.'.join(rel.with_suffix('').parts)] = str(source)
        (out / 'baseline-modules.json').write_text(json.dumps(modules, indent=2), 'utf8')
        entry = out / 'entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy,json\n'
            + 'sys.path.insert(0,' + repr(str(ROOT)) + ')\n'
            + 'modules=' + repr(modules) + '\n'
            + 'class Before(importlib.abc.MetaPathFinder):\n'
            + ' def find_spec(self,name,path=None,target=None):\n'
            + '  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            + 'sys.meta_path.insert(0,Before())\n'
            + 'runpy.run_path(' + repr(str(ROOT / 'quick_start.py')) + ',run_name="__main__")\n', 'utf8')
    command = [sys.executable, '-B', str(entry)]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=600,
        desktop_name='Default' if a.visible else None)
    result_path = out / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.exists() else {}
    result.update(exit_code=code, original_unchanged=a.project.read_bytes() == data,
        original_sha256=hashlib.sha256(data).hexdigest(), visible=a.visible)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({k:result.get(k) for k in ('exit_code','error','checks','original_unchanged')}, ensure_ascii=False))
    return 0 if (code == 0 and not result.get('error') and result.get('original_unchanged')
        and result.get('finished') and result.get('gui_shutdown')
        and all(result.get('checks',{}).values())) else 1


if __name__ == '__main__':
    raise SystemExit(main())
