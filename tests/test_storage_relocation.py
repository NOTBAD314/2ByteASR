"""2026-10-17: runtimes follow the program folder; models and runtimes can be moved.

Users with a small C: drive could not move the ~5 GB runtimes at all. These
cases cover where new, upgraded and isolated installs keep runtimes, and the
in-app move: rename on one volume, file copy across volumes, the absolute
paths a venv records, cancel and failure rollback, and the start checks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from twobyteasr import runtime_paths
from twobyteasr.runtime_paths import (
    MODEL_ROOT_ENV,
    RUNTIME_ROOT_ENV,
    USER_DATA_ENV,
    bootstrap_runtime_paths,
    build_runtime_paths,
    get_runtime_paths,
    managed_runtime_root,
    reset_runtime_paths,
)
from twobyteasr import storage_relocation as relocation

windows_only = pytest.mark.skipif(os.name != "nt", reason="runtime folders beside the program and the move are Windows only")

MODEL = "MOSS-Transcribe-Diarize"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("TWOBYTEASR_TEST_ROOT", raising=False)
    monkeypatch.delenv(USER_DATA_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_ROOT_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv(MODEL_ROOT_ENV, "")
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _program(tmp_path, name="D-drive/兔白字幕"):
    program = tmp_path / name
    program.mkdir(parents=True)
    (program / "dependencies.lock.json").write_text(json.dumps({
        "schema_version": 1,
        "models": {"moss": {"path": f"models/{MODEL}", "required_files": ["a.bin"]}},
    }), encoding="utf-8")
    return program


def _local(tmp_path):
    return tmp_path / "local" / "2ByteASR"


def _saved(tmp_path):
    return json.loads((_local(tmp_path) / "runtime_paths.json").read_text("utf-8"))


# ------------------------------------------------------- where runtimes live

@windows_only
def test_new_packaged_install_keeps_runtimes_beside_the_program(tmp_path, monkeypatch):
    program = _program(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    paths = bootstrap_runtime_paths(install_root=program, persist=True)
    assert paths.runtime_root == program / "runtimes"
    assert paths.runtime_root_source == "default_program"
    assert _saved(tmp_path)["runtime_root"] == str(program / "runtimes")
    assert not (_local(tmp_path) / "runtimes").exists()
    # Every runtime consumer reads the same folder.
    from twobyteasr.runtime_registry import registry_path, stable_runtime_root
    from twobyteasr.runtime_download_cache import runtime_cache_path
    assert registry_path() == program / "runtimes" / "registry.json"
    assert stable_runtime_root("main") == program / "runtimes" / "main"
    assert runtime_cache_path() == program / "runtimes" / "download-cache"
    # The registered choice is kept on the next start.
    reset_runtime_paths()
    assert build_runtime_paths(install_root=program).runtime_root == program / "runtimes"


@windows_only
def test_upgrade_keeps_runtimes_already_in_user_data(tmp_path, monkeypatch):
    program = _program(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    legacy = _local(tmp_path) / "runtimes"
    (legacy / "tools" / "uv-0.11.7").mkdir(parents=True)
    (legacy / "registry.json").write_text('{"runtimes": {}}', "utf-8")
    paths = bootstrap_runtime_paths(install_root=program, persist=True)
    assert paths.runtime_root == legacy
    assert paths.runtime_root_source == "legacy_user_data"
    assert not (program / "runtimes").exists()


@windows_only
def test_source_runs_dev_dist_and_isolated_roots_keep_user_data_runtimes(tmp_path, monkeypatch):
    program = _program(tmp_path)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert build_runtime_paths(install_root=program).runtime_root == _local(tmp_path) / "runtimes"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    dev_dist = checkout / "dist" / "2ByteASR"
    dev_dist.mkdir(parents=True)
    reset_runtime_paths()
    assert build_runtime_paths(install_root=dev_dist).runtime_root_source == "default_user_data"

    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path))
    reset_runtime_paths()
    assert build_runtime_paths(install_root=program).runtime_root == _local(tmp_path) / "runtimes"


def test_isolated_runs_ignore_a_runtime_folder_outside_their_root(tmp_path, monkeypatch):
    root = tmp_path / "tmp" / "isolated"
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(root / "local"))
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(tmp_path / "real-runtimes"))
    reset_runtime_paths()
    assert managed_runtime_root() == root / "local" / "2ByteASR" / "runtimes"


@windows_only
def test_moved_folder_is_kept_while_its_drive_is_away_but_an_empty_automatic_choice_is_redone(tmp_path, monkeypatch):
    program = _program(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    config = _local(tmp_path) / "runtime_paths.json"
    config.parent.mkdir(parents=True)
    away = tmp_path / "unplugged" / "runtimes"
    config.write_text(json.dumps({"runtime_root": str(away), "runtime_root_source": "moved"}), "utf-8")
    assert build_runtime_paths(install_root=program).runtime_root == away

    # Reinstalled into another folder: the never-filled automatic choice follows it.
    config.write_text(json.dumps({"runtime_root": str(tmp_path / "old-program" / "runtimes"),
                                  "runtime_root_source": "default_program"}), "utf-8")
    reset_runtime_paths()
    assert build_runtime_paths(install_root=program).runtime_root == program / "runtimes"


def test_environment_override_is_not_registered(tmp_path, monkeypatch):
    program = _program(tmp_path)
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(tmp_path / "qa-runtimes"))
    paths = bootstrap_runtime_paths(install_root=program, persist=True)
    assert paths.runtime_root == tmp_path / "qa-runtimes"
    assert paths.runtime_root_source == "environment"
    assert "runtime_root" not in _saved(tmp_path)


def test_setup_script_and_installer_use_the_passed_runtime_folder():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "setup_managed_backend.ps1").read_text("utf-8-sig")
    assert "$managed = $env:2BYTEASR_RUNTIME_ROOT" in script
    assert "$env:2BYTEASR_RUNTIME_ROOT = $managed" in script
    installer = (root / "scripts" / "install_managed_backend.py").read_text("utf-8")
    assert "managed = managed_runtime_root()" in installer
    assert "user_data_root() / 'runtimes'" not in installer


# ------------------------------------------------------------------ the move

def _junction(target: Path, link: Path) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def _launcher(path: Path, interpreter: Path) -> None:
    """A PE with uv's launcher resource (copied from a small Windows tool)."""
    import shutil
    shutil.copyfile(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe", path)
    path.write_bytes(relocation._relinked_launcher(path, str(interpreter)))
    assert relocation.launcher_python_path(path) == str(interpreter)


def _fixture(tmp_path, monkeypatch):
    """A runtime folder shaped like uv's, a model root and registered paths."""
    program = _program(tmp_path)
    local = _local(tmp_path)
    runtimes = local / "runtimes"
    full = runtimes / "python" / "cpython-3.10.19-windows-x86_64-none"
    full.mkdir(parents=True)
    (full / "python.exe").write_bytes(b"base python")
    _junction(full, runtimes / "python" / "cpython-3.10-windows-x86_64-none")
    venv = runtimes / "main" / "94c327b474d3ed9e"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "Lib" / "site-packages").mkdir(parents=True)
    # uv 0.11 launchers: a small PE whose UV_PYTHON_PATH resource names the
    # interpreter (base Python for python.exe, the venv python for scripts).
    _launcher(venv / "Scripts" / "python.exe", runtimes / "python" / "cpython-3.10-windows-x86_64-none" / "python.exe")
    _launcher(venv / "Scripts" / "accelerate.exe", venv / "Scripts" / "python.exe")
    (venv / "pyvenv.cfg").write_text(
        f"home = {runtimes}\\python\\cpython-3.10-windows-x86_64-none\nimplementation = CPython\n", "utf-8")
    (venv / "Scripts" / "activate.bat").write_text(f'@set "VIRTUAL_ENV={venv}"\n', "utf-8")
    cached = runtimes / "download-cache" / "archive-v0" / "abc"
    cached.mkdir(parents=True)
    (cached / "torch.py").write_bytes(b"x" * 4096)
    os.link(cached / "torch.py", venv / "Lib" / "site-packages" / "torch.py")
    (runtimes / "tools" / "uv-0.11.7").mkdir(parents=True)
    (runtimes / "tools" / "uv-0.11.7" / "uv.exe").write_bytes(b"uv")
    (runtimes / "bootstrap.lock").write_bytes(b"")
    python = venv / "Scripts" / "python.exe"
    (runtimes / "registry.json").write_text(json.dumps({"schema_version": 1, "runtimes": {
        "main": {"runtime_id": "main-runtime", "python_executable": str(python), "root": str(venv),
                 "source": "managed-model-bootstrap"},
        "moss": {"python_executable": str(tmp_path / "checkout" / ".venv-moss" / "Scripts" / "python.exe")},
    }}, indent=2), "utf-8")
    models = local / "Models"
    (models / MODEL).mkdir(parents=True)
    (models / MODEL / "a.bin").write_bytes(b"weights" * 100)
    (models / ".twobyteasr-models.json").write_text('{"models": {}}', "utf-8")
    (models / "my-notes").mkdir()
    (models / "my-notes" / "keep.txt").write_text("not ours", "utf-8")
    (local / "model-readiness").mkdir(parents=True)
    (local / "model-readiness" / "moss.json").write_text(json.dumps(
        {"status": "ready", "python": str(python), "model": str(models / MODEL)}), "utf-8")
    (local / "model-associations.json").write_text(json.dumps({"schema_version": 1, "detached": {
        os.path.normcase(str(models / MODEL)): {"model_key": "moss", "path": str(models / MODEL)}}}), "utf-8")
    bootstrap_runtime_paths(install_root=program, persist=True)
    runtime_paths.set_model_root(models)
    assert get_runtime_paths().managed_runtime_root == runtimes
    destination = tmp_path / "E-drive" / "兔白 数据"
    destination.mkdir(parents=True)
    return dict(program=program, runtimes=runtimes, models=models, venv=venv, python=python, destination=destination)


def _home(python: str) -> str:
    cfg = Path(python).parent.parent / "pyvenv.cfg"
    return next(line.split("=", 1)[1].strip() for line in cfg.read_text("utf-8").splitlines() if line.startswith("home"))


def _probe(fail_in=None):
    calls = []

    def probe(key, python, root):
        calls.append((key, python, str(root)))
        home = _home(python)
        # Like the real launcher: the process image is whatever UV_PYTHON_PATH names.
        image = relocation.launcher_python_path(python) or ""
        starts = Path(python).is_file() and Path(image).is_file() and relocation._inside(python, root)
        failed = fail_in is not None and relocation._inside(python, fail_in())
        return {"key": key, "starts": starts, "probe": starts and not failed, "base_prefix": home,
                "image": image, "problems": ["探测失败（测试注入）"] if failed else []}

    probe.calls = calls
    return probe


def _tree(root: Path) -> dict:
    found = {}
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(directory) / name
            info = os.lstat(path)
            link = os.readlink(path) if info.st_file_attributes & 0x400 else ""
            found[str(path.relative_to(root))] = (info.st_size if path.is_file() else -1, link,
                                                  path.read_bytes() if path.is_file() and not link else b"")
    return found


def _plan(destination, monkeypatch, *, force_copy=False):
    plan = relocation.plan_relocation(destination)
    if force_copy:
        for part in plan.parts:
            part.same_volume = False
    return plan


@windows_only
@pytest.mark.parametrize("force_copy", [False, True], ids=["rename", "copy"])
def test_move_rewrites_every_recorded_path_and_removes_the_old_copy(tmp_path, monkeypatch, force_copy):
    f = _fixture(tmp_path, monkeypatch)
    plan = _plan(f["destination"], monkeypatch, force_copy=force_copy)
    assert plan.ok, plan.problems
    assert {part.kind for part in plan.parts} == {"runtimes", "models"}
    assert all(part.same_volume is not force_copy for part in plan.parts)
    models_part = next(part for part in plan.parts if part.kind == "models")
    assert models_part.left_behind == ("my-notes",)
    runtime_part = next(part for part in plan.parts if part.kind == "runtimes")
    assert runtime_part.runtimes == (("main", str(f["python"])),)
    # Hard links count once: the cached torch.py and the installed copy are one file.
    inventory = relocation._inventory(runtime_part.source, runtime_part.entries)
    assert inventory.logical_bytes - inventory.unique_bytes == 4096 == inventory.logical_bytes - runtime_part.unique_bytes

    probe = _probe()
    result = relocation.execute_relocation(plan, probe=probe)
    assert result.status == "moved", result.messages
    new_runtimes, new_models = f["destination"] / "runtimes", f["destination"] / "models"
    new_venv = new_runtimes / "main" / "94c327b474d3ed9e"
    # Runtime folder: venv config, scripts, uv junction and registry point at the new place.
    assert _home(str(new_venv / "Scripts" / "python.exe")) == f"{new_runtimes}\\python\\cpython-3.10-windows-x86_64-none"
    assert str(new_venv) in (new_venv / "Scripts" / "activate.bat").read_text("utf-8")
    # uv launchers start the moved interpreters (packaged-build check, 2026-10-17).
    assert relocation.launcher_python_path(new_venv / "Scripts" / "python.exe") == str(
        new_runtimes / "python" / "cpython-3.10-windows-x86_64-none" / "python.exe")
    assert relocation.launcher_python_path(new_venv / "Scripts" / "accelerate.exe") == str(new_venv / "Scripts" / "python.exe")
    assert not list((new_venv / "Scripts").glob("*.relocate-*"))
    link = new_runtimes / "python" / "cpython-3.10-windows-x86_64-none"
    assert relocation._plain(os.readlink(link)) == str(new_runtimes / "python" / "cpython-3.10.19-windows-x86_64-none")
    registry = json.loads((new_runtimes / "registry.json").read_text("utf-8"))["runtimes"]
    assert registry["main"]["python_executable"] == str(new_venv / "Scripts" / "python.exe")
    assert registry["main"]["root"] == str(new_venv)
    assert registry["moss"]["python_executable"].startswith(str(tmp_path / "checkout"))  # outside: untouched
    installed, cached = new_venv / "Lib" / "site-packages" / "torch.py", new_runtimes / "download-cache" / "archive-v0" / "abc" / "torch.py"
    assert os.stat(installed).st_ino == os.stat(cached).st_ino
    assert (new_runtimes / "bootstrap.lock").is_file()
    # Models: ours moved, the user's own folder stays.
    assert (new_models / MODEL / "a.bin").read_bytes() == b"weights" * 100
    assert (new_models / ".twobyteasr-models.json").is_file()
    assert (f["models"] / "my-notes" / "keep.txt").is_file()
    assert not (f["models"] / MODEL).exists()
    # Registration, receipts and detach records.
    saved = _saved(tmp_path)
    assert saved["runtime_root"] == str(new_runtimes) and saved["runtime_root_source"] == "moved"
    assert Path(saved["model_root"]) == new_models.resolve()
    reset_runtime_paths()
    assert managed_runtime_root() == new_runtimes
    from twobyteasr.runtime_registry import resolve_runtime_python
    assert resolve_runtime_python("main", register=False) == str(new_venv / "Scripts" / "python.exe")
    receipt = json.loads((_local(tmp_path) / "model-readiness" / "moss.json").read_text("utf-8"))
    assert receipt["python"] == str(new_venv / "Scripts" / "python.exe") and receipt["model"] == str(new_models / MODEL)
    detached = json.loads((_local(tmp_path) / "model-associations.json").read_text("utf-8"))["detached"]
    assert list(detached) == [os.path.normcase(str(new_models / MODEL))]
    # The old runtime folder is gone; the probe ran before and after.
    assert not f["runtimes"].exists()
    assert [call[2] for call in probe.calls] == [str(f["runtimes"]), str(new_runtimes)]


@windows_only
@pytest.mark.parametrize("force_copy", [False, True], ids=["rename", "copy"])
def test_failed_check_after_the_move_restores_everything(tmp_path, monkeypatch, force_copy):
    f = _fixture(tmp_path, monkeypatch)
    before_runtimes, before_models = _tree(f["runtimes"]), _tree(f["models"])
    before_config = (_local(tmp_path) / "runtime_paths.json").read_bytes()
    plan = _plan(f["destination"], monkeypatch, force_copy=force_copy)
    result = relocation.execute_relocation(plan, probe=_probe(fail_in=lambda: f["destination"]))
    assert result.status == "failed"
    assert "已还原" in result.messages[0] and "探测失败" in result.messages[0]
    assert _tree(f["runtimes"]) == before_runtimes
    assert _tree(f["models"]) == before_models  # the models part never started
    assert (_local(tmp_path) / "runtime_paths.json").read_bytes() == before_config
    assert not (f["destination"] / "runtimes").exists()
    assert not result.leftovers


@windows_only
def test_cancel_while_copying_removes_the_partial_copy(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    before = _tree(f["runtimes"])
    plan = _plan(f["destination"], monkeypatch, force_copy=True)
    copied = []

    def progress(text, done, total):
        copied.append(done)

    result = relocation.execute_relocation(plan, probe=_probe(), progress=progress,
                                           cancel=lambda: any(done > 0 for done in copied))
    assert result.status == "cancelled"
    assert _tree(f["runtimes"]) == before
    assert not (f["destination"] / "runtimes").exists()
    assert managed_runtime_root() == f["runtimes"]


@windows_only
def test_models_failing_after_runtimes_moved_is_reported_as_partial(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    plan = _plan(f["destination"], monkeypatch, force_copy=True)
    counts = iter([0, 1])  # target first, then source: one model missing after the copy
    monkeypatch.setattr(runtime_paths, "complete_model_count", lambda *_args, **_kw: next(counts))
    result = relocation.execute_relocation(plan, probe=_probe())
    assert result.status == "partial" and result.moved == ["runtimes"]
    assert (f["models"] / MODEL / "a.bin").is_file()
    assert not (f["destination"] / "models").exists()
    reset_runtime_paths()
    assert get_runtime_paths().model_root == f["models"].resolve()
    assert managed_runtime_root() == f["destination"] / "runtimes"


@windows_only
def test_plan_refuses_unsafe_or_impossible_moves(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    # Target already holds something.
    (f["destination"] / "runtimes").mkdir()
    (f["destination"] / "runtimes" / "other.txt").write_text("x", "utf-8")
    assert any("已经有内容" in problem for problem in relocation.plan_relocation(f["destination"]).problems)
    # Inside the current runtime folder.
    inner = f["runtimes"] / "nested"
    inner.mkdir()
    assert any("不能在" in problem for problem in relocation.plan_relocation(inner).problems)
    # Not enough space for a copy to another drive (1 GB is kept free).
    empty = tmp_path / "F-drive"
    empty.mkdir()
    monkeypatch.setattr(relocation, "_same_volume", lambda *_paths: False)
    monkeypatch.setattr(relocation, "_free_bytes", lambda _path: 10)
    plan = relocation.plan_relocation(empty)
    assert plan.required_bytes > relocation.RESERVE_BYTES
    assert any("剩余" in problem and "需要" in problem for problem in plan.problems), plan.problems
    # Busy, missing and relative folders.
    assert any("等识别" in p for p in relocation.plan_relocation(empty, busy=lambda: True).problems)
    assert relocation.plan_relocation(tmp_path / "nowhere").problems
    assert relocation.plan_relocation("relative\\folder").problems


@windows_only
def test_nothing_downloaded_yet_only_registers_the_new_place(tmp_path, monkeypatch):
    program = _program(tmp_path)
    bootstrap_runtime_paths(install_root=program, persist=True)
    destination = tmp_path / "D-data"
    destination.mkdir()
    plan = relocation.plan_relocation(destination)
    assert plan.ok and all(part.empty for part in plan.parts) and plan.required_bytes == 0
    result = relocation.execute_relocation(plan, probe=_probe())
    assert result.status == "moved"
    reset_runtime_paths()
    assert managed_runtime_root() == destination / "runtimes"
    assert get_runtime_paths().model_root == (destination / "models").resolve()


def test_storage_maintenance_waits_while_a_move_runs(monkeypatch):
    from twobyteasr.storage_ui import app_busy

    class Owner:
        _run_in_progress = False

    monkeypatch.setattr("twobyteasr.storage_ui.existing_page", lambda *_a, **_k: None)
    assert app_busy(Owner()) is False
    relocation._RUNNING.set()
    try:
        assert app_busy(Owner()) is True
    finally:
        relocation._RUNNING.clear()


# ------------------------------------------------------------------- the UI

@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(qapp, condition, seconds=20):
    import time
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.02)
    assert condition()


@windows_only
def test_storage_panel_moves_both_and_updates_the_settings_field(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QDialog, QLineEdit, QVBoxLayout
    from twobyteasr.storage_relocation_ui import RelocationDialog
    from twobyteasr.storage_ui import StoragePanel
    f = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(relocation, "_probe_interpreter", _probe())
    settings = QDialog()
    settings.model_root_edit = QLineEdit(str(f["models"]))
    panel = StoragePanel(settings)
    QVBoxLayout(settings).addWidget(panel)
    assert str(f["runtimes"]) in panel.location_label.text() and panel.move_button is not None

    dialog = RelocationDialog(f["destination"], panel)
    dialog.moved.connect(panel._relocated)
    _wait(qapp, lambda: dialog.plan is not None)
    assert dialog.start_button.isEnabled(), dialog.problems.text()
    assert "runtimes" in dialog.summary.text() and "my-notes" in dialog.summary.text()
    dialog.start()
    _wait(qapp, lambda: dialog.result is not None)
    assert dialog.result.status == "moved", dialog.status.text()
    assert "移动完成" in dialog.status.text()
    assert settings.model_root_edit.text() == str((f["destination"] / "models").resolve())
    assert str(f["destination"] / "runtimes") in panel.location_label.text()
    assert panel.service.paths.managed_runtime_root == f["destination"] / "runtimes"
    dialog.deleteLater(); panel.deleteLater(); settings.deleteLater(); qapp.processEvents()


@windows_only
def test_dialog_refuses_to_start_and_says_why(tmp_path, monkeypatch, qapp):
    from twobyteasr.storage_relocation_ui import RelocationDialog
    f = _fixture(tmp_path, monkeypatch)
    dialog = RelocationDialog(f["destination"], busy=lambda: True)
    _wait(qapp, lambda: dialog.plan is not None)
    assert not dialog.start_button.isEnabled()
    assert "等识别" in dialog.problems.text()
    dialog.deleteLater(); qapp.processEvents()


def _hold(path):
    """Open ``path`` without sharing, as a scanner or a stuck worker would."""
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                   ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    return lambda: kernel.CloseHandle(ctypes.c_void_p(handle))


@windows_only
def test_a_file_held_by_another_program_stops_the_copy_and_restores_everything(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    before = _tree(f["runtimes"])
    plan = _plan(f["destination"], monkeypatch, force_copy=True)
    release = _hold(f["venv"] / "Scripts" / "activate.bat")
    try:
        result = relocation.execute_relocation(plan, probe=_probe())
    finally:
        release()
    assert result.status == "failed"
    assert "正被其他程序占用" in result.messages[0] and "\\?\\" not in result.messages[0]
    assert _tree(f["runtimes"]) == before
    assert not (f["destination"] / "runtimes").exists()
    assert managed_runtime_root() == f["runtimes"]


@windows_only
def test_rename_waits_for_a_file_that_is_released_soon(tmp_path, monkeypatch):
    # 2026-10-17 on H:: renaming right after the check ran the interpreter was refused for a moment.
    import threading
    f = _fixture(tmp_path, monkeypatch)
    plan = _plan(f["destination"], monkeypatch)
    assert all(part.same_volume for part in plan.parts)
    release = _hold(f["venv"] / "Scripts" / "activate.bat")
    threading.Timer(.8, release).start()
    result = relocation.execute_relocation(plan, probe=_probe())
    assert result.status == "moved", result.messages
    assert (f["destination"] / "runtimes" / "main" / "94c327b474d3ed9e" / "Scripts" / "activate.bat").is_file()


@windows_only
def test_rename_gives_up_with_a_plain_reason_and_restores_everything(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    before = _tree(f["runtimes"])
    monkeypatch.setattr(relocation, "_RENAME_WAIT_S", .5)
    plan = _plan(f["destination"], monkeypatch)
    release = _hold(f["venv"] / "Scripts" / "activate.bat")
    try:
        result = relocation.execute_relocation(plan, probe=_probe())
    finally:
        release()
    assert result.status == "failed"
    assert "正被其他程序使用" in result.messages[0]
    assert _tree(f["runtimes"]) == before
    assert not (f["destination"] / "runtimes").exists()


@windows_only
@pytest.mark.parametrize("force_copy", [False, True], ids=["rename", "copy"])
def test_a_launcher_still_starting_the_old_python_is_caught_and_rolled_back(tmp_path, monkeypatch, force_copy):
    # The packaged-build check found the move reporting success while python.exe still
    # started the old base Python; deleting the old copy then broke recognition.
    f = _fixture(tmp_path, monkeypatch)
    before = _tree(f["runtimes"])
    monkeypatch.setattr(relocation, "_relinked_launcher", lambda path, value: Path(path).read_bytes())
    plan = _plan(f["destination"], monkeypatch, force_copy=force_copy)
    result = relocation.execute_relocation(plan, probe=_probe())
    assert result.status == "failed"
    # Copy: the old Python still exists, so only the image check sees it. Rename:
    # the old path is already gone, so the launcher does not start at all.
    expected = "仍在使用旧位置的 Python" if force_copy else "移动后无法启动"
    assert expected in result.messages[0], result.messages
    assert _tree(f["runtimes"]) == before
    assert not (f["destination"] / "runtimes").exists()
    assert managed_runtime_root() == f["runtimes"]


@windows_only
def test_closing_settings_after_a_move_does_not_ask_to_save(tmp_path, monkeypatch, qapp):
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog
    f = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(relocation, "_probe_interpreter", _probe())
    settings = ApplicationSettingsDialog(None, {}, tmp_path / "projects", browse=lambda *a: None,
                                         clear_recent=lambda: None, reset_layout=None)
    assert settings._values() == settings._saved_values
    plan = relocation.plan_relocation(f["destination"])
    result = relocation.execute_relocation(plan, probe=_probe())
    assert result.status == "moved"
    settings.storage_panel._relocated(result)
    assert settings.model_root_edit.text() == str((f["destination"] / "models").resolve())
    assert settings._values() == settings._saved_values
    settings.deleteLater(); qapp.processEvents()
