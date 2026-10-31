from dataclasses import replace
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.caption_style.caption_layer_transform import GeometryBatch,resolved_values,GEOMETRY
from twobyteasr.caption_style.bilingual_layout import settings_from_state
from twobyteasr.caption_style.bilingual_geometry import geometry_pair


@pytest.mark.parametrize('alignment',range(1,10))
@pytest.mark.parametrize('order',['original_first','translation_first'])
def test_geometry_matches_existing_wrapping_and_anchors(alignment,order):
    p=SubtitleProject(StudioMedia('',width=1920,height=1080),cues=[StudioCue('a',0,3000,
        'A wrapped original with punctuation. '*8)],generation_metadata={'translations':{'a':'这是一条带标点、需要自动换行的译文。'*6}},
        studio_state={'bilingual':{'mode':'bilingual','order':order,'layout':'ink_v1'}})
    p.validate();p.styles[0].alignment=alignment
    p.styles[0].scale_x=117.;p.styles[0].scale_y=91.
    p.styles[0].outline_width=7.2;p.styles[0].shadow=4.
    batch=GeometryBatch(p)
    for language in ('original','translation'):
        assert batch.values(p.cues[0],language)==resolved_values(p,p.cues[0],language,geometry_only=True)


def test_complete_explicit_geometry_does_not_measure_any_layout(monkeypatch):
    values=dict(position_x=-3.,position_y=424.,scale_x=115.,scale_y=93.,rotation=12.,anchor_x=.3,anchor_y=.7)
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,3000,'text',transform={'language_layers':{'original':values}})],
                     generation_metadata={'translations':{'a':'译文'}})
    p.validate()
    import twobyteasr.caption_style.bilingual_geometry as module
    monkeypatch.setattr(module,'geometry_pair',lambda *a,**k:(_ for _ in ()).throw(AssertionError('unneeded layout')))
    actual=GeometryBatch(p).values(p.cues[0],'original')
    assert all(actual[k]==v for k,v in values.items())


def test_authored_marks_and_group_transforms_keep_full_path():
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,3000,'text')],generation_metadata={'translations':{'a':'译文'}})
    p.validate();settings=settings_from_state(p.studio_state)
    assert geometry_pair(p,p.cues[0],'译文',replace(settings,group_transform={'defaults':{}})) is None
    p.cues[0].appearance_override['text_marks']=[{'start':0,'end':1}]
    assert geometry_pair(p,p.cues[0],'译文',settings) is None
