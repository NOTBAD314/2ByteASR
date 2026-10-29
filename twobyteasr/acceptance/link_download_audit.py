"""Opt-in real UI and real downloader acceptance. Never loaded in normal use."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import statistics
import threading
import time
import traceback

_provider_calls=0


def install_guards():
    from ..providers.provider_service import ProviderService
    from ..app.ui import EndpointEditor
    from ..studio.studio_ai_flow import StudioAIFlowMixin
    EndpointEditor._queue_model_discovery=lambda *a,**k:None
    StudioAIFlowMixin._start_ai_provider_probe=lambda *a,**k:None
    def denied(*args,**kwargs):
        global _provider_calls
        _provider_calls+=1
        raise RuntimeError("Paid AI is not authorized in download acceptance")
    ProviderService.submit=denied


def start(window,out):
    from PySide6.QtCore import QObject,QTimer,Qt,QMimeData,QPointF,QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox
    from .blank_project_audit import _capture
    from ..projects.studio_project import load_project
    from ..projects.subtitle_consistency import validate_project
    from ..timeline.studio_commands import SetCueFieldsCommand
    from ..media.link_manifest import load_bundle,sha256
    from ..projects.link_import import LinkImportCommand

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result=dict(passed=False,checks=[],screenshots=[],network="real YouTube, no cookies",human_listening="NOT VERIFIED")
            from ..diagnostics.build_identity import load_build_identity
            self.result["identity"] = load_build_identity().to_dict()
            self.steps=self.run();self.waiting=0;self.deadline=time.monotonic()+180
            self.last_tick=time.monotonic();self.delays=[]
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(30)

        def check(self,name,value,detail=None):
            self.result["checks"].append(dict(name=name,passed=bool(value),detail=detail))
            (out/"link-progress.json").write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding="utf-8")
            if not value:
                raise AssertionError(name+": "+str(detail))

        def shot(self,name,surface=None):
            _capture(surface or window,out/(name+".png"))
            self.result["screenshots"].append(name+".png")

        def tick(self):
            try:
                now=time.monotonic()
                controller=getattr(window,"_link_download_controller",None)
                if controller and any(t["state"]=="running" for t in controller.queue.snapshots()):
                    self.delays.append((now-self.last_tick)*1000)
                self.last_tick=now
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    message=modal.text()
                    self.shot("unexpected-modal",modal)
                    modal.reject()
                    raise RuntimeError(message)
                if callable(self.waiting):
                    if not self.waiting():
                        if now>self.deadline:raise TimeoutError("Stage timed out")
                        return
                elif now<self.waiting:return
                value=next(self.steps)
                self.waiting=value if callable(value) else now+float(value)
                self.deadline=now+180
            except StopIteration:
                self.result["passed"]=True;self.finish()
            except Exception:
                self.result["error"]=traceback.format_exc()
                controller=getattr(window,"_link_download_controller",None)
                if controller:self.result["tasks"]=controller.queue.snapshots()
                try:self.shot("failure",controller.dialog if controller and controller.dialog.isVisible() else window)
                except Exception:pass
                self.finish()

        def run(self):
            yield .5
            self.check("home link entry visible",window.link_download_button.isVisible())
            QTest.mouseClick(window.link_download_button,Qt.MouseButton.LeftButton)
            self.controller=window._link_download_controller
            dialog=self.controller.dialog
            self.check("modeless download window",not dialog.isModal())
            dialog.directory.setText(str(out/"downloads 中文 日本語"))
            dialog.url.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PLtest")
            QTest.mouseClick(dialog.parse_button,Qt.MouseButton.LeftButton)
            yield lambda:dialog.catalog is not None or dialog.parse_button.isEnabled()
            self.check("real catalog parsed",dialog.catalog is not None,dialog.message.text())
            catalog=dialog.catalog
            self.check("current video only",catalog["video_id"]=="jNQXAC9IVRw" and "list=" not in catalog["url"])
            manual={t["language"]:t["track_id"] for t in catalog["tracks"] if t["source"]=="manual"}
            self.check("real manual en and de",{"en","de"}<=set(manual),manual)
            for i in range(dialog.tracks.topLevelItemCount()):
                item=dialog.tracks.topLevelItem(i)
                item.setCheckState(0,Qt.CheckState.Checked if item.data(0,Qt.ItemDataRole.UserRole) in (manual["en"],manual["de"]) else Qt.CheckState.Unchecked)
            dialog.primary.setCurrentIndex(dialog.primary.findData(manual["en"]))
            dialog.translation.setCurrentIndex(dialog.translation.findData(manual["de"]))
            video=next(f for f in catalog["formats"] if str(f["vcodec"]).startswith("avc") and (f["height"] or 0)<=360)
            audio=next(f for f in reversed(catalog["formats"]) if f["ext"]=="m4a" and f["vcodec"]=="none" and "drc" not in f["format_id"])
            dialog.video_format.setCurrentIndex(dialog.video_format.findData(video["format_id"]))
            dialog.audio_format.setCurrentIndex(dialog.audio_format.findData(audio["format_id"]))
            yield .35
            self.shot("01-real-selection",dialog)
            QTest.mouseClick(dialog.add_button,Qt.MouseButton.LeftButton)
            self.check("queued through UI",len(self.controller.queue.snapshots())==1,dialog.message.text())
            key=self.controller.queue.snapshots()[0]["task_id"]
            yield lambda:self.controller.task(key)["state"] in {"imported","failed","partial"}
            task=self.controller.task(key)
            self.check("auto imported new project",task["state"]=="imported",task)
            page=self.controller.page()
            self.check("studio entry visible",page.studio_link_download_button.isVisible())
            self.check("six editable source captions",len(page.project.cues)==6)
            manifest=Path(task["directory"])/"download.2byte-download.json"
            bundle=load_bundle(manifest,verify_media=True)
            self.result["manifest"]=str(manifest)
            self.result["tools"]=bundle["manifest"]["tools"]
            self.check("unequal language segmentation retained",
                len(bundle["captions"][manual["en"]]["captions"])==6 and len(bundle["captions"][manual["de"]]["captions"])==4)
            self.check("no row index bilingual pairing",task["import_result"]["translation_unmatched"]>0,task["import_result"])
            self.check("project consistency",validate_project(page.project).ok)
            dialog.hide()
            yield .5
            self.shot("02-imported")
            # Sample actual native preview at the beginning, middle and end.
            for name,seconds in (("start",1.7),("middle",9.0),("end",17.5)):
                page._seek(seconds)
                yield .6
                self.shot("03-"+name)
                self.check("seek "+name,abs(page.timeline.playhead_ms-seconds*1000)<500,page.timeline.playhead_ms)
            cue=page.project.cues[0]
            old=cue.text;edited=old+" [checked]"
            page.undo_stack.push(SetCueFieldsCommand(page.project,cue.id,{"text":edited},"审阅下载字幕"))
            page.undo_stack.undo();self.check("edit undo",page.project.cues[0].text==old)
            page.undo_stack.redo();self.check("edit redo",page.project.cues[0].text==edited)
            duplicate=LinkImportCommand(page.project,bundle,bundle.get("media_result"))
            self.check("duplicate notification preserves edited caption",duplicate.isObsolete() and page.project.cues[0].text==edited)
            original_hashes={s["original"]["path"]:sha256(manifest.parent/s["original"]["path"]) for s in bundle["manifest"]["subtitles"]}
            page.save()
            path=Path(page.project_path)
            yield lambda:path.is_file() and any(c["text"]==edited for c in json.loads(path.read_text(encoding="utf-8"))["cues"])
            reopened=load_project(path)
            self.check("saved edited source and translation",reopened.cues[0].text==edited and validate_project(reopened).ok)
            self.result["project"]=str(path)
            # Production subtitle exporter and FFmpeg renderer on a detached snapshot.
            self.export_done=False;self.export_error=""
            def export():
                try:
                    from ..exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
                    from ..exports.studio_render import RenderJob,RenderSettings,run_render_job
                    artifacts=export_subtitle_artifacts(reopened,out/"exports","download-edited",
                        SubtitleExportOptions(formats=frozenset({"srt","ass","json"})))
                    ass=next(a.path for a in artifacts if a.format=="ass")
                    ffmpeg=self.controller.engine.tools["ffmpeg"]
                    target=out/"exports/short-preview.mp4"
                    run_render_job(ffmpeg,RenderJob(reopened.media.path,str(ass),str(target),
                        settings=RenderSettings(encoder="libx264",preset="ultrafast",audio_codec="aac"),
                        start_seconds=0,duration_seconds=4))
                    self.result["exports"]=[str(a.path) for a in artifacts]+[str(target)]
                    self.result["export_bytes"]=target.stat().st_size
                except Exception:self.export_error=traceback.format_exc()
                finally:self.export_done=True
            threading.Thread(target=export,daemon=True).start()
            yield lambda:self.export_done
            self.check("production SRT ASS JSON and short video exports",not self.export_error,self.export_error)
            self.check("original bytes unchanged",all(sha256(manifest.parent/name)==value for name,value in original_hashes.items()))
            # Close/reopen goes through the real controller, not just a JSON roundtrip.
            page._close_project_session("link-download-audit-reopen")
            window.open_studio_project(str(path))
            yield lambda:page.project is not None and page.project.cues and page.project.cues[0].text==edited
            yield lambda:page._readiness.ready and not page._readiness.active
            self.check("real project reopen consistency",validate_project(page.project).ok)
            # Playback while the real parser processes a large local subtitle.
            from ..media.link_subtitles import parse_subtitles
            synthetic = ("WEBVTT\n\n" + "\n\n".join(
                f"00:{i//60:02}:{i%60:02}.000 --> 00:{(i+1)//60:02}:{(i+1)%60:02}.000\nCaption {i}"
                for i in range(2400))).encode()
            self.parse_done=False;self.parse_error=""
            def heavy_parse():
                try:
                    for _ in range(10):parse_subtitles(synthetic)
                except Exception:self.parse_error=traceback.format_exc()
                finally:self.parse_done=True
            page.video.set_paused(True)
            page._seek(1.0)
            yield lambda:abs(page.timeline.playhead_ms-1000)<100 and not getattr(page.video,"_seek_hold_active",False) and not getattr(page.video,"_buffered_play_pending",False)
            yield .3
            before_playhead=page.timeline.playhead_ms
            page._toggle_playback()
            threading.Thread(target=heavy_parse,daemon=True).start()
            yield 1.2
            self.check("playback advances during subtitle preparation",
                       page.timeline.playhead_ms>before_playhead+500,page.timeline.playhead_ms-before_playhead)
            page.video.set_paused(True)
            yield lambda:self.parse_done
            self.check("background large subtitle parsing",not self.parse_error,self.parse_error)
            # A real in-flight download must not write into the new blank project.
            self.controller.show()
            dialog.destination.setCurrentIndex(dialog.destination.findData("current"))
            dialog.mode.setCurrentIndex(dialog.mode.findData("video"))
            QTest.mouseClick(dialog.add_button,Qt.MouseButton.LeftButton)
            second=self.controller.queue.snapshots()[-1]["task_id"]
            yield lambda:self.controller.task(second)["state"]=="running"
            page.project_controller.create_blank_project()
            yield lambda:page.project is not None and not page.project.media.path and not page.project.cues
            new_identity=page.project.project_id
            yield lambda:self.controller.task(second)["state"] in {"pending_import","failed","partial","imported"}
            self.check("late completion remains pending",self.controller.task(second)["state"]=="pending_import",self.controller.task(second))
            self.check("new project protected",page.project.project_id==new_identity and not page.project.cues and not page.project.media.path)
            # Native drop entry discovers the adjacent receipt and commits media+captions once.
            dialog.hide()
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(bundle["media_path"])])
            event=QDropEvent(QPointF(200,200),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            page.dropEvent(event)
            yield lambda:len(page.project.cues)==6 or page._media_ingest_state=="ERROR"
            self.check("drop discovers companion tracks",len(page.project.cues)==6)
            page.undo_stack.undo()
            self.check("one undo removes drop and captions",not page.project.media_pool and not page.project.cues)
            page.undo_stack.redo()
            self.check("drop redo restores consistent receipt",len(page.project.cues)==6 and validate_project(page.project).ok)
            page.save()
            self.shot("04-drag-import")
            # Cancel while the real metadata subprocess is still running.
            self.controller.show()
            dialog.auto_import.setChecked(False)
            QTest.mouseClick(dialog.add_button,Qt.MouseButton.LeftButton)
            third=self.controller.queue.snapshots()[-1]["task_id"]
            yield lambda:self.controller.task(third)["state"]=="running"
            self.controller.queue.cancel(third)
            yield lambda:self.controller.task(third)["state"]=="cancelled"
            self.check("real cancellation",True)
            yield .3
            self.shot("05-queue",dialog)
            self.check("no automatic paid AI",_provider_calls==0)
            self.result["download_timer_ms"]=dict(count=len(self.delays),median=statistics.median(self.delays) if self.delays else None,
                                                 max=max(self.delays) if self.delays else None)
            self.check("GUI heartbeat during downloads",len(self.delays)>10 and statistics.median(self.delays)<100,self.result["download_timer_ms"])
            self.result["no_models_required"]=True

        def finish(self):
            self.timer.stop()
            self.result["provider_calls"]=_provider_calls
            window.result_exit_code=0 if self.result["passed"] else 1
            def write():
                (out/"link-download.json").write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding="utf-8")
            write()
            def stopped():
                self.result["gui_shutdown"]=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            controller=getattr(window,"_link_download_controller",None)
            if controller:
                controller.shutdown()
                if controller.dialog:controller.dialog.hide()
            page=window.built_page("studio")
            if page and page.project:page.undo_stack.setClean()
            window.close()

    window._link_download_audit=Audit()


def start_review(window,out):
    """Real auto-caption project; mocked provider responses, no paid API."""
    from PySide6.QtCore import QObject,QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..studio import link_caption_cleanup as cleanup
    from ..app import api_key_explainer
    from ..projects.link_cleanup_validation import validate_cleanup_response
    from ..studio.studio_text_tools import parse_cleanup_payload
    from ..timeline.link_timing import cue_start_anchors
    from ..projects.subtitle_consistency import validate_project
    from ..projects.studio_project import load_project

    class Review(QObject):
        def __init__(self):
            super().__init__(window)
            self.result=dict(passed=False,checks=[],network="offline mock AI responses; real previously downloaded auto-caption project")
            from ..diagnostics.build_identity import load_build_identity
            self.result["identity"] = load_build_identity().to_dict()
            self.steps=self.run();self.waiting=0;self.deadline=time.monotonic()+120
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
            self.dialog=None
        def check(self,name,value):
            self.result["checks"].append(dict(name=name,passed=bool(value)))
            if not value:raise AssertionError(name)
        def tick(self):
            try:
                now=time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now>self.deadline:raise TimeoutError("Review timed out")
                        return
                elif now<self.waiting:return
                value=next(self.steps)
                self.waiting=value if callable(value) else now+float(value);self.deadline=now+90
            except StopIteration:self.result["passed"]=True;self.finish()
            except Exception:self.result["error"]=traceback.format_exc();self.finish()
        def run(self):
            window.open_studio_project(str(out/"entry.2byteproj"))
            yield lambda:window.built_page("studio") is not None and window.studio_page.project is not None and len(window.studio_page.project.cues)>100
            page=window.studio_page
            yield .6
            self.check("real automatic-caption project",len(page.project.cues)==273)
            self.check("source language reaches existing text tools",page.project.generation_metadata["language"]["code"]=="en")
            cue=page.project.cues[0]
            self.check("real segment onsets in editor",bool(cue_start_anchors(page.project,cue)))
            for name,seconds in (("start",1.1),("middle",342.0),("end",682.0)):
                page._seek(seconds);yield .6
                _capture(window,out/("auto-"+name+".png"))
                self.check("auto source seek "+name,abs(page.timeline.playhead_ms-seconds*1000)<500)
            self.dialog=cleanup.LinkCaptionCleanupDialog(page,page);self.dialog.show();yield .3
            self.check("light defaults",set(k for k,v in self.dialog.ai_option_boxes.items() if v.isChecked())=={"glossary","punctuation"})
            self.check("local tidy offered for English captions",all(box.isChecked() and box.isEnabled() for box in self.dialog.local_boxes.values()))
            _capture(self.dialog,out/"ai-light-defaults.png")
            api_key_explainer.ask_for_key_if_missing=lambda *a,**k:False
            # 2026-10-26 design A: local tidy alone (no AI), applied and undone in one step.
            from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS,cue_words
            from ..studio.ai_cleanup_dialog import KIND_ROLE
            timed=sum(cue_words(page.project,c)[1]==DOWNLOADED_WORD_ONSETS for c in page.project.cues)
            texts=[c.text for c in page.project.cues]
            for chip in self.dialog.ai_option_boxes.values():chip.setChecked(False)
            started=time.monotonic();self.dialog.ai_run_button.click()
            yield lambda:not self.dialog._cleanup_running
            local_seconds=time.monotonic()-started
            rows=[self.dialog.preview.item(i).data(KIND_ROLE) for i in range(self.dialog.preview.count())]
            self.result["local_tidy"]=dict(word_timed=timed,rows=len(rows),breaks=rows.count("break"),seconds=round(local_seconds,2),status=self.dialog.status_label.text())
            self.check("local tidy finishes quickly in the background",local_seconds<5)
            yield .3
            _capture(self.dialog,out/"ai-local-rows.png")
            if timed:
                self.check("word-timed captions get re-break rows","break" in rows and self.dialog.all_button.isEnabled())
                self.dialog._set_filter("break");yield .3
                _capture(self.dialog,out/"ai-local-breaks.png")
                self.dialog._set_filter("all")
                depth=page.undo_stack.count()
                self.dialog.all_button.click();yield .4
                after=[c.text for c in page.project.cues]
                from ..media.link_tidy import strip_labels
                words=" ".join(strip_labels(t)[0] for t in texts).split()
                self.check("local tidy applied as one undo step",page.undo_stack.count()==depth+1 and len(after)<len(texts)
                           and " ".join(after).split()==words)
                self.check("re-broken captions keep word times",all(cue_words(page.project,c)[1]==DOWNLOADED_WORD_ONSETS for c in page.project.cues))
                self.check("tidied project consistency",validate_project(page.project).ok)
                _capture(window,out/"ai-local-applied.png")
                page.undo_stack.undo();yield .4
                self.check("undo restores the captions",[c.text for c in page.project.cues]==texts)
            else:
                self.check("captions without word times say why nothing is re-broken","词时间" in self.dialog.status_label.text())
            for key,chip in self.dialog.ai_option_boxes.items():chip.setChecked(key in {"glossary","punctuation"})
            for box in self.dialog.local_boxes.values():box.setChecked(False)
            original=cue.text
            def invalid(project,*args,**kwargs):
                time.sleep(.2)
                return validate_cleanup_response({"changes":[dict(cue_id="outside",original=original,replacement="bad",reason="bad")]},project.cues)
            cleanup.request_text_cleanup=invalid
            self.dialog._do_ai_preview()
            yield lambda:not self.dialog._cleanup_running
            self.check("invalid AI preserves all original captions",page.project.cues[0].text==original and not self.dialog._preview_hits)
            self.check("readable invalid AI error","ID" in self.dialog.status_label.text())
            def valid(project,*args,**kwargs):
                time.sleep(.2)
                payload={"changes":[dict(cue_id=cue.id,original=original,replacement=original+".",reason="punctuation",confidence=.99)]}
                return parse_cleanup_payload(validate_cleanup_response(payload,project.cues),project)
            cleanup.request_text_cleanup=valid
            start=time.monotonic();self.dialog._do_ai_preview()
            self.check("preview dispatch does not wait for provider",time.monotonic()-start<.2)
            yield lambda:not self.dialog._cleanup_running
            self.check("preview pending explicit application",page.project.cues[0].text==original and len(self.dialog._preview_hits)==1)
            yield .2
            _capture(self.dialog,out/"ai-preview.png")
            self.dialog._do_apply_preview()
            self.check("preview applied with existing command",page.project.cues[0].text==original+".")
            self.check("changed text drops old anchor indexes",not cue_start_anchors(page.project,page.project.cues[0]))
            page.undo_stack.undo()
            self.check("undo restores source anchors",page.project.cues[0].text==original and bool(cue_start_anchors(page.project,page.project.cues[0])))
            page.undo_stack.redo()
            self.check("AI edit project consistency",validate_project(page.project).ok)
            self.dialog.reject();page.save()
            yield lambda:load_project(page.project_path).cues[0].text==original+"."
            self.check("AI edit persists with source receipts",validate_project(load_project(page.project_path)).ok)
            self.check("no paid provider calls",_provider_calls==0)
        def finish(self):
            self.timer.stop()
            def write():
                (out/"link-download.json").write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding="utf-8")
            write()
            def stopped():self.result["gui_shutdown"]=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            if self.dialog:self.dialog.reject()
            page=window.built_page("studio")
            if page and page.project:page.undo_stack.setClean()
            window.result_exit_code=0 if self.result["passed"] else 1
            window.close()
    window._link_review=Review()
