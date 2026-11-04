"""Source → empty project interval is an atomic clock-domain transition."""
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_video_canvas import MpvCanvas
from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia


def test_proxy_preview_target_keeps_asset_identity_for_source_clock_duration():
    project = SubtitleProject(media=StudioMedia(path='original.flv', duration_ms=3601848))
    project.validate()
    project.media_pool[0].offline = False
    host = SimpleNamespace(project=project, _preview_media_path=lambda _: 'continuous.mkv',
        _video_transform_preview_overrides={}, _video_effects_preview_overrides={})
    layers = StudioVideoFlowMixin._multitrack_preview_layers(host, 0)
    assert layers[0]['asset_id'] == project.media_pool[0].asset_id
    assert layers[0]['source_path'] == 'continuous.mkv'


def test_gap_handoff_emits_only_project_time_and_rejects_late_source_sample():
    app=QApplication.instance() or QApplication([])
    canvas=MpvCanvas()
    canvas.controller=SimpleNamespace(running=True,post_clear_media=lambda:True,
        observed_position=lambda:dict(position=3092.38,source_generation=0),observed_properties=lambda:{})
    canvas._media_attached=True;canvas._duration=3601.848
    canvas._playback_clock.force_position(3092380,paused=False)
    canvas._base_time=3092.38;canvas._paused=False
    seen=[];canvas.position_changed.connect(lambda value:seen.append(value*1000))
    canvas.enter_timeline_gap(3389,458655)
    assert seen and all(abs(value-3389)<1 for value in seen),seen
    assert canvas._clock_only and not canvas._media_attached
    canvas._observe_cached_video_clock()
    assert canvas.playback_position_snapshot().presentation_media_ms < 3500
    canvas._timer.stop();canvas._sync_timer.stop();canvas.controller=None
    canvas.close();canvas.deleteLater();app.processEvents()
