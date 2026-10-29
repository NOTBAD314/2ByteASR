import copy,json
from pathlib import Path
import pytest
from scripts.author_balatro_candidates import candidates
from twobyteasr.caption_design.authored_partial import retained_candidate_prefix,retained_response_record
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,digest


def partial_body():
    rows=candidates();source=rows[2]['generated_source']
    rows[2]['generated_source']={k:copy.deepcopy(source.get(k,{} if k in ('appearance','palette') else ''))
        for k in ('id','name','appearance','palette','stageHtml','stageCss')}
    base=json.dumps({'candidates':rows},ensure_ascii=False)
    # Drop generated_source, candidate, array and envelope closing delimiters,
    # then begin an incomplete HTML string; no closing delimiters are invented.
    raw=base[:-4]+',"cueHtml":"<div class=\\"incomplete'
    return raw,rows


def test_retained_prefix_does_not_invent_missing_source_or_change_peers():
    raw,rows=partial_body();value=retained_candidate_prefix(raw)
    assert value['candidates']==rows
    assert 'cueHtml' not in value['candidates'][2]['generated_source']
    assert 'motionSpec' not in value['candidates'][2]['generated_source']


@pytest.mark.parametrize('mutate',[
    lambda text:'{"unrelated":'+text,
    lambda text:'{"candidates":[{"id":"unfinished',
])
def test_insufficient_or_unrelated_prefix_stays_failed(mutate):
    raw,_=partial_body()
    with pytest.raises(ValueError):retained_candidate_prefix(mutate(raw))


def test_one_or_two_complete_rows_survive_without_inventing_missing_rows():
    rows=candidates()
    for count in (1,2,3):
        raw='{"candidates":['+','.join(json.dumps(r) for r in rows[:count])+',{"id":"unfinished'
        assert retained_candidate_prefix(raw)=={'candidates':rows[:count]}


def test_recovery_receipt_keeps_failed_original_and_checks_hash(tmp_path):
    raw,_=partial_body();ledger=ThemeLedger(tmp_path,'Balatro')
    ledger.value['partial_body']={'sha256':digest(raw),'completed':False};ledger.save()
    (tmp_path/'provider-partial.txt').write_text(raw,'utf8')
    (tmp_path/'provider-invocation.json').write_text(json.dumps(dict(provider_id='fixture',model='same-model')),'utf8')
    before=(tmp_path/'ledger.json').read_bytes();record=retained_response_record(ledger)
    assert record['completed'] is False and record['model']=='same-model'
    assert (tmp_path/'ledger.json').read_bytes()==before
    (tmp_path/'provider-partial.txt').write_text(raw+'bad','utf8')
    with pytest.raises(ValueError,match='已改变'):retained_response_record(ledger)


def test_explicit_retry_preserves_incomplete_identity_and_windows_newline_receipt(tmp_path):
    from twobyteasr.caption_design.authored_visual_revision import saved_payload
    raw,rows=partial_body();raw=raw.replace(',"cueHtml"','\n,"cueHtml"')
    ledger=ThemeLedger(tmp_path,'Balatro')
    ledger.raw_response(raw,'fixture','same-model',completed=False)
    assert ledger.value['raw_response']['completed'] is False
    assert Path(ledger.value['raw_response']['path']).name=='provider-partial.txt'
    assert saved_payload(ledger)=={'candidates':rows}
    ledger.value.pop('raw_response');ledger.value['partial_body']={'sha256':digest(raw),'completed':False}
    (tmp_path/'provider-invocation.json').write_text(json.dumps(dict(provider_id='fixture',model='same-model')),'utf8')
    actual=raw.replace('\n','\r\n').encode('utf8');(tmp_path/'provider-partial.txt').write_bytes(actual)
    assert retained_response_record(ledger)['sha256']==digest(actual)
