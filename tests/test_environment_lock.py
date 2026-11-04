"""Phase A 回归测试：Main/MOSS 环境依赖契约（environments lock）。

安全语义（fail-closed）：
- dependencies.lock.json 的 environments 段是部署版本真相（== 精确版本）
- Main 契约：transformers==4.57.6 + huggingface_hub==0.36.2（错误 A 修复）
- MOSS 契约：transformers==5.14.1 + huggingface_hub==1.24.0（错误 B 修复，
  MOSS 不得再被安装 main 的 hub==0.36.2）
- wheels 多版本并存时，精确 == 版本保证解析确定（不漂移）
- lock 缺关键字段 → fail closed
- 全部离线（--no-index --find-links），不访问公网
"""

import json
import subprocess
import sys
import venv as venv_module
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "dependencies.lock.json"
HELPER = PROJECT_ROOT / "scripts" / "environment-lock.ps1"
WHEELS = PROJECT_ROOT / "wheels"
PYTHON = PROJECT_ROOT / ".venv-main" / "Scripts" / "python.exe"
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not PYTHON.is_file(),
    reason="需要 Windows 与本机主环境创建隔离 venv",
)


def _dot_source(script_text):
    """dot-source environment-lock.ps1 后执行断言脚本。"""
    helper = str(HELPER.resolve())
    return subprocess.run(
        POWERSHELL + ["-Command", f". '{helper}';" + script_text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _lock_copy(tmp_path, mutate=None):
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if mutate:
        mutate(lock)
    path = tmp_path / "dependencies.lock.json"
    path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
    return path


def _make_venv(tmp_path, name="env"):
    target = tmp_path / name
    builder = venv_module.EnvBuilder(with_pip=True)
    builder.create(str(target))
    return target / "Scripts" / "python.exe"


def _pip_install_offline(python, specs):
    return subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index",
         "--find-links", str(WHEELS)] + specs,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


def _import_version(python, module):
    result = subprocess.run(
        [str(python), "-c", f"import {module}; print({module}.__version__)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return result.returncode, result.stdout.strip()


# ---------------------------------------------------------------- 契约纯函数

def test_case_a_main_contract_has_transformers(tmp_path):
    """Case A：默认组合的 Main 契约必须包含 transformers（错误 A 修复）。"""
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    main_pkgs = lock["environments"]["main"]["packages"]
    assert main_pkgs["transformers"] == "4.57.6"
    assert main_pkgs["huggingface_hub"] == "0.36.2"
    result = _dot_source("(Get-EnvironmentPackages -Role main) -join ' '")
    assert "transformers==4.57.6" in result.stdout
    assert "huggingface_hub==0.36.2" in result.stdout


def test_case_d_moss_contract_uses_validated_combination(tmp_path):
    """Case C/D：MOSS 契约 = 已验证组合，不得是 main 的 hub pin。"""
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    moss_pkgs = lock["environments"]["moss"]["packages"]
    assert moss_pkgs["transformers"] == "5.14.1"
    assert moss_pkgs["huggingface_hub"] == "1.24.0"
    assert moss_pkgs["huggingface_hub"] != "0.36.2", "MOSS 不得使用 main 的 hub pin"
    result = _dot_source("(Get-EnvironmentPackages -Role moss) -join ' '")
    assert "transformers==5.14.1" in result.stdout
    assert "huggingface_hub==1.24.0" in result.stdout
    assert "huggingface_hub==0.36.2" not in result.stdout


def test_case_k_python_versions_in_lock(tmp_path):
    """Case K：Main 3.10 / MOSS 3.12 从 lock 确定。"""
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["environments"]["main"]["python"] == "3.10"
    assert lock["environments"]["moss"]["python"] == "3.12"
    result = _dot_source(
        "Get-EnvironmentDependency -Role main -Name python;"
        "Get-EnvironmentDependency -Role moss -Name python"
    )
    assert "3.10" in result.stdout and "3.12" in result.stdout


def test_case_g_lock_missing_main_transformers_fails_closed(tmp_path):
    """Case G：lock 缺 Main transformers → helper 抛异常。"""
    project = tmp_path / "repo"
    project.mkdir()
    _lock_copy(project, mutate=lambda lock: lock["environments"]["main"]["packages"].pop("transformers"))
    result = subprocess.run(
        POWERSHELL
        + [
            "-Command",
            f". '{HELPER.resolve()}';"
            f"try {{ Get-EnvironmentPackages -Role main -ProjectRoot '{project.resolve()}' | Out-Null; 'OK' }} "
            "catch { 'THREW' }",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert "THREW" in result.stdout, "lock 缺 transformers 必须 fail closed"


def test_case_h_lock_missing_moss_hub_fails_closed(tmp_path):
    """Case H：lock 缺 MOSS hub → helper 抛异常。"""
    project = tmp_path / "repo"
    project.mkdir()
    _lock_copy(project, mutate=lambda lock: lock["environments"]["moss"]["packages"].pop("huggingface_hub"))
    result = subprocess.run(
        POWERSHELL
        + [
            "-Command",
            f". '{HELPER.resolve()}';"
            "try { Get-EnvironmentDependency -Role moss -Name huggingface_hub "
            f"-ProjectRoot '{project.resolve()}' | Out-Null; 'OK' }} catch {{ 'THREW' }}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert "THREW" in result.stdout, "lock 缺 MOSS hub 必须 fail closed"


# ---------------------------------------------------------------- 多版本 wheels 解析（离线真实 venv）

def test_case_e_f_multiversion_wheels_resolve_exactly(tmp_path):
    """Case E/F：wheels 同时含两个 transformers/hub 版本时，精确 == 契约
    保证 main 得到 4.57.6/0.36.2、moss 得到 5.14.1/1.24.0，不漂移。"""
    main_py = _make_venv(tmp_path, "main")
    r1 = _pip_install_offline(
        main_py,
        ["transformers==4.57.6", "huggingface_hub==0.36.2",
         "tokenizers==0.22.2", "safetensors==0.8.0"],
    )
    assert r1.returncode == 0, f"main 离线安装失败：{r1.stderr[-400:]}"
    code, version = _import_version(main_py, "transformers")
    assert code == 0 and version == "4.57.6", f"main transformers 漂移：{version}"
    code, version = _import_version(main_py, "huggingface_hub")
    assert code == 0 and version == "0.36.2", f"main hub 漂移：{version}"

    moss_py = _make_venv(tmp_path, "moss")
    r2 = _pip_install_offline(
        moss_py,
        ["transformers==5.14.1", "huggingface_hub==1.24.0",
         "tokenizers==0.22.2", "safetensors==0.8.0"],
    )
    assert r2.returncode == 0, f"moss 离线安装失败：{r2.stderr[-400:]}"
    code, version = _import_version(moss_py, "transformers")
    assert code == 0 and version == "5.14.1", f"moss transformers 漂移：{version}"
    code, version = _import_version(moss_py, "huggingface_hub")
    assert code == 0 and version == "1.24.0", f"moss hub 漂移：{version}"


def test_case_b_main_import_smoke_without_network(tmp_path):
    """Case B/J/L：离线安装 main 契约 + torch 后，transformers/hub import
    正常且版本精确；FireRedASR2S 的 transformers 依赖被满足。"""
    main_py = _make_venv(tmp_path, "main")
    r = _pip_install_offline(
        main_py,
        ["transformers==4.57.6", "huggingface_hub==0.36.2",
         "tokenizers==0.22.2", "safetensors==0.8.0",
         "torch==2.11.0+cpu", "torchaudio==2.11.0+cpu",
         "numpy==2.2.6", "requests==2.33.0", "filelock==3.32.2"],
    )
    assert r.returncode == 0, f"离线安装失败：{r.stderr[-400:]}"
    probe = subprocess.run(
        [str(main_py), "-c",
         "import torch, transformers, huggingface_hub; "
         "print('OK', transformers.__version__, huggingface_hub.__version__)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert probe.returncode == 0, f"import 失败：{probe.stderr[-300:]}"
    assert "4.57.6" in probe.stdout and "0.36.2" in probe.stdout


def test_case_c_moss_no_longer_gets_main_hub_pin(tmp_path):
    """Case C：MOSS 安装序列不再包含 main 的 hub==0.36.2 pin。"""
    source = (PROJECT_ROOT / "scripts" / "setup_model_backend.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "huggingface_hub==0.36.2" not in source, (
        "setup_model_backend 不得再无条件钉装 main 的 hub 到 MOSS"
    )
    assert "Get-EnvironmentPackages -Role moss" in source
    assert "Get-EnvironmentPackages -Role main" in source
    assert "torch==$mossTorch+cpu" in source, "MOSS torch 必须按契约防漂移"
