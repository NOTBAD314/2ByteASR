"""Run MOSS-Transcribe-Diarize in its isolated Transformers 5 environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import copy
import gc
import threading
from collections import Counter
from pathlib import Path


DEFAULT_PROMPT = (
    "请将音频转写为文本，每一段需以起始时间戳和说话人编号"
    "（[S01]、[S02]、[S03]…）开头，正文为对应的语音内容，"
    "并在段末标注结束时间戳，以清晰标明该段语音范围。"
)

# Application metadata, never passed as invented model.generate parameters.
INFERENCE_MODE = "full_context"
CACHE_VERSION = "moss-full-context-v1"
PROMPT_VERSION = "native-transcript-v1"
GENERATION_POLICY = {"tokens_per_second": 24, "minimum_output_tokens": 2048,
                     "context_reserve": 32, "do_sample": False,
                     "encoder_batch_size": 2, "oom_retries": 1}


def generation_budget(duration, input_tokens, context_limit):
    requested = max(GENERATION_POLICY["minimum_output_tokens"], math.ceil(duration * GENERATION_POLICY["tokens_per_second"]))
    available = int(context_limit) - int(input_tokens) - GENERATION_POLICY["context_reserve"]
    if available < GENERATION_POLICY["minimum_output_tokens"]:
        raise ValueError(f"整段输入上下文容量不足：input_tokens={input_tokens}, context_limit={context_limit}, available_output={available}")
    return min(requested, available), requested


def ending_assessment(generated_tokens, budget, last_token, eos_ids):
    eos_ids = eos_ids if isinstance(eos_ids, (list, tuple)) else [eos_ids]
    if generated_tokens >= budget:
        return "token_limit", False
    if generated_tokens and last_token in eos_ids:
        return "eos", True
    return "unexpected_stop", False


def audio_fingerprint(audio, sample_rate):
    import numpy as np
    digest = hashlib.sha256(f"float32-mono:{int(sample_rate)}:".encode())
    # Bound scratch memory while hashing the complete ordered task waveform.
    for start in range(0, len(audio), 1024 * 1024):
        digest.update(np.asarray(audio[start:start + 1024 * 1024], dtype="<f4").tobytes())
    return digest.hexdigest()


class ExecutionProgress:
    def __init__(self):
        self.started = time.monotonic()
        self.last_activity = self.started
        self.phase = "audio_preparation"
        self.phase_started = self.started
        self.phase_seconds = {}
        self.tokens = 0
        self.first_token_seconds = None
        self.prompt_tokens = 0
        self.cuda_ready = False
        self._rate_mark = (self.started, 0)
        self.stop = threading.Event()

    def device_memory(self):
        """Measured VRAM: device-wide free/total and this process's allocator."""
        if not self.cuda_ready:
            return {}
        try:
            import torch
            free, total = torch.cuda.mem_get_info()
            return {"vram_free_gb": round(free / 1024**3, 3), "vram_total_gb": round(total / 1024**3, 3),
                    "allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 3),
                    "reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 3)}
        except Exception:
            return {}

    def emit(self, *, activity=True, **fields):
        if activity:
            self.last_activity = time.monotonic()
        row = {"phase": self.phase, "elapsed_seconds": round(time.monotonic() - self.started, 3),
               "last_activity_elapsed_seconds": round(self.last_activity - self.started, 3),
               "generated_tokens": self.tokens, "progress_percent": None, **fields}
        print("MOSS_EVENT " + json.dumps(row, ensure_ascii=False), flush=True)

    def set_phase(self, phase):
        now = time.monotonic()
        self.phase_seconds[self.phase] = round(self.phase_seconds.get(self.phase, 0.0) + now - self.phase_started, 3)
        self.phase, self.phase_started = phase, now
        if phase == "generation":
            self._rate_mark = (now, self.tokens)
        self.emit(**self.device_memory())

    def heartbeat(self):
        while not self.stop.wait(10):
            now, tokens = time.monotonic(), self.tokens
            fields = self.device_memory()
            if self.phase == "generation" and self.first_token_seconds is not None:
                mark_time, mark_tokens = self._rate_mark
                # Measured decode throughput of the last interval, counted
                # from the first generated token (prefill is reported apart).
                fields["tokens_per_second"] = round((tokens - mark_tokens) / max(1e-6, now - mark_time), 2)
                fields["context_tokens"] = self.prompt_tokens + tokens
                self._rate_mark = (now, tokens)
            elif self.phase == "generation":
                fields["prefill_running"] = True
            self.emit(activity=False, heartbeat=True, **fields)


def install_prefill_attention_policy(model, dtype, receipt):
    """Keep long prefills off PyTorch's quadratic MATH attention kernel.

    Transformers passes ``enable_gqa=True`` to SDPA for grouped-query layers.
    When neither FLASH nor EFFICIENT supports that on the device (measured on
    an RTX 5070 Ti / sm_120 with torch 2.11: only MATH would run it), a 9k-token
    prefill materialises a 16 x 9077 x 9077 score tensor (11.6 GB). Expanding
    the KV heads for the prefill only lets the efficient causal kernel run the
    identical attention; single-token decode steps are unchanged.
    """
    import torch
    import torch.nn.functional as F
    text = model.config.text_config
    heads = int(text.num_attention_heads)
    groups = heads // max(1, int(getattr(text, "num_key_value_heads", heads) or heads))
    head_dim = int(getattr(text, "head_dim", 0) or text.hidden_size // heads)
    policy = {"kv_groups": groups, "head_dim": head_dim, "fused_gqa_kernel": None, "prefill_kv_expanded": False}
    receipt["attention_policy"] = policy
    if groups <= 1:
        return policy
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel
        query = torch.zeros(1, groups * 2, 64, head_dim, device="cuda", dtype=dtype)
        kv = torch.zeros(1, 2, 64, head_dim, device="cuda", dtype=dtype)
        with sdpa_kernel([SDPBackend.FLASH_ATTENTION, SDPBackend.EFFICIENT_ATTENTION]):
            F.scaled_dot_product_attention(query, kv, kv, is_causal=True, enable_gqa=True)
        policy["fused_gqa_kernel"] = True
        return policy
    except RuntimeError:
        policy["fused_gqa_kernel"] = False
    try:
        from transformers import AttentionInterface
        import transformers.integrations.sdpa_attention as sdpa
        original_use, original_forward = sdpa.use_gqa_in_sdpa, sdpa.sdpa_attention_forward
    except (ImportError, AttributeError) as exc:
        policy["unpatched_reason"] = f"{type(exc).__name__}: {exc}"
        return policy
    prefill = threading.local()

    def use_gqa_in_sdpa(attention_mask, key, value):
        return False if getattr(prefill, "active", False) else original_use(attention_mask, key, value)

    def sdpa_attention_forward(module, query, key, value, attention_mask, **kwargs):
        prefill.active = query.shape[2] > 1
        try:
            return original_forward(module, query, key, value, attention_mask, **kwargs)
        finally:
            prefill.active = False

    sdpa.use_gqa_in_sdpa = use_gqa_in_sdpa
    AttentionInterface.register("sdpa", sdpa_attention_forward)
    policy["prefill_kv_expanded"] = True
    return policy


def install_decode_attention(model, receipt):
    """Single-token decode steps without expanding the KV cache.

    With ``enable_gqa=True`` SDPA has no FLASH/EFFICIENT kernel on sm_120 and
    falls back to MATH, which repeats every layer's whole KV cache per token
    (86% of decode GPU time at an 18.7k context, measured 2026-10-12). For
    q_len=1 the two query heads of each KV group are folded into the query
    length and attention is two batched matmuls with an fp32 softmax: the
    arithmetic of Transformers' "eager" attention, minus the repeat_kv copy.
    Prefill (q_len>1), masks and other calls keep the registered SDPA path.
    """
    import torch
    from transformers import AttentionInterface
    current = AttentionInterface._global_mapping["sdpa"]
    counts = {"folded_decode_calls": 0, "sdpa_calls": 0}
    policy = receipt.setdefault("attention_policy", {})
    policy.update(decode="gqa_fold_bmm_fp32_softmax", decode_counts=counts)

    def sdpa_attention_forward(module, query, key, value, attention_mask, dropout=0.0, scaling=None,
                               is_causal=None, **kwargs):
        groups = int(getattr(module, "num_key_value_groups", 1) or 1)
        if (groups > 1 and query.shape[2] == 1 and attention_mask is None and not dropout
                and kwargs.get("position_bias") is None and not kwargs.get("output_attentions")):
            batch, heads, _, dim = query.shape
            folded = query.reshape(batch, key.shape[1], groups, dim)
            scale = scaling if scaling is not None else dim ** -0.5
            scores = torch.matmul(folded, key.transpose(-1, -2)) * scale
            probs = torch.softmax(scores, dim=-1, dtype=torch.float32).to(query.dtype)
            counts["folded_decode_calls"] += 1
            return torch.matmul(probs, value).reshape(batch, 1, heads, dim), None
        counts["sdpa_calls"] += 1
        return current(module, query, key, value, attention_mask, dropout=dropout, scaling=scaling,
                       is_causal=is_causal, **kwargs)

    AttentionInterface.register("sdpa", sdpa_attention_forward)
    return policy


def growing_kv_cache(model, capacity):
    """DynamicCache whose layers write into preallocated buffers.

    The default layer concatenates the whole cache on every token (O(context)
    copies per step). Buffers grow by 25% only if the estimate is exceeded.
    """
    import torch
    from transformers.cache_utils import DynamicCache, DynamicLayer

    class GrowingLayer(DynamicLayer):
        def __init__(self, capacity):
            super().__init__()
            self.capacity = int(capacity)
            self.length = 0

        def lazy_initialization(self, key_states, value_states):
            self.dtype, self.device = key_states.dtype, key_states.device
            batch, heads, _, dim = key_states.shape
            self._keys = torch.empty(batch, heads, self.capacity, dim, dtype=self.dtype, device=self.device)
            self._values = torch.empty(batch, heads, self.capacity, dim, dtype=self.dtype, device=self.device)
            self.keys, self.values = self._keys[:, :, :0], self._values[:, :, :0]
            self.is_initialized = True

        def update(self, key_states, value_states, *args, **kwargs):
            if not self.is_initialized:
                self.lazy_initialization(key_states, value_states)
            end = self.length + key_states.shape[-2]
            if end > self.capacity:
                self.capacity = max(end, int(self.capacity * 1.25))
                batch, heads, _, dim = self._keys.shape
                keys = torch.empty(batch, heads, self.capacity, dim, dtype=self.dtype, device=self.device)
                values = torch.empty(batch, heads, self.capacity, dim, dtype=self.dtype, device=self.device)
                keys[:, :, :self.length].copy_(self._keys[:, :, :self.length])
                values[:, :, :self.length].copy_(self._values[:, :, :self.length])
                self._keys, self._values = keys, values
            self._keys[:, :, self.length:end].copy_(key_states)
            self._values[:, :, self.length:end].copy_(value_states)
            self.length = end
            self.keys, self.values = self._keys[:, :, :end], self._values[:, :, :end]
            return self.keys, self.values

        def get_seq_length(self):
            return self.length if self.is_initialized else 0

    try:
        cache = DynamicCache(config=model.config)
    except (AttributeError, TypeError, ValueError):
        return None          # unknown config shape: keep the library's default cache
    cache.layers = [GrowingLayer(capacity) for _ in cache.layers]
    return cache


def install_encoder_batching(model, batch_size, progress):
    """Batch the official Whisper encoder only, preserving all feature rows.

    The installed MOSS calls whisper_encoder(features, return_dict=True) and
    consumes last_hidden_state. Its mapping/merge/adaptor and decoder are intact.
    """
    import torch
    from transformers.modeling_outputs import BaseModelOutput
    encoder = model.model.whisper_encoder
    original = encoder.forward
    state = {"batch_size": batch_size}

    def forward(input_features, **kwargs):
        if not kwargs.get("return_dict") or kwargs.get("output_attentions") or kwargs.get("output_hidden_states"):
            return original(input_features, **kwargs)
        outputs = []
        for start in range(0, input_features.shape[0], state["batch_size"]):
            outputs.append(original(input_features[start:start + state["batch_size"]], **kwargs).last_hidden_state)
            progress.emit(encoder_feature_rows_done=min(input_features.shape[0], start + state["batch_size"]),
                          encoder_feature_rows_total=int(input_features.shape[0]))
        progress.set_phase("generation")
        return BaseModelOutput(last_hidden_state=torch.cat(outputs, dim=0))

    encoder.forward = forward
    return state


def generate_full_context(model, processor, audio, messages, device, dtype, progress, receipt):
    import torch
    from moss_transcribe_diarize.inference_utils import ProgressStreamer
    context_limit = int(model.config.text_config.max_position_embeddings)
    progress.set_phase("audio_encoding")
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    # Processor owns its 30s feature blocks and ordered audio_chunk_mapping.
    # Do not use truncation, VAD concatenation, or a shorter raw waveform.
    with torch.inference_mode():
        inputs = processor(text=text, audio=[audio], max_length=context_limit,
                           return_tensors="pt").to(device)
    prompt_len = int(inputs["attention_mask"][0].sum().item())
    budget, requested = generation_budget(len(audio) / processor.feature_extractor.sampling_rate, prompt_len, context_limit)
    receipt.update(input_tokens=prompt_len, max_new_tokens=budget, requested_output_tokens=requested,
                   context_limit=context_limit, processor_feature_chunk_count=int(inputs["input_features"].shape[0]))
    progress.emit(input_tokens=prompt_len, max_new_tokens=budget, context_limit=context_limit)
    progress.prompt_tokens = prompt_len
    # KV buffers sized for the expected transcript (about 5-8 tokens per audio
    # second measured); they grow only if a dense transcript needs more.
    kv_capacity = prompt_len + min(budget, math.ceil(len(audio) / processor.feature_extractor.sampling_rate * 10) + 2048)
    receipt["kv_cache"] = {"kind": "preallocated_growing", "initial_capacity_tokens": kv_capacity}
    config = copy.deepcopy(model.generation_config)
    config.max_new_tokens = budget
    config.do_sample = False
    config.num_beams = 1
    encoder_state = install_encoder_batching(model, GENERATION_POLICY["encoder_batch_size"], progress)

    window = {"start": None, "rates": []}

    def token_callback(count):
        progress.tokens = count
        progress.last_activity = time.monotonic()
        if count and count % 500 == 0 and window["start"] is not None:
            # Decode rate per 500 generated tokens: shows any slowdown as the context grows.
            started_at, started_count = window["start"]
            window["rates"].append(round((count - started_count) / max(1e-6, progress.last_activity - started_at), 2))
            window["start"] = (progress.last_activity, count)
        if progress.first_token_seconds is None and count > 0:
            window["start"] = (progress.last_activity, count)
            progress._rate_mark = (progress.last_activity, count)
            # Prefill is over: report it, then return its transient blocks to
            # the driver so decoding does not hold VRAM other programs need.
            progress.first_token_seconds = round(progress.last_activity - progress.phase_started, 3)
            receipt["first_token_seconds"] = progress.first_token_seconds
            receipt["prefill_peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1024**3, 3)
            torch.cuda.empty_cache()
            progress.emit(first_token_seconds=progress.first_token_seconds,
                          prefill_peak_allocated_gb=receipt["prefill_peak_allocated_gb"], **progress.device_memory())
        elif count % 100 == 0:
            progress.emit()

    def attempt():
        receipt["generation_attempts"] += 1
        progress.tokens = 0
        progress.first_token_seconds = None
        progress.set_phase("audio_encoding")
        progress.emit(generation_attempt=receipt["generation_attempts"], encoder_batch_size=encoder_state["batch_size"])
        # Real generate invocations are counted here, including failed attempts.
        cache = growing_kv_cache(model, kv_capacity)
        if cache is None:
            receipt["kv_cache"] = {"kind": "default_dynamic", "reason": "config_without_layer_types"}
        with torch.inference_mode(), torch.amp.autocast("cuda", dtype=dtype):
            return model.generate(**inputs, generation_config=config, streamer=ProgressStreamer(token_callback),
                                  **({"past_key_values": cache} if cache is not None else {}))

    try:
        outputs = attempt()
    except torch.cuda.OutOfMemoryError as exc:
        receipt["retries"].append({"reason": "cuda_oom", "detail": str(exc), "encoder_batch_size": 1})
        encoder_state["batch_size"] = 1
        # Release this attempt's traceback/tensors before retrying the SAME input.
        exc.__traceback__ = None
        gc.collect()
        torch.cuda.empty_cache()
        progress.emit(retry_reason="cuda_oom", encoder_batch_size=1)
        outputs = attempt()  # One bounded retry; never independent audio requests.
    generated = outputs[0][prompt_len:]
    count = int(generated.numel())
    decode_seconds = time.monotonic() - progress.phase_started - (progress.first_token_seconds or 0.0)
    receipt["decode_tokens_per_second"] = round(max(0, count - 1) / max(1e-6, decode_seconds), 2)
    receipt["decode_window_tokens_per_second"] = list(window["rates"])
    receipt["final_context_tokens"] = prompt_len + count
    reason, complete = ending_assessment(count, budget, int(generated[-1].item()) if count else None, config.eos_token_id)
    receipt.update(generated_tokens=count, end_reason=reason, complete=complete,
                   encoder_batch_size=encoder_state["batch_size"],
                   truncation_reasons=[] if complete else [reason])
    return processor.tokenizer.decode(generated, skip_special_tokens=True).strip()


def parsed_speaker_label(value, chunk_id):
    label = str(value).strip('[] ') if value is not None else ''
    if not label:
        raise RuntimeError(f'MOSS 第 {chunk_id} 块说话人标签解析失败：标签为空，未默认归入 S00。')
    return label


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio")
    parser.add_argument("--manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--run-signature", default="")
    parser.add_argument("--task-audio-fingerprint", default="")
    return parser.parse_args()


def media_duration(path):
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        return max(0.0, float(completed.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


class ModelIntegrityError(RuntimeError):
    pass


class AudioInputAudit:
    """Observe the original processor input without decoding or altering it."""

    def __init__(self, processor, on_input=None):
        self.processor = processor
        self.on_input = on_input
        self.inputs = None

    def __getattr__(self, name):
        return getattr(self.processor, name)

    def __call__(self, *args, **kwargs):
        audios = kwargs.get("audio")
        if audios is not None and self.inputs is None:
            rate = int(self.processor.feature_extractor.sampling_rate)
            self.inputs = {
                "sampling_rate": rate,
                "sample_counts": [int(len(audio)) for audio in audios],
                "audio_seconds": [len(audio) / rate for audio in audios],
                "clock": "decoded_pcm_samples",
            }
            if self.on_input is not None:
                self.on_input(self.inputs)
        return self.processor(*args, **kwargs)


def _vendored_model_root():
    """Registered MODEL_ROOT: 2BYTEASR_MODEL_ROOT env, then runtime_paths.json."""
    override = os.environ.get("2BYTEASR_MODEL_ROOT", "").strip()
    if override and os.path.isdir(override):
        return override
    base = (Path(os.environ.get("LOCALAPPDATA") or Path.home())).resolve()
    config = (base / "2ByteASR" / "runtime_paths.json").resolve()
    try:
        with config.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        candidate = str(payload.get("model_root") or "").strip()
        if candidate and os.path.isdir(candidate):
            return candidate
    except (OSError, ValueError):
        pass
    return ""


def _vendored_verify_model_files(model_name, model_root, *, install_root):
    """Minimal stand-in for twobyteasr.model_integrity.verify_model_files.

    Importing the package executes twobyteasr/__init__, whose service-chain
    side effects load the GUI bundle's cp310 .pyd files and break this 3.12
    worker ("Module use of python310.dll conflicts"). Same contract here:
    required files must exist inside the model directory, sha256-pinned
    files must match, and the location must be a known root.
    """
    lock_path = (Path(install_root) / "dependencies.lock.json").resolve()
    with lock_path.open(encoding="utf-8") as stream:
        lock = json.load(stream)
    try:
        spec = lock["models"][model_name]
    except KeyError as exc:
        raise ModelIntegrityError(f"依赖锁中没有模型：{model_name}") from exc
    target = Path(model_root).resolve()
    allowed = [(Path(install_root).resolve())]
    registered = _vendored_model_root()
    if registered:
        allowed.append(Path(registered).resolve())
    inside = any(target.is_relative_to(root) for root in allowed)
    if not inside and not target.is_dir():
        raise ModelIntegrityError(f"拒绝校验未知位置的模型：{target}")

    def _safe(relative):
        candidate = (target / relative).resolve()
        if candidate == target or candidate.is_relative_to(target):
            return candidate
        raise ModelIntegrityError(f"模型锁包含非法路径：{relative}")

    for relative in dict.fromkeys(spec.get("required_files", ())):
        candidate = _safe(relative)
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型必需文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )
    for relative, expected in (spec.get("sha256") or {}).items():
        candidate = _safe(relative)
        if not candidate.is_file():
            raise ModelIntegrityError(
                f"模型关键文件缺失：{candidate}\n"
                "请重新运行 download_models.bat，程序会断点续传并只补下载缺失文件。"
            )
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != str(expected).lower():
            raise ModelIntegrityError(
                f"模型文件校验失败，已拒绝加载：{candidate.name}。"
                f"请删除损坏文件 {candidate} 后重新运行 download_models.bat。"
            )
    return target


def resolve_model(requested, install_root):
    script_local = (Path(__file__).resolve().parent / "models" / "MOSS-Transcribe-Diarize")
    if (script_local / "config.json").is_file():
        return str(script_local)
    # Registered MODEL_ROOT: env override, then the persisted runtime_paths.json.
    override = os.environ.get("2BYTEASR_MODEL_ROOT", "").strip()
    if override:
        found = Path(override) / "MOSS-Transcribe-Diarize"
        if (found / "config.json").is_file():
            return str(found)
    base = (Path(os.environ.get("LOCALAPPDATA") or Path.home())).resolve()
    runtime_paths_file = (base / "2ByteASR" / "runtime_paths.json").resolve()
    try:
        with runtime_paths_file.open(encoding="utf-8") as stream:
            payload = json.load(stream)
        model_root = str(payload.get("model_root") or "").strip()
        if model_root:
            found = Path(model_root) / "MOSS-Transcribe-Diarize"
            if (found / "config.json").is_file():
                return str(found)
    except (OSError, ValueError):
        pass
    # Last resort: models shipped beside the install root.
    found = Path(install_root) / "models" / "MOSS-Transcribe-Diarize"
    if (found / "config.json").is_file():
        return str(found)
    return requested


def atomic_write_json(path, payload):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def load_chunk_checkpoint(checkpoint_dir, run_signature, job, job_index):
    checkpoint_dir = str(job.get("checkpoint_dir") or checkpoint_dir or "")
    run_signature = str(job.get("run_signature") or run_signature or "")
    if not checkpoint_dir or not run_signature:
        return None
    path = Path(checkpoint_dir) / f"chunk_{int(job.get('chunk_id', job_index)):03d}.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("run_signature") != run_signature:
            return None
        if abs(float(payload.get("offset", -1)) - float(job.get("offset", 0.0))) > 0.001:
            return None
        result = payload.get("result")
        if not isinstance(result, dict) or not result.get("segments"):
            return None
        return result
    except (OSError, ValueError, TypeError):
        return None


def save_chunk_checkpoint(checkpoint_dir, run_signature, result):
    checkpoint_dir = str(result.get("checkpoint_dir") or checkpoint_dir or "")
    run_signature = str(result.get("run_signature") or run_signature or "")
    if not checkpoint_dir or not run_signature:
        return
    path = Path(checkpoint_dir) / f"chunk_{int(result['chunk_id']):03d}.json"
    atomic_write_json(
        path,
        {
            "run_signature": run_signature,
            "offset": result["offset"],
            "result": result,
        },
    )


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    install_root = script_dir if (script_dir / "dependencies.lock.json").is_file() else script_dir.parent
    # Old block manifests must never execute, even through a direct CLI call.
    if args.manifest:
        jobs = json.loads(Path(args.manifest).read_text("utf8")).get("jobs", [])
        if len(jobs) != 1 or float(jobs[0].get("offset", 0)) != 0:
            raise ValueError("MOSS full_context 仅允许一个从任务0秒开始的完整音频请求；旧分块清单已停用。")
        args.audio = jobs[0]["audio"]
    else:
        jobs = [{"audio": args.audio, "offset": 0}]
    if not args.audio:
        raise ValueError("需要完整任务 --audio。")
    module_cache = Path(args.output).resolve().parent / ".hf_modules_cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_MODULES_CACHE", str(module_cache))
    progress = ExecutionProgress()
    receipt = {"inference_mode": INFERENCE_MODE, "cache_version": CACHE_VERSION,
               "application_chunk_count": 0, "worker_pids": [os.getpid()], "worker_count": len({os.getpid()}),
               "generation_attempts": 0, "retries": [], "cache_hit": False,
               "input_tokens": None, "max_new_tokens": None, "generated_tokens": None,
               "attention_backend": None, "dtype": None, "complete": False}
    payload = {"inference_mode": INFERENCE_MODE, "cache_version": CACHE_VERSION,
               "title": args.title, "execution": receipt, "chunks": []}
    heartbeat = threading.Thread(target=progress.heartbeat, daemon=True)
    heartbeat.start()
    try:
        import numpy as np
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoProcessor
        from moss_transcribe_diarize import parse_transcript
        from moss_transcribe_diarize.inference_utils import build_transcription_messages, load_audio_item
        if not torch.cuda.is_available():
            raise RuntimeError("MOSS 当前工作流要求 CUDA GPU。")
        device = torch.device("cuda:0")
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        progress.cuda_ready = True
        receipt.update(dtype=str(dtype), torch_version=torch.__version__,
                       transformers_version=transformers.__version__, runtime=sys.executable,
                       device_name=torch.cuda.get_device_name(device),
                       device_capability=".".join(str(part) for part in torch.cuda.get_device_capability(device)))
        model_source = resolve_model(args.model, install_root)
        payload["model"] = model_source
        _vendored_verify_model_files("moss", model_source, install_root=install_root)
        if Path(args.audio).suffix.lower() == ".npy":
            audio = np.load(args.audio, mmap_mode="r", allow_pickle=False)
            if audio.ndim != 1 or audio.dtype != np.dtype("float32"):
                raise ValueError("任务音频必须是完整 mono float32 PCM。")
        else:
            audio = load_audio_item(args.audio, sampling_rate=16000)
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError("任务音频为空或含非有限样本。")
        fingerprint = audio_fingerprint(audio, 16000)
        receipt.update(task_audio_duration=len(audio) / 16000, sample_rate=16000,
                       sample_count=len(audio), task_audio_fingerprint=fingerprint,
                       application_chunk_count=len(jobs), clock="task_pcm_zero")
        if args.task_audio_fingerprint and fingerprint != args.task_audio_fingerprint:
            raise ValueError("worker完整任务音频指纹与调度器不一致。")
        progress.emit(**receipt)
        progress.set_phase("model_loading")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        model_started = time.monotonic()
        model = AutoModelForCausalLM.from_pretrained(model_source, trust_remote_code=True,
                    dtype="auto", attn_implementation="sdpa").to(dtype=dtype).to(device).eval()
        processor = AutoProcessor.from_pretrained(model_source, trust_remote_code=True)
        if int(processor.feature_extractor.sampling_rate) != 16000:
            raise ValueError("MOSS processor采样率不匹配任务16k时钟。")
        receipt.update(attention_backend={"model": model.config._attn_implementation,
                       "text": model.config.text_config._attn_implementation,
                       "audio": model.config.audio_config._attn_implementation},
                       model_load_seconds=round(time.monotonic() - model_started, 3))
        install_prefill_attention_policy(model, dtype, receipt)
        progress.emit(attention_policy=install_decode_attention(model, receipt), **progress.device_memory())
        messages = build_transcription_messages(args.audio, prompt=DEFAULT_PROMPT)
        raw_text = generate_full_context(model, processor, audio, messages, device, dtype, progress, receipt)
        payload["raw_text"] = raw_text
        # Preserve native raw output even if parsing fails.
        atomic_write_json(args.output, payload)
        progress.set_phase("parsing")
        segments = []
        for segment in parse_transcript(raw_text):
            text = str(segment.text).strip()
            if text:
                start, end = float(segment.start), float(segment.end)
                if start < 0 or end <= start or end > receipt["task_audio_duration"] + 1:
                    receipt["complete"] = False
                    receipt.setdefault("truncation_reasons", []).append("invalid_timestamp")
                segments.append({"start": start, "end": end,
                                 "speaker": parsed_speaker_label(segment.speaker, 1), "text": text})
        if not segments:
            raise RuntimeError("MOSS 整段输出无法解析为说话人时间段；原始输出已保留。")
        segments.sort(key=lambda row: (row["start"], row["end"]))
        # A parser can silently skip an unfinished final clause: retain a review flag.
        import re
        if not re.search(r"\[[0-9]+(?:\.[0-9]+)?\]\s*$", raw_text):
            receipt["complete"] = False
            receipt.setdefault("truncation_reasons", []).append("unfinished_transcript_tail")
        receipt.update(raw_segment_count=len(segments),
                       raw_speaker_distribution=dict(Counter(row["speaker"] for row in segments)),
                       last_transcript_end=max(row["end"] for row in segments))
        chunk = {"chunk_id": 1, "offset": 0.0, "duration": receipt["task_audio_duration"],
                 "audio_input": {"sampling_rate": 16000, "sample_counts": [len(audio)],
                                 "audio_seconds": [len(audio) / 16000], "clock": "task_pcm_zero"},
                 "raw_text": raw_text, "segments": segments,
                 "prompt_tokens": receipt["input_tokens"], "max_new_tokens": receipt["max_new_tokens"],
                 "generated_tokens": receipt["generated_tokens"]}
        payload["chunks"] = [chunk]
        payload["generated_tokens"] = receipt["generated_tokens"]
        progress.set_phase("handoff")
    except Exception as exc:
        receipt.update(failure_stage=progress.phase, end_reason=type(exc).__name__,
                       error=str(exc), complete=False)
        progress.emit(**receipt)
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - progress.started, 3)
        receipt["phase_seconds"] = dict(progress.phase_seconds, **{
            progress.phase: round(progress.phase_seconds.get(progress.phase, 0.0) + time.monotonic() - progress.phase_started, 3)})
        try:
            import torch
            receipt["peak_allocated_gb"] = round(torch.cuda.max_memory_allocated() / 1024**3, 3)
            receipt["peak_reserved_gb"] = round(torch.cuda.max_memory_reserved() / 1024**3, 3)
        except Exception:
            pass
        payload["performance"] = {key: receipt.get(key) for key in (
            "model_load_seconds", "elapsed_seconds", "phase_seconds", "first_token_seconds",
            "decode_tokens_per_second", "prefill_peak_allocated_gb", "peak_allocated_gb", "peak_reserved_gb")}
        atomic_write_json(args.output, payload)
        progress.stop.set()
        heartbeat.join(timeout=1)
    progress.set_phase("completed" if receipt["complete"] else "needs_review")
    progress.emit(**receipt)


if __name__ == "__main__":
    main()
