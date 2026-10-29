"""Run the opt-in production performance benchmark."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from twobyteasr.acceptance.workbench_benchmark import main
if __name__=="__main__":raise SystemExit(main())
