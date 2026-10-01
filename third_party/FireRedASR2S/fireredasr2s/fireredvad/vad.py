# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import logging
import os
from dataclasses import dataclass

import torch

from .core.audio_feat import AudioFeat
from .core.detect_model import DetectModel
from .core.vad_postprocessor import VadPostprocessor

logger = logging.getLogger(__name__)


@dataclass
class FireRedVadConfig:
    use_gpu: bool = False
    smooth_window_size: int = 5
    speech_threshold: float = 0.4
    min_speech_frame: int = 20
    max_speech_frame: int = 2000  # 20s
    min_silence_frame: int = 20
    merge_silence_frame: int = 0
    extend_speech_frame: int = 0
    chunk_max_frame: int = 30000  # 300s
    def __post_init__(self):
        if self.speech_threshold < 0 or self.speech_threshold > 1:
            raise ValueError("speech_threshold must be in [0, 1]")
        if self.min_speech_frame <= 0:
            raise ValueError("min_speech_frame must be positive")



class FireRedVad:
    @classmethod
    def from_pretrained(cls, model_dir, config=FireRedVadConfig()):
        # Build Feat Extractor
        cmvn_path = os.path.join(model_dir, "cmvn.ark")
        audio_feat = AudioFeat(cmvn_path)

        # Build Model
        vad_model = DetectModel.from_pretrained(model_dir)
        if config.use_gpu:
            vad_model.cuda()
        else:
            vad_model.cpu()

        # Build Postprocessor
        vad_postprocessor = VadPostprocessor(
            config.smooth_window_size,
            config.speech_threshold,
            config.min_speech_frame,
            config.max_speech_frame,
            config.min_silence_frame,
            config.merge_silence_frame,
            config.extend_speech_frame)
        return cls(audio_feat, vad_model, vad_postprocessor, config)

    def __init__(self, audio_feat, vad_model, vad_postprocessor, config):
        self.audio_feat = audio_feat
        self.vad_model = vad_model
        self.vad_postprocessor = vad_postprocessor
        self.config = config

    def detect(self, audio, do_postprocess=True):
        # Extract feat
        feats, dur = self.audio_feat.extract(audio)
        if self.config.use_gpu:
            feats = feats.cuda()

        # Model inference
        if feats.size(0) <= self.config.chunk_max_frame:
            probs, _ = self.vad_model.forward(feats.unsqueeze(0))
            probs = probs.cpu().squeeze()  # (T,)
        else:
            logger.warning(f"Too long input, split every {self.config.chunk_max_frame} frames")
            chunk_probs = []
            chunks = feats.split(self.config.chunk_max_frame, dim=0)
            for chunk in chunks:
                chunk_prob, _ = self.vad_model.forward(chunk.unsqueeze(0))
                chunk_probs.append(chunk_prob.cpu())
            probs = torch.cat(chunk_probs, dim=1)
            probs = probs.squeeze()  # (T,)

        if not do_postprocess:
            return None, probs

        # Prob Postprocess
        decisions = self.vad_postprocessor.process(probs.tolist())
        starts_ends_s = self.vad_postprocessor.decision_to_segment(decisions, dur)

        # Format result
        result = {"dur": round(dur, 3),
                  "timestamps": starts_ends_s}
        if isinstance(audio, str):
            result["wav_path"] = audio
        return result, probs
