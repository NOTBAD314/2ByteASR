"""Install the SAME audited DMG on a newer disposable native Mac runner."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.macos_build import sha256, finder_environment
from scripts.macos_binary_audit import audit_tree
from scripts.macos_startup_contract import probe
from twobyteasr.system.macos_compatibility import MINIMUM_MACOS, host_diagnostics


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dmg',type=Path,required=True)
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--source-sha',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    if sys.platform!='darwin' or platform.machine()!='arm64' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('A disposable native GitHub Mac runner is required')
    out=args.output.resolve()
    if out.exists() or 'tmp' not in out.parts:
        raise SystemExit('Choose a fresh tmp output directory')
    expected=json.loads(args.receipt.read_text('utf8'))
    if (not expected.get('passed') or expected['source_identity']['git_sha']!=args.source_sha
            or args.dmg.stat().st_size!=expected['artifact']['bytes']
            or sha256(args.dmg)!=expected['artifact']['sha256']):
        raise SystemExit('Downloaded candidate differs from its source/DMG receipt')
    app=Path('/Applications/2ByteASR.app')
    if app.exists():
        raise SystemExit('Existing application will not be replaced')
    out.mkdir(parents=True);(out/'build').mkdir();mount=out/'mounted';mount.mkdir()
    result=dict(host=host_diagnostics(),source_sha=args.source_sha,dmg_sha256=expected['artifact']['sha256'],
                passed=False,actual_applications_install=False,browser_quarantine_verified=False)
    def run(cmd,timeout=300,check=True):
        with (out/'build/verification.log').open('ab') as stream:
            return subprocess.run(list(map(str,cmd)),check=check,timeout=timeout,stdout=stream,stderr=subprocess.STDOUT)
    try:
        run(['/usr/bin/hdiutil','verify',args.dmg])
        run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen','-mountpoint',mount,args.dmg])
        run(['/usr/bin/ditto',mount/'2ByteASR.app',app])
        result['actual_applications_install']=True
        run(['/usr/bin/codesign','--verify','--deep','--strict',app])
        result['gatekeeper_assessment_exit']=run(['/usr/sbin/spctl','--assess','--type','execute','--verbose',app],check=False).returncode
        audit=audit_tree(app,arch='arm64',target=MINIMUM_MACOS)
        (out/'build/binary-compatibility.json').write_text(json.dumps(audit,indent=2)+'\n','utf8')
        if not audit['passed']:raise RuntimeError('Installed native compatibility audit failed')
        for label,finder in (('direct',False),('finder',True)):
            result[label]=probe(app,out/(label+'-profile'),out/('build/startup-'+label+'.log'),finder=finder,
                                environment=finder_environment(out/(label+'-profile')),cwd=out)
        if not all(result[label]['passed'] for label in ('direct','finder')):
            raise RuntimeError('Normal installed startup failed')
        run([sys.executable,ROOT/'scripts/verify_blank_project_macos.py','--app',app,'--output',out/'blank-project'],timeout=240)
        run([app/'Contents/MacOS/2ByteASR','--macos-media-smoke',out/'native-media-smoke'],timeout=120)
        run([sys.executable,ROOT/'scripts/macos_renderer_smoke.py','--app',app,'--output',out/'renderer-smoke'],timeout=660)
        audio=out/'speech.wav'
        run(['/usr/bin/say','-v','Tingting','--data-format=LEI16@16000','-o',audio,
             '今天测试兔白字幕。字幕可以编辑，剪切后保存工程，最后导出视频。'])
        run([sys.executable,ROOT/'scripts/macos_desktop_smoke.py','--app',app,'--runtime',out/'unused-build-runtime',
             '--fresh-runtime','--audio',audio,'--output',out/'desktop-flow'],timeout=2100)
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
    finally:
        if os.path.ismount(mount):
            run(['/usr/bin/hdiutil','detach',mount],check=False)
        (out/'build/newer-system-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps({k:result[k] for k in ('passed','source_sha','dmg_sha256') }))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
