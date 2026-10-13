"""Home "现在先做什么", example project, feature search and diagnostics (2026-10-13)."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr import onboarding
from twobyteasr.recognition_choices import HostProfile, PlanOption


def host(nvidia=False, system="win32", machine="amd64", main=True):
    return HostProfile(system, machine, nvidia, main, False)


def facts(**overrides):
    value = onboarding.Facts(host=host(), options=[], plan_ready=False, plan_problem="", cloud_ready=False)
    value.__dict__.update(overrides)
    return value


def test_fresh_install_starts_at_step_one_with_one_main_button():
    step = onboarding.compute_next_step(media_count=0, facts=None, state={"guide": True})
    assert step.key == "welcome" and step.dismissible and step.step == 0
    assert [action for _label, action in step.actions] == ["choose_media", "tour", "open_sample"]
    assert len(step.message) <= 30 and "**" in step.message      # one short line, key words marked


def test_existing_user_sees_nothing_when_everything_works():
    ready = facts(plan_ready=True)
    assert onboarding.compute_next_step(media_count=0, facts=ready, state={"guide": False}).key == ""
    assert onboarding.compute_next_step(media_count=1, facts=ready, state={"guide": False}).key == ""


def test_closing_the_guide_is_not_followed_by_another_card_until_media_is_chosen():
    broken = facts(plan_ready=False, plan_problem="当前方案的本机模型还没有下载。")
    assert onboarding.compute_next_step(media_count=0, facts=broken, state={"guide": False}).key == ""
    assert onboarding.compute_next_step(media_count=1, facts=broken, state={"guide": False}).key == "plan"


def test_card_never_blocks_while_the_background_check_runs():
    assert onboarding.compute_next_step(media_count=1, facts=None, state={"guide": False}).key == ""


def test_no_nvidia_is_never_sent_to_the_cuda_plan():
    options = [PlanOption("cloud_only", "云端识别", "", False, "还没有设置云端识别服务的 API Key。"),
               PlanOption("windows_cuda", "NVIDIA", "", False, "这台电脑没有检测到 NVIDIA 显卡工具。"),
               PlanOption("cpu_local", "CPU", "", False, "需要在模型工坊准备 SenseVoice（CPU）。")]
    models = {"primary_asr_backend": "moss"}
    current = facts(options=options)
    ready, problem = onboarding.current_plan_status(models, current)
    assert not ready and "NVIDIA" in problem
    current.plan_ready, current.plan_problem = ready, problem
    step = onboarding.compute_next_step(media_count=1, facts=current, state={"guide": False})
    assert step.key == "plan" and step.step == 1 and "NVIDIA" in step.detail   # the exact reason on hover
    assert step.actions == [("选择识别方式", "choose_plan")]
    assert not any(action.startswith("use_plan:") for _label, action in step.actions)  # nothing is usable yet


def test_ready_plan_is_described_plainly_and_offered_without_switching():
    options = [PlanOption("cloud_only", "云端识别", "", True, "", {"primary_asr_backend": "api"})]
    current = facts(options=options, plan_ready=False, plan_problem="当前方案的本机模型还没有下载。")
    step = onboarding.compute_next_step(media_count=1, facts=current, state={"guide": False})
    assert step.actions == [("选择识别方式", "choose_plan"), ("改用“云端识别”", "use_plan:cloud_only")]
    assert onboarding.plan_patch("cloud_only", current) == {"primary_asr_backend": "api"}
    assert "最快" not in step.message and "最准" not in step.message


def test_marked_words_are_highlighted_and_everything_else_is_escaped():
    html = onboarding.emphasis_html("先**选择识别方式**<b>x</b>", "#b34470")
    assert '<span style="color:#b34470; font-weight:700;">选择识别方式</span>' in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>" not in html


def test_cloud_plan_ready_state_and_saved_key_checks():
    models = {"primary_asr_backend": "api"}
    assert onboarding.current_plan_status(models, facts(cloud_ready=True)) == (True, "")
    assert onboarding.current_plan_status(models, facts(cloud_ready=False), "还没有填写云端识别服务的 API Key。")[0] is False
    assert onboarding.current_plan_status({"primary_asr_backend": "sensevoice"},
                                          facts(installed=frozenset({"sensevoice"})))[0] is True


def test_guide_state_is_stamped_once_and_existing_users_are_not_taught(monkeypatch):
    store = {}
    monkeypatch.setattr(onboarding, "load_state", lambda: dict(store))
    monkeypatch.setattr(onboarding, "save_state", lambda state: (store.clear(), store.update(state)))
    monkeypatch.setattr(onboarding, "looks_like_existing_user", lambda: True)
    state = onboarding.ensure_state()
    assert state["fresh"] is False and state["guide"] is False
    monkeypatch.setattr(onboarding, "looks_like_existing_user", lambda: False)
    assert onboarding.ensure_state()["fresh"] is False  # stamped: an upgrade never flips into a tutorial
    assert onboarding.set_guide(True)["guide"] is True     # the help menu can bring it back
    onboarding.mark_first_task_done()
    assert store["guide"] is False and store["first_task_done"] is True


def test_example_project_needs_no_model_and_explains_itself(tmp_path, monkeypatch):
    from twobyteasr import sample_project
    from twobyteasr.studio_project import load_project
    monkeypatch.setattr(sample_project, "sample_root", lambda: tmp_path / "example")
    path = sample_project.ensure_sample_project()
    project = load_project(path)
    assert sample_project.is_sample_project(project)
    assert len(project.cues) == 8 and {s.name for s in project.speakers} == {"旁白", "嘉宾"}
    assert project.media.duration_ms == sample_project.SAMPLE_SECONDS * 1000
    assert "示意影片" in project.cues[0].text
    assert sample_project.ensure_sample_project() == path  # reused, not regenerated


def test_feature_search_finds_the_places_people_ask_for():
    from twobyteasr.feature_search import entries, search
    window = SimpleNamespace(**{name: (lambda *a, **k: None) for name in (
        "_open_application_settings", "_open_api_setup_guide", "_open_ai_settings_dialog", "_next_step_action",
        "_open_model_workshop", "_open_sample_project", "_open_diagnostics_dialog", "_check_updates", "_manage_terms",
        "_switch_page", "built_page", "_open_subtitle_studio")})
    items = entries(window)
    assert search(items, "标点")[0].title.startswith("字幕标点")
    assert search(items, "Qwen")[0].title.startswith("Qwen Cloud")
    assert search(items, "快捷键")[0].title == "快捷键"
    assert search(items, "MCP")[0].title.startswith("外部 AI")
    assert search(items, "cuda")[0].title.startswith("识别方式")


def test_diagnostics_never_contain_keys_signed_urls_or_home_folder():
    from pathlib import Path
    from twobyteasr.diagnostics_report import scrub
    home = str(Path.home())
    text = scrub(f"sk-ws-abcdefghijklmnopq Bearer abc.def https://x.oss.com/a?OSSAccessKeyId=LTAIabcdefghijklmn&Signature=zz "
                 f"{home}\\Videos\\clip.mp4 someone@example.com")
    for secret in ("sk-ws-abcdefghijklmnopq", "Signature=zz", "LTAIabcdefghijklmn", home, "someone@example.com"):
        assert secret not in text
    assert "~" in text and "https://x.oss.com/a" in text


def test_home_role_cards_recognize_every_host_limit():
    from twobyteasr.recognition_choices import HostProfile, unavailable_on_host
    from twobyteasr.ui import _HOST_LIMIT_STATUSES
    no_gpu = HostProfile("win32", "amd64", False, True, False)
    assert unavailable_on_host("primary", "moss", no_gpu) in _HOST_LIMIT_STATUSES
    assert unavailable_on_host("review", "local", no_gpu) in _HOST_LIMIT_STATUSES
    assert unavailable_on_host("timeline", "mlx_qwen_aligner", no_gpu) in _HOST_LIMIT_STATUSES
    assert unavailable_on_host("primary", "sensevoice", no_gpu) == ""
