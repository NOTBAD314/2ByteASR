"""Normal MainWindow / same-EXE audit of the fixed ace6 handoff project."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        code=1
        try:
            code=run(window,output)
        except Exception:
            (output/'error.txt').write_text(traceback.format_exc(),'utf-8')
        finally:
            page=getattr(window,'_studio_page_instance',None)
            if page and page.project:
                page.undo_stack.setClean()
            window.close()
    QTimer.singleShot(800,execute)


def run(window,output):
    from PySide6.QtWidgets import QApplication
    from ..projects.studio_project import load_project,save_project
    from ..caption_style.collision_layout import project_layout_schedule
    from ..subtitle_rules.studio_review import store_review_risks
    from ..subtitle_rules.current_issues import current_issue_view
    from ..exports.studio_subtitle_export import export_language_layers
    from ..exports.srt_codec import parse_srt
    from ..rendering.ass_compiler import compile_ass
    from ..exports.studio_render import RenderJob,RenderSettings,run_render_job
    from ..runtime_paths import detect_install_root
    from ..diagnostics.build_identity import load_build_identity
    from ..system.processes import run_hidden_subprocess
    from .blank_project_audit import _capture
    checks=[]
    result=dict(checks=checks,identity=load_build_identity().to_dict(),executable=sys.executable,pid=os.getpid())
    def persist():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail));persist()
        if not value:raise AssertionError(name+' '+str(detail))
    def pump(seconds=.1):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            QApplication.processEvents();time.sleep(.005)
    def wait(predicate,seconds=45):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            pump(.03)
            if predicate():return True
        return False
    try:
        check('normal_studio_ready',wait(lambda:getattr(window,'_studio_page_instance',None) is not None
              and window._studio_page_instance.project is not None))
        page=window._studio_page_instance
        check('normal_loading_finished',wait(lambda:not getattr(window,'_studio_loading_session',None)
              or not window._studio_loading_session.active))
        page.video.set_paused(True)
        p=page.project;original=load_project(output/'input.2byteproj')
        a=next(c for c in p.cues if c.text=='和这个月光合作的一个博弈了')
        b=next(c for c in p.cues if c.text=='我真觉得可以开香槟了')
        check('normal_open_applied_117ms_display_choice',[a.start_ms,a.end_ms,b.start_ms,b.end_ms]==[109200,111033,111033,113117])
        check('immutable_asr_and_texts',p.asr_evidence==original.asr_evidence and
              [(c.id,c.text,c.speaker_id) for c in p.cues]==[(c.id,c.text,c.speaker_id) for c in original.cues])
        plan=project_layout_schedule(p)
        check('incoming_first_frame_uses_baseline',plan[b.id]==[(111033,113117,0.)],plan[b.id])
        result['handoff']=dict(outgoing=[a.start_ms,a.end_ms],incoming=[b.start_ms,b.end_ms],offset=plan[b.id][0][2],receipt=a.transform['display_handoff'])
        yes=next(c for c in p.cues if c.text=='是的' and 86000<c.start_ms<87500)
        eight=next(c for c in p.cues if c.text=='八连击的月光合奏')
        good=next(c for c in p.cues if c.text=='好' and 87000<c.start_ms<87500)
        check('previous_100ms_bridge_retained',yes.end_ms==eight.start_ms==87233)
        check('previous_chain_and_reply_slots_retained',plan[yes.id][0][2]==plan[eight.id][0][2]
              and plan[good.id][0][2]!=plan[yes.id][0][2])
        for index,ms in enumerate((111034,111192,112000,111192)):
            page._seek(ms/1000);pump(.2)
            active=[c for c in p.cues if c.start_ms<=ms<c.end_ms]
            cache=page._caption_playback_cache
            geometry=getattr(page,'_caption_tick_geometry',None) or page._advanced_preview_size()
            cache.prepare(page._revision_store.render,[c.id for c in active],*geometry,merge=True)
            check('actual_caption_prepared_'+str(index),wait(lambda:all(page._prepared_caption(c.id) is not None for c in active)))
            check('actual_seek_settled_'+str(index),wait(lambda:not page.video.playback_position_snapshot().seeking))
            check('handoff_scene_active_'+str(index),b.id in {c.id for c in active} and a.id not in {c.id for c in active})
            _capture(window,output/f'preview-{index}-{ms}.png')
        page._seek(109.8);pump(.3);page.video.set_paused(False);pump(2.2);page.video.set_paused(True)
        check('normal_speed_crossed_handoff',page.timeline.playhead_ms>111300,page.timeline.playhead_ms)
        # Formal GUI save, with its real background persistence completion.
        saved=[]
        page.save(on_finished=lambda *args,**kwargs:saved.append((args,kwargs)))
        check('normal_formal_save_completed',wait(lambda:bool(saved),60),saved)
        reopened=load_project(output/'input.2byteproj')
        check('formal_save_reopen_times_and_plan',[(c.id,c.start_ms,c.end_ms) for c in reopened.cues]
              ==[(c.id,c.start_ms,c.end_ms) for c in p.cues] and project_layout_schedule(reopened)==plan)
        save_project(p,output/'repaired.2byteproj')
        artifacts=export_language_layers(reopened,output/'subtitles','handoff',layers=('original',))
        subtitles=parse_srt(artifacts.artifacts[0].path.read_text('utf-8'))[0]
        check('srt_common_boundary',any(c.start_ms==111033 and c.end_ms==113117 for c in subtitles))
        ass=output/'handoff.ass';ass.write_text(compile_ass(reopened),'utf-8-sig')
        check('ass_includes_incoming',b.text in ass.read_text('utf-8-sig'))
        store_review_risks(p);view=current_issue_view(p)
        result['qc']=dict(counts=view.counts(),totals=view.totals(),rules=view.statistics())
        check('qc_counts_share_current_snapshot',sum(view.counts().values())==len(view.by_cue)
              and view.totals()['issues']==sum(len(rows) for rows in view.by_cue.values()))
        page._refresh_cue_list_summary()
        check('explicit_cue_and_issue_count_visible','34 条字幕，包含 34 个问题点' in page.bulk_review_hint.text(),page.bulk_review_hint.text())
        _capture(window,output/'review-counts.png')
        root=detect_install_root();ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
        video=run_render_job(ffmpeg,RenderJob(p.media.path,str(ass),str(output/'handoff.mp4'),
            settings=RenderSettings(encoder='libx264',preset='ultrafast',width=960,height=540,fps=60,
                                   audio_codec='aac',font_directory=str(root/'assets/fonts')),
            start_seconds=109,duration_seconds=4.2,overwrite_existing=True))
        check('production_video_export',video.is_file())
        for index,at in enumerate((2.034,2.192,3.0)):
            frame=output/f'export-{index}.png'
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss',str(at),'-i',str(video),'-frames:v','1',str(frame)],
                check=True,capture_output=True,timeout=25,purpose='handoff actual decoded export')
            check('video_decoded_'+str(index),frame.is_file() and frame.stat().st_size>1000)
        # The existing explicit preview must describe the same editorial
        # choice and keep the original word clock through undo/redo.
        from ..projects.studio_runtime_state import state_for,DirtyDomain
        from ..studio.display_handoff_ui import DisplayHandoffPreview
        p.generation_metadata['display_overlap_audit']={'status':'user_undone'}
        with state_for(p).transaction(p,action_id='audit_original_boundary',dirty=DirtyDomain.CUE_TIMING,affected_cue_ids=(a.id,)):
            a.end_ms=111150
        before_words=copy.deepcopy(p.studio_state.get('caption_timeline',{}))
        dialog=DisplayHandoffPreview(page)
        row=next(i for i in range(dialog.table.rowCount()) if dialog.table.item(i,0).text()==a.id)
        check('preview_names_editorial_choice','编辑显示顺接' in dialog.table.item(row,4).text())
        dialog.show();pump(.2);_capture(dialog,output/'editorial-preview.png')
        check('preview_actually_visible',dialog.isVisible())
        dialog.apply()
        check('preview_apply_keeps_evidence',a.end_ms==111033 and p.asr_evidence==original.asr_evidence
              and a.transform['display_handoff']['acoustic_overlap_claim']=='unchanged')
        page.undo_stack.undo()
        check('preview_undo_respects_manual_keep',a.end_ms==111150)
        page.undo_stack.redo()
        check('preview_redo_keeps_word_clock',a.end_ms==111033 and p.studio_state.get('caption_timeline',{})==before_words)
        # Replay the original four answers inside this same running executable.
        # Source/compiled identity is checked separately by Build Truth.
        from scripts.verify_handoff_ai_replay import run as replay
        check('same_exe_recorded_grouping_entry',replay(output/'recorded-replay',fixture_path=output/'fixture.json')==0)
        replayed=json.loads((output/'recorded-replay/replay.json').read_text('utf-8'))
        for name,passed in replayed['checks'].items():
            check('same_exe_'+name,passed)
        result['passed']=all(c['passed'] for c in checks);persist();return 0
    except Exception:
        result['passed']=False;result['error']=traceback.format_exc()
        _capture(window,output/'failure.png');persist();raise
