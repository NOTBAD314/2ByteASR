# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in native GUI model preparation followed by the real Home task path."""
from __future__ import annotations
import json
import os
import platform
import sys
import time
import traceback


def start(window, output):
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
