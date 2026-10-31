"""Offline focused tests; isolate before collection and on Windows spawn."""
import os
import sys
from pathlib import Path
import uuid

ROOT=Path(__file__).resolve().parents[1]
if os.name == 'nt':
    # A native failure must return a failing test process, retaining stderr,
    # instead of waiting indefinitely in an invisible Windows crash dialog.
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x8003)
sys.path.insert(0,str(ROOT))
os.environ.setdefault('TWOBYTEASR_TEST_ROOT',str(ROOT/'tmp'/'isolated-tests'/uuid.uuid4().hex))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from twobyteasr.test_isolation import install
install()

def main():
    import isolated_pytest  # installs offline network / account-CLI guards
    import pytest
    return pytest.main(sys.argv[1:])


if __name__=='__main__':raise SystemExit(main())
