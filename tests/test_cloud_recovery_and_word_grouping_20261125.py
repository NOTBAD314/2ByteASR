"""2026-11-25 recovery fixes found with the three Japanese reports.

真拳伝説 03: a TLS failure while polling an accepted MOSS task ended the task and
was reported as a broken model runtime. Ninja Spy: DeepSeek 429 "concurrency
limit of 14" while 16 requests were allowed. English/Korean: one failed AI
request left every long utterance as an over-long line.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
import requests

import subtitle_core as core


# --- TLS -----------------------------------------------------------------------------------

def test_certifi_failure_retries_once_with_the_system_trust_bundle(monkeypatch, tmp_path):
    from twobyteasr.providers import network_policy
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["verify"])
        if len(calls) == 1:
            raise requests.exceptions.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        return NS(status_code=200)
    bundle = tmp_path / "merged.pem"
    bundle.write_text("x", encoding="ascii")
    monkeypatch.setattr(network_policy.requests, "get", fake_get)
    monkeypatch.setattr(network_policy, "system_trust_bundle", lambda: str(bundle))
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert network_policy.get("https://api.mosi.cn/v1/audio/tasks/x").status_code == 200
    assert calls[1] == str(bundle) and calls[0] != calls[1]     # verification stays on
    with pytest.raises(network_policy.NetworkTrustError):
        network_policy.get("https://api.mosi.cn", verify=False)


def test_worker_tls_failure_is_a_network_problem_not_a_broken_runtime():
    from twobyteasr.recognition.asr import network_certificate_problem
    stderr = "HTTPS 证书校验失败；模型列表与生成均可能受影响。请查看网络诊断后重试。（诊断 f5915892692f45e3a4a017ad531399c6）"
    problem = network_certificate_problem(stderr)
    assert problem["category"] == "tls_certificate" and problem["remote_task_kept"]
    assert "不是本机模型损坏" in problem["message"] and "f5915892692f45e3a4a017ad531399c6" in problem["action"]
    assert network_certificate_problem("CUDA out of memory") is None


def test_poll_survives_a_tls_drop_without_submitting_again(tmp_path):
    from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
    from twobyteasr.providers import mosi_asr
    client = MosiClient(statuses=("PROCESSING", "SUCCESS"))
    real_get = client.get
    drops = {"left": 2}

    def flaky_get(url, **kw):
        if drops["left"]:
            drops["left"] -= 1
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
        return real_get(url, **kw)
    client.get = flaky_get
    state_path = tmp_path / "task.json"
    state = dict(task_id="task-1", status="PENDING", submitted_at=0)
    states = []
    body = mosi_asr.poll(mosi_endpoint(), client=client, state_path=state_path, state=state, duration=10.0,
                         sleep=lambda _s: None, progress=lambda *a: states.append(a[0]))
    assert body["status"] == "SUCCESS" and client.posts == []
    assert states.count("network_retry") == 2
    assert json.loads(state_path.read_text("utf8"))["task_id"] == "task-1"


def test_poll_gives_up_with_the_task_kept_after_bounded_retries(tmp_path, monkeypatch):
    from tests.test_no_cuda_cloud_asr import mosi_endpoint
    from twobyteasr.providers import mosi_asr
    monkeypatch.setattr(mosi_asr, "POLL_NETWORK_RETRIES", 2)

    class Down:
        posts = []

        def get(self, url, **kw):
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
    with pytest.raises(mosi_asr.ASRProtocolError) as caught:
        mosi_asr.poll(mosi_endpoint(), client=Down(), state_path=tmp_path / "task.json",
                      state=dict(task_id="task-1", status="RUNNING"), duration=5.0, sleep=lambda _s: None)
    assert caught.value.category == "tls_certificate" and "不会重新上传" in str(caught.value)


# --- 429 -----------------------------------------------------------------------------------

def test_reported_concurrency_limit_caps_the_shared_account():
    from twobyteasr.providers.fair_request_queue import FairRequestQueue, reported_concurrency_limit
    message = ("Provider HTTP 429: Too many requests. Your current concurrency is 14, which exceeds your "
               "concurrency limit of 14 based on your remaining balance.")
    assert reported_concurrency_limit(message) == 14
    assert reported_concurrency_limit("HTTP 500") is None
    queue = FairRequestQueue(16)
    queue.accounts["k"] = dict(active=3, limit=16, ceiling=16, cooldown=0., successes=0, timeouts=0)
    queue.local.account = "k"
    from twobyteasr.providers.ai_providers import AIProviderError
    queue.task_done(error=AIProviderError(message, category="rate_limited"))
    state = queue.accounts["k"]
    assert state["server_limit"] == 12 and state["limit"] <= 12
    assert queue.snapshot()["local_limits"][0]["server_limit"] == 12


def test_rate_limit_backoff_is_longer_than_a_second():
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.providers.provider_input_budget import retry_delay
    error = AIProviderError("Provider HTTP 429", category="rate_limited")
    assert 4.0 <= retry_delay(error, 1) <= 5.6
    assert retry_delay(error, 3) >= 16.0


# --- English / Korean ------------------------------------------------------------------------

def long_english(i):
    text = ("so what we are going to do now is open the colour page and then we change the timeline "
            "colour space before we export anything at all")
    return core.SpeechSegment(i, i * 10.0, i * 10.0 + 8.0, text, .9, [], speaker="S01")


def test_english_failed_request_is_retried_and_missing_utterances_asked_again(monkeypatch):
    from twobyteasr.subtitle_rules import english_segmentation as en
    monkeypatch.setattr(en.time, "sleep", lambda _s: None)
    segments = [long_english(1), long_english(2)]
    sent = []

    def complete(messages):
        body = json.loads(messages[1]["content"])
        ids = [row["id"] for row in body["utterances"]]
        sent.append(ids)
        if len(sent) == 1:
            raise RuntimeError("HTTP 429")
        if len(sent) == 2:
            return json.dumps({"breaks": {"1": [9, 16, 20]}})   # utterance 2 missing
        return json.dumps({"breaks": {key: [9, 16, 20] for key in ids}})
    answers = en.ai_breaks(segments, None, complete=complete)
    assert sent == [["1", "2"], ["1", "2"], ["2"]]
    assert set(answers) == {"1", "2"}


def test_unanswered_long_english_line_is_split_locally_and_labelled(monkeypatch):
    from twobyteasr.subtitle_rules import english_segmentation as en
    from twobyteasr.subtitle_rules.language_rules import language_scope
    monkeypatch.setattr(en.time, "sleep", lambda _s: None)
    with language_scope("en"):
        segment = long_english(1)
        evidence = [
            {"text": word, "start": segment.start + i * .30, "end": segment.start + i * .30 + .25}
            for i, word in enumerate(segment.text.split())
        ]
        cues = en.group_english_with_ai([segment], evidence, complete=lambda messages: "not json")
    assert len(cues) >= 2 and {c.grouping_origin for c in cues} == {"local_fallback_split"}
    assert " ".join(c.text for c in cues).split() == long_english(1).text.split()
    assert all(len(c.text) <= en.RULES.cue_max_chars for c in cues)


def test_origin_summary_reports_ai_and_local_separately():
    from twobyteasr.subtitle_rules.grouping import grouping_origin_summary
    cues = [NS(grouping_origin=o) for o in ("ai_accepted", "ai_accepted", "ai_targeted_correction",
                                             "local_fallback_split", "source_retained_after_local_rejection")]
    summary = grouping_origin_summary(cues)
    assert (summary["ai_first_pass"], summary["ai_retry"], summary["local_fallback"], summary["pending"]) == (2, 1, 1, 1)
    assert summary["ai_adoption_rate"] == 0.6 and summary["local_fallback_rate"] == 0.2


# --- live DeepSeek runs of 11 spaced languages + Korean (2026-11-25) ---------------------------

def test_closing_break_after_the_last_word_is_ignored():
    from twobyteasr.subtitle_rules import english_segmentation as en
    tokens = "one two three four five six".split()
    assert en.drop_closing_break(tokens, [2, 5]) == [2]
    assert en.pieces_from_breaks(tokens, [2, 5], strict=True) == [(0, 3), (3, 6)]


def test_break_problem_names_long_lines_lone_words_and_short_runs():
    from twobyteasr.subtitle_rules import english_segmentation as en
    length_of = lambda text: len(text)
    tokens = "so let us go back to the checkpoint and do it again slowly".split()
    scores = [0.0] * len(tokens)
    assert "line 1 has" in en.break_problem(tokens, [], length_of=length_of, max_chars=40, scores=scores)
    assert "single word 'slowly'" in en.break_problem(tokens, [7, 11], length_of=length_of, max_chars=40, scores=scores)
    assert "very short" in en.break_problem(tokens, [1, 3, 7], length_of=length_of, max_chars=40, scores=scores,
                                             preferred=40)
    assert en.break_problem(tokens, [7], length_of=length_of, max_chars=40, scores=scores, preferred=40) == ""


def test_long_lines_are_asked_again_alone_and_merged():
    from twobyteasr.subtitle_rules import english_segmentation as en
    tokens = "so what we are going to do now is open the colour page and then we change the timeline".split()
    found = {"1": [9]}       # line 2 is still 47 characters
    asked = []

    def ask(work, problems):
        asked.append((work, problems))
        sub, words = work[0]
        return {sub: [2]}    # the colour page | and then we change the timeline
    fixed = en.refine_long_lines(found, {"1": tokens}, length_of=len, max_chars=40,
                                 scorer=lambda t: [0.0] * len(t), ask=ask)
    assert fixed == 1 and found["1"] == [9, 12]
    assert asked[0][0][0][0] == "1~2" and "split it into 2 lines" in asked[0][1]["1~2"][1]


def test_lone_word_is_joined_and_kept_cuts_survive_local_repair():
    from twobyteasr.subtitle_rules import english_segmentation as en
    tokens = "and do it again slowly".split()
    pieces, changed = en.join_orphan_words([(0, 4), (4, 5)], tokens, length_of=len, max_chars=40)
    assert pieces == [(0, 5)] and changed == {5}
    tokens = ("okay so before we start the boss fight I want to show you how the parry window actually works").split()
    pieces, origins = en.ai_pieces_with_local_repair(
        tokens, [7, len(tokens) - 1], scores=[0.0] * len(tokens), forced=set(), length_of=len, max_chars=40,
        local_split=lambda a, b: [(0, 5), (5, b - a)])
    assert pieces[0] == (0, 8) and origins[0] == "ai_accepted"
    assert set(origins[1:]) == {"local_fallback_split"}


def test_word_requests_carry_line_lengths_and_the_previous_problem():
    from twobyteasr.subtitle_rules import english_segmentation as en
    messages = en.build_ai_messages([("7", ["hello", "big", "world"])], None, {"7": ([0], "line 1 has 50 characters")})
    row = json.loads(messages[1]["content"])["utterances"][0]
    assert row["characters_through_word"] == [5, 9, 15]
    assert row["previous_breaks"] == [0] and "50 characters" in row["problem"]
    assert "characters_through_word" in messages[0]["content"]
