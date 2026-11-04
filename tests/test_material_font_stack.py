from pathlib import Path
import pytest
from twobyteasr.caption_design.web_theme_fonts import css_font_stack,offline_font_css


@pytest.mark.parametrize('stack,expected',[
    ('Cubic 11, Source Han Sans SC, sans-serif','"Cubic 11", "Source Han Sans SC", sans-serif'),
    ('"Cubic 11", monospace','"Cubic 11", monospace'),
    ('','sans-serif'),
])
def test_numbered_family_is_quoted_per_entry(stack,expected):
    assert css_font_stack(stack)==expected


def test_cubic_bytes_are_identical_in_html_and_export_asset():
    import base64,hashlib
    root=Path(__file__).resolve().parents[1]
    data=(root/'assets/fonts/Cubic11.ttf').read_bytes()
    assert data==(root/'renderer/public/fonts/Cubic11.ttf').read_bytes()
    assert base64.b64encode(data).decode() in offline_font_css('Cubic 11, Source Han Sans SC')
    assert (root/'assets/fonts/Cubic11-OFL.txt').read_bytes()==(root/'renderer/public/fonts/Cubic11-OFL.txt').read_bytes()


def test_archive_quotes_numbered_family_without_rewriting_saved_appearance():
    from twobyteasr.caption_design.web_theme import WebThemeDocument,theme_archive_html
    theme=WebThemeDocument.from_dict(dict(name='Cubic fixture',palette={'primary':'#FFFFDD','text':'#FFFFDD'},cueHtml='<div class="lettering">{{text}}</div>',
        cueCss='.lettering{font-family:var(--wt-font)}',appearance={'fontFamily':'Cubic 11, Source Han Sans SC'})).to_dict()
    assert theme['appearance']['fontFamily']=='Cubic 11, Source Han Sans SC'
    assert '--wt-font: "Cubic 11", "Source Han Sans SC";' in theme_archive_html(theme,auto_replay=False)
