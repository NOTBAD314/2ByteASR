"""Phase B 回归测试：运行环境 preflight（fast/deep + service guard）。

覆盖产品矩阵 A-N：
- A main 缺 transformers → deep fail → 任务不启动
- B main transformers 版本错误 → fail
- C moss 5.14.1+hub 0.36.2 → worker 启动前 fail
- D moss transformers 5.99+hub 1.x（满足 pyproject 范围）→ 因不符 lock fail
- E main OK/moss bad 且配置需要 moss → 明确 moss 错误
- F main OK/moss bad 但配置不用 moss → 不阻断
- G fingerprint 一致 → fast path 不执行 deep imports
- H lock hash 变化 → 缓存失效 → deep
- I interpreter 缺失 → 明确错误
- J probe 超时 → 进程终止、有界返回
- K 版本正确但 import 失败 → 分类 import failure
- L 旧用户错误 A/B → 升级后第一轮任务被阻断
- M 系统 Python 正常但当前 venv 坏 → 仍失败（不 fallback）
- N 连续两次任务 → 第二次不重复 deep
"""

import json
import os
import stat
import subprocess
import sys
import venv as venv_module
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "dependencies.lock.json"
WHEELS = PROJECT_ROOT / "wheels"
PYTHON = PROJECT_ROOT / ".venv-main" / "Scripts" / "python.exe"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not PYTHON.is_file(),
    reason="需要 Windows 与本机主环境创建隔离 venv",
)

import twobyteasr.system.environment as env_module
import twobyteasr.environment_probe as probe_module


def test_probe_protocol_keeps_import_diagnostics_off_stdout(monkeypatch, capsys):
    import io

    def noisy_imports(*args, **kwargs):
        print('[ERROR] upstream import diagnostic')
        return {'ok': True, 'errors': []}

    monkeypatch.setattr(probe_module, 'run', noisy_imports)
    monkeypatch.setattr(probe_module.sys, 'stdin', io.StringIO('{"role":"nemotron"}'))
    probe_module.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {'ok': True, 'errors': []}
    assert 'upstream import diagnostic' in captured.err


_ENVIRONMENT_SLOTS = {}
_ENVIRONMENT_ROOT = None


@pytest.fixture(scope='module', autouse=True)
def _bounded_dependency_fixtures(tmp_path_factory):
    """Two reusable corruptible environments, never one retained copy per test.

    pytest itself uses the existing development runtime. These two slots are
    needed only for the real offline install/import-failure integration cases.
    They are wholly new test data; no pre-existing environment is modified.
    """
    global _ENVIRONMENT_ROOT
    _ENVIRONMENT_ROOT = tmp_path_factory.mktemp('dependency-fixtures').resolve()
    _ENVIRONMENT_SLOTS.clear()
    yield
    _ENVIRONMENT_SLOTS.clear()
    _ENVIRONMENT_ROOT = None


@pytest.fixture(autouse=True)
def _reset_cache():
    env_module.reset_preflight_cache()
    yield
    env_module.reset_preflight_cache()


def _make_venv(tmp_path, name, *, base_python=None):
    assert _ENVIRONMENT_ROOT is not None
    slot='moss' if base_python else 'main'
    target=(_ENVIRONMENT_ROOT/slot).resolve()
    # EnvBuilder(clear=True) deletes its target contents. Check the absolute
    # target against this module's fresh owner directory before every reset.
    assert target.parent==_ENVIRONMENT_ROOT and _ENVIRONMENT_ROOT.is_relative_to(PROJECT_ROOT/'tmp')
    assert not target.is_symlink()
    if target.exists():
        assert not (getattr(target.lstat(),'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    builder = venv_module.EnvBuilder(with_pip=True,clear=target.exists())
    if base_python:
        # venv 模块用当前进程解释器；用解释器参数创建不同版本的 venv
        subprocess.run(
            [str(base_python), "-m", "venv", "--clear", str(target)],
            check=True, timeout=120,
        )
    else:
        builder.create(str(target))
    _ENVIRONMENT_SLOTS[slot]=str(target)
    (_ENVIRONMENT_ROOT/'ownership.json').write_text(json.dumps({
        'owner':'test_environment_preflight','slots':_ENVIRONMENT_SLOTS,
        'maximum_environments':2,'last_case':name},indent=2),'utf8')
    return target / "Scripts" / "python.exe"


MOSS_BASE_PY = PROJECT_ROOT / ".venv-moss" / "Scripts" / "python.exe"


def _moss_venv(tmp_path, name):
    return _make_venv(tmp_path, name, base_python=MOSS_BASE_PY)


def _moss_editable_offline(python):
    """editable 安装 MOSS（--no-deps + --no-build-isolation，离线）。"""
    _pip_offline(python, ["setuptools==80.9.0", "wheel==0.45.1"])
    return subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps",
         "--no-build-isolation",
         "-e", str(PROJECT_ROOT / "third_party" / "MOSS-Transcribe-Diarize")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )


def _pip_offline(python, specs):
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index",
         "--find-links", str(WHEELS)] + specs,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    assert result.returncode == 0, f"离线安装失败：{result.stderr[-400:]}"
    return result


MAIN_CONTRACT = ["transformers==4.57.6", "huggingface_hub==0.36.2",
                 "tokenizers==0.22.2", "safetensors==0.8.0"]
MOSS_CONTRACT = ["transformers==5.14.1", "huggingface_hub==1.24.0",
                 "tokenizers==0.22.2", "safetensors==0.8.0"]
# FireRedVAD import 链（fireredasr2s → torch → kaldiio → transformers）
FIRERED_CHAIN = ["kaldiio==2.18.1", "kaldi-native-fbank==1.22.3",
                 "soundfile==0.14.0", "sentencepiece==0.2.2",
                 "textgrid==1.6.1"]
MAIN_RUNTIME = MAIN_CONTRACT + FIRERED_CHAIN + [
    "torch==2.11.0+cpu", "torchaudio==2.11.0+cpu"]


def _probe_with(monkeypatch, role, python_executable):
    """重定向环境解释器到测试 venv，执行 deep preflight。"""
    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(python_executable))
    env_module.reset_preflight_cache()
    return env_module.deep_preflight(role)


# ---------------------------------------------------------------- 契约 reader

def test_contract_reader_matches_lock(tmp_path):
    """Python reader 与 dependencies.lock.json 同源（无硬编码版本）。"""
    contract = env_module.environments_contract("main")
    assert contract["packages"]["transformers"] == "4.57.6"
    assert contract["packages"]["huggingface_hub"] == "0.36.2"
    contract = env_module.environments_contract("moss")
    assert contract["packages"]["transformers"] == "5.14.1"
    assert contract["packages"]["huggingface_hub"] == "1.24.0"


def test_contract_reader_missing_role_fails_closed(tmp_path):
    with pytest.raises(env_module.EnvironmentContractError):
        env_module.environments_contract("no_such_role")


def test_required_roles_depend_on_configuration():
    """Only environments used by the selected Primary/Review roles are required."""
    assert env_module.required_environment_roles(None) == ["main"]
    assert env_module.required_environment_roles(
        {"models": {"primary_asr_backend": "moss"}}) == ["main", "moss"]
    assert env_module.required_environment_roles(
        {"models": {"primary_asr_backend": "firered"}}) == ["main"]
    assert env_module.required_environment_roles(
        {"models": {"primary_asr_backend": "firered_llm"}}
    ) == ["main", "firered_llm"]
    assert env_module.required_environment_roles(
        {
            "models": {
                "primary_asr_backend": "moss",
                "qwen_asr_backend": "firered_llm",
            }
        }
    ) == ["main", "moss", "firered_llm"]


def test_human_message_is_structured():
    result = env_module.PreflightResult(
        role="moss", ok=False,
        problems=["huggingface_hub: version 0.36.2 != contract 1.24.0"],
    )
    message = env_module.human_message(result)
    assert "MOSS" in message
    assert "0.36.2" in message
    assert "1.24.0" in message


# ---------------------------------------------------------------- 坏/好环境 probe（真实隔离 venv）

def test_case_a_bad_main_missing_transformers_fails(tmp_path, monkeypatch):
    """A：main 缺 transformers → deep fail。"""
    python = _make_venv(tmp_path, "bad_main")
    _pip_offline(python, ["numpy==2.2.6", "requests==2.33.0"])  # 无 transformers
    result = _probe_with(monkeypatch, "main", python)
    assert not result.ok
    assert any("transformers" in p for p in result.problems)


def test_case_b_bad_main_wrong_transformers_version_fails(tmp_path, monkeypatch):
    """B：main transformers 版本错误 → fail（区分"未安装"与"版本错误"）。"""
    python = _make_venv(tmp_path, "bad_main_ver")
    _pip_offline(python, ["transformers==5.14.1", "huggingface_hub==1.24.0",
                          "tokenizers==0.22.2", "safetensors==0.8.0"])
    result = _probe_with(monkeypatch, "main", python)
    assert not result.ok
    assert any("4.57.6" in p and "5.14.1" in p for p in result.problems)


def test_case_c_bad_moss_wrong_hub_version_fails(tmp_path, monkeypatch):
    """C：moss transformers 5.14.1 + hub 0.36.2（用户错误 B 组合）→ fail。

    坏组合必须分两步构造（与真实旧安装流程一致）：单条命令装两者时
    pip 解析器会直接拒绝（ResolutionImpossible）。
    """
    python = _moss_venv(tmp_path, "bad_moss")
    _pip_offline(python, ["transformers==5.14.1", "tokenizers==0.22.2", "safetensors==0.8.0"])
    _pip_offline(python, ["huggingface_hub==0.36.2"])  # 旧脚本 127 行的降级
    result = _probe_with(monkeypatch, "moss", python)
    assert not result.ok
    assert any("huggingface_hub" in p and "0.36.2" in p for p in result.problems)


def test_case_d_moss_future_transformers_fails_contract(tmp_path, monkeypatch):
    """D：moss transformers 非契约版本（即使满足 pyproject 范围）→ 不符 lock fail。

    非契约组合分两步安装（pip 单条命令会拒绝该组合，与真实漂移路径一致）。
    """
    python = _moss_venv(tmp_path, "bad_moss_future")
    _pip_offline(python, ["transformers==4.57.6", "tokenizers==0.22.2", "safetensors==0.8.0"])
    _pip_offline(python, ["huggingface_hub==1.24.0"])
    result = _probe_with(monkeypatch, "moss", python)
    assert not result.ok
    assert any("transformers" in p and "5.14.1" in p for p in result.problems)


def test_case_healthy_main_passes(tmp_path, monkeypatch):
    python = _make_venv(tmp_path, "healthy_main")
    _pip_offline(python, MAIN_RUNTIME)
    result = _probe_with(monkeypatch, "main", python)
    assert result.ok, f"healthy main 应通过：{result.problems}"


def test_case_moss_package_contract_still_requires_cuda(tmp_path, monkeypatch):
    python = _moss_venv(tmp_path, "healthy_moss")
    _pip_offline(python, MOSS_CONTRACT + ["torch==2.11.0+cpu"])
    assert _moss_editable_offline(python).returncode == 0, "editable 安装失败"
    result = _probe_with(monkeypatch, "moss", python)
    assert not result.ok
    assert result.detail["packages"]["transformers"] == "5.14.1"
    assert result.detail["packages"]["huggingface_hub"] == "1.24.0"
    assert result.detail["imports"]["moss_transcribe"] is True
    assert any("CPU-only torch" in problem for problem in result.problems)


def test_case_k_version_ok_but_import_fails(tmp_path, monkeypatch):
    """K：契约版本完整但 torch import 缺失时仍必须失败。"""
    python = _make_venv(tmp_path, "import_fail")
    _pip_offline(python, MAIN_CONTRACT)
    result = _probe_with(monkeypatch, "main", python)
    assert not result.ok
    assert any("torch: import failed" in p for p in result.problems)


def test_main_probe_does_not_require_optional_firered_runtime(monkeypatch):
    """Fresh Setup is a lightweight workbench; model runtimes are installed later."""
    monkeypatch.setattr(env_module, "_installed_version", lambda _name: None, raising=False)
    result = probe_module.run(
        "main",
        {"python": f"{sys.version_info.major}.{sys.version_info.minor}"},
        firered_source_dir=str(PROJECT_ROOT / "missing-firered-source"),
    )
    assert "firered_vad" not in result["imports"]
    assert not any("fireredasr2s" in problem for problem in result["errors"])


def test_firered_probe_uses_firered_adapter_and_never_moss(monkeypatch, tmp_path):
    """FireRed health checks must never leak through the MOSS probe branch."""
    imported = []

    monkeypatch.setattr(probe_module, "_installed_version", lambda _name: None)
    monkeypatch.setattr(probe_module, "_import_ok", lambda name: imported.append(name) or True)
    monkeypatch.setattr(
        probe_module,
        "_import_attr_ok",
        lambda module, attr: imported.append(f"{module}.{attr}") or True,
    )
    monkeypatch.setattr(probe_module, "_strict_cuda_probe", lambda *_args: None)

    result = probe_module.run(
        "firered_llm",
        {"python": f"{sys.version_info.major}.{sys.version_info.minor}"},
        firered_source_dir=str(tmp_path / "FireRedASR2S"),
    )

    assert result["probe_module"] == "fireredasr2s.fireredasr2.FireRedAsr2"
    assert result["imports"]["firered_llm_adapter"] is True
    assert "fireredasr2s.fireredasr2.FireRedAsr2" in imported
    assert all("moss_transcribe_diarize" not in item for item in imported)
    assert not any("moss_transcribe_diarize" in item for item in result["errors"])


def test_firered_runtime_trace_is_complete_and_role_specific(tmp_path):
    interpreter = str(tmp_path / ".venv-firered-llm" / "Scripts" / "python.exe")
    staging = str(tmp_path / ".venv-firered-llm.new")
    trace = env_module.runtime_trace(
        "firered_llm", interpreter=interpreter, repair_target=staging
    )
    assert trace == {
        "model_id": "firered_llm",
        "runtime_id": "firered_llm",
        "python_executable": interpreter,
        "probe_module": "fireredasr2s.fireredasr2.FireRedAsr2",
        "repair_target": staging,
    }


def test_case_i_missing_interpreter_fails_clearly(tmp_path, monkeypatch):
    """I：interpreter 路径不存在 → 明确错误（无 traceback）。"""
    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(tmp_path / "missing" / "python.exe"))
    env_module.reset_preflight_cache()
    result = env_module.deep_preflight("main")
    assert not result.ok
    assert any("解释器缺失" in p for p in result.problems)


def test_case_j_probe_timeout_is_bounded(tmp_path, monkeypatch):
    """J：probe 超时 → 进程终止、有界返回。"""
    class _HangProcess:
        def __init__(self, *a, **k):
            self.returncode = None
            self.pid = 424243
            self.killed = False

        def communicate(self, *a, **k):
            raise subprocess.TimeoutExpired("python", 60)

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    created = []

    def fake_popen(command, **kwargs):
        process = _HangProcess()
        created.append(process)
        return process

    monkeypatch.setattr(env_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(PYTHON))
    monkeypatch.setattr("twobyteasr.system.processes.subprocess.run", lambda *a, **k: None)
    env_module.reset_preflight_cache()
    result = env_module.deep_preflight("main")
    assert not result.ok
    assert any("超时" in p for p in result.problems)
    assert created[0].killed or created[0].wait(0) == 0


# ---------------------------------------------------------------- 缓存 / fast path

def test_case_g_h_n_cache_semantics(tmp_path, monkeypatch):
    """G/H/N：deep 成功后 fast path 复用；lock hash 变化使缓存失效。"""
    python = _make_venv(tmp_path, "cache_env")
    _pip_offline(python, MAIN_RUNTIME)
    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(python))
    env_module.reset_preflight_cache()
    probes = {"count": 0}
    original = env_module._run_probe_process

    def counting_probe(role, contract, **kwargs):
        probes["count"] += 1
        return original(role, contract, **kwargs)

    monkeypatch.setattr(env_module, "_run_probe_process", counting_probe)

    first = env_module.preflight("main")
    assert first.ok and probes["count"] == 1
    # N：第二次（缓存命中）不再执行 deep probe
    second = env_module.preflight("main")
    assert second.ok and probes["count"] == 1, "fast path 不得重复 deep probe"
    # H：environments hash 变化 → 缓存失效 → 重新 deep
    monkeypatch.setattr(env_module, "environments_hash", lambda: "different-hash")
    third = env_module.preflight("main")
    assert third.ok and probes["count"] == 2, "lock 变化后必须重新 deep"


# ---------------------------------------------------------------- service guard

def _fake_legacy(primary_backend):
    """服务层 guard 测试共享的 FakeLegacy（覆盖 queue 全路径所需属性）。"""

    class FakeLegacy:
        # The current queue freezes an explicitly selected provider first.
        # This fake pipeline never invokes it; it only exercises env guards.
        RUNTIME_SETTINGS = {"models": {"primary_asr_backend": primary_backend,"ai_service":"grok_account"}}
        HF_TOKEN = ""

        @staticmethod
        def run_event_observer(cb):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return _Ctx()

        @staticmethod
        def run_startup_self_test():
            return {"id": "x", "checks": 1}

        @staticmethod
        def begin_run_event_log():
            return ""

        @staticmethod
        def record_run_event(*a, **k):
            pass

        @staticmethod
        def runtime_content_profile_signature():
            return {}

        @staticmethod
        def runtime_settings_snapshot():
            return {}

        @staticmethod
        def cleanup_old_cache():
            pass

        @staticmethod
        def finish_media_report(*a, **k):
            return "", ""

        @staticmethod
        def output_paths_for_media(path):
            return path + ".txt", path + ".srt"

        @staticmethod
        def format_elapsed(seconds):
            return str(seconds)

        @staticmethod
        def reset_review_items():
            pass

        @staticmethod
        def run_timed_stage(*a, **k):
            return []

        @staticmethod
        def print_review_summary():
            return []

        @staticmethod
        def write_all_outputs_transactional(*a, **k):
            return {}

        @staticmethod
        def begin_local_asr_session():
            pass

        @staticmethod
        def end_local_asr_session():
            pass

        class task_reporting:
            @staticmethod
            def report_paths_for_media(path):
                return "", ""

    return FakeLegacy


def _fake_pipeline(fail_check_runtime=False):
    class FakePipeline:
        @staticmethod
        def set_cancellation_token(token):
            pass

        @staticmethod
        def check_runtime(legacy):
            if fail_check_runtime:
                raise AssertionError("check_runtime 不得在 preflight 失败后执行")

        @staticmethod
        def precompute_moss_batch_cache(*a, **k):
            pass

        @staticmethod
        def process_media(media, index, total, legacy, **k):
            return media + ".txt", media + ".srt", 0.1

    return FakePipeline


def test_case_l_m_service_guard_blocks_and_no_fallback(tmp_path, monkeypatch):
    """L/M：坏环境 + guard → 任务在 pipeline 前被阻断；系统 Python 正常也不 fallback。"""
    from twobyteasr.recognition import service as service_module

    bad_python = _make_venv(tmp_path, "guard_bad_main")
    _pip_offline(bad_python, ["numpy==2.2.6"])  # 缺 transformers

    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(bad_python))
    env_module.reset_preflight_cache()
    result = service_module.run_media_queue(
        ["media.mp4"],
        _legacy=_fake_legacy("moss")(),
        _pipeline=_fake_pipeline(fail_check_runtime=True)(),
    )
    assert all(item.status == "failed" for item in result.results)
    assert any("运行环境" in item.error for item in result.results), (
        "错误必须指出运行环境问题（不 fallback、无 traceback 作为唯一信息）"
    )


def test_case_f_moss_broken_does_not_block_firered_only(tmp_path, monkeypatch):
    """F：main OK/moss bad 但配置不用 moss → 不阻断。"""
    from twobyteasr.recognition import service as service_module

    main_python = _make_venv(tmp_path, "guard_ok_main")
    _pip_offline(main_python, MAIN_RUNTIME)

    monkeypatch.setattr(env_module, "environment_interpreter",
                        lambda _role: str(main_python))
    env_module.reset_preflight_cache()
    result = service_module.run_media_queue(
        ["media.mp4"],
        _legacy=_fake_legacy("firered")(),
        _pipeline=_fake_pipeline()(),
    )
    assert result.exit_code == 0, "firered-only 配置不得被 moss 缺失阻断"
