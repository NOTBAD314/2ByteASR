"""Run the normal source entry with a privately supplied playback audit."""
import importlib.abc
import importlib.util
import os
from pathlib import Path
import runpy
import shutil
import sys

root = Path(__file__).resolve().parents[1]
product = Path(os.environ.get('LARGE_PLAYBACK_PRODUCT') or root)
sys.path.insert(0, str(product))
from twobyteasr.test_isolation import install
install()

font_dir = Path(os.environ['LOCALAPPDATA']) / 'Microsoft/Windows/Fonts'
font_dir.mkdir(parents=True, exist_ok=True)
for name in ('猫啃什锦黑.ttf', '优设标题黑.ttf', 'SourceHanSansSC-VF.otf'):
    source = Path(os.environ['LARGE_PLAYBACK_FONTS']) / name
    if source.is_file():
        shutil.copy2(source, font_dir / name)


class AuditFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'twobyteasr.acceptance.review_editor_audit':
            audit = ('large_playback_interaction_audit.py' if os.environ.get('LARGE_PLAYBACK_INTERACTIONS') == '1'
                     else 'large_playback_audit.py')
            return importlib.util.spec_from_file_location(
                fullname, root / 'twobyteasr/acceptance' / audit)


sys.meta_path.insert(0, AuditFinder())
if __name__ == '__main__':
    runpy.run_path(str(product / 'quick_start.py'), run_name='__main__')
