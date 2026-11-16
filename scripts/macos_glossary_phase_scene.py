"""A private synthetic R5 scene with only bounded stage/time telemetry."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import macos_caption_policy_smoke as smoke
original=smoke.blank_environment
def phase_environment(out,invoker,target):
    env=original(out,invoker,target)
    from twobyteasr.app import user_overlay
    assert user_overlay.root().resolve().is_relative_to(out.resolve())
    identity='1.1.1 95fff3eeb5'
    entry,_=user_overlay.add('script','','Owned glossary stage timing',
        code=(ROOT/'scripts/macos_glossary_phase_probe.py').read_text('utf-8'),
        by='user',enabled=True,app_version=identity)
    assert entry['id']=='u1'
    user_overlay.set_scripts_allowed(True);user_overlay.mark_seen_version(identity)
    return env
smoke.blank_environment=phase_environment
if __name__=='__main__':
    code=smoke.main()
    out=Path(sys.argv[sys.argv.index('--output')+1])
    data=json.loads((out/'conflict-result.json').read_text('utf-8')) if (out/'conflict-result.json').exists() else {}
    (out/'phase-result.json').write_text(json.dumps(dict(passed=bool(data.get('passed')),checks=len(data.get('checks',[])))),encoding='utf-8')
    raise SystemExit(code)
