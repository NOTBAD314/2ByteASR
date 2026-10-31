import copy
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
from twobyteasr.caption_style.scoped_style import style_patch_command,effective_layer_style
from twobyteasr.caption_style.paint_patch import PaintPatchCommand
from twobyteasr.caption_style.caption_layer_transform import GeometryBatch


@pytest.mark.parametrize('layer',['original','translation','group'])
def test_paint_has_no_geometry_work_and_undo_restores_private_maps(monkeypatch,layer):
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue(str(i),i*2000,i*2000+1800,'text '+str(i),
        transform={'language_layers':{'original':{'position_x':float(i+50)},'translation':{'position_y':float(i+500)}}}) for i in range(40)],
        generation_metadata={'translations':{str(i):'译文'+str(i)for i in range(40)}})
    p.validate();before=copy.deepcopy([(c.appearance_override,c.transform)for c in p.cues])
    styles=copy.deepcopy(p.styles);recipes=copy.deepcopy(p.style_recipes)
    def forbidden(*a,**k):raise AssertionError('paint planned geometry')
    monkeypatch.setattr(GeometryBatch,'values',forbidden)
    command=style_patch_command(p,[c.id for c in p.cues[:30]],{'outline_color':'#FF0066FF'},layer=layer)
    assert isinstance(command,PaintPatchCommand) and len(command.changed_ids)==30
    command.redo()
    for i,cue in enumerate(p.cues):
        for language in ('original','translation'):
            actual=effective_layer_style(p,cue,language).outline_color
            if i<30 and layer in (language,'group'):assert actual=='#FF0066FF'
            else:assert actual!='#FF0066FF'
        assert cue.transform==before[i][1]
    assert p.styles==styles and p.style_recipes==recipes
    assert p.cues[0].appearance_override is not p.cues[1].appearance_override
    command.undo();assert [(c.appearance_override,c.transform)for c in p.cues]==before
    command.redo();assert p.cues[0].appearance_override!=before[0][0]
    assert style_patch_command(p,[c.id for c in p.cues[:30]],{'outline_color':'#FF0066FF'},layer=layer) is None


def test_invalid_color_does_not_touch_any_target():
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,2000,'a')]);p.validate()
    before=copy.deepcopy(p.cues)
    with pytest.raises(ValueError):style_patch_command(p,['a'],{'outline_color':'invalid-rgb'})
    assert p.cues==before


def test_solid_fill_uses_sparse_paint_but_gradient_replacement_keeps_full_recipe():
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,2000,'alpha')]);p.validate()
    patch={'colors':{'fill':{'type':'solid','color':'#FF33AA88'}}}
    cmd=style_patch_command(p,['a'],{'primary_color':'#FF33AA88'},recipe_patch=patch)
    assert isinstance(cmd,PaintPatchCommand)
    cmd.redo();assert effective_layer_style(p,p.cues[0],'original').primary_color=='#FF33AA88'
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    p.style_recipes['default']=StyleRecipe(name='gradient',colors={'fill':{'type':'linear-gradient','stops':[
        {'color':'#FFFFFFFF','position':0.},{'color':'#FF000000','position':1.}]}}).to_dict()
    cmd=style_patch_command(p,['a'],{'primary_color':'#FF33AA88'},recipe_patch=patch)
    assert not isinstance(cmd,PaintPatchCommand)
