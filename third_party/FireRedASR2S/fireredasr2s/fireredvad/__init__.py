# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import os
import sys

__version__ = "0.0.1"

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from fireredasr2s.fireredvad.aed import FireRedAed, FireRedAedConfig
    from fireredasr2s.fireredvad.stream_vad import FireRedStreamVad, FireRedStreamVadConfig
    from fireredasr2s.fireredvad.vad import FireRedVad, FireRedVadConfig
except ImportError:
    if _CURRENT_DIR not in sys.path:
        sys.path.insert(0, _CURRENT_DIR)
    from .aed import FireRedAed, FireRedAedConfig
    from .stream_vad import FireRedStreamVad, FireRedStreamVadConfig
    from .vad import FireRedVad, FireRedVadConfig


def non_stream_vad(wav_path, model_dir="pretrained_models/FireRedVAD/VAD", **kwargs):
    """Quick VAD inference"""
    config = FireRedVadConfig(**kwargs)
    vad = FireRedVad.from_pretrained(model_dir, config)
    result, probs = vad.detect(wav_path)
    return result


def stream_vad_full(wav_path, model_dir="pretrained_models/FireRedVAD/Stream-VAD", **kwargs):
    """Quick Stream VAD inference"""
    config = FireRedStreamVadConfig(**kwargs)
    svad = FireRedStreamVad.from_pretrained(model_dir, config)
    frame_results, result = svad.detect_full(wav_path)
    return frame_results, result


def non_stream_aed(wav_path, model_dir="pretrained_models/FireRedVAD/AED", **kwargs):
    """Quick AED inference"""
    config = FireRedAedConfig(**kwargs)
    aed = FireRedAed.from_pretrained(model_dir, config)
    result, probs = aed.detect(wav_path)
    return result


__all__ = [
    '__version__',
    'FireRedVad',
    'FireRedVadConfig',
    'FireRedAed',
    'FireRedAedConfig', 
    'FireRedStreamVad',
    'FireRedStreamVadConfig',
    'non_stream_vad',
    'stream_vad_full',
    'non_stream_aed'
]
