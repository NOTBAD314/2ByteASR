import json
import os
import pytest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from twobyteasr.model_workshop import (
    MODELS,
    ModelDownloadDialog,
    ModelWorkshopPage,
    _model_logo,
    installed_model_keys,
)
from PySide6.QtCore import QProcess, QSize
from twobyteasr.ui import FramelessPopupCombo, populate_available_asr_choices


ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import reset_runtime_paths, MODEL_ROOT_ENV, USER_DATA_ENV
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT',str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV,str(tmp_path/'models'))
    monkeypatch.setenv(USER_DATA_ENV,str(tmp_path/'local'))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


@pytest.mark.parametrize('saved_model',['','microsoft/mai-transcribe-2'])
def test_mai_pending_mapping_never_claims_ready_from_a_preserved_key(monkeypatch,saved_model):
    from twobyteasr.model_workshop import _metric_evidence
    monkeypatch.setattr('twobyteasr.llm_config.read_asr_api_key',lambda *a:('preserved-key','test'))
    app=QApplication.instance() or QApplication([])
    page=ModelWorkshopPage(ROOT,{'models':{'qwen_asr_api_provider':'openrouter_word',
                                        'qwen_asr_api_model':saved_model,'primary_asr_backend':'api'}})
    model=page._cards['mai_latest'].model
    assert page._model_state(model)=='configure'
    assert not _metric_evidence(model,'accuracy',api_model=saved_model)['available']
    page.deleteLater();app.processEvents()


def test_installed_model_keys_requires_every_locked_file(tmp_path):
    payload = {
        "models": {
            "ready": {"path": "models/ready", "required_files": ["a.bin", "b.json"]},
            "partial": {"path": "models/partial", "required_files": ["a.bin", "b.json"]},
        }
    }
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "models" / "ready").mkdir(parents=True)
    (tmp_path / "models" / "partial").mkdir(parents=True)
    (tmp_path / "models" / "ready" / "a.bin").write_bytes(b"a")
    (tmp_path / "models" / "ready" / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "models" / "partial" / "a.bin").write_bytes(b"a")

    assert installed_model_keys(tmp_path) == {"ready"}


def test_workshop_filters_roles_and_emits_real_backend_changes(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('twobyteasr.environment.fast_preflight',lambda role:SimpleNamespace(ok=True))
    app = QApplication.instance() or QApplication([])
    settings = {
        "models": {
            "qwen_asr_backend": "api",
            "firered_asr_backend": "local",
        }
    }
    page = ModelWorkshopPage(ROOT, settings)
    page._set_role("timeline")

    assert page.findChild(QLabel, "workshopLogoWord") is None
    assert not page._cards["firered"].isHidden()
    assert page._cards["moss"].isHidden()
    assert page._cards["qwen_local"].isHidden()

    page.runtime_settings["models"]["qwen_asr_backend"] = "local"
    page._installed = {"moss", "firered_vad", "speaker_embedding", "firered_aed"}
    page._refresh_combo()
    assert page.combo_model_labels["primary"].text() == "MOSS"
    assert page.combo_status_labels["primary"].text() == "已安装"
    assert page.combo_status_labels["timeline"].text() == "已安装"
    assert page.combo_model_labels["review"].text() == "Qwen3-ASR"
    assert page.combo_status_labels["review"].text() == "未安装"

    terms_nav = next(
        button for button in page.findChildren(QPushButton) if button.text() == "术语库"
    )
    terms_nav.setChecked(True)
    page.restore_active_navigation()
    assert page.workshop_nav_button.isChecked()

    requested = []
    page.backend_requested.connect(lambda role, value: requested.append((role, value)))
    page._installed.add("firered_aed")
    page._perform_action("firered")
    assert requested == [("firered", "off")]

    page.deleteLater()
    app.processEvents()


def test_workshop_exposes_api_presets_and_downloadable_adapter_candidates(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("twobyteasr.model_workshop.resolve_api_key", lambda _stage: ("", "missing"))
    monkeypatch.setattr("twobyteasr.model_workshop.installed_model_keys", lambda _root: set())
    page = ModelWorkshopPage(ROOT, {"models": {"qwen_asr_backend": "off"}})
    requested = []
    page.api_preset_requested.connect(requested.append)

    page._perform_action("groq_api")

    assert requested == ["groq"]
    assert {model.key for model in MODELS if model.api_preset} >= {
        "qwen31_filetrans",
        "groq_api",
        "openai_api",
        "custom_asr_api",
    }
    # The current long-file provider intentionally replaced the retired card.
    # Keep protocol/model/roles and real configuration-signal checks explicit.
    from twobyteasr.ui import ASR_API_PRESETS
    assert 'qwen_api' not in page._cards
    qwen = page._cards['qwen31_filetrans'].model
    assert qwen.api_preset == 'qwen31_filetrans'
    assert qwen.asr_capabilities == ('ASR_TEXT', 'TIMESTAMP', 'DIARIZATION')
    assert dict(qwen.adapter_bindings) == {'primary': 'api', 'review': 'api'}
    assert ASR_API_PRESETS[qwen.api_preset]['protocol'] == 'dashscope_filetrans'
    assert page._api_model_for(qwen) == 'qwen-audio-3.1-asr-flash-filetrans'
    page._perform_action('qwen31_filetrans', role='review')
    assert requested == ['groq', 'qwen31_filetrans']
    assert page.api_target_role == 'review'
    sensevoice = page._cards["sensevoice"].model
    assert page._model_state(sensevoice) == "missing"
    assert page._action_text(sensevoice, "missing") == ("下载", True)
    page._installed.add("sensevoice")
    assert page._model_state(sensevoice) == "installed"
    assert page._action_text(sensevoice, "downloaded") == ("已下载 · 接入中", False)
    assert {model.key for model in MODELS if "timeline" in (model.role, *model.extra_roles)} >= {
        "firered",
        "qwen_aligner",
        "paraformer",
        "whisper",
    }
    assert {model.key for model in MODELS if "review" in (model.role, *model.extra_roles)} >= {
        "qwen_local",
        "sensevoice",
        "whisper",
        "funasr_nano",
    }
    assert all(not hasattr(model, "accuracy") and not hasattr(model, "speed") for model in MODELS)

    page._set_role("review")
    page._installed.add("sensevoice")
    requested_backends = []
    page.backend_requested.connect(lambda role, value: requested_backends.append((role, value)))
    page._perform_action("sensevoice")
    assert requested_backends[-1] == ("qwen", "sensevoice")
    page.deleteLater()
    app.processEvents()


def test_vendor_logo_assets_load_for_recognizable_model_cards():
    app = QApplication.instance() or QApplication([])
    expected = {
        "moss", "firered", "qwen_local", "whisper", "sensevoice",
        "glm_asr_nano", "canary_qwen", "omni_asr_llm_7b",
    }
    models = {model.key: model for model in MODELS}
    for key in expected:
        assert models[key].logo_asset
        assert not _model_logo(models[key], QSize(44, 44)).isNull()
    app.processEvents()


def test_model_download_dialog_waits_for_source_choice_and_passes_it_to_script(monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == "moss")
    dialog = ModelDownloadDialog(ROOT, model)
    starts = []
    monkeypatch.setattr(dialog.process, "start", lambda program, args: starts.append((program, args)))
    monkeypatch.setattr(dialog.process, "waitForStarted", lambda _timeout: True)

    assert not starts
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 0
    modes = [dialog.source_combo.itemData(index) for index in range(dialog.source_combo.count())]
    dialog.source_combo.setCurrentIndex(modes.index("MODELSCOPE"))
    dialog.start()

    assert starts
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 0
    args = starts[0][1]
    assert args[args.index("-Source") + 1] == "MODELSCOPE"
    assert args[args.index("-Only") + 1] == "moss"
    dialog.deleteLater()
    app.processEvents()


def test_main_selectors_only_offer_complete_local_models(tmp_path):
    app = QApplication.instance() or QApplication([])
    payload = {
        "models": {
            "sensevoice": {
                "path": "models/SenseVoiceSmall",
                "required_files": ["model.pt"],
            },
            "whisper_turbo": {
                "path": "models/Whisper",
                "required_files": ["model.safetensors", "config.json"],
            },
        }
    }
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(payload), encoding="utf-8")
    sensevoice = tmp_path / "models" / "SenseVoiceSmall"
    sensevoice.mkdir(parents=True)
    (sensevoice / "model.pt").write_bytes(b"ready")
    whisper = tmp_path / "models" / "Whisper"
    whisper.mkdir(parents=True)
    (whisper / "config.json").write_text("{}", encoding="utf-8")

    primary, review, timeline = (FramelessPopupCombo() for _ in range(3))
    missing = populate_available_asr_choices(
        primary,
        review,
        timeline,
        {"models": {
            "primary_asr_backend": "whisper_turbo",
            "qwen_asr_backend": "sensevoice",
            "firered_asr_backend": "whisper_turbo",
        }},
        root=tmp_path,
    )

    assert primary.findData("sensevoice") >= 0
    assert primary.findData("whisper_turbo") == -1
    assert review.findData("sensevoice") >= 0
    assert timeline.findData("whisper_turbo") == -1
    assert primary.currentData() == "none"
    assert {item[0] for item in missing} == {"primary_asr_backend", "firered_asr_backend"}
    for combo in (primary, review, timeline):
        combo.deleteLater()
    app.processEvents()


def test_model_download_dialog_accepts_one_combination_in_one_process(monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == "sensevoice")
    dialog = ModelDownloadDialog(
        ROOT,
        model,
        download_keys=("sensevoice", "qwen_asr"),
        display_name="轻量复核组合",
    )
    starts = []
    monkeypatch.setattr(dialog.process, "start", lambda program, args: starts.append((program, args)))
    monkeypatch.setattr(dialog.process, "waitForStarted", lambda _timeout: True)
    dialog.start()

    args = starts[0][1]
    only_index = args.index("-Only")
    assert args[only_index + 1] == "sensevoice,qwen_asr"
    assert args.count("-Only") == 1
    dialog.deleteLater()
    app.processEvents()


def test_successful_download_keeps_one_completion_button():
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == "sensevoice")
    dialog = ModelDownloadDialog(ROOT, model)
    dialog._finished_v2(0, None)

    assert dialog.start_button.isVisible() or not dialog.isVisible()
    assert dialog.start_button.text() == "完成"
    assert dialog.start_button.isEnabled()
    assert dialog.close_button.text() == "关闭"
    assert dialog.progress_status.text() == "✓ 文件与运行库准备完成 · 使用时验证模型加载"
    assert dialog.progress.value() == 100
    dialog.deleteLater()
    app.processEvents()


def test_download_result_sound_plays_once_for_final_outcome(monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == "sensevoice")
    sounds = []
    monkeypatch.setattr("twobyteasr.model_workshop._play_download_result_sound", sounds.append)

    dialog = ModelDownloadDialog(ROOT, model)
    dialog._finished_v2(0, None)
    dialog._finished_v2(0, None)
    assert sounds == [True]
    dialog.deleteLater()

    failed = ModelDownloadDialog(ROOT, model)
    failed._finished_v2(1, None)
    assert sounds == [True, False]
    failed.deleteLater()

    paused = ModelDownloadDialog(ROOT, model)
    paused._paused = True
    paused._finished_v2(1, None)
    assert sounds == [True, False]
    paused.deleteLater()
    app.processEvents()


def test_workshop_individual_download_waits_but_first_run_can_auto_start(monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(ROOT, {"models": {"qwen_asr_backend": "off"}})
    started = []
    monkeypatch.setattr(ModelDownloadDialog, "start", lambda dialog: started.append(dialog.download_keys))

    manual = page.download_combination(["sensevoice"], "SenseVoice Small")
    app.processEvents()
    assert started == []
    manual.close()
    app.processEvents()

    automatic = page.download_combination(
        ["sensevoice"],
        "首次选择的字幕识别组合",
        auto_start=True,
    )
    app.processEvents()
    assert started == [("sensevoice",)]
    automatic.close()
    page.deleteLater()
    app.processEvents()


def test_background_download_has_reopenable_page_progress_and_coherent_card_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(ROOT, {"models": {"qwen_asr_backend": "off"}})
    page.show()
    app.processEvents()
    dialog = page.download_combination(["sensevoice", "qwen_asr"], "首次识别组合")
    monkeypatch.setattr(
        dialog.process, "state", lambda: QProcess.ProcessState.Running
    )
    dialog.progress.setRange(0, 100)
    dialog.progress.setValue(37)
    dialog.progress_status.setText("正在下载 model.safetensors")
    dialog.hide()

    page._sync_download_activity()
    assert page.download_activity.isVisible()
    assert page.download_activity_progress.value() == 37
    assert "首次识别组合" in page.download_activity_text.text()
    assert page._model_state(page._cards["sensevoice"].model) == "downloading"

    page.refresh()
    card = page._cards["sensevoice"]
    assert card.action.text() == "查看进度"
    assert not card.uninstall.isVisible()

    reopened = page.download_combination(["moss"], "另一个模型")
    assert reopened is dialog
    page.deleteLater()
    app.processEvents()


def test_download_failure_is_actionable_and_shown(monkeypatch):
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == "sensevoice")
    dialog = ModelDownloadDialog(ROOT, model)
    dialog.log.setPlainText("failed to rename c10.dll: 拒绝访问。 (os error 5)")
    message = dialog._actionable_failure_message(1)
    assert "运行库" in message
    assert "占用" in message

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog._finished_v2(1, None)
    assert warnings == []
    assert "运行库" in dialog.progress_status.text()
    assert dialog.start_button.text() == "继续重试"
    dialog.deleteLater()
    app.processEvents()


def test_combo_estimate_tracks_selected_primary_instead_of_always_moss(monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = {
        "models": {
            "primary_asr_backend": "sensevoice",
            "firered_asr_backend": "off",
            "qwen_asr_backend": "sensevoice",
        }
    }
    page = ModelWorkshopPage(ROOT, settings)
    page._installed = set()
    page._refresh_combo()
    estimate = page.download_estimate.text()
    assert "SenseVoice" in estimate
    assert "MOSS" not in estimate
    page.deleteLater()
    app.processEvents()


def test_structured_failure_handles_empty_detail_and_preserves_raw_log():
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == 'sensevoice')
    dialog = ModelDownloadDialog(ROOT, model)
    original = '[2BYTEASR_ERROR] {"category":"disk_space","detail":""}'
    dialog.log.setPlainText(original)
    assert '磁盘空间不足' in dialog._actionable_failure_message(1)
    assert dialog.log.toPlainText() == original
    dialog.log.setPlainText('[2BYTEASR_INSTALL_ERROR] {"phase":"dependencies_installing","message":"uv failed\\nraw detail"}')
    message = dialog._actionable_failure_message(3)
    assert '依赖安装失败' in message and 'uv failed' in message
    assert 'raw detail' not in message
    assert 'raw detail' in dialog.log.toPlainText()
    dialog.deleteLater()
    app.processEvents()


def test_runtime_download_failure_names_the_stage_and_what_to_try():
    app = QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.key == 'moss')
    dialog = ModelDownloadDialog(ROOT, model)
    failure = '[2BYTEASR_INSTALL_ERROR] {"phase":"tools_preparing","category":"runtime_network","message":"uv 下载失败"}'
    dialog.log.setPlainText(failure)
    message = dialog._actionable_failure_message(1)
    assert '运行环境准备阶段' in message and '尚未请求权重源' not in message
    assert 'TUN' in message and 'HTTPS_PROXY' in message
    dialog.log.setPlainText('error: No solution found when resolving dependencies\n'+failure)
    assert '依赖版本冲突' in dialog._actionable_failure_message(1)
    dialog.deleteLater()
    app.processEvents()


def test_downloader_supports_model_workshop_only_mode():
    source = (ROOT / "scripts" / "download_models.ps1").read_text(encoding="utf-8-sig")
    assert '[string]$Only = ""' in source
    assert "$Only -split ','" in source
    assert 'if ("moss" -in $onlyNames)' in source
    assert '@("firered_vad", "speaker_embedding")' in source
    assert 'if ("qwen_asr" -in $onlyNames) { $IncludeQwen = $true }' in source
    assert "AUTO" in source and "MODELSCOPE" in source
    assert "HF_MIRROR" in source and "HF_OFFICIAL" in source
    assert "download_sources" in source
    assert '"qwen_aligner", "whisper_turbo", "sensevoice", "paraformer", "funasr_nano"' in source
    assert "run_repository_download.py" in source
    assert 'foreach ($url in $urls)' not in source
