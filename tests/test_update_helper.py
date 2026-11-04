# SPDX-License-Identifier: GPL-3.0-only
"""The compiled updater helper: transactional replace, rollback, locks, prune."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from twobyteasr.app import update_manifest as um

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not CSC.is_file(), reason="Windows .NET compiler needed")


@pytest.fixture(scope="session")
def binaries(tmp_path_factory):
    out = tmp_path_factory.mktemp("updater-bin")
    helper, fake = out / "2ByteASRUpdater.exe", out / "fake_app.exe"
    common = ["/nologo", "/optimize+", "/codepage:65001"]
    subprocess.run([str(CSC), *common, "/target:winexe", "/reference:System.Windows.Forms.dll",
                    "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll", f"/out:{helper}",
                    str(ROOT / "launcher" / "2ByteASRUpdater.cs")], check=True, capture_output=True)
    subprocess.run([str(CSC), *common, "/target:exe", f"/out:{fake}",
                    str(ROOT / "tests" / "fixtures" / "update_fake_app.cs")], check=True, capture_output=True)
    return helper, fake


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture()
def case(tmp_path, binaries):
    helper_src, fake = binaries
    install, staging = tmp_path / "Programs" / "2ByteASR", tmp_path / "updates" / "s" / "abc"
    install.mkdir(parents=True)
    shutil.copy2(fake, install / "2ByteASR.exe")
    _write(install, "twobyteasr/app/ui.py", b"old ui")
    _write(install, "twobyteasr/retired.py", b"retired")
    _write(install, "renderer/node_modules/x.js", b"renderer")
    for name in um.PRESERVED_FILES:
        _write(install, name, b"user-owned " + name.encode())
    old = um.build_installed_manifest(install, version="0.6.5")
    (install / um.COMPONENTS_FILENAME).write_text(json.dumps(old), encoding="utf-8")
    staging.mkdir(parents=True)
    shutil.copy2(fake, staging / "2ByteASR.exe")
    _write(staging, "twobyteasr/app/ui.py", b"new ui")
    _write(staging, "twobyteasr/added.py", b"added")
    new_install = tmp_path / "expected"
    shutil.copytree(install, new_install)
    (new_install / "twobyteasr/retired.py").unlink()
    _write(new_install, "twobyteasr/app/ui.py", b"new ui")
    _write(new_install, "twobyteasr/added.py", b"added")
    new_manifest = um.build_installed_manifest(new_install, version="0.6.6")
    (staging / um.COMPONENTS_FILENAME).write_text(json.dumps(new_manifest), encoding="utf-8")
    # A user's own file next to the program: never listed, never touched.
    _write(install, "my-notes.txt", b"user file next to the program")
    helper = tmp_path / "updates" / "helper" / "2ByteASRUpdater.exe"
    helper.parent.mkdir(parents=True)
    shutil.copy2(helper_src, helper)
    return {"install": install, "staging": staging, "helper": helper, "tmp": tmp_path,
            "replace": ["2ByteASR.exe", "twobyteasr/app/ui.py", "twobyteasr/added.py"],
            "remove": ["twobyteasr/retired.py"]}


def _plan(case, *, restart=False, extra=(), replace=None, remove=None, end_delta=0) -> Path:
    replace = case["replace"] if replace is None else replace
    remove = case["remove"] if remove is None else remove
    lines = ["2BYTEASR-UPDATE-PLAN\t1", f"install_root\t{case['install']}", f"staging_root\t{case['staging']}",
             "from_version\t0.6.5", "to_version\t0.6.6", "wait_pid\t0", f"restart\t{1 if restart else 0}",
             "confirm_seconds\t20", "process_wait_seconds\t2", f"log\t{case['tmp'] / 'helper.log'}",
             f"result\t{case['tmp'] / 'result.json'}", *extra]
    lines += [f"REPLACE\t{r}" for r in replace] + [f"REMOVE\t{r}" for r in remove]
    lines += [f"MANIFEST\t{um.COMPONENTS_FILENAME}", f"END\t{len(replace) + len(remove) + 1 + end_delta}"]
    path = case["tmp"] / "plan.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(case, plan, env=None, timeout=60):
    environment = dict(os.environ)
    environment.update(env or {})
    return subprocess.run([str(case["helper"]), "--apply", str(plan), "--quiet"], env=environment,
                          timeout=timeout, capture_output=True).returncode


def _result(case):
    return json.loads((case["tmp"] / "result.json").read_text("utf-8-sig"))


def test_apply_replaces_only_planned_files_and_keeps_user_data(case):
    before = _tree(case["install"])
    assert _run(case, _plan(case)) == 0
    after = _tree(case["install"])
    assert (case["install"] / "twobyteasr/app/ui.py").read_bytes() == b"new ui"
    assert (case["install"] / "twobyteasr/added.py").read_bytes() == b"added"
    assert not (case["install"] / "twobyteasr/retired.py").exists()
    for name in (*um.PRESERVED_FILES, "my-notes.txt", "renderer/node_modules/x.js"):
        assert after[name] == before[name]
    installed = um.load_installed_manifest(case["install"])
    assert installed["version"] == "0.6.6"
    assert not (case["install"] / ".update-backup").exists() or not any((case["install"] / ".update-backup").iterdir())
    assert not (case["install"] / ".update-state" / "journal.txt").exists()
    assert _result(case)["status"] == "applied"


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
def test_failure_at_any_step_restores_the_previous_program(case, step):
    before = _tree(case["install"])
    assert _run(case, _plan(case), env={"TWOBYTEASR_UPDATER_FAIL_AT": str(step)}) == 2
    after = {k: v for k, v in _tree(case["install"]).items() if not k.startswith(".update-state/")}
    assert after == before
    assert not list(case["install"].rglob("*.update-new"))
    assert _result(case)["status"] == "rolled-back"


def test_locked_readonly_or_missing_files_abort_before_any_change(case):
    before = _tree(case["install"])
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(str(case["install"] / "twobyteasr/app/ui.py"), 0x80000000, 0, None, 3, 0x80, None)
    try:
        assert _run(case, _plan(case)) == 2
        assert "占用" in _result(case)["detail"]
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    assert _tree(case["install"]) == {**before, **{k: v for k, v in _tree(case["install"]).items()
                                                  if k.startswith(".update-state/")}}
    os.chmod(case["install"] / "twobyteasr/retired.py", 0o444)
    try:
        assert _run(case, _plan(case)) == 2
        assert "只读" in _result(case)["detail"]
    finally:
        os.chmod(case["install"] / "twobyteasr/retired.py", 0o666)
    (case["staging"] / "twobyteasr/added.py").unlink()
    assert _run(case, _plan(case)) == 2
    assert "暂存文件缺失" in _result(case)["detail"]
    assert (case["install"] / "twobyteasr/app/ui.py").read_bytes() == b"old ui"


def test_insufficient_space_aborts(case):
    assert _run(case, _plan(case, extra=["reserve_bytes\t9000000000000000"])) == 2
    assert "空间不足" in _result(case)["detail"]
    assert (case["install"] / "twobyteasr/app/ui.py").read_bytes() == b"old ui"


def test_running_program_blocks_the_update(case):
    process = subprocess.Popen([str(case["install"] / "2ByteASR.exe")],
                               env={**os.environ, "TWOBYTEASR_FAKE_BEHAVIOR": "sleep:15"})
    try:
        time.sleep(0.5)
        assert _run(case, _plan(case)) == 2
        assert "仍有程序在使用" in _result(case)["detail"]
    finally:
        process.kill()
        process.wait()
    assert (case["install"] / "twobyteasr/app/ui.py").read_bytes() == b"old ui"


@pytest.mark.parametrize("bad", [
    {"replace": ["../escape.txt"]},
    {"replace": ["2byteasr_settings.json"]},
    {"remove": ["glossary.txt"]},
    {"replace": ["C:/Windows/x.dll"]},
    {"end_delta": 1},
])
def test_invalid_plans_are_refused(case, bad):
    before = _tree(case["install"])
    assert _run(case, _plan(case, **bad)) == 4
    assert {k: v for k, v in _tree(case["install"]).items() if not k.startswith(".update-state/")} == before


def test_restart_confirmation_keeps_new_version(case):
    marker = case["tmp"] / "started.txt"
    code = _run(case, _plan(case, restart=True),
                env={"TWOBYTEASR_FAKE_BEHAVIOR": "confirm", "TWOBYTEASR_FAKE_STARTED": str(marker)})
    assert code == 0
    assert (case["install"] / "twobyteasr/app/ui.py").read_bytes() == b"new ui"
    assert "confirm-" in marker.read_text()


def test_new_version_that_fails_to_start_is_rolled_back(case):
    before = _tree(case["install"])
    marker = case["tmp"] / "started.txt"
    code = _run(case, _plan(case, restart=True),
                env={"TWOBYTEASR_FAKE_BEHAVIOR": "crash", "TWOBYTEASR_FAKE_STARTED": str(marker)})
    assert code == 2
    assert {k: v for k, v in _tree(case["install"]).items() if not k.startswith(".update-state/")} == before
    starts = marker.read_text().splitlines()
    assert len(starts) == 2 and starts[1] == "<none>"  # new start, then the restored old program
    assert _result(case)["status"] == "rolled-back-after-start"


def test_interrupted_journal_is_recovered(case):
    install = case["install"]
    backup = install / ".update-backup" / "tx"
    (backup / "twobyteasr" / "app").mkdir(parents=True)
    os.replace(install / "twobyteasr/app/ui.py", backup / "twobyteasr/app/ui.py")
    (install / "twobyteasr/app/ui.py").write_bytes(b"half-written new ui")
    state = install / ".update-state"
    state.mkdir(exist_ok=True)
    (state / "journal.txt").write_text(
        f"2BYTEASR-UPDATE-JOURNAL\t1\nTXID\ttx\nBACKUP\t{backup}\nFROM\t0.6.5\nTO\t0.6.6\n"
        "MOVED\ttwobyteasr/app/ui.py\nPLACED\ttwobyteasr/app/ui.py\n", encoding="utf-8")
    result = subprocess.run([str(case["helper"]), "--rollback", str(install), "--quiet"], timeout=60)
    assert result.returncode == 0
    assert (install / "twobyteasr/app/ui.py").read_bytes() == b"old ui"
    assert not (state / "journal.txt").exists()


def test_prune_after_setup_removes_only_exact_retired_files(case):
    install = case["install"]
    previous = install / ".update-state" / "previous-components.json"
    previous.parent.mkdir(exist_ok=True)
    shutil.copy2(install / um.COMPONENTS_FILENAME, previous)
    shutil.copy2(case["staging"] / um.COMPONENTS_FILENAME, install / um.COMPONENTS_FILENAME)
    retired_changed = install / "renderer/node_modules/x.js"
    retired_changed.write_bytes(b"modified by someone")  # listed before, absent now, but changed
    new = json.loads((install / um.COMPONENTS_FILENAME).read_text("utf-8"))
    new["components"]["renderer"] = {"content_sha256": um.content_sha256([]), "file_count": 0, "bytes": 0,
                                     "files": []}
    (install / um.COMPONENTS_FILENAME).write_text(json.dumps(new), encoding="utf-8")
    result = subprocess.run([str(case["helper"]), "--prune", str(install), str(previous), "--quiet"], timeout=60)
    assert result.returncode == 0
    assert not (install / "twobyteasr/retired.py").exists()
    assert retired_changed.exists()
    for name in (*um.PRESERVED_FILES, "my-notes.txt", "twobyteasr/app/ui.py"):
        assert (install / name).exists()


def test_uninstall_removes_listed_program_files_only(case):
    install = case["install"]
    (install / ".update-state").mkdir(exist_ok=True)
    result = subprocess.run([str(case["helper"]), "--remove-listed", str(install), "--quiet"], timeout=60)
    assert result.returncode == 0
    remaining = {p.relative_to(install).as_posix() for p in install.rglob("*") if p.is_file()}
    assert remaining == {*um.PRESERVED_FILES, "my-notes.txt", um.COMPONENTS_FILENAME}
    assert not (install / ".update-state").exists()
