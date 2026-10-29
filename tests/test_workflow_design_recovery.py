import copy
import pytest
from twobyteasr.caption_design.authored_html import html_problems
from twobyteasr.caption_design.web_theme import sanitize_html
from twobyteasr.caption_design.authored_repair import apply_patch_transaction


def test_declared_inline_svg_noise_and_merge_are_preserved():
    source = '<svg><defs><filter id="grain"><feTurbulence seed="12"/><feMerge><feMergeNode in="SourceGraphic"/></feMerge></filter></defs></svg>'
    assert not html_problems(source)
    assert 'seed="12"' in sanitize_html(source, section='cue')


@pytest.mark.parametrize('value', ['-1', '4097', 'NaN', '1.5'])
def test_inline_noise_seed_is_bounded(value):
    source = f'<svg><filter id="grain"><feTurbulence seed="{value}"/></filter></svg>'
    assert html_problems(source)
    with pytest.raises(ValueError): sanitize_html(source, section='cue')


def test_relative_repair_path_only_resolves_exact_candidate_leaf():
    payload = {'candidates':[{'name':'A'}, {'name':'B'}]}
    issue = {'candidate_index':1, 'path':'candidates[1].name', 'replacement_schema':{'type':'string'}}
    response = {'patches':[{'candidate_index':1, 'path':'name', 'value':'修复B'}]}
    original = copy.deepcopy(response)
    fixed, changes = apply_patch_transaction(payload, response, [issue])
    assert fixed['candidates'] == [{'name':'A'}, {'name':'修复B'}]
    assert changes == ['candidates[1].name'] and response == original
    for index, path in [(0, 'name'),(1,'candidates[0].name'),(1,'../name')]:
        with pytest.raises(ValueError):
            apply_patch_transaction(payload, {'patches':[{'candidate_index':index,'path':path,'value':'X'}]}, [issue])
