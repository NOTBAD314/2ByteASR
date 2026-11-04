import copy

from PySide6.QtGui import QUndoStack
from tests.test_subtitle_translation import make_project, FakeProvider
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.timeline.studio_commands import delete_cues_command


def test_late_translation_cannot_resurrect_deleted_or_undone_entity():
    p = make_project(['アリスが来た'])
    result = st.translate(st.translation_source(p), ['c0'], FakeProvider(), target='zh-Hans', retry_wait=lambda _: True)
    assert 'c0' in result.translations
    undo_result = copy.deepcopy(result)
    stack = QUndoStack(); stack.push(delete_cues_command(p, ['c0']))
    st.apply_translation_result(p, result)
    assert not p.cues and 'c0' not in st.records_of(p)
    assert 'c0' in result.discarded
    stack.undo()
    st.apply_translation_result(p, undo_result)
    assert p.cues[0].text == 'アリスが来た'
    assert 'c0' in undo_result.discarded
    assert 'c0' not in p.generation_metadata.get('translations', {})
