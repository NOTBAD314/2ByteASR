import copy
from dataclasses import asdict
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.caption_style.style_application import StyleApplication
from twobyteasr.caption_style.bulk_style_preparation import prepare_style_job
from twobyteasr.caption_style.prepared_presentation import PreparedPresentationCommand
from twobyteasr.caption_style.caption_layer_transform import resolved_values
from twobyteasr.caption_style.scoped_style import effective_layer_style
from twobyteasr.studio.presentation_scope import PresentationScope


def project():
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue(str(i),i*2000,i*2000+1800,'text',
        transform={'language_layers':{'original':{'position_x':100.+i,'position_y':300.,'scale_x':100.,'scale_y':100.},
                                     'translation':{'position_x':100.+i,'position_y':400.,'scale_x':100.,'scale_y':100.}}})for i in range(8)],
        generation_metadata={'translations':{str(i):'translation'for i in range(8)}})
    p.validate();return p


@pytest.mark.parametrize('global_mode',[False,True])
def test_queued_color_and_geometry_publish_one_atomic_undo(global_mode):
    p=project();runtime=state_for(p);deltas=[];runtime.subscribe(deltas.append)
    def authored():
        rows=[dict(asdict(c),appearance_generation=0)for c in p.cues]
        return copy.deepcopy((rows,p.studio_state,p.styles,p.style_recipes))
    before=authored()
    action=StyleApplication((id(p),'0','original'),fields={'outline_color':'#FF0066FF'},replay=False,
        geometry_ops=[dict(ids=tuple(c.id for c in p.cues),language='original',changes={'position_x':350.},
                           mode='absolute',reference_id='0',reset=False,global_mode=global_mode)])
    scope=PresentationScope(p.project_id,'all','original',tuple(c.id for c in p.cues))
    plan=prepare_style_job((StudioRevisionStore(p).authoring_render(),action,scope,False))
    cmd=PreparedPresentationCommand(p,plan,None);cmd.redo()
    assert len(deltas)==1 and all(effective_layer_style(p,c,'original').outline_color=='#FF0066FF' for c in p.cues)
    assert resolved_values(p,p.cues[0],'original')['position_x']==350.
    after=authored()
    cmd.undo();assert authored()==before
    cmd.redo();assert authored()==after
    assert len(deltas)==3


@pytest.mark.parametrize('upgrade',[False,True])
def test_key_snapshot_rolls_back_before_and_after_nested_upgrade(upgrade):
    p=project();runtime=state_for(p)
    p.studio_state['caption_group_transform']={'dx':1.}
    before=copy.deepcopy((p.studio_state,p.generation_metadata))
    with pytest.raises(ValueError):
        with runtime.transaction(p,action_id='group',dirty=DirtyDomain.PROJECT_METADATA,
                                 studio_state_keys=('caption_group_transform',)):
            p.studio_state['caption_group_transform']={'dx':50.}
            if upgrade:
                with runtime.transaction(p,action_id='nested',dirty=DirtyDomain.PROJECT_METADATA):
                    p.generation_metadata['translations']['0']='changed'
                    p.studio_state['new']='new'
            raise ValueError('rollback')
    assert (p.studio_state,p.generation_metadata)==before
    assert runtime._active is None and runtime.commit_count==0
