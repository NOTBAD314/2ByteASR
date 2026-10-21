import json
from pathlib import Path
import pytest
from twobyteasr.caption_design.web_theme import WebThemeDocument,parse_web_theme_sections,export_theme_archive,import_theme_archive,theme_archive_html
from twobyteasr.caption_design.theme_draft import canonical_theme,theme_structure

FIXTURE=Path(__file__).parent/'fixtures/death_stranding_original.txt'

def original():
    return parse_web_theme_sections(FIXTURE.read_text(encoding='utf8'))

def test_original_semantic_structure_survives_parse_sanitize_archive(tmp_path):
    before=original();after=WebThemeDocument.from_dict(before).to_dict()
    a,b=theme_structure(before),theme_structure(after)
    assert a['classes']==b['classes'] and len(a['classes'])>40
    assert a['keyframes']==b['keyframes'] and len(a['keyframes'])>10
    assert 'chiral-gold-grad' in b['ids'] and a['ids']==b['ids']
    assert before['cueCss']==after['cueCss'] and before['stageCss']==after['stageCss']
    folder=export_theme_archive(after,tmp_path)
    assert canonical_theme(import_theme_archive(folder/'theme.html'))==canonical_theme(after)
    assert canonical_theme(import_theme_archive(folder/'theme.json'))==canonical_theme(after)
    another=export_theme_archive(after,tmp_path)
    assert another!=folder and (folder/'theme.html').exists()

def test_export_failure_and_cancel_publish_no_partial_archive(tmp_path):
    def reject(folder):
        assert (folder/'theme.html').is_file()
        raise RuntimeError('isolated render rejected staged bytes')
    with pytest.raises(RuntimeError,match='isolated render'):
        export_theme_archive(original(),tmp_path,validate_before_publish=reject)
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError,match='取消'):
        export_theme_archive(original(),tmp_path,cancel_check=lambda:True)
    assert not list(tmp_path.iterdir())


def test_telemetry_bars_are_not_text_plates_but_flat_text_plate_is_rejected():
    from twobyteasr.caption_design.web_theme import _reject_flat_plate
    theme=original()
    theme['cueHtml']='<div class="cargo-plate"><div class="wave-bar"></div>{{words}}</div>'
    theme['cueCss']='.cargo-plate{font-family:var(--wt-font);background:linear-gradient(#333,#111)} .wave-bar{width:2px;background:#abc}'
    _reject_flat_plate(WebThemeDocument.from_dict(theme),'工业')
    theme['cueCss']=theme['cueCss'].replace('linear-gradient(#333,#111)','#222')
    with pytest.raises(ValueError,match='平涂'):
        _reject_flat_plate(WebThemeDocument.from_dict(theme),'工业')
