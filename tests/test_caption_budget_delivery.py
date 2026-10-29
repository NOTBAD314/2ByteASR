import copy
import pytest
from twobyteasr.caption_design.authored_prompt import assemble, compact_context
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.providers.provider_input_budget import prepare_input, InputBudgetError


def test_compaction_removes_local_inventory_and_peers_without_truncating_intent(tmp_path):
    ledger=ThemeLedger(tmp_path,'保留多层边框、字面压印与完整进退场。')
    ledger.value['creative_context']=dict(subtitle_text='原文\n完整保留',user_locks={'color':'#FFF000'},
        installed_font_names=['irrelevant font']*10000,accepted_positive_references=[{'diagnostic':'x'*100000}])
    direction=dict(id='A',name='套印',design_spec={'design':'米色纸面、双层边界、字面压印。'},
        art_direction_contract={'old':'duplicated '*10000},generated_source={'cueHtml':'do not send'},peers=['B','C'])
    prior=copy.deepcopy(direction)
    prompt,receipt=assemble(ledger,direction=direction)
    assert direction==prior and ledger.value['raw_user_prompt'] in prompt
    assert '原文\\n完整保留' in prompt and '#FFF000' in prompt
    assert not any(v in prompt for v in ('irrelevant font','duplicated','do not send'))
    assert receipt['compaction']['before']['message_utf8_bytes']>receipt['message_utf8_bytes']*5
    assert prepare_input([dict(role='user',content=prompt)],operation='generate',max_tokens=10000)[1]['passed']


def test_unbounded_user_input_is_not_cut_or_silently_sent(tmp_path):
    raw='用户必须保留的要求。'*10000
    prompt,receipt=assemble(ThemeLedger(tmp_path,raw),direction={'name':'方向','design':'字面套印'})
    assert raw in prompt
    with pytest.raises(InputBudgetError) as error:
        prepare_input([dict(role='user',content=prompt)],operation='generate',max_tokens=10000)
    assert error.value.report['dispatched'] is False
    assert error.value.report['policy']['input_tokens']==16384


def test_sample_selection_uses_whole_records_and_preserves_explicit_newlines():
    samples=['短句','显式\n换行','中间代表句','第四句','末尾全文']
    assert compact_context({'subtitle_text':samples})['subtitle_text']==[samples[0],samples[2],samples[-1]]


@pytest.mark.parametrize('definition',[
    dict(version=2),dict(version=2,geometry='chamfer',surface='glass',border='rails',motion='stamp',lettering='offset'),
    dict(version=2,geometry='capsule',surface='print',border='prism',motion='relay',lettering='spectral')])
def test_independent_surface_axes_are_safe_portable_source(definition):
    from twobyteasr.caption_design.caption_components import compose
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    value=WebThemeDocument.from_dict(dict(name='本地能力验证',**compose(definition))).to_dict()
    assert '{{words}}' in value['cueHtml'] and value['motionSpec']['version']==2
    assert 'cap-registration' in value['cueHtml'] and 'cap-light' in value['cueHtml']
    assert not any(t in value['cueHtml'] for t in ('knight','joker','bear'))


def test_motion_ready_label_without_source_or_verified_preview_is_not_adoptable():
    from PySide6.QtWidgets import QApplication,QPushButton
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    app=QApplication.instance() or QApplication([])
    dialog=ThemeConceptDialog([dict(id='A',name='未完成',creative_version='test',motion_preview={'status':'motion_ready'})],{})
    assert not next(b for b in dialog.findChildren(QPushButton) if b.text()=='采用这个方向').isEnabled()


def test_compact_source_contract_keeps_phase_and_layout_semantics(tmp_path):
    """Real Grok response confused cue fractions with phase fractions and root origin."""
    prompt, _ = assemble(ThemeLedger(tmp_path, '复古对弈'), direction={
        'name': '历史方向', 'design_spec': {'shape': '左侧肖像窗，固定巨框'}})
    assert 'start/end是所属phase内部的比例' in prompt
    assert '5600..5920ms' in prompt
    assert '并不会自动把作者节点放到底部' in prompt
    assert '不可只将肖像替换成同样大小的装饰块' in prompt


def test_resolve_phase_example_matches_actual_clock():
    from twobyteasr.caption_design.motion_ownership import motion_schedule
    spec = dict(version=2, buildMs=600, resolveMs=400, tracks=[dict(
        selector='.text', phase='resolve', start=0, end=.8,
        **{'from': {'opacity': 1}, 'to': {'opacity': 0}})])
    row = motion_schedule(spec, 6000)[0]
    assert (row['start_ms'], row['end_ms']) == (5600, 5920)
