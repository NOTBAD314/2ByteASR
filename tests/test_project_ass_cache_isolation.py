import threading
from types import SimpleNamespace

from twobyteasr.rendering.ass_compile_actor import AssCompileActor
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_revisions import StudioRevisionStore


def revision(text):
    project = SubtitleProject(media=StudioMedia(path='fixture.mp4', duration_ms=1000),
                              cues=[StudioCue('same-cue', 0, 1000, text)])
    project.project_id = 'copied-id'
    project.validate()
    return StudioRevisionStore(project).render


def test_reopened_copy_does_not_reuse_original_ass():
    first, second = revision('ORIGINAL ONLY'), revision('COPY ONLY')
    assert first.compile_key == second.compile_key
    ready, failed = [], []
    actor = AssCompileActor(ready.append, lambda *error: failed.append(error))
    try:
        actor.submit(1, first)
        assert actor.wait_idle(20) and not failed
        actor.submit(2, first)
        assert actor.wait_idle(10) and ready[-1].cache_hit
        actor.invalidate_cache()
        actor.submit(3, second)
        assert actor.wait_idle(20) and not failed
        assert not ready[-1].cache_hit
        assert 'COPY ONLY' in ready[-1].content
        assert 'ORIGINAL ONLY' not in ready[-1].content
    finally:
        actor.close()


def test_inflight_original_cannot_repopulate_next_project_cache():
    # Invalidate while an actual _compile call waits for its process response.
    actor = AssCompileActor.__new__(AssCompileActor)
    actor._condition = threading.Condition()
    actor._cache_epoch = 0
    actor._last_key = None
    actor._last_content = ''
    actor._stopping = False
    actor._process = SimpleNamespace(pid=123)
    actor._start_process = lambda: None
    actor._connection = SimpleNamespace(
        send=lambda _: None,
        poll=lambda _: True,
        recv=lambda: (actor.invalidate_cache() or (1, 'ORIGINAL ONLY', 1, '')),
    )
    actor._compile(1, revision('ORIGINAL ONLY'))
    assert actor._last_key is None and actor._last_content == ''


def test_request_dequeued_before_close_cannot_use_new_session_cache():
    ready, failed = [], []
    actor = AssCompileActor(ready.append, lambda *error: failed.append(error))
    selected, resume = threading.Event(), threading.Event()
    compile_request = actor._compile

    def held_compile(generation, value):
        if generation == 1:
            selected.set()
            assert resume.wait(10)
        return compile_request(generation, value)

    actor._compile = held_compile
    try:
        actor.submit(1, revision('ORIGINAL ONLY'))
        assert selected.wait(5)
        actor.invalidate_cache()
        actor.submit(2, revision('COPY ONLY'))
        resume.set()
        assert actor.wait_idle(20) and not failed
        assert ready[-1].generation == 2
        assert 'COPY ONLY' in ready[-1].content
        assert 'ORIGINAL ONLY' not in ready[-1].content
        assert not ready[-1].cache_hit
    finally:
        resume.set()
        actor.close()
