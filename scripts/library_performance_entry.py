"""Supply only the audit to an unmodified product checkout for A/B runs."""
from pathlib import Path
import importlib.abc,importlib.util,os,runpy,sys
root=Path(__file__).resolve().parents[1]
product=Path(os.environ.get('LIBRARY_BASELINE_SOURCE') or root)
sys.path.insert(0,str(product))
from twobyteasr.test_isolation import install
install()
class AuditOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='twobyteasr.acceptance.review_editor_audit':
            return importlib.util.spec_from_file_location(fullname,root/'twobyteasr/acceptance/library_performance_audit.py')
sys.meta_path.insert(0,AuditOnly())
if __name__=='__main__':runpy.run_path(str(product/'quick_start.py'),run_name='__main__')
