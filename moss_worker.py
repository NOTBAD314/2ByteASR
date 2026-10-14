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
CACHE_VERSION = "moss-full-context-v2"
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


# Capacity planning (2026-10-13). One generate holds the prompt, the transcript
# and the KV cache of both. A 2 h 23 min stream needed 114,384 prompt tokens of a
# 131,072-token context and a 14.0 GiB KV cache on a 16 GB GPU: it neither fits
# nor could finish. Tasks that do not fit are split at quiet points into windows
# that fit this GPU's free memory and the context; neighbouring windows overlap
# by exactly ``overlap_seconds`` (the pipeline's merger owns each half).
WINDOW_POLICY = {"overlap_seconds": 20.0, "cut_search_seconds": 45.0, "minimum_window_seconds": 180.0,
                 "planning_output_tokens_per_second": 16, "prompt_overhead_tokens": 100,
                 # Prefill peak per prompt token: MLP intermediates (3 x 3072 bf16),
                 # expanded prefill K/V, hidden states. 22 KiB was measured at the
                 # failing allocation of the 2 h 23 min report; 40 KiB keeps margin.
                 "transient_bytes_per_prompt_token": 40 * 1024,
                 "fixed_overhead_bytes": 800 * 2**20, "safety_bytes": 512 * 2**20,
                 "allocator_headroom_bytes": 256 * 2**20, "max_oom_splits": 6}


class WindowCapacityError(RuntimeError):
    """Even the shortest allowed window cannot fit the free GPU memory."""


def kv_bytes_per_token(text_config, dtype_bytes=2):
    heads = int(text_config.num_attention_heads)
    kv_heads = int(getattr(text_config, "num_key_value_heads", heads) or heads)
    head_dim = int(getattr(text_config, "head_dim", 0) or text_config.hidden_size // heads)
    return int(text_config.num_hidden_layers) * 2 * kv_heads * head_dim * int(dtype_bytes)


def window_estimate(seconds, prompt_rate, context_limit, kv_bytes):
    """Tokens and device bytes one window needs.

    The KV cache is allocated for the whole output budget, so it never grows
    (a growth step briefly needs the old and the new buffer at once).
    """
    policy = WINDOW_POLICY
    prompt = policy["prompt_overhead_tokens"] + prompt_rate * seconds
    room = context_limit - prompt - GENERATION_POLICY["context_reserve"]
    wanted = max(GENERATION_POLICY["minimum_output_tokens"], seconds * GENERATION_POLICY["tokens_per_second"])
    budget = max(0.0, min(wanted, room))
    needed = max(GENERATION_POLICY["minimum_output_tokens"], seconds * policy["planning_output_tokens_per_second"])
    total = (kv_bytes * (prompt + budget) + policy["transient_bytes_per_prompt_token"] * prompt
             + policy["fixed_overhead_bytes"])
    return {"seconds": round(seconds, 3), "prompt_tokens": int(math.ceil(prompt)), "output_budget": int(budget),
            "bytes": int(total), "context_ok": bool(room >= needed)}


def plan_windows(duration, prompt_tokens, context_limit, usable_bytes, kv_bytes, max_window_seconds=None):
    """Single context when the task fits, otherwise the fewest windows that do.

    ``max_window_seconds`` (env TWOBYTEASR_MOSS_MAX_WINDOW_SECONDS) only ever
    shortens windows: a QA knob and a manual escape if free memory is misread.
    """
    policy = WINDOW_POLICY
    rate = max(1e-6, (prompt_tokens - policy["prompt_overhead_tokens"]) / max(duration, 1e-6))
    available = usable_bytes - policy["safety_bytes"]

    try:
        override = float(max_window_seconds) if max_window_seconds else None
    except (TypeError, ValueError):
        override = None
    if override is not None:
        override = max(override, policy["minimum_window_seconds"])

    def fits(seconds):
        if override is not None and seconds > override:
            return False
        estimate = window_estimate(seconds, rate, context_limit, kv_bytes)
        return estimate["context_ok"] and estimate["bytes"] <= available

    plan = {"duration": round(duration, 3), "prompt_tokens": int(prompt_tokens),
            "prompt_tokens_per_second": round(rate, 4), "context_limit": int(context_limit),
            "kv_bytes_per_token": int(kv_bytes), "usable_bytes": int(usable_bytes),
            "overlap_seconds": policy["overlap_seconds"], "max_window_override": override}
    if fits(duration):
        plan.update(mode="single_context", count=1, max_window_seconds=round(duration, 3),
                    estimate=window_estimate(duration, rate, context_limit, kv_bytes))
        return plan
    low, high = 0.0, float(duration)
    for _ in range(48):
        middle = (low + high) / 2
        low, high = (middle, high) if fits(middle) else (low, middle)
    plan["max_window_seconds"] = round(low, 1)
    # Audio shorter than the minimum window needs only its own length (2026-10-14).
    minimum = min(policy["minimum_window_seconds"], float(duration))
    if low < minimum:
        plan.update(mode="insufficient", count=0, minimum_window_seconds=round(minimum, 3),
                    needed_bytes=window_estimate(minimum, rate, context_limit, kv_bytes)["bytes"]
                    + policy["safety_bytes"])
        return plan
    # Cuts move by up to cut_search_seconds and each window gains the overlap.
    step = low - policy["overlap_seconds"] - 2 * policy["cut_search_seconds"]
    count = max(2, math.ceil(duration / step))
    plan.update(mode="context_windows", count=count, nominal_window_seconds=round(duration / count, 1),
                estimate=window_estimate(duration / count + policy["overlap_seconds"] + 2 * policy["cut_search_seconds"],
                                         rate, context_limit, kv_bytes))
    return plan


def quiet_cut(audio, target, search, *, lower=0.0, upper=None, sample_rate=16000):
    """Centre of the quietest 0.8 s within ``search`` seconds of ``target`` (nearest on ties)."""
    import numpy as np
    upper = len(audio) / sample_rate if upper is None else upper
    start, end = max(lower, target - search), min(upper, target + search)
    hop = int(0.05 * sample_rate)
    first = int(start * sample_rate)
    segment = np.asarray(audio[first:int(end * sample_rate)], dtype=np.float32)
    frames = len(segment) // hop
    width = 16
    if frames <= width:
        return round(min(max(target, start), end), 3)
    energy = np.sqrt(np.mean(np.square(segment[:frames * hop].reshape(frames, hop), dtype=np.float64), axis=1))
    smooth = np.convolve(energy, np.ones(width) / width, mode="valid")
    centres = start + (np.arange(len(smooth)) + width / 2) * 0.05
    index = int(np.lexsort((np.abs(centres - target), np.round(smooth, 7)))[0])
    return round(float(centres[index]), 3)


def window_bounds(audio, duration, count, sample_rate=16000):
    """Window (start, end) seconds; neighbours overlap by exactly ``overlap_seconds``."""
    if count <= 1:
        return [(0.0, float(duration))]
    policy = WINDOW_POLICY
    half = policy["overlap_seconds"] / 2
    cuts, previous = [], 0.0
    for index in range(1, count):
        lower = previous + 2 * policy["overlap_seconds"]
        upper = duration - (count - index) * 2 * policy["overlap_seconds"]
        cut = quiet_cut(audio, duration * index / count, policy["cut_search_seconds"],
                        lower=lower, upper=upper, sample_rate=sample_rate)
        cuts.append(cut)
        previous = cut
    bounds = []
    for index in range(count):
        start = 0.0 if index == 0 else round(cuts[index - 1] - half, 3)
        end = float(duration) if index == count - 1 else round(cuts[index] + half, 3)
        bounds.append((start, end))
    return bounds


class DeviceOps:
    """CUDA, Apple MPS and CPU differences in one place (2026-10-14).

    The CUDA path calls exactly what the worker always called. MPS runs
    bfloat16 and the CPU float32 (as the upstream MOSS example does off CUDA);
    neither has an allocator fraction to set, and they report memory from the
    MPS driver or the process.
    """

    def __init__(self, torch, kind, device):
        self.torch, self.kind, self.device = torch, kind, device

    @property
    def cuda(self):
        return self.kind == "cuda"

    def empty_cache(self):
        if self.kind == "cuda":
            self.torch.cuda.empty_cache()
        elif self.kind == "mps":
            self.torch.mps.empty_cache()

    def reset_peak(self):
        if self.kind == "cuda":
            self.torch.cuda.reset_peak_memory_stats()
        self._peak = self.allocated_bytes()

    def allocated_bytes(self):
        try:
            if self.kind == "cuda":
                return int(self.torch.cuda.memory_allocated())
            if self.kind == "mps":
                return int(self.torch.mps.driver_allocated_memory())
            return _process_rss_bytes()
        except Exception:
            return 0

    def peak_gb(self):
        if self.kind == "cuda":
            return round(self.torch.cuda.max_memory_allocated() / 1024**3, 3)
        self._peak = max(getattr(self, "_peak", 0), self.allocated_bytes())
        return round(self._peak / 1024**3, 3)

    def autocast(self, dtype):
        if self.kind == "cuda":
            return self.torch.amp.autocast("cuda", dtype=dtype)
        import contextlib
        return contextlib.nullcontext()

    def is_oom(self, exc):
        if isinstance(exc, self.torch.cuda.OutOfMemoryError):
            return True
        return self.kind != "cuda" and isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()

    def usable(self):
        """(bytes this process may still use, total, CUDA allocator fraction or None)."""
        if self.kind == "cuda":
            return usable_device_bytes(self.torch)
        if self.kind == "mps":
            total = int(self.torch.mps.recommended_max_memory())
            used = self.allocated_bytes()
            return max(0, total - used - WINDOW_POLICY["allocator_headroom_bytes"]), total, None
        available, total = _system_memory_bytes()
        return max(0, int(available * 0.85) - WINDOW_POLICY["allocator_headroom_bytes"]), total, None

    def memory_fields(self):
        if self.kind == "cuda":
            free, total = self.torch.cuda.mem_get_info()
            return {"vram_free_gb": round(free / 1024**3, 3), "vram_total_gb": round(total / 1024**3, 3),
                    "allocated_gb": round(self.torch.cuda.memory_allocated() / 1024**3, 3),
                    "reserved_gb": round(self.torch.cuda.memory_reserved() / 1024**3, 3)}
        fields = {"device_kind": self.kind, "allocated_gb": round(self.allocated_bytes() / 1024**3, 3)}
        if self.kind == "mps":
            fields["mps_recommended_max_gb"] = round(self.torch.mps.recommended_max_memory() / 1024**3, 3)
        return fields


def _process_rss_bytes():
    """Peak resident memory of this process (no extra packages needed)."""
    try:
        import psutil
        return int(psutil.Process().memory_info().rss)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE   # pseudo-handle -1, not a 32-bit int
            get_info = kernel32.K32GetProcessMemoryInfo
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            get_info.restype = wintypes.BOOL
            if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return 0
            return int(counters.PeakWorkingSetSize)
        except Exception:
            return 0
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss if sys.platform == "darwin" else rss * 1024)
    except Exception:
        return 0


def _system_memory_bytes():
    """(available, total) physical memory."""
    try:
        import psutil
        memory = psutil.virtual_memory()
        return int(memory.available), int(memory.total)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = Status()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullAvailPhys), int(status.ullTotalPhys)
        except Exception:
            pass
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        total = int(pages * size)
        available = total // 2
        if sys.platform == "darwin":
            # vm_stat: free + inactive + speculative pages are reclaimable.
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            counts = {}
            for line in out.splitlines()[1:]:
                name, _, value = line.partition(":")
                if value.strip().rstrip(".").isdigit():
                    counts[name.strip()] = int(value.strip().rstrip("."))
            page = int(out.split("page size of")[1].split()[0]) if "page size of" in out else size
            available = page * sum(counts.get(name, 0) for name in ("Pages free", "Pages inactive", "Pages speculative"))
        return int(available), total
    except Exception:
        return 8 * 1024**3, 16 * 1024**3


def resolve_device(torch, requested):
    """(kind, device, dtype) for ``--device`` auto | cuda | mps | cpu.

    ``auto`` keeps the long-standing CUDA requirement off macOS (MOSS on a
    Windows/Linux CPU is about real time and is never chosen silently); on
    macOS it prefers the Apple GPU (MPS) and falls back to the CPU.
    """
    requested = str(requested or "auto").lower()
    if requested in ("auto", "cuda") and torch.cuda.is_available():
        device = torch.device("cuda:0")
        return "cuda", device, torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if requested == "cuda" or (requested == "auto" and sys.platform != "darwin"):
        raise RuntimeError("MOSS 当前工作流要求 CUDA GPU。")
    mps = getattr(torch.backends, "mps", None)
    if requested in ("auto", "mps") and mps is not None and mps.is_available():
        # bfloat16 like the CUDA path (2026-10-14): on a 7 GB GitHub Mac float32
        # left ~0.8 GiB and was refused; bfloat16 ran with the same text and
        # speakers (CER 0.93 % on the 4-minute two-speaker clip, 1.8x real time).
        return "mps", torch.device("mps"), torch.bfloat16
    if requested == "mps":
        raise RuntimeError("这台电脑的 PyTorch 不能使用 Apple GPU（MPS 不可用）。")
    return "cpu", torch.device("cpu"), torch.float32


def usable_device_bytes(torch):
    """Bytes this process may still allocate without spilling into shared memory.

    On Windows the driver can back allocations with system RAM once the GPU is
    full (the 2 h 23 min report: 17.4 GiB allocated on a 15.9 GiB card, ~700 s
    of crawling prefill before the OOM). The returned fraction caps PyTorch at
    the memory that is physically free now, so an overrun fails at once.
    """
    free, total = torch.cuda.mem_get_info()
    reserved, allocated = torch.cuda.memory_reserved(), torch.cuda.memory_allocated()
    limit = reserved + free - WINDOW_POLICY["allocator_headroom_bytes"]
    fraction = min(1.0, max(0.05, limit / total))
    return int(limit - allocated), int(total), fraction


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
        self.ops = None   # DeviceOps once the device is chosen
        self._rate_mark = (self.started, 0)
        self.stop = threading.Event()
        # Current window of a long task, carried by every event (2026-10-13).
        self.window = {}

    def device_memory(self):
        """Measured device memory: CUDA free/total and allocator, or MPS/CPU usage."""
        if self.ops is None:
            return {}
        try:
            return self.ops.memory_fields()
        except Exception:
            return {}

    def emit(self, *, activity=True, **fields):
        if activity:
            self.last_activity = time.monotonic()
        row = {"phase": self.phase, "elapsed_seconds": round(time.monotonic() - self.started, 3),
               "last_activity_elapsed_seconds": round(self.last_activity - self.started, 3),
               "generated_tokens": self.tokens, "progress_percent": None, **self.window, **fields}
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
    if not torch.cuda.is_available():
        # MPS / CPU (2026-10-14): no CUDA kernel choice to probe; SDPA picks its own.
        policy["non_cuda_default"] = True
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
    # Installed once per window: always wrap the library's own forward.
    original = getattr(encoder, "_twobyteasr_original_forward", None) or encoder.forward
    encoder._twobyteasr_original_forward = original
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


def prompt_inputs(processor, audio, messages, context_limit):
    """Processor output for one audio window (CPU tensors) and its prompt length."""
    import torch
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    # Processor owns its 30s feature blocks and ordered audio_chunk_mapping.
    # Do not use truncation, VAD concatenation, or a shorter raw waveform.
    with torch.inference_mode():
        inputs = processor(text=text, audio=[audio], max_length=context_limit, return_tensors="pt")
    return inputs, int(inputs["attention_mask"][0].sum().item())


def generate_full_context(model, processor, audio, messages, device, dtype, progress, receipt, inputs=None):
    """One generate over one audio window (the whole task when it fits)."""
    import torch
    ops = progress.ops or DeviceOps(torch, "cuda", device)
    from moss_transcribe_diarize.inference_utils import ProgressStreamer
    context_limit = int(model.config.text_config.max_position_embeddings)
    progress.set_phase("audio_encoding")
    if inputs is None:
        inputs, _ = prompt_inputs(processor, audio, messages, context_limit)
    inputs = inputs.to(device)
    prompt_len = int(inputs["attention_mask"][0].sum().item())
    budget, requested = generation_budget(len(audio) / processor.feature_extractor.sampling_rate, prompt_len, context_limit)
    receipt.update(input_tokens=prompt_len, max_new_tokens=budget, requested_output_tokens=requested,
                   context_limit=context_limit, processor_feature_chunk_count=int(inputs["input_features"].shape[0]))
    progress.emit(input_tokens=prompt_len, max_new_tokens=budget, context_limit=context_limit)
    progress.prompt_tokens = prompt_len
    # KV buffers for the whole output budget: they never grow, so the memory
    # planned by plan_windows is the memory used (2026-10-13).
    kv_capacity = prompt_len + budget
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
            receipt["prefill_peak_allocated_gb"] = ops.peak_gb()
            ops.empty_cache()
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
        with torch.inference_mode(), ops.autocast(dtype):
            return model.generate(**inputs, generation_config=config, streamer=ProgressStreamer(token_callback),
                                  **({"past_key_values": cache} if cache is not None else {}))

    try:
        outputs = attempt()
    except Exception as exc:
        if not ops.is_oom(exc):
            raise
        if progress.phase != "audio_encoding":
            # The decoder (prefill or decode) ran out: the same input cannot fit
            # again. The caller splits this window instead (2026-10-13).
            raise
        receipt["retries"].append({"reason": "cuda_oom", "detail": str(exc), "encoder_batch_size": 1})
        encoder_state["batch_size"] = 1
        # Release this attempt's traceback/tensors before retrying the SAME input.
        exc.__traceback__ = None
        gc.collect()
        ops.empty_cache()
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


WINDOW_RECORD_KEYS = ("generation_attempts", "input_tokens", "max_new_tokens", "requested_output_tokens",
                      "context_limit", "processor_feature_chunk_count", "kv_cache", "first_token_seconds",
                      "prefill_peak_allocated_gb", "decode_tokens_per_second", "decode_window_tokens_per_second",
                      "final_context_tokens", "generated_tokens", "end_reason", "complete", "encoder_batch_size",
                      "truncation_reasons")


def parse_window_segments(raw_text, window_seconds, chunk_id, record, parse_transcript):
    """Native MOSS rows of one window (times relative to the window start)."""
    import re
    segments = []
    for segment in parse_transcript(raw_text):
        text = str(segment.text).strip()
        if text:
            start, end = float(segment.start), float(segment.end)
            if start < 0 or end <= start or end > window_seconds + 1:
                record["complete"] = False
                record.setdefault("truncation_reasons", []).append("invalid_timestamp")
            segments.append({"start": start, "end": end,
                             "speaker": parsed_speaker_label(segment.speaker, chunk_id), "text": text})
    segments.sort(key=lambda row: (row["start"], row["end"]))
    # A parser can silently skip an unfinished final clause: retain a review flag.
    if segments and not re.search(r"\[[0-9]+(?:\.[0-9]+)?\]\s*$", raw_text):
        record["complete"] = False
        record.setdefault("truncation_reasons", []).append("unfinished_transcript_tail")
    return segments


def run_windows(model, processor, audio, messages, device, dtype, progress, receipt, payload,
                parse_transcript, output_path):
    """Plan, then generate each window in order; an OOM splits the window it hit."""
    import numpy as np
    import torch
    rate = 16000
    duration = len(audio) / rate
    policy = WINDOW_POLICY
    half = policy["overlap_seconds"] / 2
    context_limit = int(model.config.text_config.max_position_embeddings)
    progress.set_phase("audio_encoding")
    full_inputs, full_prompt = prompt_inputs(processor, audio, messages, context_limit)
    ops = progress.ops or DeviceOps(torch, "cuda", device)
    usable, total, fraction = ops.usable()
    if fraction is not None:
        torch.cuda.set_per_process_memory_fraction(fraction, device)
    kv_bytes = kv_bytes_per_token(model.config.text_config, torch.finfo(dtype).bits // 8)
    plan = plan_windows(duration, full_prompt, context_limit, usable, kv_bytes,
                        max_window_seconds=os.environ.get("TWOBYTEASR_MOSS_MAX_WINDOW_SECONDS"))
    plan.update(device_total_bytes=total, memory_fraction=round(fraction, 4) if fraction is not None else None,
                device_kind=ops.kind)
    receipt["window_plan"] = plan
    progress.emit(window_plan=plan, **progress.device_memory())
    if plan["mode"] == "insufficient":
        have, need = usable / 2**30, plan['needed_bytes'] / 2**30
        minimum = float(plan.get("minimum_window_seconds", policy['minimum_window_seconds']))
        if minimum < policy['minimum_window_seconds']:
            window = f"这段 {minimum:.0f} 秒的音频"
        else:
            window = f"MOSS 最短 {minimum / 60:.0f} 分钟的识别窗口"
        if ops.kind == "cuda":
            message = (f"显存不足：本机现在可用约 {have:.1f} GiB，{window}"
                       f"也需要约 {need:.1f} GiB。请关闭占用显卡的程序后重试，或改用其他主力转写模型。")
        else:
            # Apple GPU (MPS) and CPU use system memory, not a graphics card (2026-10-14).
            where = "这台 Mac 的内存（Apple 芯片的显卡与内存共用）" if ops.kind == "mps" else "本机内存"
            message = (f"可用内存不足：{where}现在约剩 {have:.1f} GiB，{window}"
                       f"还需要约 {need:.1f} GiB。请关闭其他占用内存的程序后重试，或改用云端识别等其他主力转写方式。")
        raise WindowCapacityError(message)
    queue = window_bounds(audio, duration, plan["count"], rate)
    first_inputs = full_inputs if plan["count"] == 1 else None
    del full_inputs
    chunks, windows, attempts, splits = [], [], 0, 0
    while queue:
        start, end = queue.pop(0)
        low, high = int(round(start * rate)), min(len(audio), int(round(end * rate)))
        single = low == 0 and high == len(audio)
        window_audio = audio if single else np.ascontiguousarray(audio[low:high])
        record = {"generation_attempts": 0, "retries": []}
        progress.window = {"window_index": len(chunks) + 1, "window_count": len(chunks) + 1 + len(queue),
                           "window_start": round(low / rate, 3), "window_end": round(high / rate, 3)}
        progress.emit()
        ops.reset_peak()
        failure = None
        try:
            raw_text = generate_full_context(model, processor, window_audio, messages, device, dtype,
                                             progress, record, inputs=first_inputs)
        except Exception as exc:
            if not ops.is_oom(exc):
                raise
            failure = (str(exc), progress.phase)
            exc.__traceback__ = None
        if failure is not None:
            # Outside the except block nothing pins the failed attempt's tensors.
            first_inputs = None
            attempts += record["generation_attempts"]
            detail, phase = failure
            del window_audio
            gc.collect()
            ops.empty_cache()
            seconds = (high - low) / rate
            if splits >= policy["max_oom_splits"] or seconds < 2 * policy["minimum_window_seconds"]:
                raise WindowCapacityError(
                    f"MOSS 分段后仍显存不足（{seconds / 60:.1f} 分钟的窗口，已拆分 {splits} 次）：{detail[:300]}") from None
            cut = quiet_cut(audio, (low + high) / 2 / rate, min(policy["cut_search_seconds"], seconds / 4),
                            lower=low / rate + 2 * policy["overlap_seconds"],
                            upper=high / rate - 2 * policy["overlap_seconds"], sample_rate=rate)
            queue[0:0] = [(low / rate, round(cut + half, 3)), (round(cut - half, 3), high / rate)]
            splits += 1
            receipt["retries"].append({"reason": "cuda_oom_window_split", "phase": phase,
                                       "window": [round(low / rate, 3), round(high / rate, 3)], "cut": cut,
                                       "detail": detail[:300]})
            progress.emit(retry_reason="cuda_oom_window_split", window_start=low / rate, window_end=high / rate, cut=cut)
            continue
        first_inputs = None
        attempts += record["generation_attempts"]
        record["peak_allocated_gb"] = ops.peak_gb()
        index = len(chunks) + 1
        chunk = {"chunk_id": index, "offset": low / rate, "duration": (high - low) / rate,
                 "audio_input": {"sampling_rate": rate, "sample_counts": [high - low],
                                 "audio_seconds": [(high - low) / rate], "clock": "task_pcm_zero"},
                 "raw_text": raw_text, "segments": []}
        chunks.append(chunk)
        payload["chunks"] = chunks
        if single:
            payload["raw_text"] = raw_text
        # Preserve native raw output even if parsing fails.
        atomic_write_json(output_path, payload)
        progress.set_phase("parsing")
        chunk["segments"] = parse_window_segments(raw_text, (high - low) / rate, index, record, parse_transcript)
        if single and not chunk["segments"]:
            raise RuntimeError("MOSS 整段输出无法解析为说话人时间段；原始输出已保留。")
        chunk.update(prompt_tokens=record.get("input_tokens"), max_new_tokens=record.get("max_new_tokens"),
                     generated_tokens=record.get("generated_tokens"), end_reason=record.get("end_reason"),
                     complete=bool(record.get("complete")))
        windows.append({"index": index, "start": round(low / rate, 3), "end": round(high / rate, 3),
                        **{key: record.get(key) for key in WINDOW_RECORD_KEYS if key in record},
                        "retries": record["retries"], "peak_allocated_gb": record["peak_allocated_gb"],
                        "segments": len(chunk["segments"])})
        atomic_write_json(output_path, payload)
        del window_audio
        gc.collect()
        ops.empty_cache()
    if not any(chunk["segments"] for chunk in chunks):
        raise RuntimeError("MOSS 各段输出都无法解析为说话人时间段；原始输出已保留。")
    receipt["retries"].extend(retry for window in windows for retry in window["retries"])
    if len(chunks) == 1:
        receipt.update({key: windows[0][key] for key in WINDOW_RECORD_KEYS if key in windows[0]})
    else:
        reasons = [f"window{row['index']}:{reason}" for row in windows for reason in row.get("truncation_reasons") or []]
        receipt.update(input_tokens=sum(row.get("input_tokens") or 0 for row in windows),
                       max_new_tokens=sum(row.get("max_new_tokens") or 0 for row in windows),
                       requested_output_tokens=sum(row.get("requested_output_tokens") or 0 for row in windows),
                       generated_tokens=sum(row.get("generated_tokens") or 0 for row in windows),
                       context_limit=context_limit,
                       end_reason="eos" if all(row.get("end_reason") == "eos" for row in windows) else next(
                           row.get("end_reason") for row in windows if row.get("end_reason") != "eos"),
                       complete=all(row.get("complete") for row in windows), truncation_reasons=reasons)
    receipt.update(generation_attempts=attempts, application_chunk_count=len(chunks), windows=windows,
                   window_mode="single_context" if len(chunks) == 1 else "context_windows")
    segments = [row for chunk in chunks for row in chunk["segments"]]
    receipt.update(raw_segment_count=len(segments),
                   raw_speaker_distribution=dict(Counter(f"W{chunk['chunk_id']}:{row['speaker']}" if len(chunks) > 1
                                                         else row["speaker"] for chunk in chunks for row in chunk["segments"])),
                   last_transcript_end=max(chunk["offset"] + row["end"] for chunk in chunks for row in chunk["segments"]))
    payload["generated_tokens"] = receipt["generated_tokens"]


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
    # 2026-10-14: auto keeps "CUDA required" off macOS; on macOS auto = MPS, else CPU.
    parser.add_argument("--device", default=os.environ.get("TWOBYTEASR_MOSS_DEVICE", "auto"),
                        choices=("auto", "cuda", "mps", "cpu"))
    parser.add_argument("--dtype", default=os.environ.get("TWOBYTEASR_MOSS_DTYPE", "auto"),
                        choices=("auto", "float32", "float16", "bfloat16"))
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
        kind, device, dtype = resolve_device(torch, args.device)
        if args.dtype != "auto":
            dtype = getattr(torch, args.dtype)
        ops = DeviceOps(torch, kind, device)
        progress.ops = ops
        if kind == "cuda":
            device_name = torch.cuda.get_device_name(device)
            capability = ".".join(str(part) for part in torch.cuda.get_device_capability(device))
        else:
            import platform
            device_name = "Apple GPU (MPS)" if kind == "mps" else (platform.processor() or platform.machine())
            capability = ""
        receipt.update(dtype=str(dtype), torch_version=torch.__version__,
                       transformers_version=transformers.__version__, runtime=sys.executable,
                       device_kind=kind, device_requested=args.device,
                       device_name=device_name, device_capability=capability)
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
        ops.empty_cache()
        ops.reset_peak()
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
        run_windows(model, processor, audio, messages, device, dtype, progress, receipt, payload,
                    parse_transcript, args.output)
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
            # Peaks are reset per window; keep the largest one.
            peaks = [row.get("peak_allocated_gb") or 0 for row in receipt.get("windows") or []]
            if progress.ops is not None and not progress.ops.cuda:
                receipt["peak_allocated_gb"] = round(max([progress.ops.peak_gb(), *peaks]), 3)
            else:
                receipt["peak_allocated_gb"] = round(max([torch.cuda.max_memory_allocated() / 1024**3, *peaks]), 3)
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
