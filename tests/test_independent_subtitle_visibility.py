"""Source and translated ink have separate persisted eyes in every renderer."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker,save_project,load_project
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.caption_style.bilingual_layout import project_display_cues
from twobyteasr.caption_style.subtitle_visibility import translation_key
from twobyteasr.rendering.ass_compiler import compile_ass


def fixture(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',0,5000,'原文甲',speaker_id='S00'),StudioCue('b',0,5000,'原文乙',speaker_id='S01'),StudioCue('c',5100,8000,'没有译文',speaker_id='S02')])
    page.project.speakers=[StudioSpeaker(k) for k in ('S00','S01','S02')]
    st.set_manual(page.project,'a','译文甲',target='zh-Hans');st.set_manual(page.project,'b','译文乙',target='zh-Hans')
    page.project.studio_state['bilingual']={'mode':'bilingual'}
    page.timeline.bilingual=True;page.timeline.set_project(page.project)
    return app,page


def test_single_eye_preserves_other_speakers_and_translation_undo_save(tmp_path,monkeypatch):
    app,page=fixture(tmp_path,monkeypatch);p=page.project
    page._subtitle_visibility_changed('S00',False)
    assert p.studio_state['subtitle_track_visibility']=={'S00':False}
    assert {c.text for c in project_display_cues(p)}=={'译文甲','原文乙','译文乙','没有译文'}
    ass=compile_ass(p)
    assert '译文甲' in ass and '原文甲' not in ass and '原文乙' in ass
    assert any(c.id=='a' for c in page._ass_preview_snapshot(p).cues)
    page.undo_stack.undo()
    assert '原文甲' in {c.text for c in project_display_cues(p)}
    page.undo_stack.redo()
    restored=load_project(save_project(p,tmp_path/'saved.2byteproj'))
    assert {c.text for c in project_display_cues(restored)}=={'译文甲','原文乙','译文乙','没有译文'}
    page.close_page();page.deleteLater();app.processEvents()


def test_translation_eye_changes_only_translation_language_key(tmp_path,monkeypatch):
    app,page=fixture(tmp_path,monkeypatch);p=page.project
    key=translation_key(p);page._subtitle_visibility_changed(key,False)
    assert p.studio_state['subtitle_track_visibility']=={key:False}
    assert {c.text for c in project_display_cues(p)}=={'原文甲','原文乙','没有译文'}
    assert set(c.id for c in p.cues)=={'a','b','c'}
    page.undo_stack.undo()
    assert '译文甲' in {c.text for c in project_display_cues(p)}
    page.close_page();page.deleteLater();app.processEvents()


def test_missing_translation_and_multiselection_do_not_switch_text_layer(tmp_path,monkeypatch):
    app,page=fixture(tmp_path,monkeypatch)
    page.timeline.set_subtitle_layer('translation');page.select_cue('c')
    page._edit_subtitle_at_playhead()
    assert page._caption_draft.target.layer=='translation' and page.subtitle_edit_input.toPlainText()==''
    page._cancel_canvas_inline_edit()
    page.timeline.set_subtitle_layer('original');page.select_cue('a')
    page.timeline.set_selected_ids({'a','b'},'a')
    page._edit_subtitle_at_playhead()
    assert getattr(page,'_caption_draft',None) is None
    page.close_page();page.deleteLater();app.processEvents()


def test_language_srt_exports_respect_independent_eyes(tmp_path,monkeypatch):
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    app,page=fixture(tmp_path,monkeypatch);p=page.project
    p.generation_metadata['language']={'code':'ja'}
    page._subtitle_visibility_changed('S00',False)
    result=export_language_layers(p,tmp_path/'layers','visible',layers=('original','translation','bilingual'))
    texts={a.layer:a.path.read_text(encoding='utf-8-sig') for a in result.artifacts}
    assert '原文甲' not in texts['original'] and '原文乙' in texts['original']
    assert '译文甲' in texts['translation'] and '译文乙' in texts['translation']
    assert '原文甲' not in texts['bilingual'] and '译文甲' in texts['bilingual']
    page.close_page();page.deleteLater();app.processEvents()


def test_explicit_original_export_overrides_display_mode_but_respects_eyes(tmp_path,monkeypatch):
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    app,page=fixture(tmp_path,monkeypatch);p=page.project;p.generation_metadata['language']={'code':'ja'}
    p.studio_state['bilingual']={'mode':'translation'}
    page._subtitle_visibility_changed(translation_key(p),False)
    result=export_language_layers(p,tmp_path/'original-only','visible',layers=('original',))
    text=result.artifacts[0].path.read_text(encoding='utf-8-sig')
    assert '原文甲' in text and '原文乙' in text and '译文甲' not in text
    page.close_page();page.deleteLater();app.processEvents()


def test_hidden_translation_does_not_return_in_bilingual_srt(tmp_path,monkeypatch):
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    app,page=fixture(tmp_path,monkeypatch);p=page.project;p.generation_metadata['language']={'code':'ja'}
    page._subtitle_visibility_changed(translation_key(p),False)
    result=export_language_layers(p,tmp_path/'hidden-translation','visible',layers=('original','bilingual'))
    for artifact in result.artifacts:
        text=artifact.path.read_text(encoding='utf-8-sig')
        assert '原文甲' in text and '原文乙' in text and '译文甲' not in text and '译文乙' not in text
    page.close_page();page.deleteLater();app.processEvents()


def test_language_export_preview_matches_actual_speaker_files(tmp_path,monkeypatch):
    from twobyteasr.exports.studio_subtitle_export import export_language_layers,planned_subtitle_files,SubtitleExportOptions
    app,page=fixture(tmp_path,monkeypatch);p=page.project;p.generation_metadata['language']={'code':'ja'}
    p.studio_state['bilingual']={'mode':'translation'};page._subtitle_visibility_changed(translation_key(p),False)
    target=tmp_path/'preview';options=SubtitleExportOptions(frozenset({'srt'}),'per_speaker')
    planned=planned_subtitle_files(p,target,'visible',options,layers=('original',))
    actual=export_language_layers(p,target,'visible',layers=('original',),speaker_mode='per_speaker')
    assert len(planned)==3 and {r.name for r in planned}=={a.path.name for a in actual.artifacts}
    page.close_page();page.deleteLater();app.processEvents()
