"""P1-5 回归测试：Qwen ASR API 取消不得等待在途 HTTP 请求。

安全语义：
- 用户取消后 pipeline 调用线程快速抛 CancelledError（不再因
  ThreadPoolExecutor context manager 的 shutdown(wait=True) 等待最长 180s）
- 未开始执行的 future 被取消（不发起新请求、不产生费用）
- 已发出的请求继续执行（同步 requests 不可硬取消，可能产生费用），
  但其迟到结果被丢弃，不进入结果表、不污染后续任务
"""

import os
import threading
import time

import pytest

import subtitle_core  # noqa: F401
from twobyteasr.recognition import asr as asr_mod
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.service import CancelledError, CancellationToken


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.reason = "OK" if status_code == 200 else "Error"
        self.headers={}

    def json(self):
        if self.status_code==200 and 'text' in self._payload:
            return {'output':{'choices':[{'message':{'content':[{'text':self._payload['text']}]}}]}}
        return self._payload


class _BlockingPost:
    """第一次调用阻塞直到 release；可配置迟到结果/错误/retry 序列。"""

    def __init__(self, payload=None, fail_statuses=(), raise_after_release=None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self._payload = payload or {"text": "迟到文本"}
        self._fail_statuses = list(fail_statuses)
        self._raise_after_release = raise_after_release

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            self.release.wait(30)
            if self._raise_after_release is not None:
                raise self._raise_after_release
        if self.calls - 1 < len(self._fail_statuses):
            return _FakeResponse(self._fail_statuses[self.calls - 1], {"code": "x", "message": "boom"})
        return _FakeResponse(200, self._payload)


class _QuickPost:
    """每次调用立即成功，返回指定文本。"""

    def __init__(self, text="快速文本"):
        self.text = text
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return _FakeResponse(200, {"text": self.text})


def _chunk(data=None, start=0.0, end=1.0):
    import numpy as np

    audio = np.zeros(1600, dtype=np.float32) if data is None else data
    return {"audio": (audio, 16000), "start": start, "end": end}


def _run_transcribe(audio_path, chunks, token, outcome):
    runtime = RuntimeContext(cancellation_token=token)
    with activate_runtime_context(runtime):
        try:
            outcome["result"] = asr_mod._transcribe_qwen_api(audio_path, chunks)
        except BaseException as exc:
            outcome["exc"] = exc


@pytest.fixture(autouse=True)
def api_env(monkeypatch):
    """1 worker（控制并发）+ 固定上下文。"""
    monkeypatch.setattr(asr_mod, "CLOUD_BATCH_WORKERS", 1)
    monkeypatch.setattr(asr_mod,'_ASR_API_THROTTLE',asr_mod._AsrApiThrottle())
    monkeypatch.setattr(subtitle_core,'RUNTIME_SETTINGS',{'models':{
        'qwen_asr_api_provider':'custom','qwen_asr_api_protocol':'dashscope_multimodal',
        'qwen_asr_api_model':'fixture-unrelated-deployment','qwen_asr_api_url':'https://example.test/asr'}})
    monkeypatch.setattr('twobyteasr.providers.llm_config.read_asr_api_key',lambda *_:('fixture','test fixture'))


# ---------------------------------------------------------------- Case A：正常完成

def test_case_a_all_requests_complete_normally(monkeypatch):
    """Case A：所有请求正常完成 → 结果与旧行为一致。"""
    quick = _QuickPost(text="正确转写")
    monkeypatch.setattr("requests.post", quick)
    chunks = [_chunk(start=0.0), _chunk(start=1.0)]
    outcome = {}
    _run_transcribe("x.mp4", chunks, None, outcome)
    result = outcome["result"]
    assert [item["text"] for item in result] == ["正确转写", "正确转写"]
    assert quick.calls == 2


# ---------------------------------------------------------------- Case B：取消不等在途请求（核心红）

def test_case_b_cancel_does_not_wait_for_running_request(api_env, monkeypatch):
    """Case B：在途请求阻塞时取消 → 快速抛 CancelledError，不等 blocking request。"""
    blocking = _BlockingPost()
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(), _chunk(start=1.0)]
    token = CancellationToken()
    outcome = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome))
    try:
        thread.start()
        assert blocking.started.wait(5), "请求应已开始"
        token.cancel()
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "取消后不得等待在途请求（旧实现挂住）"
        assert isinstance(outcome.get("exc"), CancelledError), "取消应抛 CancelledError"
    finally:
        blocking.release.set()
        thread.join(timeout=5)


# ---------------------------------------------------------------- Case C/G/J：pending futures 不再开始

def test_case_c_pending_futures_never_start_after_cancel(api_env, monkeypatch):
    """Case C/G/J：1 worker、3 chunks——取消后未开始的 chunk 不再请求 API。"""
    blocking = _BlockingPost()
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(start=0.0), _chunk(start=1.0), _chunk(start=2.0)]
    token = CancellationToken()
    outcome = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome))
    try:
        thread.start()
        assert blocking.started.wait(5)
        token.cancel()
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert isinstance(outcome.get("exc"), CancelledError)
    finally:
        blocking.release.set()
        thread.join(timeout=5)
    assert blocking.calls == 1, "取消后未开始的 chunk 不得发起请求（pending future 已取消）"


# ---------------------------------------------------------------- Case D：迟到结果被丢弃

def test_case_d_late_result_is_discarded(api_env, monkeypatch):
    """Case D：取消后在途 request 随后成功返回 → 其结果不进入结果表。"""
    blocking = _BlockingPost(payload={"text": "迟到文本"})
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(), _chunk(start=1.0)]
    token = CancellationToken()
    outcome = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome))
    thread.start()
    assert blocking.started.wait(5)
    token.cancel()
    thread.join(timeout=2.0)
    assert isinstance(outcome.get("exc"), CancelledError)
    blocking.release.set()  # 迟到结果此刻返回
    thread.join(timeout=5)
    assert "result" not in outcome, "取消后函数不得返回结果表"


# ---------------------------------------------------------------- Case E：在途错误不覆盖取消

def test_case_e_inflight_error_does_not_override_cancel(api_env, monkeypatch):
    """Case E：取消后在途 request 报错 → 仍抛 CancelledError（不被错误覆盖）。"""
    blocking = _BlockingPost(raise_after_release=RuntimeError("网络断开"))
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(), _chunk(start=1.0)]
    token = CancellationToken()
    outcome = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome))
    thread.start()
    assert blocking.started.wait(5)
    token.cancel()
    thread.join(timeout=2.0)
    assert isinstance(outcome.get("exc"), CancelledError), "迟到错误不得覆盖 CancelledError"
    blocking.release.set()
    thread.join(timeout=5)


# ---------------------------------------------------------------- Case F：取消后不触发 retry

def test_case_f_no_retry_after_cancel(api_env, monkeypatch):
    """Case F：取消后在途请求返回后不再进入 retry 重试。"""
    blocking = _BlockingPost()
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(), _chunk(start=1.0)]
    token = CancellationToken()
    outcome = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome))
    thread.start()
    assert blocking.started.wait(5)
    token.cancel()
    thread.join(timeout=2.0)
    blocking.release.set()
    thread.join(timeout=5)
    assert blocking.calls == 1, "取消后不得进入 retry 发起新请求"


# ---------------------------------------------------------------- Case H：正常 retry 行为不变

def test_case_h_retry_behavior_unchanged(monkeypatch):
    """Case H：正常请求失败（500×2）→ retry → 成功，行为与旧实现一致。"""
    calls = {"n": 0}
    attempts=[]

    def flaky_post(*args, **kwargs):
        calls["n"] += 1
        attempts.append(__import__("traceback").format_stack(limit=5))
        if calls["n"] <= 2:
            return _FakeResponse(500, {"code": "x", "message": "boom"})
        return _FakeResponse(200, {"text": "重试成功"})

    monkeypatch.setattr("requests.post", flaky_post)
    chunks = [_chunk()]
    outcome = {}
    _run_transcribe("x.mp4", chunks, None, outcome)
    assert outcome["result"][0]["text"] == "重试成功"
    assert calls["n"] == 3, attempts


# ---------------------------------------------------------------- Case I：两轮任务隔离

def test_case_i_second_run_not_polluted_by_first_late_result(api_env, monkeypatch):
    """Case I：第一轮取消（迟到结果返回）后开始第二轮 → 第二轮结果干净。"""
    blocking = _BlockingPost(payload={"text": "第一轮迟到文本"})
    monkeypatch.setattr("requests.post", blocking)
    chunks = [_chunk(), _chunk(start=1.0)]
    token = CancellationToken()
    outcome1 = {}
    thread = threading.Thread(target=_run_transcribe, args=("x.mp4", chunks, token, outcome1))
    thread.start()
    assert blocking.started.wait(5)
    token.cancel()
    thread.join(timeout=2.0)
    assert isinstance(outcome1.get("exc"), CancelledError)
    blocking.release.set()  # 第一轮迟到结果此刻返回并成为孤儿
    thread.join(timeout=5)

    # 第二轮：正常完成，使用全新 token/上下文
    quick = _QuickPost(text="第二轮正确文本")
    monkeypatch.setattr("requests.post", quick)
    outcome2 = {}
    _run_transcribe("x.mp4", [_chunk(), _chunk(start=1.0)], None, outcome2)
    texts = [item["text"] for item in outcome2["result"]]
    assert texts == ["第二轮正确文本", "第二轮正确文本"], "第二轮不得混入第一轮迟到结果"
