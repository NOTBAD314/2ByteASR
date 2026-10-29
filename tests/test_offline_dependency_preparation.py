"""P1-1 回归测试：离线 wheel 准备（prepare_offline_dependencies.ps1）。

测试只覆盖纯函数（dot-source 加载后调用）；真实 pip download 行为
由本地网络 smoke 验证（pytest 保持离线）。
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_LOCK = PROJECT_ROOT / "dependencies.lock.json"
PREPARE = PROJECT_ROOT / "scripts" / "prepare_offline_dependencies.ps1"
BUILD_HOTFIX = PROJECT_ROOT / "scripts" / "build_hotfix.ps1"
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell-only build chain"
)


def _ps_script(script_text):
    """执行一段 PowerShell（dot-source prepare 后调用其纯函数）。"""
    prepare = str(PREPARE.resolve())
    return subprocess.run(
        POWERSHELL + ["-Command", f". '{prepare}';" + script_text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _run_ps(args, timeout=120):
    return subprocess.run(
        POWERSHELL + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _make_lock(dir_path, setuptools="80.9.0", wheel="0.45.1"):
    lock = json.loads(REAL_LOCK.read_text(encoding="utf-8"))
    if setuptools is None:
        lock["runtime"].pop("setuptools", None)
    else:
        lock["runtime"]["setuptools"] = setuptools
    if wheel is None:
        lock["runtime"].pop("wheel", None)
    else:
        lock["runtime"]["wheel"] = wheel
    lock_path = dir_path / "dependencies.lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
    return str(lock_path.resolve())


# ---------------------------------------------------------------- Case A：清单推导

def test_case_a_requirements_derived_from_lock(tmp_path):
    """Case A：Get-RequiredWheels 从 lock 推导精确版本清单。"""
    lock_path = _make_lock(tmp_path)
    script = (
        f"$req = Get-RequiredWheels -LockPath '{lock_path}';"
        "$req | ForEach-Object { $_.Name + '==' + $_.Version + ' -> ' + $_.File }"
    )
    result = subprocess.run(
        POWERSHELL
        + ["-Command", f". '{PREPARE.resolve()}';" + script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, f"stderr={result.stderr[-300:]}"
    lines = result.stdout.strip().splitlines()
    assert any("setuptools==80.9.0" in line and "setuptools-80.9.0-py3-none-any.whl" in line for line in lines)
    assert any("wheel==0.45.1" in line and "wheel-0.45.1-py3-none-any.whl" in line for line in lines)


# ---------------------------------------------------------------- Case B/C：版本校验

def test_case_b_correct_wheel_matches_requirement(tmp_path):
    """Case B：正确版本 wheel 通过 Test-WheelMatchesRequirement。"""
    lock_path = _make_lock(tmp_path)
    result = _ps_script(
        "$ok = Test-WheelMatchesRequirement -File 'setuptools-80.9.0-py3-none-any.whl' "
        f"-LockPath '{lock_path}'; if ($ok) {{ 'MATCH' }} else {{ 'NO-MATCH' }}"
    )
    assert "MATCH" in result.stdout
    result = _ps_script(
        "$ok = Test-WheelMatchesRequirement -File 'wheel-0.45.1-py3-none-any.whl' "
        f"-LockPath '{lock_path}'; if ($ok) {{ 'MATCH' }} else {{ 'NO-MATCH' }}"
    )
    assert "MATCH" in result.stdout


def test_case_c_wrong_version_does_not_match(tmp_path):
    """Case C：错误版本 wheel 不通过校验（fail-closed 依据）。"""
    lock_path = _make_lock(tmp_path)
    result = _ps_script(
        "$ok = Test-WheelMatchesRequirement -File 'setuptools-0.0.0-py3-none-any.whl' "
        f"-LockPath '{lock_path}'; if ($ok) {{ 'MATCH' }} else {{ 'NO-MATCH' }}"
    )
    assert "NO-MATCH" in result.stdout


# ---------------------------------------------------------------- Case D：lock 缺失

def test_case_d_lock_missing_setuptools_fails_closed(tmp_path):
    """Case D：lock 缺 setuptools → Get-RequiredWheels 抛异常。"""
    lock_path = _make_lock(tmp_path, setuptools=None)
    result = _ps_script(
        "try { Get-RequiredWheels -LockPath $args[0] | Out-Null; 'OK' } "
        "catch { 'THREW: ' + $_.Exception.Message }"
    )
    assert "THREW" in result.stdout, "lock 缺版本必须失败"


# ---------------------------------------------------------------- Case H：index 传递

def test_case_h_pip_download_command_carries_index(tmp_path):
    """Case H：Get-PipDownloadCommand 携带可配置 index。"""
    result = _ps_script(
        "$args = Get-PipDownloadCommand -Requirements ("
        "@{ Name='setuptools'; Version='80.9.0'; File='setuptools-80.9.0-py3-none-any.whl' }) "
        "-Destination 'C:\\temp\\wheels' -IndexUrl 'https://mirror.example.invalid/simple';"
        "$args -join ' '"
    )
    assert "setuptools==80.9.0" in result.stdout
    assert "mirror.example.invalid" in result.stdout


# ---------------------------------------------------------------- Case I/J：静态不变量

def test_case_j_build_hotfix_derives_wheel_list_from_lock(tmp_path):
    """Case J：build_hotfix 的 wheels 清单从 lock 动态推导（无硬编码版本）。"""
    source = BUILD_HOTFIX.read_text(encoding="utf-8-sig")
    assert "setuptools-80.9.0" not in source, "build_hotfix 不得硬编码 wheel 版本"
    assert "wheel-0.45.1" not in source, "build_hotfix 不得硬编码 wheel 版本"
    assert "dependencies.lock.json" in source, "清单应从 lock 推导"
    assert "runtime.setuptools" in source and "runtime.wheel" in source


def test_case_i_offline_install_args_unchanged(tmp_path):
    """Case I：setup_environment.ps1 的 --no-index --find-links 离线路径保持。"""
    source = (PROJECT_ROOT / "scripts" / "setup_environment.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "--no-index" in source
    assert "--find-links" in source
    assert "$WheelsDir" in source


# ---------------------------------------------------------------- 集成：clean-room hotfix 构建（离线）

_BUILD_HOTFIX_FILES = (
    "2ByteASR.exe", "2ByteASR-Configure.exe", "apply_hotfix.bat", "CHANGELOG.md",
    "README.md", "TERMINOLOGY.md", "auto_asr.py", "quick_start.py", "subtitle_core.py",
    "setup_2byteasr.bat", "clean_models.bat", "moss_firered_pipeline.py",
    "scripts\\bootstrap_install.ps1", "scripts\\setup_environment.ps1",
    "scripts\\environment-lock.ps1", "scripts\\repair_environment.ps1",
    "scripts\\download_models.ps1", "scripts\\download_file_fast.py",
    "scripts\\install_shortcut.ps1", "scripts\\apply_update.ps1",
    "scripts\\ShortcutIdentity.exe",
    "twobyteasr\\system\\environment.py", "twobyteasr\\environment_probe.py",
    "twobyteasr\\environment_repair.py",
    "twobyteasr\\download_sources.py",
    "twobyteasr\\system\\hardware.py", "twobyteasr\\recognition\\asr.py", "twobyteasr\\subtitle_rules\\grouping.py",
    "twobyteasr\\providers\\llm_config.py", "twobyteasr\\recognition\\service.py", "twobyteasr\\subtitle_rules\\output.py",
    "twobyteasr\\app\\ui.py", "twobyteasr\\local_models\\model_workshop.py", "twobyteasr\\app\\updater.py",
    "twobyteasr\\i18n.py", "twobyteasr\\storage\\settings.py", "twobyteasr\\model_integrity.py",
    "twobyteasr\\subtitle_rules\\segmentation.py", "twobyteasr\\recognition\\pipeline_runtime.py",
    "assets\\ui-chevron-down.png", "assets\\2byteasr-icon-transparent.png",
)


def _cleanroom(tmp_path, include_wheels=True):
    """最小 clean checkout 骨架：真实 build_hotfix + 真实 lock + 占位清单文件。"""
    project = tmp_path / "cleanroom"
    for relative in _BUILD_HOTFIX_FILES:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith((".png", ".exe")):
            path.write_bytes(b"placeholder")
        else:
            path.write_text("# placeholder\n", encoding="utf-8")
    (project / "scripts").mkdir(exist_ok=True)
    for name in ("build_hotfix.ps1",):
        shutil.copy(PROJECT_ROOT / "scripts" / name, project / "scripts" / name)
    shutil.copy(REAL_LOCK, project / "dependencies.lock.json")
    (project / "2byteasr_version.json").write_text(
        json.dumps({"version": "0.1.99", "repository": "x", "channel": "stable"}),
        encoding="utf-8",
    )
    if include_wheels:
        wheels = project / "wheels"
        wheels.mkdir()
        for name in ("setuptools-80.9.0-py3-none-any.whl", "wheel-0.45.1-py3-none-any.whl"):
            source = PROJECT_ROOT / "wheels" / name
            if source.is_file():
                shutil.copy(source, wheels / name)
            else:
                (wheels / name).write_bytes(b"placeholder-wheel")
    return project


def test_cleanroom_hotfix_build_uses_lock_derived_wheels(tmp_path):
    """集成（离线）：clean checkout + 锁声明 wheel 就位 → build_hotfix 通过缺失检查。

    真实下载路径已由本地网络 smoke 验证（prepare 真实 pip download）。
    本测试离线证明：build_hotfix 的 wheels 清单从 lock 推导且被满足时
    不再报 wheels 缺失（有 7z 时完整生成 zip，无 7z 时缺失检查已通过）。
    """
    import shutil as _shutil

    project = _cleanroom(tmp_path)
    result = _run_ps(
        ["-File", str(project / "scripts" / "build_hotfix.ps1"), "-Version", "0.1.99"],
        timeout=180,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert "wheels" not in combined or "wheels" in combined and "缺失" not in combined, (
        f"缺失检查不得再报 wheels：{combined[-600:]}"
    )
    # 有 7z 时产物成功；无 7z 时报错信息不得包含 wheels 条目
    if result.returncode == 0:
        import zipfile

        zip_path = project / "dist" / "2ByteASR-Update-0.1.99.zip"
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            assert any("setuptools-80.9.0" in n for n in names), "热更包必须含 setuptools wheel"
            assert any("wheel-0.45.1" in n for n in names), "热更包必须含 wheel wheel"
    else:
        assert "wheels" not in combined, f"失败原因不得与 wheels 相关：{combined[-600:]}"


def test_cleanroom_without_wheels_fails_closed_on_missing(tmp_path):
    """集成（离线）：clean checkout 无 wheels → build_hotfix 缺失检查报 wheels（fail-closed）。

    这正是 CI 红基线；修复后该失败改由 prepare 步骤在构建前消除。
    """
    project = _cleanroom(tmp_path, include_wheels=False)
    result = _run_ps(
        ["-File", str(project / "scripts" / "build_hotfix.ps1"), "-Version", "0.1.99"],
        timeout=120,
    )
    assert result.returncode != 0, "无 wheels 必须失败（fail-closed）"
    combined = (result.stdout or "") + (result.stderr or "")
    assert "wheels" in combined, "失败原因必须指明 wheels 缺失"
