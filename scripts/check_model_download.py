"""Opt-in lightweight diagnostic using the production model HTTP transport."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from twobyteasr.model_download_diagnostic import main
if __name__=='__main__': raise SystemExit(main())
