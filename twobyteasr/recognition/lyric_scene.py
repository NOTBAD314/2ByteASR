"""Local selected-window song evidence. It never authors subtitle timings."""
import hashlib
import math
from pathlib import Path
import sys

import numpy as np


MODEL_SHA256 = "10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de"
MODEL_SIZE = 4_126_810
_CLASS_IDS = ((24, 25, 26, 32, 29), (0, 2, 3), (132, 133))
_MEAN = np.array([.030078125, .4786458333333333, .3165364583333333, .06546875,
                  .5605989583333334, .33677083333333335, .6408463645457605,
                  .37238164502996024, .6921022980064503, .10402208666006724])
_SCALE = np.array([.07642619137353754, .44101745106525797, .44610359342856504,
                   .1389513249419559, .4498354884714723, .4533840151112742,
                   .17917719812996702, .19846316719288776, .16731235839625744,
                   .06427631815399884])
_WEIGHT = np.array([.16205984384716585, -.40793913875103754, .16328663801498486,
                    .1886835185984839, -.23669312890502675, .15551426513757907,
                    .5626011395854139, .9923740314734208, .584585225135709, .8733755423828025])
_BIAS = .06849104864126516


def _pitch_statistics(pcm):
    frames = np.lib.stride_tricks.sliding_window_view(pcm, 1024)[::400].astype(np.float32)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    power = np.abs(np.fft.rfft(frames * np.hanning(1024), n=2048, axis=1)) ** 2
    correlation = np.fft.irfft(power, n=2048, axis=1)
    band = correlation[:, 42:270] / np.maximum(1.e-8, correlation[:, :1])
    lag = np.argmax(band, axis=1) + 42
    strength = band.max(axis=1)
    voiced = (rms > .004) & (strength > .4)
    stable = (np.abs(np.diff(np.log2(lag))) < .035) & voiced[1:] & voiced[:-1]
    return [np.mean(voiced), np.mean(stable), np.quantile(strength, .75), float(rms.mean())]


def managed_runtime_directory(paths):
    return paths.user_data_root / "studio-audio-tools" / "litert-2.2.0"


def detect_selected_song(pcm, model_path, runtime=None):
    if len(pcm) < 16000 or len(pcm) > 30 * 16000 or not np.isfinite(pcm).all():
        raise ValueError("请选择一到三十秒的有效音频")
    payload = Path(model_path)
    with payload.open("rb") as source:
        model = source.read(MODEL_SIZE + 1)
    if len(model) != MODEL_SIZE or hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        raise ValueError("歌唱检测模型完整性验证失败")
    if runtime is not None and runtime.is_dir():
        sys.path.insert(1, str(runtime))
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError as exc:
        raise ValueError("请在本机识别环境安装 LiteRT 后再检测歌唱") from exc
    runner = Interpreter(model_content=model, num_threads=2)
    runner.allocate_tensors()
    source = runner.get_input_details()[0]["index"]
    target = runner.get_output_details()[0]["index"]
    edges = np.pad(pcm, (7800, 7800))
    observations = []
    for at in range(0, len(pcm), 9600):
        runner.set_tensor(source, np.asarray(edges[at:at + 15600], dtype=np.float32))
        runner.invoke()
        scores = runner.get_tensor(target)[0]
        observations.append([float(scores[list(indices)].max()) for indices in _CLASS_IDS])
    scores = np.asarray(observations)
    summary = np.concatenate((np.median(scores, axis=0), np.percentile(scores, 90, axis=0),
                              _pitch_statistics(pcm)))
    logits = float(((summary - _MEAN) / _SCALE) @ _WEIGHT + _BIAS)
    evidence = 1. / (1. + math.exp(-min(50., max(-50., logits))))
    return dict(result="possible_song" if evidence >= .8 else "insufficient_evidence",
                evidence=round(evidence, 4), windows=len(observations))
