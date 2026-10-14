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


# Model sets the audit can prepare through the normal workshop dialog (2026-10-14):
# SenseVoice on the CPU, or MOSS + FireRed on the Apple GPU (MPS).
MODEL_SETS = {
    "sensevoice": dict(keys=["sensevoice"], name="SenseVoice CPU", verify=["sensevoice"], timeout=1200),
    "mac-gpu": dict(keys=["moss", "firered_aed"], name="MOSS + FireRed",
                    verify=["moss", "firered_vad", "speaker_embedding", "firered_aed"], timeout=2400),
}


def _verify_models(keys, model_root):
    from .model_integrity import locked_model, verify_model_files
    for key in keys:
        verify_model_files(key, model_root / Path(locked_model(key)["path"]).name)


def start(window, output):
    reuse = os.environ.get("TWOBYTEASR_MACOS_REUSE") == "1"
    model_set = MODEL_SETS[os.environ.get("TWOBYTEASR_MACOS_MODEL_SET") or "sensevoice"]
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
                _verify_models(model_set["verify"], roots.model_root)
                receipt.update(passed=True, gui_preparation=True, restart_reuse=True,
                    runtime=file_identity(selected), registration=load_registry().get("main"),
                    model_files_verified=True, preparation_repeated=False)
                save()
                from .home_release_flow_audit import start as start_home
                start_home(window, output)
                return
            dialog=window.workshop_page.download_combination(model_set["keys"],model_set["name"],auto_start=False)
            if dialog is None or not dialog.start_button.isEnabled():
                raise RuntimeError("The normal "+model_set["name"]+" preparation button is unavailable")
            receipt["model_set"]=model_set["keys"]
            # Select the project's real, fixed official repository source.
            combo=getattr(dialog,"source_combo",None)
            if combo is not None:
                index=combo.findData("HF_OFFICIAL")
                if index>=0: combo.setCurrentIndex(index)
            completed=[]
            dialog.completed.connect(lambda ok,message:completed.append((bool(ok),str(message))))
            # 2026-10-14: the dialog may still be appearing; a click before it is
            # shown never reaches the button (CI then waited 20 min at 0%).
            shown_by=time.monotonic()+10
            while not (dialog.isVisible() and dialog.start_button.isVisible()) and time.monotonic()<shown_by:
                QApplication.processEvents();time.sleep(.01)
            settle=time.monotonic()+1.5
            while time.monotonic()<settle:
                QApplication.processEvents();time.sleep(.01)
            dialog.grab().save(str(output/"01-workshop-before.png"))
            QTest.mouseClick(dialog.start_button,Qt.MouseButton.LeftButton)
            clicked_by=time.monotonic()+3
            while dialog.start_button.isEnabled() and time.monotonic()<clicked_by:
                QApplication.processEvents();time.sleep(.01)
            receipt["start_click_delivered"]=not dialog.start_button.isEnabled()
            if dialog.start_button.isEnabled():
                # Same handler as the user's click; recorded, never silent.
                dialog.start_button.click()
            receipt["start_button_disabled_after_start"]=not dialog.start_button.isEnabled()
            deadline=time.monotonic()+model_set["timeout"]
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
            _verify_models(model_set["verify"],roots.model_root)
            receipt["model_files_verified"]=True
            readiness={}
            from .runtime_paths import user_data_root
            for key in model_set["verify"]:
                path=user_data_root()/"model-readiness"/(key+".json")
                if path.is_file():
                    data=json.loads(path.read_text("utf8"))
                    readiness[key]={k:data.get(k) for k in ("status","device","inference_verified","elapsed_s")}
            receipt["readiness"]=readiness
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
