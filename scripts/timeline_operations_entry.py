"""Normal entry, optionally replacing only the audit on a fixed baseline."""
from pathlib import Path
import importlib.abc
import importlib.util
import os
import runpy
import sys

root = Path(__file__).resolve().parents[1]
base = Path(os.environ.get('TIMELINE_BASELINE_SOURCE') or root)
sys.path.insert(0, str(base))
from twobyteasr.test_isolation import install
install()
if base != root:
    class AuditOnly(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in {'twobyteasr.acceptance.studio_acceptance_audit',
                            'twobyteasr.acceptance.timeline_operations_audit'}:
                return importlib.util.spec_from_file_location(fullname,
                    root/'twobyteasr/acceptance'/(fullname.rsplit('.',1)[1]+'.py'))
    sys.meta_path.insert(0, AuditOnly())
runpy.run_path(str(base/'quick_start.py'), run_name='__main__')
