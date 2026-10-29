"""Verify saved real translation performance results without network calls."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from twobyteasr.acceptance.translation_result_verification import main
if __name__=='__main__':raise SystemExit(main())
