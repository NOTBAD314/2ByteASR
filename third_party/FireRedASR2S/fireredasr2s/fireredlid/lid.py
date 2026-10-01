# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)
# Modified for 2ByteASR integration; notice added 2026-09-30.
# Changes relative to FireRedASR2S 4e7d9aaf4482a47cec1724807026b9b151926eb5:
# Restricted checkpoint loading with weights_only and explicit safe globals.
# Integration changes by the 2ByteASR project; not an upstream official release.
# Original copyright and Apache-2.0 license are retained.

import argparse
import os
import re
import time
import traceback
from dataclasses import dataclass

import torch

from .data.feat import FeatExtractor
from .models.fireredlid_aed import FireRedLidAed
from .models.param import count_model_parameters
from .tokenizer.lid_tokenizer import LidTokenizer


@dataclass
class FireRedLidConfig:
    use_gpu: bool = True
    use_half: bool = False


class FireRedLid:
    @classmethod
    def from_pretrained(cls, model_dir, config=FireRedLidConfig()):
        cmvn_path = os.path.join(model_dir, "cmvn.ark")
        feat_extractor = FeatExtractor(cmvn_path)

        model_path = os.path.join(model_dir, "model.pth.tar")
        dict_path =os.path.join(model_dir, "dict.txt")
        model = load_fireredlid_model(model_path)
        tokenizer = LidTokenizer(dict_path)

        count_model_parameters(model)
        model.eval()
        return cls(feat_extractor, model, tokenizer, config)

    def __init__(self, feat_extractor, model, tokenizer, config):
        self.feat_extractor = feat_extractor
        self.model = model
        self.tokenizer = tokenizer
        self.config = config
        self.config.beam_size = 3
        self.config.nbest = 1
        self.config.decode_max_len = 2
        self.config.softmax_smoothing = 1.25
        self.config.aed_length_penalty = 0.6
        self.config.eos_penalty = 1.0
        if self.config.use_gpu:
            if self.config.use_half:
                self.model.half()
            self.model.cuda()
        else:
            self.model.cpu()

    @torch.no_grad()
    def process(self, batch_uttid, batch_wav_path):
        batch_uttid_origin = batch_uttid
        try:
            feats, lengths, durs, batch_wav_path, batch_uttid = \
                self.feat_extractor(batch_wav_path, batch_uttid)
            if feats is None:
                return [{"uttid": uttid, "lang":""} for uttid in batch_uttid_origin]
        except:
            traceback.print_exc()
            return [{"uttid": uttid, "lang":""} for uttid in batch_uttid_origin]
        total_dur = sum(durs)
        if self.config.use_gpu:
            feats, lengths = feats.cuda(), lengths.cuda()
            if self.config.use_half:
                feats = feats.half()

        start_time = time.time()

        try:
            hyps = self.model.process(
                feats, lengths,
                self.config.beam_size,
                self.config.nbest,
                self.config.decode_max_len,
                self.config.softmax_smoothing,
                self.config.aed_length_penalty,
                self.config.eos_penalty
            )
        except Exception as e:
            traceback.print_exc()
            hyps = []

        elapsed = time.time() - start_time
        rtf= elapsed / total_dur if total_dur > 0 else 0

        results = []
        for uttid, wav, hyp, dur in zip(batch_uttid, batch_wav_path, hyps, durs):
            hyp = hyp[0]  # only return 1-best
            hyp_ids = [int(id) for id in hyp["yseq"].cpu()]
            text = self.tokenizer.detokenize(hyp_ids)
            results.append({"uttid": uttid, "lang": text,
                "confidence": round(hyp["confidence"].cpu().item(), 3),
                "dur_s": round(dur, 3), "rtf": f"{rtf:.4f}"})
            if type(wav) == str:
                results[-1]["wav"] = wav
        return results


def load_fireredlid_model(model_path):
    with torch.serialization.safe_globals([argparse.Namespace]):
        package = torch.load(
            model_path,
            map_location=lambda storage, loc: storage,
            weights_only=True,
        )
    #print(package["args"])
    model = FireRedLidAed.from_args(package["args"])
    model.load_state_dict(package["model_state_dict"], strict=False)
    return model
