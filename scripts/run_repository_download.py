"""Use the production repository adapter without frozen GUI extension pollution."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.append(str(Path(__file__).resolve().parents[1]))
from twobyteasr.repository_download import main
if __name__ == '__main__':
    raise SystemExit(main())
