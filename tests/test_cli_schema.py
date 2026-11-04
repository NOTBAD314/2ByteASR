import copy
import jsonschema
from twobyteasr.providers.cli_schema import re2_schema
from twobyteasr.caption_design.theme_metadata import NAME_SCHEMA
from twobyteasr.caption_design.caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA,ThemeLedger

def test_name_projection_retains_empty_space_and_control_rejection():
    original=copy.deepcopy(NAME_SCHEMA);projected=re2_schema(original)
    for name,valid in [('方向',True),(' Direction ',True),('',False),('  ',False),('a\nb',False),('\x00',False)]:
        assert jsonschema.Draft202012Validator(projected).is_valid(name)==valid
        assert jsonschema.Draft202012Validator(original).is_valid(name)==valid
    assert NAME_SCHEMA==original

def test_full_authored_schema_no_native_lookahead_and_local_url_policy_kept():
    import json
    original=copy.deepcopy(AUTHORED_OUTPUT_SCHEMA)
    assert '(?!' not in json.dumps(re2_schema(original))
    assert original==AUTHORED_OUTPUT_SCHEMA
    from twobyteasr.caption_design.web_theme import sanitize_css
    import pytest
    with pytest.raises(ValueError):sanitize_css('.x{background:url(https://example.com/a.png)}',section='cue')


def test_projection_delegates_negation_without_rejecting_valid_svg_texture():
    from twobyteasr.providers.cli_schema import request_schema
    from twobyteasr.caption_design.authored_theme_contract import CSS_SCHEMA
    projected, receipt = request_schema(CSS_SCHEMA)
    assert receipt['local_only_constraints'] == []
    assert jsonschema.Draft202012Validator(projected).is_valid('.x{color:#fff}')
    assert jsonschema.Draft202012Validator(projected).is_valid('.x{background:url("data:image/svg+xml,%3Csvg%3E")}')
    # The transport is advisory; the authoritative contract still rejects URLs.
    assert not jsonschema.Draft202012Validator(CSS_SCHEMA).is_valid('.x{background:url(https://evil.invalid/a)}')


def test_invalid_schema_is_rejected_before_provider_process():
    import pytest
    from twobyteasr.providers.cli_schema import request_schema, preflight_request_schema
    with pytest.raises(ValueError):preflight_request_schema({'pattern':'(?!unsafe)'})
    with pytest.raises(Exception):request_schema({'type':'string','pattern':'['})
    for pattern in (r'(?<=x)y', r'(x)\1', r'(?P<name>x)'):
        wire, receipt=request_schema({'not':{'pattern':pattern}})
        assert wire == {} and receipt['local_only_constraints'] == ['$/not']

def test_theme_labels_are_preserved_as_unreviewed_evidence(tmp_path):
    import pytest
    ledger=ThemeLedger(tmp_path,'Minecraft像素风格')
    ledger.stage('art_direction_contract',{'theme':'Minecraft草地方块小场景'},require_semantics=True)
    # The design_spec schema has no required duplicate theme label. Its
    # source remains bound to the accepted art contract and raw brief hash.
    ledger.stage('design_spec',{'core_metaphor':'草土浮岛'},require_semantics=True)
    ledger.stage('art_direction_contract',{'theme':'terminal'},require_semantics=True)
    assert ledger.value['theme']=='Minecraft'
    assert ledger.value['stages'][-1]['author_theme']=='terminal'
    assert ledger.value['stages'][-1]['semantic_review']=='pending'
