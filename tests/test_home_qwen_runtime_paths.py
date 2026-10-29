"""Home Qwen probes and timeline gate must use the packaged execution paths."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import moss_firered_pipeline as pipeline
from twobyteasr.recognition import asr
from twobyteasr.system import environment, runtime_registry
from twobyteasr import runtime_paths


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_non_windows_probe_does_not_require_the_windows_adapter(tmp_path, monkeypatch, platform):
    """Exercise the generated child script, without claiming a native Mac run."""
    app = tmp_path / "MacOS"
    site = tmp_path / "managed-site"
    app.mkdir()
    site.mkdir()
    (site / "torch.py").write_text(
        "from types import SimpleNamespace\n__version__='fixture'\n"
        "version=SimpleNamespace(cuda='fixture')\n"
        "cuda=SimpleNamespace(is_available=lambda:True,get_device_name=lambda n:'fixture')\n"
        "backends=SimpleNamespace()\n", "utf8")
    (site / "qwen_asr.py").write_text("pass\n", "utf8")
    (site / "twobyteasr.py").write_text(
        "raise RuntimeError('non-Windows probe must not require Windows adapter')\n", "utf8")
    python = sys.executable
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "2ByteASR"))
    result = asr._spawn_model_runtime_probe(
        {"model_id": "qwen3-asr"}, python, str(site), "qwen_asr")
    assert result["ready"], result.get("error")


def fake_native_runtime(tmp_path, *, compat_fails=False):
    """Minimal native-path failure, executed by the real isolated probe script."""
    app = tmp_path / "程序 中文"
    site = tmp_path / "环境 中文" / "site-packages"
    package = app / "twobyteasr" / "recognition"
    package.mkdir(parents=True)
    site.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("", "utf8")
    (package / "__init__.py").write_text("", "utf8")
    real = Path(asr.__file__).with_name("qwen_runtime_compat.py")
    (package / "qwen_runtime_compat.py").write_bytes(real.read_bytes())
    (site / "torch.py").write_text(
        "from types import SimpleNamespace\n__version__='fixture'\n"
        "version=SimpleNamespace(cuda='fixture')\n"
        "cuda=SimpleNamespace(is_available=lambda:True,get_device_name=lambda n:'fixture')\n"
        "backends=SimpleNamespace()\n", "utf8")
    (site / "dynet_config.py").write_text(
        "raise RuntimeError('compat_fixture_failure')\n" if compat_fails
        else "def set(**kwargs): pass\n", "utf8")
    (site / "dynet.py").write_text(
        "from pathlib import Path\nclass ParameterCollection:\n"
        " def populate(self,filename):\n"
        "  if not filename.isascii():raise RuntimeError('Could not read Unicode native model')\n"
        "  return Path(filename).read_bytes()\nModel=ParameterCollection\n", "utf8")
    nagisa = site / "nagisa"
    (nagisa / "data").mkdir(parents=True)
    (nagisa / "data/nagisa_v001.model").write_bytes(b"owned immutable fixture")
    (nagisa / "__init__.py").write_text(
        "from pathlib import Path\nimport dynet\n"
        "data=dynet.ParameterCollection().populate(str(Path(__file__).parent/'data/nagisa_v001.model'))\n",
        "utf8")
    (site / "qwen_asr.py").write_text(
        "pass\n" if compat_fails else "import nagisa\n", "utf8")
    # The GUI bundle's source root must come after the managed runtime.
    (app / "qwen_asr.py").write_text("raise RuntimeError('GUI bundle shadowed managed runtime')\n", "utf8")
    return app, site


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native nagisa filename boundary")
@pytest.mark.parametrize("frozen", [False, True])
def test_home_probe_prepares_native_unicode_reader_in_actual_child(tmp_path, monkeypatch, frozen):
    app, site = fake_native_runtime(tmp_path)
    python = sys.executable
    original = subprocess.run
    calls = []

    def run(command, **kwargs):
        command = list(command)
        assert "-I" in command
        index = command.index("-c") + 1
        command[index] = "import sys;sys.path.insert(0," + repr(str(site)) + ")\n" + command[index]
        calls.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(asr.subprocess, "run", run)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "2ByteASR.exe"))
    monkeypatch.setattr(asr, "__file__", str(app / "twobyteasr/recognition/asr.py"))
    environment.reset_preflight_cache()
    before = Path.cwd()
    result = asr.probe_qwen_environment(runtime=python, model_path=str(site))
    assert result["ready"], result["error"]
    assert len(calls) == 1
    assert result["parent_cwd_before"] == result["parent_cwd_after"] == str(before)
    assert result["parent_sys_path_hash_before"] == result["parent_sys_path_hash_after"]
    assert (site / "nagisa/data/nagisa_v001.model").read_bytes() == b"owned immutable fixture"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native nagisa filename boundary")
def test_home_probe_does_not_hide_compatibility_failure(tmp_path, monkeypatch):
    app, site = fake_native_runtime(tmp_path, compat_fails=True)
    python = sys.executable
    original = subprocess.run

    def run(command, **kwargs):
        command = list(command)
        index = command.index("-c") + 1
        command[index] = "import sys;sys.path.insert(0," + repr(str(site)) + ")\n" + command[index]
        return original(command, **kwargs)

    monkeypatch.setattr(asr.subprocess, "run", run)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(asr, "__file__", str(app / "twobyteasr/recognition/asr.py"))
    environment.reset_preflight_cache()
    result = asr.probe_qwen_environment(runtime=python, model_path=str(site))
    assert not result["ready"]
    assert "compat_fixture_failure" in result["error"]


@pytest.mark.parametrize("frozen", [False, True])
def test_home_timeline_gate_does_not_search_worker_in_unrelated_cwd(tmp_path, monkeypatch, frozen):
    app = tmp_path / "程序 中文"
    cwd = tmp_path / "用户 工作目录"
    app.mkdir(); cwd.mkdir()
    worker = app / "qwen_aligner_worker.py"
    worker.write_text("# owned fixture; execution replaced below\n", "utf8")
    python = tmp_path / "managed-python.exe"
    python.write_bytes(b"not executed")
    models = tmp_path / "models"; models.mkdir()
    events = []
    legacy = SimpleNamespace(SCRIPT_DIR=str(app), record_run_event=lambda name, **fields:events.append((name, fields)))
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(runtime_paths, "get_runtime_paths", lambda:SimpleNamespace(model_root=models))
    monkeypatch.setattr(runtime_registry, "resolve_runtime_python", lambda role:str(python))
    monkeypatch.chdir(cwd)
    paths = pipeline._script_paths(legacy)
    calls = []
    output = pipeline._run_audited_model_stage(
        legacy, model_id="qwen_aligner", role="timeline_alignment", backend="qwen_aligner",
        media_path="owned.wav", worker=paths["qwen_aligner_worker"], runtime=paths["main_python"],
        runner=lambda:calls.append("executed") or [{"text":"hello","start":0,"end":1}],
        allow_failure=True)
    assert calls == ["executed"] and output
    assert Path(paths["qwen_aligner_worker"]) == worker
    assert any(name=="MODEL_COMPLETED" for name, _ in events)
    assert not any(name=="MODEL_FAILED" for name, _ in events)
