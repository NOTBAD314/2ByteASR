"""Source-only audit wrapper; baseline product modules remain unmodified."""
from pathlib import Path
import importlib.abc
import importlib.util
import os
import runpy
import sys

root=Path(__file__).resolve().parents[1]
baseline=os.environ.get('REVIEW_EDITOR_BASELINE_SOURCE')
sys.path.insert(0,str(Path(baseline) if baseline else root))
from twobyteasr.test_isolation import install
install()
if baseline:
    class AuditOnly(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname in {'twobyteasr.acceptance.studio_acceptance_audit','twobyteasr.acceptance.review_editor_audit',
                            'twobyteasr.acceptance.caption_editor_a_audit','twobyteasr.acceptance.editor_bilingual_audit'}:
                file=root/'twobyteasr/acceptance'/ (fullname.rsplit('.',1)[1]+'.py')
                return importlib.util.spec_from_file_location(fullname,file)
    sys.meta_path.insert(0,AuditOnly())
runpy.run_path(str((Path(baseline) if baseline else root)/'quick_start.py'),run_name='__main__')
