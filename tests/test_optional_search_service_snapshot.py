from types import SimpleNamespace
from tests.test_stage9_cache_and_budget import context  # noqa: F401
from twobyteasr.glossary.domain_terms import term_search_capability


def settings():
    return {'models': {'polish_provider': 'disabled', 'group_provider': 'disabled'},
            'switches': {'enable_ai_polish': False, 'use_ai_grouping': False}}


def test_disabled_unbound_service_does_not_fail_recognition(context):
    _core, owner, _cache = context
    owner.provider_snapshot = None
    owner.provider_snapshots = {}
    owner.asr_settings_snapshot = settings()
    owner.enable_term_search = True
    assert term_search_capability()['status'] == 'not_configured'


def test_search_uses_frozen_service_without_enabling_proofreading(context):
    _core, owner, _cache = context
    owner.asr_settings_snapshot = settings()
    owner.enable_term_search = True
    owner.provider_snapshots = {'polish': SimpleNamespace(kind='http', transport='openai_compatible',
        provider='bailian', model='fixture', endpoint=lambda: {'provider': 'bailian', 'model': 'fixture',
                                                                  'url': 'https://example.invalid', 'api_key': 'fixture'})}
    assert term_search_capability()['available']
    from twobyteasr.recognition.text_ai_plan import text_ai_plan
    assert 'polish' not in text_ai_plan(owner.asr_settings_snapshot).roles
