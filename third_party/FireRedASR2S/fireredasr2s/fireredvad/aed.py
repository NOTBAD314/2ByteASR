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
class FireRedAedConfig:
    use_gpu: bool = False
    smooth_window_size: int = 5
    speech_threshold: float = 0.4
    singing_threshold: float = 0.5
    music_threshold: float = 0.5
    min_event_frame: int = 20
    max_event_frame: int = 2000  # 20s
    min_silence_frame: int = 20
    merge_silence_frame: int = 0
    extend_speech_frame: int = 0
    chunk_max_frame: int = 30000  # 300s


class FireRedAed:
    IDX2EVENT = {0: "speech", 1: "singing", 2: "music"}

    @classmethod
    def from_pretrained(cls, model_dir, config=FireRedAedConfig()):
        # Build Feat Extractor
        cmvn_path = os.path.join(model_dir, "cmvn.ark")
        audio_feat = AudioFeat(cmvn_path)

        # Build Model
        model = DetectModel.from_pretrained(model_dir)
        if config.use_gpu:
            model.cuda()
        else:
            model.cpu()

        # Build Postprocessor
        event2postprocessor = {}
        for event in cls.IDX2EVENT.values():
            threshold = getattr(config, f"{event}_threshold")
            event2postprocessor[event] = VadPostprocessor(
                config.smooth_window_size,
                threshold,
                config.min_event_frame,
                config.max_event_frame,
                config.min_silence_frame,
                config.merge_silence_frame,
                config.extend_speech_frame)
        return cls(audio_feat, model, event2postprocessor, config)

    def __init__(self, audio_feat, model, event2postprocessor, config):
        self.audio_feat = audio_feat
        self.model = model
        self.event2postprocessor = event2postprocessor
        self.config = config

    def detect(self, audio):
        # Extract feat
        feat, dur = self.audio_feat.extract(audio)
        if self.config.use_gpu:
            feat = feat.cuda()

        # Model inference
        if feat.size(0) <= self.config.chunk_max_frame:
            probs, _ = self.model.forward(feat.unsqueeze(0))
            assert probs.size(-1) == len(self.IDX2EVENT)
            probs = probs.cpu().squeeze(0)  # (T,3)
        else:
            logger.warning(f"Too long input, split every {self.config.chunk_max_frame} frames")
            chunk_probs = []
            chunks = feat.split(self.config.chunk_max_frame, dim=0)
            for chunk in chunks:
                chunk_prob, _ = self.model.forward(chunk.unsqueeze(0))
                assert chunk_prob.size(-1) == len(self.IDX2EVENT)
                chunk_probs.append(chunk_prob.cpu())
            probs = torch.cat(chunk_probs, dim=1)
            probs = probs.squeeze(0)  # (T,3)

        # Prob Postprocess
        event2starts_ends_s = {}
        event2raw_ratio = {}
        for idx, event in self.IDX2EVENT.items():
            threshold = getattr(self.config, f"{event}_threshold")
            postprocessor = self.event2postprocessor[event]
            event_probs = probs[:, idx].tolist()
            decision = postprocessor.process(event_probs)
            starts_ends_s = postprocessor.decision_to_segment(decision, dur)
            event2starts_ends_s[event] = starts_ends_s

            raw_ratio = sum(int(p>= threshold) for p in event_probs) / len(event_probs) if len(event_probs) else 0
            event2raw_ratio[event] = round(raw_ratio, 3)

        # Format result
        result = {"dur": round(dur, 3),
                  "event2timestamps": event2starts_ends_s,
                  "event2ratio": event2raw_ratio}
        if isinstance(audio, str):
            result["wav_path"] = audio
        return result, probs
