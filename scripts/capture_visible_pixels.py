"""CLI wrapper for the same source/frozen screen probe."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from twobyteasr.visible_pixel_probe import main
if __name__=="__main__":main()
