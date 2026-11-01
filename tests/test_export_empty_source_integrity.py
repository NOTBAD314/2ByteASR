"""A historical clear needs a current explicit review before it can be skipped."""
from pathlib import Path
from dataclasses import replace
import pytest
from tests.test_static_caption_empty_pixels import fixture
from twobyteasr.exports.caption_integrity import require_confirmed_empty_sources
from twobyteasr.exports.export_timeline import export_project_snapshot
from twobyteasr.subtitle_rules.current_issues import DECISIONS,reviewed_version


def damaged(project):
    cue=project.cues[0]
    cue.original_text=cue.text
    cue.text=''
    return cue


def test_uncertain_historical_empty_blocks_snapshot_without_restoring_text(fixture):
    app,project,ffmpeg,job=fixture;cue=damaged(project)
    with pytest.raises(ValueError,match='visible-a.*明确审核确认'):
        export_project_snapshot(project)
    assert cue.text=='' and cue.original_text=='Visible'


def test_advanced_empty_reject_preserves_prior_output_and_retry_after_review(fixture):
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
    import av
    app,project,ffmpeg,job=fixture;cue=damaged(project)
    Path(job.output_path).write_bytes(b'prior output')
    job=replace(job,overwrite_existing=True)
    with pytest.raises(ValueError,match='visible-a'):
        AdvancedRendererBackend().render(project,ffmpeg,job)
    assert Path(job.output_path).read_bytes()==b'prior output'
    project.studio_state[DECISIONS]={'reviewed:'+cue.id:dict(status='resolved',input_version=reviewed_version(project,cue))}
    AdvancedRendererBackend().render(project,ffmpeg,job)
    with av.open(job.output_path) as result:assert len(list(result.decode(video=0)))==30
    assert cue.text==''


def test_old_review_does_not_authorize_a_later_clear(fixture):
    app,project,ffmpeg,job=fixture;cue=project.cues[0]
    project.studio_state[DECISIONS]={'reviewed:'+cue.id:dict(status='resolved',input_version=reviewed_version(project,cue))}
    damaged(project)
    with pytest.raises(ValueError):require_confirmed_empty_sources(project)


def test_originally_blank_hidden_and_outside_range_are_not_misclassified(fixture):
    app,project,ffmpeg,job=fixture
    require_confirmed_empty_sources(project)
    cue=damaged(project)
    require_confirmed_empty_sources(project,start_ms=600,end_ms=1000)
    project.studio_state['subtitle_track_visibility']={cue.speaker_id:False}
    require_confirmed_empty_sources(project)
    project.studio_state['subtitle_track_visibility']={}
    cue.original_text=''
    require_confirmed_empty_sources(project)


def test_translation_only_checks_original_only_when_the_original_will_be_shown(fixture):
    app,project,ffmpeg,job=fixture;cue=damaged(project)
    project.studio_state['bilingual']={'mode':'translation'}
    project.generation_metadata['translations']={cue.id:'Visible translation'}
    require_confirmed_empty_sources(project)
    project.generation_metadata['translations'][cue.id]=''
    with pytest.raises(ValueError):require_confirmed_empty_sources(project)
