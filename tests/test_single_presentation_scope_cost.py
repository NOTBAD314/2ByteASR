"""Inspector single-target queries do not walk screen-off captions."""
from types import SimpleNamespace
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.timeline.selection_scope import SelectionScope
from twobyteasr.studio.presentation_scope import capture_scope

class CountingCues(list):
    def __iter__(self):
        self.visits+=len(self)
        return super().__iter__()

def test_single_current_and_selected_scopes_use_existing_canonical_index():
    p=SubtitleProject(StudioMedia('',duration_ms=30000),cues=[StudioCue(str(i),i*2,i*2+1,'字幕',speaker_id='A') for i in range(2000)])
    p.validate();p.cues=CountingCues(p.cues);p.cues.visits=0
    p.render_settings['_cue_domain']='timeline';state_for(p)
    p.cues.visits=0
    page=SimpleNamespace(project=p,selected_cue_id='1999',selection_model=SimpleNamespace(scope=SelectionScope.explicit(['1999'])),
                         timeline=SimpleNamespace(locked_speakers=set()))
    assert capture_scope(page,scope='current',layer='original').cue_ids==('1999',)
    assert capture_scope(page,scope='selected',layer='original').cue_ids==('1999',)
    assert p.cues.visits==0
    p.studio_state['locked_speakers']=['A']
    assert capture_scope(page,scope='current',layer='translation').locked_ids==('1999',)
    assert p.cues.visits==0

def test_replaced_cue_list_falls_back_until_runtime_is_rebound():
    p=SubtitleProject(StudioMedia('',duration_ms=1000),cues=[StudioCue('old',0,100,'原字幕')]);p.validate();state_for(p)
    p.cues=[StudioCue('new',0,100,'新字幕')]
    page=SimpleNamespace(project=p,selected_cue_id='new',timeline=SimpleNamespace(locked_speakers=set()))
    assert capture_scope(page,scope='current',layer='original').cue_ids==('new',)
