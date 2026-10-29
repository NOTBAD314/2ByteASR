"""mpv on PCs without a Vulkan driver (2026-10-17).

The bundled mpv.exe imports vulkan-1.dll, which only GPU drivers install. On a
VM or remote desktop Windows refused to start mpv (0xC0000135) and Studio waited
30 s before saying only "准备超时". Studio now appends the bundled Khronos loader
to the END of mpv's PATH (a driver's own loader in System32 still wins), and a
loader-level exit fails 准备播放器 at once with the reason.
"""
import os
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from twobyteasr.playback import studio_mpv
from twobyteasr.playback.studio_mpv import (
    MpvController,
    mpv_environment,
    startup_failure_message,
    vulkan_loader_fallback_dir,
)


def _loader(root, *parts):
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True)
    (folder / "vulkan-1.dll").write_bytes(b"MZ")
    return folder


def test_installed_loader_goes_last_on_mpv_path(tmp_path):
    folder = _loader(tmp_path, "third_party", "vulkan-loader")
    base = {"PATH": os.pathsep.join([r"C:\Windows\system32", r"C:\Tools"]), "KEEP": "1"}

    env = mpv_environment(base, root=tmp_path, windows=True)

    assert env["PATH"].split(os.pathsep) == [r"C:\Windows\system32", r"C:\Tools", str(folder)]
    assert env["KEEP"] == "1"
    assert base["PATH"] == os.pathsep.join([r"C:\Windows\system32", r"C:\Tools"])
    again = mpv_environment(env, root=tmp_path, windows=True)
    assert again["PATH"].split(os.pathsep).count(str(folder)) == 1


def test_source_tree_uses_collected_tools_folder(tmp_path):
    folder = _loader(tmp_path, "tools", "vulkan-loader")

    assert vulkan_loader_fallback_dir(tmp_path) == folder
    assert mpv_environment({"PATH": r"C:\Windows"}, root=tmp_path, windows=True)["PATH"].endswith(str(folder))


def test_path_is_untouched_without_loader_or_off_windows(tmp_path):
    base = {"PATH": r"C:\Windows"}
    (tmp_path / "third_party" / "vulkan-loader").mkdir(parents=True)  # folder without the DLL

    assert mpv_environment(base, root=tmp_path, windows=True)["PATH"] == r"C:\Windows"
    _loader(tmp_path, "tools", "vulkan-loader")
    assert mpv_environment(base, root=tmp_path, windows=False)["PATH"] == r"C:\Windows"


def test_windows_loader_exit_codes_explain_themselves():
    missing = startup_failure_message(3221225781)
    assert "vulkan-1.dll" in missing and "0xC0000135" in missing
    assert startup_failure_message(-1073741515) == missing  # same NTSTATUS, signed
    assert "0xC0000139" in startup_failure_message(0xC0000139)
    assert "0xC000007B" in startup_failure_message(0xC000007B)
    assert "0xC000012F" in startup_failure_message(0xC000012F)  # garbage DLL: not an MZ image
    for ordinary in (None, 0, 1, -11, "3221225781"):
        assert startup_failure_message(ordinary) == ""


def test_controller_start_passes_mpv_environment_and_reports_exit(tmp_path, monkeypatch):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"MZ")
    seen = {}

    class _Exited:
        def poll(self):
            return 3221225781

    def fake_popen(command, **kwargs):
        seen.update(kwargs)
        return _Exited()

    sentinel = {"PATH": "sentinel"}
    monkeypatch.setattr(studio_mpv, "popen_hidden_subprocess", fake_popen)
    monkeypatch.setattr(studio_mpv, "mpv_environment", lambda: sentinel)
    monkeypatch.setattr(studio_mpv, "_MpvCommandActor", lambda controller: SimpleNamespace())
    controller = MpvController(executable)
    assert controller.exit_code is None

    controller.start(12345)

    assert seen["env"] is sentinel
    assert controller.exit_code == 3221225781
    assert not controller.running


def test_mpv_starts_without_system_error_boxes_and_restores_the_mode(tmp_path, monkeypatch):
    """Started from Explorer, Studio has error boxes on; mpv would wait on one instead of exiting."""
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"MZ")

    class _Kernel32:
        mode = 0x8000  # SEM_NOOPENFILEERRORBOX only: boxes for load failures still on

        def GetErrorMode(self):
            return self.mode

        def SetErrorMode(self, mode):
            previous, self.mode = self.mode, mode
            return previous

    kernel32 = _Kernel32()
    seen = []

    def fake_popen(command, **kwargs):
        seen.append(kernel32.mode)
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(studio_mpv, "_kernel32", lambda: kernel32)
    monkeypatch.setattr(studio_mpv, "popen_hidden_subprocess", fake_popen)
    monkeypatch.setattr(studio_mpv, "_MpvCommandActor", lambda controller: SimpleNamespace())
    MpvController(executable).start(12345)

    assert seen == [0x8000 | 0x0001]          # SEM_FAILCRITICALERRORS while mpv is created
    assert kernel32.mode == 0x8000            # and the app's own mode afterwards

    def failing_popen(command, **kwargs):
        raise OSError("start failed")

    monkeypatch.setattr(studio_mpv, "popen_hidden_subprocess", failing_popen)
    try:
        MpvController(executable).start(12345)
    except OSError:
        pass
    assert kernel32.mode == 0x8000            # restored on failure too


def _app():
    return QApplication.instance() or QApplication([])


def test_unloadable_mpv_fails_the_player_stage_at_once(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.studio.studio_readiness import StudioReadiness
    monkeypatch.setattr(StudioReadiness, "_start_mpv_player", lambda self, epoch: None)
    page = SubtitleStudioPage()
    try:
        gate = StudioReadiness(page)
        gate.begin(str(tmp_path / "ghost.2byteproj"))
        failures = []
        monkeypatch.setattr(gate, "fail", lambda stage, error: failures.append((stage, str(error))))

        page.video.controller = SimpleNamespace(exit_code=None, running=True)
        gate._tick()
        assert failures == []                                   # still starting: keep waiting

        page.video.controller = SimpleNamespace(exit_code=1, running=False)
        gate._tick()
        assert failures == []                                   # ordinary exit: old recovery path

        page.video.controller = SimpleNamespace(exit_code=3221225781, running=False)
        gate._tick()
        assert len(failures) == 1
        stage, message = failures[0]
        assert stage == "准备播放器"
        assert "vulkan-1.dll" in message and "0xC0000135" in message
        page.video.controller = None
        monkeypatch.undo()                                      # the real fail(): which row gets the ✗
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        gate.fail("准备播放器", message)
        assert gate.steps_view.failed == "准备播放器"            # not 读取工程, still unfinished
        gate.cancel()
    finally:
        page.video.controller = None
        page.close_page()
        page.deleteLater()
        _app().processEvents()
