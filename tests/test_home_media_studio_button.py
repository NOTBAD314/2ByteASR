"""字幕工作台 beside 选择素材 on Home (2026-11-20).

User: after dropping a video on Home, a 字幕工作台 button next to 选择素材 should make a project
with that video and open it in the workbench, without the bottom-left entry → 新建工程 →
dropping the video again.
"""
from pathlib import Path
from types import SimpleNamespace

from twobyteasr.app.ui import MainWindow


def test_only_one_media_file_the_workbench_takes_shows_the_button(tmp_path):
    video, audio, text = tmp_path / 'a.mp4', tmp_path / 'b.wav', tmp_path / 'c.txt'
    for path in (video, audio, text):
        path.write_bytes(b'x')
    home = SimpleNamespace(media_paths=[str(video)])
    assert MainWindow._studio_media_path(home) == video
    home.media_paths = [str(audio)]
    assert MainWindow._studio_media_path(home) == audio
    home.media_paths = [str(text)]
    assert MainWindow._studio_media_path(home) is None
    home.media_paths = [str(video), str(audio)]
    assert MainWindow._studio_media_path(home) is None
    home.media_paths = []
    assert MainWindow._studio_media_path(home) is None


def test_the_button_makes_a_new_project_with_the_file_and_opens_it(tmp_path):
    video = tmp_path / 'clip.mp4'
    video.write_bytes(b'x')
    calls = []

    class Controller:
        def create_blank_project(self, *, on_ready=None, focus_clip_assistant=False):
            calls.append('create')
            on_ready()

    studio = SimpleNamespace(project_controller=Controller(),
                             _begin_media_drop=lambda paths, at, **kw: calls.append(('drop', paths, at)))
    window = SimpleNamespace(media_paths=[str(video)])
    window._studio_media_path = lambda: MainWindow._studio_media_path(window)
    window.open_studio_project = lambda project_path=None, *, on_ready=None, **kw: (
        calls.append(('open', project_path)), on_ready(studio))
    MainWindow._open_media_in_studio(window)
    assert calls == [('open', None), 'create', ('drop', [Path(video)], 0)]


def test_a_missing_file_opens_nothing(tmp_path):
    window = SimpleNamespace(media_paths=[str(tmp_path / 'gone.mp4')])
    window._studio_media_path = lambda: MainWindow._studio_media_path(window)
    window.open_studio_project = lambda *a, **k: (_ for _ in ()).throw(AssertionError('opened'))
    MainWindow._open_media_in_studio(window)
