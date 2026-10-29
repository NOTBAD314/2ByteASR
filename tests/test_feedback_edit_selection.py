from types import SimpleNamespace
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.timeline.studio_commands import add_cue_command, merge_cues_command, SpliceCuesCommand


def project():
    return SubtitleProject(media=StudioMedia(path='fixture.mp4', duration_ms=60000), cues=[
        StudioCue(str(i), i*2000, i*2000+1000, f'第{i}句', original_text=f'第{i}句') for i in range(20)])


def test_add_selects_new_id_in_transaction_and_undo_redo():
    p = project(); state = state_for(p); state.selected_cue_id = '1'
    stack = QUndoStack()
    stack.push(add_cue_command(p, StudioCue('new', 31000, 32000, '')))
    assert state.selected_cue_id == 'new'
    stack.undo(); assert state.selected_cue_id == '1'
    stack.redo(); assert state.selected_cue_id == 'new'


def test_structural_refresh_does_not_restore_selection_by_old_row():
    p = project(); state = state_for(p); state.selected_cue_id = '18'
    command = SpliceCuesCommand(p, 2, 0, [StudioCue('new', 3000, 3900, '')], 'Insert elsewhere')
    command.redo()
    assert state.selected_cue_id == '18'
    command.undo(); assert state.selected_cue_id == '18'


def test_merge_three_uses_every_selected_cue_and_selects_result():
    p = project(); state = state_for(p); state.selected_cue_id = '3'
    stack = QUndoStack(); stack.push(merge_cues_command(p, ['2','3','4']))
    assert len(p.cues) == 18
    assert p.cues[2].text == '第2句第3句第4句'
    assert state.selected_cue_id == '2'
    stack.undo(); assert state.selected_cue_id == '3'


def test_clock_does_not_replace_active_inline_edit():
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    page = SimpleNamespace(_canvas_editor=object(), _text_input_in_progress=False)
    controller = SimpleNamespace(page=page, session=SimpleNamespace(
        observed_playhead_target_id='', playhead_target_id='new', selected_cue_id='new'))
    controller.resolve_playhead_target = lambda _: SimpleNamespace(id='old')
    controller._mirror_clock_selection = lambda cue_id: setattr(controller.session, 'selected_cue_id', cue_id)
    StudioCueController.sync_playhead_target(controller, 1000)
    assert controller.session.selected_cue_id == 'new'
    page._canvas_editor = None
    StudioCueController.sync_playhead_target(controller, 2000, force=True)
    assert controller.session.selected_cue_id == 'old'


def test_delayed_clock_keeps_inserted_target_after_commit_until_explicit_seek():
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    p=project()
    page=SimpleNamespace(_canvas_editor=None,_text_input_in_progress=False,
                         _inserted_selection_target=(id(p),'new'))
    controller=SimpleNamespace(page=page,session=SimpleNamespace(project=p,
        observed_playhead_target_id='',playhead_target_id='new',selected_cue_id='new'))
    controller.resolve_playhead_target=lambda _:SimpleNamespace(id='old')
    controller._mirror_clock_selection=lambda key:setattr(controller.session,'selected_cue_id',key)
    StudioCueController.sync_playhead_target(controller,2000)
    assert controller.session.selected_cue_id=='new'
    StudioCueController.sync_playhead_target(controller,2000,force=True)
    assert controller.session.selected_cue_id=='old'
    assert page._inserted_selection_target is None
