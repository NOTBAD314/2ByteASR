"""MOSS readiness accepts the full-context worker output (segments per chunk)."""
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_prepared_model.py"
    spec = importlib.util.spec_from_file_location("validate_prepared_model", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_context_chunks_count_as_speech():
    validator = _load()
    full_context = {"chunks": [{"segments": [{"start": 0.0, "end": 5.26, "speaker": "S01",
                                               "text": "Hello, this is a local speech recognition test."}]}]}
    assert validator.moss_has_speech(full_context)
    assert validator.moss_has_speech({"segments": [{"speaker": "S01", "text": "x"}]})
    assert not validator.moss_has_speech({"chunks": [{"segments": [{"speaker": "S01", "text": ""}]}]})
    assert not validator.moss_has_speech({"chunks": [], "segments": None})


def test_page_file_failure_gets_its_own_category():
    """2026-10-15: os error 1455 is a memory problem the user can fix, not a broken model."""
    validator = _load()
    failure = ('QWEN3-ALIGNER worker failed (exit 1):\nstdout:\n'
               '[2BYTEASR_QWEN3_ALIGNER] {"event": "failed", "error_type": "OSError", '
               '"detail": "页面文件太小，无法完成操作。 (os error 1455)"}\n\nstderr:\n')
    category, message = validator.failure_category(RuntimeError(failure))
    assert (category, message) == ("system_memory", "页面文件太小，无法完成操作。 (os error 1455)")
    assert validator.failure_category("[WinError 1455] 页面文件太小") == ("system_memory", "[WinError 1455] 页面文件太小")
    assert validator.failure_category("hardware_unsupported: 需要 CUDA")[0] == "hardware_unsupported"
    assert validator.failure_category("CUDA out of memory")[0] == "hardware_unsupported"
    # A CUDA allocation that failed with most of the VRAM free (the worker's own reading) is the commit limit too.
    oom = ('QWEN3-ALIGNER worker failed (exit 1):\nstdout:\n[2BYTEASR_QWEN3_ALIGNER] {"event": "failed", '
           '"error_type": "AcceleratorError", "detail": "CUDA error: out of memory", "free_vram_mb": 14200}\n')
    category, message = validator.failure_category(RuntimeError(oom))
    assert (category, message) == ("system_memory", "CUDA error: out of memory（显存当时还剩 14200 / ? MB）")
    assert validator.failure_category(oom.replace("14200", "300"))[0] == "hardware_unsupported"
    assert validator.failure_category("对齐 worker 没有返回有效时间戳") == ("model_load_failed", "对齐 worker 没有返回有效时间戳")
