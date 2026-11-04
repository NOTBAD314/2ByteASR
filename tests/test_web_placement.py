import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
from twobyteasr.caption_style.style_recipe import StyleRecipe
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_style.web_placement import cue_placement,moved_placement


def project():
    from twobyteasr.caption_design.web_theme import builtin_web_themes
    theme=next(iter(builtin_web_themes().values())).to_dict()
    p=SubtitleProject(media=StudioMedia(path='',width=1920,height=1080,duration_ms=3000),
                      cues=[StudioCue('cue',0,3000,'位置保持')])
    p.style_recipes[p.cues[0].style_id]=StyleRecipe(name='Web',engine='remotion',web_theme=theme).to_dict()
    p.validate()
    return p


def test_legacy_pixel_position_is_materialized_without_mutation():
    p=project();cue=p.cues[0];baseline=cue_placement(p,cue)
    cue.transform.update(position_x=420,position_y=600)
    actual=cue_placement(p,cue)
    assert actual['x']==420/1920 and actual['y']==600/1080
    assert actual['originX']==baseline['originX'] and actual['originY']==baseline['originY']
    assert 'web_placement' not in cue.transform


def test_normalized_placement_survives_save_and_output_resolution(tmp_path):
    p=project();cue=p.cues[0]
    cue.transform.update(web_placement=moved_placement(p,cue,(420,600)),position_x=420,position_y=600)
    path=tmp_path/'placement.2byteproj';save_project(p,path);reopened=load_project(path)
    a=build_visual_cue_snapshot(reopened,'cue',width=960,height=540)
    b=build_visual_cue_snapshot(reopened,'cue',width=3840,height=2160)
    assert a.style_recipe['layout']['webPlacement']==b.style_recipe['layout']['webPlacement']==cue.transform['web_placement']


def test_export_visual_and_html_use_same_placement():
    from twobyteasr.caption_design.web_theme import theme_archive_html
    from twobyteasr.rendering.advanced_renderer import normalized_visual_snapshot
    p=project();cue=p.cues[0];cue.transform.update(position_x=400,position_y=400)
    snapshot=build_visual_cue_snapshot(p,'cue')
    visual=normalized_visual_snapshot(snapshot)
    assert visual['layout']['webPlacement']==cue_placement(p,cue)
    html=theme_archive_html(visual['webTheme'],placement=visual['layout']['webPlacement'])
    assert '<subtitle-placement id="subtitle-placement">' in html
    assert html.index('subtitle-placement id=') < html.index('<div class="theme-motion">') < html.index('id="wt-cue"')


def test_snapshot_hash_still_observes_nested_edits_and_export_is_independent():
    p=project();snapshot=build_visual_cue_snapshot(p,'cue')
    first=snapshot.stable_hash();export=snapshot.to_dict()
    snapshot.style_recipe['layout']['webPlacement']['x']=.1
    assert snapshot.stable_hash()!=first
    assert export['style_recipe']['layout']['webPlacement']['x']!=.1
