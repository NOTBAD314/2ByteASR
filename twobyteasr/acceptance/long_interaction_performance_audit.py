"""Repeatable real-project operations; Qt paint delivery is not monitor scanout."""
from __future__ import annotations

import cProfile
import copy
import json
import os
from pathlib import Path
import time


def run(a, window, output):
    from PySide6.QtCore import QEvent, QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.selection_scope import SelectionScope
    from ..caption_style.style_field_patch import style_fields_command
    from ..timeline.studio_commands import delete_cues_command

    p=a.page;t=p.timeline
    targets=[p.project.cues[i].start_ms+100 for i in (10,3480,6700,30,3500,6800)]
    rows=a.result['long_operations']=[]
    resources=a.result['long_resources']=[]
    import psutil
    process=psutil.Process()
    def resource(label):
        resources.append(dict(label=label,at=time.perf_counter(),rss=process.memory_info().rss,
                              handles=process.num_handles(),threads=process.num_threads()))
    def cue_values(cues):
        # appearance_generation is a monotonic invalidation epoch, including
        # undo; equality here concerns the editable user content/presentation.
        from dataclasses import asdict
        return [{k:v for k,v in asdict(c).items() if k!='appearance_generation'} for c in cues]
    class Feedback(QObject):
        pending=None
        def eventFilter(self,obj,event):
            row=self.pending
            if row is not None and event.type()==QEvent.Paint:
                self.pending=None
                row['paint_begin_ms']=(time.perf_counter()-row['at'])*1000
                def delivered():row['paint_delivered_ms']=(time.perf_counter()-row['at'])*1000
                QTimer.singleShot(0,delivered)
            return False
    observer=Feedback(t);t.installEventFilter(observer)
    def operation(name,fn,**fields):
        row=dict(name=name,phase=a.phase,at=time.perf_counter(),**fields)
        observer.pending=row
        fn();row['handler_ms']=(time.perf_counter()-row['at'])*1000;rows.append(row)
        # Requesting a frame is also necessary when the action affects only a
        # hidden row. State assertions below are independent from this marker.
        t.update()
        yield a.wait(lambda:'paint_delivered_ms' in row,name+' Qt delivery',30)
        yield .035
    profiling=os.environ.get('LONG_OPERATION_PROFILE')=='1'
    def profiled(name,fn):
        if not profiling:return fn()
        pr=cProfile.Profile();value=pr.runcall(fn);pr.dump_stats(str(output/(name+'.pstats')));return value

    resource('loaded');a.set_phase('long-zoom-pan')
    t.set_group_expanded(True);t.vertical_scrollbar.setValue(t.vertical_scrollbar.maximum())
    diagnostic=os.environ.get('LONG_DIAG_ONLY')=='1'
    tail=os.environ.get('LONG_TAIL_ONLY')=='1'
    for repeat in range(0 if diagnostic or tail else 3):
        for span in (p.project.media.duration_ms,3600000,900000,240000,90000,30000,90000,240000,900000):
            yield from operation('zoom',lambda s=span:t.set_visible_window(1000000,s),span=span)
        for i in range(10):
            yield from operation('pan',lambda i=i:t.set_visible_window(1000000+i*8000,90000))
    a.set_phase('long-select')
    t.set_visible_window(p.project.cues[3480].start_ms-1000,90000)
    for i in range(0 if diagnostic or tail else 24):
        cue=p.project.cues[3480+i%10]
        yield from operation('select-one',lambda c=cue:profiled('select',lambda:p.select_cue(c.id)))
        a.check('selected-'+str(i),p.session.selected_cue_id==cue.id)
    _capture(window,output/'long-selection.png')
    # Exercise the same commands used by the real controls; one undo for an
    # entire batch. Original and translation presentation are checked apart.
    original_ids=[c.id for c in p.project.cues]
    original_set=set(original_ids)
    original_translation_count=sum(key in p.project.generation_metadata.get('translations',{}) for key in original_ids)
    a.result['original_associations']=dict(translation_records=len(p.project.generation_metadata.get('translations',{})),
                                          associated=original_translation_count)
    original_cues=cue_values(p.project.cues)
    for cycle in range(0 if tail else 1 if diagnostic else 2):
        a.set_phase('long-batch-'+str(cycle))
        for layer in ('original','translation'):
            from ..caption_style.scoped_style import effective_layer_style
            p.style_scope.setCurrentIndex(p.style_scope.findData('selected'))
            p.style_layer.setCurrentIndex(p.style_layer.findData(layer))
            t.set_subtitle_layer(layer)
            yield from operation('select-all-'+layer,lambda:p.cue_controller.apply_selection_scope(
                SelectionScope.all(len(p.project.cues),p.project.cues[3480].id)))
            before=cue_values(p.project.cues);index=p.undo_stack.index()
            # Layer changes use the production UI's scoped command builder.
            def change_style():
                p.style_font_size.setValue(61+cycle)
                p._commit_style_now()
            yield from operation('style-'+layer,lambda:profiled('style-'+layer,change_style))
            yield a.wait(lambda:p.undo_stack.index()==index+1,'bulk style committed '+layer,120)
            rows[-1]['commit_complete_ms']=(time.perf_counter()-rows[-1]['at'])*1000
            a.check('batch-single-undo-'+layer+'-'+str(cycle),p.undo_stack.index()==index+1)
            after=cue_values(p.project.cues)
            a.check('batch-changed-'+layer+'-'+str(cycle),after!=before)
            a.check('batch-every-selected-'+layer+'-'+str(cycle),
                    all(abs(effective_layer_style(p.project,c,layer).font_size-(61+cycle))<.001
                        for c in p.project.cues if layer=='original' or p.project.generation_metadata.get('translations',{}).get(c.id)))
            yield from operation('undo-style-'+layer,lambda:profiled('undo-'+layer,p.undo_stack.undo))
            a.check('undo-style-exact-'+layer+'-'+str(cycle),cue_values(p.project.cues)==before)
            yield from operation('redo-style-'+layer,p.undo_stack.redo)
            a.check('redo-style-exact-'+layer+'-'+str(cycle),cue_values(p.project.cues)==after)
            yield from operation('restore-style-'+layer,p.undo_stack.undo)
        # Source deletion also snapshots/restores translations. The entire
        # operation is one transaction; never save this destructive copy.
        index=p.undo_stack.index()
        yield from operation('delete-all',lambda:profiled('delete',lambda:p.undo_stack.push(
            delete_cues_command(p.project,original_ids,changed=p._changed))))
        a.check('delete-empty-'+str(cycle),not p.project.cues)
        a.check('delete-one-undo-'+str(cycle),p.undo_stack.index()==index+1)
        yield from operation('undo-delete',p.undo_stack.undo)
        a.check('undo-delete-exact-'+str(cycle),cue_values(p.project.cues)==original_cues)
        yield from operation('redo-delete',p.undo_stack.redo)
        a.check('redo-delete-empty-'+str(cycle),not p.project.cues)
        yield from operation('restore-delete',p.undo_stack.undo)
        resource('batch-'+str(cycle))
        if diagnostic:return
        # Real AI proofreading page with its local checks, no supplier call.
        a.set_phase('long-proofread-'+str(cycle))
        state=(t.visible_start_ms,t.visible_duration_ms,t.playhead_ms)
        a.action('proofread-open',window._open_studio_glossary_proofread)
        review=window.glossary_proofread_page
        yield a.wait(lambda:not review.checks_running(),'local review ready',120)
        QTest.mouseClick(review.back_button,Qt.LeftButton);yield .15
        a.check('review-return-'+str(cycle),state==(t.visible_start_ms,t.visible_duration_ms,t.playhead_ms))
    if not tail:
        a.set_phase('long-seek')
        targets=[p.project.cues[i].start_ms+100 for i in (10,3480,6700,30,3500,6800)]
        for repeat in range(3):
            for target in targets:
                yield from a.seek(target,'long-seek-'+str(repeat));yield .04
        for target in targets*2:p._seek(target/1000)
        yield a.wait(lambda:a.seek_ready(targets[-1]),'coalesced final seek',30)
        a.check('rapid-latest',abs(t.playhead_ms-targets[-1])<150)
        _capture(window,output/'long-latest.png');resource('seeks')
        a.set_phase('long-copy')
        from ..timeline.caption_copy_command import capture_captions
        from ..timeline.studio_selection import ClipSelection
        payload=[]
        yield from operation('copy-all',lambda:payload.append(capture_captions(p.project,original_ids,layer='original')))
        a.check('copy-all-snapshot',len(payload[0]['rows'])==len(original_ids))
        selection=ClipSelection(cue_ids=set(original_ids));selection.caption_payload=payload[0]
        index=p.undo_stack.index()
        yield from operation('paste-all',lambda:p._copy_selected_clip_group(selection,1000))
        copies=[c for c in p.project.cues if c.id not in original_set]
        a.check('paste-all-count',len(copies)==len(original_ids) and p.undo_stack.index()==index+1)
        a.check('paste-all-translations',sum(c.id in p.project.generation_metadata['translations'] for c in copies)
                ==original_translation_count)
        yield from operation('undo-paste-all',p.undo_stack.undo)
        a.check('undo-copy-originals',cue_values(p.project.cues)==original_cues)
        yield from operation('redo-paste-all',p.undo_stack.redo)
        a.check('redo-copy-count',len(p.project.cues)==2*len(original_ids))
        yield from operation('restore-paste-all',p.undo_stack.undo)
        resource('copy')
    # The existing playback audit records actual position observations.
    from .studio_interactions_audit import playback_budget_suite
    previous_seconds=os.environ.get('INTERACTIONS_PLAYBACK_SECONDS','0')
    os.environ['INTERACTIONS_PLAYBACK_SECONDS']='12'
    try:yield from playback_budget_suite(a,window,output)
    finally:os.environ['INTERACTIONS_PLAYBACK_SECONDS']=previous_seconds
    # Exercise the actual production export function on its owned immutable
    # job while the workbench remains interactive. The existing export page
    # cancels on Back, so this audit submits the same backend independently.
    a.set_phase('long-export-prepare')
    from ..projects.project_range import set_range
    from ..exports.studio_render import run_render_job
    from ..system.platform_media import ffmpeg_tool
    from dataclasses import replace
    import threading
    set_range(p.project,0,90000,undo_stack=p.undo_stack)
    p._open_render_dialog(skip_preflight=True);yield .3
    ui=p.export_workspace
    ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
    ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
    ui.encoder_preset.setCurrentIndex(ui.encoder_preset.findData('quality'))
    job=replace(ui._job(output/'background-export.mp4'),preview_callback=None)
    p._close_export_workspace();yield .2
    export=a.result['background_export']=dict(started=time.perf_counter(),done=False,error='',route='production run_render_job; audit submitted')
    def work():
        try:export['path']=str(run_render_job(ffmpeg_tool(),job))
        except Exception as exc:export['error']=repr(exc)
        finally:export['done']=True;export['seconds']=time.perf_counter()-export['started']
    thread=threading.Thread(target=work,name='long-audit-export',daemon=True);thread.start()
    a.set_phase('long-export-busy');resource('export-start')
    for i in range(12):
        yield from operation('busy-pan',lambda i=i:t.set_visible_window(1000000+i*8000,90000),export_running=not export['done'])
        cue=p.project.cues[3480+i]
        yield from operation('busy-select',lambda c=cue:p.select_cue(c.id),export_running=not export['done'])
    for target in targets:
        running=not export['done'];yield from a.seek(target,'busy-seek')
        a.seek_rows[-1]['export_running_at_input']=running
    yield a.wait(lambda:export['done'],'production background export',180)
    a.check('background-export',not export['error'] and (output/'background-export.mp4').is_file())
    resource('export-finished')
    p.undo_stack.undo() # audit range selection
    # Return with no changes, then reopen the same owned copy.
    p.undo_stack.setClean();a.set_phase('long-library')
    began=time.perf_counter();p.show_project_hub(skip_dirty_guard=True);yield .25
    a.result['return_library_ms']=(time.perf_counter()-began)*1000
    began=time.perf_counter();window.open_studio_project(str(a.project_path))
    yield a.wait(a.ready,'warm reopen',100)
    a.result['warm_reopen_ms']=(time.perf_counter()-began)*1000
    a.page=p=window.built_page('studio');resource('reopened')
    a.check('reopen-editable',p.project is not None and p.cue_model.rowCount()>0)
    from ..timeline.studio_commands import SetCueFieldsCommand
    cue=p.project.cues[10];prior=cue.text
    p.undo_stack.push(SetCueFieldsCommand(p.project,cue.id,{'text':prior+' '},'重开编辑',p._changed))
    a.check('reopen-edit',p.project.cues[10].text==prior+' ')
    p.undo_stack.undo();a.check('reopen-edit-undo',p.project.cues[10].text==prior)
    t.removeEventFilter(observer)
