"""Model download location chosen in 存储管理 (user report 2026-10-15).

The user moved the model location off C: and every download stopped at
``download_models.ps1`` line 33 with ``New-Item：路径的形式不合法``. Reproduced:
``New-Item -ItemType Directory -Path E:\\ -Force`` rejects a drive root, which is
what the folder picker returns when the whole drive is chosen. These tests run
the real script; nothing is downloaded (verify-only, or a stand-in source).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "download_models.ps1"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell installer")


def _powershell() -> str:
    candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate if candidate.is_file() else "powershell.exe")


def _run(script: Path, env: dict[str, str], *arguments: str) -> tuple[int, str]:
    # Same invocation as ModelDownloadDialog.start: the location travels in
    # 2BYTEASR_MODEL_ROOT, not on the command line.
    completed = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
        env=env, cwd=str(script.parents[1]), capture_output=True, timeout=180)
    output = (completed.stdout + b"\n" + completed.stderr).decode("utf-8", errors="replace")
    return completed.returncode, output


def _environment(model_root: str, *, test_root: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("TWOBYTEASR_TEST_ROOT", None)
    if test_root is not None:
        env["TWOBYTEASR_TEST_ROOT"] = str(test_root)
    env["2BYTEASR_MODEL_ROOT"] = model_root
    env["TWOBYTEASR_MAIN_PYTHON"] = sys.executable
    return env


def test_drive_root_location_reaches_model_checks():
    """The reported failure: a whole drive (E:\\) as the model location.

    Verify-only reads the system drive root and writes nothing there.
    """
    drive_root = os.environ.get("SystemDrive", "C:") + "\\"
    repository = json.loads((ROOT / "dependencies.lock.json").read_text("utf-8-sig"))["models"]["firered_vad"]["repository"]
    code, output = _run(SCRIPT, _environment(drive_root, test_root=None), "-VerifyOnly", "-Only", "firered_vad")
    assert "[2BYTEASR_MODEL_ROOT_ERROR]" not in output, output
    assert "路径的形式不合法" not in output and "not of a legal form" not in output, output
    # The per-model check ran: "[OK] repo" or "[缺文件或哈希不匹配] repo".
    assert f"] {repository}" in output, output
    assert code in (0, 1)


STAND_IN_DOWNLOADER = '''\
"""Stand-in for scripts/run_repository_download.py: writes fixture bytes, no network."""
import argparse, json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")  # as the real entry script; -I ignores PYTHONIOENCODING
parser = argparse.ArgumentParser()
for name in ("--model", "--mode", "--lock", "--destination", "--staging-root"):
    parser.add_argument(name)
args = parser.parse_args()
sandbox = Path(__file__).resolve().parents[1]
with (sandbox / "stand-in-calls.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(vars(args), ensure_ascii=False) + "\\n")
destination = Path(args.destination)
Path(args.staging_root).mkdir(parents=True, exist_ok=True)
files = json.loads(Path(args.lock).read_text("utf-8"))["stand_in_files"]
for name, text in files.items():
    (destination / name).write_bytes(text.encode("utf-8"))
print("[stand-in] wrote", destination)
'''


def _sandbox(tmp_path: Path) -> Path:
    """A program folder with the real script, a one-model lock and a stand-in source."""
    program = tmp_path / "program"
    (program / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, program / "scripts" / "download_models.ps1")
    (program / "scripts" / "run_repository_download.py").write_text(STAND_IN_DOWNLOADER, "utf-8")
    files = {"embedding_model.ckpt": "stand-in weights\n", "hyperparams.yaml": "stand-in: true\n"}
    lock = {
        "models": {"speaker_embedding": {
            # resource_only: no runtime install and no load check for the stand-in.
            "path": "models/spkrec-ecapa-voxceleb", "repository": "stand-in/speaker", "revision": "r1",
            "resource_only": True, "download_bytes": 64, "required_files": sorted(files),
            "sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest().upper() for name, text in files.items()},
        }},
        "stand_in_files": files,
    }
    (program / "dependencies.lock.json").write_text(json.dumps(lock, ensure_ascii=False), "utf-8")
    return program


@pytest.mark.parametrize("folder", ["下载", "下载 [新]"])
@pytest.mark.parametrize("form", ["plain", "trailing_backslash", "forward_slashes"])
def test_custom_location_with_spaces_chinese_and_brackets_downloads(tmp_path, form, folder):
    program = _sandbox(tmp_path)
    location = tmp_path / "E盘 模型" / folder
    value = {"plain": str(location), "trailing_backslash": str(location) + "\\",
             "forward_slashes": str(location).replace("\\", "/")}[form]
    env = _environment(value, test_root=tmp_path)
    script = program / "scripts" / "download_models.ps1"

    code, output = _run(script, env, "-Yes", "-Only", "speaker_embedding", "-Source", "AUTO")
    assert code == 0, output
    assert "[完成]" in output, output
    folder = location / "spkrec-ecapa-voxceleb"
    assert (folder / "embedding_model.ckpt").read_text("utf-8") == "stand-in weights\n"
    assert (folder / "custom.py").is_file()
    manifest = json.loads((location / ".twobyteasr-models.json").read_text("utf-8-sig"))
    assert manifest["models"] == {"speaker_embedding": "r1"}
    calls = [json.loads(line) for line in (program / "stand-in-calls.jsonl").read_text("utf-8").splitlines()]
    assert len(calls) == 1
    same = lambda a, b: os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    assert same(calls[0]["destination"], str(folder)), calls
    assert same(calls[0]["staging_root"], str(location / ".downloads")), calls

    # Second run: the verified files are found in place and nothing is fetched again.
    code, output = _run(script, env, "-Yes", "-Only", "speaker_embedding", "-Source", "AUTO")
    assert code == 0, output
    assert "模型已全部就绪" in output, output
    assert len((program / "stand-in-calls.jsonl").read_text("utf-8").splitlines()) == 1


def test_unusable_location_is_reported_as_a_storage_problem(tmp_path):
    program = _sandbox(tmp_path)
    blocker = tmp_path / "不是文件夹.txt"
    blocker.write_text("a file where the folder should be", "utf-8")
    location = blocker / "models"
    code, output = _run(program / "scripts" / "download_models.ps1", _environment(str(location), test_root=tmp_path),
                        "-Yes", "-Only", "speaker_embedding", "-Source", "AUTO")
    assert code != 0
    marker = next(line for line in output.splitlines() if line.startswith("[2BYTEASR_MODEL_ROOT_ERROR] "))
    assert json.loads(marker.split(" ", 1)[1])["path"] == str(location)
    assert not (program / "stand-in-calls.jsonl").exists()

    # The download window names the storage location, not the runtime.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from twobyteasr.local_models.model_workshop import MODELS, ModelDownloadDialog
    QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.download_key == "qwen_asr")
    dialog = ModelDownloadDialog(ROOT, model)
    try:
        dialog._phase = "preparing"
        dialog.log.appendPlainText(output)
        message = dialog._actionable_failure_message(code)
        assert "模型存储位置不可用" in message and str(location) in message and "存储管理" in message
        assert "运行环境准备失败" not in message
    finally:
        dialog.deleteLater()


def test_storage_manager_saves_a_new_location_the_same_validated_way(tmp_path, monkeypatch):
    """存储管理 → 更改 creates and write-tests the folder now, like 应用设置 (2026-10-15)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from twobyteasr import runtime_paths as rp
    from twobyteasr.local_models import model_storage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv(rp.USER_DATA_ENV, str(tmp_path / "profile"))
    monkeypatch.delenv(rp.MODEL_ROOT_ENV, raising=False)
    old = tmp_path / "old"
    old.mkdir()
    rp.reset_runtime_paths()
    rp.set_model_root(old)
    monkeypatch.setattr(model_storage.ModelStorageDialog, "refresh", lambda self: None)
    dialog = model_storage.ModelStorageDialog(ROOT, (), lambda: set(), lambda *a: None, lambda *a: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    try:
        new = tmp_path / "E盘 模型" / "下载 [新]"          # not created yet; Qt returns forward slashes
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: new.as_posix())
        dialog._change_model_root()
        assert new.is_dir() and rp.get_runtime_paths().model_root == new and warnings == []
        assert dialog.model_root_edit.text() == str(new)

        blocker = tmp_path / "file.txt"
        blocker.write_text("x", "utf-8")
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: (blocker / "models").as_posix())
        dialog._change_model_root()
        assert rp.get_runtime_paths().model_root == new and len(warnings) == 1
    finally:
        dialog.deleteLater()
        rp.reset_runtime_paths()
