import sys
from types import SimpleNamespace

from twobyteasr.recognition import asr
from twobyteasr import model_integrity


def test_funasr_falls_back_to_cpu_when_cuda_kernel_probe_fails(monkeypatch):
    calls = []

    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=FakeAutoModel))
    monkeypatch.setattr(asr, "resolve_funasr_local_source", lambda _key: "C:/models/SenseVoiceSmall")
    monkeypatch.setattr(asr, "_cuda_runtime_ready", lambda: False)
    monkeypatch.setattr(model_integrity, "verify_model_files", lambda *_args: None)

    _model, device = asr._load_funasr_model("sensevoice")

    assert device == "cpu"
    assert calls == [
        {
            "model": "C:/models/SenseVoiceSmall",
            "device": "cpu",
            "disable_update": True,
        }
    ]
