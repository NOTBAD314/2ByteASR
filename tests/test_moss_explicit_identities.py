import copy
from types import SimpleNamespace
import pytest
from twobyteasr.projects.studio_project import project_from_runtime_cues, load_project, save_project
from twobyteasr.recognition.speaker_recovery import candidate_snapshot
from twobyteasr.projects.speaker_organization import UNIFIED
from twobyteasr.recognition.speaker_evidence import label_summary


@pytest.mark.parametrize('mode', ['moss', 'single'])
def test_short_explicit_moss_keeps_low_frequency_identities_through_project_export(tmp_path, mode):
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    rows = [dict(start=i*2, end=i*2+1, text=f'人工文字{i} 20', speaker=f'S0{i%2+1}') for i in range(7)]
    evidence = candidate_snapshot(rows, source=mode)
    evidence['processing'] = {'mode': mode}
    cues = [SimpleNamespace(start=r['start'], end=r['end'], text=r['text'], speaker=r['speaker']) for r in rows]
    p = project_from_runtime_cues(str(tmp_path/'missing.wav'), cues,
        generation_metadata={'speaker_recovery': evidence})
    expected = {'S01', 'S02'}
    assert {c.speaker_id for c in p.cues} == expected
    assert [c.text for c in p.cues] == [r['text'] for r in rows]
    save_project(p, tmp_path/'project.2byteproj')
    reopened = load_project(tmp_path/'project.2byteproj')
    assert [(c.text,c.speaker_id,c.start_ms,c.end_ms) for c in reopened.cues] == [(c.text,c.speaker_id,c.start_ms,c.end_ms) for c in p.cues]
    outputs = export_subtitle_artifacts(reopened,tmp_path/'export','sample',SubtitleExportOptions(speaker_mode='per_speaker'))
    assert len(outputs) == len(expected)
    if mode == 'moss':
        assert set(evidence['roles'].values()) == {'unconfirmed'}
        assert len({s.name for s in reopened.speakers}) == 2


def test_summary_does_not_turn_missing_label_into_s00():
    result = label_summary([{'speaker':'S00'},{'speaker':'NEMO_00'},{'speaker':''},{}])
    assert result == {'labels':{'S00':1,'NEMO_00':1},'identity_count':2,'missing_labels':2}


@pytest.mark.parametrize('value',[None,'','[]','   '])
def test_moss_parser_missing_speaker_is_explicit_failure(value):
    from moss_worker import parsed_speaker_label
    with pytest.raises(RuntimeError,match='标签解析失败'):
        parsed_speaker_label(value,1)


def test_parser_preserves_valid_zero_and_distinct_labels():
    from moss_worker import parsed_speaker_label
    assert [parsed_speaker_label(v,1) for v in (0,'[S01]','[S02]')]==['0','S01','S02']


def test_moss_task_snapshot_retired_closed_setting_cannot_erase_native():
    import json
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.recognition.speaker_strategy import resolve
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['models']['speaker_source']='single'
    options=RunOptions(speaker_source='moss', settings_snapshot_json=json.dumps(settings))
    assert options.speaker_source=='moss'
    assert resolve(settings)=='moss'
