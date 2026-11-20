"""2026-11-14 volume windows, toolbar icons and the 「问问兔白」 header button.

User picks: track volume draft C (mini mixer), project loudness draft A (three
steps), toolbar draft A (icons in place), 问问兔白 draft A (terracotta button).
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QDoubleSpinBox, QLabel, QSlider, QWidget

from twobyteasr.studio import gain_scale as scale


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_zero_db_sits_near_the_middle_and_the_scale_round_trips():
    assert .5 < scale.ZERO_POSITION < .6
    # −12…+6 dB gets more than half the travel (it had about a fifth).
    assert scale.position_of(6) - scale.position_of(-12) > .5
    for value in (-60, -37.5, -12, -4.2, 0, 1.5, 9, 24):
        assert abs(scale.db_at(scale.position_of(value)) - value) < 1e-9
    assert scale.snap(.3) == 0. and scale.snap(.3, fine=True) == .3 and scale.snap(99) == 24.
    assert scale.signed(-3) == '−3.0' and scale.signed(2.5) == '+2.5' and scale.signed(0) == '0.0'
    assert scale.words(0) == '原音量' and scale.words(-60) == '几乎静音' and scale.words(10).startswith('大声很多')


def _project(tmp_path):
    from twobyteasr.projects.studio_project import AudioTrack, StudioMedia, SubtitleProject
    media = tmp_path / 'clip.mp4'
    media.write_bytes(b'0')
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=60000))
    project.validate()
    project.audio_tracks.append(AudioTrack(id='A2', name='解说'))
    project.audio_tracks.append(AudioTrack(id='A3', name='BGM', locked=True))
    for track in project.audio_tracks[:2]:
        track.locked = False
    project.video_tracks[0].locked = False
    return project


def _page(project):
    page = QWidget()
    page.project = project
    page.undo_stack = QUndoStack(page)
    page.save_state = QLabel(page)
    page.timeline = SimpleNamespace(selected_audio_track_id='A2', selected_video_track_id='')
    page.video = SimpleNamespace(_paused=True)
    page.mix_refreshes = []
    page._refresh_audio_mix_only = lambda: page.mix_refreshes.append(dict(page._gain_preview_values))
    page._gain_preview_values = {}
    page._project_gain_preview = None
    page.volume_slider = QSlider(Qt.Orientation.Horizontal, page)
    page.volume_slider.setRange(0, 100)
    page.volume_slider.setValue(70)
    return page


def test_gains_command_is_one_undo_step_for_several_tracks(app, tmp_path):
    from twobyteasr.timeline.studio_track_gain import gains_command, track_gain_db
    project = _project(tmp_path)
    stack = QUndoStack()
    stack.push(gains_command(project, {'A1': -6., 'A2': 3.5}))
    assert stack.count() == 1 and track_gain_db(project, 'A1') == -6. and track_gain_db(project, 'A2') == 3.5
    stack.undo()
    assert track_gain_db(project, 'A1') == 0. and track_gain_db(project, 'A2') == 0.
    with pytest.raises(ValueError):
        gains_command(project, {'A3': 1.})


def test_the_mixer_previews_every_changed_track_and_applies_them_together(app, tmp_path):
    from twobyteasr.timeline.studio_track_gain import show_track_gain, track_gain_db
    project = _project(tmp_path)
    page = _page(project)
    show_track_gain(page, 'A2')
    dialog = page._track_gain_dialog
    assert dialog.strips['A2'].current and not dialog.strips['A1'].current
    assert dialog.findChild(QDoubleSpinBox, 'trackGainDb') is dialog.strips['A2'].spin
    assert not dialog.strips['A3'].fader.isEnabled()
    dialog.strips['A1'].fader.setValue(-6.)
    dialog.strips['A2'].spin.setValue(2.)
    assert page._gain_preview_values == {'A1': -6., 'A2': 2.}
    assert dialog.strips['A2'].fader.value() == 2.
    assert '2' in dialog.apply_button.text()
    assert track_gain_db(project, 'A1') == 0. and page.undo_stack.count() == 0
    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert page.undo_stack.count() == 1 and page._gain_preview_values == {}
    assert track_gain_db(project, 'A1') == -6. and track_gain_db(project, 'A2') == 2.


def test_cancel_restores_and_a_fader_drag_only_previews(app, tmp_path):
    from twobyteasr.timeline.studio_track_gain import show_track_gain, track_gain_db
    project = _project(tmp_path)
    page = _page(project)
    show_track_gain(page, 'A2')
    dialog = page._track_gain_dialog
    dialog.resize(700, 560)
    dialog.show()
    app.processEvents()
    fader = dialog.strips['A2'].fader
    y = round(fader.pixel_of(0.))
    QTest.mousePress(fader, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(fader.width() // 2, y))
    QTest.mouseMove(fader, QPoint(fader.width() // 2, y - 40))
    QTest.mouseRelease(fader, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(fader.width() // 2, y - 40))
    assert fader.value() > 0 and page._gain_preview_values.get('A2') == fader.value()
    QTest.mouseDClick(fader, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(fader.width() // 2, y - 40))
    assert fader.value() == 0.
    fader.setValue(-4.)
    dialog.reject()
    assert page._gain_preview_values == {} and track_gain_db(project, 'A2') == 0. and page.undo_stack.count() == 0


def _panel(app, tmp_path):
    from twobyteasr.playback.project_loudness import baseline_identity
    from twobyteasr.studio.project_loudness_panel import show_project_loudness
    project = _project(tmp_path)
    page = _page(project)
    page._loudness_cache = {baseline_identity(project): dict(integrated=-12.4, true_peak=-0.8, duration=60.,
                                                            elapsed=1., sample_rate=48000, channels=2)}
    show_project_loudness(page)
    return page, page._project_loudness_panel


def test_one_click_matches_the_destination_and_the_peak_stays_safe(app, tmp_path):
    from twobyteasr.playback.project_loudness import project_gain_db
    page, panel = _panel(app, tmp_path)
    assert panel.worker is None and panel.result
    assert '−12.4 LUFS' in panel.loud_badge.text()
    assert panel.match.isEnabled() and '−14.0' in panel.match.text()
    for _ in range(3):
        QTest.mouseClick(panel.match, Qt.MouseButton.LeftButton)
    assert project_gain_db(page.project) == -1.6 and page.undo_stack.count() == 1
    assert panel.step3.done and '−14.0 LUFS' in panel.loud_badge.text()
    podcast = next(card for card in panel.destinations if card.key == 'podcast')
    QTest.mouseClick(podcast, Qt.MouseButton.LeftButton)
    assert panel.target.value() == -16. and page.project.studio_state['loudness_target'] == -16.
    assert podcast.isChecked() and not any(c.isChecked() for c in panel.destinations if c is not podcast)
    panel.target.setValue(-10.)   # louder than the peak allows
    panel.apply_match()
    assert project_gain_db(page.project) == -0.2 and '−12.6' in panel.outcome.text()
    panel.monitor.setValue(25)
    assert page.volume_slider.value() == 25 and project_gain_db(page.project) == -0.2
    panel.reject()


def test_manual_gain_previews_then_commits_once(app, tmp_path):
    from twobyteasr.playback.project_loudness import project_gain_db
    page, panel = _panel(app, tmp_path)
    assert not panel.manual.isVisible()
    panel.more.setChecked(True)
    panel.fader.setValue(-3.)
    assert page._project_gain_preview == -3. and project_gain_db(page.project) == 0.
    panel.fader.editFinished.emit()
    assert project_gain_db(page.project) == -3. and page._project_gain_preview is None
    assert panel.gain_spin.value() == -3. and panel.reset.isVisibleTo(panel)
    panel.reset.click()
    assert project_gain_db(page.project) == 0. and page.undo_stack.count() == 2
    panel.reject()


def test_the_toolbar_buttons_show_loudness_and_group_state(app, tmp_path):
    from twobyteasr.playback.project_loudness import baseline_identity
    from twobyteasr.studio.toolbar_audio_buttons import LoudnessButton, SecondaryRolesButton
    project = _project(tmp_path)
    page = _page(project)
    button = LoudnessButton(page)
    button.refresh()
    assert button.readout is None and button.width() <= 40
    page._loudness_cache = {baseline_identity(project): dict(integrated=-12.4, true_peak=-0.8)}
    button.refresh()
    assert button.readout == (-12.4, -0.8, -14.) and '−12.4' in button.toolTip() and button.width() > 40
    assert button.grab().size() == button.size()
    group = SimpleNamespace(project=project, _group_members=('a', 'b', 'c'), _group_expanded=False,
                            _group_header_state=lambda: (False, False))
    page.timeline = group
    roles = SecondaryRolesButton(page)
    roles.refresh()
    assert roles.signature == (3, 'collapsed') and '3' in roles.toolTip()
    group._group_header_state = lambda: (True, False)
    roles.refresh()
    assert roles.signature == (3, 'hidden')
    page.timeline = SimpleNamespace(project=project, _group_members=())
    roles.refresh()
    assert roles.signature == (0, 'none')
    roles.grab()


def test_app_icons_render_through_the_themed_icon_helpers(app):
    from twobyteasr.design.app_icons import BODIES, is_app_icon
    from twobyteasr.design.themed_icons import cached_icon_pixmap, colored_icon, themed_icon
    for key in BODIES:
        name = 'app.' + key
        assert is_app_icon(name)
        image = themed_icon(name, 'accent').pixmap(QSize(24, 24)).toImage()
        assert not image.isNull() and any(image.pixelColor(x, y).alpha() for x in range(24) for y in range(24))
        assert not colored_icon(name, '#c4532c').pixmap(20, 20).isNull()
        assert not cached_icon_pixmap(name, '#271f18', QSize(18, 18), device_pixel_ratio=2.).isNull()
    assert not is_app_icon('fa5s.cog') and not is_app_icon('app.nothing')


def test_the_ask_bunny_button_is_a_pill_with_or_without_words(app):
    from twobyteasr.app.ask_bunny_button import AskBunnyButton
    full, compact = AskBunnyButton('问问兔白'), AskBunnyButton('')
    assert full.sizeHint().width() > compact.sizeHint().width() + 40
    clicks = []
    full.clicked.connect(lambda: clicks.append(1))
    full.show(); app.processEvents()
    QTest.mouseClick(full, Qt.MouseButton.LeftButton)
    assert clicks == [1] and not full.grab().isNull()
    full.hide()
    assert not full._breath.isActive()
