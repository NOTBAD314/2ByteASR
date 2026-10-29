"""Explicit frozen/source acceptance for grouping; no network or user data."""
from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace


@contextmanager
def _attributes(module, **values):
    previous = {key: getattr(module, key) for key in values}
    try:
        for key, value in values.items():
            setattr(module, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(module, key, value)


def run_offline():
    """Return checks plus a safe candidate for the normal Studio audit to edit.

    This is a synthetic replay, not evidence of a user's specific cloud reply.
    Call only inside an isolated acceptance process with no recognition job.
    """
    if not os.environ.get("TWOBYTEASR_ACCEPTANCE_DIR"):
        raise RuntimeError("Grouping replay requires explicit acceptance mode.")
    import subtitle_core as core
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.providers.asr_provider_snapshot import ProviderSnapshot
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_contract import (
        parse_grouping_response, validate_grouping_result, GroupingContractError,
    )

    checks = []
    source = "先看左边，再看右边"
    rows = [core.SpeechSegment(1, 0, 2, source, .9, [
        core.WordUnit(index * .2, (index + 1) * .2, char, .9)
        for index, char in enumerate("先看左边再看右边")], speaker="S01")]
    invalid = {
        "malformed": '{"boundaries":[4,8]',
        "contradictory": '{"boundaries":[8],"segmented_text":"先看左边，|再看右边"}',
        "trailing": '{"boundaries":[8]}{"error":"unfinished"}',
        "duplicate": '{"boundaries":[4,4,8]}',
        "range": '{"boundaries":[4,99]}',
        "mutation": '{"segmented_text":"先看右边，|再看左边"}',
    }
    for name, body in invalid.items():
        rejected = False
        try:
            parse_grouping_response(body, source)
        except GroupingContractError:
            rejected = True
        checks.append({"name": "grouping_reject_" + name, "passed": rejected})

    snapshot = ProviderSnapshot(
        provider="custom", profile_id="offline-grouping-audit", profile_revision="1",
        model="offline-fixture", kind="http", transport="openai_compatible",
        endpoint_identity="http://127.0.0.1:1/v1", protocol="openai_compatible_chat",
        capabilities=("text", "structured_output"),
        _endpoint=(("provider", "custom"), ("model", "offline-fixture"),
                   ("base_url", "http://127.0.0.1:1/v1"),
                   ("url", "http://127.0.0.1:1/v1/chat/completions"), ("api_key", "")))
    requests = []
    def complete(_messages, **kwargs):
        requests.append(kwargs.get("stage"))
        return invalid["contradictory"]
    with activate_runtime_context(RuntimeContext(), legacy=core):
        with _attributes(grouping, provider_for_stage=lambda *a, **k: SimpleNamespace(complete=complete),
                         GROUPING_API_RETRIES=1, SECOND_PASS_GROUP_VALIDATION=False):
            result = grouping.call_grouping_api(rows, provider_snapshot=snapshot, _packed=True)
    checks.append({"name": "grouping_safe_local_fallback",
                   "passed": result.origin == "fallback" and result.data_validated and not result.validated
                   and "".join(cue.text for cue in result) == source and len(requests) == 1})
    checks.append({"name": "grouping_fallback_source_contract",
                   "passed": validate_grouping_result(rows, result)})
    for name, cue in (
            ("unknown_speaker", core.SubtitleCue(1,0,2,source,speaker="S99")),
            ("invalid_time", core.SubtitleCue(1,float("nan"),2,source,speaker="S01")),
            ("wrong_time_domain", core.SubtitleCue(1,1000,1002,source,speaker="S01"))):
        rejected = False
        try:
            validate_grouping_result(rows, [cue])
        except GroupingContractError:
            rejected = True
        checks.append({"name": "grouping_reject_" + name, "passed": rejected})
    return {"passed": all(check["passed"] for check in checks), "checks": checks,
            "provenance": "synthetic offline grouping response; no provider request",
            "runtime_cues": core.serialize_cues(result), "source_segments": core.serialize_segments(rows)}

