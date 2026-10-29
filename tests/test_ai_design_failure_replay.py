import copy
import json
from pathlib import Path
from urllib.parse import quote
import pytest
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,accept_authored_set
from twobyteasr.caption_design.theme_texture_resource import checked_css_urls,validate_svg_texture

def test_original_balatro_response_keeps_all_artwork_and_theme_labels(tmp_path):
    payload=json.loads((Path(__file__).parent/'fixtures/balatro-deepseek-4f5564.json').read_text('utf8'))
    original=copy.deepcopy(payload)
    ledger=ThemeLedger(tmp_path,'balatro小丑牌风格')
    result=accept_authored_set(payload,ledger,'deepseek','deepseek-v4-pro',allow_partial=True)
    assert payload==original
    assert all(c.get('technical_status')!='failed' for c in result.concepts)
    for i,c in enumerate(result.concepts):
        assert c['authored_theme']['cueCss']==original['candidates'][i]['generated_source']['cueCss']
        assert ledger.value['candidates'][i]['art_direction_contract']['theme']=='Balatro/小丑牌'
        assert 'theme' not in ledger.value['candidates'][i]['design_spec']
    assert all(s['semantic_review']=='pending' for s in ledger.value['stages'])

def noise(extra='',body=None):
    body=body or '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" '+extra+'/></filter><rect width="100" height="100" filter="url(#n)" opacity="0.06"/>'
    return 'data:image/svg+xml,'+quote('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'+body+'</svg>',safe='')

def test_bounded_noise_and_inner_url_survive_exactly():
    url=noise();css='background:url("'+url+'")'
    assert checked_css_urls(css)=='background:'
    assert validate_svg_texture(url)['nodes']==4

@pytest.mark.parametrize('extra',['seed="NaN"','numOctaves="999"','href="https://evil.invalid"','onload="run()"','in="SourceGraphic"'])
def test_noise_cannot_execute_fetch_or_expand_unboundedly(extra):
    with pytest.raises(ValueError):validate_svg_texture(noise(extra))

@pytest.mark.parametrize('body',[
    '<filter id="n"><feImage href="https://evil.invalid/a"/></filter>',
    '<filter id="n"><feTurbulence filter="url(#n)"/></filter>',
    '<rect filter="url(https://evil.invalid/a)"/>',
    '<rect filter="url(#missing)"/>',
    '<filter id="n"><feTurbulence/></filter><filter id="n"><feTurbulence/></filter>',
])
def test_svg_internal_references_have_no_fetch_or_recursion(body):
    with pytest.raises(ValueError):validate_svg_texture(noise(body=body))
