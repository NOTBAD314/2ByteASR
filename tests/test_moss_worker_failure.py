"""Failure diagnosis, using explicitly synthetic faults, not a user's hardware."""
import json
import sys

import pytest

import moss_firered_pipeline as pipeline


def event(**fields):
    return "MOSS_EVENT " + json.dumps(fields, ensure_ascii=False)


def fail(tmp_path, lines, receipt=None, code=1):
    output = tmp_path / "worker.json"
    if receipt is not None:
        output.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf8")
    recorded = []
    with pytest.raises(RuntimeError) as caught:
        pipeline._read_moss_worker_payload(output, code, lines, "MOSS 整段worker",
            recorder=lambda name, **values: recorded.append((name, values)))
    return str(caught.value), recorded


def test_long_progress_json_does_not_hide_receipt_error(tmp_path):
    cause = "OSError: [WinError 1455] 页面文件太小，无法完成操作。"
    lines = [event(phase="model_loading", windows=list(range(3000)), error=cause)]
    # The old path started halfway through the JSON, exactly as in the screenshot.
    assert cause not in "\n".join(lines)[-3000:][:220]
    text, recorded = fail(tmp_path, lines, {"execution": {
        "error": cause, "failure_stage": "model_loading", "complete": False}})
    assert cause in text[:220] and "系统管理的大小" in text[:220]
    assert "MOSS_EVENT" not in text and "windows" not in text
    assert recorded[0][1]["error"] == cause
    assert recorded[0][1]["log_tail"] == lines[0]


@pytest.mark.parametrize("cause,advice", [
    ("ValueError: Prompt/audio sequence exceeds max_length=131072", "音频超过单次输入上限"),
    ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 672 MiB", "显存分配失败"),
    ("ModuleNotFoundError: No module named 'moss_transcribe_diarize'", "运行环境"),
    ("ImportError: DLL load failed while importing _C", "运行环境"),
    ("RuntimeError: unsupported operator", "请发送本次任务报告"),
])
def test_event_reason_survives_missing_or_broken_receipt(tmp_path, cause, advice):
    (tmp_path / "worker.json").write_text("{broken", encoding="utf8")
    text, recorded = fail(tmp_path, [event(phase="model_loading", error=cause),
                                    event(phase="model_loading", heartbeat=True)])
    assert cause in text[:220] and advice in text
    assert recorded[0][1]["failure_stage"] == "model_loading"


def test_traceback_without_receipt_and_non_object_events(tmp_path):
    text, _ = fail(tmp_path, [event(phase="model_loading"), "MOSS_EVENT null", "MOSS_EVENT []",
        "Traceback (most recent call last):", '  File "worker.py", line 1, in run',
        "RuntimeError: fixture real cause", "cleanup warning", event(heartbeat=True)])
    assert "RuntimeError: fixture real cause" in text
    assert "cleanup warning" not in text


@pytest.mark.parametrize("code", [1, -1073741819, 0])
def test_missing_reason_is_not_guessed_from_status_or_exit(tmp_path, code):
    text, _ = fail(tmp_path, [event(phase="model_loading", generated_tokens=None)], code=code)
    assert "未生成结果文件" in text if code == 0 else "未返回具体异常" in text
    assert "虚拟内存不足" not in text and "显存分配失败" not in text


def test_full_cause_preserved_when_display_is_bounded(tmp_path):
    cause = "ValueError: " + "diagnostic " * 500
    text, recorded = fail(tmp_path, [], {"execution": {"error": cause}})
    assert len(text) <= 220 and recorded[0][1]["error"] == cause.strip()


def test_success_still_validates_payload(tmp_path):
    output = tmp_path / "success.json"
    raw = {"chunks": [{"segments": [{"start": 0, "end": 1, "text": "测试"}]}]}
    output.write_text(json.dumps(raw), encoding="utf8")
    assert pipeline._read_moss_worker_payload(output, 0, [], "MOSS") == raw
    output.write_text("{}", encoding="utf8")
    with pytest.raises(pipeline.SchemaContractError):
        pipeline._read_moss_worker_payload(output, 0, [], "MOSS")


def test_real_child_exit_keeps_cause_and_full_diagnostics(tmp_path, monkeypatch):
    # A real subprocess emits progress, saves failure evidence, then raises.
    import numpy as np
    from types import SimpleNamespace
    try:
        import torch
    except ModuleNotFoundError:
        # This fixture exercises subprocess failure handling, not CUDA. The
        # production managed model runtime may be separate from the test venv.
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
        monkeypatch.setitem(sys.modules, 'torch', torch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    worker = tmp_path / "failed_worker.py"
    worker.write_text('''import json, sys
from pathlib import Path
target = sys.argv[sys.argv.index("--output") + 1]
cause = "RuntimeError: fixture loading failed"
receipt = {"error": cause, "failure_stage": "model_loading", "complete": False}
Path(target).write_text(json.dumps({"execution": receipt}), encoding="utf8")
print("MOSS_EVENT " + json.dumps({"phase": "model_loading", "padding": "x" * 5000, **receipt}), flush=True)
raise RuntimeError("fixture loading failed")
''', encoding="utf8")
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {
        "moss_python": sys.executable, "moss_worker": str(worker)})
    legacy = SimpleNamespace(AUDIO_SAMPLE_RATE=16000, record_run_event=lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="fixture loading failed"):
        pipeline.transcribe_moss_global("fixture.mp4", np.zeros(16000, np.float32), legacy,
                                       {"cache_dir": str(tmp_path / "cache")})
    evidence = tmp_path / "cache" / "speaker-evidence"
    assert "Traceback" in (evidence / "moss-full-context-worker.log").read_text("utf8")
    raw = json.loads((evidence / "moss-full-context-raw.json").read_text("utf8"))
    assert raw["execution"]["error"] == "RuntimeError: fixture loading failed"
