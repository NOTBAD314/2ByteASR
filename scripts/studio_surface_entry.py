"""Source-only normal-entry audit; optionally run unchanged baseline product code."""
import importlib.util
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
product = Path(os.environ.get('STUDIO_SURFACE_BASELINE_SOURCE') or root)
sys.path.insert(0, str(product))
from twobyteasr.test_isolation import install
install()
from twobyteasr.acceptance import studio_acceptance_audit as entry
from twobyteasr.acceptance.blank_project_audit import install_offline_guards
install_offline_guards()
spec = importlib.util.spec_from_file_location('surface_audit', root/'twobyteasr/acceptance/studio_surface_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
entry.start_acceptance = lambda window: audit.start(window, entry.audit_directory())
runpy.run_path(str(product/'quick_start.py'), run_name='__main__')
