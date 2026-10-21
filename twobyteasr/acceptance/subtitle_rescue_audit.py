"""Synthetic acceptance executed inside the shipped rescue EXE itself."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from dataclasses import asdict


def fixture():
    from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    p = SubtitleProject(StudioMedia("missing-video.mp4", duration_ms=60000),
                        speakers=[StudioSpeaker(f"S{i:02d}", f"S{i:02d}") for i in range(5)])
    for s in range(4):
        for i in range(20):
            text = f"中文 日本語 😀 第 {i+1} 句"
            if s == 2 and i == 17: text = "上半句\n"
            if s == 1 and i == 3: text = "第一行\r\n第二行\r\n"
            if s == 3 and i == 5: text = "  正文 \t\n\n123\n数字之后\n\n"
            if s == 0 and i == 1: text = ""
            p.cues.append(StudioCue(f"S{s:02d}-{i+1}",1000+i*2000,1800+i*2000,text,f"S{s:02d}",original_text="旧 ASR"))
    p.validate()
    p.render_settings["_cue_domain"] = "timeline"
    p.speakers[2].hidden = True
    return p


def run(output: Path, *, gui=False):
    from ..exports import studio_subtitle_export as export
    from ..exports import subtitle_rescue as rescue
    from ..exports.srt_codec import normalize_srt_text, parse_srt
    from ..projects.studio_project import StudioCue
    from ..timeline.studio_edit_sequence import VideoSegment, sequence_of, replace_runtime_sequence
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"build_id":rescue.BUILD_ID, "frozen":bool(getattr(sys,"frozen",False)),
              "executable":sys.executable, "executable_sha256":hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
              "checks":[], "failed":0}
    def check(name, passed):
        result["checks"].append({"name":name,"passed":bool(passed)})
        if not passed: raise AssertionError(name)
    # Nothing in recovery needs child processes or network. This stays active
    # throughout core and GUI acceptance, including all worker threads.
    def guard(event, args):
        if event in {"subprocess.Popen","os.system","socket.connect","socket.getaddrinfo"}:
            raise AssertionError("unexpected external operation: " + event)
    sys.addaudithook(guard)
    try:
        p = fixture()
        source = output / "10月20日 (1).2byteproj"
        source.write_text(json.dumps(p.to_dict(),ensure_ascii=False),encoding="utf-8")
        raw = source.read_bytes()
        out = rescue.rescue_subtitles(source, output / "中文 目录 (1)")
        manifest = json.loads((out / "rescue-manifest.json").read_text(encoding="utf-8"))
        check("input_untouched", raw == source.read_bytes() == (out / "input-copy.json").read_bytes())
        check("all_four_speakers_and_empty_track", len(manifest["files"]) == 6)
        check("all_80_timeline_cues", manifest["timeline_cue_count"] == 80)
        check("hidden_s02_included", manifest["hidden_speakers_included"] == ["S02"])
        for file in manifest["files"]:
            rows, errors = parse_srt((out / file["name"]).read_text(encoding="utf-8"))
            expected = sorted([c for c in p.cues if not file["speaker_id"] or c.speaker_id == file["speaker_id"]],
                              key=lambda c:(c.start_ms,c.end_ms,c.id))
            check("exact_"+(file["speaker_id"] or "combined"), not errors and
                  [(r.start_ms,r.end_ms,r.text) for r in rows] == [(c.start_ms,c.end_ms,normalize_srt_text(c.text)) for c in expected])
        check("empty_track_written", next(f for f in manifest["files"] if f["speaker_id"] == "S04")["cue_count"] == 0)
        repeat = rescue.rescue_subtitles(source, out.parent)
        check("repeat_never_overwrites", repeat != out and source.read_bytes() == raw)
        # Verify actual normal-export production path too, not just rescue.
        for speaker in p.speakers: speaker.hidden=False
        artifacts = export.export_subtitle_artifacts(p,output/"ordinary",source.stem,
            export.SubtitleExportOptions(frozenset({"srt"}),"per_speaker"))
        check("ordinary_four_speakers", len(artifacts)==4 and sum(a.cue_count for a in artifacts)==80)
        s02=next(a for a in artifacts if a.speaker_id=="S02")
        subset=copy.copy(p);subset.cues=[c for c in p.cues if c.speaker_id=="S02"]
        original=s02.path.read_text(encoding="utf-8")
        for name,bad in [("text",original.replace("上半句", "上半句多出内容")),
                         ("timestamps",original.replace("00:00:35,000", "00:00:35,001"))]:
            s02.path.write_text(bad,encoding="utf-8")
            v=export.verify_subtitle_artifact(s02,subset)
            check("reject_"+name, not v.valid and v.first_mismatch["field"]==name
                  and v.first_mismatch["subtitle_number"]==18 and v.first_mismatch["cue_id"]=="S02-18")
        s02.path.write_text(original,encoding="utf-8")
        # Mid-batch validation failure must preserve every prior artifact.
        preserved={a.path:a.path.read_bytes() for a in artifacts}
        real=export._atomic_text_write
        def corrupt(path, content):
            real(path,content.replace("上半句","截断") if "S02" in path.name else content)
        export._atomic_text_write=corrupt
        try:
            try:
                export.export_subtitle_artifacts(p,output/"ordinary",source.stem,
                    export.SubtitleExportOptions(frozenset({"srt"}),"per_speaker"))
                raise AssertionError("corruption was accepted")
            except export.SubtitleVerificationError as exc:
                check("friendly_s02_18", "S02 第 18 条字幕" in str(exc))
                (output/"synthetic-error-details.json").write_text(exc.details(),encoding="utf-8")
        finally: export._atomic_text_write=real
        check("validation_preserves_existing_batch",all(path.read_bytes()==data for path,data in preserved.items()))
        # Source time -> 2x cut and repeated 1x clip; text remains the edit.
        mapped=fixture();mapped.render_settings.pop("_cue_domain",None)
        mapped.cues=[StudioCue("mapped",11000,11800,"最后编辑\n","S02")]
        seq=copy.deepcopy(sequence_of(mapped))
        seq.segments=[VideoSegment("cut","missing-video.mp4",10000,20000,0,5000),
                      VideoSegment("repeat","missing-video.mp4",10000,20000,7000,17000)]
        replace_runtime_sequence(mapped,seq)
        mapping_input=output/"剪辑映射.json"
        mapping_input.write_text(json.dumps(mapped.to_dict(),ensure_ascii=False),encoding="utf-8")
        mapped_out=rescue.rescue_subtitles(mapping_input,output/"mapped")
        rows,_=parse_srt(next(mapped_out.glob("*_S02.srt")).read_text(encoding="utf-8"))
        check("cut_speed_repeat_current_timeline",[(r.start_ms,r.end_ms,r.text) for r in rows]==[(500,900,"最后编辑\n"),(8000,8800,"最后编辑\n")])
        bad_input=output/"任务记录.json";bad_input.write_text('{"job_id":"example","result":{"cue_count":548}}',encoding="utf-8")
        try:
            rescue.rescue_subtitles(bad_input,output/"must-not-exist")
            raise AssertionError("summary accepted as project")
        except rescue.RescueInputError:
            check("summary_rejected_without_fake_asr_timeline",not (output/"must-not-exist").exists())
        # A's shared contract accepts human edits without pretending old word
        # indices still apply. Exercise this in the frozen package itself.
        edited=fixture(); edited.cues=[StudioCue("manual",1000,1800,"最后手工修改\n","S02",original_text="ASR 原文")]
        edited.studio_state["caption_timeline"]={"version":1,"instances":{"manual":{
            "text":"ASR 原文","words":[{"text":"ASR 原文","start_ms":99999,"end_ms":99999,"char_start":0,"char_end":100}]}}}
        edited_source=output/"人工修改 (2).json"
        edited_source.write_text(json.dumps(edited.to_dict(),ensure_ascii=False),encoding="utf-8")
        edited_raw=edited_source.read_bytes()
        edited_out=rescue.rescue_subtitles(edited_source,output/"stale-words")
        edited_manifest=json.loads((edited_out/"rescue-manifest.json").read_text(encoding="utf-8"))
        check("shared_contract_stale_words_nonblocking",edited_manifest["consistency"]["ok"] and
              any(w["code"]=="stale_word_alignment" for w in edited_manifest["consistency"]["warnings"]))
        rows,errors=parse_srt(next(edited_out.glob("*_S02.srt")).read_text(encoding="utf-8"))
        check("manual_text_sentence_time_and_input_preserved",not errors and
              [(r.start_ms,r.end_ms,r.text) for r in rows]==[(1000,1800,"最后手工修改\n")] and
              edited_source.read_bytes()==edited_raw)
        edited.speakers[2].hidden=False
        json_artifact=export.export_subtitle_artifacts(edited,output/"edited-json","manual",
            export.SubtitleExportOptions(frozenset({"json"})))[0]
        json_cue=json.loads(json_artifact.path.read_text(encoding="utf-8"))["cues"][0]
        check("json_omits_stale_word_indices",json_cue["original_text"]=="最后手工修改\n" and
              json_cue["word_timing"]["pieces"]==[] and "stale_word_alignment" in json_cue["word_timing"]["basis"])
        implicit=copy.deepcopy(edited);implicit.studio_state.pop("caption_timeline",None)
        implicit.asr_evidence["cue-align:manual"]={"cue_alignment":{},"text":implicit.cues[0].text,
            "caption_arbitration":{"acoustic_words":[{"text":"最","start_ms":1000,"end_ms":1200,"char_start":0,"char_end":999}]}}
        implicit_artifact=export.export_subtitle_artifacts(implicit,output/"implicit-words","manual",
            export.SubtitleExportOptions(frozenset({"json"})))[0]
        implicit_row=json.loads(implicit_artifact.path.read_text(encoding="utf-8"))["cues"][0]
        check("json_implicit_alignment_uses_shared_contract",implicit_row["word_timing"]["pieces"]==[] and
              implicit_row["word_timing"]["basis"].startswith("unavailable:") and implicit_row["text"]=="最后手工修改\n")
        from ..exports.export_consistency import SubtitleDataError
        conflict=copy.deepcopy(edited);conflict.cues[0].evidence_refs=["missing-source"]
        try:
            export.export_subtitle_artifacts(conflict,output/"conflict","conflict",export.SubtitleExportOptions())
            raise AssertionError("missing source silently exported")
        except SubtitleDataError as exc:
            check("shared_contract_conflict_cue_located",exc.result.errors[0].cue_id=="manual" and
                  not list((output/"conflict").glob("*.srt")))
        invalid_time=copy.deepcopy(edited);invalid_time.cues[0].start_ms=1000.4
        try:
            export.export_subtitle_artifacts(invalid_time,output/"invalid-time","invalid",export.SubtitleExportOptions())
            raise AssertionError("fractional source time was coerced")
        except SubtitleDataError as exc:
            check("invalid_time_rejected_before_coercion",any(i.code=="sentence_time_invalid" for i in exc.result.errors) and
                  invalid_time.cues[0].start_ms==1000.4)
        invalid_saved=json.loads(edited_raw.decode("utf-8"));invalid_saved["cues"][0]["evidence_refs"]=[""]
        invalid_source=output/"无效引用.json";invalid_source.write_text(json.dumps(invalid_saved),encoding="utf-8")
        try:
            rescue.rescue_subtitles(invalid_source,output/"invalid-reference")
            raise AssertionError("invalid reference was removed by loader")
        except SubtitleDataError as exc:
            check("invalid_saved_reference_rejected_before_cleanup",any(i.code=="source_reference_invalid" for i in exc.result.errors)
                  and not (output/"invalid-reference").exists())
        if gui:
            from PySide6.QtWidgets import QApplication, QLabel
            from PySide6.QtGui import QPalette
            from PySide6.QtTest import QTest
            from PySide6.QtCore import Qt
            from ..exports.subtitle_rescue_ui import SubtitleRescueDialog
            app=QApplication.instance() or QApplication([])
            window=SubtitleRescueDialog(str(source));window.output.setText(str(output/"GUI 输出 (1)"));window.show()
            QTest.qWait(200)
            check("headed_window_visible",window.isVisible() and app.platformName()=="windows")
            window.grab().save(str(output/"rescue-ready.png"))
            QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline and (window.worker is None or window.worker.isRunning() or not window.run_button.isEnabled()):
                QTest.qWait(20)
            check("gui_worker_completed",window.worker is not None and not window.worker.isRunning())
            check("gui_all_cues_success", "80" in window.status.text() and window.open_button.isEnabled())
            window.grab().save(str(output/"rescue-success.png"))
            window.source.setText(str(bad_input));QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and (window.worker.isRunning() or not window.run_button.isEnabled()):QTest.qWait(20)
            check("gui_failure_explained", "缺少已编辑字幕及时间轴" in window.details.toPlainText() and not window.open_button.isEnabled())
            window.grab().save(str(output/"rescue-failure.png"))
            window.source.setText(str(invalid_source));QTest.mouseClick(window.run_button,Qt.MouseButton.LeftButton)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and (window.worker.isRunning() or not window.run_button.isEnabled()):QTest.qWait(20)
            check("gui_source_failure_has_structured_cue_details",all(value in window.details.toPlainText()
                  for value in ("cue_id", "manual", "source_reference_invalid")))
            window.grab().save(str(output/"rescue-source-failure.png"))
            window.close();app.processEvents()
            previous_style=app.styleSheet()
            app.setStyleSheet("QWidget {background:#201d26;color:#f7f4f0;} QLabel {color:#f7f4f0;}"
                              "QLineEdit,QTextEdit {background:#16131b;color:#f7f4f0;}")
            inherited=SubtitleRescueDialog(str(source));inherited.show();QTest.qWait(150)
            check("rescue_contrast_under_dark_application",all(label.palette().color(QPalette.ColorRole.WindowText).lightness()<128
                  for label in inherited.findChildren(QLabel)) and
                  inherited.details.palette().color(QPalette.ColorRole.Text).lightness()<128)
            inherited.grab().save(str(output/"rescue-dark-host.png"))
            inherited.close();app.setStyleSheet(previous_style);app.processEvents()
        check("no_player_no_recognition_no_network",True)
    except Exception:
        result["failed"]=1
        result["error"]=traceback.format_exc()
    result["passed"]=sum(c["passed"] for c in result["checks"])
    (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    if sys.stdout: print(json.dumps({"passed":result["passed"],"failed":result["failed"],"frozen":result["frozen"]}))
    return 1 if result["failed"] else 0
