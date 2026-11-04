import copy

import pytest

from twobyteasr.acceptance.first_deployment_contract import verify_home_evidence


def successful_evidence():
    models = {name: dict(selected=True, completed=True, failed=False,
                         skipped=False, segment_count=1, failure_reason="")
              for name in ("moss", "qwen3-asr", "qwen_aligner")}
    report = dict(job_id="current", status="degraded_success",
                  review_items=[dict(severity="review", category="说话人需要确认")],
                  events=[
                      dict(event="model_summary", models=models),
                      dict(event="forced_alignment", stage="final_cues", attached=3,
                           statuses=dict(aligned=1), stats=dict(words=3)),
                  ])
    words = [dict(model="qwen3_forced_aligner", start_basis="model", end_basis="model",
                  start_ms=i * 100, end_ms=(i + 1) * 100, text=text)
             for i, text in enumerate(("Hello", "local", "speech"))]
    project = {"cue-align:1": {"caption_arbitration": {"acoustic_words": words}}}
    return report, project


def test_review_notice_does_not_masquerade_as_model_failure():
    report, project = successful_evidence()
    proof = verify_home_evidence(report, project, job_id="current")
    assert proof["qwen_model_word_count"] == 3
    assert proof["review_items"][0]["severity"] == "review"


@pytest.mark.parametrize("name", ("moss", "qwen3-asr", "qwen_aligner"))
def test_later_alignment_cannot_hide_a_failed_selected_stage(name):
    report, project = successful_evidence()
    report["events"][0]["models"][name].update(failed=True, failure_reason="environment_missing")
    with pytest.raises(AssertionError, match=name):
        verify_home_evidence(report, project, job_id="current")


@pytest.mark.parametrize("change", (dict(skipped=True), dict(completed=False),
                                     dict(segment_count=0), dict(selected=False)))
def test_required_stage_must_really_produce_results(change):
    report, project = successful_evidence()
    report["events"][0]["models"]["qwen3-asr"].update(change)
    with pytest.raises(AssertionError, match="qwen3-asr"):
        verify_home_evidence(report, project, job_id="current")


def test_generic_word_counts_cannot_replace_model_timing():
    report, _ = successful_evidence()
    with pytest.raises(AssertionError, match="model-derived"):
        verify_home_evidence(report, {"moss": {"words": [{}] * 72}}, job_id="current")


def test_duplicate_or_estimated_word_timings_cannot_satisfy_contract():
    report, project = successful_evidence()
    words = project["cue-align:1"]["caption_arbitration"]["acoustic_words"]
    words[:] = [copy.deepcopy(words[0])] * 10
    with pytest.raises(AssertionError, match="model-derived"):
        verify_home_evidence(report, project, job_id="current")
    words[0]["start_basis"] = "estimated"
    with pytest.raises(AssertionError, match="model-derived"):
        verify_home_evidence(report, project, job_id="current")


def test_stale_report_and_missing_final_alignment_are_rejected():
    report, project = successful_evidence()
    with pytest.raises(AssertionError, match="completed task"):
        verify_home_evidence(report, project, job_id="another-task")
    report["events"].pop()
    with pytest.raises(AssertionError, match="final-cue"):
        verify_home_evidence(report, project, job_id="current")
