import json

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import pytest

from twobyteasr.exports import studio_export_ui
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path/'config.ini'), QSettings.IniFormat)
    monkeypatch.setattr(studio_export_ui, 'QSettings', lambda *args:settings)
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices', lambda *args:['libx264'])
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'中文 源.mp4'), duration_ms=159400,
        width=1920, height=1080))
    ui = StudioExportWorkspace(project, str(tmp_path/'preview.ass'))
    yield ui
    ui.close(); ui.deleteLater(); app.processEvents()


@pytest.mark.parametrize('target', [5000, 10000, 20000])
def test_manual_target_overrides_recommended_and_commits_pending_editor(workspace, tmp_path, target):
    ui = workspace
    ui.quality.setCurrentIndex(ui.quality.findData('recommended'))
    ui.rate_control.setCurrentIndex(ui.rate_control.findData('target'))
    ui.bitrate.lineEdit().setText(f'{target} kbps')  # Intentionally no focus-out event.
    settings = ui._render_settings()
    assert ui.quality.currentData() == 'custom'
    assert ui.preset.currentData() == 'custom'
    assert settings.quality_mode == 'target'
    assert settings.bitrate_kbps == target
    job = ui._job(tmp_path/'out.mp4', settings=settings)
    ui.bitrate.setValue(999)
    assert job.settings.bitrate_kbps == target
    assert job.export_context['requested_encoder'] == 'auto'
    assert job.export_context['project_revision'].startswith('sha256:')
    assert job.export_context['requested_settings']['bitrate_kbps'] == target


def test_user_preset_restores_mode_maxrate_resolution_and_manual_quality(workspace):
    ui = workspace
    ui._apply_preset_payload(dict(id='user-example', user=True, encoder='libx264',
        codec='h264', container='mp4', quality_mode='limited', quality=23,
        bitrate_kbps=20000, max_bitrate_kbps=30000, resolution=[1280,720], fps=60))
    result = ui._render_settings()
    assert (result.quality_mode, result.quality, result.bitrate_kbps, result.max_bitrate_kbps) == ('limited',23,20000,30000)
    assert (result.width,result.height,result.fps) == (1280,720,60)
    assert '20000 kbps' in ui.summary.text()
    ui.quality.setCurrentIndex(ui.quality.findData('recommended'))
    assert ui._render_settings().quality_mode == 'crf'
    assert ui._render_settings().quality == 20
    assert '随画面复杂度变化' in ui.estimated_size.text()


def test_saved_preferences_keep_target_after_reopen(workspace):
    ui = workspace
    ui.rate_control.setCurrentIndex(ui.rate_control.findData('target'))
    ui.bitrate.lineEdit().setText('10000 kbps')
    ui._confirm_export_preferences()
    payload = json.loads(ui._settings.value('render/preferences_v1'))
    ui.quality.setCurrentIndex(ui.quality.findData('recommended'))
    ui.bitrate.setValue(7000)
    ui._saved_export_preferences = payload
    ui._restore_export_preferences()
    assert ui._render_settings().quality_mode == 'target'
    assert ui._render_settings().bitrate_kbps == 10000


@pytest.mark.parametrize('measured,target_met', [(5000000,False),(None,None),(9900000,True)])
def test_success_reports_independent_video_rate_and_preserves_outside_target_file(workspace, tmp_path, measured, target_met):
    from twobyteasr.exports.studio_render import RenderJob
    ui = workspace
    output = tmp_path/'成片.mp4'; output.write_bytes(b'published')
    job = RenderJob('', '', str(output), ui._render_settings())
    job.completion_metadata.update(output_path=str(output.resolve()), elapsed_seconds=1,
        average_bitrate_bps=12000000, requested_video_bitrate_bps=10000000, bitrate_target_met=target_met,
        video_bitrate={'average_bitrate_bps':measured}, actual_rate_control='target')
    ui._last_job = job
    ui._show_success(str(output))
    assert '10000 kbps' in ui.success_meta.text()
    expected = '无法可靠测量' if measured is None else f'{measured / 1000:.0f} kbps'
    assert expected in ui.success_meta.text()
    assert not ui.success_page.error.isHidden() if target_met is not True else ui.success_page.error.isHidden()
    assert ui.success_page.values['平均码率'].text() == '12.0 Mb/s'
    assert output.read_bytes() == b'published'


def test_speed_choice_maps_to_numeric_svt_av1_presets(workspace, monkeypatch):
    ui = workspace
    assert ui._render_settings().preset == 'medium'  # Software x264 keeps its named presets.
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices',
        lambda _ffmpeg, codec: ['av1_nvenc', 'libsvtav1', 'libaom-av1'] if codec == 'av1' else ['libx264'])
    ui.codec.setCurrentIndex(ui.codec.findData('av1'))
    ui.encoder.setCurrentIndex(ui.encoder.findData('libsvtav1'))
    expected = {'fastest': '12', 'fast': '10', 'balanced': '8', 'quality': '6', 'best': '4'}
    for speed, preset in expected.items():
        ui.encoder_preset.setCurrentIndex(ui.encoder_preset.findData(speed))
        settings = ui._render_settings()
        assert (settings.encoder, settings.preset) == ('libsvtav1', preset)
    ui.encoder.setCurrentIndex(ui.encoder.findData('libaom-av1'))
    assert ui._render_settings().preset == ''
    ui.encoder.setCurrentIndex(ui.encoder.findData('av1_nvenc'))
    assert ui._render_settings().preset == 'p7'


def test_limited_average_and_maximum_are_independent_and_invalid_order_is_explicit(workspace):
    ui = workspace
    ui.rate_control.setCurrentIndex(ui.rate_control.findData('limited'))
    ui.bitrate.setValue(20000); ui.max_bitrate.setValue(10000)
    settings = ui._render_settings()
    assert settings.bitrate_kbps == 20000 and settings.max_bitrate_kbps == 10000
    with pytest.raises(ValueError, match='maximum bitrate'):
        settings.validate()


@pytest.mark.parametrize('language,requested_text,elapsed_text', [
    ('zh', '请求视频码率', '1 分 1.5 秒'),
    ('en', 'Requested video bitrate', '1 min 1.5 s'),
    ('ja', '指定映像ビットレート', '1分 1.5秒'),
])
def test_target_completion_dynamic_arguments_follow_language(workspace, tmp_path, monkeypatch,
                                                            language, requested_text, elapsed_text):
    from twobyteasr import i18n
    from twobyteasr.i18n_widgets import apply
    from twobyteasr.exports.studio_render import RenderJob
    monkeypatch.setattr(i18n, '_CURRENT_LANGUAGE_CACHE', language)
    ui = workspace
    output = tmp_path/'out.mp4'; output.write_bytes(b'published')
    job = RenderJob('', '', str(output), ui._render_settings())
    job.completion_metadata.update(output_path=str(output.resolve()), elapsed_seconds=61.5,
        requested_video_bitrate_bps=10000000, bitrate_target_met=None, actual_rate_control='target')
    ui._last_job = job
    ui._show_success(str(output))
    apply(ui.success_page, language)
    assert requested_text in ui.success_meta.text()
    assert elapsed_text in ui.success_meta.text()
    assert str(i18n.tr('无法可靠测量')) in ui.success_meta.text()
    assert str(i18n.tr('导出完成，视频码率无法可靠测量。成片与诊断信息已保留。')) == ui.success_page.error.text()
    assert output.read_bytes() == b'published'


def test_auto_uses_a_verified_hardware_encoder_first(workspace, monkeypatch):
    """2026-10-28 (users: burning is slow): "auto" used to pick libx264 whenever
    it existed, so a verified NVENC never ran and the recommended preset's CQ
    became CRF. Now it follows the capability order: hardware first."""
    ui = workspace
    assert ui._render_settings().encoder == 'libx264'   # software only: unchanged
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices',
                        lambda _ffmpeg, codec: {'h264': ['h264_nvenc', 'h264_amf', 'libx264']}.get(codec, []))
    ui.preset.setCurrentIndex(ui.preset.findData('recommended'))
    ui._encoder_changed()
    settings = ui._render_settings()
    assert (settings.encoder, settings.quality_mode, settings.preset) == ('h264_nvenc', 'cq', 'p4')
    # The preset number (20) was always run as x264 CRF; NVENC needs +4 for that picture.
    assert settings.quality == 20 + studio_export_ui.AUTO_NVENC_CQ_OFFSET
    assert 'NVIDIA NVENC' in ui.actual_encoder_hint.text()
    ui._populate_encoders()
    ui.encoder.setCurrentIndex(ui.encoder.findData('h264_nvenc'))   # chosen by hand: the number as typed
    assert ui.encoder.currentData() == 'h264_nvenc'
    assert ui._render_settings().quality == 20
    ui.encoder.setCurrentIndex(ui.encoder.findData('auto'))
    # Quick Sync / AMF H.264 were not measured: auto keeps x264 there.
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices',
                        lambda _ffmpeg, codec: {'h264': ['h264_qsv', 'h264_amf', 'libx264']}.get(codec, []))
    assert ui._resolved_encoder() == 'libx264'
    # The HEVC / AV1 presets exist only with a hardware encoder; auto must use it,
    # and AV1 without one takes SVT-AV1, never the far slower libaom.
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices',
                        lambda _ffmpeg, codec: {'hevc': ['hevc_amf', 'libx265'],
                                                'av1': ['libsvtav1', 'libaom-av1']}.get(codec, []))
    ui.codec.setCurrentIndex(ui.codec.findData('hevc'))
    assert ui._resolved_encoder() == 'hevc_amf'
    ui.codec.setCurrentIndex(ui.codec.findData('av1'))
    assert ui._resolved_encoder() == 'libsvtav1'
    monkeypatch.setattr(studio_export_ui, 'cached_encoder_choices', lambda *_args: [])
    ui.codec.setCurrentIndex(ui.codec.findData('h264'))
    assert ui._resolved_encoder() == 'libx264'   # no capability scan yet
