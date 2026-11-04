"""P1-7 回归测试：热更/更新包路径越界防护（fail-closed）。

安全不变量：来自 HOTFIX.json 的任何相对路径在执行 Copy/Move/Delete/
Replace 前必须 canonicalize，且最终路径严格位于允许的 root 内
（candidate 不得等于 root、不得以 root+分隔符之外的方式命中）。
无法解析/类型错误 → 拒绝整个操作。
"""

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
HELPER = PROJECT_ROOT / "scripts" / "update-path-safety.ps1"
APPLY_HOTFIX = PROJECT_ROOT / "scripts" / "apply_hotfix.ps1"
APPLY_UPDATE = PROJECT_ROOT / "scripts" / "apply_update.ps1"


def _run_powershell(script_text):
    result = subprocess.run(
        POWERSHELL + ["-Command", script_text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return result


# ---------------------------------------------------------------- helper 单元矩阵
# 契约：Candidate 是调用方拼接后的绝对路径（生产调用点总是先
# Join-Path <root> <relative> + GetFullPath 再传入）。相对路径的越界
# 形态由 apply_hotfix/apply_update 集成测试覆盖。
_HELPER_CASES = [
    # (candidate, root, expected_inside)
    ("C:\\Temp\\App\\a\\b\\c.txt", "C:\\Temp\\App", True),
    ("C:\\Temp\\App\\subdir\\file.txt", "C:\\Temp\\App", True),
    ("C:\\Temp\\App\\Application\\evil.txt", "C:\\Temp\\App", True),  # 前缀相似但在内
    ("C:\\Temp\\outside.txt", "C:\\Temp\\App", False),  # 越界（../outside 形态）
    ("C:\\outside.txt", "C:\\Temp\\App", False),  # 多级越界
    ("C:\\Temp\\App2\\evil.txt", "C:\\Temp\\App", False),  # prefix collision 变体
    ("C:\\Temp\\Application\\evil.txt", "C:\\Temp\\App", False),  # prefix collision
    ("C:\\Windows\\evil.txt", "C:\\Temp\\App", False),  # 绝对路径
    ("D:\\evil.txt", "C:\\Temp\\App", False),  # 其它盘符
    ("\\\\server\\share\\evil.txt", "C:\\Temp\\App", False),  # UNC
    ("C:\\Temp\\App", "C:\\Temp\\App", False),  # root 自身
    ("", "C:\\Temp\\App", False),  # 空路径（GetFullPath 失败 → fail-closed）
    ("C:\\Temp\\app\\a.txt", "C:\\Temp\\App", True),  # 大小写不敏感（Windows）
]


@pytest.mark.parametrize("candidate,root,expected", _HELPER_CASES)
def test_assert_path_inside_root_matrix(candidate, root, expected):
    """helper 单元矩阵：canonicalize + root containment。"""
    helper_posix = str(HELPER).replace("'", "''")
    script = (
        f". '{helper_posix}';"
        "$ok = $false;"
        f"try {{ $ok = Assert-PathInsideRoot -Candidate '{candidate}' -Root '{root}' }}"
        " catch { $ok = $false };"
        "if ($ok) { 'INSIDE' } else { 'OUTSIDE' }"
    )
    result = _run_powershell(script)
    actual = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "ERROR"
    expected_text = "INSIDE" if expected else "OUTSIDE"
    assert actual == expected_text, (
        f"candidate={candidate!r} root={root!r}: 期望 {expected_text}，"
        f"实际 {actual}（stderr={result.stderr.strip()[-200:]}）"
    )


# ---------------------------------------------------------------- apply_hotfix 集成

def _make_hotfix_zip(zip_path, manifest, files):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "HOTFIX.json",
            json.dumps(manifest, ensure_ascii=False),
        )
        for name, content in files.items():
            archive.writestr(name, content)


def _run_hotfix(zip_path, root):
    return subprocess.run(
        POWERSHELL + ["-File", str(APPLY_HOTFIX), "-ZipPath", str(zip_path), "-Root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def test_malicious_hotfix_traversal_is_rejected_and_outside_untouched(tmp_path):
    """恶意 HOTFIX.json：files/delete 越界 → 整包拒绝，outside 文件不受影响。"""
    app = tmp_path / "app"
    outside = tmp_path / "outside"
    app.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    zip_path = tmp_path / "malicious.zip"
    _make_hotfix_zip(
        zip_path,
        {
            "schema_version": 1,
            "version": "evil",
            "files": [
                "ok.txt",                      # 合法条目（fail-closed：也不应用）
                "../../outside/evil.txt",      # files 越界写
                "sub/../../outside/evil2.txt", # 嵌套越界
            ],
            "delete": ["../../outside/sentinel.txt"],
        },
        {"ok.txt": "ok", "evil.txt": "evil"},
    )

    result = _run_hotfix(zip_path, app)
    assert result.returncode != 0, f"恶意包必须失败：stdout={result.stdout} stderr={result.stderr}"
    assert sentinel.is_file(), "越界 delete 不得删除 outside 文件"
    assert not (outside / "evil.txt").exists(), "越界 files 不得写入 outside"
    assert not (outside / "evil2.txt").exists(), "嵌套越界不得写入 outside"
    assert not (app / "ok.txt").exists(), "fail-closed：合法条目也不得在整包拒绝时应用"


def test_legal_hotfix_applies_files_and_delete(tmp_path):
    """合法 HOTFIX.json：文件落地、delete 生效。"""
    app = tmp_path / "app"
    app.mkdir()
    stale = app / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    zip_path = tmp_path / "legal.zip"
    _make_hotfix_zip(
        zip_path,
        {
            "schema_version": 1,
            "version": "1.0",
            "files": ["ok.txt", "sub/dir/file.txt"],
            "delete": ["stale.txt"],
        },
        {"ok.txt": "new", "sub/dir/file.txt": "nested"},
    )

    result = _run_hotfix(zip_path, app)
    assert result.returncode == 0, f"合法包应成功：stdout={result.stdout} stderr={result.stderr}"
    assert (app / "ok.txt").read_text(encoding="utf-8") == "new"
    assert (app / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "nested"
    assert not stale.exists(), "清单中的 delete 应生效"


def test_missing_manifest_is_rejected(tmp_path):
    """缺 HOTFIX.json → 拒绝。"""
    app = tmp_path / "app"
    app.mkdir()
    zip_path = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("random.txt", "x")
    result = _run_hotfix(zip_path, app)
    assert result.returncode != 0


# ---------------------------------------------------------------- apply_update 集成（复用 helper 后不回归）

def _run_update(zip_path, root, log_dir):
    """非交互运行 apply_update.ps1：日志写入临时目录，绝不弹 MessageBox、
    绝不写真实 %LOCALAPPDATA%。"""
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    log_path = log_dir / "update.log"
    return subprocess.run(
        POWERSHELL
        + [
            "-File",
            str(APPLY_UPDATE),
            "-Package",
            str(zip_path),
            "-ProjectRoot",
            str(root),
            "-ExpectedSha256",
            digest,
            "-NonInteractive",
            "-LogPath",
            str(log_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def test_retired_update_rejects_even_legal_package_without_mutation(tmp_path):
    """Legacy ZIP hot replacement is no longer a supported upgrade path."""
    app = tmp_path / "app"
    app.mkdir()
    zip_path = tmp_path / "update.zip"
    _make_hotfix_zip(
        zip_path,
        {"schema_version": 1, "version": "1.0", "files": ["a/b.txt"], "delete": []},
        {"a/b.txt": "content"},
    )
    result = _run_update(zip_path, app, tmp_path / "logs")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert list(app.iterdir()) == []
    assert zip_path.is_file()
    assert not (tmp_path / "logs").exists()


def test_update_traversal_package_is_rejected(tmp_path):
    """apply_update.ps1 越界包被拒绝：非交互、temp 日志、确定性退出码。

    测试隔离不变量（P1-7 regression）：运行不得弹 GUI MessageBox（-NonInteractive
    下 catch 只 Write-Error + exit 1），日志必须落在临时目录而不是真实
    %LOCALAPPDATA%\\2ByteASR\\update.log。
    """
    app = tmp_path / "app"
    outside = tmp_path / "outside"
    log_dir = tmp_path / "logs"
    app.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    zip_path = tmp_path / "evil-update.zip"
    _make_hotfix_zip(
        zip_path,
        {"schema_version": 1, "version": "1.0", "files": ["../../outside/evil.txt"], "delete": []},
        {"evil.txt": "x"},
    )
    result = _run_update(zip_path, app, log_dir)
    assert result.returncode != 0, "越界更新包必须以非零退出码被拒绝"
    # PowerShell 5.1 的 stderr 用 ANSI 码页输出，中文可能乱码；内容以日志
    # 文件（UTF-8 写入）为准，stderr 只需证明非交互失败有错误输出。
    assert result.stderr.strip(), "非交互失败必须通过 stderr 报告错误"
    assert sentinel.is_file(), "越界 files 不得写入 outside"
    assert not (outside / "evil.txt").exists()
    assert not log_dir.exists(), "退役入口应在任何写入前拒绝"
    assert zip_path.is_file()


def test_retired_update_fails_before_any_legacy_write_or_gui():
    """Direct invocations cannot reactivate arbitrary HOTFIX operations."""
    source = Path(__file__).resolve().parents[1] / "scripts" / "apply_update.ps1"
    text = source.read_text(encoding="utf-8-sig")
    assert "[switch]$NonInteractive" in text
    assert "[string]$LogPath" in text
    rejection = text.index('throw "旧 ZIP 热替换更新已停用')
    for operation in ('New-Item ', 'Copy-Item ', 'Remove-Item ', '[System.Windows.Forms.MessageBox]::Show'):
        assert rejection < text.index(operation)
