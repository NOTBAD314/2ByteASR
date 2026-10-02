# SPDX-License-Identifier: GPL-3.0-only
"""Native .app entry, adapting resource roots before normal desktop launch."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def startup_smoke_argument(argv: list[str]) -> Path | None:
    """Allow LaunchServices' process serial argument without losing our audit."""
    args=[value for value in argv[1:] if not value.startswith('-psn_')]
    if not args or args[0] != '--macos-startup-smoke':
        return None
    if len(args) != 2:
        raise ValueError('Startup smoke requires exactly one output directory')
    return Path(args[1]).resolve()


def finish_startup_event_loops(app, windows, exit_code: int) -> None:
    """Cancel the fresh wizard before quitting the outer application loop."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    # A first-run QDialog.exec() precedes QApplication.exec(). Calling exit
    # inside the first loop alone lets the later application loop start anew.
    pending={window for window in windows if isinstance(window,QDialog)}
    def completed(window):
        pending.discard(window)
        if not pending:
            QTimer.singleShot(0,lambda:app.exit(exit_code))
    if not pending:
        QTimer.singleShot(0,lambda:app.exit(exit_code))
    for window in list(pending):
        # SpringDialog.done() animates before emitting finished. Queue the
        # outer-loop exit only after that actual completion, not after reject.
        window.finished.connect(lambda _result,window=window:completed(window))
        window.reject()


def dismiss_first_wizard_for_desktop_audit(app, output: Path) -> None:
    """Use the real Escape action so the normal workshop audit can start."""
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    timer=QTimer(app)
    def inspect():
        for window in app.topLevelWidgets():
            if type(window).__name__=='GuidedSetupDialog' and window.isVisible():
                window.grab().save(str(output/'00-first-run-wizard.png'))
                receipt={
                    'shown':True,'action':'Escape / cancel without download',
                    'dismissed':False,'injected_model_or_transcript':False,
                }
                def completed(result):
                    receipt.update(dismissed=not window.isVisible(),dialog_result=int(result))
                    (output/'first-run-wizard.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
                window.finished.connect(completed)
                timer.stop()
                QTest.keyClick(window, Qt.Key.Key_Escape)
                return
    timer.timeout.connect(inspect)
    timer.start(250)
    app._macos_wizard_audit_timer=timer


def main() -> int:
    # PyInstaller's hook diverts spawn/resource-tracker children before any
    # QApplication, single-instance guard, defaults or normal GUI is created.
    import multiprocessing
    multiprocessing.freeze_support()
    if sys.platform != "darwin":
        raise SystemExit("The macOS launcher must run on a native macOS host.")
    smoke_output = None
    requested_output = startup_smoke_argument(sys.argv)
    if requested_output is not None:
        output = requested_output
        if output.exists():
            raise SystemExit("Smoke output must be a new directory.")
        output.mkdir(parents=True)
        os.environ.setdefault("TWOBYTEASR_TEST_ROOT", str(output))
        boundary = Path(os.environ["TWOBYTEASR_TEST_ROOT"]).resolve()
        if "tmp" not in {part.casefold() for part in boundary.parts} or not output.is_relative_to(boundary):
            raise SystemExit("Startup smoke requires an owned absolute tmp boundary containing its output.")
        smoke_output = output
        (output/'entry.json').write_text(json.dumps({'argv':sys.argv,'platform':sys.platform,
            'packaged':bool(getattr(sys,'frozen',False)),'resource_root':str(ROOT),
            'cwd_at_entry':os.getcwd()},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        # Windowed bootloaders have no streams. Keep failures from the real
        # entry visible in this isolated audit; model child pipes stay intact.
        for name in ('stdout','stderr'):
            if getattr(sys,name) is None:
                setattr(sys,name,(output/(name+'.log')).open('a',encoding='utf8',buffering=1))
        # The caller supplies an isolated native runtime for this profile.
        sys.argv = [sys.argv[0]]
    from twobyteasr.platform_macos import configure_macos_paths, cpu_factory_settings
    configure_macos_paths(ROOT)
    # Finder supplies neither a terminal cwd nor the developer's shell PATH.
    # Use the stable writable application root; resources remain at ROOT.
    from twobyteasr.runtime_paths import user_data_root
    data_root = user_data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    os.chdir(data_root)
    # Frozen media children inherit the parent's guarded audit environment.
    # Dispatch them before creating QApplication, first-run dialogs or settings;
    # they own their native decoder/audio event loop and never enter GUI audit.
    if len(sys.argv) > 1 and sys.argv[1] == '--studio-audio-worker':
        from twobyteasr.audio_process import main as audio_main
        return audio_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == '--studio-video-worker':
        from twobyteasr.video_decode_worker import main as video_main
        return video_main()
    if len(sys.argv) > 1 and sys.argv[1] == '--macos-prepare-cpu':
        # A windowed .app may replace Python streams with None even though
        # the workshop owns real pipes. This child never opens a GUI.
        if sys.stdout is None:
            sys.stdout = os.fdopen(os.dup(1), 'w', encoding='utf8', buffering=1)
        if sys.stderr is None:
            sys.stderr = os.fdopen(os.dup(2), 'w', encoding='utf8', buffering=1)
        from twobyteasr.macos_model_prepare import main as prepare_cpu
        return prepare_cpu(sys.argv[2:])
    if len(sys.argv) == 3 and sys.argv[1] == "--macos-media-smoke":
        from twobyteasr.macos_media_smoke import main as media_smoke
        return media_smoke(sys.argv[2])
    if smoke_output is not None:
        output = smoke_output
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from twobyteasr.build_identity import load_build_identity
        app = QApplication(sys.argv)
        def finish():
            windows = [w for w in app.topLevelWidgets() if w.isVisible()]
            main_windows = [w for w in windows if type(w).__name__ == "MainWindow"]
            required = ["2byteasr_version.json", "LICENSE", "assets/fonts/SourceHanSansSC-Heavy.otf"]
            receipt = {"native_host": sys.platform, "packaged": bool(getattr(sys,"frozen",False)),
                       "identity": load_build_identity().to_dict(),
                       "visible_window_types": [type(w).__name__ for w in windows],
                       "normal_entry_main_window_visible": bool(main_windows),
                       "resources": {p: (ROOT/p).is_file() for p in required},
                       "playback_recognition_export_verified": False}
            receipt["passed"] = bool(main_windows) and all(receipt["resources"].values())
            (output/"result.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
            for index,window in enumerate(windows):
                window.grab().save(str(output/f"window-{index}.png"))
            finish_startup_event_loops(app, windows, 0 if receipt["passed"] else 1)
        QTimer.singleShot(10000, finish)
    elif os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='macos-desktop':
        from twobyteasr.studio_acceptance_audit import audit_directory
        # Validate the existing owned tmp/profile/project guard before any
        # opt-in UI action. Ordinary user launches never enter this route.
        audit_output=audit_directory()
        if audit_output is None:
            raise RuntimeError('Desktop audit requires its isolated output')
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication(sys.argv)
        dismiss_first_wizard_for_desktop_audit(app,audit_output)
    # Install only fresh defaults; existing projects/configuration are never
    # rewritten or copied from a Windows user's AppData.
    from twobyteasr.settings import DEFAULT_SETTINGS, project_settings_path
    settings = project_settings_path()
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(cpu_factory_settings(DEFAULT_SETTINGS),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    import quick_start
    # PyInstaller 6 .app resources live at _MEIPASS, not Contents/MacOS.
    # This adapter binds the existing explicit application-root function;
    # the Windows entry and its process/renderer ownership are unchanged.
    quick_start.application_root = lambda: str(ROOT)
    return quick_start.main()


if __name__ == "__main__":
    raise SystemExit(main())
