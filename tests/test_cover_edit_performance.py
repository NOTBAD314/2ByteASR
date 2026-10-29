"""Regressions for content-clock frames and interactive snapshot work."""
import copy
from pathlib import Path
import threading

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from tests.test_timeline_flv_content_clock import gappy, FFMPEG
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.projects.studio_runtime_state import state_for


def test_cover_uses_same_content_frame_as_preview_after_flv_gaps(gappy, tmp_path, monkeypatch):
    from twobyteasr.media import indexed_media
    from twobyteasr.media.indexed_media import IndexedMediaCache
    from twobyteasr.exports.frame_export import save_project_frame, decode_frame
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.export_timeline import export_project_snapshot
    from twobyteasr.timeline.studio_media_pool import add_media_asset, add_video_clip
    app=QApplication.instance() or QApplication([])
    _,sources=gappy
    cache=IndexedMediaCache(tmp_path/'seek'); monkeypatch.setattr(indexed_media,'GLOBAL_INDEXED_MEDIA',cache)
    ref=cache.prepare_timeline_source(str(sources[0]),ffmpeg=FFMPEG)
    p=SubtitleProject(media=StudioMedia(str(sources[0]),duration_ms=14000,width=96,height=64));p.validate()
    p.video_tracks[0].locked=False
    clip=p.video_tracks[0].clips[0]
    clip.source_in_ms=7500;clip.source_out_ms=9500;clip.timeline_in_ms=0;clip.timeline_out_ms=2000
    # An offline later clip must not delay or fail this screenshot.
    missing=add_media_asset(p,tmp_path/'offline.flv',duration_ms=1000,video_metadata={'has_video':True})
    add_video_clip(p,p.video_tracks[0].id,missing.asset_id,source_in_ms=0,source_out_ms=1000,timeline_in_ms=5000)
    graph=capture_video_graph(p); before=copy.deepcopy(graph)
    result=save_project_frame(export_project_snapshot(p),graph,333,tmp_path,'cover',subtitles=False,ffmpeg=FFMPEG)
    expected,_=decode_frame(ref['path'],7.833)
    raw,_=decode_frame(str(sources[0]),7.833)
    assert QImage(result['path']).convertToFormat(QImage.Format_ARGB32)==expected.convertToFormat(QImage.Format_ARGB32)
    assert QImage(result['path'])!=raw
    assert Path(result['decode'][0]['path'])==Path(ref['path'])
    assert graph==before


def test_edit_defers_persistence_but_save_captures_latest_evidence(monkeypatch):
    p=SubtitleProject(media=StudioMedia('',duration_ms=1000),cues=[StudioCue('a',0,1000,'原文')]);p.validate()
    p.asr_evidence={'original':{'words':[{'text':'原文','start':0,'end':1}]*1000}}
    p.generation_metadata={'translations':{'a':'Original'},'recognition_history':['keep']*1000}
    store=StudioRevisionStore(p);state_for(p).subscribe(store.consume)
    original=store.persistence
    capture=store._capture_persistence;calls=[]
    def tracked(generation):
        calls.append(generation);return capture(generation)
    monkeypatch.setattr(store,'_capture_persistence',tracked)
    command=SetCueFieldsCommand(p,'a',{'text':'新文字'},'edit');command.redo()
    assert calls==[], 'A keystroke must not freeze the entire autosave payload'
    assert store.render.timeline_cues[0].text=='新文字'
    saved=store.persistence
    assert saved.to_payload()['cues'][0]['text']=='新文字'
    assert saved.to_payload()['asr_evidence']==p.asr_evidence
    assert saved.to_payload()['generation_metadata']==p.generation_metadata
    from twobyteasr.projects.studio_revisions import thaw_json
    # Speaker names joined the live view with Codex's speaker-label template (2026-10-24).
    assert thaw_json(store.render.generation_metadata)=={'translations':{'a':'Original'},'speaker_names':{}}
    from twobyteasr.timeline.studio_commands import SetCueTranslationCommand
    SetCueTranslationCommand(p,'a','Edited').redo()
    assert thaw_json(store.render.generation_metadata)['translations']['a']=='Edited'
    command.undo()
    assert len(calls)==1
    assert saved.to_payload()['cues'][0]['text']=='新文字'
    assert original.to_payload()['cues'][0]['text']=='原文'
    assert store.refresh_persistence(20).to_payload()['cues'][0]['text']=='原文'


def test_waveform_retirement_keeps_lease_until_worker_releases_it():
    from twobyteasr.playback.waveform_cache import WaveformCache
    entered=threading.Event(); release=threading.Event(); done=threading.Event(); threads=[]
    class Lease:
        def __exit__(self,*_):
            threads.append(threading.get_ident());entered.set();release.wait(3);done.set()
    cache=object.__new__(WaveformCache);cache._storage_leases=[Lease()]
    main=threading.get_ident()
    try:
        cache.__del__()
        assert entered.wait(1)
        assert threads==[threads[0]] and threads[0]!=main
        assert not done.is_set()
        cache.__del__()  # repeated finalization cannot release twice
    finally:release.set()
    assert done.wait(2)
    assert len(threads)==1
