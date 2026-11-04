"""Native restore transitions and the current editor's proofreading document."""
from types import SimpleNamespace

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

APP=QApplication.instance() or QApplication([])


def test_text_review_allows_duration_probe_but_rejects_real_content_changes():
    from twobyteasr.glossary.glossary_proofread import _TextReviewBinding
    from twobyteasr.studio.studio_find_replace import PreviewBinding
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    p=SubtitleProject(media=StudioMedia('original.mp4',duration_ms=5000),
                      cues=[StudioCue('a',0,1000,'原句')]);p.validate()
    binding=_TextReviewBinding.capture(p);ordinary=PreviewBinding.capture(p)
    p.media.duration_ms=6000
    for asset in p.media_pool:asset.duration_ms=6000
    assert binding.matches(p)
    assert not ordinary.matches(p)
    p.cues[0].text='改句';assert not binding.matches(p)
    p.cues[0].text='原句';p.cues[0].end_ms=1200;assert not binding.matches(p)
    p.cues[0].end_ms=1000;p.media.path='replacement.mp4';assert not binding.matches(p)


def test_native_maximized_transition_is_not_shrunk_by_qt_normal_constraints(monkeypatch):
    from twobyteasr.app import window_constraints as bounds
    w=QWidget();w.setGeometry(0,0,1200,800)
    monkeypatch.setattr(bounds,'available_rect',lambda *_a,**_k:QRect(8,8,1184,784))
    monkeypatch.setattr(bounds,'_native_window_is_special',lambda _w:True)
    try:
        assert not w.isMaximized()  # Qt has not received the HWND state yet.
        bounds.constrain(w)
        assert w.geometry()==QRect(0,0,1200,800)
        monkeypatch.setattr(bounds,'_native_window_is_special',lambda _w:False)
        bounds.constrain(w)
        assert w.geometry()==QRect(8,8,1184,784)  # ordinary windows still fit
    finally:w.close();w.deleteLater();APP.processEvents()


def test_studio_proofread_uses_unsaved_text_and_applies_one_undo(tmp_path,monkeypatch):
    from tests.test_studio_style_controller import _page,_finish
    from tests.test_glossary_proofread import _wait
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    from twobyteasr.projects.studio_project import save_project,load_project
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
    import subtitle_core as legacy
    _,studio=_page(tmp_path,monkeypatch)
    legacy.add_learned_mapping('入口词库','CHIOCHOO','CHICHOO',origin='手动')
    identity=next(x['id'] for x in legacy.glossary_catalog() if x['name']=='入口词库')
    studio.project.glossary_ids=[identity]
    save_project(studio.project,studio.project_path)
    studio.undo_stack.push(SetCueFieldsCommand(studio.project,'a',{'text':'未保存 CHIOCHOO'},'edit'))
    before=studio.undo_stack.index()
    window=SimpleNamespace(studio_page=studio,_prepare_glossary_for_task=lambda:True)
    review=GlossaryProofreadPage(window)
    try:
        review.open_task(studio.project_path,studio.project,studio=studio)
        assert _wait(review)
        [issue]=review._by_id['a']['issues']
        assert (issue['replacement'],issue['checked'],issue['default'])==('CHICHOO',False,True)
        assert load_project(studio.project_path).cues[0].text=='First'
        review._toggle_issue('a',0);assert _wait(review)  # adopting writes to the open document
        assert studio.project.cues[0].text=='未保存 CHICHOO' and review._by_id['a']['issues'][0]['checked']
        # An ordinary Studio edit: Studio's own save writes the file.
        assert not studio.undo_stack.isClean()
        studio.project_controller.save()
        assert load_project(studio.project_path).cues[0].text=='未保存 CHICHOO'
        assert studio.undo_stack.index()==before+1
        studio.undo_stack.undo()
        assert studio.project.cues[0].text=='未保存 CHIOCHOO'
    finally:
        review.shutdown();review.deleteLater();_finish(studio)


def test_explicit_editor_binding_supports_unsaved_document_and_rejects_replacement(monkeypatch):
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    first=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',0,1000,'原句')]);first.validate()
    second=SubtitleProject.from_dict(first.to_dict())
    studio=SimpleNamespace(project_path=None,session=SimpleNamespace(project=first))
    review=GlossaryProofreadPage(SimpleNamespace(studio_page=studio))
    monkeypatch.setattr(review,'_run',lambda *_:None)
    monkeypatch.setattr(review,'_fill_libraries',lambda *_a,**_k:None)
    try:
        review.open_task(None,first,studio=studio)
        assert review._live_project()==(first,studio)
        studio.session.project=second
        assert review._live_project()==(None,None)
    finally:review.shutdown();review.deleteLater();APP.processEvents()
