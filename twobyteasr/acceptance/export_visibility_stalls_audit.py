"""Normal application entry, confirmed field-project copies, actual export button."""
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    def execute():
        try: run(window, Path(output))
        except Exception: (Path(output)/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        window.studio_page.undo_stack.setClean()
        window.close()
    QTimer.singleShot(150, execute)


def run(window, output):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject, StudioCue, StudioSpeaker, save_project
    from ..projects.project_range import set_range
    from ..studio.studio_track_header import button_rect
    from ..caption_style.bilingual_layout import project_display_cues
    from ..diagnostics.build_identity import launch_identity_payload
    from .blank_project_audit import _capture
    source=json.loads(Path(os.environ['TWOBYTEASR_FIELD_PROJECT']).read_text(encoding='utf-8'))
    result={'runtime':launch_identity_payload(), 'checks':[], 'exports':[]}
    page=window.studio_page
    def save(): (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    def check(name, value, detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value: raise AssertionError(name+': '+str(detail))
    def wait(predicate, label, seconds=180):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline: raise TimeoutError(label)
            QTest.qWait(10)
    def open_data(data, name):
        path=save_project(SubtitleProject.from_dict(data),output/(name+'.2byteproj'))
        page.undo_stack.setClean();previous=page.project
        window.open_studio_project(str(path),mode='edit',source='export-visibility-stalls-audit')
        wait(lambda:page.project is not previous and page._readiness.ready,'project ready')
        page.video.set_paused(True);QTest.qWait(300)
        return path
    def eyes(visible, only=None):
        page.timeline.set_group_expanded(True);QTest.qWait(50)
        for speaker in page.project.speakers:
            if only is not None and speaker.id!=only:continue
            current=page._subtitle_track_visibility.get(speaker.id,True)
            if current==visible:continue
            rect=page.timeline._track_layout()[0].get(speaker.id)
            if rect is not None:
                QTest.mouseClick(page.timeline,Qt.MouseButton.LeftButton,pos=button_rect('subtitle','visibility',rect).center().toPoint())
            else:
                # Empty rows have no clickable header; retain the same signal contract.
                page.timeline.subtitle_visibility_changed.emit(speaker.id,visible)
            check('eye '+speaker.id+' '+str(visible),page.project.studio_state['subtitle_track_visibility'].get(speaker.id)==visible)
    def export(name, expected, duration=231775):
        set_range(page.project,0,duration,page.undo_stack)
        page.studio_render_button.click();wait(lambda:page.export_workspace is not None,'workspace')
        w=page.export_workspace;QTest.qWait(120)
        w.directory.setText(str(output));w.filename_prefix.setText('');w.filename_suffix.setText('');w.filename.setText(name)
        w.extension.setCurrentIndex(w.extension.findData('mp4'));w.codec.setCurrentIndex(w.codec.findData('h264'))
        w.encoder.setCurrentIndex(w.encoder.findData('libx264'))
        w.rate_control.setCurrentIndex(w.rate_control.findData('crf'));w.quality_value.setValue(20)
        w.encoder_preset.setCurrentIndex(w.encoder_preset.findData('balanced'))
        w.fps.setCurrentIndex(w.fps.findData(0.0));w.resolution.setCurrentIndex(w.resolution.findData((0,0)))
        w.audio.setCurrentIndex(w.audio.findData('copy'));w._target_changed()
        if not result['exports']: _capture(window,output/'export-settings.png')
        started=time.perf_counter();destination=w.export_target().full_path;w.export_button.click()
        wait(lambda:not w._running,'complete '+name,600)
        check(name+' published',destination.is_file() and w.pages.currentWidget() is w.success_page,w._last_failure)
        job=w._last_job
        check(name+' burn-in plan', bool(job.ass_path)==bool(expected),dict(ass=job.ass_path,cues=len(job.export_project_data['cues'])))
        check(name+' requested settings',job.settings.encoder=='libx264' and job.settings.quality==20 and job.settings.preset=='medium')
        result['exports'].append(dict(name=name,file=str(destination),wall=time.perf_counter()-started,
            job=job.export_context,completion=job.completion_metadata,cues=[(c['id'],c['speaker_id']) for c in job.export_project_data['cues']]))
        _capture(window,output/(name+'-success.png'));save();page._close_export_workspace();QTest.qWait(100)
    window.showNormal();window.resize(1600,950);window.show()
    empty=json.loads(json.dumps(source));empty['cues']=[]
    open_data(empty,'A-empty');export('A-no-captions',False)
    path=open_data(source,'restored-field');eyes(True);export('C-visible',True)
    original_text=[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]
    eyes(False);export('B-hidden',False)
    check('hiding preserves cue data',original_text==[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues])
    saved=save_project(page.project,output/'hidden-saved.2byteproj')
    open_data(json.loads(saved.read_text(encoding='utf-8')),'hidden-reopened')
    export('hidden-reopened',False,15000)
    eyes(True);export('C-visible-again',True,15000)
    # Keep original two-language layout while checking the existing display-mode control.
    p=page.project
    first=p.cues[0]
    other=next((s.id for s in p.speakers if s.id!=first.speaker_id), None)
    if other is None:
        other='qa-second-track';p.speakers.append(StudioSpeaker(other,'第二條 QA 軌'))
    p.cues.append(StudioCue('qa-other-speaker',1000,14000,'第二條字幕軌保留',speaker_id=other,
        transform={'position_x':960,'position_y':180}))
    p.studio_state['subtitle_track_visibility']={s.id:True for s in p.speakers}
    p.generation_metadata['translations']={c.id:'Translation '+c.id for c in p.cues}
    p.studio_state['bilingual']={'mode':'bilingual'}
    path=save_project(p,output/'bilingual.2byteproj')
    open_data(json.loads(path.read_text(encoding='utf-8')),'bilingual-reopened');export('bilingual-visible',True,15000)
    page.project.studio_state['bilingual']['mode']='original'
    export('translation-hidden',True,15000)
    check('translation mode retained in snapshot',page.project.studio_state['bilingual']['mode']=='original')
    speaker=next(c.speaker_id for c in page.project.cues if c.start_ms<15000)
    eyes(False,only=speaker);export('one-track-hidden',any(c.speaker_id!=speaker and c.start_ms<15000 for c in page.project.cues),15000)
    # Cancellation owns the staged output; no successful filename may remain.
    eyes(True);set_range(page.project,0,231775,page.undo_stack)
    page.studio_render_button.click();wait(lambda:page.export_workspace is not None,'cancel workspace')
    w=page.export_workspace;w.directory.setText(str(output));w.filename.setText('cancelled-export');destination=w.export_target().full_path
    w.export_button.click();QTest.qWait(800);w._cancel_export();wait(lambda:not w._running,'cancel acknowledgement',30)
    check('cancel did not publish',not destination.exists());page._close_export_workspace()
    result['completed']=True;result['passed']=all(c['passed'] for c in result['checks']);save()
