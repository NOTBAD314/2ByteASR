"""Real-window consistency failures and preserved manual text; synthetic data only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def run(output, *, window=None):
    from ..test_isolation import install, install_pytest_network_guard
    install(); install_pytest_network_guard()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from PySide6.QtTest import QTest
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from ..studio.studio_ui import SubtitleStudioPage
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity

    output = Path(output)
    app = QApplication.instance() or QApplication([])
    page = window.studio_page if window is not None else SubtitleStudioPage()
    surface = window if window is not None else page
    surface.resize(1440, 900); surface.show()
    project = SubtitleProject(media=StudioMedia(path="",duration_ms=5000),
        cues=[StudioCue("edited",1000,2000,"手動保留的新文字🙂",evidence_refs=["segment"])],
        asr_evidence={"segment":{"words":[dict(text="原始句子",start_ms=1000,end_ms=2000)]}},
        render_settings={"_cue_domain":"timeline"},
        studio_state={"caption_timeline":{"version":1,
            "source_archive":[dict(id="source",text="原始句子",start_ms=1000,end_ms=2000)],
            "instances":{"edited":dict(source_cue_id="source",text="原始句子",words=[
                dict(text="原始句子",char_start=0,char_end=4,start_ms=1000,end_ms=2000,evidence_ref="segment")],
                word_alignment="exact_token_text")}}})
    source = save_project(project,output/"manual.2byteproj")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    result = dict(passed=False, cases=[], identity=load_build_identity().to_dict(),
                  frozen=bool(getattr(sys,"frozen",False)), pid=os.getpid(),
                  entry="normal-window" if window else "standalone-page",
                  scope="synthetic projects, real Windows widgets, isolated data, no player or user files")

    def check(name, condition, detail=None):
        result["cases"].append(dict(name=name,passed=bool(condition),detail=detail))
        if not condition:
            raise AssertionError(name + ": " + str(detail))

    def wait(predicate, timeout=25):
        end=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>end:
                raise TimeoutError("consistency window did not reach expected state")
            QTest.qWait(20)

    timer=QTimer()
    handled=[]
    def handle_failure():
        box=next((w for w in QApplication.topLevelWidgets()
                  if isinstance(w,QMessageBox) and w.objectName()=="subtitleConsistencyFailure"
                  and w.isVisible()),None)
        if box is None or box.property("consistencyAuditHandled"):
            return
        box.setProperty("consistencyAuditHandled", True)
        handled.append(len(handled) + 1)
        QTest.qWait(150)  # Allow the native dialog first paint before PrintWindow.
        _capture(box,output/f"failure-{len(handled)}.png")
        result["cases"].append(dict(name=f"failure {len(handled)} explains retained text",
            passed="人工文字" in box.text(),detail=box.informativeText()))
        button=box.findChild(QPushButton,"subtitleConsistencyRescue")
        if button is not None:
            button.click()
        else:
            box.reject()
    timer.timeout.connect(handle_failure); timer.start(30)
    try:
        # Replay the actual provider entry with a contradictory response, then
        # pass its safe fallback through the actual runtime-cue project adapter.
        from .grouping_contract_audit import run_offline
        from ..projects.studio_project import project_from_runtime_cues
        from ..projects.subtitle_consistency import validate_project
        import subtitle_core as core
        replay = run_offline()
        result["cases"].extend(replay["checks"])
        fallback = project_from_runtime_cues(
            output/"missing-fixture.mp4", core.deserialize_cues(replay["runtime_cues"]),
            initialize_layout=False,
            media_identity={"duration_ms":2000,"width":640,"height":360,
                            "has_video":False,"has_audio":False})
        fallback.asr_evidence = {"segment:1":{
            "text":"先看左边，再看右边","speaker_id":"S01",
            "words":[dict(text=word["text"],start_ms=round(word["start"]*1000),
                          end_ms=round(word["end"]*1000))
                     for word in replay["source_segments"][0]["words"]]}}
        for cue in fallback.cues:
            cue.evidence_refs=["segment:1"]
        check("safe fallback satisfies editable-project contract",validate_project(fallback).ok)
        fallback_path=save_project(fallback,output/"safe-fallback.2byteproj")
        if window is not None:
            window.open_studio_project(str(fallback_path))
        else:
            page.open_project(fallback_path)
        wait(lambda:bool(getattr(page,"_readiness",None) and page._readiness.ready))
        check("safe fallback preserves original text",
              "".join(c.text for c in page.project.cues)=="先看左边，再看右边")
        check("safe fallback opens without source conflicts",page._subtitle_consistency_result.ok)
        check("safe fallback is distinct from a stale manual alignment",
              not any(issue.code=="stale_word_alignment" for issue in page._subtitle_consistency_result.warnings))
        _capture(surface,output/"fallback-open.png")
        if window is not None:
            window.open_studio_project(str(source))
        else:
            page.open_project(source)
        wait(lambda:bool(getattr(page,"_readiness",None) and page._readiness.ready))
        check("manual text survives load",page.project.cues[0].text=="手動保留的新文字🙂")
        check("stale word data does not block",page._subtitle_consistency_result.ok)
        check("word warning visible","字级" in page.save_state.text(),page.save_state.text())
        _capture(surface,output/"manual-open.png")
        previous=page.project
        for index,kind in enumerate(("source","time"),1):
            data=json.loads(source.read_text("utf8"))
            if kind=="source":
                data["cues"][0]["evidence_refs"]=["missing"]
            else:
                data["cues"][0]["end_ms"]=900
            path=output/f"invalid-{kind}.2byteproj"
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),"utf8")
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            page.open_project(path)
            wait(lambda:len(handled)>=index and getattr(page,"_subtitle_rescue_dialog",None) is not None)
            dialog=page._subtitle_rescue_dialog
            wait(dialog.isVisible)
            QTest.qWait(150)
            check(f"{kind} error preserves session",page.project is previous)
            check(f"{kind} rescue points to original",Path(dialog.source.text())==path)
            check(f"{kind} file remains byte-identical",hashlib.sha256(path.read_bytes()).hexdigest()==before)
            _capture(dialog,output/f"rescue-{kind}.png")
            dialog.close()
            page._subtitle_rescue_dialog=None
            page._readiness.cancel()
            QTest.qWait(100)
        check("manual saved file unchanged",hashlib.sha256(source.read_bytes()).hexdigest()==original_hash)
        result["passed"]=all(case["passed"] for case in result["cases"])
    except Exception:
        result["error"]=traceback.format_exc()
    finally:
        timer.stop()
        page.undo_stack.setClean()
        if window is None:
            page.close_page();page.close()
        QTest.qWait(200)
        result["shutdown"]=not bool(getattr(page,"_close_thread",None) and page._close_thread.is_alive())
        (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),"utf8")
    return 0 if result["passed"] and result["shutdown"] else 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    output=Path(output)
    def execute():
        window.result_exit_code=run(output,window=window)
        def stopped():
            path=output/"result.json"
            data=json.loads(path.read_text("utf8"))
            data["gui_shutdown"]=True
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),"utf8")
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100,execute)

