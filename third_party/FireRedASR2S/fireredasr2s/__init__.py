# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang, Yan Jia, Junjie Chen, Wenpeng Li)

import os
import sys
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=ALL, 1=INFO, 2=WARNING, 3=ERROR
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

__version__ = "0.0.1"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fireredasr2s.fireredasr2system import (
    FireRedAsr2System,
    FireRedAsr2SystemConfig
)


# API
__all__ = [
    "__version__",
    "FireRedAsr2System",
    "FireRedAsr2SystemConfig",
    "FireRedAsr2",
    "FireRedAsr2Config",
    "FireRedVad",
    "FireRedVadConfig",
    "FireRedStreamVad",
    "FireRedStreamVadConfig",
    "FireRedAed",
    "FireRedAedConfig",
    "FireRedLid",
    "FireRedLidConfig",
    "FireRedPunc",
    "FireRedPuncConfig",
]
