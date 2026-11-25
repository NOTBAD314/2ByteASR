"""Local, duration-checked vocal separation for one explicitly selected clip."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

from ..runtime_paths import get_runtime_paths
from ..system.processes import popen_hidden_subprocess, stop_process_tree


SAMPLE_RATE = 44100
ASR_RATE = 16000
MAX_CLIP_SECONDS = 30
_CACHE_BYTES = 32 * 1024 * 1024
_TOOL_FILES = {
    "crispasr.exe": "d7e1109e956e98bbcc82eef6edbe27715b839a84cd6d83855ab294e4c803ca6c",
    "openblas.dll": "b134a7311569aa049a407a7bbaa0e70ec5c5f1c8067924a501baed2b58608c2a",
}
_CUDA_FILES = {
    "crispasr.dll": "6a9eb10d255bbd7efb66172080a75a0c59b252738237defe2d82259fd9d8357b",
    "crispasr.exe": "9b768855dabc5cb92736a2883f3ea9605e4cad02f99aeae189ef04e15269e71e",
    "cublas64_12.dll": "0a60a7ecbf906f7f3842826fecaf412f1587ff6269729339245a1ec224364161",
    "cublasLt64_12.dll": "a21ddfc1c9cd090ab07d2c6aad235aa4f15fe60fe896d5db28adf7a279c09ef3",
    "cudart64_12.dll": "9d9b868955149875ac4ef43442aaaa8913d4a7b3e4d6dd60ee871626aa045768",
    "ggml-base.dll": "346c289e9dc6a5b5782e350f46ee6704d4591059799ce65c1fe213238a0649be",
    "ggml-cpu.dll": "d6f5f02b4be82c6017cfcd5fca14a4ee13febe3cf2b81638d053d37287ad553b",
    "ggml-cuda.dll": "4bcc0d075f7bf97b15e3434e47149c07816ed5d8b9c486b77842d2e9b12887f6",
    "ggml.dll": "b63126e809abe491663a0cefc89cef2a3d373f5fe37f4bd9295895318e887b34",
    "whisper.dll": "6a9eb10d255bbd7efb66172080a75a0c59b252738237defe2d82259fd9d8357b",
}
_MODEL_NAME = "htdemucs-f16.gguf"
_MODEL_SHA256 = "4e7c4dcb8ac6315115848ff642ff8465f56b96d0a8ac7450be82acfc3534f006"


@dataclass(frozen=True, slots=True)
class EnhancedClip:
    path: Path
    cache_key: str
    backend: str


def _cache_path(key):
    return get_runtime_paths().cache_root / "studio-vocal-enhancement" / f"{key}.wav"


def cached_clip(key):
    if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
        return None
    path = _cache_path(key)
    try:
        _wav_samples(path, 1, ASR_RATE)
    except (OSError, ValueError, EOFError, wave.Error):
        return None
    return path


def _asset_paths():
    roots = get_runtime_paths()
    tools = roots.install_root / "tools"
    model = roots.model_root / "HTDemucs" / _MODEL_NAME
    return tools, model


def managed_tools_root(paths):
    return paths.user_data_root / "studio-audio-tools"


def _installed_tools(tools):
    managed = managed_tools_root(get_runtime_paths())
    for backend, folder, files in (("cuda", "crispasr-cuda", _CUDA_FILES),
                                  ("cpu", "crispasr", _TOOL_FILES)):
        for root in (managed, tools):
            path = root / folder
            if all((path / name).is_file() for name in files):
                yield backend, path, files


def assets_present():
    tools, model = _asset_paths()
    return os.name == "nt" and model.is_file() and next(_installed_tools(tools), None) is not None


def _check(cancel_check):
    if cancel_check and cancel_check():
        from ..recognition.service import CancelledError

        raise CancelledError()


def _sha256(path, cancel_check):
    fingerprint = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            _check(cancel_check)
            fingerprint.update(block)
    return fingerprint.hexdigest()


def _wav_samples(path, channels, rate):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (channels, 2, rate):
            raise ValueError("Unexpected PCM vocal enhancement format")
        frames = audio.getnframes()
        if not 0 < frames <= rate * MAX_CLIP_SECONDS:
            raise ValueError("Vocal enhancement clip exceeds the selected range limit")
        if len(audio.readframes(frames)) != frames * channels * 2:
            raise ValueError("Incomplete PCM vocal enhancement data")
        return frames


def waveform_peaks(path, bins=80):
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        frames, channels = audio.getnframes(), audio.getnchannels()
        pcm = np.frombuffer(audio.readframes(frames), dtype="<i2").astype(np.float32)
    envelope = np.abs(pcm.reshape(-1, channels)).max(axis=1) / 32768
    return tuple(float(samples.max()) for samples in np.array_split(envelope, min(bins, frames)))


def _run(command, purpose, cancel_check, *, cwd, timeout, **process_options):
    _check(cancel_check)
    process = popen_hidden_subprocess(command, purpose=purpose, log_command=[purpose], cwd=cwd,
                                     own_process_tree=True, **process_options)
    deadline = time.monotonic() + timeout
    try:
        while True:
            _check(cancel_check)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(purpose)
            try:
                code = process.wait(timeout=min(.2, remaining))
            except subprocess.TimeoutExpired:
                continue
            if code:
                raise RuntimeError(f"{purpose} (exit {code})")
            _check(cancel_check)
            return
    finally:
        if process.poll() is None:
            stop_process_tree(process)


def _matches_clock(path, expected):
    return abs(_wav_samples(path, 1, ASR_RATE) - expected) <= 1


def _copy_cached_audio(cache, output, expected):
    try:
        if not _matches_clock(cache, expected):
            return False
        shutil.copyfile(cache, output)
        return _matches_clock(output, expected)
    except (OSError, EOFError, ValueError, wave.Error):
        return False


def _cache_output(output, cache):
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="clip-", dir=cache.parent) as directory:
            staged = Path(directory) / "voice.wav"
            shutil.copyfile(output, staged)
            os.replace(staged, cache)
        items = []
        for item in cache.parent.glob("*.wav"):
            try:
                info = item.stat()
                items.append((info.st_mtime_ns, info.st_size, item))
            except OSError:
                continue
        remaining = _CACHE_BYTES
        for _, size, item in sorted(items, reverse=True):
            if size <= remaining:
                remaining -= size
            else:
                item.unlink(missing_ok=True)
    except OSError:
        pass


def enhance_studio_clip(original, target, ffmpeg_path, *, cancel_check=None):
    """Separate an exact 44.1 kHz stereo window and return a 16 kHz mono file.

    Source and output clocks must match to the output sample resolution.
    The caller owns both paths so it can clean them up with the recognition job.
    """
    original, target = Path(original).resolve(), Path(target).resolve()
    ffmpeg_path = str(Path(ffmpeg_path).resolve())
    if original == target:
        raise ValueError("Vocal enhancement requires its own output file")
    if not assets_present():
        raise FileNotFoundError("未安装受验证的本机 HTDemucs 人声增强模型")
    tools, model = _asset_paths()
    if _sha256(model, cancel_check) != _MODEL_SHA256:
        raise ValueError("人声增强模型完整性验证失败")
    source_frames = _wav_samples(original, 2, SAMPLE_RATE)
    expected = round(source_frames * ASR_RATE / SAMPLE_RATE)
    source_hash = _sha256(original, cancel_check)
    last_failure = None
    for backend, tool, files in _installed_tools(tools):
        unknown_libraries = {path.name.lower() for path in tool.glob("*.dll")} - {
            name.lower() for name in files if name.endswith(".dll")}
        try:
            if unknown_libraries or any(_sha256(tool / name, cancel_check) != digest for name, digest in files.items()):
                raise ValueError("人声增强工具完整性验证失败")
            key_prefix = "pcm-cuda-v1" if backend == "cuda" else "pcm-v1"
            key = hashlib.sha256(f"{key_prefix}:{_MODEL_SHA256}:{source_hash}".encode("ascii")).hexdigest()
            cache = _cache_path(key)
            with tempfile.TemporaryDirectory(prefix="htdemucs-", dir=target.parent) as directory:
                temporary = Path(directory)
                output = temporary / "voice-16k.wav"
                if not _copy_cached_audio(cache, output, expected):
                    stem = _separate(tool, model, backend, original, temporary, source_frames, cancel_check)
                    command = [ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                               "-i", str(stem), "-ac", "1", "-ar", str(ASR_RATE), "-c:a", "pcm_s16le", str(output)]
                    _run(command, "HTDemucs resample exact clip", cancel_check, cwd=directory, timeout=30)
                    if not _matches_clock(output, expected):
                        raise ValueError("增强人声重采样后与原音的样本长度不一致")
                    _cache_output(output, cache)
                _check(cancel_check)
                os.replace(output, target)
            return EnhancedClip(target, key if cache.is_file() else "", backend)
        except (OSError, ValueError, RuntimeError, wave.Error, EOFError) as error:
            _check(cancel_check)
            last_failure = error
    raise ValueError("本机人声增强没有生成有效音频") from last_failure


def _separate(tool, model, backend, original, temporary, source_frames, cancel_check):
    from ..system.processes import sanitized_child_environment

    command = [str(tool / "crispasr.exe"), "--separate", "-m", str(model), "-f", str(original),
               "--stems", "vocals", "--sep-output-dir", str(temporary)]
    cuda = backend == "cuda"
    env = sanitized_child_environment()
    env.update(CRISPASR_HTDEMUCS_GPU="1" if cuda else "0", CRISPASR_HTDEMUCS_GGML="1" if cuda else "0")
    if cuda:
        command.extend(("--gpu-backend", "cuda"))
    log_path = temporary / "backend.log"
    with log_path.open("wb") as log:
        _run(command, "HTDemucs vocal separation", cancel_check, cwd=str(tool),
             timeout=max(90, 18 * source_frames / SAMPLE_RATE), env=env, stderr=log, stdout=log)
    if cuda and not any(b"htdemucs: backend = CUDA" in line for line in log_path.read_bytes().splitlines()):
        raise RuntimeError("CUDA 人声增强未启用")
    stem = temporary / (original.stem + "_vocals.wav")
    if _wav_samples(stem, 2, SAMPLE_RATE) != source_frames:
        raise ValueError("增强人声与原音的样本长度不一致")
    return stem
