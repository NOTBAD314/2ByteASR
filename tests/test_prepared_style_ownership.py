import copy
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.caption_style.style_application import StyleApplication
from twobyteasr.caption_style.bulk_style_preparation import prepare_style_job
from twobyteasr.caption_style.prepared_presentation import PreparedPresentationCommand
from twobyteasr.studio.presentation_scope import PresentationScope


def test_worker_owned_command_preserves_undo_and_no_live_aliases():
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('a',0,2000,'alpha'),StudioCue('b',2200,4000,'beta')]);p.validate()
    before=copy.deepcopy([(c.style_id,c.appearance_override,c.transform)for c in p.cues])
    scope=PresentationScope(p.project_id,'all','original',('a','b'))
    action=StyleApplication((id(p),'a','original'),fields={'font_size':75.})
    plan=prepare_style_job((StudioRevisionStore(p).authoring_render(),action,scope,False))
    cmd=PreparedPresentationCommand(p,plan,None);cmd.redo()
    assert p.cues[0].appearance_override is not cmd.after['a'][3]
    assert p.cues[0].appearance_override is not p.cues[1].appearance_override
    p.cues[0].appearance_override['local-note']='unrelated'
    cmd.undo()
    assert [(c.style_id,c.appearance_override,c.transform)for c in p.cues]==before
    cmd.redo();assert 'local-note' not in p.cues[0].appearance_override


def test_cancelled_fallback_stops_before_layout_work(monkeypatch):
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue(str(i),i*2000,i*2000+1800,'text') for i in range(500)]);p.validate()
    from twobyteasr.caption_style.scoped_preset import preset_command
    from twobyteasr.caption_style.caption_layer_transform import GeometryBatch
    calls=[]
    monkeypatch.setattr(GeometryBatch,'values',lambda *a,**k:calls.append(1))
    assert preset_command(p,[c.id for c in p.cues],{'id':'test','font_size':50.},cancel_check=lambda:True) is None
    assert not calls
