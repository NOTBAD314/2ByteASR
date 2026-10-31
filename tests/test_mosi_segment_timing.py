"""MOSS Pro cloud: a few sentences timed outside the request's audio (2026-10-25).

User report (0.8.4, an English singing stream): ``MOSS Pro 句段时间越出提交的音频``,
"it keeps failing". One sentence timed past the audio failed the whole task,
and as the result was not kept, every new start read the same finished task
and failed again. Now an end past the audio is clipped, a sentence outside it
(or reversed, or without a time) is left out, MOSI's own result is kept, and
the report says what was changed.
"""
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pytest

from tests.test_mosi_parallel_requests import small_requests, tiny_sleep
from tests.test_no_cuda_cloud_asr import Response, _FakeMosi, mosi_endpoint, mosi_form
from twobyteasr.providers.qwen31_asr import ASRProtocolError

# A 2-second request: one good sentence, one ending 2.5 s past the audio, one
# after it, one reversed, one without a time.
SEGMENTS = [
    {'speaker': 'S01', 'text': 'one', 'start': 0.1, 'end': 0.9},
    {'speaker': 'S01', 'text': 'two', 'start': 1.2, 'end': 4.5},
    {'speaker': 'S01', 'text': 'three', 'start': 3.0, 'end': 3.5},
    {'speaker': 'S02', 'text': 'four', 'start': 1.6, 'end': 1.1},
    {'speaker': 'S02', 'text': 'five', 'start': None, 'end': 1.9},
    {'speaker': 'S02', 'text': '', 'start': 9.0, 'end': 9.5},       # no text: not counted
]


class Mosi:
    """Fake MOSI: every upload is one task; each poll answers SUCCESS with
    ``segments(request_seconds)``."""

    def __init__(self, segments, uploads=True):
        self.segments, self.uploads, self.lock = segments, uploads, threading.Lock()
        self.posts, self.polls, self.seconds = [], [], {}

    def post(self, url, **kw):
        assert self.uploads, 'must not upload again'
        samples = (len(mosi_form(kw['data'].read())['file'][2]) - 44) // 2
        with self.lock:
            task = f'task-{len(self.posts) + 1}'
            self.posts.append(task)
            self.seconds[task] = samples / 16000
        return Response({'id': task, 'task_id': task, 'status': 'PENDING', 'retry_after': 2})

    def get(self, url, **kw):
        task = url.rsplit('/', 1)[-1]
        with self.lock:
            self.polls.append(task)
        segments = self.segments(self.seconds.get(task, 2.0)) if callable(self.segments) else self.segments
        return Response({'id': task, 'status': 'SUCCESS', 'text': 'x', 'segments': segments})


def run(tmp_path, client, audio=None, monkeypatch=None):
    from twobyteasr.providers import mosi_asr
    events = []
    if monkeypatch is not None:
        # This fixture asserts timing repair events; language provenance is
        # independently checked in test_asr_language_provenance.
        def capture_timing(kind, **kw):
            if kind == 'cloud_asr_timing_repaired':
                events.append((kind, kw))
        monkeypatch.setattr(mosi_asr, '_record_event', capture_timing)
    audio = np.zeros(32000, np.float32) if audio is None else audio
    rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep)
    return rows, events


def test_sentences_outside_the_audio_are_clipped_or_left_out(tmp_path, monkeypatch):
    rows, events = run(tmp_path, Mosi(SEGMENTS), monkeypatch=monkeypatch)
    assert [row['text'] for row in rows] == ['one', 'two']
    assert rows[1]['start'] == pytest.approx(1.2) and rows[1]['end'] == pytest.approx(2.0)   # clipped to the audio
    folder = next(tmp_path.rglob('request-000-0-32000'))
    assert json.loads((folder / 'result.json').read_text('utf8'))['segments'] == SEGMENTS    # MOSI's own result kept
    repair = json.loads((folder / 'timing-repair.json').read_text('utf8'))
    assert {key: repair[key] for key in ('segments', 'clipped', 'outside', 'reversed', 'invalid')} == dict(
        segments=5, clipped=1, outside=1, reversed=1, invalid=1)
    assert repair['audio_seconds'] == 2.0 and repair['latest_end'] == 4.5
    assert [row['text'] for row in repair['examples']] == ['two', 'three', 'four', 'five']
    (kind, event), = events
    assert kind == 'cloud_asr_timing_repaired' and event['segment'] == [1, 1]
    assert (event['start'], event['end'], event['clipped'], event['outside']) == (0.0, 2.0, 1, 1)
    assert 'examples' not in event                       # no subtitle text in the run report


def test_ends_rounded_just_past_the_audio_are_no_change(tmp_path, monkeypatch):
    segments = [{'speaker': 'S01', 'text': 'one', 'start': 0.1, 'end': 2.6}]   # within 1 s, as before
    rows, events = run(tmp_path, Mosi(segments), monkeypatch=monkeypatch)
    assert [row['end'] for row in rows] == [pytest.approx(2.0)]
    assert events == [] and not list(tmp_path.rglob('timing-repair.json'))


def test_each_request_is_clipped_to_its_own_audio(tmp_path, monkeypatch):
    small_requests(monkeypatch)
    audio = np.random.default_rng(5).standard_normal(int(16000 * 2.4)).astype(np.float32) * 0.1
    client = Mosi(lambda seconds: [{'speaker': 'S01', 'text': 'run on', 'start': 0.1, 'end': seconds + 5}])
    rows, events = run(tmp_path, client, audio, monkeypatch)
    ranges = json.loads(next(tmp_path.rglob('plan.json')).read_text('utf8'))['requests']
    assert len(ranges) == 2 and len(client.posts) == 2
    assert [row['end'] for row in rows] == [pytest.approx(r['end'] / 16000) for r in ranges]
    assert sorted(event['segment'] for _kind, event in events) == [[1, 2], [2, 2]]


def test_a_finished_task_saved_by_084_is_fetched_again_not_uploaded(tmp_path, monkeypatch):
    """0.8.4 saved the task id and SUCCESS, then failed before keeping the result."""
    from twobyteasr.providers import mosi_asr
    from twobyteasr.providers.cloud_asr_jobs import job_root
    audio = np.zeros(32000, np.float32)
    folder = job_root(audio, mosi_endpoint(), tmp_path) / 'request-000-0-32000'
    folder.mkdir()
    (folder / 'task.json').write_text(json.dumps(dict(task_id='old-1', status='SUCCESS', bytes=64044,
                                                      submitted_at=1.0)), 'utf8')
    client = Mosi(SEGMENTS, uploads=False)
    rows, _events = run(tmp_path, client, audio, monkeypatch)
    assert client.polls == ['old-1'] and client.posts == []
    assert [row['text'] for row in rows] == ['one', 'two']
    assert (folder / 'result.json').is_file()
    rows_again, _ = run(tmp_path, client, audio, monkeypatch)      # next start: the kept result, no poll
    assert client.polls == ['old-1'] and [row['text'] for row in rows_again] == ['one', 'two']
    assert mosi_asr.validate_result({'segments': SEGMENTS}) is None


def test_no_sentence_inside_the_audio_still_fails_and_says_what_came_back(tmp_path, monkeypatch):
    """Every time outside the audio (say milliseconds): not a silent empty result."""
    segments = [{'speaker': 'S01', 'text': 'one', 'start': 1200, 'end': 1800},
                {'speaker': 'S01', 'text': 'two', 'start': 1900, 'end': 2000}]
    with pytest.raises(ASRProtocolError) as failure:
        run(tmp_path, Mosi(segments), monkeypatch=monkeypatch)
    assert failure.value.category == 'invalid_timing'
    message = str(failure.value)
    assert '2 句' in message and '1200' in message and '2.0 秒' in message and '请回报问题' in message
    assert next(tmp_path.rglob('result.json'))      # MOSI's result kept for the report


def test_a_broken_result_shape_is_still_an_error():
    from twobyteasr.providers import mosi_asr
    with pytest.raises(ASRProtocolError):
        mosi_asr.validate_result({'segments': 'none'})
    with pytest.raises(ASRProtocolError):
        mosi_asr.validate_result(['not', 'an', 'object'])


class _RunOnMosi(_FakeMosi):
    def do_GET(self):
        assert self.path == '/v1/audio/tasks/loop-1'
        self._send(200, {'id': 'loop-1', 'status': 'SUCCESS', 'text': 'la la. la.', 'segments': [
            {'speaker': 'S01', 'text': 'la la.', 'start': 0.1, 'end': 0.9},
            {'speaker': 'S01', 'text': 'la.', 'start': 1.0, 'end': 7.5},
            {'speaker': 'S01', 'text': 'la la la.', 'start': 8.0, 'end': 9.0}]})


def test_real_worker_process_reports_the_change_to_the_app(monkeypatch, tmp_path):
    """The worker process forwards the event; the app records it for 排查原因."""
    from twobyteasr.recognition import asr
    from twobyteasr.providers import asr_api_process
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    events = []
    monkeypatch.setattr('twobyteasr.recognition.cache.record_run_event', lambda kind, **kw: events.append((kind, kw)))
    server = ThreadingHTTPServer(('127.0.0.1', 0), _RunOnMosi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        endpoint = mosi_endpoint(url=f'http://127.0.0.1:{server.server_port}/v1', api_key='sk-loopback')
        context = RuntimeContext(job_id='job-loop', asr_endpoint_snapshot=endpoint,
                                 asr_settings_snapshot={'models': {}}, speaker_source='native')
        monkeypatch.setattr(asr, 'build_qwen_asr_context', lambda *a: '')
        monkeypatch.setattr('twobyteasr.glossary.terminology.runtime_snapshot', lambda: SimpleNamespace(canonical_terms=[]))
        chunks = [dict(start=0, end=2, audio=(np.zeros(32000, np.float32), 16000))]
        with activate_runtime_context(context):
            rows = asr_api_process.transcribe('fixture.wav', chunks, publish_primary=True, cache_root=tmp_path / 'jobs')
    finally:
        server.shutdown()
    assert [row['text'].rstrip('.') for row in rows] == ['la la', 'la'] and rows[1]['end'] == pytest.approx(2.0)
    repaired = [kw for kind, kw in events if kind == 'cloud_asr_timing_repaired']
    assert len(repaired) == 1
    assert (repaired[0]['segments'], repaired[0]['clipped'], repaired[0]['outside']) == (3, 1, 1)


# ---- 排查原因 ---------------------------------------------------------------

def _diagnosis(data):
    from twobyteasr.recognition.run_diagnosis import DiagnosisInput, diagnose_run
    return diagnose_run(DiagnosisInput(report=data, ai_ready=True))


def test_the_084_failure_is_recognized_and_points_to_the_update():
    from tests.test_run_diagnosis import failed, with_settings
    error = 'PRIMARY_API worker failed (exit 1):\nstdout:\n\nstderr:\nMOSS Pro 句段时间越出提交的音频'
    data = with_settings(failed(error, stage='在线 ASR API 主力转写（MOSS Pro 云端）'),
                         models={'primary_asr_backend': 'api'})
    diagnosis = _diagnosis(data)
    found = diagnosis.rule_ids
    assert found[0] == 'cloud_asr_timing_rejected' and 'cloud_asr_failed' not in found
    issue = diagnosis.findings[0].issue
    assert issue.fixed and 'update' in issue.actions and 'retry' not in issue.actions


def _repair_event(**overrides):
    row = {'event': 'cloud_asr_timing_repaired', 'provider': 'mosi_moss_pro', 'segment': [3, 5],
           'start': 2652.0, 'end': 3990.0, 'segments': 212, 'audio_seconds': 1338.0, 'latest_end': 1395.2,
           'clipped': 1, 'outside': 4, 'reversed': 0, 'invalid': 0}
    row.update(overrides)
    return row


def test_a_finished_task_with_changed_sentences_says_where_and_how_many():
    from tests.test_run_diagnosis import report, with_settings
    from twobyteasr.recognition.run_diagnosis import specific_text
    events = report()['events'] + [_repair_event(), _repair_event(segment=[5, 5], start=5320.0, end=6650.0,
                                                                  segments=180, clipped=2, outside=0)]
    diagnosis = _diagnosis(with_settings(report(events=events), models={'primary_asr_backend': 'api'}))
    finding = next(row for row in diagnosis.findings if row.rule_id == 'cloud_asr_timing_repaired')
    assert finding.severity == 'quality'                 # sentences were left out
    assert specific_text(finding, 'zh') == ('所在的段：44:12–1:06:30、1:28:40–1:50:50。MOSS Pro 返回的 392 句里，'
                                            '3 句结尾超出上传的音频、已截到音频结尾，4 句的时间不在这段音频里或起止颠倒、没有放进字幕。')
    english = specific_text(finding, 'en')
    assert '44:12–1:06:30' in english and '392' in english and english != specific_text(finding, 'zh')
    clipped_only = _diagnosis(with_settings(report(events=report()['events'] + [_repair_event(outside=0)]),
                                            models={'primary_asr_backend': 'api'}))
    note = next(row for row in clipped_only.findings if row.rule_id == 'cloud_asr_timing_repaired')
    assert note.severity == 'tip'
