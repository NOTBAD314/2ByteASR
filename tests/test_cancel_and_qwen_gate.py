"""Regression tests for the 2026-08-10 P0 fixes:

- parallel stages propagate cancellation without blocking on siblings;
- stage failure still waits for siblings (callers rely on it before the
  serial fallback retries);
- the Qwen enabled switch is part of the qwen cache signature and the
  evidence-attach stage short-circuits when the switch is off.
"""

from contextlib import contextmanager
import threading
import time

import pytest

from twobyteasr.recognition.pipeline_runtime import run_parallel_stages
from twobyteasr.recognition.service import CancelledError, CancellationToken


class _ParallelLegacy:
    def __init__(self):
        self.items = []
        self.local = threading.local()

    @contextmanager
    def capture_review_items(self):
        bucket = []
        self.local.current = bucket
        try:
            yield bucket
        finally:
            self.local.current = None

    def extend_review_items(self, rows):
        self.items.extend(rows)


def test_parallel_cancellation_returns_promptly_without_waiting_for_sibling():
    legacy = _ParallelLegacy()
    release = threading.Event()
    started = time.monotonic()

    def slow_stage():
        release.wait(timeout=5)
        return "slow"

    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        run_parallel_stages(
            legacy,
            {"fast": lambda: "fast", "slow": slow_stage},
            thread_name_prefix="test",
            cancel_poll=token.raise_if_cancelled,
        )
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"取消应立刻返回，实际阻塞了 {elapsed:.2f} 秒"
    release.set()


def test_parallel_stage_failure_still_waits_for_sibling():
    legacy = _ParallelLegacy()
    release = threading.Event()
    finished = []

    def failing_stage():
        raise RuntimeError("boom")

    def slow_stage():
        release.wait(timeout=5)
        finished.append("slow-done")
        return "slow"

    with pytest.raises(RuntimeError):
        run_parallel_stages(
            legacy,
            {"fail": failing_stage, "slow": slow_stage},
            thread_name_prefix="test",
        )
    # 阶段失败必须等兄弟阶段结束：调用方的显存回退依赖其释放资源。
    assert finished == ["slow-done"]
    release.set()


def test_qwen_cache_signature_changes_with_enabled_switch(monkeypatch):
    import twobyteasr.recognition.cache as cache

    signature_enabled = cache.cache_stage_signature("qwen")
    monkeypatch.setattr(cache, "USE_QWEN_ASR_REFERENCE", False)
    signature_disabled = cache.cache_stage_signature("qwen")
    assert signature_enabled != signature_disabled


def test_attach_qwen_evidence_short_circuits_when_switch_disabled():
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition.transcript_data import SpeechSegment

    segments = [
        SpeechSegment(
            segment_id=1,
            start=0.0,
            end=2.0,
            text="测试",
            confidence=0.9,
            words=[],
        )
    ]
    chunks = [{"start": 0.1, "end": 1.9, "text": "测试"}]

    class _Legacy:
        USE_QWEN_ASR_REFERENCE = False

    returned = pipeline.attach_qwen_review_evidence(segments, chunks, _Legacy())
    assert returned is segments
    assert segments[0].qwen_asr_context == ""
