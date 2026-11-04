"""Normal Windows entry, isolated project/configuration, surface and lifecycle audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline-source', type=Path)
    p.add_argument('--scale', default='0.5714285714')
    p.add_argument('--zoom', type=int, default=100)
    p.add_argument('--size', default='1600x980')
    p.add_argument('--theme', default='grape')
    p.add_argument('--visible', action='store_true')
    p.add_argument('--fresh-import', action='store_true')
    p.add_argument('--skip-zoom-cycle', action='store_true')
    p.add_argument('--screen-only', action='store_true')
    p.add_argument('--wait-focus', action='store_true')
    p.add_argument('--layout-only', action='store_true')
    p.add_argument('--exe', type=Path)
    p.add_argument('--gui', type=Path)
    p.add_argument('--entry-bridge', type=Path)
    p.add_argument('--range-replay', type=Path)
    a = p.parse_args(); out = a.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        p.error('Choose a fresh output under this source/tmp')
    out.mkdir(parents=True)
    original = hashlib.sha256(a.project.read_bytes()).hexdigest()
    shutil.copy2(a.project, out/'project.2byteproj')
    replay=None
    if a.range_replay:
        folder=a.range_replay.resolve();report=json.loads(next(folder.glob('*_字幕任务报告.json')).read_text('utf8'))
        cache=Path(report['cache']['directory'])
        for src,name in [(folder/'raw-response.json','replay-raw.json'),(folder/'heard.wav','replay-heard.wav'),
                         (folder/'manifest.json','replay-manifest.json'),(cache/'primary_api.json','replay-primary.json'),
                         (cache/'firered_primary.json','replay-aligned.json'),(cache/'final_timing.json','replay-final.json')]:
            shutil.copy2(src,out/name)
        manifest=json.loads((folder/'manifest.json').read_text('utf8'))
        replay=dict(job_id=report['job_id'],window_ms=manifest['project_range_ms'],
                    requested_ms=[manifest['sequence']['in_point_ms'],manifest['sequence']['out_point_ms']])
    import_source=''
    if a.fresh_import:
        import_source=json.loads(a.project.read_text('utf-8-sig'))['media']['path']
        os.environ['TWOBYTEASR_TEST_ROOT']=str(out);sys.path.insert(0,str(root))
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
        save_project(SubtitleProject(StudioMedia('')),out/'project.2byteproj')
    (out/'input.json').write_text(json.dumps(dict(theme=a.theme, zoom=a.zoom,
        baseline=bool(a.baseline_source), visible=a.visible, fresh_import=a.fresh_import, import_source=import_source,
        skip_zoom_cycle=a.skip_zoom_cycle,screen_only=a.screen_only,wait_focus=a.wait_focus,
        layout_only=a.layout_only,range_replay=replay,source_sha256=original)), 'utf8')
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-surface', TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_STARTUP_SIZE=a.size,
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=a.scale,
        PYTHONUTF8='1', HF_HUB_OFFLINE='1', TWOBYTEASR_WINDOW_TRACE_SECONDS='180',TWOBYTEASR_SCREEN_PROBE_PYTHON=sys.executable)
    if a.baseline_source: env['STUDIO_SURFACE_BASELINE_SOURCE'] = str(a.baseline_source.resolve())
    cmd = [sys.executable, '-B', '-X', 'utf8', str(root/'scripts/studio_surface_entry.py')]
    if a.exe:cmd=[str(a.exe.resolve())]
    if a.gui:
        if not a.exe or not a.entry_bridge:p.error('--gui needs --exe and --entry-bridge')
        cmd=[sys.executable,'-B',str(a.entry_bridge.resolve()),'--launcher',str(a.exe.resolve()),
             '--gui',str(a.gui.resolve()),'--output',str(out),'--timeout','260']
    if a.visible:
        import subprocess
        with (out/'process.log').open('wb') as log:
            code = subprocess.run(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                timeout=280, creationflags=0x08000000).returncode
    else:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(cmd, cwd=root, env=env, output=out/'process', timeout=280)
    file = out/'result.json'
    r = json.loads(file.read_text('utf8')) if file.exists() else {}
    r.update(process_exit=code, input_unchanged=hashlib.sha256(a.project.read_bytes()).hexdigest()==original)
    r['passed'] = bool(r.get('passed') and r.get('gui_shutdown') and code==0 and r['input_unchanged'])
    file.write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str), 'utf8')
    print(json.dumps({k:r.get(k) for k in ('passed','process_exit','error','failures','native_dispatch')}, ensure_ascii=False))
    return 0 if r['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
