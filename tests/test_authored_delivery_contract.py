"""Fresh provider delivery must describe the gates used by the real adapter."""
import copy
import json
from types import SimpleNamespace

import jsonschema
import pytest

from twobyteasr.caption_design import caption_creative_pipeline as pipeline
from twobyteasr.caption_design.web_theme import WebThemeDocument


def valid_source():
    return dict(name='明确的字幕', palette=dict(primary='#334455', text='#FFFFFF'),
        stageHtml='', stageCss='', cueHtml='<div class="caption">{{text}}</div>',
        cueCss='.caption{font-family:var(--wt-font);font-size:var(--wt-size)}',
        motionSpec=dict(version=1, runtime='gsap', tracks=[dict(selector='.caption',
            phase='build', **{'from': {'opacity': 0}, 'to': {'opacity': 1}})]))


@pytest.mark.parametrize('field,value', [
    ('stageHtml', '<div class="wt-stage"></div>'),
    ('palette', {'primary': '#334455'}),
    ('palette', {'primary': '#fff', 'text': '#FFFFFF'}),
    ('cueHtml', ''),
    ('cueHtml', '<div>fixed text without cue placeholder</div>'),
    ('cueHtml', '<div>{{text}}' + 'x'*65536 + '</div>'),
    ('cueCss', ''),
    ('cueCss', '.caption{font-family:sans-serif}'),
    ('cueCss', '.caption{font-family:var(--wt-font);transition:opacity 1s}'),
    ('cueCss', '.caption{font-family:var(--wt-font);background:url(https://example.invalid/a.png)}'),
    ('cueCss', '.caption{font-family:var(--wt-font)}' + ' '*32769 + '.x{}'),
    ('stageCss', '.x{ANIMATION:spin 1s}'),
    ('appearance', {'fontFamily': 'url(font.woff)'}),
    ('appearance', {'color': '#fff'}),
    ('schema', 'another-theme-format'),
    ('version', 2),
], ids=lambda value: repr(value)[:60])
def test_provider_schema_rejects_known_local_format_failures(field, value):
    source = valid_source()
    source[field] = value
    with pytest.raises(ValueError):
        WebThemeDocument.from_dict(source)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(source, pipeline.WEB_THEME_OUTPUT_SCHEMA)


def test_valid_source_and_authored_examples_remain_accepted():
    from scripts.author_balatro_candidates import candidates
    jsonschema.validate(valid_source(), pipeline.WEB_THEME_OUTPUT_SCHEMA)
    rows = candidates()
    before = copy.deepcopy(rows)
    jsonschema.validate({'candidates': rows}, pipeline.AUTHORED_OUTPUT_SCHEMA)
    assert rows == before


@pytest.mark.parametrize('missing', ['base', 'primary', 'contrast', 'support', 'highlight', 'shadow'])
def test_legacy_palette_metadata_does_not_block_usable_source(missing):
    from scripts.author_balatro_candidates import candidates
    rows = candidates()
    rows[0]['ColorRole'] = [r for r in rows[0]['ColorRole'] if r['role'] != missing]
    jsonschema.validate({'candidates': rows}, pipeline.AUTHORED_OUTPUT_SCHEMA)


@pytest.mark.parametrize('phase', ['entrance', 'hold', 'exit'])
def test_schema_rejects_empty_semantic_motion(phase):
    from scripts.author_balatro_candidates import candidates
    rows = candidates()
    rows[0]['MotionContract'][phase] = ''
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'candidates': rows}, pipeline.AUTHORED_OUTPUT_SCHEMA)


def test_actual_provider_prompt_includes_complete_authored_constraints(tmp_path, monkeypatch):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design.caption_design_trials import CaptionPreferences
    from twobyteasr.caption_style import font_system
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY, 'selection',
        lambda *a, **k: SimpleNamespace(provider='test', model='test'))
    monkeypatch.setattr(CaptionPreferences, 'read', lambda *a: {})
    monkeypatch.setattr(font_system, 'windows_font_family_names', lambda: [])
    calls = []
    class Client:
        def capabilities(self): return SimpleNamespace(vision=False)
        def complete(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return '{invalid response retained for test'
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE, 'client_for_stage', lambda *a, **k: Client())
    with pytest.raises(Exception):
        pipeline.request_creative_options(SimpleNamespace(cues=[SimpleNamespace(id='x', text='合成字幕')]),
            'x', '三个独立视觉方向', {}, ledger_root=tmp_path)
    assert len(calls) == 1
    planning_prompt = calls[0][0][0]['content']
    assert '不生成源码' in planning_prompt
    from twobyteasr.caption_design.authored_prompt import assemble
    prompt,_ = assemble(pipeline.ThemeLedger.open(tmp_path/'ledger.json'),direction={'id':'test','name':'测试方向'})
    for required in ('不得自行创建宿主', '32768', '400',
                     'HTML 白名单', 'style 属性', 'HTML 注释', '{{words}}', '.wt-w',
                     '主字幕必须绑定 build 和 resolve',
                     'aria-hidden', 'data-semantic-text', '0.03', '0.97', '0.98',
                     '2BYTE-ARTWORK/1', 'data-emphasis'):
        assert required in prompt
    from twobyteasr.caption_design.authored_generation import direction_schema
    assert calls[0][1]['json_schema'] == direction_schema(1)
    for required in ('data-block','4096字节'):
        assert required in prompt
    from twobyteasr.caption_design.design_guidance import load_design_guidance
    guidance,_=load_design_guidance('三个独立视觉方向')
    assert '在现有六段design_spec、art_direction_contract、MotionContract中记录' not in prompt
    assert 'example-carrier' not in prompt
    ledger=json.loads((tmp_path/'ledger.json').read_text('utf8'))
    from twobyteasr.caption_design.design_guidance import VERSION
    assert ledger['design_skills']['version']==VERSION
