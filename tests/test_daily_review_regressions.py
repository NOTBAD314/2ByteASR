"""The reported FireRed tail, numeric receipts and missing-proof-only policy."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from twobyteasr.projects.studio_project import SubtitleProject
from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses
from twobyteasr.recognition.current_review import current_review
from twobyteasr.subtitle_rules.studio_review import store_review_risks
from twobyteasr.subtitle_rules.current_issues import current_issue_view
from twobyteasr.subtitle_rules.studio_qc import normalize_spoken_text


@pytest.fixture
def project():
    payload=json.loads((Path(__file__).parent/'fixtures/firered_projection_regression.json').read_text('utf8'))
    payload['project_id']='fire-red-regression-fixture'
    p = SubtitleProject.from_dict(payload)
    ensure_independent_captions(p)
    return p


@pytest.mark.parametrize('cue_id,expected', [('50','法务部已经紧急启动了'),('21','57'),('23','55')])
def test_original_receipts_survive_timeline_projection(project, cue_id, expected):
    cue = next(c for c in project.cues if c.id == cue_id)
    before = deepcopy(project.asr_evidence)
    rows = cue_source_hypotheses(project, cue)
    assert {r['text'] for r in rows} == {expected}
    assert {r['model'] for r in rows} == {'firered','asr-api:moss-transcribe-diarize-pro'}
    store_review_risks(project)
    assert current_issue_view(project).level(cue_id) == 'confident'
    assert project.asr_evidence == before


def test_actual_trim_does_not_pull_the_tail_back_from_receipt(project):
    cue = next(c for c in project.cues if c.id == '50')
    cue.end_ms = 299750
    rows = cue_source_hypotheses(project, cue)
    assert rows and all('了' not in r['text'] for r in rows)


def test_old_review_missing_proof_is_information_without_human_confirmation(project):
    project.studio_state['review_confirmations'] = {'21': {'user': 'existing'}}
    before = deepcopy(project.studio_state['review_confirmations'])
    report = dict(job_id='fixture',review_items=[
        dict(category='时间锚覆盖低', severity='review',cue_id='50', text=project.cues[-1].text),
        dict(category='边界待看', severity='review',cue_id='50',text=project.cues[-1].text,
             detail='句首与起音相差313ms')])
    view = current_review(project, report)
    assert not any(r['category']=='时间锚覆盖低' for r in view['items'])
    assert any(r['category']=='边界待看' for r in view['items'])
    assert project.studio_state['review_confirmations'] == before


@pytest.mark.parametrize('a,b', [('57','五十七'),('55','五十五'),('4.7','四点七'),('3.14','三点一四')])
def test_numeric_spelling_is_not_a_lexical_conflict(a,b):
    assert normalize_spoken_text(a) == normalize_spoken_text(b)


def test_firered_alternate_keeps_actual_producer_identity():
    from types import SimpleNamespace
    import subtitle_core  # normal application initialization owns this legacy bridge
    from twobyteasr.subtitle_rules.polishing import _independent_asr_sources
    s = SimpleNamespace(primary_source='api-primary',moss_text='',alternate_text='凶手',
                        firered_text='凶手',qwen_asr_text='')
    assert _independent_asr_sources(s,'凶手') == [('firered','凶手')]


def test_silence_marker_is_not_independent_transcript_evidence():
    from twobyteasr.recognition.caption_arbitration import usable_transcript
    assert not usable_transcript('<sil>')
    assert not usable_transcript('  ')
    assert usable_transcript('法务部已经紧急启动了')
