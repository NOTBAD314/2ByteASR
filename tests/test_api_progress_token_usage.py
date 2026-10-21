"""Live progress and provider-reported token usage of online API steps (2026-10-15).

User report: API recognition steps only showed results once the whole step
finished, and no input/output tokens were recorded anywhere. These tests pin
the usage accounting, the events the steps emit and what the progress page
and the task report show.
"""
from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.providers import api_usage  # noqa: E402

DEEPSEEK_USAGE = {  # tests/fixtures/p14_real_task_report.json, a real DeepSeek answer
    "prompt_tokens": 5953, "completion_tokens": 1024, "total_tokens": 6977,
    "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 1024},
    "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 5953,
}


# ------------------------------------------------------------ accounting

def test_provider_usage_fields_are_normalized_without_guessing():
    assert api_usage.normalize_usage(DEEPSEEK_USAGE) == dict(
        input_tokens=5953, output_tokens=1024, cached_input_tokens=0, uncached_input_tokens=5953, reasoning_tokens=1024, total_tokens=6977)
    # DeepSeek cache hits; OpenAI Chat / Responses cached details.
    assert api_usage.normalize_usage(dict(DEEPSEEK_USAGE, prompt_cache_hit_tokens=5000))["cached_input_tokens"] == 5000
    assert api_usage.normalize_usage({"prompt_tokens": 10, "completion_tokens": 2,
                                      "prompt_tokens_details": {"cached_tokens": 6}})["cached_input_tokens"] == 6
    assert api_usage.normalize_usage({"input_tokens": 10, "output_tokens": 5,
                                      "input_tokens_details": {"cached_tokens": 4},
                                      "output_tokens_details": {"reasoning_tokens": 3}}) == dict(
        input_tokens=10, output_tokens=5, cached_input_tokens=4, reasoning_tokens=3)
    # Anthropic-style usage: cache reads/writes are input too.
    assert api_usage.normalize_usage({"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 100,
                                      "cache_creation_input_tokens": 20})["input_tokens"] == 125
    # Duration-billed speech APIs.
    assert api_usage.normalize_usage({"type": "duration", "seconds": 12.5}) == {"audio_seconds": 12.5}
    assert api_usage.normalize_usage({"duration": 9}) == {"audio_seconds": 9}
    # Nothing usable is "not reported", never zero.
    for value in (None, {}, {"prompt_tokens": None}, {"prompt_tokens": True}, {"prompt_tokens": -1},
                  {"prompt_tokens": float("nan")}, "12", []):
        assert api_usage.normalize_usage(value) is None
    normalized = api_usage.normalize_usage(DEEPSEEK_USAGE)
    assert api_usage.normalize_usage(normalized) == normalized


def test_totals_count_unreported_calls_and_read_in_plain_words():
    totals = api_usage.UsageTotals()
    assert api_usage.usage_text(totals, plain=True) == ""
    totals.add(api_usage.call_payload(stage="polished", usage=None))
    assert api_usage.usage_text(totals, plain=True) == "未返回用量（1 次调用）"
    totals.add(api_usage.call_payload(stage="polished", usage=dict(DEEPSEEK_USAGE, prompt_cache_hit_tokens=953)))
    totals.add(api_usage.call_payload(stage="polished", usage={"prompt_tokens": 47, "completion_tokens": 6}))
    assert totals.to_dict() == dict(calls=3, reported_calls=2, unreported_calls=1, input_tokens=6000,
                                    output_tokens=1030, cached_input_tokens=953, reasoning_tokens=1024,
                                    total_tokens=6977, uncached_input_tokens=5953)
    assert api_usage.usage_text(totals, plain=True) == \
        "输入 6,000（缓存命中 953） · 输出 1,030 tokens · 1 次未返回用量"
    audio = api_usage.UsageTotals().add(api_usage.call_payload(stage="asr", usage={"duration": 3600}))
    assert api_usage.usage_text(audio, plain=True) == "音频 3,600 秒"


def test_summary_groups_by_step_stage_and_model():
    events = [dict(api_usage.call_payload(stage="polished", provider="deepseek", model="deepseek-v4-pro",
                                          usage=DEEPSEEK_USAGE), step_label="云端模型受限校对"),
              dict(api_usage.call_payload(stage="grouped", provider="deepseek", model="deepseek-v4-pro",
                                          usage=None), step_label="云端模型全文智能断句")]
    summary = api_usage.summarize(events)
    assert summary["calls"] == 2 and summary["input_tokens"] == 5953 and summary["unreported_calls"] == 1
    assert set(summary["steps"]) == {"云端模型受限校对", "云端模型全文智能断句"}
    assert summary["api_stages"]["grouped"]["reported_calls"] == 0
    assert summary["models"]["deepseek/deepseek-v4-pro"]["calls"] == 2


# ------------------------------------------------------------ transports

def _sse(*packets):
    return b"".join(("data: " + (packet if isinstance(packet, str) else json.dumps(packet)) + "\n\n").encode()
                    for packet in packets)


class _StreamResponse:
    def __init__(self, status, body, content_type="text/event-stream"):
        self.status_code, self._body = status, body
        self.headers = {"Content-Type": content_type}

    def iter_content(self, chunk_size=1024, **_):
        for start in range(0, len(self._body), 7):
            yield self._body[start:start + 7]

    def close(self):
        pass


def _usage_events(monkeypatch):
    events = []
    import subtitle_core
    monkeypatch.setattr(subtitle_core, "record_run_event",
                        lambda kind, **payload: events.append((kind, payload)), raising=False)
    return events


def test_stream_asks_for_usage_and_records_one_call_with_cached_tokens(monkeypatch):
    from twobyteasr.providers import llm_adapter
    bodies = []
    usage_chunk = {"id": "r1", "choices": [], "usage": {"prompt_tokens": 1200, "completion_tokens": 80,
                                                        "total_tokens": 1280,
                                                        "prompt_tokens_details": {"cached_tokens": 1000}}}
    body = _sse({"id": "r1", "choices": [{"index": 0, "delta": {"content": "{\"ok\":true}"}, "finish_reason": None}]},
                {"id": "r1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                usage_chunk, "[DONE]")

    def post(url, **kwargs):
        bodies.append(kwargs["json"])
        return _StreamResponse(200, body)
    monkeypatch.setattr("requests.post", post)
    events = _usage_events(monkeypatch)
    text = llm_adapter.post_chat_completion_stream(
        [{"role": "user", "content": "x"}], model="m", api_key="k", url="https://example.invalid/v1/chat/completions",
        max_tokens=50, provider="openai", base_url="https://example.invalid/v1", stage="polished")
    assert text == "{\"ok\":true}"
    assert bodies[0]["stream_options"] == {"include_usage": True}
    usage = [payload for kind, payload in events if kind == "api_usage"]
    assert len(usage) == 1 and usage[0]['request_id'] and usage[0]['status'] == 'received'
    assert usage[0]['estimated_cost']['known'] is False
    assert {k:v for k,v in usage[0].items() if k not in {'request_id','status','estimated_cost'}} == dict(stage="polished", provider="openai", model="m", request_mode="chat.completions_stream",
                          reported=True, input_tokens=1200, output_tokens=80, cached_input_tokens=1000,
                          total_tokens=1280)


def test_endpoint_rejecting_stream_options_is_asked_again_without_it(monkeypatch):
    from twobyteasr.providers import llm_adapter
    monkeypatch.setattr(llm_adapter, "_STREAM_USAGE_REJECTED", set())
    bodies = []
    ok = _sse({"id": "r2", "choices": [{"index": 0, "delta": {"content": "done"}, "finish_reason": "stop"}]}, "[DONE]")
    rejected = json.dumps({"error": {"message": "Unrecognized request argument supplied: stream_options",
                                     "type": "invalid_request_error"}}).encode()

    def post(url, **kwargs):
        bodies.append(dict(kwargs["json"]))
        if "stream_options" in kwargs["json"]:
            return _StreamResponse(400, rejected, "application/json")
        return _StreamResponse(200, ok)
    monkeypatch.setattr("requests.post", post)
    events = _usage_events(monkeypatch)
    call = dict(model="m", api_key="k", url="https://local.invalid/v1/chat/completions", max_tokens=20,
                provider="custom", base_url="https://local.invalid/v1", stage="polished")
    assert llm_adapter.post_chat_completion_stream([{"role": "user", "content": "x"}], **call) == "done"
    assert ["stream_options" in body for body in bodies] == [True, False]
    kinds = [kind for kind, _ in events]
    assert "llm_stream_usage_option_rejected" in kinds
    # Every dispatched attempt counts; a rejected request with no usage is unknown.
    usage = [payload for kind, payload in events if kind == "api_usage"]
    assert len(usage) == 2 and all(row['reported'] is False for row in usage)
    assert len({row['request_id'] for row in usage}) == 2
    # The endpoint is remembered: the next request does not send it again.
    llm_adapter.post_chat_completion_stream([{"role": "user", "content": "x"}], **call)
    assert ["stream_options" in body for body in bodies] == [True, False, False]


def test_unrelated_rejection_is_not_retried(monkeypatch):
    from twobyteasr.providers import llm_adapter
    monkeypatch.setattr(llm_adapter, "_STREAM_USAGE_REJECTED", set())
    calls = []
    rejected = json.dumps({"error": {"message": "model not found", "type": "invalid_request_error"}}).encode()
    monkeypatch.setattr("requests.post", lambda url, **kw: calls.append(1) or _StreamResponse(400, rejected,
                                                                                             "application/json"))
    events = _usage_events(monkeypatch)
    with pytest.raises(llm_adapter.LLMRequestError):
        llm_adapter.post_chat_completion_stream([{"role": "user", "content": "x"}], model="m", api_key="k",
            url="https://x.invalid/v1/chat/completions", max_tokens=20, provider="custom", stage="polished")
    assert len(calls) == 1
    usage = [payload for kind,payload in events if kind == 'api_usage']
    assert len(usage) == 1 and usage[0]['reported'] is False


def test_bounded_transport_records_usage_once(monkeypatch):
    from twobyteasr.providers import llm_adapter
    payload = {"choices": [{"message": {"content": "{\"a\":1}"}, "finish_reason": "stop"}], "usage": DEEPSEEK_USAGE}

    class Response(_StreamResponse):
        pass
    monkeypatch.setattr("requests.post", lambda url, **kw: Response(200, json.dumps(payload).encode(),
                                                                      "application/json"))
    events = _usage_events(monkeypatch)
    diagnostics = {}
    llm_adapter.post_chat_completion([{"role": "user", "content": "x"}], model="deepseek-v4-pro", api_key="k",
        url="https://api.deepseek.com/chat/completions", max_tokens=20, provider="deepseek", timeout=(10, 30),
        base_url="https://api.deepseek.com", stage="grouped", request_diagnostics=diagnostics)
    usage = [payload for kind, payload in events if kind == "api_usage"]
    assert len(usage) == 1 and usage[0]["stage"] == "grouped" and usage[0]["input_tokens"] == 5953
    assert diagnostics["usage"]["reasoning_tokens"] == 1024


def test_cloud_worker_forwards_usage_and_retries_under_the_step_it_serves():
    import inspect
    from twobyteasr.providers import cloud_api_worker
    source = inspect.getsource(cloud_api_worker.run)
    for kind in ("api_usage", "asr_request_retry", "asr_retry_sweep"):
        assert f"'{kind}'" in source
    assert "asr_primary" in source and "asr_review" in source


def test_mosi_and_chunk_jobs_publish_each_finished_request(tmp_path):
    import numpy as np
    from twobyteasr.providers import cloud_asr_jobs
    seen, states = [], []
    endpoint = dict(model=cloud_asr_jobs.FLASH, provider="qwen31_flash", url="https://dashscope.aliyuncs.com/x",
                    api_key="k", speaker_source="single")

    def caller(audio, endpoint, check):
        return {"text": "你好", "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}], "words": []}
    rows = cloud_asr_jobs.transcribe_chunks(np.zeros(16000 * 2, dtype="float32"), endpoint, tmp_path,
        caller=caller, progress=lambda *a: states.append(a), on_rows=lambda *a: seen.append(a))
    assert rows and seen and seen[0][0] == 0 and seen[0][2] == rows
    assert states[-1][0] == "completed"


# ------------------------------------------------------------ report

def test_task_report_keeps_usage_per_step_and_in_words(tmp_path, monkeypatch):
    from twobyteasr.recognition import reporting
    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path / "reports")
    media = tmp_path / "录播.mp4"
    media.write_bytes(b"0")
    reporting.begin_media_report(str(media), {"cache_dir": ""}, {"models": {
        "qwen_asr_model": "Qwen3-ASR", "polish_model": "deepseek-v4-pro", "group_model": "deepseek-v4-pro"},
        "switches": {}, "performance": {}})
    # Cloud recognition (step 2) is billed to step 2 although the voice check started after it.
    reporting.record_media_event("stage_started", index=2, label="MOSS 全局说话人与粗时间转写", resource="网络")
    reporting.record_media_event("stage_started", index=3, label="轻量静音与人声区间检测", resource="CPU")
    reporting.record_media_event("api_usage", **api_usage.call_payload(stage="asr_primary", provider="mosi",
                                                                     usage={"duration": 60}))
    reporting.record_media_event("stage_completed", index=3, label="轻量静音与人声区间检测", elapsed_seconds=1.0)
    reporting.record_media_event("stage_completed", index=2, label="MOSS 全局说话人与粗时间转写", elapsed_seconds=9.0)
    reporting.record_media_event("stage_started", index=8, label="云端模型受限校对", resource="网络")
    for usage in (DEEPSEEK_USAGE, None):
        reporting.record_media_event("api_usage", **api_usage.call_payload(
            stage="polished", provider="deepseek", model="deepseek-v4-pro", usage=usage))
    reporting.record_media_event("stage_completed", index=8, label="云端模型受限校对", elapsed_seconds=3.0)
    json_path, text_path = reporting.finish_media_report("success", cue_count=1)
    report = json.loads(open(json_path, encoding="utf-8").read())
    assert report["api_usage"]["calls"] == 3 and report["api_usage"]["input_tokens"] == 5953
    assert report["api_usage"]["steps"]["云端模型受限校对"]["unreported_calls"] == 1
    assert report["api_usage"]["steps"]["MOSS 全局说话人与粗时间转写"]["audio_seconds"] == 60
    text = open(text_path, encoding="utf-8").read()
    assert "API 用量" in text
    assert "- 合计：输入 5,953 · 输出 1,024 tokens · 音频 60 秒 · 1 次未返回用量（3 次调用）" in text


# ------------------------------------------------------------ progress page

def test_cloud_recognition_steps_have_short_record_names():
    from twobyteasr.app import progress_model as model
    label = "在线 ASR API 主力转写（MOSS Pro 云端 · moss-transcribe-diarize-pro）"
    assert model.stage_record_name(label) == "在线识别文字"
    assert model.stage_record_name("在线 ASR API 文字复核（Qwen3-ASR · flash）") == "在线复核文字"
    assert model.stage_action(label) == "在线服务正在识别文字"
    # The service and model move to the line under the title.
    assert model.stage_description(label) == "MOSS Pro 云端 · moss-transcribe-diarize-pro"
    assert model.cloud_job_phase({"state": "PENDING"}) == ("排队中", dict(index=1, done=0, total=1))
    assert model.upload_progress({"state": "uploading", "uploaded_bytes": 1048576,
                                  "upload_bytes_total": 4 * 1048576}) == (
        "{sent} / {size} MB", dict(sent="1.0", size="4.0"))
    assert model.cloud_batch_list({22, 19, 21, 20, 23}) == "19, 20, 21, 22 …"


def _window():
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow([], legacy, object(), None)


def _event(kind, **values):
    from twobyteasr.recognition.service import PipelineEvent
    return PipelineEvent(kind=kind, timestamp="", job_id="", **values)


def _stage(kind, index, label, seconds=0.0):
    return _event(kind, stage_index=index, stage_total=11, media_index=1, media_total=1,
                  label=label, resource="网络", elapsed_seconds=seconds)


def test_proofreading_shows_batches_retries_tokens_and_text_while_running():
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        win._handle_event(_stage("stage_started", 8, "云端模型受限校对"))
        for index in (19, 20, 21):
            win._handle_event(_event("cloud_batch_started", payload=dict(stage="polished", batch_index=index,
                                                                         batch_total=46, cue_count=20)))
        facts = dict(win.stage_metrics.metrics())
        assert facts["正在处理"] == "第 19, 20, 21 批"
        assert win.stage_usage_label.text() == "本步用量：等待服务商返回"
        win._handle_event(_event("llm_request_retry", payload=dict(stage="polished", batch_index=20,
                                                                   batch_total=46, attempt=2)))
        win._handle_event(_event("api_usage", payload=api_usage.call_payload(
            stage="polished", provider="deepseek", model="deepseek-v4-pro",
            usage=dict(DEEPSEEK_USAGE, prompt_cache_hit_tokens=953))))
        win._handle_event(_event("cloud_batch_preview", payload=dict(stage="polished", batch_index=19, batch_total=46,
            rows=[dict(cue_id=1, start=61.0, end=63.5, text="这波打得漂亮", state="polished_changed")])))
        win._handle_event(_event("cloud_batch_completed", elapsed_seconds=4.2, payload=dict(
            stage="polished", batch_index=19, batch_total=46, cue_count=20, success_cues=20, fallback_cues=0)))
        facts = dict(win.stage_metrics.metrics())
        assert facts["已完成批次"] == "1 / 46"
        assert facts["正在处理"] == "第 20, 21 批"
        assert facts["重试"] == "1 次"
        # Usage has its own full-width line: long numbers never squeeze the step title.
        assert "本步用量" not in facts
        assert win.stage_usage_label.text() == "本步用量：输入 5,953（缓存命中 953） · 输出 1,024 tokens"
        win._render_preview()
        assert win.preview_source.text() == "AI 校对结果"
        assert any("这波打得漂亮" in row[1] for row in win.recognition_preview.rows())
        # The finished step keeps its usage in the record; the end shows the task total.
        win._handle_event(_stage("stage_completed", 8, "云端模型受限校对", seconds=30.0))
        rows = [win.event_log.itemWidget(win.event_log.item(i)) for i in range(win.event_log.count())]
        finished = [row.message_label.text() for row in rows if row._badge == "完成"]
        assert finished == ["AI 校对字幕 · 输入 5,953（缓存命中 953） · 输出 1,024 tokens"]
        win._handle_event(_stage("stage_started", 9, "云端模型全文智能断句"))
        win._handle_event(_event("api_usage", payload=api_usage.call_payload(stage="grouped", usage=None)))
        assert win.stage_usage_label.text() == ("本步用量：未返回用量（1 次调用）\n"
                                                "任务累计：输入 5,953（缓存命中 953） · 输出 1,024 tokens · 1 次未返回用量")
        win._recognition_terminal = "success"
        win._finish_progress_presentation()
        win._refresh_progress_cards()
        assert win.stage_usage_label.text().startswith("API 用量：输入 5,953")
    finally:
        win.close()


def test_async_cloud_recognition_names_upload_queue_and_processing():
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        win._handle_event(_stage("stage_started", 2, "MOSS 全局说话人与粗时间转写"))

        def progress(**payload):
            win._handle_event(_event("asr_progress", payload=dict(backend="mosi", model="moss-transcribe-diarize-pro",
                                                                  completed_batches=0, total_batches=1, **payload)))
            return dict(win.stage_metrics.metrics())
        assert progress(state="uploading", uploaded_bytes=50 * 1048576,
                        upload_bytes_total=200 * 1048576)["已上传"] == "50.0 / 200.0 MB"
        facts = progress(state="PENDING")
        assert facts["云端阶段"] == "排队中" and "已返回批次" not in facts and "已上传" not in facts
        assert facts["最近回应"].endswith("秒前")
        assert progress(state="PROCESSING")["云端阶段"] == "云端识别中"
        win._handle_event(_event("api_usage", payload=api_usage.call_payload(
            stage="asr_primary", provider="mosi", model="moss-transcribe-diarize-pro", usage={"duration": 3600})))
        assert win.stage_usage_label.text() == "本步用量：音频 3,600 秒"
    finally:
        win.close()


def test_translation_during_save_counts_translated_lines():
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        win._handle_event(_stage("stage_started", 11, "保存识别结果与工程"))
        win._handle_event(_event("subtitle_translation_progress", payload=dict(target="zh-Hans", done=40, total=120)))
        assert dict(win.stage_metrics.metrics())["已翻译"] == "40 / 120 条"
    finally:
        win.close()
