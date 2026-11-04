import pytest
from twobyteasr.providers.provider_input_budget import prepare_input,InputBudgetError
from twobyteasr.caption_design.authored_prompt import assemble
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger, AUTHORED_OUTPUT_SCHEMA


def test_soft_budget_requires_this_endpoint_evidence_and_hard_limit_wins():
    message=[{'role':'user','content':'中'*18200}]
    with pytest.raises(InputBudgetError):prepare_input(message,operation='generate',max_tokens=32000)
    _,report=prepare_input(message,operation='generate',max_tokens=32000,
        model_limits={'context_tokens':65536,'source':'same endpoint model metadata'})
    assert report['reallocated'] and report['safety_margin_tokens']==1024
    with pytest.raises(InputBudgetError):
        prepare_input(message,operation='generate',max_tokens=32000,
            model_limits={'context_tokens':65536,'source':'same endpoint'},user_limits={'input_tokens':16384})


def test_single_direction_preserves_requirement_without_history(tmp_path):
    ledger=ThemeLedger(tmp_path,'保留每一个需求字；让双板压印。')
    ledger.value['creative_context']={'subtitle_text':'真实正文','project_context':{'cue_duration_ms':1500},
        'material_direction':'无关旧重复说明','theme_authority':{'explicit_requirements':ledger.value['raw_user_prompt']}}
    schema=AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['properties']['generated_source']
    message,receipt=assemble(ledger,direction={'id':'A','name':'双板','MotionContract':{'entrance':'压印落定'}},schema=schema)
    assert message.count(ledger.value['raw_user_prompt'])==1
    assert '真实正文' in message and '1500' in message and '压印落定' in message
    assert '无关旧重复说明' not in message
    assert set(receipt['components']) >= {'user_requirement','design_direction','artifact_protocol','design_skills'}
    assert 'schema' not in receipt['components']
    _,report=prepare_input([{'role':'user','content':message}],schema=schema,operation='generate',max_tokens=32000)
    assert report['passed']
