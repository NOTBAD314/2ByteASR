"""Opt-in same-project dismissal, persistence and screenshot-style export audit."""
from pathlib import Path
import copy
import json
import time


def open_from_list(page,cue_id,layer):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QLineEdit
    if layer!='original':
        page._open_caption_editor(cue_id,layer)
        return
    page.timeline.set_subtitle_layer('original')
    index=page.cue_model.index(page.cue_model.row_for_cue_id(cue_id),3)
    page.cue_table.scrollTo(index);QApplication.processEvents()
    rect=page.cue_table.visualRect(index)
    assert rect.isValid()
    QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,pos=rect.center())
    QTest.mouseDClick(page.cue_table.viewport(),Qt.LeftButton,pos=rect.center())
    QApplication.processEvents()
    assert page._caption_draft is not None and page._caption_draft.target.cue_id==cue_id
    assert not [widget for widget in page.cue_table.findChildren(QLineEdit) if widget.isVisible()]


def check_dismissal(page, output, check, capture):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from ..projects.studio_project import load_project, SubtitleProject
    cue=next(c for c in page.project.cues if c.start_ms>10000 and
             page.project.generation_metadata.get('translations',{}).get(c.id))
    page.select_cue(cue.id)
    records=[]
    for layer in ('original','translation'):
        for exit_kind in ('cancel','escape','header_close','window_close'):
            for rejected in (False,True):
                open_from_list(page,cue.id,layer)
                draft=page._caption_draft
                before=draft.target.read(page.project)
                page.subtitle_edit_input.setPlainText('' if not rejected else 'Rejected draft stays local')
                page._flush_edit_preview()
                if rejected:
                    track=cue.speaker_id if layer=='original' else 'translation'
                    page.timeline.locked_speakers.add(track)
                    check(f'{layer}/{exit_kind}/real_lock_reject',not page._caption_trigger_commit('button'))
                    page.timeline.locked_speakers.discard(track)
                index,count=page.undo_stack.index(),page.undo_stack.count()
                if rejected and layer=='original' and exit_kind=='header_close':capture('integrity-rejected-draft')
                if exit_kind=='cancel':QTest.mouseClick(page.caption_cancel_button,Qt.LeftButton)
                elif exit_kind=='escape':QTest.keyClick(page.subtitle_edit_input,Qt.Key_Escape)
                elif exit_kind=='header_close':QTest.mouseClick(page.caption_close_button,Qt.LeftButton)
                else:page.subtitle_edit_dock.close()
                QTimer.singleShot(0,page._flush_edit_preview)
                QTimer.singleShot(0,page._commit_canvas_inline_edit)
                QTest.qWait(220)
                check(f'{layer}/{exit_kind}/{rejected}/no_write',draft.target.read(page.project)==before and
                      (page.undo_stack.index(),page.undo_stack.count())==(index,count) and
                      page._caption_draft is None and not page._live_edit_text_overrides)
                records.append(dict(edit_session_id=draft.edit_session_id,cue_id=cue.id,layer=layer,
                    exit=exit_kind,rejected=rejected,state=draft.state,undo_index=index,undo_count=count))
    page.save()
    reopened=load_project(page.project_path)
    check('joint_cancel_save_reload_keeps_original_translation',
          next(c.text for c in reopened.cues if c.id==cue.id)==cue.text and
          reopened.generation_metadata['translations'][cue.id]==page.project.generation_metadata['translations'][cue.id])
    (output/'dismissal-records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf8')
    capture('integrity-authoritative-restored')
    return SubtitleProject.from_dict(copy.deepcopy(reopened.to_dict()))


def export_same_project(project, output):
    import av
    import numpy as np
    import sys
    from ..exports.studio_render import RenderJob,RenderSettings
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..caption_style.bilingual_layout import materialize_display_project
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    target=next(c for c in project.cues if c.start_ms>10000 and
                project.generation_metadata.get('translations',{}).get(c.id))
    start=max(0,target.start_ms/1000-.2)
    duration=8.0
    job=RenderJob(project.media.path,str(output/'joint.ass'),str(output/'joint-cancel-export.mp4'),
        RenderSettings(encoder='h264_nvenc',preset='p4',quality_mode='cq',quality=18,width=0,height=0,fps=30,audio_codec='aac'),
        start_seconds=start,duration_seconds=duration,export_project_data=project.to_dict(),
        export_context={'caption_canvas':{'output':[project.media.width,project.media.height]}})
    progress=[];trace=[]
    AdvancedRendererBackend().render(project,ffmpeg,job,progress=progress.append,
                                     trace=lambda name,data:trace.append((name,data)))
    container=av.open(job.output_path)
    audio_present=bool(container.streams.audio)
    frames=list(container.decode(video=0));container.close()
    assert len(frames)==round(duration*30) and audio_present
    # Compare every active layer against the same frozen LIVE raster. Both
    # languages, wrapping and position are checked instead of a color total.
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.advanced_live_renderer import render_live_snapshot
    from PySide6.QtGui import QImage
    display=materialize_display_project(project);coverage=[];ids=set()
    for cue in display.cues:
        at=max(start+.05,cue.start_ms/1000+.05)
        if not start<=at<start+duration or at>=cue.end_ms/1000:continue
        snapshot=build_visual_cue_snapshot(display,cue.id,width=project.media.width,height=project.media.height,resolved_cue=cue)
        image=render_live_snapshot(snapshot,width=project.media.width,height=project.media.height).convertToFormat(QImage.Format_RGBA8888)
        rgba=np.ndarray((image.height(),image.width(),4),np.uint8,buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))
        mask=(rgba[:,:,0]>140)&(rgba[:,:,1]>60)&(rgba[:,:,3]>128)
        index=min(len(frames)-1,round((at-start)*30))
        rgb=frames[index].to_ndarray(format='rgb24')
        ratio=float(((rgb[:,:,0]>120)&(rgb[:,:,1]>45)&mask).sum()/max(1,mask.sum()))
        assert mask.sum()>10 and ratio>.75,(cue.id,ratio)
        ids.add(cue.id);coverage.append(ratio)
    frames[20].to_image().save(output/'joint-export-frame.png')
    assert any(value.endswith('#tr') for value in ids)
    with av.open(job.output_path) as audio:
        samples=[frame.to_ndarray().astype(float) for frame in audio.decode(audio=0)]
    assert samples and max(np.abs(value).max() for value in samples)>0
    (output/'joint-progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),'utf8')
    (output/'joint-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2,default=str),'utf8')
    return dict(joint_frames=len(frames),joint_layers=len(ids),joint_coverage=min(coverage),joint_audio=True)


def export_full_static(project, output):
    import av
    import numpy as np
    import sys
    from ..exports.studio_render import RenderJob,RenderSettings
    from ..rendering.advanced_renderer import AdvancedRendererBackend,compile_composition_data
    from ..caption_style.bilingual_layout import materialize_display_project
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.advanced_live_renderer import render_live_snapshot
    from PySide6.QtGui import QImage
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    job=RenderJob(project.media.path,str(output/'full.ass'),str(output/'full-1397-1740s.mp4'),
        RenderSettings(encoder='h264_nvenc',preset='p4',quality_mode='cq',quality=18,width=0,height=0,fps=30,audio_codec='aac'),
        start_seconds=0,duration_seconds=1740,export_project_data=project.to_dict(),
        export_context={'caption_canvas':{'output':[1920,1080]}})
    progress=[];traces=[]
    def on_progress(row):
        progress.append(row)
        (output/'full-current-progress.json').write_text(json.dumps(row,ensure_ascii=False),'utf8')
    began=time.perf_counter()
    AdvancedRendererBackend().render(project,root/'tools/ffmpeg/bin/ffmpeg.exe',job,progress=on_progress,
                                     trace=lambda name,data:traces.append((name,data)))
    render_s=time.perf_counter()-began
    display=materialize_display_project(project)
    props=compile_composition_data(display,width=1920,height=1080,fps=30,start_seconds=0,duration_seconds=1740)
    assert len(props['cues'])==1397
    cases=[(i,props['cues'][i]) for i in (0,1,468,469,470,1395,1396)]
    by_frame={}
    for index,cue in cases:
        frame=round((cue['startMs']+min(500,(cue['endMs']-cue['startMs'])/2))*30/1000)
        by_frame.setdefault(frame,[]).append((index,cue))
    coverage=[];count=0
    with av.open(job.output_path) as video:
        for frame in video.decode(video=0):
            if count in by_frame:
                rgb=frame.to_ndarray(format='rgb24')
                for index,cue in by_frame[count]:
                    snapshot=build_visual_cue_snapshot(display,cue['id'],width=1920,height=1080)
                    image=render_live_snapshot(snapshot,width=1920,height=1080).convertToFormat(QImage.Format_RGBA8888)
                    rgba=np.ndarray((1080,1920,4),np.uint8,buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))
                    mask=(rgba[:,:,0]>140)&(rgba[:,:,1]>60)&(rgba[:,:,3]>128)
                    ratio=float(((rgb[:,:,0]>120)&(rgb[:,:,1]>45)&mask).sum()/max(1,mask.sum()))
                    assert mask.sum()>10 and ratio>.75,(index,cue['id'],ratio)
                    coverage.append(dict(task_index=index,cue_id=cue['id'],coverage=ratio))
                frame.to_image().save(output/f'full-frame-{count}.png')
            count+=1
    assert count==52200
    samples=0;peak=0
    with av.open(job.output_path) as audio:
        for frame in audio.decode(audio=0):
            samples+=frame.samples
            peak=max(peak,float(np.abs(frame.to_ndarray().astype(float)).max()))
    assert abs(samples/48000-1740)<.1 and peak>0
    states=[row for row in progress if 'static_completed' in row]
    assert states[-1]['static_completed']=='1397' and states[-1]['static_failed']=='0'
    result=dict(full_frames=count,full_audio_samples=samples,full_audio_peak=peak,full_render_s=render_s,
                full_coverage=coverage,full_preparation=states[-1],
                full_timings=next(data for name,data in traces if name=='static_caption_timings'))
    (output/'full-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    (output/'full-progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),'utf8')
    return result
