# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Junjie Chen)

import os
import sys
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=ALL, 1=INFO, 2=WARNING, 3=ERROR
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

__version__ = "0.0.1"

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from fireredasr2s.fireredpunc.punc import FireRedPunc, FireRedPuncConfig
except ImportError:
    if _CURRENT_DIR not in sys.path:
        sys.path.insert(0, _CURRENT_DIR)
    from .punc import FireRedPunc, FireRedPuncConfig


# API
__all__ = [
    "__version__",
    "FireRedPunc",
    "FireRedPuncConfig",
]
