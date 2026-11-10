"""Run the same isolated MainWindow checks inside the shipped executable."""
import os
from pathlib import Path
from types import SimpleNamespace


def start(window, output):
    from PySide6.QtCore import QTimer
    from scripts.verify_review_reliability import child
    args = SimpleNamespace(project=Path(os.environ['TWOBYTEASR_STARTUP_PROJECT']).resolve(),
                           output=Path(output).resolve(), module_root=None, logic_only=False)
    QTimer.singleShot(250, lambda: child(args, window=window))
