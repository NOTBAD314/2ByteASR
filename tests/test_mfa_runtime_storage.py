"""MFA's conda runtime in storage management, card uninstall and the runtime move (2026-10-19).

The experimental Montreal Forced Aligner runs in ``<runtime root>\\mfa``
(about 2 GB, plus the installer's ``mfa-install``). It is not in the uv
runtime registry, so the storage page did not list it and uninstalling the
MFA card left it (and the Japanese model) behind.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.runtime_paths import MODEL_ROOT_ENV, RUNTIME_ROOT_ENV, reset_runtime_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
windows_only = pytest.mark.skipif(os.name != "nt", reason="the MFA runtime is Windows only")


@pytest.fixture
def runtimes(tmp_path, monkeypatch):
    root = tmp_path / "runtimes"
    root.mkdir()
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(root))
    monkeypatch.delenv("TWOBYTEASR_MFA_PREFIX", raising=False)
    reset_runtime_paths()
    from twobyteasr.local_models import model_runtime_cleanup
    monkeypatch.setattr(model_runtime_cleanup, "_running_paths", lambda: [])
    yield root
    reset_runtime_paths()


def _junction(target: Path, link: Path) -> None:
    import subprocess
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


def _env(runtimes: Path, tmp_path: Path, *, complete=True) -> dict:
    """A conda env shaped like the installer's: interpreter, conda-meta, DLLs, empty and read-only bits."""
    env = runtimes / "mfa"
    (env / "conda-meta").mkdir(parents=True)
    (env / "python.exe").write_bytes(b"p" * 1000)
    (env / "conda-meta" / "kaldi-5.5.json").write_text('{"files": []}', "utf-8")
    if complete:
        (env / "conda-meta" / "2byteasr-mfa-runtime.json").write_text('{"montreal_forced_aligner": "3.4.3"}', "utf-8")
    (env / "Library" / "bin").mkdir(parents=True)
    (env / "Library" / "bin" / "kaldi-base.dll").write_bytes(b"k" * 5000)
    (env / "Lib" / "site-packages" / "__pycache__").mkdir(parents=True)
    (env / "Lib" / "site-packages" / "mfa.py").write_bytes(b"m" * 300)
    (env / "etc" / "conda" / "deactivate.d").mkdir(parents=True)  # stays empty
    locked = env / "share" / "readonly.txt"
    locked.parent.mkdir(parents=True)
    locked.write_bytes(b"r" * 20)
    os.chmod(locked, stat.S_IREAD)
    outside = tmp_path / "user-folder"
    outside.mkdir(exist_ok=True)
    (outside / "keep.txt").write_text("not the app's", "utf-8")
    _junction(outside, env / "share" / "linked")
    work = runtimes / "mfa-install"
    work.mkdir()
    (work / "micromamba.exe").write_bytes(b"u" * 700)
    (runtimes / "registry.json").write_text('{"runtimes": {}}', "utf-8")
    (runtimes / "main").mkdir()
    (runtimes / "main" / "keep.txt").write_text("uv runtime", "utf-8")
    return dict(env=env, work=work, outside=outside, files=6 if complete else 5)


@windows_only
def test_plan_counts_every_file_keeps_conda_meta_last_and_does_not_follow_links(runtimes, tmp_path):
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal
    f = _env(runtimes, tmp_path)
    plan = plan_mfa_runtime_removal()
    assert plan.root == f["env"] and plan.ready and not plan.protected_reason
    assert plan.files == f["files"]  # the junction's target is not counted
    assert plan.logical_bytes == 1000 + 5000 + 300 + 20 + len('{"files": []}') + len('{"montreal_forced_aligner": "3.4.3"}')
    env_plan, work_plan = plan.removals
    assert work_plan.root == f["work"] and plan.total_bytes == plan.logical_bytes + 700
    assert f["env"] / "share" / "linked" in env_plan.paths
    assert not any(f["outside"] in path.parents for path in env_plan.paths)
    # The marker that says "this is the MFA env" goes last.
    assert {p.parent.name for p in env_plan.paths[-2:]} == {"conda-meta"}


@windows_only
def test_removal_deletes_env_installer_and_marker_and_nothing_else(runtimes, tmp_path):
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal, remove_mfa_runtime
    from twobyteasr.recognition import mfa_aligner
    f = _env(runtimes, tmp_path)
    assert mfa_aligner.runtime_python() == str(f["env"] / "python.exe")
    result = remove_mfa_runtime(plan_mfa_runtime_removal())
    assert result.completed, result.failures
    assert not f["env"].exists() and not f["work"].exists()
    assert not (runtimes / "mfa.install-pending.json").exists()
    assert (f["outside"] / "keep.txt").read_text("utf-8") == "not the app's"
    assert (runtimes / "main" / "keep.txt").exists() and (runtimes / "registry.json").exists()
    assert result.logical_bytes >= 1000 + 5000 + 700
    assert mfa_aligner.runtime_python() is None and plan_mfa_runtime_removal() is None


@windows_only
def test_removal_refuses_while_busy_or_while_mfa_runs_from_it(runtimes, tmp_path, monkeypatch):
    from twobyteasr.local_models import model_runtime_cleanup
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal, remove_mfa_runtime
    f = _env(runtimes, tmp_path)
    plan = plan_mfa_runtime_removal()
    assert remove_mfa_runtime(plan, busy=lambda: True).failures
    monkeypatch.setattr(model_runtime_cleanup, "_running_paths", lambda: [f["env"] / "python.exe"])
    refused = remove_mfa_runtime(plan)
    assert "运行中的进程" in next(iter(refused.failures.values()))
    assert (f["env"] / "python.exe").exists() and not (runtimes / "mfa.install-pending.json").exists()


@windows_only
def test_interrupted_removal_leaves_a_repairable_runtime_and_can_be_finished(runtimes, tmp_path, monkeypatch):
    from twobyteasr.local_models import model_runtime_cleanup
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal, remove_mfa_runtime
    from twobyteasr.recognition import mfa_aligner
    f = _env(runtimes, tmp_path)
    real = model_runtime_cleanup._unlink_owned
    deleted = []

    def flaky(path):
        if len(deleted) == 2:
            raise PermissionError("held by another program")
        real(path)
        deleted.append(path)

    monkeypatch.setattr(model_runtime_cleanup, "_unlink_owned", flaky)
    first = remove_mfa_runtime(plan_mfa_runtime_removal())
    assert first.failures and not first.completed
    # Never left looking complete: the installer's pending marker is there and conda-meta is kept.
    assert (runtimes / "mfa.install-pending.json").exists() and (f["env"] / "conda-meta").is_dir()
    assert mfa_aligner.runtime_python() is None
    monkeypatch.setattr(model_runtime_cleanup, "_unlink_owned", real)
    retry = plan_mfa_runtime_removal()
    assert not retry.protected_reason
    assert remove_mfa_runtime(retry).completed
    assert not f["env"].exists() and not (runtimes / "mfa.install-pending.json").exists()


@windows_only
def test_folders_the_app_does_not_own_are_not_deleted(runtimes, tmp_path, monkeypatch):
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal, remove_mfa_runtime
    stranger = runtimes / "mfa"
    stranger.mkdir()
    (stranger / "notes.txt").write_text("someone else's", "utf-8")
    plan = plan_mfa_runtime_removal()
    assert "不是兔白字幕安装" in plan.protected_reason and not plan.removals
    assert plan.files == 1 and plan.logical_bytes == len("someone else's")  # still shown with its size
    assert remove_mfa_runtime(plan).failures and (stranger / "notes.txt").exists()
    # A prefix chosen by environment variable is shown, never deleted.
    elsewhere = tmp_path / "dev-env"
    (elsewhere / "conda-meta").mkdir(parents=True)
    (elsewhere / "python.exe").write_bytes(b"p")
    monkeypatch.setenv("TWOBYTEASR_MFA_PREFIX", str(elsewhere))
    plan = plan_mfa_runtime_removal()
    assert plan.root == elsewhere and "TWOBYTEASR_MFA_PREFIX" in plan.protected_reason
    assert remove_mfa_runtime(plan).failures and (elsewhere / "python.exe").exists()


def _mfa_card():
    from twobyteasr.local_models import model_workshop
    return next(model for model in model_workshop.MODELS if model.key == "mfa_aligner")


@windows_only
def test_storage_scan_shows_the_mfa_runtime_for_the_mfa_model(runtimes, tmp_path):
    from twobyteasr.local_models.model_storage import scan_storage
    f = _env(runtimes, tmp_path)
    entry, = scan_storage(ROOT, [_mfa_card()], set())
    assert entry.environment_name == "mfa" and entry.environment_path == f["env"]
    assert entry.environment_bytes > 6000  # not ".venv-main · 未安装" any more
    _remove_fixture(f["env"])
    entry, = scan_storage(ROOT, [_mfa_card()], set())
    assert entry.environment_bytes == 0


def _remove_fixture(env: Path) -> None:
    import shutil
    os.rmdir(env / "share" / "linked")  # the junction only, not its target
    for path in env.rglob("*"):
        if path.is_file():
            os.chmod(path, stat.S_IWRITE)
    shutil.rmtree(env)


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(qapp, condition, seconds=20):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.02)
    assert condition()


@windows_only
def test_storage_page_lists_the_runtime_and_deletes_it_after_confirmation(runtimes, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton
    from twobyteasr.local_models.model_storage import ModelStorageDialog
    f = _env(runtimes, tmp_path)
    asked, shown = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or QMessageBox.StandardButton.Ok)
    current = {"mfa_aligner"}
    dialog = ModelStorageDialog(ROOT, [_mfa_card()], lambda: set(current), lambda *a: None, lambda *a: None)
    _wait(qapp, lambda: dialog._scanner is None)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert "MFA 运行环境（实验）" in texts and "当前使用" in texts
    assert any(str(f["env"]) in text and "6 个文件" in text for text in texts)
    assert any("mfa · " in text for text in texts)  # the MFA model row names its runtime
    delete = next(button for button in dialog.findChildren(QPushButton) if button.text() == "删除运行环境")
    # In use as the timeline: refused before anything is asked.
    delete.click()
    assert not asked and "字幕时间轴正在用 MFA" in shown[-1] and f["env"].exists()
    current.clear()
    delete.click()
    assert str(f["env"]) in asked[-1] and "回收站" in asked[-1]
    _wait(qapp, lambda: dialog._history_worker is None and not f["env"].exists())
    _wait(qapp, lambda: dialog._scanner is None and dialog._mfa_runtime is None)
    assert not f["work"].exists() and "已永久删除" in shown[-1]
    assert "MFA 运行环境（实验）" not in [label.text() for label in dialog.findChildren(QLabel) if label.isVisibleTo(dialog)]
    dialog.deleteLater()
    qapp.processEvents()


def _model_folder(models: Path, key: str) -> Path:
    lock = json.loads((ROOT / "dependencies.lock.json").read_text("utf-8"))
    spec = lock["models"][key]
    folder = models / Path(spec["path"]).name
    for name in spec["required_files"]:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"w" * 64)
    # Downloaded by the app into this model folder (not a manually linked one).
    manifest = models / ".twobyteasr-models.json"
    payload = json.loads(manifest.read_text("utf-8")) if manifest.exists() else {"models": {}}
    payload["models"][key] = {"path": str(folder)}
    manifest.write_text(json.dumps(payload), "utf-8")
    return folder


@windows_only
def test_uninstalling_the_mfa_card_removes_both_models_and_offers_the_runtime(runtimes, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    models = tmp_path / "models"
    monkeypatch.setenv(MODEL_ROOT_ENV, str(models))
    reset_runtime_paths()
    mandarin, japanese = _model_folder(models, "mfa_aligner"), _model_folder(models, "mfa_aligner_ja")
    f = _env(runtimes, tmp_path)
    prompts = []

    def answer(box):
        prompts.append((box.windowTitle(), box.text(), box.checkBox()))
        return QMessageBox.StandardButton.Yes if box.checkBox() is not None else QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", answer)
    page = ModelWorkshopPage(ROOT, {"models": {"primary_asr_backend": "moss", "firered_asr_backend": "qwen_aligner",
                                               "qwen_asr_backend": "off"}})
    done = []
    page.removal_finished.connect(done.append)
    page._uninstall_model("mfa_aligner")
    _wait(qapp, lambda: done and not page._removing, seconds=30)
    title, text, box = prompts[0]
    assert str(japanese) in text and str(f["env"]) in text
    assert box is not None and box.isChecked() and "只有这张卡使用" in box.text()
    _key, result, error, runtime = done[0]
    assert not error and result.completed and runtime is not None and runtime.completed
    assert not mandarin.exists() and not japanese.exists() and not f["env"].exists()
    assert "MFA 运行环境：已永久删除" in prompts[-1][1]
    card = page._cards["mfa_aligner"].model
    assert page._compute_model_state(card, "timeline") == "missing"
    assert page._action_text(card, "missing") == ("下载", True)
    page.deleteLater()
    qapp.processEvents()


@windows_only
def test_unticking_the_box_keeps_the_runtime(runtimes, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    models = tmp_path / "models"
    monkeypatch.setenv(MODEL_ROOT_ENV, str(models))
    reset_runtime_paths()
    _model_folder(models, "mfa_aligner"), _model_folder(models, "mfa_aligner_ja")
    f = _env(runtimes, tmp_path)

    def answer(box):
        if box.checkBox() is not None:
            box.checkBox().setChecked(False)
            return QMessageBox.StandardButton.Yes
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", answer)
    page = ModelWorkshopPage(ROOT, {"models": {"firered_asr_backend": "qwen_aligner", "qwen_asr_backend": "off"}})
    done = []
    page.removal_finished.connect(done.append)
    page._uninstall_model("mfa_aligner")
    _wait(qapp, lambda: done and not page._removing, seconds=30)
    assert done[0][3] is None and (f["env"] / "python.exe").exists()
    page.deleteLater()
    qapp.processEvents()


@windows_only
def test_card_offers_repair_once_only_the_runtime_is_gone(runtimes, tmp_path, monkeypatch):
    from twobyteasr.local_models import model_workshop
    from twobyteasr.local_models.model_runtime_cleanup import plan_mfa_runtime_removal, remove_mfa_runtime
    _env(runtimes, tmp_path)
    card = _mfa_card()
    page = SimpleNamespace(runtime_settings={"models": {}}, _installed={"mfa_aligner", "mfa_aligner_ja"},
                           _registry=None, _active_download_dialog=lambda key: None, _removing=set())
    monkeypatch.setattr(model_workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(model_workshop, "_runtime_role_available", lambda *a: True)
    monkeypatch.setattr(model_workshop, "_readiness_status", lambda key: "PASS")
    assert model_workshop.ModelWorkshopPage._compute_model_state(page, card, "timeline") == "installed"
    assert remove_mfa_runtime(plan_mfa_runtime_removal()).completed
    state = model_workshop.ModelWorkshopPage._compute_model_state(page, card, "timeline")
    assert state == "runtime_missing"
    assert model_workshop.ModelWorkshopPage._action_text(page, card, state) == ("安装 / 修复独立环境", True)


# ------------------------------------------------------------ runtime move

@pytest.fixture
def relocation_paths(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import USER_DATA_ENV, bootstrap_runtime_paths
    monkeypatch.delenv("TWOBYTEASR_TEST_ROOT", raising=False)
    monkeypatch.delenv(USER_DATA_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_ROOT_ENV, raising=False)
    monkeypatch.delenv("TWOBYTEASR_MFA_PREFIX", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv(MODEL_ROOT_ENV, "")
    reset_runtime_paths()
    program = tmp_path / "program"
    program.mkdir()
    (program / "dependencies.lock.json").write_text('{"schema_version": 1, "models": {}}', "utf-8")
    runtimes = tmp_path / "local" / "2ByteASR" / "runtimes"
    runtimes.mkdir(parents=True)
    paths = bootstrap_runtime_paths(install_root=program, persist=True)
    assert paths.managed_runtime_root == runtimes
    destination = tmp_path / "E-drive" / "兔白 数据"
    destination.mkdir(parents=True)
    yield runtimes, destination
    reset_runtime_paths()


def _mfa_probe(fail_after_move=False):
    calls = []

    def probe(key, python, root):
        calls.append((key, python, str(root)))
        moved = "E-drive" in python
        ok = Path(python).is_file() and not (fail_after_move and moved)
        return {"key": key, "starts": ok, "probe": ok, "base_prefix": str(Path(python).parent),
                "image": python, "dll": "", "problems": [] if ok else ["MFA 组件无法加载（测试注入）"]}

    probe.calls = calls
    return probe


@windows_only
@pytest.mark.parametrize("force_copy", [False, True], ids=["rename", "copy"])
def test_runtime_move_takes_mfa_along_and_checks_it_before_and_after(relocation_paths, tmp_path, force_copy):
    from twobyteasr.recognition import mfa_aligner
    from twobyteasr.storage import storage_relocation as relocation
    runtimes, destination = relocation_paths
    old = runtimes / "mfa"
    (old / "conda-meta").mkdir(parents=True)
    (old / "conda-meta" / "2byteasr-mfa-runtime.json").write_text("{}", "utf-8")
    (old / "python.exe").write_bytes(b"conda python")
    (runtimes / "mfa-install").mkdir()
    (runtimes / "mfa-install" / "micromamba.exe").write_bytes(b"u")
    plan = relocation.plan_relocation(destination, kinds=(relocation.RUNTIMES,))
    assert plan.ok, plan.problems
    part, = plan.parts
    assert part.runtimes == (("mfa", str(old / "python.exe")),)
    if force_copy:
        part.same_volume = False
    probe = _mfa_probe()
    result = relocation.execute_relocation(plan, probe=probe)
    assert result.status == "moved", result.messages
    new = destination / "runtimes" / "mfa"
    assert [call[:2] for call in probe.calls] == [("mfa", str(old / "python.exe")), ("mfa", str(new / "python.exe"))]
    assert not old.exists() and (destination / "runtimes" / "mfa-install" / "micromamba.exe").exists()
    assert mfa_aligner.runtime_python() == str(new / "python.exe")


@windows_only
def test_runtime_move_is_rolled_back_when_mfa_breaks_after_the_move(relocation_paths):
    from twobyteasr.recognition import mfa_aligner
    from twobyteasr.storage import storage_relocation as relocation
    runtimes, destination = relocation_paths
    old = runtimes / "mfa"
    (old / "conda-meta").mkdir(parents=True)
    (old / "conda-meta" / "2byteasr-mfa-runtime.json").write_text("{}", "utf-8")
    (old / "python.exe").write_bytes(b"conda python")
    plan = relocation.plan_relocation(destination, kinds=(relocation.RUNTIMES,))
    result = relocation.execute_relocation(plan, probe=_mfa_probe(fail_after_move=True))
    assert result.status != "moved"
    assert (old / "python.exe").exists() and mfa_aligner.runtime_python() == str(old / "python.exe")
    assert not (destination / "runtimes" / "mfa").exists()


@windows_only
def test_move_check_starts_mfa_with_its_dll_folders(tmp_path, monkeypatch):
    from twobyteasr.storage import storage_relocation as relocation
    from twobyteasr.system import processes
    env = tmp_path / "runtimes" / "mfa"
    env.mkdir(parents=True)
    (env / "python.exe").write_bytes(b"p")
    seen, cwds = [], []

    def run(command, **kwargs):
        seen.append((command, kwargs["env"]))
        cwds.append(kwargs.get("cwd"))
        out = json.dumps([str(env), str(env), str(env / "python.exe"), str(env / "python311.dll")])
        return SimpleNamespace(returncode=0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(processes, "run_hidden_subprocess", run)
    report = relocation._probe_interpreter("mfa", str(env / "python.exe"), tmp_path / "runtimes")
    assert report["starts"] and report["probe"] is True
    assert len(seen) == 2 and "_kalpy" in seen[1][0][-1]
    assert all(kwargs_cwd == str(env) for kwargs_cwd in cwds)  # never the program folder (898e7423)
    for _command, child in seen:
        assert child["PATH"].split(os.pathsep)[:4] == [str(env), str(env / "Library/mingw-w64/bin"),
                                                       str(env / "Library/usr/bin"), str(env / "Library/bin")]
