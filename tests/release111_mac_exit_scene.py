"""Compare old direct-quit with the actual window close on owned fixtures."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import macos_caption_policy_smoke as smoke
original=smoke.blank_environment
mode=os.environ.get('EXIT_CHECK_MODE','original')
assert mode in {'original','window-close'}
def environment(out,invoker,target):
    env=original(out,invoker,target)
    from twobyteasr.app import user_overlay
    assert user_overlay.root().resolve().is_relative_to(out.resolve())
    code=(ROOT/'tests/release111_mac_exit_phase.py').read_text('utf-8')
    if mode=='window-close':
        source=(ROOT/'tests/release111_mac_multilingual_close.py').read_text('utf-8')
        code+='\nCLOSE_AUDIT_SOURCE='+repr(source)+'\nphase_setup=setup\n'
        code+=('def setup(api):\n'
               '    phase_setup(api)\n'
               '    from twobyteasr.acceptance import multilingual_terms_audit\n'
               '    scope={"__package__":"twobyteasr.acceptance","__name__":"twobyteasr.acceptance.external_close_fixture"}\n'
               '    exec(compile(CLOSE_AUDIT_SOURCE,"external_close_fixture.py","exec"),scope)\n'
               '    multilingual_terms_audit.start=scope["start"]\n')
    else:source=''
    identity='1.1.1 589308de06'
    user_overlay.add('script','','Owned exit path checks',code=code,by='user',enabled=True,app_version=identity)
    user_overlay.set_scripts_allowed(True);user_overlay.mark_seen_version(identity)
    (out/'exit-driver-binding.json').write_text(json.dumps(dict(mode=mode,
        checker_source=subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        product_source='589308de06500575946e292520391f84d06c05d1',
        fixture_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest())),encoding='utf-8')
    return env
smoke.blank_environment=environment
if __name__=='__main__':raise SystemExit(smoke.main())
