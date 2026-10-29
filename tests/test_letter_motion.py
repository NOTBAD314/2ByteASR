import copy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.acceptance.letter_motion_audit import make_project
from twobyteasr.caption_style.letter_motion import PRESETS,sample
from twobyteasr.caption_style.word_animation import build_word_animation,remap_word_animation
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.rendering.caption_scene import SceneRasterizer,animated_caption
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.rendering.advanced_renderer import _native_segment_project


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('duration',[1500,6000])
def test_curated_effects_have_measured_onsets_readable_hold_and_clean_exit(app,duration):
    p=make_project('none.mp4',duration=duration)
    for cue,mode in zip(p.cues,PRESETS):
        plan=build_word_animation(p,cue)
        assert plan['status']=='measured'
        assert [s['spoken'] for s in plan['spans']]==list('让每一句都有余韵')
        for unit in plan['units']:
            assert sample(unit,0)['opacity']==0
            assert sample(unit,duration)['opacity']==0
            assert sample(unit,duration)['dust']==0
            assert max(sample(unit,f[0])['opacity'] for f in unit['frames'])==1
        assert sample(plan['units'][2],200)==sample(plan['units'][2],200)


def test_sentence_modes_expose_unspoken_glyphs_without_inventing_word_times(app):
    p=make_project('none.mp4')
    plans={mode:build_word_animation(p,cue) for cue,mode in zip(p.cues,PRESETS)}
    for mode,plan in plans.items():
        upcoming=sample(plan['units'][-1],500)
        if mode in {'word_sweep','word_echo'}:
            assert upcoming['opacity']==1 and upcoming['ink']==0
        else:
            assert upcoming['opacity']==0
        assert plan['spans'][-1]['start_ms']>500


def test_glyph_fragments_partition_original_type_without_randomness(app):
    p=make_project('none.mp4')
    plan=build_word_animation(p,p.cues[-1])
    for unit in plan['units']:
        cells=unit['shards']
        assert len(cells)==12
        assert sum(c['rect'][2]*c['rect'][3] for c in cells)==pytest.approx(1)
        assert sample(unit,4400)['scatter']==0
    assert plan==build_word_animation(p,p.cues[-1])


def test_late_last_word_remains_visible_until_the_cue_boundary(app):
    p=make_project('none.mp4')
    for i,cue in enumerate(p.cues):
        p.asr_evidence[str(i)]['words'][-1].update(start_ms=cue.start_ms+5950,end_ms=cue.end_ms)
        plan=build_word_animation(p,cue)
        last=plan['units'][-1]
        assert sample(last,5990)['opacity']>.8
        assert sample(last,6000)['opacity']==0


def test_missing_evidence_has_explicit_whole_line_choreography(app):
    p=make_project('none.mp4');p.asr_evidence={}
    snapshot=build_visual_cue_snapshot(p,'0')
    plan=snapshot.word_animation
    assert not plan['spans'] and plan['status']!='measured'
    assert len(plan['units'])==1 and plan['units'][0]['char_end']==len(plan['text'])
    assert animated_caption(SimpleNamespace(snapshot=snapshot,web=False))
    assert r'\move' in compile_ass(p)
    cut=_native_segment_project(p,750,5800)
    clipped=remap_word_animation(cut._word_animation_plans['0'],p.cues[0].text)
    for t in (0,300,4900):
        assert sample(plan['units'][0],t+750)==pytest.approx(sample(clipped['units'][0],t),abs=.0001)


@pytest.mark.parametrize('cue_index',range(6))
def test_cut_preserves_original_motion_clock_including_outro(app,cue_index):
    p=make_project('none.mp4');cue=p.cues[cue_index]
    original=build_word_animation(p,cue)
    seg=_native_segment_project(p,cue.start_ms+750,cue.start_ms+5800)
    cut=remap_word_animation(seg._word_animation_plans[cue.id],cue.text)
    for t in (0,550,2400,4930):
        for a,b in zip(original['units'],cut['units']):
            assert sample(a,t+750)==pytest.approx(sample(b,t),abs=.0001)
    ass=compile_ass(seg)
    assert r'\move' in ass and 'template' not in ass and 'math.random' not in ass


def test_live_seek_keeps_same_pixels_and_multiple_motion_frames(app):
    p=make_project('none.mp4');raster=SceneRasterizer()
    for cue in p.cues:
        snap=build_visual_cue_snapshot(p,cue.id)
        prepared=SimpleNamespace(snapshot=snap,snapshot_hash=snap.stable_hash())
        first=raster.native_frame(prepared,180,640,360)
        second=raster.native_frame(prepared,280,640,360)
        assert first!=second
        assert first==raster.native_frame(prepared,180,640,360)
    raster.close()


def test_cached_tiles_follow_changed_appearance(app):
    from dataclasses import replace
    p=make_project('none.mp4');raster=SceneRasterizer()
    snap=build_visual_cue_snapshot(p,'0')
    normal=raster.native_frame(SimpleNamespace(snapshot=snap,snapshot_hash=snap.stable_hash()),4000,640,360)
    changed=replace(snap,fill={'type':'solid','color':'#FF00FF00'})
    green=raster.native_frame(SimpleNamespace(snapshot=changed,snapshot_hash=changed.stable_hash()),4000,640,360)
    assert normal!=green
    assert normal==raster.native_frame(SimpleNamespace(snapshot=snap,snapshot_hash=snap.stable_hash()),4000,640,360)
    raster.close()


def test_multiline_remap_keeps_words_and_punctuation(app):
    p=make_project('none.mp4');cue=p.cues[0]
    plan=remap_word_animation(build_word_animation(p,cue),'让每一句，\n都有余韵')
    assert ''.join(plan['text'][u['char_start']:u['char_end']] for u in plan['units'])==plan['text']
    assert len(plan['units'])==8


def test_featured_library_is_real_six_motion_preview_and_saved_roundtrip(app,tmp_path):
    from twobyteasr.caption_style.studio_motion_browser import MotionBrowserDialog,MotionCard
    from twobyteasr.caption_style.motion_library import MotionPresetStore,MotionPreset
    from twobyteasr.caption_style.effect_dsl import builtin_effects
    p=make_project('none.mp4');dialog=MotionBrowserDialog(p.styles[0])
    try:
        cards=dialog.host.findChildren(MotionCard)
        assert {c.preset.id for c in cards}==set(PRESETS)
        for card in cards:
            assert card.preview.snapshot.word_animation['units']
        store=MotionPresetStore(tmp_path)
        store.upsert(MotionPreset('custom-mist','自订雾光',{'nativeEffect':builtin_effects()['word_mist']},system=False))
        assert store.load_user()['custom-mist'].motion['nativeEffect']['entry']['type']=='word_mist'
    finally:
        dialog.close();dialog.deleteLater();app.processEvents()
