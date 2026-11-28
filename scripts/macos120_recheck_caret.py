# SPDX-License-Identifier: GPL-3.0-only
"""Run the current caret fixture against an unchanged installed 1.2.0 .app."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import macos_caret_split_smoke as runner

PRODUCT = 'dee83d5549434ac51538d636d7628c8cc22870a9'
MODULE = 'caption_caret_split_audit'


def bind_fixture(folder, invoker, target):
    env = original_environment(folder, invoker, target)
    from twobyteasr.app import user_overlay

    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    assert user_overlay.root().resolve().is_relative_to(folder.resolve())
    source = (ROOT / 'twobyteasr/acceptance' / (MODULE + '.py')).read_text('utf-8')
    code = 'API_VERSION = 1\nSOURCE = ' + repr(source) + '''
def setup(api):
    import json
    import os
    from pathlib import Path
    from twobyteasr.acceptance import caption_caret_split_audit
    from twobyteasr.app import user_overlay
    scope = {"__package__": "twobyteasr.acceptance",
             "__name__": "twobyteasr.acceptance.macos120_caret_fixture"}
    exec(compile(SOURCE, "macos120_caret_fixture.py", "exec"), scope)
    caption_caret_split_audit.start = scope["start"]
    user_overlay.remove(api.script_id)
    user_overlay.set_scripts_allowed(False)
    assert user_overlay.entries() == [] and not user_overlay.load()["scripts_allowed"]
    output = Path(os.environ["TWOBYTEASR_ACCEPTANCE_DIR"])
    (output / "bootstrap-neutral.json").write_text(json.dumps({"entries": 0, "scripts_allowed": False}), "utf-8")
'''
    user_overlay.check_script(code)
    identity = '1.2.0 ' + PRODUCT[:10]
    user_overlay.add('script', '', 'Owned 1.2.0 caret acceptance fixture',
                     code=code, by='user', enabled=True, app_version=identity)
    user_overlay.set_scripts_allowed(True)
    user_overlay.mark_seen_version(identity)
    checker = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    result = {'product_source': PRODUCT, 'checker_source': checker,
              'acceptance_module': MODULE, 'fixture_sha256': hashlib.sha256(source.encode()).hexdigest()}
    (folder / 'fixture-identity.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    return env


if __name__ == '__main__':
    original_environment = runner.blank_environment
    runner.blank_environment = bind_fixture
    code = runner.main()
    if not code:
        output = Path(sys.argv[sys.argv.index('--output') + 1])
        reset = json.loads((output / 'bootstrap-neutral.json').read_bytes())
        assert reset == {'entries': 0, 'scripts_allowed': False}
    raise SystemExit(code)
