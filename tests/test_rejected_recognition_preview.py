"""Actual Studio delta handlers must not turn rejected previews into captions."""
from dataclasses import asdict
from tests.test_round42_studio_recognition import _page as _make_page


def _page(monkeypatch,tmp_path):
    page=_make_page(monkeypatch,tmp_path)
    page.project.validate()
    return page


def delta(page,state,rows):
    page.apply_recognition_cue_delta(dict(source_path=page.project.media.path,state=state,cues=rows))


def test_zero_final_preserves_existing_edits_and_discards_only_owned_preview(monkeypatch,tmp_path):
    page=_page(monkeypatch,tmp_path)
    try:
        old=page.project.cues[0];old.text='My manual edit';old.appearance_override={'outline_width':3.5}
        before=asdict(old)
        page._recognition_replace_baseline_ids={old.id}
        delta(page,'provisional',[dict(id='new-preview',start_ms=5000,end_ms=6000,text='Wrong candidate')])
        assert len(page.project.cues)==2
        delta(page,'final',[])
        assert [asdict(c) for c in page.project.cues]==[before]
        assert page._recognition_replace_baseline_ids is None
    finally:page.close_page()


def test_cached_provisional_id_cannot_overwrite_existing_caption(monkeypatch,tmp_path):
    page=_page(monkeypatch,tmp_path)
    try:
        old=page.project.cues[0];before=asdict(old)
        delta(page,'provisional',[dict(id=old.id,start_ms=100,end_ms=300,text='Cached wrong text')])
        assert asdict(page.project.cues[0])==before
    finally:page.close_page()


def test_failure_keeps_user_edited_preview_and_removes_unaccepted_candidate(monkeypatch,tmp_path):
    page=_page(monkeypatch,tmp_path)
    try:
        delta(page,'provisional',[dict(id='edited',start_ms=5000,end_ms=6000,text='Candidate A'),
                                  dict(id='unaccepted',start_ms=7000,end_ms=8000,text='Candidate B')])
        edited=next(c for c in page.project.cues if c.id=='edited');edited.text='Manual repaired text'
        page.fail_recognition_runtime('all ranges quarantined')
        assert {c.id:c.text for c in page.project.cues}=={'cue-old':'旧正式字幕','edited':'Manual repaired text'}
    finally:page.close_page()
