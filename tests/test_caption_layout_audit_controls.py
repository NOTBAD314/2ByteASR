"""Exercise real combo data and saved export preferences without a desktop."""
import json

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox

from twobyteasr.acceptance.caption_layout_audit import (
    check_video_dimensions, select_combo_value, select_output_resolution, snapshot_layout_receipt,
)
from twobyteasr.exports import studio_export_ui
from twobyteasr.exports.export_timeline import export_project_snapshot
from twobyteasr.exports.output_caption_layout import layout_snapshots
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def make_workspace(tmp_path, monkeypatch, saved=None):
    settings = QSettings(str(tmp_path/'preferences.ini'), QSettings.Format.IniFormat)
    if saved is not None:
        settings.setValue('render/preferences_v1', json.dumps(saved))
    monkeypatch.setattr(studio_export_ui, 'QSettings', lambda *_: settings)
    project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=3000, width=1920, height=1080),
        cues=[StudioCue('cue', 0, 3000, '输出比例改变时，字幕必须按新的画布宽度重新排版。')])
    workspace = studio_export_ui.StudioExportWorkspace(project, str(tmp_path/'preview.ass'))
    QApplication.processEvents()  # run the normal deferred preference restore
    return workspace, settings


def test_combo_selection_uses_structural_tuple_value():
    combo = QComboBox()
    combo.addItem('source', tuple([0, 0]))
    combo.addItem('custom', tuple([-1, -1]))
    desired = tuple([-1, -1])  # a new Python object, as in the real audit module
    selected = select_combo_value(combo, desired)
    assert selected['index'] == 1
    assert tuple(combo.currentData()) == desired
    with pytest.raises(AssertionError, match='not found'):
        select_combo_value(combo, (540, 960))
    assert tuple(combo.currentData()) == desired  # a missing value never clears the selection


def test_audit_selects_real_custom_dimensions_and_output_snapshot(tmp_path, monkeypatch):
    workspace, _ = make_workspace(tmp_path, monkeypatch)
    receipt = select_output_resolution(workspace, 540, 960)
    assert tuple(workspace.resolution.currentData()) == (-1, -1)
    assert receipt['settings'] == [540, 960]
    assert workspace._output_layout_project._output_canvas['output'] == [540, 960]
    assert workspace._output_layout_project._output_canvas['design'] == [608, 1080]
    snapshots = layout_snapshots(workspace._output_layout_project)
    assert all(snapshot.resolution == (540, 960) for snapshot in snapshots)
    assert snapshots[0].resolved_caption.line_count > 1
    workspace.close(); workspace.deleteLater(); QApplication.processEvents()


@pytest.mark.parametrize('resolution,custom_size', [((-1, -1), (540, 960)), ((1280, 720), None)])
def test_saved_resolution_restores_by_value_after_reopening(tmp_path, monkeypatch, resolution, custom_size):
    first, settings = make_workspace(tmp_path, monkeypatch)
    if custom_size:
        select_output_resolution(first, *custom_size)
    else:
        select_combo_value(first.resolution, tuple(list(resolution)))
    first._confirm_export_preferences()
    saved = json.loads(settings.value('render/preferences_v1'))
    assert saved['resolution'] == list(resolution)
    first.close(); first.deleteLater(); QApplication.processEvents()
    second, _ = make_workspace(tmp_path, monkeypatch)
    assert tuple(second.resolution.currentData()) == resolution
    settings_value = second._render_settings(commit=False)
    assert (settings_value.width, settings_value.height) == (custom_size or resolution)
    if custom_size:
        assert second._output_layout_project._output_canvas['design'] == [608, 1080]
    second.close(); second.deleteLater(); QApplication.processEvents()


@pytest.mark.parametrize('invalid', [None, 'invalid', [1920], 720])
def test_invalid_old_resolution_does_not_abort_preference_restore(tmp_path, monkeypatch, invalid):
    workspace, settings = make_workspace(tmp_path, monkeypatch,
        {'resolution': invalid, 'bitrate': 14000, 'custom_resolution_width': 540, 'custom_resolution_height': 960})
    workspace._restore_export_preferences()  # must not throw inside or outside its Qt callback
    assert tuple(workspace.resolution.currentData()) == (0, 0)
    assert workspace.bitrate.value() == 14000
    assert workspace.custom_resolution_width.value() == 540
    assert json.loads(settings.value('render/preferences_v1'))['resolution'] == invalid
    workspace.close(); workspace.deleteLater(); QApplication.processEvents()


def test_probe_verification_rejects_a_file_with_wrong_dimensions():
    actual = {'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080}]}
    assert not check_video_dimensions(actual, [540, 960])
    assert check_video_dimensions(actual, [1920, 1080])
    assert not check_video_dimensions({'streams': []}, [1920, 1080])


@pytest.mark.parametrize('bilingual', [False, True])
def test_preview_receipt_identity_matches_composition_output_canvas(bilingual):
    from twobyteasr.rendering.advanced_renderer import compile_composition_data
    project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=3000, width=1920, height=1080),
        cues=[StudioCue('cue', 0, 3000, '输出字幕排版应和最终视频保持相同断行。')])
    project.style_recipes['default'] = {'engine': 'remotion', 'name': 'audit',
        'motion': {'mode': 'explicit', 'entrance': {'type': 'letter_stagger', 'duration_ms': 300}}}
    if bilingual:
        project.studio_state['bilingual'] = {'mode': 'bilingual'}
        project.generation_metadata['translations'] = {'cue': 'Shared output layout and exact line breaks.'}
        project.cues[0].appearance_override['text_marks'] = [{'start': 2, 'end': 5, 'bold': True}]
        project.cues[0].effect_id = 'rich'
        project.effects['rich'] = {'entry': {'type': 'char_rise', 'duration': 400}}
    frozen = export_project_snapshot(project, width=540, height=960)
    preview = {row['cue_id']: row for row in snapshot_layout_receipt(layout_snapshots(frozen))}
    props = compile_composition_data(frozen, width=540, height=960, fps=30, start_seconds=0, duration_seconds=3)
    assert len(preview) == len(props['cues']) == (2 if bilingual else 1)
    for cue in props['cues']:
        expected = preview[cue['id']]
        assert expected['snapshot_hash'] == cue['snapshotHash']
        assert expected['text'] == cue['text']
        assert expected['layout'] == cue['layout']
