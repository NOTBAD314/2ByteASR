from dataclasses import asdict
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache,materialize_captions


APP=QApplication.instance() or QApplication([])


def project(count=100):
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue(str(i),i*1000,(i+1)*1000,'parola '+str(i)) for i in range(count)])
    p.generation_metadata['translations']={str(i):'译文'+str(i) for i in range(count)}
    p.studio_state['bilingual']={'mode':'bilingual'}
    p.validate()
    return p


def test_only_requested_original_and_translation_are_materialized_first():
    store=StudioRevisionStore(project())
    cache=PlaybackCaptionCache()
    revision=cache._window_revision(store.render,['5','6'])
    assert len(revision.cues)==2
    partial=materialize_captions(revision)[0]
    complete=materialize_captions(store.render)[0]
    expected=[asdict(c) for c in complete.project.cues if c.id in {x.id for x in partial.project.cues}]
    assert [asdict(c) for c in partial.project.cues]==expected
    assert len(store.render.cues)==100
    cache.close()


def test_scrub_adds_missing_cues_and_reuses_prior_display_without_unbounded_growth():
    store=StudioRevisionStore(project())
    cache=PlaybackCaptionCache()
    partial=materialize_captions(cache._window_revision(store.render,['5','6']))[0]
    scoped=cache._window_revision(store.render,['6','99'])
    assert len(scoped.cues)==2 and any(c.id=='99' for c in scoped.cues)
    second,reused,_=materialize_captions(scoped,partial)
    assert any(c.id=='99' for c in second.project.cues)
    assert reused
    cache.close()


def test_global_speaker_name_layout_keeps_existing_complete_context():
    p=project();p.studio_state['show_speaker_names']=True
    store=StudioRevisionStore(p)
    cache=PlaybackCaptionCache()
    assert cache._window_revision(store.render,['5']) is store.render
    cache.close()


def test_reader_stat_checks_do_not_spawn_decoder_and_preserve_missing_status(tmp_path):
    from twobyteasr.media.media_availability import stat_sources_in_reader
    source=tmp_path/'present.mp4';source.write_bytes(b'media')
    missing=tmp_path/'missing.mp4'
    result=stat_sources_in_reader([source,missing])
    assert result[str(source)]['status']=='available'
    assert result[str(missing)]['status']=='missing'


def test_cancelled_reader_does_not_keep_checking_sources(tmp_path):
    from twobyteasr.media.media_availability import stat_sources_in_reader
    assert stat_sources_in_reader([tmp_path/'missing'],cancel_check=lambda:True)=={}
