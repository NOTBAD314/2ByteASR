"""Validate GPU model preparation through an existing candidate's frozen entry.

The checker can be newer than the app; both revisions are recorded separately.
No source checkout modules are substituted into the installed application's
Python, model preparer or inference workers.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.macos_build import sha256,finder_environment


def isolated_model_environment(output: Path) -> tuple[dict, Path]:
    profile=output/'profile'
    return finder_environment(profile),profile/'models'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dmg',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--app-source-sha',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mlx-only',action='store_true',help='Only rerun MLX; preserves earlier independent MPS evidence')
    args=parser.parse_args(argv)
    if sys.platform!='darwin' or platform.machine()!='arm64' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('Use a disposable native Mac runner')
    out=args.output.resolve()
    if out.exists() or 'tmp' not in out.parts:raise SystemExit('Use a fresh tmp output')
    receipt=json.loads(args.receipt.read_text('utf8'))
    if (not receipt.get('passed') or receipt['source_identity']['git_sha']!=args.app_source_sha
        or sha256(args.dmg)!=receipt['artifact']['sha256'] or args.dmg.stat().st_size!=receipt['artifact']['bytes']):
        raise SystemExit('Candidate does not match its source and artifact receipt')
    out.mkdir(parents=True);mount=out/'mount';mount.mkdir();app=Path('/Applications/2ByteASR.app')
    if app.exists():raise SystemExit('Will not replace an existing app')
    result=dict(passed=False,macos=platform.mac_ver()[0],architecture=platform.machine(),app_source_sha=args.app_source_sha,
                checker_sha=os.environ.get('GITHUB_SHA'),dmg_sha256=receipt['artifact']['sha256'],backends={},
                requested_backends=['mlx'] if args.mlx_only else ['mlx','mps'])
    env,models=isolated_model_environment(out)
    def run(command,log,timeout):
        with (out/log).open('ab') as stream:
            return subprocess.run(list(map(str,command)),env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    try:
        subprocess.run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen','-mountpoint',str(mount),str(args.dmg)],check=True)
        subprocess.run(['/usr/bin/ditto',str(mount/'2ByteASR.app'),str(app)],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        root=app/'Contents/Resources';exe=app/'Contents/MacOS/2ByteASR'
        identity=json.loads((root/'2byteasr_build.json').read_text('utf8'))
        if identity['git_sha']!=args.app_source_sha:raise RuntimeError('Installed app identity differs')
        for label,flag,keys,timeout in (
            ('mlx','--macos-prepare-mlx',['mlx_qwen_aligner','mlx_qwen3_asr_0_6b'],1200),):
            entry=dict(passed=False,keys=keys,entry='installed frozen app')
            result['backends'][label]=entry
            try:
                completed=run([exe,flag,'--root',root,'--models',models,'--keys',','.join(keys),'--source','HF_OFFICIAL'],label+'-prepare.log',timeout)
                entry['exit_code']=completed.returncode
                receipts=out/'profile/local/2ByteASR/model-readiness'
                wanted=keys+(['firered_vad','speaker_embedding'] if label=='mps' else [])
                entry['readiness']={}
                for key in wanted:
                    path=receipts/(key+'.json')
                    if path.is_file():
                        entry['readiness'][key]=json.loads(path.read_text('utf8'))
                        shutil.copy2(path,out/(key+'-readiness.json'))
                entry['passed']=completed.returncode==0 and all(entry['readiness'].get(key,{}).get('status')=='PASS' for key in wanted)
                if label=='mlx' and entry['passed']:
                    interpreters=list((out/'profile/local/2ByteASR/runtimes/mlx').glob('macos-mlx-*/bin/python'))
                    if len(interpreters)!=1:raise RuntimeError('Ambiguous managed MLX interpreter')
                    probe=run([interpreters[0],'-I',root/'mlx_worker.py','--mode','probe','--output',out/'mlx-probe.json'],'mlx-probe.log',180)
                    entry['device_probe']=json.loads((out/'mlx-probe.json').read_text('utf8')) if probe.returncode==0 else {}
                    entry['passed']=probe.returncode==0 and entry['device_probe'].get('metal_available') is True
            except Exception:entry['error']=traceback.format_exc()
        # MOSS / FireRed use the actual workshop and Home/Studio workflow,
        # including measured word times, bilingual editing and video export.
        if not args.mlx_only:
            mps=dict(passed=False,entry='installed frozen GUI',keys=['moss','firered_aed'])
            result['backends']['mps']=mps
            try:
                audio=out/'mps-speech.wav'
                subprocess.run(['/usr/bin/say','-v','Tingting','--data-format=LEI16@16000','-o',str(audio),
                    '今天测试兔白字幕。我们使用本地模型识别中文。字幕可以编辑，剪切后保存工程，最后导出视频。'],check=True,timeout=60)
                completed=run([sys.executable,ROOT/'scripts/macos_desktop_smoke.py','--app',app,'--runtime',out/'unused-build-runtime',
                    '--fresh-runtime','--audio',audio,'--output',out/'mps-desktop','--model-set','mac-gpu'],'mps-flow.log',3000)
                mps['exit_code']=completed.returncode
                for name in ('workshop-result','result','export-validation','restart-summary'):
                    path=out/'mps-desktop'/(name+'.json')
                    mps[name]=json.loads(path.read_text('utf8')) if path.is_file() else {}
                mps['passed']=completed.returncode==0 and all(mps[name].get('passed') is True for name in ('workshop-result','result','export-validation','restart-summary'))
            except Exception:mps['error']=traceback.format_exc()
        result['passed']=all(entry['passed'] for entry in result['backends'].values())
    except Exception:result['error']=traceback.format_exc()
    finally:
        if os.path.ismount(mount):subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],check=False)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
