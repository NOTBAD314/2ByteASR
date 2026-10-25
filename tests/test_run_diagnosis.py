"""排查原因: the local checks, the AI digest and the catalog (2026-10-23)."""
from __future__ import annotations

import copy
import json

import pytest

from twobyteasr.recognition import diagnosis_checks
from twobyteasr.recognition.diagnosis_catalog import ACTION_LABELS, ISSUES, STAGES
from twobyteasr.recognition.diagnosis_prompt import (DIGEST_LIMIT, digest_text, knowledge_text, plain_report,
                                                     strip_folders, system_prompt, user_prompt)
from twobyteasr.recognition.run_diagnosis import (CONFIDENCES, SEVERITIES, DiagnosisInput, diagnose_run,
                                                  registered_issue_ids, specific_text)


def report(**overrides):
    """A finished, healthy MOSS + FireRed + AI task (nothing to report)."""
    base = {
        "schema_version": 1, "status": "success", "started_at": "2026-10-23T10:00:00+0800",
        "media": {"name": "录播.mp4", "path": r"C:\Users\someone\Videos\录播.mp4", "audio_seconds": 600.0},
        "settings": {
            "config_warnings": [],
            "models": {"primary_asr_backend": "moss", "firered_asr_backend": "local", "qwen_asr_backend": "local",
                       "polish_provider": "deepseek", "polish_model": "deepseek-chat",
                       "group_provider": "deepseek", "group_model": "deepseek-chat"},
            "switches": {"enable_ai_polish": True, "use_ai_grouping": True},
        },
        "stages": [{"index": 1, "label": "统一 16k 音频采样时钟", "status": "completed", "elapsed_seconds": 1.0}],
        "events": [{"event": "TASK_LANGUAGE", "language": "zh", "requested": "zh", "decided_by": "manual",
                    "kana": 0, "han": 900}],
        "review_items": [],
        "polishing_summary": {"success_batches": 3, "success_cues": 120, "fallback_cues": 0},
        "result": {"cue_count": 180, "segment_count": 120, "audio_seconds": 600.0, "elapsed_seconds": 300.0,
                   "outputs": {"project": "p.2byteproj"}},
    }
    for key, value in overrides.items():
        base[key] = value
    return base


def failed(error, *, stage="锁定最终字幕时间轴", events=(), **overrides):
    data = report(**overrides)
    data["status"] = "failed"
    data["result"] = {"elapsed_seconds": 20.0, "error": error}
    data["stages"] = data["stages"] + [{"index": 9, "label": stage, "status": "failed", "error": error}]
    data["events"] = data["events"] + list(events)
    return data


def ids(data, **kwargs):
    return diagnose_run(DiagnosisInput(report=data, **kwargs)).rule_ids


def with_settings(data, *, models=None, switches=None):
    data = copy.deepcopy(data)
    data["settings"]["models"].update(models or {})
    data["settings"]["switches"].update(switches or {})
    return data


# ---- catalog --------------------------------------------------------------------

def test_catalog_entries_are_complete_and_reference_known_actions():
    for issue in ISSUES.values():
        assert issue.stage in STAGES
        assert issue.severity in SEVERITIES
        assert issue.title and issue.symptom and issue.cause and issue.advice
        assert set(issue.actions) <= set(ACTION_LABELS), issue.id
        assert set(issue.supersedes) <= set(ISSUES), issue.id


def test_every_entry_has_a_local_check_unless_it_is_knowledge_for_the_ai():
    checked = set(registered_issue_ids())
    assert checked <= set(ISSUES)
    knowledge_only = {issue.id for issue in ISSUES.values() if issue.ai_only}
    assert set(ISSUES) - checked == knowledge_only | {"unknown_failure"}
    assert not checked & knowledge_only


def test_healthy_task_has_no_findings():
    assert ids(report(), ai_ready=True) == ()


# ---- the user's report of 2026-10-23 (SenseVoice, no timeline, Japanese chosen for Chinese audio) --

def user_report():
    data = failed("字幕保真检查未通过：S00 1167.880s；原文和阶段记录已保留", events=[
        {"event": "MODEL_SKIPPED", "model_id": "firered", "role": "timeline_alignment", "backend": "off",
         "failure_reason": "timeline_backend_off"},
        {"event": "japanese_morphology_unavailable", "error": "日语分词失败（exit 1）："},
        {"event": "final_content_conservation_recovery", "speaker": "S00", "start": 73.12, "end": 120.4,
         "expected_numbers": [], "actual_numbers": []},
        {"event": "final_content_conservation_recovery", "speaker": "S00", "start": 1167.88, "end": 1191.56,
         "expected_numbers": [], "actual_numbers": ["2"]},
    ] + [{"event": "local_hard_split_recovery", "cue_count": 6}] * 55)
    data["events"][0] = {"event": "TASK_LANGUAGE", "language": "ja", "requested": "ja", "decided_by": "manual",
                         "disagrees_with_transcript": "zh", "kana": 0, "han": 971}
    return with_settings(data, models={"primary_asr_backend": "sensevoice", "firered_asr_backend": "off",
                                       "qwen_asr_backend": "off", "polish_provider": "disabled",
                                       "group_provider": "disabled"},
                         switches={"enable_ai_polish": False, "use_ai_grouping": False})


def test_user_report_names_the_number_cut_language_and_missing_word_timing():
    diagnosis = diagnose_run(DiagnosisInput(report=user_report(), ai_ready=False))
    assert diagnosis.rule_ids == ("fidelity_numbers", "language_mismatch", "no_word_timing", "ai_key_missing",
                                  "grouping_local_fallback")
    top = diagnosis.headline()
    assert top.rule_id == "fidelity_numbers" and top.confidence == "certain"
    text = specific_text(top, "zh")
    assert "19:27" in text and "没有字级时间轴" in text
    assert specific_text(diagnosis.findings[1], "zh") == "这次的字幕语言是「日语」，但识别出的文字看起来是中文。"
    assert specific_text(diagnosis.findings[2], "zh") == "这次的主力转写是 SenseVoice，字幕时间轴：已关闭。"
    # The generic fidelity entry is hidden by the specific one; Japanese
    # morphology failing is explained by the wrong language.
    assert "fidelity_failed" not in diagnosis.rule_ids and "japanese_morphology_failed" not in diagnosis.rule_ids


def test_user_report_with_a_key_now_suggests_turning_ai_on():
    diagnosis = diagnose_run(DiagnosisInput(report=user_report(), ai_ready=True))
    assert "ai_key_missing" not in diagnosis.rule_ids
    assert diagnosis.findings[-1].rule_id == "ai_steps_off" and diagnosis.findings[-1].severity == "tip"


def test_fidelity_failure_without_number_change_stays_generic():
    data = failed("字幕保真检查未通过：S01 61.500s；原文和阶段记录已保留", events=[
        {"event": "final_content_conservation_recovery", "speaker": "S01", "start": 61.5, "end": 70.0,
         "expected_numbers": ["20"], "actual_numbers": ["20"]}])
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    assert diagnosis.rule_ids == ("fidelity_failed",)
    assert specific_text(diagnosis.top, "zh") == "出错的位置：说话人 S01，视频的 1:01。"


# ---- one check each -----------------------------------------------------------------

@pytest.mark.parametrize("error, issue", [
    ("Qwen3-ForcedAligner 0.6B 未安装，请先在模型工坊下载。", "model_missing"),
    ("SENSEVOICE worker failed (exit 1):\nstderr:\nModuleNotFoundError: No module named 'funasr'", "runtime_broken"),
    ("RuntimeError: CUDA is not available on this machine", "no_cuda"),
    ("MOSS 整段worker失败（退出码 1）：torch.OutOfMemoryError: CUDA out of memory。本次显存分配失败。", "gpu_out_of_memory"),
    ("OSError: [WinError 1455] 页面文件太小，无法完成操作。", "pagefile_too_small"),
    ("ValueError: prompt/audio sequence exceeds max_length 131072", "moss_too_long"),
    ("QWEN3 worker timeout", "worker_timeout"),
    ("MOSS 整段worker失败（退出码 3221225477）：子进程未返回具体异常。", "worker_crashed"),
    ("[Errno 28] No space left on device", "disk_full"),
    ("moov atom not found", "media_unreadable"),
    ("Stage 9后处理违反原文逐字符守恒；停止返回错误字幕。", "stage9_conservation"),
    ("识别结果工程保存失败：识别输出路径已被其它任务占用", "project_save_failed"),
    ("sensevoice 没有生成有效文字。", "empty_result"),
])
def test_failure_text_maps_to_its_issue(error, issue):
    found = ids(failed(error, stage="SenseVoice 主力转写"), ai_ready=True)
    assert found[0] == issue
    assert "unknown_failure" not in found


def test_specific_environment_causes_hide_the_generic_crash():
    found = ids(failed("MOSS 整段worker失败（退出码 1）：CUDA out of memory"), ai_ready=True)
    assert "gpu_out_of_memory" in found and "worker_crashed" not in found


def test_unexplained_failure_gets_the_generic_entry():
    assert ids(failed("Something nobody has seen before"), ai_ready=True) == ("unknown_failure",)


def test_incremental_no_text_fallback_alone_is_not_an_empty_result():
    data = report(events=report()["events"] + [{"event": "incremental_asr_fallback", "backend": "sensevoice",
                                                  "error": "sensevoice worker returned no parsed text"}])
    assert "empty_result" not in ids(data, ai_ready=True)


def test_zero_cues_is_an_empty_result():
    data = report()
    data["result"]["cue_count"] = 0
    assert ids(data, ai_ready=True)[0] == "empty_result"


def test_sparse_result_needs_long_audio():
    data = report()
    data["result"]["cue_count"] = 10
    assert ids(data, ai_ready=True) == ("sparse_result",)
    data["media"]["audio_seconds"] = data["result"]["audio_seconds"] = 120
    assert ids(data, ai_ready=True) == ()


@pytest.mark.parametrize("category, issue", [
    ("auth_error", "ai_auth_failed"), ("quota_exhausted", "ai_quota"), ("rate_limited", "ai_rate_limited"),
    ("total_timeout", "ai_timeout"), ("read_idle_timeout", "ai_timeout"), ("tls_error", "ai_connection"),
    ("connection_error", "ai_connection"), ("parse_failure", "ai_bad_output"),
    ("format_mismatch", "ai_bad_output"), ("request_too_large", "ai_request_too_large"),
])
def test_ai_fallback_category_names_the_cause(category, issue):
    data = report(events=report()["events"] + [
        {"event": "grouping_api_fallback", "batch_index": 2, "category": category, "error": "x"}])
    found = ids(data, ai_ready=True)
    assert found[0] == issue
    # The "retry what failed" entry follows as a tip when the cause is known.
    partial = diagnose_run(DiagnosisInput(report=data, ai_ready=True)).findings[-1]
    assert partial.rule_id == "ai_partial_fallback" and partial.severity == "tip"


def test_partial_polish_without_a_category_is_a_partial_fallback_problem():
    data = report(polishing_summary={"success_cues": 100, "fallback_cues": 6, "fallback_batches": 1})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    assert diagnosis.rule_ids == ("ai_partial_fallback",)
    assert diagnosis.top.severity == "problem"


def test_ai_steps_off_without_key_is_a_quality_finding():
    data = with_settings(report(), switches={"use_ai_grouping": False, "enable_ai_polish": False})
    assert ids(data, ai_ready=False) == ("ai_key_missing",)
    assert ids(data, ai_ready=None) == ("ai_steps_off",)


def test_word_timing_off_is_named_with_the_engine():
    data = with_settings(report(), models={"primary_asr_backend": "api", "firered_asr_backend": "off"})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    assert diagnosis.rule_ids == ("no_word_timing",)
    assert specific_text(diagnosis.top, "zh") == "这次的主力转写是 在线 API，字幕时间轴：已关闭。"
    english = specific_text(diagnosis.top, "en")  # the engine and "off" follow the language too
    assert "Online API" in english and "Off" in english and "在线" not in english


def test_alignment_and_review_degradation():
    data = report(events=report()["events"] + [
        {"event": "model_degraded", "model_id": "firered", "reason": "no_firered_timeline_output"},
        {"event": "model_degraded", "model_id": "qwen3-asr", "reason": "no_qwen_text_output"}])
    assert ids(data, ai_ready=True) == ("alignment_degraded", "review_model_failed")


def test_cloud_recognition_failures():
    auth = failed("[2BYTEASR_API_ERROR] 401 InvalidApiKey", stage="在线 ASR API 主力转写（MOSS Pro）")
    auth = with_settings(auth, models={"primary_asr_backend": "api"})
    assert ids(auth, ai_ready=True)[0] == "cloud_asr_auth"
    quota = failed("[2BYTEASR_API_ERROR] Arrearage: 账户欠费", stage="在线 ASR API 主力转写（MOSS Pro）")
    assert ids(with_settings(quota, models={"primary_asr_backend": "api"}), ai_ready=True)[0] == "cloud_asr_quota"
    other = failed("[2BYTEASR_API_ERROR] upload failed", stage="在线 ASR API 主力转写（MOSS Pro）")
    assert ids(with_settings(other, models={"primary_asr_backend": "api"}), ai_ready=True)[0] == "cloud_asr_failed"


def test_cloud_marker_quoting_the_provider_reason_is_read_whole():
    """2026-10-23: the worker's line can quote MOSI's own error, braces
    included; the old pattern stopped at the first "} " and lost the category."""
    marker = "[2BYTEASR_API_ERROR] " + json.dumps(
        {"category": "key", "message": 'MOSI 返回 {"code": 7} 后拒绝', "action": "", "link": "", "code": "auth_failed"},
        ensure_ascii=False)
    assert ids({"status": "failed", "result": {"error": marker}}, ai_ready=True)[0] == "cloud_asr_auth"


def test_resubmit_evidence_names_the_segment_and_mosi_reason():
    from twobyteasr.providers.cloud_api_worker import ERROR_MARKER, RESUBMIT_CATEGORIES
    message = (RESUBMIT_CATEGORIES["remote_terminal"] + " 第 2 / 2 段（55:59–1:36:04）的 MOSI 任务（任务编号 t-9）"
               "执行失败，MOSI 没有说明原因。")
    marker = ERROR_MARKER + json.dumps({"category": "resubmit_needed", "message": message, "action": "确认后重新提交。",
                                        "link": None, "code": "remote_terminal", "resubmit": True}, ensure_ascii=False)
    error = f"{message} 确认后重新提交。 PRIMARY_API worker failed (exit 1): stdout: stderr: {marker} 已保存远端终态 FAILED"
    data = with_settings(failed(error, stage="在线 ASR API 主力转写（MOSS Pro 云端 · moss-transcribe-diarize-pro）"),
                         models={"primary_asr_backend": "api"})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    finding = next(f for f in diagnosis.findings if f.rule_id == "cloud_asr_resubmit")
    assert "第 2 / 2 段（55:59–1:36:04）的 MOSI 任务（任务编号 t-9）执行失败，MOSI 没有说明原因" in finding.evidence[0]


def test_content_review_block_is_its_own_cause_not_a_resubmit():
    """2026-10-24 user report: MOSI's safety review stopped segment 2 of 5; the
    report called it 「需要你确认后重新提交」 and advised 重试失败项."""
    from twobyteasr.providers.cloud_api_worker import CONTENT_BLOCKED_ACTION, ERROR_MARKER, RESUBMIT_CATEGORIES
    message = (RESUBMIT_CATEGORIES["content_blocked"] + " 第 2 / 5 段（21:16–41:46）的 MOSI 任务（任务编号 t-9）"
               "被 MOSI 的内容安全审查拦下，没有返回这一段的字幕（MOSI 返回的原因：safety policy error；"
               "safety guardrail blocked（17001，111111004））。")
    marker = ERROR_MARKER + json.dumps({"category": "resubmit_needed", "message": message, "action": CONTENT_BLOCKED_ACTION,
                                        "link": "", "code": "content_blocked", "resubmit": True}, ensure_ascii=False)
    error = f"{message} {CONTENT_BLOCKED_ACTION} PRIMARY_API worker failed (exit 1): stdout: stderr: {marker} 已保存远端终态 FAILED"
    data = with_settings(failed(error, stage="在线 ASR API 主力转写（MOSS Pro 云端 · moss-transcribe-diarize-pro）"),
                         models={"primary_asr_backend": "api"})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    found = [f.rule_id for f in diagnosis.findings]
    assert found[0] == "cloud_asr_content_blocked" and "cloud_asr_resubmit" not in found
    assert "第 2 / 5 段（21:16–41:46）" in diagnosis.findings[0].evidence[0]
    assert "pick_primary" in diagnosis.findings[0].issue.actions and "retry" not in diagnosis.findings[0].issue.actions


def test_content_review_block_in_a_084_report_is_recognized():
    """The error text of the user's 0.8.4 report (raw MOSI JSON, remote_terminal)."""
    error = ('上次提交的云端识别任务已结束但没有成功（失败或已取消）。 第 2 / 5 段（21:16–41:46）的 MOSI 任务'
             '（任务编号 bdcd3aa0-2ebf-468d-9fc6-b8243315ed48）执行失败，MOSI 返回的原因：{"error_code": 17001, '
             '"error_msg": "safety policy error", "internal_error_code": 111111004, "internal_error_msg": '
             '"safety guardrail blocked"}。 要再试，可在完成页按“重试失败项”并确认重新提交；重新提交会再次上传并可能再次计费。')
    found = ids(with_settings(failed(error, stage="在线 ASR API 主力转写（MOSS Pro 云端）"),
                              models={"primary_asr_backend": "api"}), ai_ready=True)
    assert found[0] == "cloud_asr_content_blocked" and "cloud_asr_resubmit" not in found


def _gap_event(**overrides):
    row = {"event": "cloud_asr_gap_fill", "ranges": [[1276.0, 2506.0]], "language": "en", "filled": True, "rows": 212,
           "backend": "qwen_local", "model": "Qwen3-ASR 1.7B", "resplittable": True,
           "gaps": [{"start": 1276.0, "end": 2506.0, "segment": [2, 5], "task_id": "t-2", "resplittable": True}]}
    row.update(overrides)
    return row


def test_a_filled_content_review_gap_is_a_finished_task_with_a_note():
    """2026-10-24: a blocked range no longer fails the task; it is filled locally."""
    data = with_settings(report(events=report()["events"] + [_gap_event()]), models={"primary_asr_backend": "api"})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    finding = diagnosis.findings[0]
    assert finding.rule_id == "cloud_asr_gap_filled" and finding.issue.severity == "problem"
    assert specific_text(finding, "zh") == "被拦下的时间：21:16–41:46；补识别用的是本地 Qwen3-ASR 1.7B。"
    assert finding.issue.actions == ("studio", "mosi_resplit")


@pytest.mark.parametrize("reason, why", [("no_local_model", "这台电脑上没有能补这段语言的本地主力模型。"),
                                         ("fill_failed", "本地模型补识别失败。")])
def test_an_unfilled_content_review_gap_names_the_range_and_why(reason, why):
    event = _gap_event(filled=False, rows=0, backend="", model="", reason=reason)
    data = with_settings(report(events=report()["events"] + [event]), models={"primary_asr_backend": "api"})
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    finding = diagnosis.findings[0]
    assert finding.rule_id == "cloud_asr_gap_unfilled"
    assert specific_text(finding, "zh") == "被拦下的时间：21:16–41:46。" + why
    assert finding.issue.actions == ("model_workshop", "mosi_resplit")
    assert specific_text(finding, "en").endswith(".") and "21:16–41:46" in specific_text(finding, "en")


@pytest.mark.parametrize("filled, expected", [(False, False), (True, True)])
def test_a_transcript_stopping_at_an_unfilled_gap_is_the_gap_not_a_cut_off(filled, expected):
    early = {"timestamp": 1275.4, "category": "主力转写提前结束", "detail": "api 到 1275.40s，FireRedVAD 人声到 3600.00s",
             "priority": 3}
    event = _gap_event(filled=filled, reason="" if filled else "no_local_model")
    data = with_settings(report(events=report()["events"] + [event], review_items=[early]),
                         models={"primary_asr_backend": "api"})
    found = ids(data, ai_ready=True)
    assert ("primary_incomplete" in found) is expected
    assert found[0] == ("cloud_asr_gap_filled" if filled else "cloud_asr_gap_unfilled") or "primary_incomplete" in found[:1]


def test_a_task_failed_by_a_block_it_could_not_fill_keeps_the_failure_cause():
    from twobyteasr.providers.cloud_api_worker import RESUBMIT_CATEGORIES
    error = RESUBMIT_CATEGORIES["content_blocked"] + " 第 1 / 1 段的 MOSI 任务被 MOSI 的内容安全审查拦下。"
    event = _gap_event(filled=False, rows=0, backend="", model="", reason="no_local_model")
    data = with_settings(failed(error, stage="在线 ASR API 主力转写（MOSS Pro 云端）", events=[event]),
                         models={"primary_asr_backend": "api"})
    found = ids(data, ai_ready=True)
    assert found[0] == "cloud_asr_content_blocked" and "cloud_asr_gap_unfilled" not in found
    assert "mosi_resplit" in ISSUES["cloud_asr_content_blocked"].actions


@pytest.mark.parametrize("error, issue", [
    ("MOSI 的内容安全审查拦下了这段音频（HTTP 403：safety_guardrail_blocked），没有受理。", "cloud_asr_content_blocked"),
    ('[2BYTEASR_API_ERROR] {"category": "balance", "message": "x"}', "cloud_asr_quota"),
    ('[2BYTEASR_API_ERROR] {"category": "key", "message": "x"}', "cloud_asr_auth"),
    ('[2BYTEASR_API_ERROR] {"category": "resubmit_needed", "resubmit": true}', "cloud_asr_resubmit"),
    ("MOSI 请求过于频繁或并发已满（HTTP 429）。", "cloud_asr_rate_limited"),
    ("连不上 dashscope-intl.aliyuncs.com（等待超时）。请检查网络或代理后重试", "cloud_asr_network"),
    ("本段音频超过 MOSI 512 MB 上传限制。", "cloud_asr_input_limit"),
    ("热词不符合 MOSI 限制（最多 20 个，每个不超过 30 字）。", "cloud_asr_hotwords"),
    ("录音文件识别只接受“服务商能读到的音频网址”，还没有设置音频交给服务商的方式", "cloud_asr_upload_setup"),
    ("还没有填写云端识别服务的 API Key。", "cloud_asr_auth"),
])
def test_cloud_messages_without_a_report(error, issue):
    found = ids({"status": "failed", "result": {"error": error}}, ai_ready=True)
    assert found[0] == issue and "cloud_asr_failed" not in found


@pytest.mark.parametrize("error, issue", [
    ("音频解码长时间无响应（超过 120 秒），ffmpeg 已被终止：a.flv。", "media_decode_stall"),
    ("识别启动后素材已改变：a.mp4", "studio_input_changed"),
    ("当前没有可运行的主力转写模型：请到模型工坊下载并选择模型，或配置在线 ASR API。", "no_primary_model"),
    ("已登记的模型目录不可用：E:\\models。请恢复磁盘连接或在路径登记中更正位置；不会重新下载。", "model_dir_unavailable"),
    ("MOSS 没有筛出可用的主播字幕。", "host_filter_empty"),
    ("断句阶段结果未通过来源正文、归属与时间校验：x；未提交或缓存。", "grouping_refused"),
    ("Qwen 单条本地修复未覆盖完整原文。", "hard_split_dead_end"),
    ("本地修复的文字与时间单元不一致。", "ja_number_timing_old"),
    ("字幕校对模型选择的模型 deepseek-reasoner 已不可用（服务商已下线）。", "ai_model_retired"),
    ("字幕校对模型使用账号登陆传输（grok），当前不可用：未登录。", "ai_cli_login"),
    ("Text AI stage is disabled for this task: polish", "term_search_polish_off"),
    ("invalid literal for int() with base 10: '2.1.2'", "old_batch_index_crash"),
    ("工程交付的任务 ID 与当前任务不一致。", "studio_result_mismatch"),
    ("FireRedVAD 没有检测到语音。", "empty_result"),
    ("主运行环境不完整或版本不匹配：torch 缺失。可点击“立即修复”自动重建该运行环境", "runtime_broken"),
    ("本次选择的 MOSS 需要 NVIDIA CUDA。", "no_cuda"),
])
def test_program_sentences_name_their_issue(error, issue):
    found = ids({"status": "failed", "result": {"error": error}}, ai_ready=True)
    assert found[0] == issue and "unknown_failure" not in found


def test_review_items_and_events_for_degraded_results():
    data = report(review_items=[
        {"category": "说话人需要确认", "detail": "x", "severity": "review"},
        {"category": "主力转写提前结束", "detail": "api 到 218.54s，FireRedVAD 人声到 236.69s", "severity": "warning"},
        {"category": "时间轴模型失败", "detail": "电脑可用内存不足（Windows 虚拟内存/页面文件太小），Qwen3 对齐模型没有加载", "severity": "warning"},
    ], events=report()["events"] + [{"event": "vad_backend_selected", "backend": "lightweight_vad", "reason": "main_runtime_missing"},
                                    {"event": "incremental_asr_fallback", "backend": "sensevoice", "error": "x"}])
    data["status"] = "degraded_success"
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=True))
    # The page file explains why the aligner failed, so it comes first.
    assert diagnosis.rule_ids[:3] == ("pagefile_too_small", "primary_incomplete", "alignment_degraded")
    assert diagnosis.findings[0].severity == "problem"  # the aligner only; the task finished
    assert {"speakers_need_review", "vad_lightweight_fallback", "incremental_fallback"} <= set(diagnosis.rule_ids)


def test_moss_vram_plan_without_error_text():
    data = failed("MOSS 整段worker失败（退出码 1）：子进程未返回具体异常。")
    data["moss_execution"] = {"window_plan": {"mode": "insufficient", "usable_bytes": 1}}
    assert ids(data, ai_ready=True)[0] == "gpu_out_of_memory"


def test_text_ai_key_errors_are_not_cloud_recognition():
    data = report(events=report()["events"] + [
        {"event": "polishing_api_fallback", "category": "auth_error", "error": "401 Unauthorized"}])
    found = ids(data, ai_ready=True)
    assert "ai_auth_failed" in found and not any(item.startswith("cloud_asr") for item in found)


def test_tips_and_informational_entries():
    data = report(events=report()["events"] + [{"event": "timeline_backend_rerouted", "language": "ja"},
                                               {"event": "numeric_edit_rejected"},
                                               {"event": "subtitle_translation_failed", "error": "timeout"}])
    data["settings"]["config_warnings"] = ["unknown key: foo"]
    found = ids(data, ai_ready=True)
    assert found[0] == "translation_failed"
    assert {"timeline_rerouted", "ai_edits_rejected", "settings_warnings"} <= set(found)
    cancelled = report(status="cancelled")
    assert ids(cancelled, ai_ready=True) == ("cancelled",)


def test_a_broken_check_does_not_stop_the_others(monkeypatch):
    from twobyteasr.recognition import run_diagnosis
    original = list(run_diagnosis._CHECKS)
    monkeypatch.setattr(run_diagnosis, "_CHECKS", [("cancelled", lambda facts: 1 / 0)] + original)
    assert ids(failed("moov atom not found"), ai_ready=True)[0] == "media_unreadable"


def test_garbage_report_does_not_crash():
    for data in ({}, {"status": "failed"}, {"events": "x", "settings": [], "result": None}):
        diagnose_run(DiagnosisInput(report=data, item_error="queue failed"))


def test_queue_failure_without_report_uses_the_item_error():
    found = ids({"status": "failed", "result": {"error": ""}}, item_error="缺少新流水线组件：moss_worker.py")
    assert found[0] == "runtime_broken"


# ---- the AI digest and prompt ------------------------------------------------------------

def big_report():
    data = user_report()
    noise = [{"event": "cue_delta", "cue_id": index, "text": "很长的字幕" * 20} for index in range(20000)]
    fails = [{"event": "grouping_api_fallback", "category": "timeout", "error": "e" * 3000, "batch_index": index}
             for index in range(40)]
    data["events"] = data["events"] + noise + fails
    data["review_items"] = [{"category": "边界待看", "detail": "细节" * 50, "cue_id": index} for index in range(5000)]
    return data


def test_digest_fits_the_limit_and_keeps_errors_and_failures():
    data = big_report()
    assert len(json.dumps(data, ensure_ascii=False)) > 2_000_000
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=False))
    text = digest_text(data, diagnosis.findings)
    assert len(text) <= DIGEST_LIMIT + 40
    assert "字幕保真检查未通过" in text
    assert "final_content_conservation_recovery" in text and "grouping_api_fallback" in text
    assert "fidelity_numbers" in text  # the local findings go along


def test_digest_hides_keys_and_folders():
    data = user_report()
    data["result"]["error"] += " Authorization: Bearer sk-abcdefghijklmnopqrstuv"
    data["events"].append({"event": "llm_request_failed", "error": "key sk-1234567890abcdefgh failed",
                           "input": r"F:\OBS\2026-10-21 16-39-40.mp4", "api_key": "sk-secretsecretsecret"})
    text = digest_text(data, ())
    assert "sk-abcdefghijklmnopqrstuv" not in text and "sk-1234567890abcdefgh" not in text
    assert "sk-secretsecretsecret" not in text
    assert r"F:\\OBS" not in text and "OBS" not in text
    assert "2026-10-21 16-39-40.mp4" in text  # the file name itself stays
    assert "someone" not in text  # media.path is not sent at all


def test_strip_folders_keeps_file_names():
    assert strip_folders(r"open F:\OBS\a b.mp4 now") == "open …\\a b.mp4 now"
    assert strip_folders("/Users/joy/Movies/a.mp4") == "/~/Movies/a.mp4"


def test_prompt_carries_the_catalog_and_answer_language():
    prompt = system_prompt("English", "0.8.2")
    assert "用English回答" in prompt and "0.8.2" in prompt
    for issue in ISSUES.values():
        assert f"[{issue.id}]" in prompt
    assert "SenseVoice" in knowledge_text()
    user = user_prompt('{"status": "failed"}', r"错误 C:\Users\x\a.mp4")
    assert "```json" in user and "完成页显示的错误" in user


def test_request_fits_the_token_budget_and_focuses_the_catalog():
    from twobyteasr.recognition.diagnosis_prompt import REQUEST_TOKEN_BUDGET, build_request, token_estimate
    data = big_report()
    diagnosis = diagnose_run(DiagnosisInput(report=data, ai_ready=False))
    messages, digest = build_request(diagnosis, language_name="简体中文", app_version="0.8.2")
    system, user = messages[0]["content"], messages[1]["content"]
    assert token_estimate(system, user) <= REQUEST_TOKEN_BUDGET
    assert digest in user
    # Findings and their stages in full; the rest one line each.
    assert "- 原因：断句把一个数字从中间切开" in system  # fidelity_numbers (a finding)
    assert "- 原因：" + ISSUES["cloud_asr_hotwords"].cause not in system
    assert "[cloud_asr_hotwords]" in system
    full = system_prompt("简体中文")
    assert len(system) < len(full)


def test_plain_report_is_redacted_and_lists_findings():
    diagnosis = diagnose_run(DiagnosisInput(report=user_report(), ai_ready=False))
    text = plain_report(diagnosis, language="zh", task_name="a.mp4", ai_answer="AI 说：sk-abcdefghijklmnop0000",
                        app_version="0.8.2")
    assert "fidelity_numbers" in text and "19:27" in text and "0.8.2" in text
    assert "sk-abcdefghijklmnop0000" not in text


def test_severity_and_confidence_constants():
    assert SEVERITIES[0] == "blocker" and CONFIDENCES[0] == "certain"
    assert diagnosis_checks.ai_category_issue("", "HTTP 429 Too Many Requests") == "ai_rate_limited"
