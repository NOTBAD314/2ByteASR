"""Repeat the complete normal installed-app verifier, with one corrected fixture."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import macos_verify_candidate as verifier
original_run=subprocess.run

def run(command,*args,**kwargs):
    cmd=list(command)
    if '--scenario' in cmd and cmd[cmd.index('--scenario')+1]=='glossary-conflicts':
        positions=[i for i,v in enumerate(cmd) if Path(str(v)).name=='macos_caption_policy_smoke.py']
        assert len(positions)==1
        cmd[positions[0]]=str(ROOT/'tests/release111_mac_conflict_scene.py')
    return original_run(cmd,*args,**kwargs)

subprocess.run=run
if __name__=='__main__':
    result=verifier.main()
    out=Path(sys.argv[sys.argv.index('--output')+1])
    product='9e17e45884dbf02d1ae8d3d3b79a5b74cd9a7403'
    actual=json.loads((out/'build/newer-system-result.json').read_text('utf-8'))
    assert actual['source_sha']==product
    original_run(['/usr/bin/codesign','--verify','--deep','--strict','/Applications/2ByteASR.app'],check=True)
    (out/'build/external-verification.json').write_text(json.dumps(dict(
        checker_source=subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        product_source=product,passed=bool(actual['passed']),binary_adhoc_signature_after=True,
        fixture_replacement='Only glossary-conflicts native layout setup; all original application checks run')),
        encoding='utf-8')
    raise SystemExit(result)
