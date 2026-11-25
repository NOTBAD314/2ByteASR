"""Studio alignment uses the common task UI and bounded shared PCM."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,time
from types import SimpleNamespace
import numpy as np
import pytest


def test_selected_pcm_is_readonly_spooled_and_offsets_are_applied_once(monkeypatch):
    from twobyteasr.studio import studio_realign as realign
    from twobyteasr.recognition import asr
    from twobyteasr.studio import studio_video_track
    runs=[dict(text='a',members=[dict(key='one',text='a',start_ms=5000,end_ms=6000)],spans=[(0,1)],window_start_ms=5000,window_end_ms=6000),
          dict(text='b',members=[dict(key='two',text='b',start_ms=9000,end_ms=10000)],spans=[(0,1)],window_start_ms=9000,window_end_ms=10000)]
    monkeypatch.setattr(realign,'_runs',lambda *args:(runs,{'one','two'}))
    monkeypatch.setattr(realign,'_cue_pcm',lambda project,key,ffmpeg,**kw:
                        (SimpleNamespace(play_range_ms=(5000 if key=='one' else 9000,0)),np.ones(16000,dtype=np.float32)))
    monkeypatch.setattr(studio_video_track,'ffmpeg_executable',lambda:'unused')
    from twobyteasr.recognition import cue_forced_alignment
    monkeypatch.setattr(cue_forced_alignment,'second_opinion',lambda *args:None)
    seen=[]
    def worker(audio,jobs):
        assert isinstance(audio,np.memmap) and not audio.flags.writeable
        assert jobs[1]['window_start_ms']==1200  # 1s clip + exact 0.2s separator
        seen.append(True)
        rows=[]
        for job in jobs:
            start=job['window_start_ms']
            rows.append(dict(job,status='aligned',stats={},segments=[dict(char_start=0,char_end=1,
                start_ms=start+100,end_ms=start+800,granularity='word',start_basis='model',end_basis='model')]))
        return dict(model='test',model_revision='test',results=rows)
    monkeypatch.setattr(asr,'run_qwen_aligner_worker',worker)
    result=realign.measure(SimpleNamespace(),['one','two'],language='English')
    assert seen and result['one']['words'][0]['start_ms']==5100
    assert result['two']['words'][0]['start_ms']==9100
    assert result['two']['evidence']['timebase']=='concatenated-pcm-ms'
    assert result['two']['evidence']['project_offset_ms']==7800


_qt_app=None

def test_local_task_shows_phases_and_existing_cancel_action(monkeypatch):
    from PySide6.QtWidgets import QApplication,QLabel
    from PySide6.QtCore import QObject
    from PySide6.QtTest import QTest
    from twobyteasr.studio import studio_realign as realign
    from twobyteasr.timeline import studio_caption_timeline
    from twobyteasr.studio.studio_task_progress import SubtitleTask
    from twobyteasr.recognition.cache import record_run_event
    from twobyteasr.recognition.service import CancelledError
    global _qt_app
    _qt_app=QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    project = SubtitleProject(media=StudioMedia(''), project_id='fixture',
                              cues=[StudioCue('one', 1000, 2500, 'a')])
    class Page(QObject):
        def _new_subtitle_task(self,kind,cues):
            self.task=SubtitleTask(kind,tuple(cue.id for cue in cues));self.task.project=self.project;return self.task
        def _refresh_subtitle_task_entry(self):pass
    page=Page();page.project=project;page.runtime_settings={};page.save_state=QLabel()
    page.timeline = SimpleNamespace(locked_speakers=set())
    monkeypatch.setattr(studio_caption_timeline,'independent_captions',lambda project:True)
    monkeypatch.setattr(realign,'alignment_audio_basis',lambda *args:'basis')
    def measure(project,ids,**kw):
        record_run_event('alignment_progress',worker_state='loading',jobs=2)
        until=time.monotonic()+3
        while not kw['cancelled']() and time.monotonic()<until:time.sleep(.01)
        raise CancelledError('fixture cancelled')
    monkeypatch.setattr(realign,'measure',measure)
    realign.start_realign(page,['one'])
    until=time.monotonic()+2
    while '0/2' not in page.save_state.text() and time.monotonic()<until:
        QApplication.processEvents();time.sleep(.02)
    assert '0/2' in page.save_state.text() and page.task.kind=='字词对齐'
    page.task.cancel_action()
    until=time.monotonic()+2
    while page.task.ended is None and time.monotonic()<until:
        QApplication.processEvents();time.sleep(.02)
    assert page.task.cancelled and '已取消' in page.save_state.text()
    assert page.task.time_label=='工程时间'
    assert (page.task.rows['one']['start_ms'],page.task.rows['one']['end_ms'])==(1000,2500)
    page.deleteLater();page.save_state.deleteLater();QTest.qWait(20)


def test_realign_removes_only_resolved_proofreading_marker_and_undo_restores_it():
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.studio.studio_realign import RealignWordsCommand

    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia('', duration_ms=6000),
                              cues=[StudioCue('edited', 1000, 3000, 'correct'),
                                    StudioCue('other', 3500, 5000, 'kept')])
    pending = {'text': 'correct', 'words': [], 'requires_acoustic_alignment': True}
    other = {'text': 'kept', 'words': [], 'requires_acoustic_alignment': True}
    project.studio_state['term_word_overrides'] = {'edited': pending, 'other': other}
    result = {'text': 'correct', 'status': 'aligned', 'cue_range_ms': [1000, 3000],
              'measurement': {'state': 'measured'},
              'words': [{'text': 'correct', 'char_start': 0, 'char_end': 7,
                         'start_ms': 1110, 'end_ms': 1900}]}
    stack = QUndoStack()
    stack.push(RealignWordsCommand(project, {'edited': result}))
    assert project.studio_state['term_word_overrides'] == {'other': other}
    assert (project.cues[0].text, project.cues[0].start_ms, project.cues[0].end_ms) == ('correct', 1000, 3000)
    stack.undo()
    assert project.studio_state['term_word_overrides'] == {'edited': pending, 'other': other}
