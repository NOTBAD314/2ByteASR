"""The cover may retire only after native video and destination paint commit."""
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from twobyteasr.app.ui import MainWindow
from twobyteasr.design import native_visibility_commit


def test_native_cover_is_outermost_of_video_handoff(monkeypatch):
    events = []
    view = object()

    class Cover:
        def __init__(self, owner):
            assert owner is window

        @contextmanager
        def scope(self, widgets):
            assert widgets == [view]
            events.append('cover-held')
            yield
            assert events[-1] == 'video-committed-and-flushed'
            events.append('cover-hidden')

    @contextmanager
    def video():
        events.append('video-held')
        yield
        events.append('video-committed-and-flushed')

    window = NS(_studio_loading_session=NS(uses_native_cover=True, view=view),
                _native_video_handoff=video)
    monkeypatch.setattr(native_visibility_commit, 'NativeVisibilityCommit', Cover)
    with MainWindow._loading_cover_handoff(window):
        events.append('destination-painted')
    assert events == ['cover-held', 'video-held', 'destination-painted',
                      'video-committed-and-flushed', 'cover-hidden']


@pytest.mark.parametrize('verified', [False, True])
def test_editor_cannot_be_exposed_before_cover_submission_is_verified(verified):
    events = []
    studio = NS(video=NS(_paused=False, set_paused=lambda value: events.append(('pause', value))))
    session = NS(active=True, uses_native_cover=True,
                 native_cover_state=lambda: {'verified': verified},
                 view=NS(raise_=lambda: events.append('raise-cover')))
    window = NS(_studio_loading_session=session, built_page=lambda name: studio,
                _switch_page=lambda page: events.append(('show', page)),
                _loading_surface_painted=lambda: events.append('queued-work'))
    MainWindow._present_native_loading_destination(window)
    assert events == ([('pause', True), ('show', studio), 'raise-cover', 'queued-work'] if verified else [])


def test_destination_native_page_paint_follows_shell_paint():
    events = []
    layout = NS(activate=lambda: None)
    window = NS(repaint=lambda: events.append('shell'),
                _page_changed=lambda index: events.append('chrome'), layout=lambda: layout,
                pages=NS(repaint=lambda: events.append('pages'), currentIndex=lambda: 0,
                         layout=lambda: layout))
    MainWindow._paint_loading_destination(window)
    assert events == ['chrome', 'shell', 'pages']
