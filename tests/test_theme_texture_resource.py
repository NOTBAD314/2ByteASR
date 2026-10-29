from urllib.parse import quote
import pytest
from twobyteasr.caption_design.theme_texture_resource import validate_svg_texture,checked_css_urls
from twobyteasr.caption_design.web_theme import sanitize_css,sanitize_html,WebThemeValidationError
from twobyteasr.caption_design.authored_html import html_problems
from twobyteasr.caption_design.authored_theme_contract import CSS_SCHEMA
import jsonschema

def uri(body='<rect width="80" height="80" fill="#8B4513"/><rect width="80" height="20" fill="#6B8E23"/>',**attributes):
    attributes={'xmlns':'http://www.w3.org/2000/svg','width':'80','height':'80',**attributes}
    attrs=' '.join(f'{k}="{v}"' for k,v in attributes.items())
    return 'data:image/svg+xml,'+quote(f'<svg {attrs}>{body}</svg>',safe='')

def test_safe_texture_retains_exact_source_and_same_schema():
    css='.grass{background-image:url("'+uri()+'");background-size:80px 80px;}'
    assert sanitize_css(css,section='cue')==css
    jsonschema.validate(css,CSS_SCHEMA)
    assert validate_svg_texture(uri())['nodes']==3

@pytest.mark.parametrize('body',[
    '<script>alert(1)</script>','<image href="https://example.com/a.png"/>',
    '<foreignObject/>','<style>rect{fill:red}</style>','<animate attributeName="x"/>',
    '<rect onclick="alert(1)"/>','<rect style="fill:red"/>','<rect fill="url(#nested)"/>',
    '<rect width="999999999"/>','<rect opacity="2"/>','<text>font</text>',
    '<use href="#other"/>','<rect xmlns="https://bad.test"/>','<svg width="10" height="10"/>',
    '<rect width="NaN"/>','<rect width="1e999"/>','<path d="M1e999 0"/>',
    '<path d="alert(1)"/>','<g>'*65+'</g>'*65,
])
def test_unsafe_or_unbounded_svg_rejected(body):
    with pytest.raises(ValueError):validate_svg_texture(uri(body))

@pytest.mark.parametrize('url',[
    'https://example.com/texture.svg','file:///C:/secret','//example.com/a',
    'data:text/html,%3Cscript%3E','data:image/svg+xml;base64,PHN2Zz4=',
    'data:image/svg+xml,%3C!DOCTYPE%20svg%3E%3Csvg/%3E',
    'data:image/svg+xml,%GG',
])
def test_uncontrolled_urls_rejected_even_beside_valid_texture(url):
    with pytest.raises(ValueError):checked_css_urls(f'url("{uri()}"),url("{url}")')

@pytest.mark.parametrize('css',[r'.x{background:u\72l(https://bad.test)}',r'.x{background:u\000072 l(https://bad.test)}',
    '.x{background:url("unterminated)}','.x{background:url("https://bad.test/a"),url(#ok)}'])
def test_every_css_url_is_checked(css):
    with pytest.raises(WebThemeValidationError):sanitize_css(css,section='cue')

def test_internal_svg_references_and_declarative_block_identity():
    assert checked_css_urls('fill:url("#grain");filter:url(#shade)')=='fill:;filter:'
    source='<div class="block" data-block="grass-side_1"></div>'
    assert sanitize_html(source,section='cue')==source and not html_problems(source)
    assert html_problems('<div data-something="x"></div>')
    with pytest.raises(WebThemeValidationError):sanitize_html('<div data-block="bad value"></div>',section='cue')

def test_encoded_texture_bounds_and_entities():
    for value in (uri(width='4096'),uri(height='0'),uri(' '*4100),
                  'data:image/svg+xml,'+quote('<!DOCTYPE svg [<!ENTITY e "boom">]><svg width="80" height="80">&e;</svg>')):
        with pytest.raises(ValueError):validate_svg_texture(value)
