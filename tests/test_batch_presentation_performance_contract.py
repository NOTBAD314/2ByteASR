"""Reuse is local to a transaction and preserves per-cue state and undo."""
import copy
from tests.test_subtitle_translation import make_project
from twobyteasr.caption_style import style_field_patch as patcher


def test_materialize_same_presentation_once_and_preserve_distinct_transform_metadata(monkeypatch):
    project=make_project()
    for cue in project.cues:
        cue.speaker_id='S00'
        cue.transform={'private_marker':cue.id,'initial_layout':{'version':1,'position_x':960,'position_y':900,'source':cue.id}}
    before=copy.deepcopy(project.cues)
    original=patcher.resolve_cue_visual;calls=[]
    def counted(*args):
        calls.append(args[1].id);return original(*args)
    monkeypatch.setattr(patcher,'resolve_cue_visual',counted)
    command=patcher.style_fields_command(project,[c.id for c in project.cues],{'font_size':77})
    assert len(calls)==1
    command.redo()
    assert all(c.transform['private_marker']==c.id for c in project.cues)
    assert len({c.style_id for c in project.cues})==1
    project.cues[0].appearance_override['font_size']=66
    assert project.cues[1].appearance_override['font_size']==77
    command.undo()
    for a,b in zip(project.cues,before):
        assert a.transform==b.transform and a.appearance_override==b.appearance_override and a.style_id==b.style_id


def test_distinct_geometry_and_appearance_are_never_coalesced():
    project=make_project()
    project.cues[0].transform={'position_x':200}
    project.cues[1].transform={'position_x':400}
    project.cues[1].appearance_override={'primary_color':'#FF223344'}
    before=[patcher.resolve_cue_visual(project,c).style for c in project.cues]
    command=patcher.style_fields_command(project,[c.id for c in project.cues],{'font_size':77})
    command.redo()
    after=[patcher.resolve_cue_visual(project,c).style for c in project.cues]
    assert [(s.position_x,s.primary_color) for s in after]==[(s.position_x,s.primary_color) for s in before]


def test_canvas_multi_drag_and_scale_are_one_undo_step(page):
    from tests.test_style_effective_selection import choose,visuals
    choose(page,'all')
    before=visuals(page.project)
    active=before[page.session.selected_cue_id]
    from twobyteasr.caption_style.visual_snapshot import _anchor
    def point(style):return _anchor(style,1920,1080)[:2]
    x,y=point(active)
    count=page.undo_stack.count()
    page.style_controller._commit_canvas_style(position=(x+10,y-20),font_size=active.font_size*1.5)
    after=visuals(page.project)
    for cue_id,old in before.items():
        x,y=point(old)
        assert (after[cue_id].position_x,after[cue_id].position_y)==(x+10,y-20)
        assert after[cue_id].font_size==old.font_size*1.5
        assert after[cue_id].primary_color==old.primary_color
    assert page.undo_stack.count()==count+1
    page.undo_stack.undo();assert visuals(page.project)==before
    page.undo_stack.redo();assert visuals(page.project)==after


from tests.test_style_effective_selection import page


def test_style_revision_reuses_state_but_metadata_edit_recaptures(monkeypatch):
    from tests.test_studio_state_freeze_sharing import _project
    from twobyteasr.projects.studio_revisions import StudioRevisionStore,freeze_json
    from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain as D
    project=_project(100)
    store=StudioRevisionStore(project)
    state=state_for(project);state.subscribe(store.consume)
    old=store.render.studio_state
    command=patcher.style_fields_command(project,[c.id for c in project.cues],{'font_size':77})
    command.redo()
    assert store.render.studio_state is old
    with state.transaction(project,action_id='metadata',dirty=D.PROJECT_METADATA):
        project.studio_state['manual_caption_text']['c3']='改过'
    assert store.render.studio_state==freeze_json(project.studio_state)
    assert store.render.studio_state is not old


def test_batch_model_and_timeline_notifications_are_coalesced(page,monkeypatch):
    signals=[]
    page.cue_model.dataChanged.connect(lambda a,b,*_:signals.append((a.row(),b.row())))
    page.cue_model.refresh_cues([c.id for c in page.project.cues])
    assert signals==[(0,len(page.project.cues)-1)]
    calls=[];original=page.timeline._track_layout
    def layout():calls.append(1);return original()
    monkeypatch.setattr(page.timeline,'_track_layout',layout)
    page.timeline._text_layout_cache={('a',1):'a',('b',1):'b',('other',1):'retained'}
    page.timeline.invalidate_cues(['a','b'])
    assert len(calls)==1
    assert page.timeline._text_layout_cache=={('other',1):'retained'}


def test_filtered_batch_rebuilds_rows_once(page,monkeypatch):
    model=page.cue_model
    model.scope_ids=None;model.query='新文字'
    resets=[];original=model.refresh
    def refresh():resets.append(1);return original()
    monkeypatch.setattr(model,'refresh',refresh)
    page.project.cues[0].text='新文字'
    model.refresh_cues([c.id for c in page.project.cues],(3,4))
    assert len(resets)==1 and model.rowCount()==1


def test_web_group_scale_uses_the_measured_overlay_origin(page,monkeypatch):
    from tests.test_style_effective_selection import choose
    choose(page,'all')
    for cue in page.project.cues:
        page.project.style_recipes[cue.style_id]={'webTheme':{'id':'test-only'}}
    page.position_overlay._origin_font_size=100
    ratios=[]
    def scale(project,cue,ratio,*args):ratios.append(ratio);return {'test_ratio':ratio}
    monkeypatch.setattr('twobyteasr.caption_style.web_placement.scaled_placement',scale)
    # No render is requested by the test; the group command must keep the
    # same measured origin used by the existing single-cue canvas path.
    monkeypatch.setattr(page,'_consume_state_delta',lambda *_:None)
    page.style_controller._commit_canvas_style(font_size=150)
    assert ratios==[1.5]*len(page.project.cues)


def test_filtered_style_edit_keeps_membership_and_multi_selection(page):
    from tests.test_style_effective_selection import choose,visuals
    page.cue_model.query=page.project.cues[0].text
    page.cue_model.refresh()
    choose(page,'all')
    selected=set(page._style_target_ids());resets=[]
    page.cue_model.modelReset.connect(lambda:resets.append(1))
    page.style_font_size.setValue(77);page._commit_style_now()
    assert not resets and set(page._style_target_ids())==selected
    assert all(s.font_size==77 for i,s in visuals(page.project).items() if i in selected)
    page.style_outline_width.setValue(4.5);page._commit_style_now()
    assert not resets and set(page._style_target_ids())==selected
    assert all(s.outline_width==4.5 and s.font_size==77 for i,s in visuals(page.project).items() if i in selected)
