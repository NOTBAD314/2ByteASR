import pytest
from subtitle_core import SpeechSegment
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
from twobyteasr.subtitle_rules import polishing


def patch(text, source, target, *, reference='', original='', lexicon=()):
    decisions=[]
    context=RuntimeContext(task_language='it')
    context.correction_lexical_words=lexicon
    with activate_runtime_context(context):
        result,applied=apply_correction_edits(text, [], [dict({'from':source,'to':target})],
            independent_sources=[('review',reference)] if reference else [], moss_text=original, decisions=decisions)
    return result,applied,decisions


def test_authoritative_word_boundaries_restore_visible_text():
    text='È sost an zial mente vero'
    result,applied,decisions=patch(text,'sost an zial mente','sostanzialmente', original='È sostanzialmente vero')
    assert result=='È sostanzialmente vero' and len(applied)==1 and decisions==[]


def test_same_letters_alone_do_not_authorize_arbitrary_join():
    assert patch('Vado a casa','a casa','acasa')[0]=='Vado a casa'
    assert patch('Vado a casa','a casa','acasa',lexicon={'vado','a','casa','acasa'})[0]=='Vado a casa'
    assert not patch('Vado a casa','a casa','acasa',original='Vado a casa')[1]


def test_multiple_original_word_boundaries_and_distinct_positions_are_independent():
    with activate_runtime_context(RuntimeContext(task_language='it')):
        corrected,applied=apply_correction_edits('Kim i Anton elli',[],[
            {'from':'Kim i','to':'Kimi','start':0,'end':5},
            {'from':'Anton elli','to':'Antonelli','start':6,'end':16}],
            independent_sources=[],moss_text='Kimi Antonelli')
        assert corrected=='Kimi Antonelli' and len(applied)==2
        corrected,applied=apply_correction_edits('sost anzialmente, sost anzialmente',[],[
            {'from':'sost anzialmente','to':'sostanzialmente','start':0,'end':16},
            {'from':'sost anzialmente','to':'sostanzialmente','start':18,'end':34}],
            independent_sources=[],moss_text='sostanzialmente, sostanzialmente')
        assert corrected=='sostanzialmente, sostanzialmente' and len(applied)==2


def test_lexical_fragment_join_needs_task_word_evidence():
    assert patch('è sost anzialmente vero','sost anzialmente','sostanzialmente',
                 lexicon={'sostanzialmente','vero'})[0]=='è sostanzialmente vero'


@pytest.mark.parametrize('source,target',[('e','è'),('si','sì')])
def test_semantic_accents_are_not_format_equivalence(source,target):
    original=f'Questo {source} vero'
    assert not patch(original,source,target)[1]
    assert patch(original,source,target,reference=f'Questo {target} vero')[1]


def test_one_independent_local_sentence_can_support_ordinary_spelling():
    assert patch('la vetturra corre','vetturra','vettura',reference='la vettura corre')[0]=='la vettura corre'
    assert not patch('la vetturra corre','vetturra','vettura',reference='in un altro posto vettura')[1]


def test_apostrophe_glyph_and_adjacent_spaces():
    assert patch('Prendi l ’ acqua', 'l ’ acqua', "l'acqua")[0]=="Prendi l'acqua"


@pytest.mark.parametrize('text,source,target',[
    ('Non è vero','Non è','è'), ('giro 49','49','50'), ('Charles Leclerc','Leclerc','Hamilton')])
def test_high_risk_changes_stay_protected(text,source,target):
    assert not patch(text,source,target,reference=text.replace(source,target))[1]


def test_no_change_and_duplicate_patch_are_completed_states():
    result,applied,decisions=patch('la vettura corre','vettura','vettura')
    assert result=='la vettura corre' and not applied
    assert decisions[0]['state']=='completed_no_change'
    with activate_runtime_context(RuntimeContext(task_language='it')):
        decisions=[]
        result,applied=apply_correction_edits('è sost anzialmente vero',[],
            [{'from':'sost anzialmente','to':'sostanzialmente'}]*2,
            independent_sources=[],moss_text='è sostanzialmente vero',decisions=decisions)
    assert len(applied)==1 and decisions[0]['state']=='already_applied'


def test_bad_patch_does_not_discard_disjoint_valid_patch():
    text='va va vetturra'
    segment=SpeechSegment(1,0.,2.,text,.8,[])
    failures=polishing.CueValidationFailures()
    value=polishing._validate_polish_response({'checked_ids':[1],'cues':[{'id':1,'edits':[
        {'from':'va','to':'vai','start':2,'end':4},
        {'from':'vetturra','to':'vettura','start':6,'end':14}]}]},[segment],1,failures)
    assert not failures
    assert value['cues'][0]['edits']==[{'from':'vetturra','to':'vettura','start':6,'end':14}]
    assert failures.rejected_patches[1][0]['reason']=='ambiguous_source_quote'


def test_schema_invalid_patch_is_local_when_cue_identity_is_valid():
    segment=SpeechSegment(1,0.,2.,'vetturra',.8,[])
    failures=polishing.CueValidationFailures()
    value=polishing._validate_polish_response({'checked_ids':[1],'cues':[{'id':1,'edits':[
        {'from':'vetturra','to':3}, {'from':'vetturra','to':'vettura'}]}]},[segment],1,failures)
    assert not failures and value['cues'][0]['edits']==[{'from':'vetturra','to':'vettura'}]
    assert failures.rejected_patches[1][0]['reason']=='edit_schema_invalid'


def test_partial_batch_cache_keeps_success_and_failure_states(tmp_path,monkeypatch):
    from twobyteasr.recognition import cache
    monkeypatch.setattr(cache,'cache_stage_signature',lambda *a,**k:'signature-v1')
    context=RuntimeContext()
    calls=[]
    def runner():
        calls.append('request')
        return polishing.PolishBatchResult({1:'correct',2:'original'},succeeded={1},failures={2:'semantic_validation'})
    with activate_runtime_context(context):
        args=('polished',{'identity':'test','cache_dir':str(tmp_path)},{'input':'frozen'},runner)
        cache.run_cached_api_batch(*args,encoder=polishing._encode_polish_batch,decoder=polishing._decode_polish_batch)
        value=cache.run_cached_api_batch(*args,encoder=polishing._encode_polish_batch,decoder=polishing._decode_polish_batch)
    assert calls==['request'] and value.succeeded=={1} and value.failures=={2:'semantic_validation'}
