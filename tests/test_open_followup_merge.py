import copy

import pytest
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.timeline.studio_commands import merge_cues_command


def sample():
    p = SubtitleProject(media=StudioMedia(path='sample.mp4'), cues=[
        StudioCue('24', 66233, 68610, '怖いわー 怖いわー', speaker_id='S00'),
        StudioCue('25', 68610, 71280, 'バーチャル世代怖いわー', speaker_id='S00'),
        StudioCue('26', 71280, 72800, 'でもまあ', speaker_id='S00')])
    p.generation_metadata['language'] = {'code': 'ja'}
    return p


@pytest.mark.parametrize('ids', [('24','25'), ('24','25','26')])
def test_local_merge_preserves_translations_and_roundtrip(ids):
    p=sample()
    for key,text in [('24','好可怕 好可怕'),('25','虚拟世代好可怕'),('26','不过嘛')]:
        st.set_manual(p,key,text)
    before=copy.deepcopy(p.to_dict())
    stack=QUndoStack(); stack.push(merge_cues_command(p,ids))
    expected='好可怕 好可怕 虚拟世代好可怕' + (' 不过嘛' if len(ids)==3 else '')
    assert st.translation_view(p)['24']['text'] == expected
    assert st.cue_status(p,'24') == st.MANUAL
    assert all(key not in p.generation_metadata['translations'] for key in ids[1:])
    merged=copy.deepcopy(p.to_dict())
    reopened=SubtitleProject.from_dict(merged)
    assert st.translation_view(reopened)['24']['text'] == expected
    stack.undo()
    assert p.to_dict()['cues'] == before['cues']
    assert st.snapshot(p) == {k:before['generation_metadata'][k] for k in (st.RECORDS_KEY,st.RENDER_KEY)}
    stack.redo()
    assert st.translation_view(p)['24']['text'] == expected


def test_partial_sequential_merge_never_loses_later_or_repeated_text():
    p=sample(); st.set_manual(p,'24','可怕！'); st.set_manual(p,'26','可怕！')
    stack=QUndoStack(); stack.push(merge_cues_command(p,['24','25']))
    assert st.translation_view(p)['24']['text']=='可怕！'
    assert st.cue_status(p,'24') == st.NEEDS_UPDATE
    stack.push(merge_cues_command(p,['24','26']))
    assert st.translation_view(p)['24']['text']=='可怕！可怕！'
    assert st.cue_status(p,'24') == st.NEEDS_UPDATE
    stack.undo(); stack.undo()
    assert st.translation_view(p)['26']['text']=='可怕！'


def test_nonadjacent_merge_uses_same_atomic_metadata_path():
    p=sample(); st.set_manual(p,'24','第一句'); st.set_manual(p,'26','第三句')
    stack=QUndoStack(); stack.push(merge_cues_command(p,['24','26']))
    assert st.translation_view(p)['24']['text']=='第一句 第三句'
    assert p.cues[1].id=='25'
    stack.undo()
    assert st.translation_view(p)['26']['text']=='第三句'


def test_legacy_map_and_intent_revision_are_preserved():
    from twobyteasr.studio.translation_actions import capture_intent,intent_current
    from types import SimpleNamespace
    p=sample(); p.generation_metadata['translations']={'24':'好可怕','25':'好可怕'}
    page=SimpleNamespace(project=p); intent=capture_intent(page,['24','25'],'zh-Hans')
    stack=QUndoStack(); stack.push(merge_cues_command(p,['24','25']))
    assert st.translation_view(p)['24']['text']=='好可怕 好可怕'
    assert not intent_current(page,intent,'zh-Hans')
    stack.undo()
    assert not intent_current(page,intent,'zh-Hans')
