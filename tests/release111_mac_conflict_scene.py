"""Run a corrected external fixture against the unchanged frozen R6 app."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import macos_caption_policy_smoke as smoke
original=smoke.blank_environment

def corrected_environment(out,invoker,target):
    env=original(out,invoker,target)
    from twobyteasr.app import user_overlay
    assert user_overlay.root().resolve().is_relative_to(out.resolve())
    source=(ROOT/'tests/release111_mac_conflict_runtime.py').read_text('utf-8')
    code=('API_VERSION=1\nAUDIT_SOURCE='+repr(source)+'\n'
          'def setup(api):\n'
          '    from twobyteasr.acceptance import glossary_conflict_audit\n'
          '    scope={"__package__":"twobyteasr.acceptance","__name__":"twobyteasr.acceptance.external_conflict_fixture"}\n'
          '    exec(compile(AUDIT_SOURCE,"external_conflict_fixture.py","exec"),scope)\n'
          '    glossary_conflict_audit.start=scope["start"]\n')
    identity='1.1.1 9e17e45884'
    user_overlay.add('script','','Owned native card-layout fixture',code=code,by='user',enabled=True,app_version=identity)
    user_overlay.set_scripts_allowed(True);user_overlay.mark_seen_version(identity)
    (out/'external-driver.json').write_text(json.dumps(dict(
        checker_source=subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        fixture_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
        product_source='9e17e45884dbf02d1ae8d3d3b79a5b74cd9a7403',
        scope='Test fixture only: native batched layout and real scrollbar action; every business assertion retained')),
        encoding='utf-8')
    return env

smoke.blank_environment=corrected_environment
if __name__=='__main__':raise SystemExit(smoke.main())
