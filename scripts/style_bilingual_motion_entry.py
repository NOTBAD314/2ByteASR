"""Normal entry with an opt-in in-process audit; baseline product stays intact."""
from pathlib import Path
import importlib.abc,importlib.util,os,runpy,shutil,sys
root=Path(__file__).resolve().parents[1]
product=Path(os.environ.get('STYLE_MOTION_BASELINE') or root)
sys.path.insert(0,str(product))
before=os.environ.get('STYLE_FONT_BEFORE')
if before:
    class BeforeFontLoader(importlib.abc.Loader):
        def __init__(self,saved,actual):self.saved,self.actual=saved,actual
        def create_module(self,spec):return None
        def exec_module(self,module):
            module.__file__=str(self.actual)
            exec(compile(self.saved.read_bytes(),str(self.actual),'exec'),module.__dict__)
    class BeforeFontFinder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            names={'twobyteasr.caption_style.studio_font_combo','twobyteasr.caption_style.studio_style_widgets',
                   'twobyteasr.caption_style.studio_style_controller','twobyteasr.design.combo_popup'}
            if fullname in names:
                rel=Path(*fullname.split('.')[1:]).with_suffix('.py')
                actual=product/'twobyteasr'/rel
                return importlib.util.spec_from_loader(fullname,BeforeFontLoader(Path(before)/rel,actual),origin=str(actual))
    sys.meta_path.insert(0,BeforeFontFinder())
from twobyteasr.test_isolation import install
install()
font_dir=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts';font_dir.mkdir(parents=True,exist_ok=True)
for name in ('猫啃什锦黑.ttf','优设标题黑.ttf','SourceHanSansSC-VF.otf'):
    p=Path(os.environ['STYLE_MOTION_FONTS'])/name
    if p.is_file():shutil.copy2(p,font_dir/name)
# Preset validation may initialize the font catalogue: install test copies
# before importing any style modules so both runs use the actual chosen face.
from twobyteasr.caption_style.style_presets import StylePresetStore
store=StylePresetStore();store.path.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(os.environ['STYLE_MOTION_PRESETS'],store.path)
class AuditOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='twobyteasr.acceptance.review_editor_audit':
            audit='font_picker_audit.py'if os.environ.get('STYLE_FONT_AUDIT')=='1'else 'style_bilingual_motion_audit.py'
            return importlib.util.spec_from_file_location(fullname,root/'twobyteasr/acceptance'/audit)
sys.meta_path.insert(0,AuditOnly())
if __name__=='__main__':runpy.run_path(str(product/'quick_start.py'),run_name='__main__')
