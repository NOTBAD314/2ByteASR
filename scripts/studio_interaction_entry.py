"""Run the normal product entry with only the opt-in audit implementation replaced."""
from pathlib import Path
import importlib.abc
import importlib.util
import os
import runpy
import shutil
import sys

root=Path(__file__).resolve().parents[1]
product=Path(os.environ.get('INTERACTION_BASELINE_SOURCE') or root)
sys.path.insert(0,str(product))
from twobyteasr.test_isolation import install
install()
font_source=Path(os.environ['INTERACTION_PRESETS']).parent/'优设标题黑.ttf'
if font_source.is_file():
    font_dir=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts'
    font_dir.mkdir(parents=True,exist_ok=True)
    shutil.copy2(font_source,font_dir/font_source.name)
from twobyteasr.caption_style.style_presets import StylePresetStore
store=StylePresetStore()
profile=Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve()
if not store.path.resolve().is_relative_to(profile):
    raise RuntimeError('Preset copy must stay in the owned profile')
store.path.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(os.environ['INTERACTION_PRESETS'],store.path)

class AuditOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='twobyteasr.acceptance.review_editor_audit':
            return importlib.util.spec_from_file_location(fullname,root/'twobyteasr/acceptance/studio_interaction_audit.py')
sys.meta_path.insert(0,AuditOnly())
if __name__=='__main__':
    runpy.run_path(str(product/'quick_start.py'),run_name='__main__')
