"""Verified text-command submission shared by review and find/replace."""
from dataclasses import dataclass, field
from uuid import uuid4

from ..diagnostics.event_log import emit
from ..projects.studio_runtime_state import state_for


@dataclass
class TextEditResult:
    operation_id: str = field(default_factory=lambda: uuid4().hex)
    states: dict = field(default_factory=dict)
    error: str = ''
    revision_before: int = 0
    revision_after: int = 0
    cue_count: int = 0

    @property
    def changed(self):
        return {key for key, state in self.states.items() if state == 'changed'}


def submit_text_changes(page, values, expected, *, label, operation='replace', operation_id=None, **command_options):
    from .subtitle_text_targets import entry_lookup
    from ..timeline.studio_commands import BatchReplaceTextCommand
    project = page.session.project
    result = TextEditResult(operation_id=operation_id or uuid4().hex)
    result.revision_before = state_for(project).revision
    live = entry_lookup(project, targets=[entry.target for entry in expected.values()])
    accepted = {}
    for key, value in values.items():
        before, now = expected.get(key), live.get(key)
        if before is None or now is None or before.target != now.target:
            result.states[key] = 'missing'
        elif now.text == value:
            result.states[key] = 'already_target'
        elif now != before:
            result.states[key] = 'conflict'
        else:
            accepted[key] = value
    emit('text_edit.command', module=__name__, operation_id=result.operation_id,
         action=operation, project_id=project.project_id, project_object=id(project),
         revision_before=result.revision_before,
         targets=[dict(key=key, **expected[key].target.to_dict()) for key in accepted])
    if accepted:
        try:
            options = dict(command_options)
            records = options.get('proofread_records')
            if records is not None:
                options['proofread_records'] = {key: record for key, record in records.items() if key in accepted}
            command = BatchReplaceTextCommand(project,
                {live[key].target.cue_id: text for key, text in accepted.items() if live[key].target.storage == 'cue'},
                translation_values={live[key].target.cue_id: (text, live[key].target.language)
                                    for key, text in accepted.items() if live[key].target.storage == 'translation'},
                needle=label, changed=page._changed, **options)
            command.setText(label)
            # QUndoStack invokes Python virtual redo through Qt: an exception
            # can reach sys.excepthook while push() still returns normally.
            # Validate/commit in Python first; push then registers that exact
            # completed transaction without executing it a second time.
            command._apply(command.after)
            actual = entry_lookup(project, targets=[live[key].target for key in accepted])
            for key, value in accepted.items():
                result.states[key] = 'changed' if key in actual and actual[key].text == value else 'failed'
            if result.changed:
                command._initial_applied = True
                page.session.undo_stack.push(command)
        except Exception as exc:
            result.error = str(exc)
            result.states.update({key: 'failed' for key in accepted})
    result.revision_after = state_for(project).revision
    result.cue_count = len({live[key].target.cue_id for key in result.changed})
    page._last_text_edit_result = result
    if result.changed:
        history = getattr(page, '_text_edit_operations', None)
        if history is None:
            history = page._text_edit_operations = []
        history.append((project.project_id, result.revision_after, result.operation_id))
        del history[:-128]
    emit('text_edit.result', module=__name__, operation_id=result.operation_id, action=operation,
         project_id=project.project_id, revision_before=result.revision_before,
         revision_after=result.revision_after, states=result.states,
         changed_count=len(result.changed), cue_count=result.cue_count, error=result.error)
    return result


def save_operation_ids(page, project, revision):
    """Capture before starting the writer; later edits get no saved receipt."""
    return tuple(operation_id for project_id, edited_revision, operation_id in
                 getattr(page, '_text_edit_operations', ())
                 if project_id == project.project_id and edited_revision <= revision)


def record_text_save(operation_ids, *, kind, revision, generation, error=''):
    for operation_id in operation_ids:
        emit('text_edit.save', module=__name__, operation_id=operation_id,
             save_kind=kind, saved_revision=revision, saved_generation=generation,
             result='failed' if error else 'saved', error=str(error))
