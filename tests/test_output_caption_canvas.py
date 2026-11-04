import copy

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.exports.export_timeline import export_project_snapshot, write_export_ass
from twobyteasr.exports.output_caption_layout import OutputCaptionLayoutPreview, layout_snapshots, require_layout_fit
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def project():
    return SubtitleProject(media=StudioMedia('unused.mp4', duration_ms=3000, width=1920, height=1080),
        styles=[SubtitleStyle('default', 'Base', font_family='Microsoft YaHei', font_size=72,
                              position_x=960, position_y=1000, shadow=0)],
        cues=[StudioCue('one', 0, 3000, '输出比例改变时保留字号，字幕按新画布宽度重新换行。')],
        render_settings={'play_res_x': 1920, 'play_res_y': 1080, '_cue_domain': 'timeline'})


def test_same_ratio_never_reflows_when_pixel_resolution_changes():
    p = project(); before = copy.deepcopy(p.to_dict())
    full = export_project_snapshot(p, width=1920, height=1080)
    half = export_project_snapshot(p, width=960, height=540)
    assert full.render_settings == half.render_settings
    assert build_visual_cue_snapshot(full, 'one').text == build_visual_cue_snapshot(half, 'one').text
    assert not half._output_canvas['relayout']
    assert half.styles[0].font_size == 72
    assert p.to_dict() == before


def test_new_aspect_reflows_width_and_preserves_height_font_and_anchor_fraction():
    p = project()
    p.cues[0].transform = {'initial_layout': {'version': 1, 'position_x': 960, 'position_y': 980},
                           'language_layers': {'translation': {'position_x': 720, 'position_y': 940}}}
    p.studio_state['caption_group_transform'] = {'dx': 120, 'dy': -10, 'sx': 1, 'sy': 1}
    before = copy.deepcopy(p.to_dict())
    output = export_project_snapshot(p, width=1080, height=1920)
    assert output.render_settings['play_res_y'] == 1080
    assert output.render_settings['play_res_x'] == 608
    assert output.styles[0].font_size == 72
    assert output.styles[0].position_x == 304
    assert output.styles[0].position_y == 1000
    assert output.cues[0].transform['initial_layout']['position_x'] == 304
    assert output.cues[0].transform['language_layers']['translation']['position_x'] == pytest.approx(228)
    assert output.studio_state['caption_group_transform']['dx'] == pytest.approx(38)
    assert output.media == p.media  # video geometry/source identity is independent
    assert len(build_visual_cue_snapshot(output, 'one').text.split('\n')) > len(build_visual_cue_snapshot(p, 'one').text.split('\n'))
    assert p.to_dict() == before


def test_output_preview_and_ass_share_the_derived_canvas(tmp_path):
    p = project()
    preview = export_project_snapshot(p, width=1080, height=1920)
    path = tmp_path/'export.ass'
    exported = write_export_ass(p, path, width=1080, height=1920, require_layout_fit=True)
    assert exported.render_settings == preview.render_settings
    assert layout_snapshots(exported)[0].resolved_caption.layout == layout_snapshots(preview)[0].resolved_caption.layout
    ass = path.read_text('utf-8-sig')
    assert 'PlayResX: 608' in ass and 'PlayResY: 1080' in ass
    assert r'\N' in ass


def test_impossible_output_layout_reports_failure_before_writing_ass(tmp_path):
    p = project(); p.styles[0].font_size = 4000
    target = tmp_path/'must-not-publish.ass'
    with pytest.raises(ValueError, match='超出输出画布'):
        write_export_ass(p, target, width=1080, height=1920, require_layout_fit=True)
    assert not target.exists()


def test_output_preview_owns_only_a_static_derived_view():
    p = project(); before = copy.deepcopy(p.to_dict())
    output = export_project_snapshot(p, width=1080, height=1920)
    widget = OutputCaptionLayoutPreview(); widget.show()
    widget.set_project(output, 1080, 1920, 1500)
    widget._draw()
    assert widget.image.pixmap() is not None and not widget.image.pixmap().isNull()
    assert widget.image.pixmap().height() > widget.image.pixmap().width()
    assert '重新换行' in widget.description.text()
    assert widget._last_ids == ('one',)
    assert not widget.property('layoutOverflow')
    widget.hide()
    assert not widget._timer.isActive()
    assert p.to_dict() == before
    widget.close()


def test_linear_output_canvas_resizes_before_burning_subtitles(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_render
    media = tmp_path/'source.mp4'; media.write_bytes(b'fixture')
    ass = tmp_path/'captions.ass'; ass.write_text('[Script Info]\nPlayResX: 608\nPlayResY: 1080\n')
    monkeypatch.setattr(studio_render, 'select_encoder', lambda *_: 'libx264')
    job = studio_render.RenderJob(str(media), str(ass), str(tmp_path/'output.mp4'),
        settings=studio_render.RenderSettings(encoder='libx264', width=540, height=960, audio_codec='none'),
        duration_seconds=3, export_context={'caption_canvas': {'relayout': True}})
    command = studio_render.build_render_command('ffmpeg.exe', job)
    chain = command[command.index('-vf')+1]
    assert chain.index('scale=540:960') < chain.index('ass=filename')
    assert 'force_original_aspect_ratio=decrease,pad=540:960' in chain
