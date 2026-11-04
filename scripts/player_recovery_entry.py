"""Isolated normal app entry for source playback recovery acceptance."""
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from twobyteasr.test_isolation import install
install()
from twobyteasr.acceptance.blank_project_audit import install_offline_guards
install_offline_guards()
runpy.run_path(str(root/'quick_start.py'), run_name='__main__')
