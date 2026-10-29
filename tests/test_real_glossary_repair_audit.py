"""Offscreen audit bootstrap and failure diagnostics, without loading real data."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.acceptance.real_glossary_repair_audit import project_ready, start, wait_state


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_actual_lazy_studio_page_can_be_sampled_before_project_entry(app, tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.studio.studio_readiness import StudioReadiness
    from twobyteasr.projects.studio_project import StudioMedia,SubtitleProject
    page=SubtitleStudioPage()
    assert not hasattr(page,'_readiness')
    state=wait_state(SimpleNamespace(),page,'normal Home entry')
    assert state['readiness']['initialized'] is False
    assert state['project_view_state']=='hub' and state['project_id'] is None
    assert not project_ready(page,tmp_path/'isolated.2byteproj')

    gate=page._readiness=StudioReadiness(page)
    gate.profile={'gui_gaps_ms':list(range(50)),'stages_ms':{'读取工程':1.25}}
    gate.completed={'读取工程'}
    page.session.project=SubtitleProject(media=StudioMedia(path=''))
    page.session.project_path=tmp_path/'isolated.2byteproj'
    gate.ready=True
    state=wait_state(SimpleNamespace(),page,'loaded')
    assert state['readiness']['initialized'] and state['readiness']['ready']
    assert state['readiness']['profile']['recent_gui_gaps_ms']==list(range(34,50))
    assert state['readiness']['profile']['gui_gap_count']==50
    assert gate.profile['gui_gaps_ms']==list(range(50))
    assert project_ready(page,tmp_path/'isolated.2byteproj')
    assert not project_ready(page,tmp_path/'other.2byteproj')
    assert json.loads(json.dumps(state))['readiness']['completed']==['读取工程']


class AuditWindow(QWidget):
    """Keep Qt ownership real while replacing visible entry and project I/O."""
    def __init__(self):
        super().__init__()
        self.studio_page=SimpleNamespace(project=None,project_path=None,
            video=SimpleNamespace(controller=None),isVisible=lambda:False)
        self.opens=[];self.closed=False

    def isVisible(self):return True
    def showNormal(self):pass
    def open_studio_project(self,path,**kwargs):self.opens.append((path,kwargs))
    def close(self):self.closed=True;return True


def make_audit(tmp_path):
    plan={'project_path':str(tmp_path/'isolated.2byteproj'),
        'glossary_path':str(tmp_path/'isolated-glossary.json'),'project_id':'isolated',
        'live':False,'approved_aliases_sha256':'isolated'}
    (tmp_path/'real-glossary-repair-plan.json').write_text(json.dumps(plan),'utf8')
    window=AuditWindow();start(window,tmp_path)
    audit=window._acceptance_audit;audit.timer.stop()
    return window,audit


def test_first_tick_enters_project_before_readiness_exists(app,tmp_path):
    window,audit=make_audit(tmp_path)
    audit.tick()
    assert len(window.opens)==1
    assert window.opens[0][0]==tmp_path/'isolated.2byteproj'
    assert window.opens[0][1]['source']=='human-approved-real-glossary-repair'
    assert audit.result['checks'][0]['passed']
    assert audit.result['last_wait_state']['readiness']['initialized'] is False
    assert callable(audit.waiting) and audit.waiting() is False
    assert not audit.finished and not window.closed


@pytest.mark.parametrize('failed_persistence',[False,True])
def test_diagnostic_failures_preserve_original_exception_and_close(app,tmp_path,monkeypatch,failed_persistence):
    window,audit=make_audit(tmp_path)
    def bad_state():raise RuntimeError('original state sampling failure')
    def bad_capture(*args):raise OSError('capture unavailable')
    def bad_write():raise OSError('report filesystem unavailable')
    monkeypatch.setattr(audit,'wait_state',bad_state)
    monkeypatch.setattr(audit,'shot',bad_capture)
    if failed_persistence:monkeypatch.setattr(audit,'write',bad_write)
    audit.tick()
    assert audit.finished and not audit.timer.isActive() and window.closed
    assert window.result_exit_code==1 and audit.result['passed'] is False
    assert 'original state sampling failure' in audit.result['error']
    assert audit.result['failed_wait_state']['state_unavailable']
    stages={row['stage'] for row in audit.result['reporting_errors']}
    assert {'failure state','failure screenshot'}<=stages
    if failed_persistence:assert 'result write' in stages
    else:
        receipt=json.loads((tmp_path/'real-glossary-repair-result.json').read_text('utf8'))
        assert 'original state sampling failure' in receipt['error']
    # Stale timer delivery cannot repeat a failed bootstrap or a data write.
    count=len(audit.result['reporting_errors']);audit.tick()
    assert len(audit.result['reporting_errors'])==count and window.opens==[]
