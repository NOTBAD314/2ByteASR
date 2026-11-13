"""Real Windows output-loopback audition check; all files stay under tmp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twobyteasr.acceptance.proofread_audio_audit import main

if __name__ == "__main__":
    raise SystemExit(main())
