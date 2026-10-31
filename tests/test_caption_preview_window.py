"""Long bilingual previews prepare the requested window without losing peers."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import asdict
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache, materialize_captions


@pytest.fixture
def setup_window():
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia(''),
        cues=[StudioCue(str(i), i*700, i*700+1900, f'Parliamo della qualifica numero {i}', f'S{i%5}')
              for i in range(350)],
        speakers=[StudioSpeaker(f'S{i}', f'Speaker {i}') for i in range(5)],
        generation_metadata={'translations': {str(i): f'第{i}条完整译文' for i in range(350)}},
        studio_state={'bilingual': {'mode': 'bilingual', 'layout': 'ink_v1', 'order': 'translation_first'}})
    project.validate()
    store = StudioRevisionStore(project)
    cache = PlaybackCaptionCache()
    yield project, store, cache
    cache.close()
    cache.deleteLater()


def test_window_keeps_overlapping_speakers_and_exact_bilingual_geometry(setup_window):
    project, store, cache = setup_window
    revision = store.render
    window = cache._window_revision(revision, ('11', '12', '13'))
    assert [c.id for c in window.cues] == ['11', '12', '13']
    assert window.generation_metadata is revision.generation_metadata
    assert window.speakers is revision.speakers
    partial = materialize_captions(window)[0]
    full = materialize_captions(revision)[0]
    expected = {c.id: asdict(c) for c in full.project.cues}
    assert len(partial.project.cues) == 6
    assert all(asdict(c) == expected[c.id] for c in partial.project.cues)
    assert len(project.cues) == 350
    assert len(project.generation_metadata['translations']) == 350
    assert cache._window_revision(revision, ('12#tr',)).cues == (revision.cues[12],)


def test_later_window_and_changed_style_match_full_build(setup_window):
    project, store, cache = setup_window
    first = materialize_captions(cache._window_revision(store.render, ('11', '12')))[0]
    next_window = cache._window_revision(store.render, ('12', '200'))
    second, reused, reason = materialize_captions(next_window, first)
    assert reason == ''
    assert {'12', '12#tr'} <= reused
    assert {c.id for c in second.project.cues} == {'12', '12#tr', '200', '200#tr'}
    project.styles[0].font_size += 7
    from twobyteasr.projects.studio_runtime_state import DirtyDomain as D, StateDelta
    store.consume(StateDelta('style', D.CUE_STYLE | D.AUTOSAVE, frozenset(), frozenset(), (), '', '', 1))
    third = materialize_captions(cache._window_revision(store.render, ('12', '200')), second)[0]
    expected = {c.id: asdict(c) for c in materialize_captions(store.render)[0].project.cues}
    assert all(asdict(c) == expected[c.id] for c in third.project.cues)
    assert len(third.project.cues) == 4


def test_name_layout_preserves_neighbour_dependent_full_path(setup_window):
    project, _, cache = setup_window
    project.studio_state['show_speaker_names'] = True
    revision = StudioRevisionStore(project).render
    assert cache._window_revision(revision, ('11', '12')) is revision


def test_window_indexes_projected_cues_and_releases_on_close(setup_window):
    from dataclasses import replace
    _, store, cache = setup_window
    cue = replace(store.render.cues[1], id='1#edit-segment', start_ms=9000, end_ms=9500)
    revision = replace(store.render, timeline_cues=(cue,))
    window = cache._window_revision(revision, ('1#edit-segment',))
    assert window.cues == (cue,)
    assert window.timeline_cues is None
    cache.close()
    assert not cache._window_cues and cache._window_input is None


def test_window_index_and_retirement_share_one_gate(setup_window):
    import threading
    _, store, cache = setup_window
    entered, release = threading.Event(), threading.Event()
    original = cache._window_revision
    def gated(revision, ids):
        entered.set()
        assert release.wait(5)
        return original(revision, ids)
    cache._window_revision = gated
    try:
        cache.prepare(store.render, ('11',), 640, 360)
        assert entered.wait(5)
        acquired = cache._lock.acquire(blocking=False)
        if acquired:
            cache._lock.release()
        assert not acquired
    finally:
        release.set()
        cache.close()
        worker = cache.worker_thread()
        if worker is not None:
            worker.join(5)
    assert not cache._window_cues and cache._window_input is None
