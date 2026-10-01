# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu)

import os
import sys
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=ALL, 1=INFO, 2=WARNING, 3=ERROR
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

__version__ = "0.0.1"

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from fireredasr2s.fireredasr2.asr import FireRedAsr2, FireRedAsr2Config
except ImportError:
    if _CURRENT_DIR not in sys.path:
        sys.path.insert(0, _CURRENT_DIR)
    from .asr import FireRedAsr2, FireRedAsr2Config


# API
__all__ = [
    "__version__",
    "FireRedAsr2",
    "FireRedAsr2Config",
]
