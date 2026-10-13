# SPDX-License-Identifier: GPL-3.0-only
"""Developer / source-mode 2ByteASR launcher.

This is not the official user-facing desktop entry. The release process is
``dist\\2ByteASR\\2ByteASR.exe`` (or the tiny ``2ByteASR.exe`` bootstrapper that
hands off to that packaged build). Keep this file for source hot-reload and
headed automation.

Never bypass the real GUI via direct MainWindow construction in acceptance.
"""

from __future__ import annotations

import os
import ctypes
import hashlib
import importlib.util
import json
import sys
import traceback

if len(sys.argv) >= 2 and sys.argv[1] == '--mcp-stdio':
    # The MCP stdio server starts once per client session: no startup trace
    # line (importing startup_trace appends one) and no other log writes.
    def _startup_mark(*_args, **_details):
        return None
else:
    from twobyteasr.startup_trace import mark as _startup_mark




PIPELINE_BUILD_ID = "2026.08.10-v7.18-asr-result-schema-v2"


def application_root() -> str:
    """Return the deployed app root in both source and frozen launches."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _startup_runtime_snapshot() -> dict[str, object]:
    """Capture import-resolution state before application dependencies load."""
    path_entries = [str(item) for item in sys.path]
    encoded_path = json.dumps(path_entries, ensure_ascii=False, separators=(",", ":"))
    try:
        numpy_spec = importlib.util.find_spec("numpy")
        numpy_origin = str(getattr(numpy_spec, "origin", "") or "")
        numpy_locations = [str(item) for item in (getattr(numpy_spec, "submodule_search_locations", None) or ())]
    except Exception as exc:
        numpy_origin = ""
        numpy_locations = []
        numpy_error = f"{type(exc).__name__}: {exc}"
    else:
        numpy_error = ""
    return {
        "PROCESS_EXE": str(sys.executable),
        "SYS_PREFIX": str(sys.prefix),
        "SYS_BASE_PREFIX": str(sys.base_prefix),
        "SYS_PATH": path_entries,
        "SYS_PATH_HASH": hashlib.sha256(encoded_path.encode("utf-8")).hexdigest(),
        "CWD": os.getcwd(),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "PYTHONHOME": os.environ.get("PYTHONHOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "FROZEN": bool(getattr(sys, "frozen", False)),
        "MEIPASS": str(getattr(sys, "_MEIPASS", "") or ""),
        "NUMPY_SPEC_ORIGIN": numpy_origin,
        "NUMPY_SPEC_LOCATIONS": numpy_locations,
        "NUMPY_SPEC_ERROR": numpy_error,
        "MAIN_RUNTIME_OVERRIDE": os.environ.get("TWOBYTEASR_MAIN_PYTHON", ""),
    }


def _log_path():
    if getattr(sys, "frozen", False):
        from twobyteasr.runtime_paths import user_data_root
        directory = user_data_root() / "logs"
        return str(directory / "2byteasr-startup.log")
    try:
        root = application_root()
        return os.path.join(root, "2byteasr-startup.log")
    except Exception:
        return os.path.join(os.getcwd(), "2byteasr-startup.log")


def _append_startup_log(message: str) -> None:
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(message.rstrip() + "\n")
    except Exception:
        pass


def _show_error(title: str, message: str) -> None:
    """Show a native message box; never fail silently (pythonw has no console).

    Writes a startup log entry first so even if the dialog is missed or the
    process exits abruptly there is a persistent record.
    """
    _append_startup_log(f"[ERROR DIALOG] {title}\n{message}")
    # Try native Win32 first (works even without a QApplication and under pythonw)
    try:
        import ctypes  # type: ignore
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
        return
    except Exception:
        pass
    # Fallbacks (may be suppressed under pythonw but still attempt)
    try:
        print(f"[{title}] {message}", file=sys.stderr)
    except Exception:
        pass
    try:
        import tkinter as tk  # type: ignore
        from tkinter import messagebox  # type: ignore
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def _write_full_traceback(exc: BaseException) -> None:
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _append_startup_log("=== STARTUP CRASH ===\n" + tb + "=== END CRASH ===")
    except Exception:
        pass


def _write_setup_marker() -> None:
    """Self-heal: once the app starts, record that configuration finished.

    Legacy installs configured before the marker feature existed would
    otherwise keep showing the first-run dialog. The marker is written next
    to this script; the path is normalized and confined to the script dir.
    """
    if os.environ.get('TWOBYTEASR_TEST_ROOT'):
        # A source acceptance run owns its profile, not the operator's install.
        return
    try:
        import datetime
        import pathlib
        root = os.path.normpath(application_root())
        required = (".venv-main/Scripts/python.exe",)
        if not all(os.path.isfile(os.path.join(root, *item.split("/"))) for item in required):
            return
        marker = os.path.join(root, "2byteasr.setup-complete")
        if not os.path.abspath(marker).startswith(os.path.abspath(root) + os.sep):
            return
        pathlib.Path(marker).write_text(
            datetime.datetime.now().isoformat(), encoding="ascii")
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == '--mcp-stdio':
        # Local MCP server for desktop AI clients: protocol on stdout only, no
        # GUI, no logs or data writes; it forwards to the running window.
        from twobyteasr.mcp_stdio import main as mcp_stdio_main
        return mcp_stdio_main(sys.argv[2:])
    if len(sys.argv) == 3 and sys.argv[1] == '--data-roots-inspect':
        from twobyteasr.data_roots_inspect import main as inspect_data_roots
        return inspect_data_roots(sys.argv[2])
    from twobyteasr.offline_audit_io import install as install_offline_audit_io
    install_offline_audit_io()
    if len(sys.argv) == 3 and sys.argv[1] == '--cover-font-self-test':
        from twobyteasr.cover_font_selftest import main as cover_font_self_test
        return cover_font_self_test(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == '--caption-cli-audit':
        from twobyteasr.caption_cli_audit import main as caption_cli_audit
        return caption_cli_audit(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == '--caption-provider-self-test':
        from twobyteasr.caption_provider_selftest import main as caption_self_test
        return caption_self_test(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == '--asr-provider-self-test':
        from twobyteasr.stage9_acceptance_audit import main as asr_self_test_main
        return asr_self_test_main(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == '--moss-full-context-audit':
        from twobyteasr.moss_full_context_audit import main as moss_audit
        return moss_audit(sys.argv[2])
    if len(sys.argv) > 2 and sys.argv[1] == '--glossary-update-self-test':
        # 真实联网词库更新自检（源码与冻结 EXE 同入口；不写词库，只落结果 JSON）
        from twobyteasr.glossary_update_selftest import main as glossary_self_test
        return glossary_self_test(sys.argv[2:])
    if len(sys.argv) > 2 and sys.argv[1] == '--glossary-update-ui-loop':
        # 有界面的真实联网闭环（真实 UI+真实引擎；默认不写词库，截图+结果 JSON 留证）
        from twobyteasr.glossary_ui_loop import main as glossary_ui_loop
        return glossary_ui_loop(sys.argv[2:])
    if len(sys.argv) > 2 and sys.argv[1] == '--playback-audit':
        # 真实工程播放验收自检（源码与冻结 EXE 同链路；不写用户工程/素材）
        from twobyteasr.playback_audit_selftest import main as playback_audit
        return playback_audit(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == '--runtime-fixes-audit':
        # 2026-09-20 三修自检（日志横滚/子进程UTF-8/失效模型；不写用户数据）
        from twobyteasr.runtime_fixes_audit import main as runtime_fixes_audit
        return runtime_fixes_audit(sys.argv[2:])
    if len(sys.argv) > 2 and sys.argv[1] == '--studio-screen-probe':
        from twobyteasr.visible_pixel_probe import main as screen_probe_main
        screen_probe_main(sys.argv[2])
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == '--studio-video-worker':
        from twobyteasr.video_decode_worker import main as video_worker_main
        return video_worker_main()
    if len(sys.argv) > 1 and sys.argv[1] == '--studio-audio-worker':
        from twobyteasr.audio_process import main as audio_main
        return audio_main(sys.argv[2:])
    if len(sys.argv) == 2 and sys.argv[1] == '--asr-api-worker':
        # Cloud recognition request process (2026-10-13): runs with the app's
        # own executable so cloud-only users need no local model runtime.
        from twobyteasr.cloud_api_worker import main as cloud_api_worker_main
        return cloud_api_worker_main()
    import multiprocessing

    multiprocessing.freeze_support()
    os.environ["TWOBYTEASR_PROCESS_ROLE"] = "main-gui"
    from twobyteasr.media_intake import parse_media_arguments
    media_arguments = parse_media_arguments(sys.argv[1:])
    _startup_mark("PYTHON_ENTRY")
    from PySide6.QtWidgets import QApplication
    from twobyteasr.single_instance import SingleInstanceGuard
    app = QApplication.instance() or QApplication([sys.argv[0]])
    _startup_mark("EARLY_QT_READY")
    instance_guard = SingleInstanceGuard(SingleInstanceGuard.application_name(application_root()))
    _startup_mark("EARLY_INSTANCE_GUARD_CREATED")
    if not instance_guard.acquire():
        if instance_guard.forward(media_arguments, timeout_ms=30000):
            return 0
        # A crashed owner releases the OS mutex. A hung live owner is not safe to steal.
        if not instance_guard.acquire():
            _show_error("2ByteASR 暂时无法接收文件",
                        "现有实例未确认接收。请稍后重试；如窗口无响应，请关闭该实例后重开。文件没有被修改。")
            return 2
    _startup_mark("EARLY_INSTANCE_OWNER")
    app._instance_guard = instance_guard
    app.aboutToQuit.connect(instance_guard.release)
    # Ensure we have a record even for very early interpreter crashes.
    packaged = bool(getattr(sys, "frozen", False))
    if packaged:
        os.environ.setdefault("TWOBYTEASR_LAUNCH_MODE", "packaged")
    else:
        os.environ.setdefault("TWOBYTEASR_LAUNCH_MODE", "source-dev")
    _append_startup_log(
        f"=== 2ByteASR {'packaged' if packaged else 'developer/source-mode'} cold start "
        f"pid={os.getpid()} argv={sys.argv} ==="
    )
    try:
        _append_startup_log(
            "STARTUP_RUNTIME_CONTEXT="
            + json.dumps(_startup_runtime_snapshot(), ensure_ascii=False, separators=(",", ":"))
        )
    except Exception as exc:
        _append_startup_log(f"STARTUP_RUNTIME_CONTEXT_ERROR={type(exc).__name__}: {exc}")
    try:
        # IMPORTANT: These imports can fail if a role environment is broken.
        # We intentionally keep them here so the real launch path exercises the
        # same contract/repair surface as a packaged user run.  Failures are
        # logged + shown and do not mutate live environments.
        from twobyteasr.build_identity import (
            load_build_identity,
            runtime_fingerprint_lines,
            startup_identity_lines,
            write_launch_identity,
        )
        from twobyteasr.runtime_paths import bootstrap_runtime_paths

        if os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR'):
            from twobyteasr.studio_acceptance_audit import isolate_acceptance_settings
            isolate_acceptance_settings()

        runtime_paths = bootstrap_runtime_paths(install_root=application_root(), persist=True)
        build_identity = load_build_identity()
        identity_path = write_launch_identity(build_identity)
        _append_startup_log(f"BUILD_IDENTITY_PATH={identity_path}")
        for line in startup_identity_lines(
            build_identity,
            model_root=runtime_paths.model_root,
            project_root=runtime_paths.project_root,
        ):
            _append_startup_log(line)
        import moss_firered_pipeline  # type: ignore
        import subtitle_core  # type: ignore
        subtitle_core.FIRERED_MODEL_DIR = subtitle_core._resolve_firered_model_dir()
        from twobyteasr.ui import after_startup_idle, run_desktop_app  # type: ignore

        def write_runtime_fingerprint():
            for line in runtime_fingerprint_lines(build_identity):
                _append_startup_log(line)

        # The fingerprint imports the Studio module tree to read its feature
        # symbols (~0.4 s); it is written once the window is interactive.
        after_startup_idle(write_runtime_fingerprint)

        _startup_mark("IMPORTS_DONE")

        moss_firered_pipeline.verify_pipeline_contract(
            subtitle_core,
            os.path.realpath(sys.executable if getattr(sys, "frozen", False) else __file__),
            PIPELINE_BUILD_ID,
        )
        _startup_mark("BOOTLOADER_DONE")
        _write_setup_marker()
        _append_startup_log("imports ok; calling run_desktop_app (real cold-start path)")
        rc = run_desktop_app(
            subtitle_core,
            moss_firered_pipeline,
            None,
            select_media=False,
            initial_paths=media_arguments,
            instance_guard=instance_guard,
        )
        _append_startup_log(f"run_desktop_app returned {rc}")
    except SystemExit as exit_request:
        # Allow intentional exits from inside the app, but still hard-terminate:
        # 2026-09-07（打包关停滞留）——run_desktop_app 以 SystemExit 结束时若直接
        # 放行，Py_Finalize→PySide 清理会楔在 ~QMediaPlayer/驱动线程上。
        rc = exit_request.code if isinstance(exit_request.code, int) else 0
        _append_startup_log(f"run_desktop_app raised SystemExit({rc})")
    except Exception as exc:
        _write_full_traceback(exc)
        recovery = (
            "请重新运行本版本安装包修复程序文件；模型环境可在模型工坊中重试。\n"
            if getattr(sys, "frozen", False) else
            "请双击 setup_2byteasr.bat 重新完成配置，或在配置器中点击“重新检查”。\n"
        )
        _show_error(
            "2ByteASR 启动失败",
            "运行环境不完整（可能上次配置中断或修复失败），无法启动工作台。\n\n"
            f"{recovery}"
            "已下载的内容会自动续传、不会重复下载。\n\n"
            f"详细错误日志：{_log_path()}。\n\n"
            f"详细信息：\n{exc}",
        )
        rc = 1
    finally:
        try:
            _append_startup_log("=== 2ByteASR cold start exit ===")
        except Exception:
            pass
        # 2026-09-07（打包关停滞留）：主窗口完整关闭后，解释器/CRT/DLL 拆卸链
        # （Py_Finalize→~QGuiApplication→QThreadPool 等待；ExitProcess 的 DLL
        # detach 与媒体后端/显卡驱动工作线程在堆锁上互等）在 frozen 上必楔。
        # 应用层关闭链（含 autosave/actor 关停）此时已 100% 完成——硬终止进程。
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        # 2026-10-10: the untyped call truncated the pseudo handle of
        # GetCurrentProcess() to 32 bits, so TerminateProcess failed with
        # ERROR_INVALID_HANDLE and every exit fell through to the full
        # interpreter/Qt teardown — after long sessions that teardown aborted
        # and the process ended 0xC0000409 instead of rc. Typed, on a private
        # WinDLL so no other caller's ctypes declarations change.
        try:
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateProcess.restype = wintypes.BOOL
            _append_startup_log(f"terminate issued rc={rc}")
            kernel32.TerminateProcess(kernel32.GetCurrentProcess(), int(rc) & 0xFFFFFFFF)
            # Only reached when the call failed.
            _append_startup_log(f"terminate failed: error {ctypes.get_last_error()}; os._exit")
        except Exception as exc:
            _append_startup_log(f"terminate failed: {exc}; os._exit")
        os._exit(int(rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
