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


def test_quick_chooser_gpu_check_never_keeps_the_dialog_alive_on_its_thread(monkeypatch):
    import gc
    import threading
    import time
    from PySide6.QtWidgets import QApplication
    from twobyteasr import hardware
    from twobyteasr.quick_setup import QuickSetupDialog

    app = QApplication.instance() or QApplication([])
    release = threading.Event()

    def slow_check():
        release.wait(timeout=5)
        return SimpleNamespace(ready=True, code='ok', gpu_name='NVIDIA RTX')

    monkeypatch.setattr(hardware, 'detect_cuda_runtime', slow_check)
    dialog = QuickSetupDialog(plan_keys=['local', 'cloud', 'light'], size_of=lambda _backends: 1.0)
    thread = next(t for t in threading.enumerate() if t.name == 'quick-setup-cuda')
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
    del dialog
    gc.collect()
    release.set()          # the late result has nowhere to go and is dropped
    thread.join(timeout=5)
    assert not thread.is_alive()
    app.processEvents()

    release.clear()
    release.set()
    dialog = QuickSetupDialog(plan_keys=['local', 'cloud', 'light'], size_of=lambda _backends: 1.0)
    deadline = time.monotonic() + 5
    while dialog._cuda is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert getattr(dialog._cuda, 'gpu_name', '') == 'NVIDIA RTX' and dialog.cards['local'].isEnabled()
    dialog.close()


def test_tutorial_bubble_is_measured_with_its_new_buttons():
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.home_tour import GuidedTour, TourAction, TourStep

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(1600, 1000)
    target = QWidget(window)
    target.setGeometry(10, 100, 1500, 120)
    window.show()
    text = '**放入影音**：把视频或音频拖进来，一次可以放好几个。先放一段演示视频'
    tour = GuidedTour(window, [TourStep('先看一眼'), TourStep(text, lambda: target, [
        TourAction('放入演示视频', lambda: None, advance=True)], show_next=False)])
    tour.start()
    app.processEvents()
    tour.go(1)                      # the action button is created while the bubble is visible
    button = tour.action_buttons[0]
    assert button.isVisible()
    assert tour.bubble.height() >= tour.bubble.sizeHint().height()
    assert tour.text.geometry().bottom() < button.geometry().top()
    tour.close_tour(False)
    window.close()


def test_tutorial_project_has_something_to_teach_on_every_step():
    import subtitle_core
    from twobyteasr.sample_project import ensure_tutorial_project, tutorial_ai_preview, TUTORIAL_LIBRARY
    from twobyteasr.studio_glossary_service import preview_glossary_correction
    from twobyteasr.studio_project import load_project
    from twobyteasr.studio_qc import review_candidates
    from twobyteasr.terminology import snapshot_glossaries

    project = load_project(ensure_tutorial_project())
    # Review mode: the three recognizers disagree on the first line → three choices (keys 1/2/3).
    first = project.cues[0]
    assert len(review_candidates(project, first)) == 3
    assert all(len(review_candidates(project, cue)) == 1 for cue in project.cues[1:])
    # The built-in 原神 library fixes three spellings offline; the stand-in "AI" adds 派门→派蒙 twice.
    snapshot = snapshot_glossaries(subtitle_core, [subtitle_core.runtime_game_identity(TUTORIAL_LIBRARY)])
    ids = [cue.id for cue in project.cues]
    local = preview_glossary_correction(project, ids, snapshot, {}, use_ai=False)
    texts = {cue.id: cue.text for cue in project.cues}
    fixed = {texts[hit.cue_id][:hit.span[0]] + hit.replacement + texts[hit.cue_id][hit.span[1]:]
             for hit in local.hits if hit.source == 'local_confirmed'}
    assert {'听说至冬那边下了很大的雪', '坎瑞亚的故事我还没看完', '阿蕾奇诺这次登场好帅'} <= fixed
    assert not local.receipt.get('pending_rows')  # nothing unrelated to explain
    pretend = tutorial_ai_preview(project, ids, snapshot, {})
    ai = [hit for hit in pretend.hits if hit.source == 'ai_accepted']
    assert [(hit.original, hit.replacement) for hit in ai] == [('派门', '派蒙')] * 2
    assert len(pretend.hits) == len(local.hits) + 2 and pretend.receipt['tutorial'] is True
    # A new tutorial starts from a clean copy.
    assert load_project(ensure_tutorial_project()).cues[1].text == '听说至东那边下了很大的雪'


def test_tutorial_steps_let_clicks_through_the_outline_and_move_on_when_done():
    import time
    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from twobyteasr.home_tour import GuidedTour, TourAction, TourStep

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(1400, 900)
    button = QPushButton('目标', window)
    button.setGeometry(60, 380, 160, 44)
    video = QWidget(window)          # stands for the native video window the bubble must not cover
    video.setGeometry(600, 150, 700, 500)    # right of the target: the bubble goes below instead
    window.show()
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    tour = GuidedTour(window, [
        TourStep('点目标', lambda: button, [TourAction('帮我做', button.click)], show_next=False,
                 interactive=True, done=lambda: bool(clicked)),
        TourStep('完成'),
    ], avoid=lambda: [QRectF(video.geometry())])
    tour.start()
    app.processEvents()
    hole_center = tour.hole.center().toPoint()
    assert not tour.mask().contains(hole_center)                 # clicks there reach the page
    assert tour.mask().contains(QPoint(1300, 50))                # elsewhere the page waits
    assert tour.mask().contains(tour.bubble.geometry().center())
    bubble = QRectF(tour.bubble.geometry())
    assert not bubble.intersects(tour.hole) and not bubble.intersects(QRectF(video.geometry()))
    assert tour.pointer is not None
    button.click()                                               # as if the user clicked through the hole
    deadline = time.monotonic() + 3
    while tour.index == 0 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert tour.index == 1 and tour.mask().isEmpty()             # moved on by itself; centred card, no hole
    tour.close_tour(True)
    window.close()
