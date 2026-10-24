"""The captured 38e22e1 response must fail safely and use bounded model repair."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.providers.structured_output import response_object, StructuredResponseError
from twobyteasr.caption_design.authored_generation import generate_staged
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger

FIXTURES = Path(__file__).parent / 'fixtures'
RAW = (FIXTURES / 'studio-design-38e22e1/provider-original.txt').read_text('utf8')


def test_captured_provider_response_is_invalid_without_local_rewriting():
    assert len(RAW) == 1420
    with pytest.raises(StructuredResponseError) as failure:
        response_object(RAW)
    assert failure.value.category == 'structured_output_invalid_json'
    assert failure.value.diagnostics['column'] == 490
    assert failure.value.diagnostics['stage'] == 'json_syntax'


@pytest.mark.parametrize('raw,category', [
    ('{"candidates":[', 'structured_output_truncated'),
    ('{"duration":NaN}', 'structured_output_schema'),
    ('{"duration":Infinity}', 'structured_output_schema'),
    ('{"duration":1e400}', 'structured_output_schema'),
    ('```json\n{"name":"ok"}', 'structured_output_truncated'),
])
def test_incomplete_and_nonfinite_responses_are_rejected(raw, category):
    with pytest.raises(StructuredResponseError) as failure:
        response_object(raw)
    assert failure.value.category == category


def test_only_complete_unambiguous_json_fence_is_unwrapped():
    assert response_object('```json\n{"name":"ok"}\n```') == {'name': 'ok'}
    with pytest.raises(ValueError):
        response_object('Explanation\n{"name":"ok"}')
    with pytest.raises(ValueError):
        response_object(json.dumps('{"name":"ok"}'))


class DesignClient:
    def __init__(self, first, repaired):
        self.values = [first, repaired]
        self.calls = []
        self.source = json.loads((FIXTURES / 'balatro-deepseek-4f5564.json').read_text('utf8'))['candidates'][0]['generated_source']

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if kwargs.get('response_kind') == 'source_artifact':
            from twobyteasr.caption_design.source_artifact import from_theme, token
            marker = re.findall(r'2BYTE-ARTWORK/1 ([a-f0-9]{24})', messages[0]['content'])[-1]
            raw = from_theme(self.source, 'fixture').replace(token('fixture'), marker)
        else:
            raw = self.values.pop(0)
        kwargs['on_stream_event']('delta', raw)
        kwargs['on_stream_event']('final', raw)
        return raw

    def invocation_trace(self):
        return {'provider_id': 'deepseek', 'model': 'deepseek-flash', 'dispatched': True}


VALID = json.dumps({'candidates': [
    {'name': '晨窗微光', 'design': '米白纸面与晨窗斜光，文字从下方轻微进入并完整退场。'},
    {'name': '手帐便签', 'design': '两片胶带与方格纸承托文字，整张便签从上方进入。'},
    {'name': '分镜两格', 'design': '共用中缝的两个分镜，左右依次展开并向中心收回。'},
]}, ensure_ascii=False)


@pytest.mark.parametrize('first,stage', [(RAW, 'json_syntax'), ('{"candidates":[{"name":3}]}', 'schema')])
def test_direction_failure_has_one_model_repair_and_preserves_original(tmp_path, first, stage):
    client = DesignClient(first, VALID)
    ledger = ThemeLedger(tmp_path, '日常动漫风格')
    generate_staged(ledger, client, SimpleNamespace(provider='deepseek', model='deepseek-flash'), '',
        {'models': {'ai_design_candidate_count': 3, 'ai_design_concurrency': 1, 'ai_design_max_repair_calls': 2}},
        request_id='captured-replay')
    assert (tmp_path/'directions/provider-original.txt').read_text('utf8') == first
    failure = json.loads((tmp_path/'directions/failure.json').read_text('utf8'))
    assert failure['stage'] == stage and failure['response_complete'] is True
    assert failure['request_id'] == 'captured-replay/directions'
    assert ledger.value['automatic_direction_completion']['attempt'] == 1
    assert len(ledger.value['directions']['candidates']) == 3
    assert first in client.calls[1][0][0]['content'] or json.dumps(first, ensure_ascii=False)[1:-1] in client.calls[1][0][0]['content']


def test_failed_repair_stops_and_publishes_no_partial_directions(tmp_path):
    client = DesignClient(RAW, RAW)
    ledger = ThemeLedger(tmp_path, '日常动漫风格')
    with pytest.raises(StructuredResponseError):
        generate_staged(ledger, client, SimpleNamespace(provider='deepseek', model='deepseek-flash'), '',
            {'models': {'ai_design_candidate_count': 3, 'ai_design_max_repair_calls': 2}}, request_id='bounded')
    assert len(client.calls) == 2
    assert not ledger.value.get('directions')


def test_terminal_ui_clears_generating_and_keeps_project(tmp_path):
    from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QPlainTextEdit
    from twobyteasr.caption_design.studio_theme_draft import StudioThemeDraftController
    from twobyteasr.caption_design.theme_draft import ThemeDraft
    app = QApplication.instance() or QApplication([])
    page = QWidget()
    page.project = object()
    page._ai_request_generation = 1
    page._ai_request_active = True
    for key in ('ai_generate',):
        setattr(page, key, QPushButton(page))
    for key in ('ai_suggestion_title', 'ai_confidence', 'ai_quality_details'):
        setattr(page, key, QLabel('正在生成视觉方案', page))
    page.ai_preview = QPlainTextEdit(page)
    page._stop_storyboard_animation = lambda: None
    page._set_ai_input_sections_visible = lambda value: None
    page._show_ai_progress_bar = lambda value: None
    controller = StudioThemeDraftController(page)
    controller.project = page.project
    controller.root = tmp_path
    controller.current = ThemeDraft('test', 1, 'cue-315', '字幕', '', 'subtitle', 'deepseek', 'deepseek-flash')
    controller.phase = 'PROVIDER'
    controller.operation = controller.provider_operation = 'test/provider'
    controller.generation_running = True
    controller._failed(controller.operation, '$: invalid JSON; chars=1420, line=1, column=490', 'structured_output_invalid_json')
    assert controller.phase == 'FAILED' and not controller.timer.isActive()
    assert not controller.generation_running and not page._ai_request_active
    assert page.ai_suggestion_title.text() == '设计未完成'
    assert '已应用' not in page.ai_confidence.text()
    assert controller.project is page.project
    page.close()
