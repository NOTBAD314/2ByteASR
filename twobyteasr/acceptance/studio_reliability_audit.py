"""Opt-in real-window/frozen verification on copied projects; no providers."""
from pathlib import Path
import copy
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import zipfile


def start(window, output):
    from PySide6.QtCore import Qt, QTimer, QMimeData
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..projects.studio_runtime_state import state_for
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture
    if window.built_page('studio') is None:
        QTimer.singleShot(100,lambda:start(window,output));return
    output=Path(output);page=window.studio_page
    clipboard=QApplication.clipboard();original_clipboard=QMimeData()
    current_mime=clipboard.mimeData()
    if current_mime is not None:
        for kind in current_mime.formats():original_clipboard.setData(kind,current_mime.data(kind))
    result=dict(passed=False,checks=[],pid=os.getpid(),executable=sys.executable,
                identity=load_build_identity().to_dict(),frozen=bool(getattr(sys,'frozen',False)))
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save();require(value,name)
    def wait(predicate,seconds=90):
        until=time.perf_counter()+seconds
        while time.perf_counter()<until and not predicate():
            QApplication.processEvents()
            time.sleep(.02)  # Release Python's GIL while export/decode workers run.
        require(predicate(),'reliability wait timed out')
    def capture(name):
        QTest.qWait(80)
        _capture(window,output/(name+'.png'))
        page.subtitle_edit_card.grab().save(str(output/(name+'-editor.png')))
    def run():
        diagnostic=None
        try:
            wait(lambda:page.project is not None and page._readiness.ready and not page._readiness.active)
            page.video.set_paused(True);page.volume_slider.setValue(0)
            p=page.project
            result['project']=dict(cues=len(p.cues),translations=len(p.generation_metadata.get('translations',{})),
                dpr=window.devicePixelRatioF(),size=[window.width(),window.height()])
            cue=next(c for c in p.cues if c.start_ms>10000 and p.generation_metadata.get('translations',{}).get(c.id))
            cue_id=cue.id;other=next(c for c in p.cues if c.id!=cue_id)
            original=cue.text;locks=set(page.timeline.locked_speakers)
            page._seek((cue.start_ms+80)/1000);QTest.qWait(500)
            def open_editor(layer='original'):
                if os.environ.get('TWOBYTEASR_CAPTION_INTEGRITY_AUDIT')=='1':
                    from .caption_integrity_audit import open_from_list
                    open_from_list(page,cue_id,layer)
                else:page._open_caption_editor(cue_id,layer)
                wait(lambda:page._caption_draft is not None)
                return page.subtitle_edit_input
            editor=open_editor();session_id=page._caption_draft.edit_session_id
            check('raw_baseline_not_display_projection',editor.toPlainText()==original)
            edited=original+' [可靠保存]'
            editor.setPlainText(edited)
            page.select_cue(other.id);page._seek((other.start_ms+50)/1000)
            page.cue_controller.set_text(other.id,other.text+' [另一条变化]')
            p.cues=copy.deepcopy(p.cues);state_for(p).reindex_cues(p)
            page._seek((next(c for c in p.cues if c.id==cue_id).start_ms+80)/1000)
            began=time.perf_counter();QTest.keyClick(editor,Qt.Key.Key_Return)
            check('bound_edit_after_seek_selection_rebuild',next(c for c in p.cues if c.id==cue_id).text==edited)
            check('confirmation_closes_after_disk',page._caption_draft is None and not page.subtitle_edit_dock.isVisible())
            check('persisted_first_target',next(c for c in load_project(page.project_path).cues if c.id==cue_id).text==edited)
            check('duplicate_confirmation_is_idle',page._commit_canvas_inline_edit() is False and next(c for c in p.cues if c.id==cue_id).text==edited)
            from ..subtitle_rules.punctuation_style import style_cues
            displayed=style_cues(p,[next(c for c in p.cues if c.id==cue_id)])[0].text
            wait(lambda:page._prepared_caption(cue_id) is not None and page._prepared_caption(cue_id).snapshot.text==displayed,30)
            result['commit_key_and_preview_ms']=(time.perf_counter()-began)*1000
            capture('saved-original')
            page.undo_stack.undo();check('undo_preserves_other_edit',next(c for c in p.cues if c.id==cue_id).text==original)
            page.undo_stack.redo();check('redo_restores_text',next(c for c in p.cues if c.id==cue_id).text==edited)
            editor=open_editor();editor.setPlainText('保留我的草稿')
            page.cue_controller.set_text(cue_id,edited+' [并发修改]')
            QTest.mouseClick(page.caption_confirm_button,Qt.MouseButton.LeftButton)
            check('real_conflict_retains_draft',page._caption_draft is not None and editor.toPlainText()=='保留我的草稿')
            check('conflict_has_specific_code','text_conflict' in page.subtitle_edit_card.error_detail.text())
            capture('text-conflict')
            QTest.mouseClick(page.subtitle_edit_card.reload_current_button,Qt.MouseButton.LeftButton)
            check('explicit_rebase_copies_draft',QApplication.clipboard().text()=='保留我的草稿' and editor.toPlainText()==edited+' [并发修改]')
            page._cancel_canvas_inline_edit()
            editor=open_editor();editor.setPlainText(edited+' [解锁保存]')
            track=next(c for c in p.cues if c.id==cue_id).speaker_id
            page.timeline.locked_speakers.add(track)
            QTest.mouseClick(page.caption_confirm_button,Qt.MouseButton.LeftButton)
            check('current_track_lock_is_retryable',page._caption_draft is not None and 'track_locked' in page.subtitle_edit_card.error_detail.text())
            page.timeline.locked_speakers.discard(track)
            QTest.mouseClick(page.caption_confirm_button,Qt.MouseButton.LeftButton)
            check('unlock_saves_existing_draft',page._caption_draft is None and next(c for c in p.cues if c.id==cue_id).text.endswith('[解锁保存]'))
            editor=open_editor('translation');translated=editor.toPlainText()+'（译文验收）'
            editor.setPlainText(translated)
            other_track=next((c.speaker_id for c in p.cues if c.speaker_id!=track),'unrelated-track')
            page.timeline.locked_speakers.add(other_track)
            QTest.keyClick(editor,Qt.Key.Key_R,Qt.KeyboardModifier.ShiftModifier)
            check('other_track_lock_does_not_block_translation',page._caption_draft is None and p.generation_metadata['translations'][cue_id]==translated)
            page.timeline.locked_speakers=locks
            page.save();saved_path=page.project_path
            reopened=load_project(saved_path)
            check('original_and_translation_saved_together',reopened.generation_metadata['translations'][cue_id]==translated
                  and next(c for c in reopened.cues if c.id==cue_id).text.endswith('[解锁保存]'))
            page.undo_stack.setClean();page._close_project_session('reliability-reopen');page.open_project(saved_path)
            wait(lambda:page.project is not None and page.project is not p and page._readiness.ready)
            check('normal_project_reopen_preserves_text',page.project.generation_metadata['translations'][cue_id]==translated)
            joint=None
            if os.environ.get('TWOBYTEASR_CAPTION_INTEGRITY_AUDIT')=='1':
                from .caption_integrity_audit import check_dismissal
                joint=check_dismissal(page,output,check,capture)
            # Production renderer executes on the same kind of worker as the
            # export page; the GUI continues pumping events throughout.
            worker_result={}
            def export():
                try:
                    worker_result.update(_export_cases(output))
                    if joint is not None:
                        from .caption_integrity_audit import export_same_project
                        worker_result.update(export_same_project(joint,output))
                        if os.environ.get('TWOBYTEASR_FULL_STATIC_AUDIT')=='1':
                            from .caption_integrity_audit import export_full_static
                            worker_result.update(export_full_static(joint,output))
                except BaseException:worker_result['error']=traceback.format_exc()
            worker=threading.Thread(target=export,name='studio-export-reliability');worker.start()
            wait(lambda:not worker.is_alive(),2000 if os.environ.get('TWOBYTEASR_FULL_STATIC_AUDIT')=='1' else 300)
            result['exports']=worker_result
            check('production_static_export_complete',not worker_result.get('error') and worker_result.get('static_frames')==180,worker_result.get('error'))
            check('production_export_visible_languages',worker_result.get('visible_bands',0)==3)
            if joint is not None:check('joint_cancel_saved_project_exports',worker_result.get('joint_frames')==240,worker_result.get('error'))
            if os.environ.get('TWOBYTEASR_FULL_STATIC_AUDIT')=='1':
                check('full_1397_static_1740s_export',worker_result.get('full_frames')==52200,worker_result.get('error'))
            if result['frozen']:
                check('production_motion_export_complete',worker_result.get('motion_frames')==180,worker_result.get('motion_status'))
            from ..diagnostics.support_dialog import open_support_dialog
            diagnostic=open_support_dialog(window,page)
            wait(lambda:not diagnostic._loading and diagnostic._analysis is not None,40)
            diagnostic._export_to(str(output/'diagnostic.zip'))
            wait(lambda:not diagnostic._exporting,40)
            check('diagnostic_export_completed',not (diagnostic._result or {}).get('error'),diagnostic._result)
            with zipfile.ZipFile(output/'diagnostic.zip') as archive:
                check('diagnostic_zip_opens',archive.testzip() is None)
                rows=[json.loads(line) for line in archive.read('events.jsonl').splitlines()]
                related=[r for r in rows if r.get('edit_session_id')==session_id]
                check('diagnostic_has_edit_correlation',any(r['event_name']=='caption.edit.open' for r in related)
                      and any(r['event_name']=='caption.edit.result' for r in related)
                      and any(r['event_name']=='caption.persistence' for r in related))
                check('diagnostic_has_specific_rejections',any(r.get('reason_code')=='text_conflict' for r in rows)
                      and any(r.get('reason_code')=='track_locked' for r in rows))
                check('diagnostic_has_export_job',any(r.get('event_name')=='video.export.completed' and r.get('task_id') for r in rows))
                check('diagnostic_has_export_manifest',any(name.startswith('exports/') for name in archive.namelist()))
                check('diagnostic_defaults_exclude_bodies', 'selected-content.json' not in archive.namelist())
            _capture(diagnostic,output/'diagnostic-dialog.png')
            diagnostic.close();diagnostic=None
            result['passed']=all(c['passed'] for c in result['checks'])
        except BaseException:result['error']=traceback.format_exc()
        finally:
            if clipboard.ownsClipboard() and clipboard.text()=='保留我的草稿':clipboard.setMimeData(original_clipboard)
            if diagnostic is not None:diagnostic.close()
            save()
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
            if page._caption_draft is not None:page._cancel_canvas_inline_edit()
            page.undo_stack.setClean()
            window.result_exit_code=0 if result['passed'] else 1
            window.close()
    QTimer.singleShot(300,run)


def _export_cases(output):
    import av
    import numpy as np
    from ..projects.studio_project import StudioCue,StudioMedia,SubtitleStyle,SubtitleProject
    from ..exports.studio_render import RenderJob,RenderSettings
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..system.processes import run_hidden_subprocess
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';media=output/'export-source.mp4'
    run_hidden_subprocess([ffmpeg,'-v','error','-f','lavfi','-i','color=c=0x202020:s=640x360:r=30:d=6',
                           '-c:v','libx264','-threads','2',media],check=True,timeout=40,purpose='reliability export fixture')
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=6000,width=640,height=360),
        styles=[SubtitleStyle('g','审查样式',font_family='Source Han Sans SC',font_size=90)],
        cues=[StudioCue('export-'+str(i),i*2000,(i+1)*2000,text,style_id='g') for i,text in enumerate(
            ('Original one','Original two\nwith line break','Final original'))],
        generation_metadata={'translations':{'export-0':'第一条译文','export-1':'第二条译文，含换行','export-2':'最后一条译文'}},
        studio_state={'bilingual':{'mode':'bilingual','layout':'ink_v1'},'bilingual_mode':True})
    project.style_recipes['g']={'name':'验收渐变','engine':'remotion','motion':{'mode':'none'},'colors':{'fill':{
        'type':'linear-gradient','stops':[{'position':0,'color':'#FFFF6060'},{'position':1,'color':'#FFFFD060'}]}}}
    traces=[]
    job=RenderJob(str(media),str(output/'native.ass'),str(output/'static-complete.mp4'),
                  RenderSettings(encoder='libx264',preset='ultrafast',width=640,height=360,fps=30,audio_codec='none'),duration_seconds=6)
    AdvancedRendererBackend().render(project,ffmpeg,job,trace=lambda name,data:traces.append((name,data)))
    frames=list(av.open(job.output_path).decode(video=0));visible=0
    from PySide6.QtGui import QImage
    from ..caption_style.bilingual_layout import materialize_display_project
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.advanced_live_renderer import render_live_snapshot
    from .studio_acceptance_audit import require
    display=materialize_display_project(project);masks={}
    for cue in display.cues:
        snapshot=build_visual_cue_snapshot(display,cue.id,width=640,height=360,resolved_cue=cue)
        preview=render_live_snapshot(snapshot,width=640,height=360).convertToFormat(QImage.Format_RGBA8888)
        pixels=np.ndarray((preview.height(),preview.width(),4),np.uint8,buffer=preview.constBits(),strides=(preview.bytesPerLine(),4,1))
        masks[cue.id]=((pixels[:,:,0]>100)&(pixels[:,:,0]>pixels[:,:,2].astype(int)+20)&(pixels[:,:,3]>32)).copy()
        require(int(masks[cue.id].sum())>5,'preview language layer has no expected colored glyphs')
    coverage=[]
    for index,frame in enumerate(frames):
        rgb=frame.to_ndarray(format='rgb24').astype(int)
        actual=(rgb[:,:,0]>100)&(rgb[:,:,0]>rgb[:,:,2]+20)
        for cue in display.cues:
            if cue.start_ms<=index*1000/30<cue.end_ms:
                expected=masks[cue.id]
                ratio=float((actual&expected).sum()/max(1,expected.sum()))
                coverage.append(ratio);require(ratio>.6,'export lost or moved original/translation glyphs')
    for index in (25,85,145):
        rgb=frames[index].to_ndarray(format='rgb24').astype(int)
        mask=(rgb[:,:,0]>100)&(rgb[:,:,0]>rgb[:,:,2]+20)
        bands=np.flatnonzero(np.any(mask,axis=1));visible+=int(len(bands)>8)
        frames[index].to_image().save(output/f'export-frame-{index}.png')
    (output/'export-traces.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2,default=str),'utf8')
    result=dict(static_frames=len(frames),visible_bands=visible,language_layers_verified=len(masks),
        minimum_preview_ink_coverage=min(coverage),compared_language_frames=len(coverage),
        output_sha256=hashlib.sha256(Path(job.output_path).read_bytes()).hexdigest())
    backend=AdvancedRendererBackend()
    status=backend.status()
    if status.available:
        from dataclasses import replace
        project.effects['audit-motion']={'entry':{'type':'fade','duration':180},'exit':{'type':'fade','duration':140},
            'loop':{'type':'loop_breathe','duration':1200},'motion_override':True}
        for cue in project.cues:cue.effect_id='audit-motion'
        context=dict(job.export_context or {});context.pop('job_id',None)
        motion_job=replace(job,output_path=str(output/'motion-complete.mp4'),completion_metadata={},export_context=context)
        backend.render(project,ffmpeg,motion_job,trace=lambda name,data:traces.append((name,data)))
        motion_frames=list(av.open(motion_job.output_path).decode(video=0))
        result.update(motion_frames=len(motion_frames),motion_status='completed')
        for index in (0,25,85,145,179):motion_frames[index].to_image().save(output/f'motion-frame-{index}.png')
    else:result['motion_status']='not_run_optional_runtime_missing'
    (output/'export-traces.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2,default=str),'utf8')
    return result
