"""Normal-window checks of the user's three handoffs using a private project."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    deadline=time.monotonic()+60
    def execute():
        page=getattr(window,'_studio_page_instance',None)
        if (page is None or page.project is None) and time.monotonic()<deadline:
            QTimer.singleShot(100,execute)
            return
        code = 1
        try:
            code = run(window, output)
        except Exception:
            (output/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        finally:
            if window.studio_page.project:
                window.studio_page.undo_stack.setClean()
            window.close()
            QApplication.instance().exit(code)
    QTimer.singleShot(800, execute)


def run(window, output):
    from PySide6.QtWidgets import QApplication
    from ..projects.studio_project import load_project, save_project
    from ..caption_style.collision_layout import project_layout_schedule
    from ..studio.display_handoff_ui import bridge_short_gaps
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    from ..diagnostics.build_identity import load_build_identity
    from .blank_project_audit import _capture
    from ..test_isolation import install_pytest_network_guard
    install_pytest_network_guard()
    checks = []
    result = dict(checks=checks, identity=load_build_identity().to_dict(), executable=sys.executable,
                  modules={}, samples=[])
    def persist():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        persist()
        if not value:
            raise AssertionError(name+' '+str(detail))
    def pump(seconds=.1):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            QApplication.processEvents()
            time.sleep(.005)
    def wait(predicate, seconds=30):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            pump(.03)
            if predicate():
                return True
        return False
    try:
        original=load_project(output/'input.2byteproj')
        check('normal_studio_constructed',wait(lambda:getattr(window,'_studio_page_instance',None) is not None))
        page=window._studio_page_instance
        check('normal_project_ready',wait(lambda:page.project is not None and len(page.project.cues)==len(original.cues)))
        def studio_visible():
            session=getattr(window,'_studio_loading_session',None)
            return session is None or (not session.active and not session.view.isVisible())
        check('normal_studio_visible',wait(studio_visible,45))
        page.video.set_paused(True)
        project=page.project
        before=copy.deepcopy(project.cues)
        evidence=copy.deepcopy(project.asr_evidence)
        previous=next(c for c in project.cues if c.text=='是的' and 86000<c.start_ms<87500)
        following=next(c for c in project.cues if c.text=='八连击的月光合奏')
        reply=next(c for c in project.cues if c.text=='好' and 87000<c.start_ms<87500)
        check('screenshot_three_input', [previous.end_ms,reply.start_ms,following.start_ms]==[87133,87133,87233])
        page.select_cue(reply.id)
        count=bridge_short_gaps(page)
        check('existing_bridge_action_changes_project',count>0,count)
        check('core_actual_100ms_display_hold',previous.end_ms==following.start_ms==87233)
        check('reply_timing_retained',(reply.start_ms,reply.end_ms)==(87133,87450))
        check('raw_text_speaker_and_speech_evidence',
              [(c.id,c.text,c.speaker_id) for c in project.cues]==[(c.id,c.text,c.speaker_id) for c in before]
              and project.asr_evidence==evidence)
        plan=project_layout_schedule(project)
        check('core_chain_keeps_position',plan[previous.id][0][2]==plan[following.id][0][2])
        check('reply_uses_other_position',plan[reply.id][0][2]!=plan[previous.id][0][2])
        result['core']=dict(before=[(c.id,c.start_ms,c.end_ms) for c in before if c.id in {previous.id,following.id,reply.id}],
                           after=[(c.id,c.start_ms,c.end_ms,plan[c.id][0][2]) for c in (previous,reply,following)])
        page.undo_stack.undo()
        check('one_step_undo',project.cues==before)
        page.undo_stack.redo()
        check('one_step_redo',previous.end_ms==87233)
        saved=save_project(project,output/'repaired.2byteproj')
        reopened=load_project(saved)
        check('saved_reopened_intervals',reopened.cues==project.cues)
        check('saved_reopened_layout',project_layout_schedule(reopened)==plan)
        artifacts=export_language_layers(reopened,output/'subtitles','continuity',layers=('original',))
        subtitles=parse_srt(artifacts.artifacts[0].path.read_text(encoding='utf-8'))[0]
        from ..caption_style.speaker_names import display_text_cues
        displayed=display_text_cues(reopened,reopened.cues)
        check('srt_display_times_and_text',[(c.start_ms,c.end_ms,c.text) for c in subtitles]
              ==[(c.start_ms,c.end_ms,c.text) for c in displayed])
        # The same source identity and geometry are requested through the
        # actual caption preparation worker, including manually styled cues.
        for index,ms in enumerate((14509,47000,87200,87262,87500,87000,87262)):
            page._seek(ms/1000)
            pump(.15)
            active=[c for c in page.project.cues if c.start_ms<=ms<c.end_ms]
            cache=page._caption_playback_cache
            geometry=getattr(page,'_caption_tick_geometry',None) or page._advanced_preview_size()
            cache.prepare(page._revision_store.render,[c.id for c in active],*geometry,merge=True)
            ready=wait(lambda:all(page._prepared_caption(c.id) is not None for c in active))
            failures={c.id:str(cache.failure(page._revision_store.render,c.id,*geometry)) for c in active}
            check('actual_prepared_'+str(ms),ready,dict(active=[c.id for c in active],failures=failures,stats=cache.stats()))
            check('actual_frame_has_captions_'+str(ms),bool(active))
            def seek_presented():
                preparation=getattr(page,'_caption_seek_preparation',None)
                return not page.video.playback_position_snapshot().seeking and (
                    preparation is None or preparation.pending is None)
            check('actual_seek_completed_'+str(ms),wait(seek_presented))
            sample=page._caption_sample_ms()
            expected_ids={c.id for c in project.cues if c.start_ms<=sample<c.end_ms}
            def scene_ready():
                scene=getattr(page,'_caption_scene',None)
                if scene is None:
                    return False
                trace=scene.trace()
                return trace.get('visible') and set(trace.get('rendered_cue_ids',()))==expected_ids
            check('actual_scene_visible_'+str(ms),wait(scene_ready),dict(sample_ms=float(sample),expected=sorted(expected_ids),
                trace=page._caption_scene.trace()))
            pump(.2)
            _capture(window,output/f'preview-{index}-{ms}.png')
            result['samples'].append(dict(ms=ms,active=[c.id for c in active],
                offsets={c.id:plan[c.id][0][2] for c in active}))
        # A normal-speed interval includes both sides of the core handoff.
        page._seek(86.6)
        pump(.2)
        page.video.set_paused(False)
        pump(2.5)
        page.video.set_paused(True)
        check('normal_speed_crossed_core_handoff',page.timeline.playhead_ms>88100,page.timeline.playhead_ms)
        for name in ('twobyteasr.subtitle_rules.display_timing','twobyteasr.subtitle_rules.display_continuity',
                     'twobyteasr.caption_style.collision_layout','twobyteasr.caption_style.continuity_layout'):
            module=sys.modules.get(name)
            path=Path(module.__file__) if module and getattr(module,'__file__',None) else None
            result['modules'][name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None)
        result['passed']=all(item['passed'] for item in checks)
        persist()
        return 0
    except Exception:
        result['error']=traceback.format_exc()
        result['passed']=False
        _capture(window,output/'failure.png')
        persist()
        raise
