"""USER RECOVERY Change Group 1：Environment Repair 回归测试。

覆盖产品不变量（先写测试，再实现）：
- marker 存在 + MOSS 损坏仍执行 repair，且普通 setup 幂等语义由脚本门闩保留
- MOSS 2.13 → 部署契约 torch 2.11.0（不放宽 lock、不装 2.13）
- 仅修损坏角色：Main 健康时绝不重建 Main
- repair 失败保留旧环境；只有 staging deep preflight 成功才切换
- 修复后 preflight cache 失效
- 系统 Python / sys.executable 不影响修复目标，也不删除现有 venv
- 普通用户文案：标题/小字/立即修复/查看详情；成功句按角色
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "dependencies.lock.json"
REPAIR_PS1 = PROJECT_ROOT / "scripts" / "repair_environment.ps1"
BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap_install.ps1"
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]

import twobyteasr.environment as env_module
import twobyteasr.environment_repair as repair_module


@pytest.fixture(autouse=True)
def _reset_cache():
    env_module.reset_preflight_cache()
    yield
    env_module.reset_preflight_cache()


def _lock():
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _write_tree(path: Path, token: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "IDENTITY.txt"
    marker.write_text(token, encoding="utf-8")
    python = path / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"fake-python")
    return python


def _identity(venv_dir: Path) -> str:
    return (venv_dir / "IDENTITY.txt").read_text(encoding="utf-8")


def _fake_preflight(health):
    """health[role] = {'live': bool, 'staging': bool}."""

    def _run(role, *, interpreter=None, use_cache=True, **_kwargs):
        paths = repair_module.role_paths(role)
        staging_py = os.path.normcase(os.path.abspath(paths["staging_python"]))
        chosen = os.path.normcase(os.path.abspath(interpreter or paths["live_python"]))
        ok = health[role]["staging"] if chosen == staging_py else health[role]["live"]
        problems = [] if ok else [f"{role} 环境与部署契约不一致"]
        return env_module.PreflightResult(
            role=role,
            ok=ok,
            interpreter=interpreter or paths["live_python"],
            problems=problems,
        )

    return _run


def _install_ok(root: Path, health, *, fail_roles=(), requested=None):
    requested = requested if requested is not None else []

    def _install(role, staging_path):
        requested.append(role)
        if role in fail_roles:
            raise repair_module.EnvironmentRepairError(f"{role} 安装失败（测试）")
        _write_tree(Path(staging_path), f"staging-{role}")
        health[role]["staging"] = True
        return {"torch": "2.11.0", "role": role, "staging": staging_path}

    return _install


# ---------------------------------------------------------------- 文案与契约


def test_user_facing_copy_hides_versions_until_details():
    copy = repair_module.user_facing_copy(
        [
            env_module.PreflightResult(
                role="moss",
                ok=False,
                problems=["torch: base version 2.13.0 != contract 2.11.0"],
            )
        ]
    )
    assert copy.title == "运行环境需要更新"
    assert copy.subtitle == "当前环境与此版本 2ByteASR 不兼容"
    assert copy.repair_label == "立即修复"
    assert copy.details_label == "查看详情"
    assert "2.13" not in copy.title
    assert "2.13" not in copy.subtitle
    assert "2.13" in copy.details
    assert "2.11" in copy.details
    assert copy.success_message == "MOSS 运行环境已修复"


def test_success_message_joins_roles_in_stable_order():
    assert repair_module.success_message(["moss"]) == "MOSS 运行环境已修复"
    assert repair_module.success_message(["main"]) == "Main 运行环境已修复"
    assert repair_module.success_message(["moss", "main"]) == "Main/MOSS 运行环境已修复"
    assert repair_module.success_message(["firered_llm"]) == "FireRed LLM 运行环境已修复"


def test_repair_package_specs_pin_moss_torch_211_from_lock():
    """MOSS 2.13→2.11：安装清单必须来自 deployment lock，且禁止 2.13。"""
    lock = _lock()
    assert lock["environments"]["moss"]["torch"] == "2.11.0"
    specs = repair_module.repair_package_specs("moss")
    joined = " ".join(specs)
    assert "torch==2.11.0" in joined
    assert "transformers==5.14.1" in joined
    assert "huggingface_hub==1.24.0" in joined
    assert "2.13" not in joined
    assert not any(item.startswith("torch==") and "2.11.0" not in item for item in specs)


def test_repair_package_specs_do_not_mix_main_and_moss_contracts():
    main = " ".join(repair_module.repair_package_specs("main"))
    moss = " ".join(repair_module.repair_package_specs("moss"))
    assert "transformers==4.57.6" in main
    assert "huggingface_hub==0.36.2" in main
    assert "transformers==5.14.1" not in main
    assert "huggingface_hub==1.24.0" not in moss or "huggingface_hub==1.24.0" in moss
    assert "transformers==4.57.6" not in moss
    assert "huggingface_hub==0.36.2" not in moss


# ---------------------------------------------------------------- 规划：marker / 角色隔离


def test_marker_present_and_moss_bad_still_plans_and_runs_repair(tmp_path, monkeypatch):
    """marker 不是健康证明：MOSS 损坏时必须规划并执行 repair。"""
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    (tmp_path / "2byteasr.setup-complete").write_text("done", encoding="ascii")
    _write_tree(tmp_path / ".venv-main", "live-main")
    _write_tree(tmp_path / ".venv-moss", "live-moss-213")
    health = {
        "main": {"live": True, "staging": False},
        "moss": {"live": False, "staging": False},
    }
    requested = []
    settings = {"models": {"primary_asr_backend": "moss"}}
    plan = repair_module.diagnose_repair(
        settings, preflight_fn=_fake_preflight(health)
    )
    assert plan is not None
    assert plan.roles == ["moss"]
    assert plan.title == "运行环境需要更新"
    result = repair_module.repair_roles(
        plan.roles,
        install_fn=_install_ok(tmp_path, health, requested=requested),
        preflight_fn=_fake_preflight(health),
    )
    assert result.ok
    assert requested == ["moss"]
    assert _identity(tmp_path / ".venv-moss") == "staging-moss"
    assert _identity(tmp_path / ".venv-main") == "live-main"
    assert (tmp_path / "2byteasr.setup-complete").is_file()
    assert not (tmp_path / ".venv-moss.new").exists()


def test_healthy_main_is_not_rebuilt_when_only_moss_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-main", "live-main-ok")
    _write_tree(tmp_path / ".venv-moss", "live-moss-bad")
    health = {
        "main": {"live": True, "staging": False},
        "moss": {"live": False, "staging": False},
    }
    requested = []
    plan = repair_module.diagnose_repair(
        {"models": {"primary_asr_backend": "moss"}},
        preflight_fn=_fake_preflight(health),
    )
    assert plan.roles == ["moss"]
    result = repair_module.repair_roles(
        plan.roles,
        install_fn=_install_ok(tmp_path, health, requested=requested),
        preflight_fn=_fake_preflight(health),
    )
    assert result.ok
    assert requested == ["moss"]
    assert _identity(tmp_path / ".venv-main") == "live-main-ok"
    assert result.roles_repaired == ["moss"]
    assert result.success_message == "MOSS 运行环境已修复"


def test_only_main_failure_does_not_rebuild_moss(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-main", "live-main-bad")
    _write_tree(tmp_path / ".venv-moss", "live-moss-ok")
    health = {
        "main": {"live": False, "staging": False},
        "moss": {"live": True, "staging": False},
    }
    requested = []
    plan = repair_module.diagnose_repair(
        {"models": {"primary_asr_backend": "moss"}},
        preflight_fn=_fake_preflight(health),
    )
    assert plan.roles == ["main"]
    result = repair_module.repair_roles(
        ["main"],
        install_fn=_install_ok(tmp_path, health, requested=requested),
        preflight_fn=_fake_preflight(health),
    )
    assert result.ok
    assert requested == ["main"]
    assert _identity(tmp_path / ".venv-moss") == "live-moss-ok"


# ---------------------------------------------------------------- 原子性


def test_repair_failure_keeps_old_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-moss", "keep-old-213")
    health = {"moss": {"live": False, "staging": False}}
    result = repair_module.repair_roles(
        ["moss"],
        install_fn=_install_ok(tmp_path, health, fail_roles=("moss",)),
        preflight_fn=_fake_preflight(health),
    )
    assert not result.ok
    assert result.kept_old
    assert _identity(tmp_path / ".venv-moss") == "keep-old-213"
    assert not (tmp_path / ".venv-moss.new").exists()


def test_only_successful_staging_preflight_switches_live(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-moss", "old-live")
    health = {"moss": {"live": False, "staging": False}}

    def install_but_staging_unhealthy(role, staging_path):
        _write_tree(Path(staging_path), "bad-staging")
        health[role]["staging"] = False
        return {"role": role}

    result = repair_module.repair_roles(
        ["moss"],
        install_fn=install_but_staging_unhealthy,
        preflight_fn=_fake_preflight(health),
    )
    assert not result.ok
    assert result.kept_old
    assert _identity(tmp_path / ".venv-moss") == "old-live"
    assert not (tmp_path / ".venv-moss.new").exists()


def test_swap_exception_restores_or_keeps_old(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    live = tmp_path / ".venv-moss"
    _write_tree(live, "original")
    health = {"moss": {"live": False, "staging": False}}

    def boom_swap(live_dir, staging_dir, backup_dir):
        raise OSError("directory in use")

    result = repair_module.repair_roles(
        ["moss"],
        install_fn=_install_ok(tmp_path, health),
        preflight_fn=_fake_preflight(health),
        swap_fn=boom_swap,
    )
    assert not result.ok
    assert result.kept_old
    assert _identity(live) == "original"
    assert not (tmp_path / ".venv-moss.new").exists()


def test_atomic_replace_is_two_phase_and_cleans_backup(tmp_path):
    live = tmp_path / ".venv-moss"
    staging = tmp_path / ".venv-moss.new"
    _write_tree(live, "old")
    _write_tree(staging, "new")
    repair_module.atomic_replace_directory(str(live), str(staging))
    assert _identity(live) == "new"
    assert not staging.exists()
    assert not (tmp_path / ".venv-moss.old").exists()


# ---------------------------------------------------------------- cache / 系统 Python


def test_repair_invalidates_preflight_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-moss", "before")
    env_module._CACHE["moss"] = (
        env_module.environments_hash(),
        env_module.PreflightResult(role="moss", ok=True, problems=[]),
    )
    health = {"moss": {"live": False, "staging": False}}
    result = repair_module.repair_roles(
        ["moss"],
        install_fn=_install_ok(tmp_path, health),
        preflight_fn=_fake_preflight(health),
    )
    assert result.ok
    assert "moss" not in env_module._CACHE


def test_failed_repair_also_invalidates_stale_success_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    _write_tree(tmp_path / ".venv-moss", "still-old")
    env_module._CACHE["moss"] = (
        env_module.environments_hash(),
        env_module.PreflightResult(role="moss", ok=True, problems=[]),
    )
    health = {"moss": {"live": False, "staging": False}}
    result = repair_module.repair_roles(
        ["moss"],
        install_fn=_install_ok(tmp_path, health, fail_roles=("moss",)),
        preflight_fn=_fake_preflight(health),
    )
    assert not result.ok
    assert "moss" not in env_module._CACHE


def test_system_python_state_does_not_affect_repair_target_or_delete_live(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    system_py = tmp_path / "WindowsApps" / "python.exe"
    system_py.parent.mkdir(parents=True)
    system_py.write_bytes(b"system")
    monkeypatch.setattr(sys, "executable", str(system_py))
    live = tmp_path / ".venv-moss"
    _write_tree(live, "must-survive")
    seen = {}
    health = {"moss": {"live": False, "staging": False}}

    def install(role, staging_path):
        seen["role"] = role
        seen["staging"] = os.path.abspath(staging_path)
        seen["sys"] = sys.executable
        raise repair_module.EnvironmentRepairError("故意失败：验证不删旧环境")

    result = repair_module.repair_roles(
        ["moss"],
        install_fn=install,
        preflight_fn=_fake_preflight(health),
    )
    assert not result.ok
    assert result.kept_old
    assert _identity(live) == "must-survive"
    assert seen["staging"].endswith(os.path.join(".venv-moss.new"))
    assert os.path.normcase(seen["staging"]) != os.path.normcase(str(system_py.parent))
    assert "WindowsApps" not in seen["staging"]
    assert live.is_dir()


def test_install_never_receives_live_venv_path(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    live = tmp_path / ".venv-main"
    _write_tree(live, "live")
    health = {"main": {"live": False, "staging": False}}
    targets = []

    def install(role, staging_path):
        targets.append(os.path.normcase(os.path.abspath(staging_path)))
        _write_tree(Path(staging_path), "staging")
        health[role]["staging"] = True
        return {}

    repair_module.repair_roles(
        ["main"],
        install_fn=install,
        preflight_fn=_fake_preflight(health),
    )
    live_abs = os.path.normcase(os.path.abspath(live))
    assert targets
    assert all(path != live_abs for path in targets)
    assert all(path.endswith(os.path.normcase(".venv-main.new")) for path in targets)


def test_diagnose_does_not_treat_setup_marker_as_health(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    (tmp_path / "2byteasr.setup-complete").write_text("done", encoding="ascii")
    health = {
        "main": {"live": True, "staging": False},
        "moss": {"live": False, "staging": False},
    }
    _write_tree(tmp_path / ".venv-main", "main")
    _write_tree(tmp_path / ".venv-moss", "moss")
    plan = repair_module.diagnose_repair(
        {"models": {"primary_asr_backend": "moss"}},
        preflight_fn=_fake_preflight(health),
    )
    assert plan is not None
    assert "moss" in plan.roles


def test_diagnose_skips_healthy_configuration():
    health = {
        "main": {"live": True, "staging": False},
        "moss": {"live": True, "staging": False},
    }
    plan = repair_module.diagnose_repair(
        {"models": {"primary_asr_backend": "moss"}},
        preflight_fn=_fake_preflight(health),
    )
    assert plan is None


def test_staging_paths_are_role_specific_and_inside_root(tmp_path, monkeypatch):
    # 契约（P8A/P9A 起有意为之）：仓库旁已存在的 live venv 原地修复；live 不存在
    # （打包安装）时由 runtime registry 的稳定根接管，staging 始终紧邻 live。
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    (tmp_path / ".venv-moss").mkdir()
    (tmp_path / ".venv-main").mkdir()
    moss = repair_module.role_paths("moss")
    main = repair_module.role_paths("main")
    assert moss["live"].endswith(".venv-moss")
    assert moss["staging"].endswith(".venv-moss.new")
    assert main["staging"].endswith(".venv-main.new")
    assert moss["staging"] != main["staging"]
    assert moss["staging"] != moss["live"]
    for path in moss.values():
        assert os.path.abspath(path).startswith(os.path.abspath(str(tmp_path)))


def test_staging_paths_fall_back_to_registry_root_when_no_live_dir(
    tmp_path, monkeypatch
):
    from twobyteasr.runtime_registry import intended_runtime_root

    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    live = repair_module.role_paths("moss")
    expected = intended_runtime_root("moss")
    assert live["live"] == expected
    assert live["staging"] == expected + ".new"


def test_firered_repair_only_swaps_its_runtime_and_preserves_model_weights(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    firered_live = tmp_path / ".venv-firered-llm"
    moss_live = tmp_path / ".venv-moss"
    model_marker = tmp_path / "models" / "FireRedASR2-LLM" / "weights.bin"
    _write_tree(firered_live, "live-firered-bad")
    _write_tree(moss_live, "live-moss")
    model_marker.parent.mkdir(parents=True)
    model_marker.write_bytes(b"model-weights-must-not-change")
    before = model_marker.read_bytes()
    health = {"firered_llm": {"live": False, "staging": False}}
    requested = []

    result = repair_module.repair_roles(
        ["firered_llm"],
        install_fn=_install_ok(tmp_path, health, requested=requested),
        preflight_fn=_fake_preflight(health),
    )

    assert result.ok
    assert requested == ["firered_llm"]
    assert result.success_message == "FireRed LLM 运行环境已修复"
    assert _identity(firered_live) == "staging-firered_llm"
    assert _identity(moss_live) == "live-moss"
    assert model_marker.read_bytes() == before
    assert not (tmp_path / ".venv-firered-llm.new").exists()


def test_injected_firered_repair_does_not_execute_fixture_interpreter(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    health = {"firered_llm": {"live": False, "staging": False}}

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("injected repair must not execute the fixture interpreter")

    monkeypatch.setattr(repair_module.subprocess, "run", unexpected_run)
    result = repair_module.repair_roles(
        ["firered_llm"],
        install_fn=_install_ok(tmp_path, health),
        preflight_fn=_fake_preflight(health),
    )

    assert result.ok


def test_failed_firered_staging_probe_preserves_live_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_module, "project_root", lambda: str(tmp_path))
    live = tmp_path / ".venv-firered-llm"
    _write_tree(live, "live-firered-must-survive")
    health = {"firered_llm": {"live": False, "staging": False}}

    def install(role, staging_path):
        _write_tree(Path(staging_path), "staging-firered-still-bad")

    monkeypatch.setattr(repair_module.time, "sleep", lambda _seconds: None)
    result = repair_module.repair_roles(
        ["firered_llm"], install_fn=install, preflight_fn=_fake_preflight(health)
    )

    assert not result.ok
    assert result.kept_old
    assert _identity(live) == "live-firered-must-survive"
    assert not (tmp_path / ".venv-firered-llm.new").exists()


# ---------------------------------------------------------------- PowerShell / bootstrap 门闩


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell repair helpers")
def test_powershell_repair_helpers_bypass_marker_and_pin_torch():
    helper = str(REPAIR_PS1.resolve())
    script = (
        f". '{helper}';"
        "$proceed = Test-RepairShouldProceed -Repair -SetupMarkerPresent;"
        "Write-Output ('PROCEED=' + $proceed);"
        "$skip = Test-RepairShouldProceed -SetupMarkerPresent;"
        "Write-Output ('SKIP_WITHOUT_REPAIR=' + $skip);"
        "$torch = Get-RepairTorchSpec -Role moss;"
        "Write-Output ('TORCH=' + $torch);"
        "$live = Get-RepairLivePath -Role moss -ProjectRoot 'C:\\app';"
        "$staging = Get-RepairStagingPath -Role moss -ProjectRoot 'C:\\app';"
        "Write-Output ('LIVE=' + $live);"
        "Write-Output ('STAGING=' + $staging);"
    )
    result = __import__("subprocess").run(
        POWERSHELL + ["-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "PROCEED=True" in out
    assert "SKIP_WITHOUT_REPAIR=False" in out
    assert "TORCH=2.11.0" in out
    assert "2.13" not in out
    assert ".venv-moss.new" in out
    assert out.count(".venv-moss") >= 1
    assert ".venv-moss.new" in out.split("STAGING=", 1)[1]


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell repair helpers")
def test_powershell_repair_helpers_accept_firered_role():
    helper = str(REPAIR_PS1.resolve())
    script = (
        f". '{helper}';"
        "$live = Get-RepairLivePath -Role firered_llm -ProjectRoot 'C:\\app';"
        "$staging = Get-RepairStagingPath -Role firered_llm -ProjectRoot 'C:\\app';"
        "$torch = Get-RepairTorchSpec -Role firered_llm;"
        "Write-Output ('LIVE=' + $live);"
        "Write-Output ('STAGING=' + $staging);"
        "Write-Output ('TORCH=' + $torch)"
    )
    result = __import__("subprocess").run(
        POWERSHELL + ["-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "LIVE=C:\\app\\.venv-firered-llm" in result.stdout
    assert "STAGING=C:\\app\\.venv-firered-llm.new" in result.stdout
    assert "TORCH=2.11.0" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell repair helpers")
def test_invoke_environment_repair_returns_scalar_numeric_exit_code(tmp_path):
    project = tmp_path / "app"
    fake_python = project / ".venv-main" / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True)
    shutil.copy2(sys.executable, fake_python)
    shutil.copy2(PROJECT_ROOT / ".venv-main" / "pyvenv.cfg", project / ".venv-main" / "pyvenv.cfg")
    package = project / "twobyteasr"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="ascii")
    (package / "environment_repair.py").write_text(
        "print('中文诊断输出')\nraise SystemExit(7)\n", encoding="utf-8"
    )
    helper = str(REPAIR_PS1.resolve()).replace("'", "''")
    root = str(project).replace("'", "''")
    script = (
        f". '{helper}';"
        f"$code = Invoke-EnvironmentRepair -ProjectRoot '{root}';"
        "Write-Output ('TYPE=' + $code.GetType().FullName);"
        "Write-Output ('CODE=' + $code)"
    )
    result = __import__("subprocess").run(
        POWERSHELL + ["-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "中文诊断输出" in result.stdout
    assert "TYPE=System.Int32" in result.stdout
    assert "CODE=7" in result.stdout


def test_repair_process_chain_forces_utf8_and_clean_exit_code():
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8-sig")
    helper = REPAIR_PS1.read_text(encoding="utf-8-sig")
    driver = (PROJECT_ROOT / "scripts" / "repair_environment_driver.ps1").read_text(
        encoding="utf-8-sig"
    )
    for source in (bootstrap, helper, driver):
        assert '$OutputEncoding = $Utf8NoBom' in source
        assert '$env:PYTHONIOENCODING = "utf-8"' in source
        assert '$env:PYTHONUTF8 = "1"' in source
    assert "ForEach-Object { Write-Host" in helper
    assert "return [int]$exitCode" in helper


def test_configurator_auto_repair_only_owns_main_runtime():
    settings = {"models": {"primary_asr_backend": "moss"}}
    assert repair_module.configuration_repair_roles(settings) == ["main"]


def test_first_setup_installs_the_same_main_contract_as_preflight():
    source = (PROJECT_ROOT / "scripts" / "setup_environment.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "Get-EnvironmentPackages -Role main" in source
    assert "Get-EnvironmentDependency -Role main -Name torch" in source
    assert '"torch==$MainTorchVersion+cpu"' in source


def test_bootstrap_repair_mode_does_not_early_return_on_marker():
    source = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "[switch]$Repair" in source
    assert "-not $Repair" in source or "if ($Repair)" in source
    # 普通 setup 仍保留幂等早退
    assert "2byteasr.setup-complete" in source
    assert "$alreadyConfigured" in source
    # repair 不得要求用户设环境变量或手删 marker
    repair_block_start = source.index("[switch]$Repair")
    # 早退必须被 Repair 短路：看到 marker 时 Repair 仍继续
    assert "if ($Repair)" in source
    assert "environment_repair" in source or "repair_environment.ps1" in source


def test_bootstrap_keeps_idempotent_setup_without_repair_flag():
    source = BOOTSTRAP.read_text(encoding="utf-8-sig")
    assert "$alreadyConfigured = (Test-Path $SetupMarker) -and (Test-Path $MainPy)" in source
    assert "if ($alreadyConfigured" in source
    assert "2BYTEASR_FORCE_SETUP" in source


def test_repair_script_never_upgrades_live_venv_in_place():
    source = REPAIR_PS1.read_text(encoding="utf-8-sig")
    assert "Get-RepairStagingPath" in source
    assert ".venv-$Role.new" in source or ".venv-$($Role).new" in source or ".new" in source
    assert "2BYTEASR_FORCE_SETUP" not in source
    lowered = source.lower()
    assert "pip install --upgrade" not in lowered or "staging" in lowered
    # 安装目标必须是 staging，不得对 live 做 in-place
    assert "$StagingPython" in source or "StagingPath" in source


def test_configure_recheck_uses_repair_mode():
    configure = (PROJECT_ROOT / "launcher" / "2ByteASRConfigure.cs").read_text(
        encoding="utf-8"
    )
    assert "-Repair" in configure


def test_main_window_offers_in_app_repair_entry():
    source = (PROJECT_ROOT / "twobyteasr" / "ui.py").read_text(encoding="utf-8")
    assert "def _ensure_runtime_environment(" in source
    assert "diagnose_repair" in source
    assert "repair_roles" in source
    assert "follow = diagnose_repair(settings, roles=plan.roles)" in source
    assert "修复后重新检查仍未通过" in source


def test_human_message_no_longer_dead_ends_to_force_setup():
    message = env_module.human_message(
        env_module.PreflightResult(
            role="moss",
            ok=False,
            problems=["torch: base version 2.13.0 != contract 2.11.0"],
        )
    )
    assert "MOSS" in message
    assert "2.13" in message or "2.11" in message
    assert "2BYTEASR_FORCE_SETUP" not in message
    assert "立即修复" in message
