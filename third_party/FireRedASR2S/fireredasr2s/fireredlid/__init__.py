# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)

import os
import sys

__version__ = "0.0.1"

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from fireredasr2s.fireredlid.lid import FireRedLid, FireRedLidConfig
except ImportError:
    if _CURRENT_DIR not in sys.path:
        sys.path.insert(0, _CURRENT_DIR)
    from .lid import FireRedLid, FireRedLidConfig


# API
__all__ = [
    "__version__",
    "FireRedLid",
    "FireRedLidConfig",
]
