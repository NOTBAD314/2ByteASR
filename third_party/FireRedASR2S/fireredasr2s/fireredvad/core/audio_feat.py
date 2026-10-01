# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import math
import os

import soundfile as sf
import kaldiio
import kaldi_native_fbank as knf
import numpy as np
import torch


class AudioFeat:
    def __init__(self, kaldi_cmvn_file):
        self.cmvn = CMVN(kaldi_cmvn_file) if kaldi_cmvn_file != "" else None
        self.fbank = KaldifeatFbank(num_mel_bins=80, frame_length=25,
            frame_shift=10, dither=0)

    def reset(self):
        pass

    def extract(self, audio):
        if isinstance(audio, str):
            wav_np, sample_rate = sf.read(audio, dtype="int16")
        elif isinstance(audio, (list, tuple)):
            wav_np, sample_rate = audio
        else:
            wav_np = audio
            sample_rate = 16000
        assert sample_rate == 16000

        dur = wav_np.shape[0] / sample_rate
        fbank = self.fbank((sample_rate, wav_np))
        if self.cmvn is not None:
            fbank = self.cmvn(fbank)
        feat = torch.from_numpy(fbank).float()
        return feat, dur



class CMVN:
    def __init__(self, kaldi_cmvn_file):
        self.dim, self.means, self.inverse_std_variances = \
            self.read_kaldi_cmvn(kaldi_cmvn_file)

    def __call__(self, x, is_train=False):
        assert x.shape[-1] == self.dim, "CMVN dim mismatch"
        out = x - self.means
        out = out * self.inverse_std_variances
        return out

    def read_kaldi_cmvn(self, kaldi_cmvn_file):
        assert os.path.exists(kaldi_cmvn_file)
        stats = kaldiio.load_mat(kaldi_cmvn_file)
        assert stats.shape[0] == 2
        dim = stats.shape[-1] - 1
        count = stats[0, dim]
        assert count >= 1
        floor = 1e-20
        means = []
        inverse_std_variances = []
        for d in range(dim):
            mean = stats[0, d] / count
            means.append(mean.item())
            variance = (stats[1, d] / count) - mean * mean
            if variance < floor:
                variance = floor
            istd = 1.0 / math.sqrt(variance)
            inverse_std_variances.append(istd)
        return dim, np.array(means), np.array(inverse_std_variances)



class KaldifeatFbank:
    def __init__(self, num_mel_bins=80, frame_length=25, frame_shift=10,
                 dither=0):
        self.dither = dither
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = 16000
        opts.frame_opts.frame_length_ms = 25
        opts.frame_opts.frame_shift_ms = 10
        opts.frame_opts.dither = dither
        opts.frame_opts.snip_edges = True
        opts.mel_opts.num_bins = num_mel_bins
        opts.mel_opts.debug_mel = False
        self.opts = opts

    def __call__(self, wav, is_train=False):
        if isinstance(wav, str):
            wav_np, sample_rate = sf.read(wav, dtype="int16")
        elif isinstance(wav, (tuple, list)) and len(wav) == 2:
            sample_rate, wav_np = wav
        assert len(wav_np.shape) == 1

        dither = self.dither if is_train else 0.0
        self.opts.frame_opts.dither = dither
        fbank = knf.OnlineFbank(self.opts)

        fbank.accept_waveform(sample_rate, wav_np.tolist())
        feat = []
        for i in range(fbank.num_frames_ready):
            feat.append(fbank.get_frame(i))
        if len(feat) == 0:
            return np.zeros((0, self.opts.mel_opts.num_bins))
        feat = np.vstack(feat)
        return feat
