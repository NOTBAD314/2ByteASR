"""Design kits (components version 11): AI 设计's art-directed vocabulary."""
import copy
import json
import re
import threading
from types import SimpleNamespace

import pytest

from twobyteasr.caption_design.authored_generation import generate_staged
from twobyteasr.caption_design.caption_components import capability_text, compose
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.caption_design.caption_kits import ENERGIES, KITS, MOTIONS, examples, normalize
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.web_theme import WebThemeDocument


def theme(**choice):
    return WebThemeDocument.from_dict(dict(name='kit', **compose(dict(version=11, **choice)))).to_dict()


@pytest.mark.parametrize('kit', KITS)
def test_every_kit_is_an_ordinary_portable_theme(kit):
    value = theme(kit=kit, emphasis=['看傻了'])
    # The same safe contract as an authored theme: static CSS, host stage, declarative motion.
    assert value['stageHtml'] == '' and '{{words}}' in value['cueHtml']
    assert not re.search(r'@keyframes|animation\s*:|transition\s*:|<script|url\(http', value['cueCss'] + value['cueHtml'])
    assert 'var(--wt-font)' in value['cueCss'] and 'var(--wt-size)' in value['cueCss']
    spec = validate_motion_spec(value['motionSpec'], cue_html=value['cueHtml'], duration_ms=6000)
    phases = {(t['selector'], t['phase']) for t in spec['tracks']}
    # The real characters, not only ornaments, arrive and leave.
    assert ('.cap-type .wt-w', 'build') in phases and ('.cap-type .wt-w', 'resolve') in phases


@pytest.mark.parametrize('kit', KITS)
def test_a_kit_never_writes_caption_text(kit):
    value = theme(kit=kit, emphasis=['重点'])
    visible = re.sub(r'<[^>]+>', '', value['cueHtml'])
    # Everything a viewer can read comes from the project's own line.
    assert re.fullmatch(r'(\{\{words\}\})+', visible.strip())
    # One readable line; any second copy is a painted outline, hidden from readers.
    assert value['cueHtml'].count('data-semantic-text="true"') == 1
    assert value['cueHtml'].count('{{words}}') - 1 == len(re.findall(r'cap-under[^"]*" aria-hidden="true"', value['cueHtml']))
    assert not re.search(r'(?<![-\w])content:\s*"[^"]', value['cueCss'])
    assert 'data-emphasis="重点"' in value['cueHtml']


def test_layout_is_not_a_one_line_text_well():
    # A bottom-anchored box is one line tall when the host measures it, and the host
    # shrinks text to fit a bounded well: a manual line break came out at 60% size.
    css = theme(kit='glass')['cueCss']
    assert '.kit-layout{position:absolute;inset:0;' in css and 'align-items:flex-end' in css
    assert not re.search(r'\.kit-layout\{[^}]*bottom:', css)


def test_gradient_lettering_is_outlined_by_copies_not_filters():
    # Filter chains on gradient text were slow and differed between preview and export.
    value = theme(kit='chrome')
    assert value['cueHtml'].count('{{words}}') == 3 and 'cap-cast' in value['cueHtml']
    assert not re.search(r'\.cap-(type|under|main)[^{]*\{[^}]*filter:', value['cueCss'])


def test_kits_are_different_compositions_not_recolours():
    themes = [theme(kit=kit) for kit in KITS]
    assert len({t['cueHtml'] for t in themes}) == len(KITS)
    assert len({t['appearance']['fontFamily'] for t in themes}) >= 6
    # Four of the kits carry no backing plate at all.
    plates = [kit for kit in KITS if re.search(r'kit-(panel|paper|box|pill|brush)"', theme(kit=kit)['cueHtml'])]
    assert set(KITS) - set(plates) >= {'variety', 'neon', 'editorial', 'cinema', 'chrome'}


@pytest.mark.parametrize('motion', MOTIONS)
@pytest.mark.parametrize('energy', ENERGIES)
def test_text_choreography_and_energy_combine_with_any_kit(motion, energy):
    for kit in ('variety', 'ink', 'hud', 'comic'):
        value = theme(kit=kit, motion=motion, energy=energy)
        validate_motion_spec(value['motionSpec'], cue_html=value['cueHtml'], duration_ms=6000)
        validate_motion_spec(value['motionSpec'], cue_html=value['cueHtml'], duration_ms=1200)


def test_calm_moves_less_than_punchy():
    travel = lambda energy: max(abs(t['from'].get('y', 0)) for t in theme(kit='glass', motion='rise', energy=energy)['motionSpec']['tracks'])
    assert travel('calm') < travel('lively') < travel('punchy')


def test_palette_font_and_size_follow_the_art_direction():
    value = theme(kit='neon', palette=dict(ink='#ffffff', base='#001122', accent='#00ff88', accent2='#ffaa00'),
                  fontFamily='Smiley Sans', fontSize=90, tilt=3)
    assert value['palette'] == dict(primary='#00FF88', secondary='#FFAA00', accent='#00FF88',
                                    background='#001122', text='#FFFFFF')
    assert value['appearance']['fontFamily'] == 'Smiley Sans' and value['appearance']['fontSize'] == 90
    assert '#00FF88' in value['cueCss'] and 'rotate(3deg)' in value['cueCss']


def test_loose_art_direction_falls_back_to_the_designed_default():
    # None of these is worth a second paid model call.
    loose = normalize(dict(version=11, kit='ink', palette=dict(ink='white', accent='#12AB34'), fontFamily='Papyrus',
                           fontSize=400, tilt='left', motion='explode', energy=None, note='x',
                           emphasis=['好', 3, 'a|b', '  真的  ', '', '1', '2', '3']))
    assert loose['palette']['ink'] == '#F6F1E4' and loose['palette']['accent'] == '#12AB34'
    assert loose['fontFamily'] == '楷体' and loose['fontSize'] == 110 and loose['tilt'] == 0
    assert loose['motion'] == 'native' and loose['energy'] == 'lively'
    assert loose['emphasis'] == ['好', '真的', '1', '2']
    for bad in (dict(version=11), dict(version=11, kit='plate'), dict(version=10, kit='ink'), 'ink'):
        with pytest.raises((ValueError, TypeError)):
            normalize(bad)


def test_system_kai_keeps_a_bundled_fallback():
    stack = theme(kit='ink')['appearance']['fontFamily']
    assert stack.startswith('"KaiTi"') and 'Source Han Sans SC Medium' in stack


def test_the_model_is_told_what_each_kit_looks_like():
    text = capability_text(None)
    assert all(kit + '：' in text for kit in KITS)
    assert 'version:11' in text and '三个不同的kit' in text and '不要改字' in text
    assert 'caption-components-2' in text  # the plate vocabulary stays available on request
    assert examples() == [dict(version=11, kit=kit) for kit in KITS]


class ArtDirector:
    """A provider that answers the draft request with three kit choices."""
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def complete(self, messages, **kw):
        content = messages[0]['content']
        content = content if isinstance(content, str) else content[0]['text']
        with self.lock:
            self.calls.append(content)
        rows = [('综艺', dict(version=11, kit='variety', emphasis=['看傻了'], energy='punchy')),
                ('水墨', dict(version=11, kit='ink', palette=dict(accent='#C8372D'))),
                ('玻璃', dict(version=11, kit='glass', motion='rise', energy='calm', extra='ignored'))]
        return json.dumps({'candidates': [dict(name=name, design='不同构图的字幕设计方向说明', components=value)
                                          for name, value in rows]}, ensure_ascii=False)

    def invocation_trace(self):
        return {'dispatched': True, 'timings': {'queue_ms': 0, 'retry_count': 0}}


def test_one_request_yields_three_kit_designs(tmp_path):
    client = ArtDirector()
    ledger = ThemeLedger(tmp_path, '日系综艺花字')
    result = generate_staged(ledger, client, SimpleNamespace(provider='fixture', model='local'), 'unused',
                             {'models': dict(ai_design_wait_mode='long30', ai_design_candidate_count=3, ai_design_mode='drafts')},
                             request_id='fixture', client_factory=lambda: client)
    assert len(client.calls) == 1
    # DeepSeek's JSON mode rejects a prompt that never says JSON.
    assert 'json' in client.calls[0].lower() and 'version=11' in client.calls[0]
    assert [c.get('technical_status') for c in result.concepts] == [None, None, None]
    sources = [c['authored_theme'] for c in result.concepts]
    assert ['kit-variety' in s['cueHtml'] for s in sources] == [True, False, False]
    assert 'kit-ink' in sources[1]['cueHtml'] and 'kit-glass' in sources[2]['cueHtml']
    assert all(c['source_origin'] == 'model_components_new' for c in result.concepts)


def test_numeric_slips_are_fixed_locally_and_a_receipt_never_aborts_the_repair(tmp_path):
    from twobyteasr.caption_design.authored_repair import repair_authored
    source = theme(kit='glass')
    source['motionSpec']['resolveMs'] = 700
    source['motionSpec']['buildMs'] = 900
    source['appearance']['fontSize'] = 'calc(4.5 * var(--wt-u))'
    track = source['motionSpec']['tracks'][0]
    track['transformOrigin'] = '50% 50%'
    payload = {'candidates': [dict(id='A', name='稿', generated_source=source, composition_family='胶囊',
        art_direction_contract={}, design_spec={'design': '玻璃胶囊'}, ColorRole=[],
        MaterialContract={'material': '', 'selectors': []},
        MotionContract={'entrance': '浮起', 'hold': '静止', 'exit': '上移'})]}
    ledger = ThemeLedger(tmp_path, '玻璃')
    seen = []

    def validate(value):
        import jsonschema
        seen.append(copy.deepcopy(value))
        row = value['candidates'][0]['generated_source']
        # The first receipt is taken while later slips are still present.
        jsonschema.validate(row['motionSpec'].get('resolveMs'), {'type': 'number', 'maximum': 500})
        WebThemeDocument.from_dict(row)

    fixed = repair_authored(payload, ledger=ledger, provider='fixture', model='local', parent_request_id='p',
                            validate=validate, patch_request=None, regenerate_request=None)
    row = fixed['candidates'][0]['generated_source']
    assert row['motionSpec']['resolveMs'] == 500 and row['motionSpec']['buildMs'] == 800
    assert row['appearance']['fontSize'] == 54.0
    assert 'transformOrigin' not in row['motionSpec']['tracks'][0]
    operations = [r['operation'] for r in ledger.value['technical_repairs']]
    assert operations == ['local_constant_motion_origin', 'local_exact_numeric']
    assert ledger.value['technical_repairs'][0]['validation']['passed'] is False
    assert all(r['model_calls'] == 0 for r in ledger.value['technical_repairs'])
