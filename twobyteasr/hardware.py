"""Hardware diagnostics shared by the GUI and transcription pipeline."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from twobyteasr.processes import (
    main_python_executable,
    python_utf8_command,
    run_hidden_subprocess,
    run_subprocess_with_tree_kill,
    sanitized_child_environment,
)


@dataclass(frozen=True)
class CudaRuntimeStatus:
    ready: bool
    code: str
    summary: str
    guidance: str
    gpu_name: str = ""
    memory_mb: int = 0
    torch_version: str = ""
    cuda_version: str = ""
    driver_version: str = ""


@dataclass(frozen=True)
class TorchAudioRuntimeStatus:
    ready: bool
    code: str
    summary: str
    guidance: str
    torch_version: str = ""
    torchaudio_version: str = ""


def _visible_nvidia_gpu() -> tuple[str, int]:
    if not shutil.which("nvidia-smi"):
        return "", 0
    try:
        result = run_hidden_subprocess(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            purpose="nvidia-smi GPU inventory",
            runner=run_subprocess_with_tree_kill,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if not first:
            return "", 0
        name, _, memory = first.rpartition(",")
        return name.strip() or first.strip(), int(memory.strip()) if memory.strip().isdigit() else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return "", 0


def _nvidia_driver_version() -> str:
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        result = run_hidden_subprocess(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            purpose="nvidia-smi driver version",
            runner=run_subprocess_with_tree_kill,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _version_major(version: str) -> int:
    try:
        return int(version.strip().split(".", 1)[0])
    except (AttributeError, TypeError, ValueError):
        return 0


_TORCH_PROBE_MARKER = "__2BYTEASR_TORCH_PROBE__"


def _sys_path_hash(entries=None) -> str:
    values = [str(item) for item in (sys.path if entries is None else entries)]
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _probe_cwd() -> str:
    """Return a stable project/install cwd, never the external venv tree."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return str(Path(__file__).resolve().parents[1])


def _probe_torch_runtime() -> dict:
    """Probe Torch in a disposable process so the GUI never locks Torch DLLs.

    Model installation may need to replace ``torch\\lib\\c10.dll``. Importing
    Torch in the long-running model-workshop process keeps that DLL mapped on
    Windows and makes an otherwise valid cu128 upgrade fail with ``os error
    5``. The child exits immediately after the probe and releases every DLL.
    """
    script = r'''
import importlib.util
import json
import os
import sys
import warnings

marker = "__2BYTEASR_TORCH_PROBE__"
result = {
    "imported": False,
    "available": False,
    "usable": False,
    "torch_version": "",
    "cuda_version": "",
    "gpu_name": "",
    "memory_mb": 0,
    "total_memory_mb": 0,
    "free_memory_mb": 0,
    "device_count": 0,
    "error": "",
    "torchaudio_imported": False,
    "torchaudio_version": "",
    "torchaudio_error": "",
    "runtime_context": {
        "process_exe": sys.executable,
        "sys_prefix": sys.prefix,
        "sys_base_prefix": sys.base_prefix,
        "sys_path": list(sys.path),
        "cwd": os.getcwd(),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "pythonhome": os.environ.get("PYTHONHOME", ""),
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": str(getattr(sys, "_MEIPASS", "") or ""),
    },
}
try:
    result["runtime_context"]["numpy_spec_origin"] = str(
        getattr(importlib.util.find_spec("numpy"), "origin", "") or ""
    )
except Exception as exc:
    result["runtime_context"]["numpy_spec_error"] = f"{type(exc).__name__}: {exc}"
try:
    result["runtime_context"]["torch_spec_origin"] = str(
        getattr(importlib.util.find_spec("torch"), "origin", "") or ""
    )
except Exception as exc:
    result["runtime_context"]["torch_spec_error"] = f"{type(exc).__name__}: {exc}"
try:
    import torch
    result["imported"] = True
    result["torch_version"] = str(getattr(torch, "__version__", "unknown"))
    result["cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        result["available"] = bool(torch.cuda.is_available())
        result["device_count"] = int(torch.cuda.device_count()) if result["available"] else 0
        if result["available"]:
            props = torch.cuda.get_device_properties(0)
            result["gpu_name"] = str(props.name)
            result["memory_mb"] = int(props.total_memory / 1024 / 1024)
            result["total_memory_mb"] = result["memory_mb"]
            try:
                free, total = torch.cuda.mem_get_info(0)
                result["free_memory_mb"] = int(free / 1024 / 1024)
                result["total_memory_mb"] = int(total / 1024 / 1024)
            except Exception as exc:
                result["memory_info_error"] = str(exc)
            probe = torch.ones(1, device="cuda")
            result["usable"] = float(probe.sum().item()) == 1.0
except Exception as exc:
    result["error"] = str(exc)
try:
    import torchaudio
    result["torchaudio_imported"] = True
    result["torchaudio_version"] = str(getattr(torchaudio, "__version__", "unknown"))
except Exception as exc:
    result["torchaudio_error"] = str(exc)
print(marker + json.dumps(result, ensure_ascii=False))
'''
    parent_path = list(sys.path)
    parent_cwd = os.getcwd()
    interpreter = main_python_executable()
    if not interpreter:
        return {
            "imported": False,
            "error": "Main runtime Python was not found (registry, legacy venvs or %LOCALAPPDATA%\\2ByteASR\\runtimes)",
            "parent_sys_path_hash_before": _sys_path_hash(parent_path),
            "parent_sys_path_hash_after": _sys_path_hash(),
            "parent_cwd_before": parent_cwd,
            "parent_cwd_after": os.getcwd(),
        }
    try:
        completed = run_hidden_subprocess(
            python_utf8_command([interpreter, "-I", "-c", script]),
            purpose="PyTorch runtime probe",
            runner=run_subprocess_with_tree_kill,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            check=False,
            cwd=_probe_cwd(),
            env=sanitized_child_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"imported": False, "error": str(exc)}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(_TORCH_PROBE_MARKER):
            try:
                result = json.loads(line[len(_TORCH_PROBE_MARKER):])
                result["probe_interpreter"] = interpreter
                result["probe_cwd"] = _probe_cwd()
                result["parent_sys_path_hash_before"] = _sys_path_hash(parent_path)
                result["parent_sys_path_hash_after"] = _sys_path_hash()
                result["parent_cwd_before"] = parent_cwd
                result["parent_cwd_after"] = os.getcwd()
                return result
            except json.JSONDecodeError:
                break
    detail = completed.stderr.strip() or completed.stdout.strip()
    return {
        "imported": False,
        "error": detail or "Torch probe returned no result",
        "probe_interpreter": interpreter,
        "probe_cwd": _probe_cwd(),
        "parent_sys_path_hash_before": _sys_path_hash(parent_path),
        "parent_sys_path_hash_after": _sys_path_hash(),
        "parent_cwd_before": parent_cwd,
        "parent_cwd_after": os.getcwd(),
    }


def collect_gpu_telemetry() -> dict[str, object]:
    """Return honest GPU evidence without importing Torch in the GUI process.

    ``UNKNOWN`` is intentionally distinct from an unavailable GPU.  A failed
    probe must never be converted to ``0 GB`` and then interpreted as a valid
    low-memory machine by the scheduler.
    """
    probe = _probe_torch_runtime()
    nvidia_name, nvidia_total_mb = _visible_nvidia_gpu()
    driver = _nvidia_driver_version()
    torch_version = str(probe.get("torch_version", "") or "")
    cuda_version = str(probe.get("cuda_version", "") or "")
    device_count = int(probe.get("device_count") or 0)
    total_mb = int(probe.get("total_memory_mb") or probe.get("memory_mb") or 0)
    free_mb = int(probe.get("free_memory_mb") or 0)
    gpu_name = str(probe.get("gpu_name") or nvidia_name or "")
    error = str(probe.get("error") or "")
    status = "READY" if bool(probe.get("usable")) else (
        "UNAVAILABLE" if probe.get("imported") and (gpu_name or nvidia_name) else "UNKNOWN"
    )
    if not probe.get("imported") and not nvidia_name:
        status = "UNKNOWN"
    return {
        "status": status,
        "torch_version": torch_version,
        "torch_cuda_version": cuda_version,
        "cuda_available": bool(probe.get("available")),
        "cuda_usable": bool(probe.get("usable")),
        "device_count": device_count,
        "gpu_name": gpu_name,
        "total_vram_gb": round((total_mb or nvidia_total_mb) / (1024.0), 3),
        "free_vram_gb": round(free_mb / (1024.0), 3) if free_mb else None,
        "total_memory_mb": total_mb or nvidia_total_mb,
        "free_memory_mb": free_mb,
        "driver_version": driver,
        "probe_error": error,
        "nvml_error": "" if nvidia_name else ("nvidia-smi unavailable or returned no GPU" if shutil.which("nvidia-smi") else "nvidia-smi not found"),
        "probe_interpreter": str(probe.get("probe_interpreter") or ""),
        "probe_cwd": str(probe.get("probe_cwd") or ""),
        "probe_runtime_context": probe.get("runtime_context") or {},
        "parent_sys_path_hash_before": str(probe.get("parent_sys_path_hash_before") or ""),
        "parent_sys_path_hash_after": str(probe.get("parent_sys_path_hash_after") or ""),
        "parent_cwd_before": str(probe.get("parent_cwd_before") or ""),
        "parent_cwd_after": str(probe.get("parent_cwd_after") or ""),
    }


def _wheel_build_tag(version: str) -> str:
    return version.partition("+")[2].strip().lower()


def detect_torch_audio_runtime() -> TorchAudioRuntimeStatus:
    """Check the shared Torch/TorchAudio pair without importing it in the GUI."""
    probe = _probe_torch_runtime()
    torch_version = str(probe.get("torch_version", "") or "")
    audio_version = str(probe.get("torchaudio_version", "") or "")
    if not probe.get("imported"):
        return TorchAudioRuntimeStatus(
            False,
            "torch_missing",
            "本地模型运行库缺少 PyTorch。",
            "请在模型工坊对所选模型执行“校验并修复”。",
            torch_version,
            audio_version,
        )
    if not probe.get("torchaudio_imported"):
        detail = str(probe.get("torchaudio_error", "") or "TorchAudio 无法导入")
        return TorchAudioRuntimeStatus(
            False,
            "torchaudio_mismatch",
            "PyTorch 与 TorchAudio 版本不匹配，本地模型无法稳定运行。",
            "请在模型工坊点击所选模型的“校验并修复”，安装器会成对重装二者。"
            f"\n诊断：{detail}",
            torch_version,
            audio_version,
        )
    torch_tag = _wheel_build_tag(torch_version)
    audio_tag = _wheel_build_tag(audio_version)
    if torch_tag != audio_tag:
        return TorchAudioRuntimeStatus(
            False,
            "torch_audio_build_mismatch",
            f"PyTorch（{torch_tag or '无构建标签'}）与 TorchAudio（{audio_tag or '无构建标签'}）不是同一运行版本。",
            "请在模型工坊点击所选模型的“校验并修复”，不要单独安装 Torch 或 TorchAudio。",
            torch_version,
            audio_version,
        )
    return TorchAudioRuntimeStatus(
        True,
        "ready",
        "PyTorch 与 TorchAudio 运行库匹配。",
        "本地模型运行库可用。",
        torch_version,
        audio_version,
    )


def detect_cuda_runtime() -> CudaRuntimeStatus:
    """Return an actionable CUDA diagnosis without raising."""
    gpu_name, memory_mb = _visible_nvidia_gpu()
    driver_version = _nvidia_driver_version()
    probe = _probe_torch_runtime()
    if not probe.get("imported"):
        exc = probe.get("error", "PyTorch is not installed")
        return CudaRuntimeStatus(
            False,
            "torch_missing",
            "Python 环境缺少 PyTorch，无法运行 MOSS。",
            f"请关闭 2ByteASR 后运行“配置或修复 2ByteASR”。诊断：{exc}",
            gpu_name,
            memory_mb,
        )

    torch_version = str(probe.get("torch_version", "unknown"))
    cuda_version = str(probe.get("cuda_version", "") or "")
    cuda_probe_error = str(probe.get("error", "") or "")
    cuda_ready = bool(probe.get("usable"))
    if cuda_ready:
        gpu_name = str(probe.get("gpu_name") or gpu_name)
        memory_mb = int(probe.get("memory_mb") or memory_mb)
        return CudaRuntimeStatus(
            True,
            "ready",
            f"已检测到 NVIDIA CUDA GPU：{gpu_name or 'GPU'}"
            + (f"（{memory_mb} MB）" if memory_mb else ""),
            "CUDA 运行环境可用。",
            gpu_name,
            memory_mb,
            torch_version,
            cuda_version,
            driver_version,
        )

    if not gpu_name:
        return CudaRuntimeStatus(
            False,
            "gpu_or_driver_missing",
            "未检测到可用的 NVIDIA CUDA GPU，MOSS 无法运行。",
            "请确认电脑具有 NVIDIA CUDA 显卡并安装/更新 NVIDIA 显卡驱动。"
            "普通 VMware 虚拟机看不到宿主机 GPU；需要配置 GPU 直通/vGPU，或在宿主机运行 2ByteASR。"
            "通常不需要另外安装完整 CUDA Toolkit，2ByteASR 配置器会安装 CUDA 版 PyTorch。",
            torch_version=torch_version,
            cuda_version=cuda_version,
            driver_version=driver_version,
        )

    cpu_build = "+cpu" in torch_version.lower() or not cuda_version
    if cpu_build:
        return CudaRuntimeStatus(
            False,
            "cpu_torch",
            f"已检测到 NVIDIA GPU（{gpu_name}），但当前安装的是 CPU 版 PyTorch。",
            "请关闭 2ByteASR，打开“配置或修复 2ByteASR”重新配置；"
            "配置器会从国内镜像安装 CUDA 版 PyTorch。",
            gpu_name,
            memory_mb,
            torch_version,
            cuda_version,
            driver_version,
        )

    if cuda_probe_error:
        return CudaRuntimeStatus(
            False,
            "gpu_arch_unsupported",
            f"已检测到 NVIDIA GPU（{gpu_name}），但当前 PyTorch 无法在这张显卡上执行 CUDA。",
            "显卡并不一定太旧，通常是 PyTorch CUDA 构建不包含这张显卡的计算架构。"
            "请关闭 2ByteASR 后运行“配置或修复 2ByteASR”；RTX 50 系列会自动改用 cu128。"
            f"\n诊断：{cuda_probe_error}",
            gpu_name,
            memory_mb,
            torch_version,
            cuda_version,
            driver_version,
        )

    # NVIDIA 的官方兼容表要求 CUDA 13.x 至少使用 580 系列驱动。旧安装包
    # 曾错误地选择 cu130，因此 RTX 30 系显卡即使可见也可能在这里不可用。
    if _version_major(cuda_version) >= 13 and 0 < _version_major(driver_version) < 580:
        return CudaRuntimeStatus(
            False,
            "driver_torch_mismatch",
            f"已检测到 NVIDIA GPU（{gpu_name}），但 PyTorch CUDA 版本与驱动不匹配。",
            "当前 PyTorch 使用 CUDA 13，而驱动低于 580。显卡本身并不太老；"
            "请关闭 2ByteASR，运行“配置或修复 2ByteASR”，配置器会改装兼容性更好的 cu126 版本。"
            "通常不需要安装完整 CUDA Toolkit。",
            gpu_name,
            memory_mb,
            torch_version,
            cuda_version,
            driver_version,
        )
    return CudaRuntimeStatus(
        False,
        "cuda_unavailable",
        f"已检测到 NVIDIA GPU（{gpu_name}），但 PyTorch 无法启用 CUDA。",
        "请先关闭 2ByteASR，运行“配置或修复 2ByteASR”重装匹配的 CUDA PyTorch；"
        "完成后重启电脑。若仍失败，再重新安装 NVIDIA 驱动。通常不需要安装完整 CUDA Toolkit。"
        f"当前 PyTorch：{torch_version}，CUDA 构建：{cuda_version or '无'}，驱动：{driver_version or '未知'}。",
        gpu_name,
        memory_mb,
        torch_version,
        cuda_version,
        driver_version,
    )


def require_cuda_runtime() -> CudaRuntimeStatus:
    status = detect_cuda_runtime()
    if not status.ready:
        raise RuntimeError(f"{status.summary} {status.guidance}")
    return status


CUDA_REQUIRED_PRIMARY = {"moss", "firered", "qwen_local", "firered_llm"}
CUDA_REQUIRED_TIMELINE = {"local", "qwen_aligner"}
CUDA_REQUIRED_REVIEW = {"local", "firered_llm"}

LOCAL_PRIMARY = {
    "moss", "firered", "qwen_local", "firered_llm", "whisper_turbo",
    "sensevoice", "paraformer", "funasr_nano", "glm_asr_nano", "canary_qwen",
}
LOCAL_TIMELINE = {"local", "qwen_aligner", "paraformer", "whisper_turbo"}
LOCAL_REVIEW = {"local", "firered_llm", "whisper_turbo", "sensevoice", "funasr_nano"}


def selected_local_runtime_components(settings: dict) -> list[str]:
    models = settings.get("models", {}) if isinstance(settings, dict) else {}
    selected = []
    primary = str(models.get("primary_asr_backend", "moss"))
    timeline = str(models.get("firered_asr_backend", "local"))
    review = str(models.get("qwen_asr_backend", "api"))
    if primary in LOCAL_PRIMARY:
        selected.append(f"主力转写：{primary}")
    if timeline in LOCAL_TIMELINE:
        selected.append(f"字级时间轴：{timeline}")
    if review in LOCAL_REVIEW and review != primary:
        selected.append(f"文字复核：{review}")
    return selected


def require_local_torch_runtime(settings: dict) -> TorchAudioRuntimeStatus:
    status = detect_torch_audio_runtime()
    if selected_local_runtime_components(settings) and not status.ready:
        raise RuntimeError(f"{status.summary} {status.guidance}")
    return status


def selected_cuda_components(settings: dict) -> list[str]:
    """Return the selected runtime components that cannot run without CUDA.

    CPU-capable local models and online APIs are deliberately excluded so a
    machine without an NVIDIA GPU is not blocked before the pipeline starts.
    """
    models = settings.get("models", {}) if isinstance(settings, dict) else {}
    selected = []
    primary = str(models.get("primary_asr_backend", "moss"))
    timeline = str(models.get("firered_asr_backend", "local"))
    review = str(models.get("qwen_asr_backend", "api"))
    if primary in CUDA_REQUIRED_PRIMARY:
        selected.append({
            "moss": "MOSS 主力转写",
            "firered": "FireRed 主力转写",
            "qwen_local": "Qwen3-ASR 本地主力转写",
            "firered_llm": "FireRedASR2-LLM 主力转写",
        }[primary])
    if timeline in CUDA_REQUIRED_TIMELINE:
        label = "FireRed 字级时间轴" if timeline == "local" else "Qwen3 ForcedAligner 时间轴"
        if label not in selected:
            selected.append(label)
    if review in CUDA_REQUIRED_REVIEW:
        selected.append(
            "FireRedASR2-LLM 文字复核"
            if review == "firered_llm"
            else "Qwen3-ASR 本地文字复核"
        )
    return selected


def combination_requires_cuda(settings: dict) -> bool:
    return bool(selected_cuda_components(settings))
