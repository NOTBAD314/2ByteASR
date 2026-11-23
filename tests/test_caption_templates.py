"""Motion templates (components version 12): hand-made effect captions the AI only selects."""
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.caption_design.authored_generation import generate_staged
from twobyteasr.caption_design.caption_components import capability_text, compose
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.caption_design.caption_templates import INTENSITIES, normalize, template_ids, validate_template
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.web_theme import WebThemeDocument, theme_archive_html

ROOT = Path(__file__).resolve().parents[1]


def theme(**choice):
    return WebThemeDocument.from_dict(dict(name='tpl', **compose(dict(version=12, **choice)))).to_dict()


@pytest.mark.parametrize('template', template_ids())
def test_every_template_is_a_valid_portable_theme(template):
    value = theme(template=template, emphasis=['看傻了'], intensity='heavy', seed=42)
    assert value['stageHtml'] == '' and value['cueHtml'].count('{{words}}') == 1
    assert not re.search(r'@keyframes|animation\s*:|transition\s*:|<script|url\(http', value['cueCss'] + value['cueHtml'])
    assert value['motionSpec'] == dict(version=2, runtime='gsap', buildMs=0., resolveMs=0., tracks=[],
                                       template=dict(id=template, params=dict(seed=42, intensity='heavy')))
    assert 'data-emphasis="看傻了"' in value['cueHtml']


@pytest.mark.parametrize('template', template_ids())
def test_templates_never_write_caption_text(template):
    markup = theme(template=template)['cueHtml']
    # Decorative interface labels (PLAY, REC, timecodes) are hidden from readers and never Chinese.
    hidden = re.findall(r'<(\w+)[^>]*aria-hidden="true"[^>]*>(.*?)</\1>', markup)
    assert hidden
    shown = re.sub(r'<(\w+)[^>]*aria-hidden="true"[^>]*>.*?</\1>', '', markup)
    assert re.sub(r'<[^>]+>', '', shown).strip() == '{{words}}'
    decoration = re.sub(r'<[^>]+>', '', ''.join(text for _, text in hidden))
    assert not re.search(r'[一-鿿]', decoration)
    assert markup.count('data-semantic-text="true"') == 1


def test_template_block_is_validated_strictly():
    assert validate_template({'id': 'vhs-signal'}) == {'id': 'vhs-signal', 'params': {'seed': 0, 'intensity': 'normal'}}
    for bad in ({'id': 'unknown'}, {'id': 'vhs-signal', 'params': {'seed': -1}}, {'id': 'vhs-signal', 'params': {'seed': 1.5}},
                {'id': 'vhs-signal', 'params': {'intensity': 'wild'}}, {'id': 'vhs-signal', 'params': {'code': 'x'}},
                {'id': 'vhs-signal', 'extra': 1}, 'vhs-signal'):
        with pytest.raises(ValueError):
            validate_template(bad)
    base = dict(version=2, runtime='gsap', tracks=[], template={'id': 'hud-lock'})
    assert validate_motion_spec(base)['template']['id'] == 'hud-lock'
    for change in (dict(version=1), dict(tracks=[{'selector': '.x', 'phase': 'build', 'from': {'opacity': 0}, 'to': {'opacity': 1}}]),
                   dict(timingProfile='readable-pixel')):
        with pytest.raises(ValueError):
            validate_motion_spec(dict(base, **change))


def test_loose_choices_fall_back_to_the_design():
    c = normalize(dict(version=12, template='hud-lock', palette=dict(accent='orange', ink='#ffffff'), fontFamily='Papyrus',
                       fontSize=900, intensity='max', seed='7', emphasis=['稳了', 'a|b', 5]))
    assert c['palette'] == dict(ink='#FFFFFF', base='#0E0F11', accent='#FFB020')
    assert c['fontFamily'] == 'Source Han Sans SC Heavy' and c['fontSize'] == 96
    assert c['intensity'] == 'normal' and c['seed'] == 0 and c['emphasis'] == ['稳了']
    with pytest.raises(ValueError):
        normalize(dict(version=12, template='plate'))


def test_the_vhs_template_loads_its_pixel_face():
    assert theme(template='vhs-signal')['appearance']['fontFamily'] == '"Source Han Sans SC Heavy", "Cubic 11"'


def test_runtime_has_a_builder_for_every_template_and_both_hosts_load_it():
    source = (ROOT / 'renderer/src/webThemeTemplates.js').read_text('utf8')
    for template in template_ids():
        assert f"templates['{template}']" in source
    # Determinism rules for anything both the preview and the export seek.
    assert 'Math.random' not in source and 'Date.now' not in source and '.call(' not in source
    assert "import '../webThemeTemplates.js';" in (ROOT / 'renderer/src/components/WebThemeSubtitle.tsx').read_text('utf8')
    motion = (ROOT / 'renderer/src/webThemeMotion.js').read_text('utf8')
    assert 'runtime.__2byteTemplates' in motion and 'templateCleanup' in motion
    page = theme_archive_html(theme(template='vhs-signal'), sample_text='测试', auto_replay=False)
    assert "templates['vhs-signal']" in page
    plain = theme_archive_html(dict(theme(template='vhs-signal'), motionSpec=None) if False else
                               WebThemeDocument.from_dict(dict(name='k', **compose(dict(version=11, kit='glass')))).to_dict(),
                               sample_text='测试', auto_replay=False)
    assert "templates['vhs-signal']" not in plain


def test_animated_scene_detection_counts_templates():
    from twobyteasr.rendering.caption_scene import animated_caption
    snapshot = SimpleNamespace(style_recipe={'webTheme': theme(template='vhs-signal')}, word_animation=None)
    assert animated_caption(SimpleNamespace(snapshot=snapshot, web=True))


def test_the_model_is_steered_to_templates_first():
    text = capability_text(None)
    assert text.index('version=12') < text.index('version=11')
    assert all(template + '：' in text for template in template_ids())
    assert '至少两个用动态模板' in text and '蓝青色' in text
    assert set(INTENSITIES) == {'calm', 'normal', 'heavy'}


class Director:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def complete(self, messages, **kw):
        content = messages[0]['content']
        with self.lock:
            self.calls.append(content if isinstance(content, str) else content[0]['text'])
        rows = [dict(version=12, template='vhs-signal', emphasis=['看傻了']),
                dict(version=12, template='hud-lock', palette=dict(accent='#FF4D4D'), intensity='heavy'),
                dict(version=12, template='vhs-signal', intensity='calm', seed=9)]
        return json.dumps({'candidates': [dict(name=f'方案{i}', design='同一句字幕的特效字幕方向说明', components=c)
                                          for i, c in enumerate(rows)]}, ensure_ascii=False)

    def invocation_trace(self):
        return {'dispatched': True, 'timings': {'queue_ms': 0, 'retry_count': 0}}


def test_one_request_yields_template_designs(tmp_path):
    client = Director()
    result = generate_staged(ThemeLedger(tmp_path, '游戏实况特效字幕'), client, SimpleNamespace(provider='fixture', model='local'), 'unused',
                             {'models': dict(ai_design_wait_mode='long30', ai_design_candidate_count=3, ai_design_mode='drafts')},
                             request_id='fixture', client_factory=lambda: client)
    assert len(client.calls) == 1 and 'version=12' in client.calls[0]
    assert [c.get('technical_status') for c in result.concepts] == [None, None, None]
    ids = [c['authored_theme']['motionSpec']['template']['id'] for c in result.concepts]
    assert ids == ['vhs-signal', 'hud-lock', 'vhs-signal']
    assert '#FF4D4D' in result.concepts[1]['authored_theme']['cueCss']


def test_hud_decoration_uses_bundled_mono_in_preview_and_export():
    """2026-11-22: hud-lock labels use the bundled JetBrains Mono, with system mono after it."""
    from twobyteasr.caption_design.web_theme_fonts import DECORATION_FONT_FILES, FONT_FILES
    value = theme(template='hud-lock')
    stack = [n.strip().strip('"') for n in value['appearance']['fontFamily'].split(',')]
    assert stack[0] in FONT_FILES and stack[-1] == 'JetBrains Mono'
    assert '.hud-head,.hud-foot{position:relative;display:flex;align-items:center;gap:.6em;font-family:"JetBrains Mono","Consolas"' in value['cueCss']
    assert 'JetBrains Mono' not in FONT_FILES  # never offered as a caption font
    filename, _ = DECORATION_FONT_FILES['JetBrains Mono']
    assert (ROOT / 'assets/fonts' / filename).read_bytes() == (ROOT / 'renderer/public/fonts' / filename).read_bytes()
    assert f"'JetBrains Mono':['{filename}','truetype']" in (ROOT / 'renderer/src/webThemeFonts.ts').read_text('utf8')
    html = theme_archive_html(value, sample_text='这一波操作直接把我看傻了', duration_seconds=3, auto_replay=False)
    assert '@font-face{font-family:"JetBrains Mono";src:url(data:font/truetype;base64,' in html


def test_missing_decoration_font_falls_back_without_failing(tmp_path, monkeypatch):
    from twobyteasr.caption_design import web_theme_fonts as fonts
    (tmp_path / 'assets/fonts').mkdir(parents=True)
    (tmp_path / 'assets/fonts/SourceHanSansSC-Heavy.otf').write_bytes(b'caption-font')
    monkeypatch.setattr(fonts, 'detect_install_root', lambda: tmp_path)
    css = fonts.offline_font_css('"Source Han Sans SC Heavy", "JetBrains Mono"')
    assert 'Source Han Sans SC Heavy' in css and 'JetBrains Mono' not in css
