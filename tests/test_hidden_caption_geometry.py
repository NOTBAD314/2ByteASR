"""Hidden startup geometry must produce a real caption token for a paused cue."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QVBoxLayout, QStackedWidget, QWidget

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def methods(path, owner, names, package):
    tree = ast.parse((ROOT/path).read_text('utf8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    body = []
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            body.append(node)
    module = ast.Module(body=[ast.ClassDef(name='Harness', bases=[], keywords=[], body=body,
                                         decorator_list=[])], type_ignores=[])
    namespace = dict(__package__=package, QWidget=QWidget)
    exec(compile(ast.fix_missing_locations(module), str(ROOT/path), 'exec'), namespace)
    return namespace['Harness']


def test_same_outer_rectangle_settles_empty_hidden_video_geometry():
    harness = methods('twobyteasr/app/ui.py', 'MainWindow', {'_prepare_hidden_studio_geometry'}, 'twobyteasr.app')
    window = QWidget()
    window.resize(800, 600)
    window.setLayout(QVBoxLayout())
    pages = QStackedWidget(window)
    window.layout().addWidget(pages)
    loading, page = QWidget(), QWidget()
    page.setLayout(QVBoxLayout())
    video = QWidget(page)
    page.layout().addWidget(video)
    video.show()
    page.video = video
    pages.addWidget(loading)
    pages.addWidget(page)
    pages.setCurrentWidget(loading)
    window.layout().activate()
    pages.layout().activate()
    page.setGeometry(pages.contentsRect())
    video.resize(0, 120)
    page.layout().invalidate()
    owner = harness()
    owner.pages = pages
    owner.layout = window.layout
    owner.built_page = lambda name: page
    owner._studio_loading_session = SimpleNamespace(active=True, generation=1, view=loading)
    assert page.geometry() == pages.contentsRect() and video.size().isEmpty()
    assert owner._prepare_hidden_studio_geometry(page)
    assert video.width() > 0 and video.height() > 0
    window.close()


def test_hidden_caption_preparation_syncs_overlay_before_activation():
    harness = methods('twobyteasr/studio/studio_advanced_flow.py', 'StudioAdvancedFlowMixin',
                      {'_prepare_loading_subtitles'}, 'twobyteasr.studio')
    from twobyteasr.studio.studio_position_overlay import SubtitlePositionOverlay
    page = harness()
    page.project = object()
    page.project_path = 'fixture.2byteproj'
    page._close_requested = False
    page._readiness = SimpleNamespace(active=True, hydrated=True, path=page.project_path, _owns_request=lambda: True)
    page.video = QWidget()
    page.video.resize(640, 360)
    page.position_overlay = SubtitlePositionOverlay(page.video)
    page.position_overlay.resize(0, 0)
    page._caption_scene = SimpleNamespace(active=True)
    observed = []
    page._activate_selected_advanced_if_needed = lambda: observed.append(page.position_overlay._content_rect())
    page.ensure_active_subtitle_renderer = lambda **kwargs: {}
    assert page._prepare_loading_subtitles()
    assert observed and not observed[0].isEmpty()
    assert page.position_overlay.geometry() == page.video.rect()
    page.video.close()


def test_empty_rect_then_same_paused_cue_submits_after_geometry_changes(monkeypatch):
    from twobyteasr.rendering import caption_scene
    monkeypatch.setattr(caption_scene, 'active_cues', lambda page, milliseconds: ())
    harness = methods('twobyteasr/studio/studio_advanced_flow.py', 'StudioAdvancedFlowMixin',
                      {'_present_caption_scene'}, 'twobyteasr.studio')
    page = harness()
    page.project = object()
    page.isVisible = lambda: True
    page._caption_tick_time_ms = 0
    page._caption_playhead_sample = {}
    page._caption_sample_ms = lambda: 0
    page._sync_canvas_selection = lambda: None
    rectangle = [QRectF()]
    page.position_overlay = SimpleNamespace(_content_rect=lambda: rectangle[0])

    class Scene:
        token = None
        calls = 0

        def present(self, cues, milliseconds):
            self.calls += 1
            if not rectangle[0].isEmpty():
                self.token = ('current',)
            return True

    scene = page._caption_scene = Scene()
    assert page._present_caption_scene() and scene.token is None
    rectangle[0] = QRectF(0, 0, 640, 360)
    assert page._present_caption_scene()
    assert scene.calls == 2 and scene.token == ('current',)
