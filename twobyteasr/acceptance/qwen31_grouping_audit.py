"""Offline source/frozen audit of the supplied task, with reviewable receipts."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def require(value, message):
    if not value:
        raise AssertionError(message)


def verify_overview(window, output, check, wait):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    page = window.studio_page
    timeline = page.timeline
    overview = page.timeline_overview
    saved = timeline.visible_start_ms, timeline.visible_duration_ms

    def verify(name):
        def refreshed():
            project, cues = overview._cues()
            return overview._marker_key == overview._key(project, cues)
        check(name+'_repainted', wait(refreshed))
        project, cues = overview._cues()
        left = timeline.visible_start_ms
        right = left + timeline.visible_duration_ms
        check(name+'_only_visible_cues', all(cue.end_ms > left and cue.start_ms < right for cue in cues))
        center = overview._track().center().x()
        check(name+'_ruler_alignment', abs(overview._ms(center)-timeline._x_to_time(center)) <= 1)
        check(name+'_screenshot', overview.grab().save(str(output/(name+'.png'))))

    for name, start, duration in [('overview-begin', 0, 60_000),
                                   ('overview-middle', 1_110_000, 60_000),
                                   ('overview-end', 2_640_000, 60_000)]:
        timeline.set_visible_window(start, duration)
        verify(name)
    duration = timeline.visible_duration_ms
    point = QPointF(timeline._time_to_x(timeline.visible_start_ms+duration//2), timeline.RULER_HEIGHT+20)
    event = QWheelEvent(point, QPointF(timeline.mapToGlobal(point.toPoint())), QPoint(), QPoint(0,120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(timeline, event)
    check('overview_control_wheel_zoom', timeline.visible_duration_ms < duration)
    verify('overview-zoomed')
    start = timeline.visible_start_ms
    event = QWheelEvent(point, QPointF(timeline.mapToGlobal(point.toPoint())), QPoint(), QPoint(-120,0),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.AltModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(timeline, event)
    check('overview_horizontal_wheel_moves_view', timeline.visible_start_ms > start)
    verify('overview-scrolled')
    left, duration = timeline.visible_start_ms, timeline.visible_duration_ms
    track = overview._track()
    point = QPoint(round(track.left()+track.width()*.75), round(track.center().y()))
    clicked_ms = overview._ms(point.x())
    QTest.mousePress(overview, Qt.MouseButton.LeftButton, pos=point)
    check('overview_press_anchors_visible_range', overview._drag_window == (left,duration))
    after_press = timeline.visible_start_ms
    QTest.mouseMove(overview, point)
    check('overview_drag_does_not_accumulate_pan', timeline.visible_start_ms == after_press)
    QTest.mouseRelease(overview, Qt.MouseButton.LeftButton, pos=point)
    check('overview_local_click_target', abs(timeline.visible_start_ms-(clicked_ms-duration//2)) <= 1)
    check('overview_local_click_stays_near_view', abs(timeline.visible_start_ms-left) <= duration//2)
    verify('overview-clicked')
    check('overview_window_screenshot', window.grab().save(str(output/'overview-window.png')))
    timeline.set_visible_window(*saved)


def main(output_directory):
    output = Path(output_directory).resolve()
    invoker = Path(os.environ.get("TWOBYTEASR_INVOKER_CWD") or Path.cwd()).resolve()
    if not output.is_relative_to(invoker/"tmp"):
        raise ValueError("Audit output must be under cwd/tmp")
    fixture_path = output/"fixture.json"
    fixture = json.loads(fixture_path.read_text("utf-8"))
    if fixture.get("audit_kind") == "recorded-grouping-task":
        from .recorded_grouping_audit import main as recorded_audit
        return recorded_audit(output, fixture)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output/"profile")
    from ..test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    import subtitle_core as core
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    from ..subtitle_rules.language_rules import language_scope
    from ..subtitle_rules import grouping
    from ..subtitle_rules.grouping_quality import BoundaryQuality, quality_for_segments, QUALITY_VERSION
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..recognition.pipeline_runtime import finalize_cues
    from ..projects.studio_project import project_from_runtime_cues,save_project,load_project
    from ..subtitle_rules import subtitle_translation as translation
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    from ..diagnostics.build_identity import load_build_identity
    from dataclasses import asdict

    result = dict(job_id=fixture["job_id"],original_response_policy=fixture.get("original_response_policy"),frozen=bool(getattr(sys,"frozen",False)),quality_version=QUALITY_VERSION,
        real_provider_requests=0,build_identity=asdict(load_build_identity()),checks=[],events=[],requests=[])
    response_mode = "normal"
    valid_boundaries = []
    saved_provider, saved_record = grouping.provider_for_stage, grouping.record_run_event
    saved_core_record = core.record_run_event

    def record(event, **data):
        result["events"].append(dict(event=event,**data))

    def complete(messages, **kwargs):
        body = json.loads(messages[1]["content"])
        result["requests"].append(dict(body=body,max_tokens=kwargs["max_tokens"],timeout=kwargs["timeout"]))
        if body.get("failed_constraints"):
            return '{"boundaries":[1]}'
        if body["source_text"]==fixture["source_text"]:
            return json.dumps(dict(boundaries=valid_boundaries if response_mode=="normal" else fixture["model_boundaries"]))
        if body["source_text"]=="先看左边再看右边":
            return '{"boundaries":[4,8]}'
        quality=BoundaryQuality(body["source_text"])
        cuts,_=quality.repair([quality.total])
        return json.dumps(dict(boundaries=cuts))

    def check(name, value):
        result["checks"].append(dict(name=name,passed=bool(value)))
        require(value,name)

    try:
        grouping.provider_for_stage=lambda *a,**k:SimpleNamespace(complete=complete)
        grouping.record_run_event=record
        core.record_run_event=record
        snapshot=resolve_provider_snapshot({"models":{"ai_service":"custom","provider_profiles":{
            "custom":{"base_url":"http://127.0.0.1:1/v1","model":"offline-fixture"}}}})
        context=RuntimeContext(task_language="zh",requested_language="zh",provider_snapshot=snapshot)
        rows=[core.SpeechSegment(r["id"],r["start"],r["end"],r["text"],.9,[],speaker=r["speaker"])
              for r in fixture["segments"]]
        with language_scope("zh"), activate_runtime_context(context,legacy=core):
            quality=quality_for_segments(rows,fixture["acoustic_tokens"])
            issues=quality.inspect(fixture["model_boundaries"])
            check("nineteen_raw_overlength_spans",sum(x["kind"]=="length" for x in issues)==19)
            check("620_original_acoustic_tokens",len(fixture["acoustic_tokens"])==620)
            valid_boundaries,_=quality.repair(fixture["model_boundaries"])
            started=time.perf_counter()
            normal=grouping.group_subtitles(rows,fixture["acoustic_tokens"],use_ai=True,
                                            provider_snapshot=snapshot,max_workers=1)
            result["normal"] = dict(elapsed_ms=(time.perf_counter()-started)*1000,
                                    requests=len(result["requests"]),extra_requests=0)
            check("normal_single_remote_round",normal.validated and len(result["requests"])==1)
            response_mode = "abnormal"
            result["events"].clear()
            request_start=len(result["requests"])
            started=time.perf_counter()
            cues=grouping.group_subtitles(rows,fixture["acoustic_tokens"],use_ai=True,
                                          provider_snapshot=snapshot,max_workers=1)
            grouping_elapsed=(time.perf_counter()-started)*1000
            grouped=copy.deepcopy(cues)
            finalized=finalize_cues(cues,rows,fixture["acoustic_tokens"],[],112.8666875,30,core)
            elapsed=(time.perf_counter()-started)*1000
            sample_requests=result["requests"][request_start:]
            result["abnormal"] = dict(elapsed_ms=grouping_elapsed,final_display_ms=elapsed-grouping_elapsed,requests=len(sample_requests),
                extra_requests=len(sample_requests)-1,
                extra_output_token_reserve=sum(x["max_tokens"] for x in sample_requests[1:]))
            check("raw_625_characters_exact", "".join(c.text for c in finalized)==fixture["source_text"])
            check("user_16_character_limit",all(core.display_length(c.text)<=16 for c in finalized))
            check("local_retry_budget",1 < len(sample_requests)<=3 and
                  all(len(x["body"]["source_text"])<=224 for x in sample_requests[1:]))
            check("all_display_phases_same_text",all(
                [r["text"] for r in e["cues"]]==[c.text for c in grouped]
                for e in result["events"] if e["event"]=="display_boundary_phase"))
            cursor=0
            boundaries=[]
            for cue in finalized:
                cursor+=core.display_length(cue.text)
                boundaries.append(cursor)
            for word in ("这场","虽然","但是","李妹","上一次","六代团","总体来说"):
                positions=[i for i in range(len(fixture["source_text"])) if fixture["source_text"].startswith(word,i)]
                check("intact_"+word,all(not a < b < a+len(word) for a in positions for b in boundaries))
            check("adversative_result_starts_next_clause",next(c for c in finalized if "结果" in c.text).text.startswith("结果"))
            project=project_from_runtime_cues(str(output/"fixture.mp4"),finalized,
                generation_metadata={"language":{"code":"zh"}},initialize_layout=False)
            project.generation_metadata[translation.RECORDS_KEY]=translation._empty_container("en")
            for cue in project.cues:
                translation.set_manual(project,cue.id,"Translation "+cue.id,target="en")
            project_path=save_project(project,output/"replay.2byteproj")
            reopened=load_project(project_path)
            check("project_reopen_text_and_source_spans",[c.text for c in reopened.cues]==[c.text for c in finalized]
                and reopened.generation_metadata["segmentation_source_spans"]==project.generation_metadata["segmentation_source_spans"])
            exported=export_language_layers(reopened,output/"srt","replay")
            layers={a.layer:parse_srt(a.path.read_text("utf-8"))[0] for a in exported.artifacts}
            check("srt_original_exact", "".join(c.text for c in layers["original"])==fixture["source_text"])
            check("translation_stable_ids",[c.text for c in layers["translation"]]==["Translation "+c.id for c in reopened.cues])
            check("srt_timeline_equals_reopened_project",[(c.start_ms,c.end_ms) for c in layers["original"]]
                  ==[(c.start_ms,c.end_ms) for c in reopened.cues])
            from ..providers.provider_input_budget import prepare_input,InputBudgetError
            long_text="先看左边然后继续向右移动"*350
            long_source=[core.SpeechSegment(77,0,len(long_text)*.13,long_text,.9,[],speaker="A")]
            messages=grouping.call_grouping_api(long_source,provider_snapshot=snapshot,_messages_only=True)
            rejected=False
            try:
                prepare_input(messages,schema=grouping.GROUPING_SCHEMA,max_tokens=snapshot.max_output_tokens,operation="group")
            except InputBudgetError:
                rejected=True
            check("singleton_actually_exceeds_request_budget",rejected)
            request_start=len(result["requests"])
            from ..subtitle_rules.grouping_quality_request import QualityRetryBudget
            long_result=grouping.call_grouping_api(long_source,provider_snapshot=snapshot,
                _quality_budget=QualityRetryBudget(requests=0))
            owned_requests=[r for r in result["requests"][request_start:] if r["body"].get("segments")]
            check("oversized_singleton_enters_multiple_AI_requests",len(owned_requests)>1)
            check("request_context_is_not_duplicated", "".join(r["body"]["source_text"] for r in owned_requests)==long_text)
            check("oversized_result_exact_and_bounded", "".join(c.text for c in long_result)==long_text
                  and all(core.display_length(c.text)<=16 for c in long_result))
            result["oversized"] = dict(requests=len(owned_requests),characters=len(long_text),
                children=[r["body"]["segments"][0]["source_mapping"] for r in owned_requests])
            result.update(source_segments=fixture["segments"],model_boundaries=fixture["model_boundaries"],
                model_texts=fixture["model_texts"],previous_repairs=fixture["previous_repairs"],
                final_cues=core.serialize_cues(finalized),project=str(project_path),
                evidence_limits=fixture["evidence_limits"],passed=True)
    except Exception as exc:
        import traceback
        result.update(passed=False,error=str(exc),traceback=traceback.format_exc())
    finally:
        grouping.provider_for_stage=saved_provider
        grouping.record_run_event=saved_record
        core.record_run_event=saved_core_record
    (output/"comparison.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if result.get("passed") else 1


def start(window, output):
    """Normal Studio entry, real prepared previews and window captures."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture

    def run():
        result=dict(passed=False,frozen=bool(getattr(sys,"frozen",False)),checks=[])
        def check(name, condition):
            result["checks"].append(dict(name=name,passed=bool(condition)))
            require(condition,name)
        def pump():
            QApplication.processEvents()
            time.sleep(.01)
        def wait(predicate,seconds=35):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                pump()
                if predicate():
                    return True
            return False
        page=window.studio_page
        try:
            from ..diagnostics.build_identity import load_build_identity
            from ..projects.studio_project import load_project
            result["identity"]=load_build_identity().to_dict()
            expected=load_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"])
            window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"],
                                       mode="edit",source="canonical")
            check("normal_project_ready",wait(lambda:page.project is not None and page._project_view_state=="open"))
            def visibly_ready():
                session=getattr(window,"_studio_loading_session",None)
                return (page.isVisible() and page.timeline.isVisible() and (session is None or
                    session.state=="ready" and not session.view.isVisible()))
            check("loading_cover_released_and_workbench_visible",wait(visibly_ready,80))
            page.video.set_paused(True)
            if page.video.controller is not None:
                page.video.controller.post_set_volume(0)
            check("all_Studio_text_matches_saved_project",[c.text for c in page.project.cues]==[c.text for c in expected.cues])
            page.timeline.set_subtitle_layer("original")
            terms=json.loads(os.environ.get('TWOBYTEASR_GROUPING_PREVIEW_TERMS',
                '["虽然","结果","上一次","六代团","总体来说"]'))
            examples=[c for c in expected.cues if any(w in c.text for w in terms)]
            check('requested_preview_examples_exist',bool(examples))
            if os.environ.get('TWOBYTEASR_GROUPING_FIRST_PER_TERM') == '1':
                examples=[]
                for term in terms:
                    matches=[cue for cue in expected.cues if term in cue.text]
                    check('preview_term_exists_'+term,bool(matches))
                    if matches[0] not in examples:
                        examples.append(matches[0])
            result['preview_examples']=[dict(id=cue.id,text=cue.text,start_ms=cue.start_ms) for cue in examples]
            for index,cue in enumerate(examples):
                page.select_cue(cue.id)
                page._seek((cue.start_ms+50)/1000.)
                def ready():
                    prepared=page._prepared_caption(cue.id)
                    return prepared is not None and prepared.snapshot.text==cue.text
                check("prepared_preview_"+cue.id,wait(ready))
                deadline=time.monotonic()+.5
                while time.monotonic()<deadline:
                    pump()
                _capture(window,output/f"preview-{index}.png")
            check("all_cue_ids_stable",[c.id for c in page.project.cues]==[c.id for c in expected.cues])
            if os.environ.get('TWOBYTEASR_GROUPING_VIEWPORT_AUDIT') == '1':
                verify_overview(window, output, check, wait)
            if os.environ.get('TWOBYTEASR_GROUPING_TASK_PHASE_AUDIT')=='1':
                page._recognition_running=True
                page._recognition_subtitle_task=None
                page.set_recognition_runtime_stage('断句：模型处理','离线固定响应')
                task=page._recognition_subtitle_task
                for label in ('断句：本地断点检查','断句：局部重试未变化','断句：最终字幕验证'):
                    page._record_recognition_task_event('pipeline_work_progress',dict(label=label,state='completed'))
                    check('task_phase_'+label,task.phase==label)
                page._record_recognition_task_event('grouping_quality_retry',dict(outcome='unchanged',improved=False))
                check('unchanged_retry_is_not_improvement',task.rows['source']['activity']['grouping_quality_retry']['improved'] is False)
                page._record_recognition_task_event('FIRERED_ALIGNMENT_STATUS',dict(status='degraded',counts={'aligned':9,'failed_or_unavailable':1},
                    reason='部分 FireRed 窗口没有真实字级对齐；已隔离估计时间，保留转写文本。'))
                page._finish_recognition_subtitle_task('suggestion','结果已交付，时间证据需检查')
                page._recognition_running=False
                check('alignment_degradation_remains_reviewable',task.counts()['review']==1)
                page.subtitle_tasks_button.click()
                check('task_panel_visible',wait(lambda:page._subtitle_task_panel().isVisible()))
                _capture(page._subtitle_task_panel(),output/'task-progress.png')
                page._subtitle_task_panel().hide()
            result["passed"]=True
        except Exception as exc:
            import traceback
            result.update(error=str(exc),traceback=traceback.format_exc())
        finally:
            if page.project is not None:
                page.undo_stack.setClean()
                page.project_dirty=False
            (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            window.close()
    QTimer.singleShot(1500,run)
