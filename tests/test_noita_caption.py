import copy
import hashlib
from dataclasses import replace
from pathlib import Path
import time

from twobyteasr.caption_design.caption_noita import compose, DIRECTIONS
from twobyteasr.caption_design.web_theme import WebThemeDocument, theme_archive_html, export_theme_archive, import_theme_archive
from twobyteasr.rendering.live_web_preview import prepare_web_configuration
from twobyteasr.rendering.caption_proxy import CaptionProxyStore, proxy_key, with_quality


def theme(direction='reaction'):
    return WebThemeDocument.from_dict(dict(id='noita-test',name='炼金铭牌',**compose(dict(version=8,direction=direction)))).to_dict()


def test_all_directions_portable_and_semantic(tmp_path):
    from twobyteasr.caption_design.authored_html import html_problems
    for direction in DIRECTIONS:
        assert html_problems(compose(dict(version=8,direction=direction))['cueHtml'])==[]
        t=theme(direction)
        assert t['cueHtml'].count('{{words}}')==1
        assert 'filter:' not in t['cueCss'] and 'animation:' not in t['cueCss']
        archive=export_theme_archive(t,tmp_path/direction,sample_text='别喝！Mana 100%')
        restored=import_theme_archive(archive)
        for key in ('cueHtml','cueCss','motionSpec','appearance'):
            assert restored[key]==t[key]


def test_noita_wins_over_negative_ice_reference_and_is_in_prompt():
    from twobyteasr.caption_design.caption_reference_catalog import component_style
    from twobyteasr.caption_design.caption_reference_search import queries_for
    from twobyteasr.caption_design.design_guidance import load_design_guidance
    from twobyteasr.caption_design.caption_components import capability_text
    prompt='Noita 炼金字幕，避免之前冰主题错误'
    assert component_style(prompt)=='noita'
    assert queries_for(prompt)[0].startswith('Noita')
    guidance,receipt=load_design_guidance(prompt)
    assert receipt['theme']=='Noita' and any('noita-caption' in f['path'] for f in receipt['files'])
    assert 'version:8' in capability_text('noita') and '实心' in guidance


def test_quality_and_every_edit_invalidate_without_mutating_source():
    source=theme();before=copy.deepcopy(source)
    prepared=prepare_web_configuration(source,'药剂',duration_seconds=1.5)
    keys={proxy_key(prepared,960,540)}
    for field,value in [('text','另一句'),('duration',2),('placement',{'x':.2}),('html',prepared.html+' '),('speaker','S02')]:
        keys.add(proxy_key(replace(prepared,**{field:value}),960,540))
    keys.add(proxy_key(prepared,1280,720))
    keys.add(proxy_key(with_quality(prepared,'draft'),960,540))
    keys.add(proxy_key(with_quality(prepared,'standard'),960,540))
    assert len(keys)==9
    assert source==before
    assert 'visibility:hidden!important' in with_quality(prepared,'draft').html
    assert with_quality(prepared,'full') is prepared
    from twobyteasr.rendering.caption_proxy import eligible
    assert not eligible(replace(prepared,proxy_safe=False))


def test_source_artifact_accepts_noita_definition_and_retains_editable_source():
    import json
    from twobyteasr.caption_design.source_artifact import frame,to_theme
    definition=dict(version=8,direction='reaction',fontSize=66,emphasis=['法杖'])
    raw=frame(dict(HTML='',CSS='',STAGE_CSS='',PARAMETERS=json.dumps({'components':definition})), 'noita-source')
    t,receipt=to_theme(raw,'noita-source',{'name':'炼金反应铭牌'})
    assert receipt['component_definition']==definition
    assert '{{words}}' in t['cueHtml'] and len(t['motionSpec']['tracks'])==21


class FakeRenderer:
    def live_set(self,*args,**kwargs): pass
    def live_text(self,**kwargs): pass
    def live_frame(self,*,cue_ms,stage_ms): return ('frame:'+str(round(cue_ms,4))).encode()
    def shutdown(self): pass


def test_atomic_proxy_reopen_boundaries_and_corrupt_frame_fallback(tmp_path):
    store=CaptionProxyStore(tmp_path,service_factory=FakeRenderer)
    prepared=prepare_web_configuration(theme(),'测试',duration_seconds=.2)
    key=store.ensure(prepared,960,540)
    end=time.monotonic()+5
    while store.status(key)=='building' and time.monotonic()<end:time.sleep(.01)
    assert store.status(key)=='ready'
    assert store.frame_at(key,-1) is None and store.frame_at(key,200) is None
    assert store.frame_at(key,67)[1]==2000/30
    reopened=CaptionProxyStore(tmp_path)
    assert reopened.frame_at(key,67)==store.frame_at(key,67)
    (tmp_path/key/'0003.png').write_bytes(b'corrupt')
    assert reopened.frame_at(key,100) is None
    assert reopened.status(key)=='failed'
    assert not list(tmp_path.glob('.pending-*'))


def test_cancel_never_publishes_partial_sequence(tmp_path):
    store=CaptionProxyStore(tmp_path,service_factory=FakeRenderer)
    prepared=prepare_web_configuration(theme(),'取消',duration_seconds=.2)
    key=store.ensure(prepared,960,540,cancel_check=lambda:True)
    store._jobs.join()
    assert store.status(key)=='missing'
    assert not (tmp_path/key/'manifest.json').exists()
