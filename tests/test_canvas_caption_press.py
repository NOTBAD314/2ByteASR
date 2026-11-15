"""Press a visible caption on the picture: select, pause, follow its layer, drag (2026-11-14)."""
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QWidget

APP = QApplication.instance() or QApplication([])

from twobyteasr.studio import canvas_visibility
from twobyteasr.studio.canvas_caption_press import CanvasCaptionPress
from twobyteasr.studio.studio_position_overlay import SubtitlePositionOverlay

CAPTION = QRectF(220, 280, 200, 40)  # where the renderer shows the caption


class FakeVideo(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(640, 360)
        self._paused = False
        self.controller = object()

    def set_paused(self, paused):
        self._paused = bool(paused)


class FakePage:
    def __init__(self, *, bounds_ready=True):
        self.project = SimpleNamespace()
        self.selected_cue_id = 'old'
        self.selected = []
        self.layers = []
        self.export_workspace = None
        self._canvas_editor = None
        self.bounds_ready = bounds_ready
        self.video = FakeVideo()
        self.position_overlay = SubtitlePositionOverlay(self.video)
        self.position_overlay.setGeometry(self.video.rect())
        self.position_overlay._requires_measured_bounds = True  # as SelectionGeometryController sets it
        self.position_edit_button = QPushButton()
        self.position_edit_button.setCheckable(True)
        self.position_edit_button.setChecked(True)
        language = QComboBox()
        for value in ('original', 'translation', 'linked'):
            language.addItem(value, value)
        self.caption_transform_panel = SimpleNamespace(language=language)
        self.timeline = SimpleNamespace(set_subtitle_layer=self.layers.append)
        self.play_button_paused = None
        self.committed = []
        self.position_overlay.position_committed.connect(lambda x, y: self.committed.append((x, y)))
        self.video.show()

    def select_cue(self, cue_id):
        self.selected_cue_id = cue_id
        self.selected.append(cue_id)

    def _sync_play_button(self, paused):
        self.play_button_paused = paused

    def _sync_canvas_selection(self):
        overlay = self.position_overlay
        overlay.setVisible(self.position_edit_button.isChecked())
        if self.bounds_ready:
            overlay.set_measured_bounds(CAPTION)


def mouse(kind, point, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton,
          modifiers=Qt.KeyboardModifier.NoModifier):
    point = QPointF(point)
    return QMouseEvent(kind, point, point, button, buttons, modifiers)


@pytest.fixture
def hit(monkeypatch):
    def visible(page, point):
        return ('cue-2', 'original') if CAPTION.contains(QPointF(point)) else None
    monkeypatch.setattr(canvas_visibility, 'visible_object_at', visible)


def drag(press, start, delta):
    assert press.press(mouse(QEvent.Type.MouseButtonPress, start))
    for step in range(1, 5):
        press.move(mouse(QEvent.Type.MouseMove, start + delta * (step / 4), Qt.MouseButton.NoButton))
    press.release(mouse(QEvent.Type.MouseButtonRelease, start + delta, buttons=Qt.MouseButton.NoButton))


def test_press_on_unselected_caption_while_playing_selects_pauses_and_drags(hit):
    page = FakePage()
    press = CanvasCaptionPress(page)
    drag(press, CAPTION.center(), QPointF(0, -60))
    assert page.video._paused and page.play_button_paused is True
    assert page.selected == ['cue-2'] and page.layers == ['original']
    assert len(page.committed) == 1
    _, y = page.committed[0]
    assert y < 960  # moved up from the default bottom anchor
    assert not page.position_overlay._dragging and press.pending is None


def test_box_measured_after_the_press_still_drags_the_whole_movement(hit):
    page = FakePage(bounds_ready=False)
    press = CanvasCaptionPress(page)
    start = CAPTION.center()
    assert press.press(mouse(QEvent.Type.MouseButtonPress, start))
    assert not press.pending['started']
    page.position_overlay.set_measured_bounds(CAPTION)  # renderer answers late
    press.move(mouse(QEvent.Type.MouseMove, start + QPointF(0, -60), Qt.MouseButton.NoButton))
    assert press.pending['started']
    press.release(mouse(QEvent.Type.MouseButtonRelease, start + QPointF(0, -60), buttons=Qt.MouseButton.NoButton))
    ready = FakePage()
    drag(CanvasCaptionPress(ready), start, QPointF(0, -60))
    assert page.committed == ready.committed


def test_language_layer_follows_the_caption_that_was_hit(hit):
    page = FakePage()
    language = page.caption_transform_panel.language
    language.setCurrentIndex(language.findData('translation'))
    drag(CanvasCaptionPress(page), CAPTION.center(), QPointF(0, -40))
    assert language.currentData() == 'original' and page.committed
    linked = FakePage()
    language = linked.caption_transform_panel.language
    language.setCurrentIndex(language.findData('linked'))
    drag(CanvasCaptionPress(linked), CAPTION.center(), QPointF(0, -40))
    assert language.currentData() == 'linked' and linked.committed


def test_drag_turned_off_selects_without_dragging(hit):
    page = FakePage()
    page.position_edit_button.setChecked(False)
    press = CanvasCaptionPress(page)
    drag(press, CAPTION.center(), QPointF(0, -40))
    assert page.selected == ['cue-2'] and not page.committed and press.pending is None


def test_press_outside_any_caption_is_not_consumed(hit):
    page = FakePage()
    press = CanvasCaptionPress(page)
    assert not press.press(mouse(QEvent.Type.MouseButtonPress, QPointF(20, 20)))
    assert not page.selected and not page.video._paused


def test_modified_press_keeps_the_existing_behaviour(hit):
    page = FakePage()
    press = CanvasCaptionPress(page)
    event = mouse(QEvent.Type.MouseButtonPress, CAPTION.center(), modifiers=Qt.KeyboardModifier.ControlModifier)
    assert not press.press(event) and not page.selected


def test_double_click_on_a_caption_that_was_not_selected_opens_the_workshop(hit):
    page = FakePage()
    press = CanvasCaptionPress(page)
    drag(press, CAPTION.center(), QPointF(0, 0))
    assert press.claim_double_click() == 'cue-2'
    assert press.claim_double_click() == ''
    drag(press, CAPTION.center(), QPointF(0, 0))  # already selected: the box edits text
    assert press.claim_double_click() == ''


def test_position_toggle_stays_on_without_a_selection():
    from twobyteasr.studio.studio_canvas_edit import StudioCanvasEditMixin
    button = QPushButton()
    button.setCheckable(True)
    button.setChecked(True)
    calls = []
    page = SimpleNamespace(position_overlay=object(), position_edit_button=button, project=None,
                           selected_cue_id='', ensure_active_subtitle_renderer=lambda **kw: calls.append(kw))
    StudioCanvasEditMixin._toggle_position_edit(page, True)
    assert button.isChecked() and not calls


def test_rejected_overlay_event_does_not_reenter_parent_canvas(hit):
    page = FakePage()
    press = CanvasCaptionPress(page)
    received = []
    def move(event):
        received.append(press.move(event))
        event.ignore()
    page.video.mouseMoveEvent = move
    start = CAPTION.center()
    assert press.press(mouse(QEvent.Type.MouseButtonPress, start))
    page.position_overlay.interaction_guard = lambda: False
    assert press.move(mouse(QEvent.Type.MouseMove, start + QPointF(0, -30), Qt.MouseButton.NoButton))
    assert received == [False]
    assert not press._dispatching and not press.pending['started']
    press.release(mouse(QEvent.Type.MouseButtonRelease, start, buttons=Qt.MouseButton.NoButton))


def test_press_cancels_play_intent_while_transport_is_temporarily_paused(hit):
    page = FakePage()
    page.video._paused = True
    page.video.playback_intended = True
    assert CanvasCaptionPress(page).press(mouse(QEvent.Type.MouseButtonPress, CAPTION.center()))
    assert page.play_button_paused is True


def test_captured_geometry_survives_own_preview_but_rejects_target_changes(monkeypatch):
    from twobyteasr.studio.selection_geometry import SelectionGeometryController
    cue = SimpleNamespace(id='a')
    project = object()
    page = SimpleNamespace(project=project,selected_cue_id='a',_cue_lookup={'a':cue},
        caption_transform_panel=SimpleNamespace(language=SimpleNamespace(currentData=lambda:'original')),
        video=SimpleNamespace(_paused=True),_caption_scene=SimpleNamespace(active=True,token=None))
    controller=SimpleNamespace(page=page,key=(id(project),'a','scene-hash','original'),
        overlay=SimpleNamespace(_dragging=True),_measured_language='original')
    monkeypatch.setattr(canvas_visibility,'layer_is_shown',lambda *a:True)
    assert SelectionGeometryController.interaction_valid(controller)
    page.selected_cue_id='b'
    page._cue_lookup['b']=SimpleNamespace(id='b')
    assert not SelectionGeometryController.interaction_valid(controller)
    page.selected_cue_id='a';page.video._paused=False
    assert not SelectionGeometryController.interaction_valid(controller)
    page.video._paused=True;controller.overlay._dragging=False
    assert not SelectionGeometryController.interaction_valid(controller)
