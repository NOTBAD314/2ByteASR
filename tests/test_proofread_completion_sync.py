"""Proofreading updates canonical completion data without rebuilding a hidden page."""
from types import SimpleNamespace,MethodType
from twobyteasr.app.ui import MainWindow

def workspace(tmp_path,visible=False):
    path=tmp_path/'copied-project.2byteproj';path.write_text('owned fixture',encoding='utf-8')
    live=object();refreshes=[]
    owner=SimpleNamespace(_completion_tasks=[(SimpleNamespace(project_path=str(path)),object())],
        glossary_proofread_page=SimpleNamespace(_project_path=str(path),_live_project=lambda:(live,None)),
        result_preview=SimpleNamespace(isVisible=lambda:visible),
        _refresh_completion_preview=lambda:refreshes.append('refresh'))
    owner._flush_pending_completion_preview=MethodType(MainWindow._flush_pending_completion_preview,owner)
    return owner,path,live,refreshes

def test_hidden_preview_keeps_live_data_and_coalesces_twenty_edits(tmp_path):
    owner,path,live,refreshes=workspace(tmp_path)
    for _ in range(20):MainWindow._glossary_proofread_applied(owner,str(path))
    assert owner._completion_tasks[0][1] is live
    assert not refreshes and owner._completion_preview_dirty
    owner._flush_pending_completion_preview(force=True)
    owner._flush_pending_completion_preview(force=True)
    assert refreshes==['refresh'] and not owner._completion_preview_dirty

def test_visible_completion_is_updated_immediately(tmp_path):
    owner,path,live,refreshes=workspace(tmp_path,True)
    MainWindow._glossary_proofread_applied(owner,str(path))
    assert owner._completion_tasks[0][1] is live and refreshes==['refresh']
    assert not owner._completion_preview_dirty
