from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.glossary.glossary_build import extract_catalog_names
from twobyteasr.glossary.glossary_skill import SearchedTerm, diff_term_updates, bind_search_sources
from twobyteasr.playback.video_compositor import VideoCompositionScene

def test_existing_alias_requires_receipt():
    term=SearchedTerm(term='娜娜莉',aliases=('捏造别名',),verification='unverified')
    diffs=diff_term_updates([term],existing_terms=['娜娜莉'],confirmed_pairs=[],excluded_terms=[])
    assert diffs and not diffs[0].checked_by_default
    assert diffs[0].change_type=='unverifiable'

def test_sourced_alias_cannot_override_confirmed_mapping():
    term=SearchedTerm(term='Alice',aliases=('Boss',),sources=({'url':'https://example.com'},),verification='source_matched')
    diffs=diff_term_updates([term],existing_terms=['Alice'],confirmed_pairs=[('Boss','Betty')],excluded_terms=[])
    assert diffs[0].change_type=='conflict' and not diffs[0].checked_by_default

def test_roster_extraction_excludes_headers_and_navigation_and_accepts_second_column():
    html='<table><tr><th>图片</th><th>角色名称</th><th>定位</th></tr><tr><td><img src="a.png"></td><td>娜娜莉</td><td>输出</td></tr></table><table><tr><td>客户端下载</td></tr></table>'
    entries=extract_catalog_names({'https://example.com/characters':html},[],existing_terms=[],structured_only=True)
    assert [x.name for x in entries]==['娜娜莉']

def test_unmatched_claim_is_never_page_verified():
    terms=bind_search_sources([SearchedTerm(term='名字',sources=({'url':'https://fake.example/a'},))],
                              [{'tool':'web_search','urls':['https://real.example/b']}])
    assert terms[0].verification=='unverified'

def test_promoted_v2_uses_exact_loaded_instance(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    scene=VideoCompositionScene()
    source=str(tmp_path/'v2.mp4')
    layer=dict(track_id='V2',clip_id='clip-v2',source_path=source,source_ms=1000,
               primary_media=False,transform={})
    kwargs=dict(paused=True,rate=1.,audio_master_track_id='V2',base_track_id='V2',volume=0.,mpv_path=source)
    scene.set_composition([layer],**kwargs,mpv_binding=('V2','clip-v2',source))
    assert not scene._layers and not scene._players
    scene.close()
