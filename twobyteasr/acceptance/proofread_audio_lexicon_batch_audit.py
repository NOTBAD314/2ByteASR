"""Opt-in real-window verification with disposable project/library data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QTimer, Qt, QPoint
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    restart = os.environ.get("TWOBYTEASR_PROOFREAD_AUDIT_RESTART") == "1"
    result = {"passed": False, "checks": [], "timings_ms": {}, "synthetic_project": True,
              "cues": 744, "input": "SAPI adjacent Chinese speech + persisted temporary selected libraries"}
    source_root = Path(__file__).resolve().parents[2]
    source_files = ["glossary/glossary_proofread.py", "glossary/proofread_policy.py", "glossary/proofread_rules.py", "glossary/proofread_decisions.py",
        "glossary/proposal_safety.py", "glossary/proofread_batch.py", "glossary/terminology.py", "glossary/term_editing.py",
        "glossary/term_editor.py", "glossary/studio_glossary_service.py", "playback/cue_audio_preview.py", "playback/cue_player.py",
        "subtitle_rules/stutter_cleanup.py", "acceptance/proofread_audio_lexicon_batch_audit.py"]
    def hashes():
        return {name:hashlib.sha256((source_root/"twobyteasr"/name).read_bytes()).hexdigest() for name in source_files}
    result["source_sha256"] = hashes()
    result_path = out/("result-restart.json" if restart else "result.json")
    result["runtime"] = {"frozen":bool(getattr(sys,"frozen",False)),"pid":os.getpid(),"executable":sys.executable,
                         "exe_sha256":hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}
    metadata=Path(sys.executable).parent/"2byteasr_build.json"
    if metadata.is_file():result["runtime"]["build"]=json.loads(metadata.read_text("utf-8"))
    from ..test_isolation import require_isolated_paths
    result["isolated_paths"]={k:str(v) for k,v in require_isolated_paths("frozen-proofread",emit=lambda _s:None).items()}


    def save():
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def shutdown():
        result["gui_shutdown"]=True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)

    def check(name, value):
        result["checks"].append({"name":name,"passed":bool(value)}); save()
        if not value:
            raise AssertionError(name)

    def pump(seconds=.03):
        end = time.perf_counter()+seconds
        while time.perf_counter()<end:
            QApplication.processEvents(); time.sleep(.002)

    def wait(predicate, seconds=90):
        end = time.perf_counter()+seconds
        while not predicate() and time.perf_counter()<end:
            pump()
        return predicate()

    def run():
        review = None
        try:
            import subtitle_core as legacy
            from ..projects.studio_project import load_project
            from ..glossary.term_editing import library_terms
            from ..glossary.terminology import TermResolver, snapshot_glossaries
            fixture = json.loads((out/"fixture.json").read_text("utf-8"))
            project = load_project(out/"work.2byteproj")
            window._show_glossary_proofread(str(out/"work.2byteproj"), project)
            review = window.glossary_proofread_page
            def settled():
                receipt=review._receipt or {}
                return (not review.checks_running() and review._worker is None and not getattr(review,"_stutter_threads",())
                        and receipt.get("checked_cues",0)>0 and review._snapshot is not None
                        and (receipt.get("snapshot_summary") or {}).get("snapshot_digest")==review._snapshot.digest)
            def settle_checks():
                pump(.2)
                return wait(settled,120)
            check("normal application displays all 744 captions",review.isVisible() and len(review._rows)==744)
            check("real local matching completes",settle_checks())
            if restart:
                check('disabled cleanup preference survives restart',not review.stutter_toggle.isChecked())
                check('restart cannot regenerate disabled cleanup proposals',not any(i['kind'] in {'stutter','merge'}
                    and not i['checked'] for row in review._rows for i in row['issues']))
                record = next(r for r in library_terms(review._snapshot) if r.library_id==fixture["library"] and r.canonical=="骨龙")
                check("removed alias remains absent after process restart","术语甲" not in record.aliases)
                check("disk mapping affects actual resolver after restart",TermResolver(review._snapshot).resolve("术语甲来了").text=="术语甲来了")
                if fixture.get("case_term"):
                    check("canonical edit persists after process restart",TermResolver(review._snapshot).resolve("nameid").text=="NAMEid")
                check("batch ignore persists after process restart",review.proposal_counts()["ignored"]>0)
                _capture(window,out/"08-restart.png")
            else:
                check("three reported false corrections absent from real local results",all(not any(
                    i["replacement"] and not i["reviewed"] for i in review._by_id[c]["issues"] if i["kind"] in {"term","near","association","consistency","ai","ai_review"})
                    for c in ("stable-0","stable-2","stable-3")))
                records=library_terms(review._snapshot)
                check("same name retains both real library sources",len([r for r in records if r.canonical=="降灵"])==2)
                check("term count equals actual data",review.term_list.count()==len(records))
                from PySide6.QtWidgets import QPushButton
                check('batch selection is available immediately without a mode button',
                    not hasattr(review,'batch_toggle') and not review._batch_selected
                    and not any(b.text()=="批量选择" for b in review.findChildren(QPushButton)))
                check('canonical rows contain only the word',all(review.term_list.item(i).text()==
                    review.term_list.item(i).data(Qt.UserRole+1).canonical for i in range(review.term_list.count())))
                check('row checkboxes are painted before any selection',any(a=='rowcheck' for _,a,_,_ in review.list._hit_boxes))
                # Actual local repeat analysis, followed by an in-flight offline
                # model result delivered by the production QThread callback.
                from ..studio.studio_text_tools import TextOccurrence
                import threading
                repeats={'stable-15','stable-16','stable-17'}
                review.stutter_toggle.setChecked(True)
                review._start_stutter(project)
                check('reported repeated phrases produce local cleanup proposals',wait(lambda:
                    not review.checks_running(),120) and all(any(i['kind'] in {'stutter','merge'}
                    for i in review._by_id[c]['issues']) for c in repeats))
                original_texts=[c.text for c in project.cues]
                started,release=threading.Event(),threading.Event()
                def delayed(*_args,**_kwargs):
                    started.set();release.wait(10)
                    return type('Result',(),{'hits':[
                        TextOccurrence('stable-16',48000,'它','',(0,1),source='ai_accepted'),
                        TextOccurrence('stable-18',54000,'古龙','骨龙',(3,5),source='ai_accepted')],
                        'receipt':{}})()
                review.ai_stand_in=delayed
                review._run(True)
                check('model thread is running before disabling cleanup',wait(started.is_set,10))
                review._batch_selected=repeats|{'stable-18'};review._batch_update()
                QTest.mouseClick(review.stutter_toggle,Qt.LeftButton);pump()
                check('disabled repeats leave selection and retain mixed lexical row',review._batch_selected=={'stable-18'})
                release.set()
                check('late model result finishes',wait(lambda:review._worker is None,15))
                check('late result does not restore disabled repeats',all(not review._groups(review._by_id[c]) for c in repeats))
                check('mixed row retains normal glossary correction',any(i['replacement']=='骨龙'
                    for i in review._unresolved(review._by_id['stable-18'])))
                check('disabled repeat marks and previews are absent',all(not review.list.groups(review._by_id[c])
                    and not review.list._visible_issues(review._by_id[c]) for c in repeats))
                review.search.setText('有点');review.filter_buttons['suggested'].click();pump();review._apply_filter()
                check('repeat-only row leaves suggested filter',not review.list.visible)
                review.filter_buttons['all'].click();pump();review._apply_filter()
                check('original caption remains in all captions',[review._rows[n]['cue_id'] for n in review.list.visible]==['stable-15'])
                review.search.clear();review._apply_filter();review._batch_selected=repeats|{'stable-18'}
                review._batch_adopt();pump()
                check('batch adoption cannot delete the disabled repeated words',
                    all(project.cues[int(c.split('-')[1])].text==original_texts[int(c.split('-')[1])] for c in repeats)
                    and project.cues[18].text=='那 那骨龙很赚')
                review._undo();pump()
                check('cleanup switch never changes document text',original_texts==[c.text for c in project.cues])
                _capture(window,out/'01-cleanup-disabled.png')
                review.ai_stand_in=None;review.stutter_toggle.setChecked(True);review._run(False)
                check('reenabling and rematching restores only valid proposals',settle_checks())
                review.search.clear();review._batch_clear();review.filter_buttons['all'].click();review._apply_filter()
                _capture(window,out/"01-initial.png")
                review.term_filter.setText("术语甲"); pump()
                check("alias search and count agree",review.term_list.count()==1 and "1 /" in review.term_count.text())
                review.term_list.setCurrentRow(0)
                QTest.mouseClick(review.term_edit,Qt.LeftButton); pump()
                editor=review._term_editor
                check("term editor shows real persisted aliases","术语甲" in editor.alias_input.toPlainText())
                _capture(editor,out/"02-edit-alias.png")
                editor.alias_input.setFocus(); QTest.keyClick(editor.alias_input,Qt.Key_A,Qt.ControlModifier)
                event=QInputMethodEvent();event.setCommitString("古龙");QApplication.sendEvent(editor.alias_input,event)
                before=[c.text for c in project.cues]
                QTest.mouseClick(editor.save_button,Qt.LeftButton);pump()
                check("alias edit rematches current suggestions",settle_checks())
                check("term edit never rewrites confirmed caption text",before==[c.text for c in project.cues])
                check("deleted alias stops literal matching",TermResolver(review._snapshot).resolve("术语甲来了").text=="术语甲来了")
                check("old mapping proposal not restored from cache",not any(i["original"]=="术语甲" for i in review._by_id["stable-4"]["issues"]))
                review.term_filter.setText("NameID");pump();review.term_list.setCurrentRow(0)
                QTest.mouseClick(review.term_edit,Qt.LeftButton);pump()
                editor=review._term_editor
                editor.canonical_input.setFocus();QTest.keyClick(editor.canonical_input,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClicks(editor.canonical_input,"NAMEid");QTest.mouseClick(editor.save_button,Qt.LeftButton)
                check("canonical spelling edit affects matching",settle_checks() and TermResolver(review._snapshot).resolve("nameid").text=="NAMEid")
                review.term_filter.clear();pump()
                # Exercise delete + its separate library undo, retaining alias removal.
                item=next(review.term_list.item(i) for i in range(review.term_list.count())
                          if review.term_list.item(i).data(Qt.UserRole)=="降灵" and
                          review.term_list.item(i).data(Qt.UserRole+1).library_id==fixture["other"])
                review.term_list.setCurrentItem(item);QTest.mouseClick(review.term_delete,Qt.LeftButton);pump()
                check("whole term deletion removes only selected library",not any(r.library_id==fixture["other"] for r in library_terms(review._snapshot)))
                QTest.mouseClick(review.term_undo,Qt.LeftButton);pump()
                check("library undo restores deleted term",settle_checks() and any(r.library_id==fixture["other"] for r in library_terms(review._snapshot)))
                primary=next(review.library_list.item(i) for i in range(review.library_list.count())
                             if review.library_list.item(i).data(Qt.UserRole)==fixture["library"])
                primary.setCheckState(Qt.Unchecked)
                check("deselecting library immediately removes its pending suggestions",not any(
                    i["replacement"] in {"骨龙","火笼"} and not i["checked"] for row in review._rows for i in row["issues"]))
                check("deselected library cannot return through late callbacks",settle_checks() and not any(
                    i["replacement"] in {"骨龙","火笼"} and not i["checked"] for row in review._rows for i in row["issues"]))
                primary.setCheckState(Qt.Checked)
                check("reselected real library rematches without text changes",settle_checks() and before==[c.text for c in project.cues])
                # Full-row checkbox and independent controls: real painted targets.
                review.list.repaint();pump()
                target="stable-5";review.list.ensure_visible(target);pump();review.list.repaint()
                box=next(r for r,a,c,_ in review.list._hit_boxes if a=='rowcheck' and c==target)
                QTest.mouseClick(review.list,Qt.LeftButton,pos=box.center().toPoint())
                check("large caption row selects its stable ID",review._batch_selected=={target})
                detail=next((r for r,a,c,_ in review.list._hit_boxes if a=="detail" and c==target),None)
                check("details target exists",detail is not None)
                QTest.mouseClick(review.list,Qt.LeftButton,pos=detail.center().toPoint());pump()
                check("details does not toggle row selection",review._batch_selected=={target})
                review.list.ensure_visible(target);pump()
                _capture(window,out/"03-details-and-selection.png")
                # Timings include the first actual Paint after the operation.
                paints=[]; original=review.list.paintEvent
                def paint(event):
                    original(event);paints.append(time.perf_counter())
                review.list.paintEvent=paint
                def timed(name,callback):
                    stamp=time.perf_counter();callback();end=time.perf_counter()
                    wait(lambda:any(p>=stamp for p in paints),2)
                    first=next((p for p in paints if p>=stamp),end)
                    result["timings_ms"].setdefault(name,[]).append(round((max(first,end)-stamp)*1000,2));save()
                review.speaker_filter.setCurrentIndex(review.speaker_filter.findData("A"));pump()
                timed("select_filtered",lambda:QTest.mouseClick(review.batch_all,Qt.LeftButton))
                check("all selects offscreen rows within speaker filter",len(review._batch_selected)>300 and all(review._by_id[c]["speaker_id"]=="A" for c in review._batch_selected))
                review.search.setText("no-such-caption");review._apply_filter()
                check("filter change removes hidden selection",not review._batch_selected)
                review.search.clear();review.speaker_filter.setCurrentIndex(0)
                review.filter_buttons["suggested"].click();pump()
                initial=[c.text for c in project.cues]
                for index in range(3):
                    timed("select_all",lambda:QTest.mouseClick(review.batch_all,Qt.LeftButton))
                    check(f"all selected entire filtered list {index}",len(review._batch_selected)==len(review.list.visible)>700)
                    timed("ignore",lambda:QTest.mouseClick(review.batch_ignore,Qt.LeftButton))
                    check(f"ignore processes every unresolved issue {index}",not review.list.visible and initial==[c.text for c in project.cues])
                    timed("undo_ignore",lambda:QTest.mouseClick(review.undo_button,Qt.LeftButton))
                    check(f"one undo restores all rows {index}",len(review.list.visible)>700)
                timed("select_adopt",lambda:QTest.mouseClick(review.batch_all,Qt.LeftButton))
                timed("adopt",lambda:QTest.mouseClick(review.batch_adopt,Qt.LeftButton))
                check("bulk adoption changes only selected valid issues",project.cues[5].text=="骨龙和火笼来了" and project.cues[0].text==initial[0])
                timed("undo_adopt",lambda:QTest.mouseClick(review.undo_button,Qt.LeftButton))
                check("bulk adoption undoes as one operation",[c.text for c in project.cues]==initial)
                # Leave a persisted ignore decision and inspect state on restart.
                review._batch_selected={"stable-5"};review._batch_ignore()
                check("project saves with ignored metadata",review._flush_save())
                _capture(window,out/"04-batch.png")
                # Adjacent real speech uses exactly cue A, not the next sentence.
                from ..playback.cue_audio_preview import plan_cue_preview,preview_command
                from ..studio.studio_video_track import ffmpeg_executable
                plan=plan_cue_preview(project,"stable-0")
                command,_=preview_command(plan,ffmpeg_executable())
                payload=subprocess.run(command,capture_output=True,check=True).stdout
                decoded_ms=len(payload)/192
                result["speech"]={"voice_culture":fixture["voice_culture"],"cue_range_ms":list(plan.cue_range_ms),
                                  "play_range_ms":list(plan.play_range_ms),"decoded_ms":decoded_ms}
                check("adjacent speech decode ends at cue boundary",plan.play_range_ms==plan.cue_range_ms and abs(decoded_ms-fixture["boundary_ms"])<2)
                review._play("stable-0");check("real speech sink starts",wait(lambda:review._player.state=="playing",10))
                if os.environ.get("TWOBYTEASR_PROOFREAD_AUDIO_OUTPUT")=="1":
                    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioCue
                    audio=SubtitleProject(StudioMedia(str(out/"audio-probe.wav"),duration_ms=8000),cues=[
                        StudioCue("A",0,2000,"啊 属性减一"),StudioCue("B",2000,4000,"那还……"),
                        StudioCue("C",4000,6000,"第三句")],render_settings={"_cue_domain":"timeline"})
                    audio.validate();player=review._player;player.stop();pump(.3)
                    result["audio_actions"]=[];result["audio_states"]=[]
                    player.state_changed.connect(lambda cue,state:result["audio_states"].append(
                        {"time":time.perf_counter(),"cue":cue,"state":state}))
                    def audio_action(name,callback):
                        stamp=time.perf_counter();callback()
                        result["audio_actions"].append({"name":name,"time":stamp,"return_ms":(time.perf_counter()-stamp)*1000});save()
                    audio_action("first_A",lambda:player.play(audio,"A"));pump(3.2)
                    for index in range(3):
                        audio_action(f"repeat_A_{index}",lambda:player.play(audio,"A"));pump(.7)
                        audio_action(f"pause_A_{index}",player.pause);pump(.4)
                        audio_action(f"resume_A_{index}",player.resume);pump(.25)
                        audio_action(f"stop_{index}",player.stop);pump(.25)
                    audio_action("loading_B",lambda:player.play(audio,"B"))
                    audio_action("pause_loading",player.pause);pump(1)
                    audio_action("rapid_A",lambda:player.play(audio,"A"));pump(.01)
                    audio_action("rapid_B",lambda:player.play(audio,"B"));pump(.01)
                    audio_action("rapid_C",lambda:player.play(audio,"C"));pump(2.7)
                    audio_action("leave",player.stop);pump(.3)

                review._back();pump(.15)
                check("leaving page stops sink and pending intent",not review._player.cue_id and not review._player._wants_play)
                if review.stutter_toggle.isChecked():QTest.mouseClick(review.stutter_toggle,Qt.LeftButton)
                check('disabled cleanup preference is saved',not review._stored_stutter())
            result["passed"]=all(c["passed"] for c in result["checks"])
        except BaseException:
            result["error"]=traceback.format_exc()
        finally:
            if review is not None:review.shutdown()
            result["source_unchanged_during_audit"] = result["source_sha256"] == hashes()
            result["passed"] &= result["source_unchanged_during_audit"]
            save();QTimer.singleShot(50,window.close)
    QTimer.singleShot(350,run)
