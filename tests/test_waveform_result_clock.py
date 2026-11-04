"""Asynchronous waveform completion must preserve the committed media clock."""
from types import SimpleNamespace

import pytest

from twobyteasr.recognition.recognition_result import media_identity_for_task, stamp_result, verify_result_reference
from twobyteasr.projects.studio_project import MediaAsset, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline


def timeline(project):
    return SimpleNamespace(project=project, waveform_caches={}, update=lambda: None)


def cache(source, duration):
    return SimpleNamespace(metadata=SimpleNamespace(source_path=str(source), duration_ms=duration))


@pytest.mark.parametrize('waveform_duration', [67664, 70000, 60000])
def test_late_waveform_cannot_change_exact_saved_recognition_clock(tmp_path, waveform_duration):
    source = tmp_path/'same.mp4'
    source.write_bytes(b'isolated identity input')
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=67653),
        media_pool=[MediaAsset(asset_id='input', canonical_source=str(source), duration_ms=67653)])
    reference = stamp_result(project, tmp_path/'new.2byteproj', job_id='new-job',
        media_identity=media_identity_for_task(source))
    widget = timeline(project)
    ready = cache(source, waveform_duration)

    WaveformTimeline.set_cache(widget, ready)

    assert project.media.duration_ms == project.media_pool[0].duration_ms == 67653
    assert widget.waveform_caches['input'] is ready
    assert verify_result_reference(reference, project=project) is project


def test_waveform_can_fill_an_unknown_legacy_duration(tmp_path):
    source = tmp_path/'unknown.mp4'
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=0),
        media_pool=[MediaAsset(asset_id='unknown', canonical_source=str(source), duration_ms=0)])
    widget = timeline(project)

    WaveformTimeline.set_cache(widget, cache(source, 12000))

    assert project.media.duration_ms == project.media_pool[0].duration_ms == 12000


def test_other_asset_waveform_never_changes_primary_clock(tmp_path):
    primary, secondary = tmp_path/'primary.mp4', tmp_path/'secondary.mp4'
    project = SubtitleProject(media=StudioMedia(path=str(primary), duration_ms=67653),
        media_pool=[MediaAsset(asset_id='secondary', canonical_source=str(secondary), duration_ms=0)])

    WaveformTimeline.set_cache(timeline(project), cache(secondary, 80000))

    assert project.media.duration_ms == 67653
    assert project.media_pool[0].duration_ms == 80000
