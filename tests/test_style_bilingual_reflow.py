"""Preset appearance never freezes a generated bilingual line position."""
from copy import deepcopy
from dataclasses import asdict
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,SubtitleStyle,save_project,load_project
from twobyteasr.caption_style.scoped_preset import preset_command
from twobyteasr.caption_style.scoped_style import style_patch_command
from twobyteasr.caption_style.bilingual_layout import project_display_cues,ink_block
from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
from twobyteasr.caption_style.caption_layer_transform import GeometryBatch,resolved_values


def project(width=1920,height=1080,order='translation_first'):
    p=SubtitleProject(StudioMedia('',width=width,height=height),cues=[StudioCue('a',0,6000,
        'A real bilingual sentence wraps when its font size changes. '*2)],
        generation_metadata={'translations':{'a':'这是一段字号变化后需要重新排版的双语字幕。'*2}},
        studio_state={'bilingual':{'mode':'bilingual','order':order,'layout':'ink_v1'}})
    p.render_settings.update(play_res_x=width,play_res_y=height);p.validate()
    return p


def boxes(p):
    result=[]
    for c in project_display_cues(p):
        r=resolve_caption_style(p.styles,p.speakers,c,p.style_recipes,
            p.render_settings['play_res_x'],p.render_settings['play_res_y'])
        s=r.style;h,_,o,shadow=ink_block(r);f=(1.,.5,0.)[(s.alignment-1)//3]
        y=s.position_y if s.position_y is not None else p.render_settings['play_res_y']-s.margin_v
        result.append((y-f*h-o,y+(1-f)*h+o+shadow))
    return sorted(result)


@pytest.mark.parametrize('geometry',[False,True])
@pytest.mark.parametrize('layer',['original','translation','group'])
@pytest.mark.parametrize('order',['original_first','translation_first'])
@pytest.mark.parametrize('canvas',[(1920,1080),(1280,720)])
def test_auto_pair_reflows_after_preset_and_size(geometry,layer,order,canvas):
    p=project(*canvas,order);cue=p.cues[0]
    patch=asdict(SubtitleStyle('large','Large',font_family='Microsoft YaHei UI',font_size=72,
                             outline_width=7,primary_color='#FFCC623F',outline_color='#FFFFFFFF'))
    cmd=preset_command(p,['a'],patch,layer=layer,apply_geometry=geometry);cmd.redo()
    assert not any({'position_x','position_y'} & set(v) for v in cue.transform.get('language_layers',{}).values())
    for size in (90,40,68):
        cmd=style_patch_command(p,['a'],{'font_size':size},layer=layer);cmd.redo()
        bounds=boxes(p)
        assert bounds[0][1] <= bounds[1][0],(layer,size,bounds)
        batch=GeometryBatch(p)
        for language in ('original','translation'):
            assert batch.values(cue,language)==resolved_values(p,cue,language,geometry_only=True)
    for family in ('Arial','Microsoft YaHei UI'):
        style_patch_command(p,['a'],{'font_family':family,'font_file':'','font_weight':0,'font_style_name':''},layer=layer).redo()
        bounds=boxes(p);assert bounds[0][1]<=bounds[1][0]


def test_manual_layer_anchors_and_group_anchor_survive_appearance():
    p=project();c=p.cues[0]
    c.transform={'position_x':800.,'position_y':830.,'language_layers':{
        'original':{'position_x':700.,'position_y':650.},'translation':{'position_x':850.,'position_y':400.}}}
    before=deepcopy(c.transform)
    cmd=preset_command(p,['a'],asdict(SubtitleStyle('s','S',font_size=65)),layer='group',apply_geometry=False)
    cmd.redo()
    for name in ('original','translation'):
        assert all(c.transform['language_layers'][name][k]==v for k,v in before['language_layers'][name].items())
    cmd=style_patch_command(p,['a'],{'font_size':50},layer='original');cmd.redo()
    assert c.transform['position_y']==830.
    assert c.transform['language_layers']['translation']['position_y']==400.


def test_complete_legacy_preset_replaces_old_rich_recipe_but_font_edit_keeps_it(tmp_path):
    p=project();c=p.cues[0]
    style_patch_command(p,['a'],{},layer='group',recipe_patch={'effects':{'glow':{'enabled':True,'blur':19}},
        'outline':{'shadow':{'enabled':True,'color':'#FFFF0000','offset_x':20,'opacity':.9}},
        'colors':{'fill':{'type':'linear-gradient','angle':20,'stops':[{'offset':0,'color':'#FF00FF00'},{'offset':1,'color':'#FF0000FF'}]}}}).redo()
    patch=asdict(SubtitleStyle('legacy','Legacy',primary_color='#FFCC623F',outline_width=7,shadow=0))
    for key in ('font_weight','font_style_name','font_file','font_face_index'):patch.pop(key)
    cmd=preset_command(p,['a'],patch,layer='group');cmd.redo()
    def appearance():
        rows=[]
        for shown in project_display_cues(p):
            r=resolve_caption_style(p.styles,p.speakers,shown,p.style_recipes,1920,1080)
            rows.append((r.style.primary_color,r.recipe.colors,r.recipe.outline,r.recipe.effects))
        return rows
    before=appearance()
    assert all(row[0]=='#FFCC623F' and not row[3].get('glow',{}).get('enabled',False) for row in before)
    style_patch_command(p,['a'],{'font_size':66},layer='group').redo()
    assert appearance()==before
    path=save_project(p,tmp_path/'saved.2byteproj');p2=load_project(path)
    assert [(x.appearance_override,x.transform)for x in p2.cues]==[(x.appearance_override,x.transform)for x in p.cues]


@pytest.mark.parametrize('canvas',[(1920,1080),(1280,720)])
def test_breathing_peak_keeps_automatic_rows_separate_and_inside_canvas(canvas):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app=QApplication.instance() or QApplication([])
    from twobyteasr.caption_style.motion_application import motion_command
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.rendering.caption_scene import SceneRasterizer
    from twobyteasr.rendering.caption_playback_cache import PreparedCaption
    from twobyteasr.caption_style.style_recipe import route_recipe
    p=project(*canvas)
    from twobyteasr.caption_style.font_metadata import resolve_local_face
    for style in p.styles:QFontDatabase.addApplicationFont(resolve_local_face(style.font_family)[0].file)
    style_patch_command(p,['a'],{'font_size':58},layer='group').redo()
    motion_command(p,['a'],motion={'entry':{'type':'fade','duration':180},'exit':{'type':'fade','duration':140},
        'loop':{'type':'loop_breathe','duration':1200,'strength':'high'}},language='linked').redo()
    prepared=[]
    for c in project_display_cues(p):
        s=build_visual_cue_snapshot(p,c.id,width=canvas[0],height=canvas[1],resolved_cue=c)
        prepared.append((c.id,PreparedCaption(s,s.stable_hash(),route_recipe(s.style_recipe))))
    r=SceneRasterizer();image,evidence=r.frame(prepared,780,*canvas)
    assert all(row['status']=='rendered'for row in evidence)
    bounds=sorted([row['bounds']for row in evidence],key=lambda b:b[1])
    assert bounds[0][1]+bounds[0][3]<bounds[1][1]
    assert all(x>0 and y>0 and x+w<canvas[0] and y+h<canvas[1] for x,y,w,h in bounds),(bounds,
        [(key,s.snapshot.position_y,s.snapshot.font_family,s.snapshot.font_size,
          ink_block(s.snapshot.resolved_caption),s.snapshot.resolved_caption.line_count,
          s.snapshot.style_recipe.get('layout',{}).get('lineHeightPx'))for key,s in prepared])
    r.close()
