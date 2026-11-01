import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from twobyteasr.local_mcp.production_text import TextOperations, _cues
from twobyteasr.local_mcp.mcp_bridge import BridgeError
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


class Service(TextOperations):
    def __init__(self):
        self.project = SubtitleProject(media=StudioMedia(path='test.mp4'), cues=[StudioCue(id='a', start_ms=0, end_ms=1000, text='再再强调一遍')])
        self.page = SimpleNamespace(project=self.project)
        self.job_payloads, self.jobs = {}, {}
        self.bridge = SimpleNamespace(_require_glossary=lambda: None, settings={'allow_glossary': True})
        self.revision = 1
    def require_project(self, project_id, revision, permission='allow_edits', idle=True):
        if project_id != self.project.project_id or revision != self.revision:
            raise BridgeError('stale', 'changed')
        return self.page, self.project
    def snapshot(self, page, project):
        return {'project_id': project.project_id, 'revision': self.revision}
    def check_snapshot(self, snapshot):
        return self.require_project(snapshot['project_id'], snapshot['revision'])
    def get_owned_job(self, job_id, kind=None):
        job = self.jobs[job_id]
        if job['kind'] != kind:
            raise BridgeError('bad_params', 'wrong job')
        return job
    def run_job(self, kind, snapshot, work, apply=None, check_before_apply=True, summarize_cancelled=None):
        from twobyteasr.recognition.service import CancellationToken
        job = {'job_id': str(len(self.jobs)), 'kind': kind, 'status': 'running'}
        self.jobs[job['job_id']] = job
        job['result'] = apply(work(CancellationToken(), lambda *_: None), job)
        job['status'] = 'completed'
        return job


def test_unknown_or_duplicate_scope_rejected():
    svc = Service()
    with pytest.raises(BridgeError):
        _cues(svc.project, ['a', 'a'])
    with pytest.raises(BridgeError):
        _cues(svc.project, ['missing'])


def test_stutter_preview_is_local_and_stale_apply_refused():
    svc = Service()
    with patch('twobyteasr.local_mcp.production_text._locked', return_value=False), \
         patch('twobyteasr.local_mcp.production_text._settings', side_effect=AssertionError('AI called')):
        job = svc.op_cleanup_stutter(svc.project.project_id, 1)
        assert job['result']['audio_video_changed'] is False
        assert svc.project.cues[0].text == '再再强调一遍'
        svc.revision = 2
        with pytest.raises(BridgeError) as exc:
            svc.op_cleanup_stutter(svc.project.project_id, 2, action='apply', job_id=job['job_id'])
        assert exc.value.code == 'stale'


def test_apply_never_starts_a_second_ai_request():
    svc = Service()
    with pytest.raises(BridgeError):
        svc.op_start_glossary_proofread(svc.project.project_id, 1, cue_ids=['a'], action='apply', job_id='x')

def test_sentence_preview_then_apply_uses_saved_result_and_undo():
    from PySide6.QtGui import QUndoStack
    from twobyteasr.subtitle_rules.sentence_refine import RefineOutcome, CueRefineAction
    svc = Service()
    svc.page.undo_stack = QUndoStack()
    svc.page._changed = lambda *_: None
    calls = []
    def refine(cues, **kwargs):
        calls.append(1)
        return RefineOutcome(actions=[CueRefineAction(cue_id='a', action='space', space_after_chars=[1])])
    with patch('twobyteasr.local_mcp.production_text._locked', return_value=False), \
         patch('twobyteasr.local_mcp.production_text._settings', return_value={'models': {'x': 1}}), \
         patch('twobyteasr.subtitle_rules.sentence_refine.refine_cues_with_llm', side_effect=refine):
        job = svc.op_start_sentence_refine(svc.project.project_id, 1)
        assert job['result']['api_completed']
        before = svc.project.cues[0].text
        assert svc.op_start_sentence_refine(svc.project.project_id, 1, action='apply', job_id=job['job_id'])['changed_cues'] == 1
        assert svc.project.cues[0].text != before
        svc.page.undo_stack.undo()
        assert svc.project.cues[0].text == before
        with pytest.raises(BridgeError):
            svc.op_start_sentence_refine(svc.project.project_id, 1, action='apply', job_id=job['job_id'])
        assert len(calls) == 1


def test_glossary_preview_works_without_library_and_reports_failure():
    from twobyteasr.glossary.studio_glossary_service import GlossaryReviewPreview
    svc = Service()
    def preview(project, cue_ids, snapshot, settings, **kwargs):
        assert snapshot.libraries == ()
        return GlossaryReviewPreview((), {'successful_cues': 0, 'fallback_cues': 1,
            'request_errors': ['HTTP 429: private details'], 'failed_cues': []})
    with patch('twobyteasr.local_mcp.production_text._locked', return_value=False), \
         patch('twobyteasr.local_mcp.production_text._settings', return_value={}), \
         patch('twobyteasr.glossary.studio_glossary_service.preview_glossary_correction', side_effect=preview), \
         patch('twobyteasr.local_mcp.production_text._glossary_changes', return_value={}):
        job = svc.op_start_glossary_proofread(svc.project.project_id, 1)
        assert job['result']['api_status'] == 'failed'
        assert job['result']['error_categories'] == ['rate_limited']
        assert 'private details' not in repr(job['result'])
        with pytest.raises(BridgeError):
            svc.op_start_glossary_proofread(svc.project.project_id, 1, action='apply', job_id=job['job_id'])

def test_review_reads_native_groups_without_mutating_review_or_switching_page(tmp_path):
    from copy import deepcopy
    svc = Service()
    svc.page.session = SimpleNamespace(project_path=tmp_path / 'a.2byteproj')
    svc.page.undo_stack = SimpleNamespace(isClean=lambda: True)
    rows = [{'cue_id': 'a', 'base': svc.project.cues[0].text, 'origin': svc.project.cues[0].text,
             'issues': [], 'groups': [{'state': 'suggested', 'reviewed': False}]}]
    review = SimpleNamespace(_project_path=svc.page.session.project_path, _rows=rows,
        _snapshot=SimpleNamespace(digest='d'), _selected_ids=lambda: [],
        _live_project=lambda: (svc.project, svc.page), checks_running=lambda: False,
        _groups=lambda row: row['groups'])
    def row_state(row):
        row['review_retained'] = True
        return True, True, False
    review._row_state = row_state
    svc.window = SimpleNamespace(glossary_proofread_page=review)
    original = deepcopy(rows)
    svc.snapshot = lambda *_: {'project_id': svc.project.project_id, 'revision': 1,
                               'project_path': str(svc.page.session.project_path), 'project_fingerprint': 'f'}
    with patch('twobyteasr.local_mcp.production_text._glossary', return_value=SimpleNamespace(digest='d')):
        result = svc.op_get_review_summary(svc.project.project_id, 1)
        assert result['status'] == 'ready'
        assert result['counts']['remaining_proposals'] == 1
        assert result['counts']['pending_captions'] == 1
        assert rows == original
        review.checks_running = lambda: True
        assert svc.op_get_review_summary(svc.project.project_id, 1)['counts'] is None

def test_real_review_page_with_glossary_denied_never_reads_library(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    app = QApplication.instance() or QApplication([])
    svc = Service()
    svc.bridge.settings['allow_glossary'] = False
    path = tmp_path / 'project.2byteproj'
    svc.page.session = SimpleNamespace(project_path=path, project=svc.project)
    svc.page.undo_stack = SimpleNamespace(isClean=lambda: True)
    svc.snapshot = lambda *_: {'project_id': svc.project.project_id, 'revision': 1,
                               'project_path': str(path), 'project_fingerprint': 'fingerprint'}
    review = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    review._project_path = str(path)
    review._rows = [{'cue_id': 'a', 'base': svc.project.cues[0].text, 'origin': svc.project.cues[0].text, 'issues': []}]
    monkeypatch.setattr(review, '_live_project', lambda: (svc.project, svc.page))
    monkeypatch.setattr(review, 'checks_running', lambda: False)
    monkeypatch.setattr(review, '_selected_ids', lambda: pytest.fail('must not read library IDs'))
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._glossary', lambda *_: pytest.fail('must not read glossary'))
    svc.window = SimpleNamespace(glossary_proofread_page=review)
    try:
        result = svc.op_get_review_summary(svc.project.project_id, 1)
        assert result['status'] == 'permission_limited' and result['counts'] is None
        assert 'library_ids' not in result and 'glossary_digest' not in result
    finally:
        review.close(); review.deleteLater(); app.processEvents()


def test_cold_mcp_sentence_refine_sends_only_one_body_request(monkeypatch):
    import json
    from twobyteasr.providers import ai_providers, provider_service
    from twobyteasr.system.resource_governor import ResourceGovernor
    calls = []
    class Adapter:
        provider_id = 'custom'
        model = 'fixture'
        endpoint = {'provider': 'custom', 'model': 'fixture', 'base_url': 'http://127.0.0.1:1/v1', 'api_key': ''}
        def validate(self, **kwargs):
            pytest.fail('unexpected provider_readiness request')
        def complete(self, messages, **kwargs):
            calls.append(kwargs.get('stage'))
            return json.dumps({'results': [{'cue_id': 'a', 'action': 'keep'}]})
    service = provider_service.ProviderService(workers=1, governor=ResourceGovernor())
    adapter = Adapter()
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda *a, **kw: adapter)
    monkeypatch.setattr(ai_providers, 'provider_for_stage',
        lambda settings, stage, sender=None: service.client_for_stage(settings, stage, sender=sender))
    settings = {'models': {'group_provider': 'custom', 'group_model': 'fixture',
        'group_transport': 'openai_compatible', 'group_base_url': 'http://127.0.0.1:1/v1',
        'group_protocol': 'openai_compatible_chat'}, 'switches': {}}
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._settings', lambda stage: settings)
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._locked', lambda *args: False)
    svc = Service()
    result = svc.op_start_sentence_refine(svc.project.project_id, 1)
    assert result['result']['api_completed'] is True
    assert calls == ['sentence_refine']
    assert service.wait_for_idle(timeout=2)

@pytest.mark.parametrize('kind', ['sentence', 'glossary'])
def test_cancelled_ai_preview_can_summarize_native_result_without_applying(monkeypatch, kind):
    from twobyteasr.glossary.studio_glossary_service import GlossaryReviewPreview
    from twobyteasr.subtitle_rules.sentence_refine import RefineOutcome, CueRefineAction
    svc = Service()
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._locked', lambda *args: False)
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._settings', lambda stage: {'models': {'fixture': True}})
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._glossary_changes', lambda *args: {})
    summaries = []
    def cancelled_job(job_kind, snapshot, work, apply=None, check_before_apply=True, summarize_cancelled=None):
        assert summarize_cancelled is apply
        result = (RefineOutcome(actions=[CueRefineAction(cue_id='a', action='keep')]) if kind == 'sentence'
                  else GlossaryReviewPreview((), {'successful_cues': 1, 'fallback_cues': 0,
                                                   'request_errors': [], 'failed_cues': []}))
        summary = summarize_cancelled(result, {'job_id': 'cancelled-job'})
        summaries.append(summary)
        return {'job_id': 'cancelled-job', 'status': 'cancelled', 'result': summary}
    monkeypatch.setattr(svc, 'run_job', cancelled_job)
    original = svc.project.cues[0].text
    result = (svc.op_start_sentence_refine(svc.project.project_id, 1) if kind == 'sentence'
              else svc.op_start_glossary_proofread(svc.project.project_id, 1))
    assert result['status'] == 'cancelled' and summaries[0]['api_completed'] is True
    assert svc.project.cues[0].text == original
    assert svc.job_payloads['cancelled-job']['applied'] is False

def test_cancelled_sentence_reports_unknown_request_count_when_native_result_is_cancelled(monkeypatch):
    from twobyteasr.subtitle_rules.sentence_refine import RefineOutcome
    svc = Service()
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._locked', lambda *args: False)
    monkeypatch.setattr('twobyteasr.local_mcp.production_text._settings', lambda stage: {'models': {'fixture': True}})
    def cancelled_job(job_kind, snapshot, work, apply=None, check_before_apply=True, summarize_cancelled=None):
        return summarize_cancelled(RefineOutcome(llm_status='cancelled'), {'job_id': 'cancelled'})
    monkeypatch.setattr(svc, 'run_job', cancelled_job)
    result = svc.op_start_sentence_refine(svc.project.project_id, 1)
    assert result['request_count'] is None
    assert result['recorded_request_count'] == 0
    assert result['api_completed'] is False
