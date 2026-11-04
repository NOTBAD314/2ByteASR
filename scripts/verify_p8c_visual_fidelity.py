"""P8C entry point for LIVE/Remotion stroke, shadow, panel, and motion pixels."""

from __future__ import annotations

import runpy
from pathlib import Path


runpy.run_path(
    str(Path(__file__).with_name("verify_p8b_visual_fidelity.py")),
    run_name="__main__",
)
