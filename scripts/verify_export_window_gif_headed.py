"""Temporary media, normal application entry and private Windows desktop."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--phase', default='export')
    p.add_argument('--scale', default='')
    p.add_argument('--exe', type=Path)
    p.add_argument('--expected-gui-sha256')
    a = p.parse_args()
    if a.exe and (not a.exe.is_file() or a.baseline):
        p.error('Existing EXE and no external source override required')
    out = a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        p.error('Fresh repository tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (
        SubtitleProject, StudioMedia, StudioCue, default_style, save_project)
    media = out / 'reference.mp4'
    if a.phase in ('gif', 'gif-solo'):
        from PIL import Image, ImageDraw
        for disposal in (1, 2, 3):
            frames = []
            for x, color in [(0, 'red'), (20, 'lime'), (40, 'yellow')]:
                image = Image.new('RGBA', (80, 60), (0,0,0,0))
                ImageDraw.Draw(image).rectangle((x,10,x+15,30), fill=color)
                frames.append(image)
            frames[0].save(out / f'animation-{disposal}.gif', save_all=True,
                append_images=frames[1:], duration=[100,300,200], loop=0, disposal=disposal, optimize=True)
        large = []
        for i in range(120):
            image = Image.new('RGBA',(1024,576),(0,0,0,0))
            ImageDraw.Draw(image).rectangle((i*7%900,80,i*7%900+100,220),fill=(i*17%255,220,80,255))
            large.append(image)
        large[0].save(out/'large.gif',save_all=True,append_images=large[1:],duration=40,
            disposal=2,loop=0,optimize=True)
        del large
    subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=8',
        '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=8',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '30', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-shortest', str(media)], check=True)
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=8000, width=640, height=360),
        styles=[default_style()], cues=[StudioCue(f'c{i}', i*1500+200, i*1500+1400, f'定位验证 {i}') for i in range(5)])
    fixture = out / 'fixture.2byteproj'
    save_project(project, fixture)
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='export-window-gif', TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_SIZE='1440x900', EXPORT_GIF_PHASE=a.phase, QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
        HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='localhost,127.0.0.1')
    for key in ('QT_SCALE_FACTOR', 'QT_FONT_DPI'):
        env.pop(key, None)
    if a.scale:
        env['QT_SCALE_FACTOR'] = a.scale
    entry = ROOT / 'quick_start.py'
    if a.exe:
        env['TWOBYTEASR_EXPECTED_GUI_SHA256'] = a.expected_gui_sha256 or hashlib.sha256(a.exe.read_bytes()).hexdigest()
    if a.baseline:
        modules = {}
        before = a.baseline.resolve()
        for source in (before / 'twobyteasr').rglob('*.py'):
            rel = source.relative_to(before)
            current = ROOT / rel
            if 'acceptance' not in rel.parts and current.exists() and source.read_bytes() != current.read_bytes():
                modules['.'.join(rel.with_suffix('').parts)] = str(source)
        entry = out / 'entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            + 'sys.path.insert(0,' + repr(str(ROOT)) + ')\nmodules=' + repr(modules) + '\n'
            + 'class Before(importlib.abc.MetaPathFinder):\n'
            + ' def find_spec(self,name,path=None,target=None):\n'
            + '  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            + 'sys.meta_path.insert(0,Before())\nrunpy.run_path('
            + repr(str(ROOT / 'quick_start.py')) + ',run_name="__main__")\n', 'utf8')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(a.exe.resolve())] if a.exe else [sys.executable, '-B', str(entry)]
    code = run_on_desktop(command, cwd=ROOT, env=env,
        output=out / 'process', timeout=300)
    receipt = out / 'result.json'
    deadline=time.monotonic()+120
    result={}
    while time.monotonic()<deadline:
        try: result=json.loads(receipt.read_text('utf8'))
        except (OSError,ValueError): pass
        if code and not result: break
        if result.get('gui_shutdown') or result.get('error'): break
        time.sleep(.1)
    if a.exe:
        import psutil
        runtime=result.get('runtime',{})
        expected=a.expected_gui_sha256 or hashlib.sha256(a.exe.read_bytes()).hexdigest()
        result['identity_passed']=bool(runtime.get('frozen') and runtime.get('exe_sha256')==expected)
        result.setdefault('checks',{})['frozen-gui-identity']=result['identity_passed']
        pid=runtime.get('pid')
        if pid and psutil.pid_exists(pid):
            try: result['gui_exit']=psutil.Process(pid).wait(timeout=30)
            except psutil.NoSuchProcess: result['gui_exit']=0
            except psutil.TimeoutExpired: result['gui_exit']='timeout'
        else: result['gui_exit']=0
        result['checks']['gui-process-exited']=result['gui_exit']==0
    result.setdefault('checks',{})['gui-shutdown']=bool(result.get('gui_shutdown'))
    result['checks']['audit-finished']=bool(result.get('finished'))
    result['exit_code'] = code
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(exit_code=code, error=result.get('error'),
        passed=sum(bool(v) for v in result.get('checks', {}).values()),
        failed=[k for k,v in result.get('checks', {}).items() if not v],
        gui_shutdown=result.get('gui_shutdown')), ensure_ascii=False))
    return int(code != 0 or bool(result.get('error')) or not all(result.get('checks', {}).values()))


if __name__ == '__main__':
    raise SystemExit(main())
