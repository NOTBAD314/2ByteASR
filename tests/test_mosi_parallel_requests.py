"""MOSS Pro cloud: long audio as requests of about 20 minutes, several with MOSI at once (2026-10-23).

User report: a 96-minute task went to MOSI as 56 + 40 minutes; the 40-minute
request took MOSI 864 s every time (and once failed after 24 minutes), while
the same audio as two halves took 98 s and 168 s. Requests are now cut at
quiet points into parts of at most 22.5 minutes, uploaded in order and waited
for in parallel; a task planned before keeps what MOSI already has.
"""
import json
import threading
import time

import numpy as np
import pytest

from tests.test_no_cuda_cloud_asr import Response, mosi_endpoint, mosi_form
from twobyteasr.providers.qwen31_asr import ASRProtocolError

SEGMENTS = [{'speaker': 'S01', 'text': '你好。', 'start': 0.2, 'end': 0.8}]


class ScriptedMosi:
    """Thread-safe fake MOSI: one task id per upload, scripted polls per task
    (1-based upload order), and how many tasks it had at once."""

    def __init__(self, script=None, hold_until_posts=0, limit=None):
        self.lock = threading.Lock()
        self.script, self.hold, self.limit = dict(script or {}), hold_until_posts, limit
        self.posts, self.polls, self.open, self.most_open, self.refused, self.finished = [], {}, set(), 0, 0, []

    def post(self, url, **kw):
        samples = (len(mosi_form(kw['data'].read())['file'][2]) - 44) // 2
        with self.lock:
            if self.limit is not None and len(self.open) >= self.limit:
                self.refused += 1
                return Response({'error': {'code': 'concurrency_limit_exceeded'}}, 429)
            task = f'task-{len(self.posts) + 1}'
            self.posts.append((task, samples))
            self.open.add(task)
            self.most_open = max(self.most_open, len(self.open))
        return Response({'id': task, 'task_id': task, 'status': 'PENDING', 'retry_after': 2})

    def get(self, url, **kw):
        task = url.rsplit('/', 1)[-1]
        with self.lock:
            count = self.polls[task] = self.polls.get(task, 0) + 1
            steps = self.script.get(int(task.split('-')[1]), ['PROCESSING'])
            status = steps[count - 1] if count <= len(steps) else 'SUCCESS'
            if status == 'SUCCESS' and len(self.posts) < self.hold:
                status = 'PROCESSING'   # hold until enough uploads arrived (proves parallel waiting)
            if status in ('SUCCESS', 'FAILED'):
                self.open.discard(task)
                self.finished.append(task)
        body = {'id': task, 'status': status}
        if status == 'SUCCESS':
            body.update(text='你好。', segments=SEGMENTS)
        if status == 'FAILED':
            body['error'] = {'code': 'processing_timeout', 'message': 'took too long'}
        return Response(body)


def small_requests(monkeypatch):
    """Scale the plan down: one request up to 1 s, parts of at most 1.3 s."""
    from twobyteasr.providers import mosi_asr
    monkeypatch.setattr(mosi_asr, 'SINGLE_REQUEST_SECONDS', 1)
    monkeypatch.setattr(mosi_asr, 'REQUEST_MAX_SECONDS', 1.3)
    monkeypatch.setattr(mosi_asr, 'RATE_LIMIT_RETRY_SECONDS', 0.01)
    return mosi_asr


def tiny_sleep(_):
    time.sleep(0.001)


@pytest.mark.parametrize('minutes, count', [(10, 1), (25, 1), (25.5, 2), (40, 2), (61.5, 3), (96, 5), (120, 6)])
def test_requests_are_about_twenty_minutes(minutes, count):
    from twobyteasr.providers import mosi_asr
    samples = int(minutes * 60 * 16000)
    audio = np.broadcast_to(np.float32(0), (samples,))          # length only; no memory
    ranges = mosi_asr.plan_ranges(audio)
    assert len(ranges) == count and ranges[0][0] == 0 and ranges[-1][1] == samples
    assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
    assert all(end - start <= 25 * 60 * 16000 for start, end in ranges)   # one request up to 25 min, parts at most 22.5 + 2


def test_each_cut_moves_to_the_quietest_second_nearby():
    from twobyteasr.providers import mosi_asr
    rate = 16000
    audio = np.random.default_rng(3).standard_normal(40 * 60 * rate).astype(np.float32) * 0.2
    quiet = 21 * 60                                   # within two minutes of the 20-minute target
    audio[quiet * rate:(quiet + 1) * rate] *= 0.05
    (_, cut), _second = mosi_asr.plan_ranges(audio)
    assert quiet <= cut / rate <= quiet + 1


def test_requests_upload_in_order_and_wait_in_parallel(tmp_path, monkeypatch):
    mosi_asr = small_requests(monkeypatch)
    audio = np.random.default_rng(1).standard_normal(16000 * 6).astype(np.float32) * 0.1
    client = ScriptedMosi(hold_until_posts=3)
    events, seen = [], []
    rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep, parallel=3,
                               progress=lambda *a: events.append(a), on_rows=lambda i, n, r: seen.append(i))
    ranges = json.loads(next(tmp_path.rglob('plan.json')).read_text('utf8'))['requests']
    assert len(ranges) == 5
    assert [samples for _task, samples in client.posts] == [r['end'] - r['start'] for r in ranges]   # in order
    assert client.most_open == 3                       # three with MOSI at once, never more
    assert sorted(seen) == [0, 1, 2, 3, 4]
    assert [row['speaker'] for row in rows] == [f'R00{i}_S01' for i in range(1, 6)]
    assert [row['start'] for row in rows] == sorted(row['start'] for row in rows)
    waiting = [a for a in events if a[0] in ('PENDING', 'PROCESSING')]
    assert max(len(a[3]['active_requests']) for a in waiting) == 3
    assert all(a[2] == 5 for a in events if a[0] != 'upload_bytes')
    assert events[-1][:3] == ('completed', 5, 5)


def test_one_failed_request_keeps_the_others_and_resubmits_only_itself(tmp_path, monkeypatch):
    mosi_asr = small_requests(monkeypatch)
    audio = np.random.default_rng(2).standard_normal(int(16000 * 3.5)).astype(np.float32) * 0.1
    client = ScriptedMosi(script={2: ['PROCESSING', 'FAILED']})
    with pytest.raises(ASRProtocolError) as failure:
        mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep)
    assert failure.value.category == 'remote_terminal'
    assert failure.value.remote_detail.startswith('第 2 / 3 段') and '任务编号 task-2' in failure.value.remote_detail
    results = sorted(p.parent.name.split('-')[1] for p in tmp_path.rglob('request-*/result.json'))
    assert results == ['000', '002'] and len(client.posts) == 3          # the others finished and were kept
    with pytest.raises(ASRProtocolError):                                # no confirmation: nothing new is sent
        mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep)
    assert len(client.posts) == 3
    rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep,
                               restart_terminal=True)
    assert len(client.posts) == 4 and len(rows) == 3                    # only the failed request again


@pytest.mark.parametrize('second', ['failed', 'in_flight', 'not_sent'])
def test_a_task_planned_before_keeps_what_mosi_already_has(tmp_path, monkeypatch, second):
    """Tasks planned with the earlier 55-minute requests: a finished request
    is reused, one MOSI still has is waited for, a failed one is only cut
    shorter after the user confirms resubmitting, an unsent one is cut now."""
    mosi_asr = small_requests(monkeypatch)
    from twobyteasr.providers.cloud_asr_jobs import job_root
    audio = np.random.default_rng(4).standard_normal(16000 * 5).astype(np.float32) * 0.1
    endpoint = dict(mosi_endpoint(), url=mosi_asr.normalize_api_base(mosi_endpoint()['url']))
    root = job_root(audio, endpoint, tmp_path)
    cut = 16000 * 2
    (root / 'plan.json').write_text(json.dumps({'requests': [{'start': 0, 'end': cut},
                                                              {'start': cut, 'end': len(audio)}]}), 'utf8')
    first = root / f'request-000-0-{cut}'
    first.mkdir()
    (first / 'result.json').write_text(json.dumps({'status': 'SUCCESS', 'segments': SEGMENTS}), 'utf8')
    second_dir = root / f'request-001-{cut}-{len(audio)}'
    second_dir.mkdir()
    states = {'failed': {'status': 'FAILED', 'task_id': 'old-2', 'submitted_at': time.time()},
              'in_flight': {'status': 'PROCESSING', 'task_id': 'task-9', 'submitted_at': time.time()},
              'not_sent': {'status': 'REJECTED', 'category': 'rate_limited'}}
    (second_dir / 'task.json').write_text(json.dumps(states[second]), 'utf8')
    client = ScriptedMosi()
    if second == 'failed':
        with pytest.raises(ASRProtocolError):
            mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep)
        assert client.posts == []
        rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep,
                                   restart_terminal=True)
    else:
        rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep)
    plan = [(r['start'], r['end']) for r in json.loads((root / 'plan.json').read_text('utf8'))['requests']]
    assert plan[0] == (0, cut)                                          # the finished request is kept
    if second == 'in_flight':
        assert client.posts == [] and plan[1:] == [(cut, len(audio))]   # still with MOSI: waited for, not resent
    else:
        assert len(plan) == 4 and len(client.posts) == 3                # the rest cut into the shorter requests
    assert rows[0]['speaker'] == 'R001_S01' and len(rows) == len(plan)


def test_mosi_concurrency_limit_waits_instead_of_failing(tmp_path, monkeypatch):
    mosi_asr = small_requests(monkeypatch)
    audio = np.random.default_rng(5).standard_normal(int(16000 * 3.5)).astype(np.float32) * 0.1
    client = ScriptedMosi(script={n: ['PROCESSING'] * 5 for n in (1, 2, 3)}, limit=2)
    states = []
    rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=tiny_sleep, parallel=3,
                               progress=lambda *a: states.append(a[0]))
    assert len(rows) == 3 and len(client.posts) == 3 and client.refused >= 1 and client.most_open == 2
    assert 'waiting_for_slot' in states
