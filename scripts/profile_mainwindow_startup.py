"""Print cumulative hotspots inside MainWindow construction."""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr.ui import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication([])
    profiler = cProfile.Profile()
    profiler.enable()
    window = MainWindow([], subtitle_core, moss_firered_pipeline, None)
    profiler.disable()
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(60)
    print(output.getvalue())
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
