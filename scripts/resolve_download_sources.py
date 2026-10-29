"""Isolated managed-Python entry for the source resolver."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from twobyteasr.download_sources import main
raise SystemExit(main())
