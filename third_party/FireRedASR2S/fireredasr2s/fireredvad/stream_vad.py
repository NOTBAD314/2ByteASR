# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import logging
import os
from dataclasses import dataclass
from typing import List, Tuple, Union

import torch
import numpy as np

from .core.constants import FRAME_LENGTH_SAMPLE, FRAME_PER_SECONDS
from .core.audio_feat import AudioFeat
from .core.detect_model import DetectModel
from .core.stream_vad_postprocessor import StreamVadPostprocessor, StreamVadFrameResult

logger = logging.getLogger(__name__)


@dataclass
class FireRedStreamVadConfig:
    use_gpu: bool = False
    smooth_window_size: int = 5
    speech_threshold: float = 0.5
    pad_start_frame : int = 5
    min_speech_frame: int = 8
    max_speech_frame: int = 2000  # 20s
    min_silence_frame: int = 20
    chunk_max_frame: int = 30000  # 300s
    def __post_init__(self):
        if self.speech_threshold < 0 or self.speech_threshold > 1:
            raise ValueError("speech_threshold must be in [0, 1]")
        if self.min_speech_frame <= 0:
            raise ValueError("min_speech_frame must be positive")



class FireRedStreamVad:
    @classmethod
    def from_pretrained(cls, model_dir, config=FireRedStreamVadConfig()):
        # Feat
        cmvn_path = os.path.join(model_dir, "cmvn.ark")
        feat_extractor = AudioFeat(cmvn_path)

        # Load & Build Model
        vad_model = DetectModel.from_pretrained(model_dir)
        if config.use_gpu:
            vad_model.cuda()
        else:
            vad_model.cpu()

        # Build Postprocessor
        postprocessor = StreamVadPostprocessor(
            config.smooth_window_size,
            config.speech_threshold,
            config.pad_start_frame,
            config.min_speech_frame,
            config.max_speech_frame,
            config.min_silence_frame)
        return cls(feat_extractor, vad_model, postprocessor, config)

    def __init__(self, audio_feat, vad_model, postprocessor, config):
        self.audio_feat = audio_feat
        self.vad_model = vad_model
        self.postprocessor = postprocessor
        self.config = config
        self.model_caches = None

    def reset(self):
        self.model_caches = None
        self.audio_feat.reset()
        self.postprocessor.reset()

    def detect_frame(self, audio_frame: np.ndarray) -> StreamVadFrameResult:
        if len(audio_frame) != FRAME_LENGTH_SAMPLE:
            raise ValueError(f"Expected {FRAME_LENGTH_SAMPLE} samples, got {len(audio_frame)}")

        feat, dur = self.audio_feat.extract(audio_frame)
        if self.config.use_gpu:
            feat = feat.cuda()

        prob, self.model_caches = self.vad_model.forward(
            feat.unsqueeze(0), caches=self.model_caches)
        raw_prob = prob.cpu().squeeze().tolist()

        frame_result = self.postprocessor.process_one_frame(raw_prob)
        return frame_result

    def detect_chunk(self, audio_chunk: np.ndarray) -> List[StreamVadFrameResult]:
        feats, dur = self.audio_feat.extract(audio_chunk)
        if self.config.use_gpu:
            feats = feats.cuda()

        probs, self.model_caches = self.vad_model.forward(
            feats.unsqueeze(0), caches=self.model_caches)
        raw_probs = probs.cpu().squeeze().tolist()
        if isinstance(raw_probs, float):
            raw_probs = [raw_probs]

        chunk_results = []
        for t, raw_prob in enumerate(raw_probs):
            stream_vad_frame_result = self.postprocessor.process_one_frame(raw_prob)
            chunk_results.append(stream_vad_frame_result)
        return chunk_results

    def detect_full(self, audio: Union[str, np.ndarray]) -> Tuple[List[StreamVadFrameResult], dict]:
        self.reset()
        feats, dur = self.audio_feat.extract(audio)
        if self.config.use_gpu:
            feats = feats.cuda()

        if feats.size(0) <= self.config.chunk_max_frame:
            probs, _ = self.vad_model.forward(feats.unsqueeze(0))
        else:
            logger.warning(f"Too long input, split every {self.config.chunk_max_frame} frames")
            chunk_probs = []
            chunks = feats.split(self.config.chunk_max_frame, dim=0)
            for chunk in chunks:
                chunk_prob, _ = self.vad_model.forward(chunk.unsqueeze(0))
                chunk_probs.append(chunk_prob)
            probs = torch.cat(chunk_probs, dim=1)
            probs = probs.squeeze()  # (T,)
        raw_probs = probs.cpu().squeeze().tolist()  # (T,)
        if isinstance(raw_probs, float):
            raw_probs = [raw_probs]

        frame_results = []
        for t, raw_prob in enumerate(raw_probs):
            stream_vad_frame_result = self.postprocessor.process_one_frame(raw_prob)
            frame_results.append(stream_vad_frame_result)
        self.reset()

        # Format result
        timestamps = self.results_to_timestamps(frame_results)
        result = {"dur": round(dur, 3),
                  "timestamps": timestamps}
        if isinstance(audio, str):
            result["wav_path"] = audio
        return frame_results, result

    def set_mode(self, mode: int = 0):
        if mode == 0:    # VERY PERMISSIVE
            self.config.speech_threshold = 0.3
            self.config.min_speech_frame = 8
            self.config.min_silence_frame = 20
        elif mode == 1:  # PERMISSIVE
            self.config.speech_threshold = 0.5
            self.config.min_speech_frame = 10
            self.config.min_silence_frame = 15
        elif mode == 2:  # AGGRESSIVE
            self.config.speech_threshold = 0.7
            self.config.min_speech_frame = 15
            self.config.min_silence_frame = 10
        elif mode == 3:  # VERY_AGGRESSIVE
            self.config.speech_threshold = 0.9
            self.config.min_speech_frame = 20
            self.config.min_silence_frame = 5
        self.postprocessor.speech_threshold = self.config.speech_threshold
        self.postprocessor.min_speech_frame = self.config.min_speech_frame
        self.postprocessor.min_silence_frame = self.config.min_silence_frame

    @classmethod
    def results_to_timestamps(cls, results):
        results = sorted(results, key=lambda r: r.frame_idx)
        # Get frame index (0-based)
        frame_timestamps = []
        start, end = -1, -1
        for r in results:
            if r.is_speech_start:
                if start != -1: logger.warning("start should be -1")
                start = max(0, r.speech_start_frame - 1)
                end = -1
            elif r.is_speech_end:
                assert end == -1
                end = max(0, r.speech_end_frame - 1)
                frame_timestamps.append((start, end))
                start, end = -1, -1
        if start != -1:
            assert end == -1
            end = results[-1].frame_idx - 1
            frame_timestamps.append((start, end))
        # Convert to seconds
        timestamps = []
        for s, e in frame_timestamps:
            timestamps.append((s/FRAME_PER_SECONDS, e/FRAME_PER_SECONDS))
        return timestamps
