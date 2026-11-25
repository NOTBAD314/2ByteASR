"""Forced alignment for lyrics on a user-selected singing window."""
from __future__ import annotations

import re
import unicodedata

import numpy as np


SAMPLE_RATE = 16000
FRAME_MS = 20
MAX_SECONDS = 30
_SHA256 = "bc8d8e504eabec5538027623b376e3f560691c2fb134c1a8fc6081bd10e86716"
_CONFIGS = {
    "config.json": "b1c416b5f172db84aee2cfca5c8224d35993989c74d82a68d3c80815f8dc661f",
    "preprocessor_config.json": "9c6008e1229e6914e5c11df2f673c3a0af5fd6ad442426a4b4eb3a4c11d78264",
    "vocab.json": "2d9fa2ffb8a0b24ddc33cd30b6a7217dcda08a0a55115d50df9cd9ee23aae6ff",
}


def _terms(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("\u2019", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", value)


def _encode(lines, vocabulary):
    tokens, groups = [], []
    delimiter = int(vocabulary["|"])
    for line in lines:
        intervals = []
        for word in _terms(line):
            if tokens:
                tokens.append(delimiter)
            first = len(tokens)
            for char in word:
                token = next((vocabulary[variant] for variant in (char, char.lower(), char.upper())
                              if variant in vocabulary), None)
                if token is None:
                    raise ValueError("歌词含当前模型不支持的文字")
                tokens.append(int(token))
            intervals.append((first, len(tokens)))
        if not intervals:
            raise ValueError("歌词行内缺少可对齐文字")
        groups.append(intervals)
    return np.asarray(tokens, dtype=np.intp), groups


def ctc_path(log_probabilities, targets, blank):
    """Monotone Viterbi alignment. Repeated tokens require a blank between them."""
    if len(targets) == 0 or len(targets) > len(log_probabilities):
        return None
    states = np.full(2 * len(targets) + 1, blank, dtype=np.intp)
    states[1::2] = targets
    skip = np.zeros(len(states), dtype=bool)
    skip[2:] = (states[2:] != blank) & (states[2:] != states[:-2])
    scores = np.full(len(states), -np.inf, dtype=np.float64)
    scores[0] = 0
    moves = np.empty((len(log_probabilities), len(states)), dtype=np.uint8)
    for index, frame in enumerate(log_probabilities):
        step = np.pad(scores[:-1], (1, 0), constant_values=-np.inf)
        jump = np.where(skip, np.pad(scores[:-2], (2, 0), constant_values=-np.inf), -np.inf)
        choices = np.stack((scores, step, jump))
        moves[index] = choices.argmax(axis=0)
        scores = choices.max(axis=0) + frame[states]
    ending = len(states) - (1 if scores[-1] >= scores[-2] else 2)
    if not np.isfinite(scores[ending]):
        return None
    path = np.empty(len(log_probabilities), dtype=np.intp)
    for index in range(len(path) - 1, -1, -1):
        path[index] = ending
        ending -= int(moves[index, ending])
    return path


def measure_lines(log_probabilities, lines, vocabulary, duration_ms):
    """Return only evidence-backed provisional word and line positions."""
    blank = int(vocabulary["<blank>"])
    targets, groups = _encode(lines, vocabulary)
    if not len(log_probabilities) or len(targets) > 1500:
        raise ValueError("歌词超出局部音频可对齐范围")
    path = ctc_path(log_probabilities, targets, blank)
    if path is None:
        raise ValueError("没有找到可用的歌词对齐路径")
    rows = []
    posterior = []
    for text, intervals in zip(lines, groups):
        words = []
        for first, last in intervals:
            frames = np.flatnonzero((path >= first * 2 + 1) & (path <= (last - 1) * 2 + 1) & (path % 2 == 1))
            if not len(frames):
                raise ValueError("部分歌词未获得可验证的发音位置")
            start = int(frames[0]) * FRAME_MS
            end = min(duration_ms, (int(frames[-1]) + 1) * FRAME_MS)
            if end <= start:
                raise ValueError("歌词位置超出局部音频")
            probabilities = np.exp(log_probabilities[frames, targets[(path[frames] - 1) // 2]])
            confidence = float(probabilities.mean())
            words.append(dict(start_ms=start, end_ms=end, posterior=round(confidence, 4)))
            posterior.append(confidence)
        rows.append(dict(text=text, start_ms=words[0]["start_ms"], end_ms=words[-1]["end_ms"], words=words))
    if (not np.isfinite(posterior).all() or float(np.median(posterior)) < .25
            or sum(value >= .08 for value in posterior) < .9 * len(posterior)):
        raise ValueError("唱词证据不足，请核对选区及歌词")
    return rows


def run_alignment(audio, model_dir, lines):
    """Use standard Transformers weights locally, with no model-supplied code."""
    import hashlib
    import json
    from pathlib import Path

    import torch
    from transformers import SeamlessM4TFeatureExtractor, Wav2Vec2BertForCTC

    model_dir = Path(model_dir)
    config = {name: (model_dir / name).read_bytes() for name in _CONFIGS}
    if any(hashlib.sha256(config[name]).hexdigest() != expected for name, expected in _CONFIGS.items()):
        raise ValueError("歌词模型配置完整性验证失败")
    digest = hashlib.sha256()
    with (model_dir / "model.safetensors").open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != _SHA256:
        raise ValueError("歌词模型完整性验证失败")
    if not 0 < len(audio) <= SAMPLE_RATE * MAX_SECONDS:
        raise ValueError("局部歌詞處理限 30 秒以內")
    if not np.isfinite(audio).all() or float(np.max(np.abs(audio))) < .001:
        raise ValueError("局部音频缺少可用于歌词的声音")
    vocab = json.loads(config["vocab.json"])
    _encode(lines, vocab)  # Fail early before loading GPU weights.
    torch.set_num_threads(2)
    processor = SeamlessM4TFeatureExtractor.from_pretrained(model_dir, local_files_only=True)
    model = Wav2Vec2BertForCTC.from_pretrained(model_dir, local_files_only=True, use_safetensors=True).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    inputs = {name: tensor.to(device) for name, tensor in
              processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").items()}
    with torch.inference_mode():
        logits = model(**inputs).logits[0].float().log_softmax(-1).cpu().numpy()
    return measure_lines(logits, lines, vocab, len(audio) * 1000 // SAMPLE_RATE)
