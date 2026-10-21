import pytest
from twobyteasr.caption_design.theme_generation_policy import authored_request_budget
from twobyteasr.providers.provider_input_budget import prepare_input,InputBudgetError


def test_reasoning_and_artwork_fit_without_mutating_settings():
    models={'ai_design_cli_timeout_seconds':300}
    tokens,limits=authored_request_budget('deepseek',models)
    assert tokens==48000 and limits.concepts==300 and limits.inactivity==240
    assert models=={'ai_design_cli_timeout_seconds':300}
    _,report=prepare_input([{'role':'user','content':'完整作品'}],max_tokens=tokens,operation='generate')
    assert report['passed'] and report['combined_token_reserve']<65536
    assert authored_request_budget('deepseek',models,candidate_count=1)[0]==32000


def test_explicit_deadline_and_other_providers_are_not_extended():
    assert authored_request_budget('deepseek',{},45)[1].concepts==45
    assert authored_request_budget('deepseek',{'ai_design_cli_timeout_seconds':900})[1].concepts==900
    tokens,limits=authored_request_budget('openai',{'ai_design_cli_timeout_seconds':300})
    assert tokens==24000 and limits.concepts==300
    with pytest.raises(InputBudgetError):
        prepare_input([{'role':'user','content':'patch'}],max_tokens=48000,operation='local_patch',scope={'allowed_paths':['cueCss']})
