import sys
import types

from twobyteasr.recognition import asr


def _fake_torch(monkeypatch):
    """CI 不安装 torch；该测试只验证会话复用逻辑，与 CUDA 无关。"""
    fake = types.ModuleType("torch")
    fake.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    monkeypatch.setitem(sys.modules, "torch", fake)


def test_qwen_model_is_reused_only_inside_explicit_queue_session(monkeypatch):
    _fake_torch(monkeypatch)
    marker = object()
    asr.begin_local_asr_session()
    try:
        assert asr._reuse_or_remember_qwen_model(marker) is marker
        assert asr._session_qwen_model() is marker
        assert asr._qwen_model_is_session_owned(marker)
    finally:
        asr.end_local_asr_session()

    assert asr._session_qwen_model() is None
    assert not asr._qwen_model_is_session_owned(marker)


def test_studio_persistent_session_survives_queue_end_until_forced_close(monkeypatch):
    _fake_torch(monkeypatch)
    marker = object()
    asr.begin_local_asr_session(persistent=True)
    asr._reuse_or_remember_qwen_model(marker)
    asr.end_local_asr_session()

    state = asr.local_asr_session_state()
    assert state["enabled"] is True
    assert state["persistent"] is True
    assert asr._session_qwen_model() is marker

    asr.end_local_asr_session(force=True)
    assert asr._session_qwen_model() is None
