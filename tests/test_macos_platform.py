# SPDX-License-Identifier: GPL-3.0-only
import os
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest

from twobyteasr.platform_browser import bundled_browser
from twobyteasr.platform_macos import configure_macos_paths, cpu_factory_settings, device_capabilities
from twobyteasr.platform_media import executable_name
from twobyteasr.platform_mpv import native_video_arguments, preview_surface, UnixIPCStream, cleanup_unix_ipc, unix_ipc_path
from twobyteasr.platform_audio import audio_endpoint, valid_audio_endpoint, audio_backend


def test_windows_player_arguments_preserve_hwnd_and_d3d11():
    assert native_video_arguments(145,platform="win32")==["--gpu-api=d3d11","--wid=145"]
    assert preview_surface("win32")=="embedded-hwnd"
    with pytest.raises(ValueError,match="positive native HWND"):native_video_arguments(0,platform="win32")


def test_cocoa_qt_id_is_not_misrepresented_as_embeddable_hwnd():
    args=native_video_arguments(145,platform="darwin")
    assert not any(arg.startswith("--wid=") for arg in args)
    assert "--gpu-api=d3d11" not in args
    assert preview_surface("darwin")=="embedded-qt-video-sink"


@pytest.mark.parametrize("system,machine,tag,binary",[
    ("win32","AMD64","win64","chrome-headless-shell.exe"),
    ("darwin","arm64","mac-arm64","chrome-headless-shell"),
    ("darwin","x86_64","mac-x64","chrome-headless-shell"),
    ("linux","aarch64","linux-arm64","headless_shell"),
    ("linux","x86_64","linux64","chrome-headless-shell")])
def test_browser_matches_locked_remotion_platform_layout(system,machine,tag,binary):
    root=Path("renderer")
    assert bundled_browser(root,platform=system,machine=machine)==root/"node_modules/.remotion/chrome-headless-shell"/tag/("chrome-headless-shell-"+tag)/binary


def test_media_tool_suffix_preserves_windows_and_selects_native_posix():
    assert executable_name("ffmpeg",windows=True)=="ffmpeg.exe"
    assert executable_name("ffmpeg",windows=False)=="ffmpeg"


def test_macos_resource_and_user_paths_keep_explicit_isolation(tmp_path):
    env={"2BYTEASR_USER_DATA_ROOT":str(tmp_path/"isolated"),"TWOBYTEASR_MAIN_PYTHON":"existing-owned-runtime"}
    resource=tmp_path/"2ByteASR.app/Contents/Frameworks"
    data=configure_macos_paths(resource,home=tmp_path/"home",environ=env)
    assert data==tmp_path/"isolated/2ByteASR"
    assert env["2BYTEASR_INSTALL_ROOT"]==str(resource)
    assert env["TWOBYTEASR_MAIN_PYTHON"]=="existing-owned-runtime"
    assert "AppData" not in data.relative_to(tmp_path).parts
    assert not data.exists()


def test_macos_factory_does_not_modify_windows_defaults():
    defaults={"models":{"primary_asr_backend":"moss"},"switches":{"use_ai_grouping":True,"enable_ai_polish":True}}
    result=cpu_factory_settings(defaults)
    assert defaults["models"]["primary_asr_backend"]=="moss"
    assert defaults["switches"]["use_ai_grouping"] is True
    assert result["models"]["primary_asr_backend"]=="sensevoice"
    assert all(value is False for value in result["switches"].values())


def test_mps_availability_does_not_select_an_unverified_model_device():
    torch=SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda:True,is_available=lambda:False)))
    actual=device_capabilities(torch)
    assert actual["mps_built"] is True
    assert actual["mps_available"] is False
    assert actual["selected_asr_device"]=="cpu"
    assert actual["mps_model_verified"] is False


def test_windows_audio_endpoint_keeps_authenticated_pipe_namespace():
    if os.name != "nt": pytest.skip("Windows namespace regression")
    address,family=audio_endpoint()
    assert family=="AF_PIPE"
    assert address.startswith(r'\\.\pipe\2byte-audio-')
    assert valid_audio_endpoint(address)
    assert not valid_audio_endpoint("/tmp/untrusted.sock")
    assert audio_backend()=="isolated-wasapi"


def test_cleanup_never_recursively_removes_unknown_files(tmp_path):
    owned=tmp_path/"2basr-mpv-fixture"
    owned.mkdir()
    (owned/"ipc.sock").write_bytes(b"")
    other=owned/"unexpected"
    other.write_text("preserve")
    cleanup_unix_ipc(str(owned/"ipc.sock"))
    assert other.read_text()=="preserve"
    assert owned.exists()
    unowned=tmp_path/"unowned"
    unowned.mkdir()
    socket_path=unowned/"ipc.sock"
    socket_path.write_bytes(b"")
    cleanup_unix_ipc(str(socket_path))
    assert socket_path.exists()


@pytest.mark.skipif(os.name=="nt",reason="Real POSIX AF_UNIX transport is exercised on Linux/macOS")
def test_posix_socket_duplex_stream_is_not_opening_socket_as_regular_file(tmp_path):
    path=Path(unix_ipc_path())
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    server.bind(str(path));server.listen(1)
    received=[]
    def respond():
        client,_=server.accept()
        with client:
            received.append(client.recv(2048))
            client.sendall(b'{"request_id":1,"error":"success"}\n')
    thread=threading.Thread(target=respond);thread.start()
    stream=UnixIPCStream(str(path))
    try:
        command=b'{"command":["get_property","time-pos"],"request_id":1}\n'
        assert stream.write(command)==len(command)
        assert os.read(stream.fileno(),2048)==b'{"request_id":1,"error":"success"}\n'
    finally:
        stream.close();server.close();thread.join(timeout=2);cleanup_unix_ipc(str(path))
    assert received==[command]

@pytest.mark.parametrize("system,frozen,expected", [
    ("darwin", True, "resources"), ("win32", True, "executable"), ("darwin", False, "source")])
def test_pipeline_worker_root_obeys_real_bundle_layout(tmp_path, monkeypatch, system, frozen, expected):
    import subprocess, sys
    from types import SimpleNamespace
    from twobyteasr import runtime_paths
    contents = tmp_path / "兔白 移動.app/Contents"
    source = tmp_path / "source/subtitle_core.py"
    executable = contents / "MacOS/2ByteASR"
    resources = contents / "Frameworks"
    for folder in (source.parent, executable.parent, resources): folder.mkdir(parents=True)
    roots = dict(resources=resources, executable=executable.parent, source=source.parent)
    for kind, folder in roots.items():
        (folder / "sensevoice_worker.py").write_text("print(" + repr(kind) + ")", encoding="utf8")
    monkeypatch.setenv(runtime_paths.INSTALL_ROOT_ENV, str(resources))
    monkeypatch.setattr(runtime_paths, "sys", SimpleNamespace(platform=system, frozen=frozen, executable=str(executable)))
    selected = runtime_paths.pipeline_script_root(source)
    assert selected == roots[expected].resolve()
    # Execute the selected real script; finding the basename alone cannot pass.
    probe = subprocess.run([sys.executable, "-I", "-X", "utf8", str(selected / "sensevoice_worker.py")],
                           capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == expected
