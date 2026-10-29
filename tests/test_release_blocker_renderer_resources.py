"""G01/G03: authored resource rejection and installed-only browser selection."""
from urllib.parse import quote
import pytest
from twobyteasr.caption_design.web_theme import sanitize_css, sanitize_html, WebThemeValidationError
from twobyteasr.rendering import advanced_renderer

@pytest.mark.parametrize('value', [
    'image-set("https://example.invalid/a" 1x)',
    r'im\61ge-set("http://127.0.0.1:9/trap" 1x)',
    '-webkit-image-set("file:///C:/synthetic-only.svg" 1x)',
    'image("//example.invalid/a")',
    'src("https://example.invalid/a")',
])
def test_string_resource_functions_rejected(value):
    with pytest.raises(WebThemeValidationError):
        sanitize_css('.x{background-image:'+value+'}', section='cue')

@pytest.mark.parametrize('attribute,value', [
    ('fill', "url('https://example.invalid/a#f')"),
    ('stroke', 'url( "file:///C:/synthetic-only.svg#f" )'),
    ('mask', r'u\72l(http://127.0.0.1:9/trap#m)'),
    ('filter', 'url(//example.invalid/a#f)'),
    ('clip-path', 'url(data:image/svg+xml,%3Csvg%2F%3E)'),
])
def test_svg_presentation_urls_are_internal_only(attribute, value):
    import html
    with pytest.raises(WebThemeValidationError):
        sanitize_html(f'<svg><rect {attribute}="{html.escape(value, quote=True)}"/></svg>', section='cue')

def test_local_filter_and_bounded_svg_texture_remain_legal():
    source='<svg><defs><filter id="grain"><feTurbulence baseFrequency="0.2"/></filter></defs><rect fill="url(\'#paint\')" filter="url(#grain)"/></svg>'
    assert 'url' in sanitize_html(source, section='cue')
    data='data:image/svg+xml,'+quote('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#123"/></svg>', safe='')
    css='.x{background:url("'+data+'");filter:url(#grain)}'
    assert sanitize_css(css, section='cue')==css

def test_browser_selection_works_without_system_chrome(tmp_path, monkeypatch):
    bundled=tmp_path/'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'
    monkeypatch.setattr(advanced_renderer.Path, 'is_file', lambda p: p == bundled)
    assert advanced_renderer._export_browser(tmp_path, web=True)==bundled
    assert advanced_renderer._export_browser(tmp_path, web=False)==bundled

def test_no_browser_fails_before_any_download(tmp_path, monkeypatch):
    monkeypatch.setattr(advanced_renderer.Path, 'is_file', lambda p: False)
    with pytest.raises(RuntimeError, match='浏览器'):
        advanced_renderer._export_browser(tmp_path, web=True)
