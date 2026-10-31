"""The two scope dimensions apply the same preset and a subsequent field edit."""
from copy import deepcopy
from dataclasses import asdict
import pytest
from tests.test_presentation_scope_contract import page,expected
from tests.test_studio_interaction_style import choose
from twobyteasr.projects.studio_project import SubtitleStyle
from twobyteasr.caption_style.scoped_style import effective_layer_style
from twobyteasr.caption_style.scoped_style import style_patch_command


@pytest.mark.parametrize('scope',['current','selected','speaker','all'])
@pytest.mark.parametrize('layer',['original','translation','group'])
@pytest.mark.parametrize('geometry',[False,True])
def test_preset_then_one_field_is_one_undo_per_action(page,monkeypatch,scope,layer,geometry):
    page.style_scope.setCurrentIndex(page.style_scope.findData(scope))
    page.style_layer.setCurrentIndex(page.style_layer.findData(layer))
    page.style_apply_geometry.setChecked(geometry);page.undo_stack.clear()
    p=page.project;before=deepcopy([(c.appearance_override,c.transform,c.style_id)for c in p.cues])
    before_faces={(c.id,l):tuple(getattr(effective_layer_style(p,c,l),k)for k in
        ('font_size','primary_color','outline_color','outline_width'))for c in p.cues for l in ('original','translation')}
    patch=asdict(SubtitleStyle('matrix','Matrix',font_size=62,primary_color='#FFCC623F',
        outline_color='#FFFFFFFF',outline_width=7,shadow=2,position_x=600,position_y=800))
    choose(page,monkeypatch,patch)
    assert page.undo_stack.count()==1
    preset_state=deepcopy([(c.appearance_override,c.transform,c.style_id)for c in p.cues])
    page.style_font_size.setValue(74);page._commit_style_now()
    assert page.undo_stack.count()==2
    targets=expected(page,scope)
    for c in p.cues:
        for language in ('original','translation'):
            face=effective_layer_style(p,c,language)
            edited=c.id in targets and (layer=='group' or layer==language)
            if edited:
                assert face.font_size==74
                assert face.primary_color=='#FFCC623F' and face.outline_color=='#FFFFFFFF' and face.outline_width==7
            else:assert tuple(getattr(face,k)for k in ('font_size','primary_color','outline_color','outline_width'))==before_faces[c.id,language]
    after=deepcopy([(c.appearance_override,c.transform,c.style_id)for c in p.cues])
    page.undo_stack.undo();assert [(c.appearance_override,c.transform,c.style_id)for c in p.cues]==preset_state
    page.undo_stack.undo();assert [(c.appearance_override,c.transform,c.style_id)for c in p.cues]==before
    page.undo_stack.redo();page.undo_stack.redo()
    assert [(c.appearance_override,c.transform,c.style_id)for c in p.cues]==after


def test_group_mixed_includes_the_other_language(page):
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
    page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
    page._load_style_inspector()
    assert '混合' in page.style_font_size.lineEdit().text()
    assert '字号' in page.style_scope_summary.text() and '颜色' in page.style_scope_summary.text()


def test_inspector_materializes_stale_solid_and_keeps_gradient(page):
    p=page.project;c=p.cues[0]
    p.style_recipes[c.style_id]={'name':'old','colors':{'fill':'#FFFFFFFF'}}
    style_patch_command(p,[c.id],{'primary_color':'#FFCC623F'},changed=page._changed).redo()
    page.select_cue(c.id)
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'));page._load_style_inspector()
    assert page._fill_spec.color=='#FFCC623F'
    style_patch_command(p,[c.id],{},recipe_patch={'colors':{'fill':{
        'type':'linear-gradient','angle':0,'stops':[{'offset':0,'color':'#FFFF0000'},{'offset':1,'color':'#FF0000FF'}]}}},
        changed=page._changed).redo()
    page._load_style_inspector()
    assert page._fill_spec.kind=='linear-gradient'
