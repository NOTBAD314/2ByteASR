# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in native GUI model preparation followed by the real Home task path."""
from __future__ import annotations
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    reuse = os.environ.get("TWOBYTEASR_MACOS_REUSE") == "1"
    original_output = output
    if reuse:
        output = output / "restart"
        output.mkdir(exist_ok=True)
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    receipt={"platform":sys.platform,"architecture":platform.machine(),
             "packaged":bool(getattr(sys,"frozen",False)),"gui_preparation":False,
             "injected_transcript":False,"cloud_ai_calls":0,"passed":False}

    def save():
        (output/"workshop-result.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")

    def run():
        try:
            if sys.platform!="darwin" or platform.machine()!="arm64":
                raise RuntimeError("This desktop audit requires native Apple Silicon")
            if os.environ.get("QT_QPA_PLATFORM")=="offscreen":
                raise RuntimeError("Offscreen widgets cannot validate the native desktop")
            window.show(); window.raise_()
            if reuse:
                from .runtime_registry import resolve_runtime_python, load_registry
                from .python_runtime_identity import file_identity
                from .runtime_paths import bootstrap_runtime_paths
                from .model_integrity import verify_model_files
                previous = json.loads((original_output/"workshop-result.json").read_text("utf8"))
                if previous.get("passed") is not True:
                    raise RuntimeError("Restart requires a previously verified prepared runtime")
                selected = resolve_runtime_python("main")
                if not selected or not (Path(selected).parent.parent/"pyvenv.cfg").is_file():
                    raise RuntimeError("Restart did not recover the registered virtual environment")
                roots = bootstrap_runtime_paths(persist=False)
                verify_model_files("sensevoice", roots.model_root/"SenseVoiceSmall")
                receipt.update(passed=True, gui_preparation=True, restart_reuse=True,
                    runtime=file_identity(selected), registration=load_registry().get("main"),
                    model_files_verified=True, preparation_repeated=False)
                save()
                from .home_release_flow_audit import start as start_home
                start_home(window, output)
                return
            dialog=window.workshop_page.download_combination(["sensevoice"],"SenseVoice CPU",auto_start=False)
            if dialog is None or not dialog.start_button.isEnabled():
                raise RuntimeError("The normal SenseVoice preparation button is unavailable")
            # Select the project's real, fixed official repository source.
            combo=getattr(dialog,"source_combo",None)
            if combo is not None:
                index=combo.findData("HF_OFFICIAL")
                if index>=0: combo.setCurrentIndex(index)
            completed=[]
            dialog.completed.connect(lambda ok,message:completed.append((bool(ok),str(message))))
            dialog.grab().save(str(output/"01-workshop-before.png"))
            QTest.mouseClick(dialog.start_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+1200
            while not completed and time.monotonic()<deadline:
                QApplication.processEvents();time.sleep(.01)
            receipt["completed_signal"]=completed
            receipt["log"]=dialog.log.toPlainText()
            receipt["phase"]=getattr(dialog,"_phase","")
            receipt["gui_preparation"]=bool(completed and completed[-1][0] and getattr(dialog,"_finished_ok",False))
            dialog.grab().save(str(output/"02-workshop-after.png"))
            if not receipt["gui_preparation"]:
                raise RuntimeError("GUI preparation did not reach its verified ready state")
            from .runtime_paths import bootstrap_runtime_paths
            from .model_integrity import verify_model_files
            roots=bootstrap_runtime_paths(persist=False)
            verify_model_files("sensevoice",roots.model_root/"SenseVoiceSmall")
            receipt["model_files_verified"]=True
            receipt["passed"]=True;save()
            dialog.close()
            from .home_release_flow_audit import start as start_home
            # Recognition is created by the production Home Start button. The
            # fixture contains original spoken QA text, never a transcript.
            start_home(window,output)
        except Exception:
            receipt["error"]=traceback.format_exc();save()
            window.close()
    QTimer.singleShot(500,run)
