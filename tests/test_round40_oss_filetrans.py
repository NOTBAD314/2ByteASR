"""四十轮守护：OSS 临时音频中转 + Qwen Filetrans Provider。

用户规格的 10 个必测场景（CI 用 fake storage/requests；真实 OSS 走设置里的
「测试 OSS 连接」按钮做端到端）：
1  本地音频上传成功；            6  Qwen 失败后清理临时对象；
2  预签名 GET 返回 200；         7  用户取消后清理临时对象；
3  URL 过期阻断访问；            8  日志/请求体不含密钥与签名 query；
4  Qwen 收到 HTTPS URL 非本地路径；9  同名本地文件 → 不同 UUID key；
5  成功后对象删除；              10 不影响既有 MAI/OpenRouter/本地 provider。
"""

from __future__ import annotations

import os
import re
import uuid

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FILETRANS_ENDPOINT = {
    "provider": "qwen_filetrans",
    "protocol": "dashscope_filetrans",
    "model": "qwen-audio-3.0-asr-flash-filetrans",
    "url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
    "api_key": "sk-filetrans-secret",
    "style": "clean",
}

RESULT_PAYLOAD = {
    "transcripts": [
        {
            "text": "今天天气真好我们出去玩吧",
            "sentences": [
                {
                    "text": "今天天气真好",
                    "begin_time": 100,
                    "end_time": 3820,
                    "speaker_id": 0,
                    "words": [
                        {"text": "今天", "begin_time": 100, "end_time": 900},
                        {"text": "天气", "begin_time": 950, "end_time": 1900},
                        {"text": "真好", "begin_time": 1950, "end_time": 3820},
                    ],
                },
                {
                    "text": "我们出去玩吧",
                    "begin_time": 4200,
                    "end_time": 7000,
                    "speaker_id": 1,
                    "words": [
                        {"text": "我们", "begin_time": 4200, "end_time": 5100},
                        {"text": "出去", "begin_time": 5150, "end_time": 6100},
                        {"text": "玩吧", "begin_time": 6150, "end_time": 7000},
                    ],
                },
            ],
        }
    ]
}


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.reason = "OK"
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeFiletransRequests:
    """filetrans 提交/轮询/取消/结果下载四类请求的假实现。"""

    def __init__(self, *, result_payload=None, task_status="SUCCEEDED", cancel_first=False):
        self.posts = []
        self.gets = []
        self._result = result_payload if result_payload is not None else RESULT_PAYLOAD
        self._task_status = task_status
        self._cancel_first = cancel_first
        self._poll_count = 0

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("/cancel"):
            return _Resp(200, {"output": {"task_status": "CANCELED"}})
        return _Resp(
            200,
            {
                "output": {
                    "task_id": f"task-{len(self.posts)}",
                    "task_status": "PENDING",
                }
            },
        )

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if "/tasks/" in url:
            self._poll_count += 1
            if self._task_status == "FAILED":
                return _Resp(
                    200,
                    {
                        "output": {
                            "task_id": "task-1",
                            "task_status": "FAILED",
                            "message": "FILE_DOWNLOAD_FAILED",
                        }
                    },
                )
            return _Resp(
                200,
                {
                    "output": {
                        "task_id": "task-1",
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "file_url": "https://example/audio",
                                "transcription_url": "https://dashscope-results/transcription.json",
                                "subtask_status": "SUCCEEDED",
                            }
                        ],
                    }
                },
            )
        return _Resp(200, self._result)


class FakeStorage:
    """实现 TemporaryAudioStorage 协议的假中转层（记录全部调用）。"""

    def __init__(self):
        self.uploads = []
        self.deleted = []
        self.urls = []
        self.verify_calls = []

    def upload_audio(self, payload, extension, *, progress=None):
        from twobyteasr.providers.temp_audio_storage import StoredObject

        key = f"asr-temp/20260905/{uuid.uuid4().hex}.{extension}"
        self.uploads.append(key)
        return StoredObject(
            key=key,
            bucket="2byte",
            region="cn-hangzhou",
            size_bytes=len(payload),
            uploaded_seconds=0.01,
        )

    def create_download_url(self, key, ttl_seconds=None):
        url = (
            f"https://2byte.oss-cn-hangzhou.aliyuncs.com/{key}"
            "?Expires=1767225600&OSSAccessKeyId=LTAI_FAKE&Signature=SECRETQUERY"
        )
        self.urls.append(url)
        return url

    def verify_download_url(self, url):
        self.verify_calls.append(url)

    def delete_object(self, key):
        self.deleted.append(key)

    def describe(self):
        return "cn-hangzhou · 2byte"


def _audio(seconds=8.0):
    return np.zeros(int(16000 * seconds), dtype=np.float32)


@pytest.fixture()
def media_file(tmp_path):
    path = tmp_path / "同名单曲测试.mp4"
    path.write_bytes(b"\x00" * 32)
    return path


def _run_filetrans(monkeypatch, media_file, fake_requests, fake_storage, *, settings=None):
    import subtitle_core

    monkeypatch.setattr(
        subtitle_core,
        "RUNTIME_SETTINGS",
        settings
        or {"models": {"qwen_asr_api_protocol": "dashscope_filetrans", "oss_auto_delete": True}},
    )
    from twobyteasr.recognition.asr import _transcribe_qwen_filetrans

    return _transcribe_qwen_filetrans(
        str(media_file),
        _audio(),
        endpoint=dict(FILETRANS_ENDPOINT),
        requests_module=fake_requests,
        storage=fake_storage,
    )


# ---------------------------------------------------------------- 场景 4/5/8/9+1


def test_happy_path_rows_speakers_and_tokens(monkeypatch, media_file, capsys):
    fake_requests = FakeFiletransRequests()
    storage = FakeStorage()
    rows = _run_filetrans(monkeypatch, media_file, fake_requests, storage)

    # 解析：ms→s、说话人强制分句（S00/S01）、词级 tokens
    assert len(rows) == 2
    assert rows[0]["start"] == pytest.approx(0.1)
    assert rows[0]["end"] == pytest.approx(3.82)
    assert rows[0]["speaker"] == "API_S00"
    assert rows[1]["speaker"] == "API_S01"
    assert [token["text"] for token in rows[0]["tokens"]] == ["今天", "天气", "真好"]
    assert rows[0]["tokens"][0]["start"] == pytest.approx(0.1)

    # 场景 4：Qwen 只收到预签名 HTTPS URL，不带本地路径；请求体除 URL 本身
    # 外不含任何 OSS 凭据字段（URL 的 query 里带 key-id/签名是 OSS 预签名
    # 的固有设计——签名是派生值，不是 Secret）。
    submit = fake_requests.posts[0]
    assert submit[0] == FILETRANS_ENDPOINT["url"]
    body = submit[1]["json"]
    file_url = body["input"]["file_urls"][0]
    assert file_url.startswith("https://2byte.oss-cn-hangzhou.aliyuncs.com/asr-temp/")
    assert file_url == storage.urls[0]
    assert "同名单曲测试" not in file_url and ".mp4" not in file_url
    body_str = str(body).replace(file_url, "<URL>")
    assert "LTAI_FAKE" not in body_str and "SECRETQUERY" not in body_str
    assert "access_key" not in body_str.lower() and "oss_access" not in body_str.lower()
    # 鉴权头只有 DashScope Bearer，没有 OSS 凭据
    assert set(submit[1]["headers"]) <= {
        "Authorization", "Content-Type", "X-DashScope-Async",
    }
    # 官方要求：异步提交头
    assert submit[1]["headers"]["X-DashScope-Async"] == "enable"

    # 四十一轮：合法参数契约——enable_words 不是本路线参数（词级 words 自动
    # 返回）；parameters 必传；context 是数组 [{role, content:[{type,text}]}]。
    assert "enable_words" not in body["parameters"]
    assert body["parameters"] == {"diarization_enabled": True}
    context_block = body["input"].get("context")
    assert isinstance(context_block, list) and context_block[0]["role"] == "user"
    assert context_block[0]["content"][0]["type"] == "input_text"
    assert context_block[0]["content"][0]["text"]  # 上下文非空

    # 场景 5：成功后删除临时对象
    assert storage.deleted == [storage.uploads[0]]
    # 提交前做过 URL 可达性验证
    assert len(storage.verify_calls) == 1

    # 场景 8：日志脱敏（签名 query 与密钥绝不出现）
    out = capsys.readouterr().out
    assert "SECRETQUERY" not in out
    assert "sk-filetrans-secret" not in out
    assert "LTAI_FAKE" not in out
    assert "?[REDACTED]" in out


def test_same_named_local_files_get_distinct_uuid_keys(monkeypatch, media_file):
    """场景 9：对象 key 用日期+uuid，同名本地文件不会互相覆盖。"""
    storage = FakeStorage()
    _run_filetrans(monkeypatch, media_file, FakeFiletransRequests(), storage)
    _run_filetrans(monkeypatch, media_file, FakeFiletransRequests(), storage)
    assert len(storage.uploads) == 2
    assert storage.uploads[0] != storage.uploads[1]
    pattern = re.compile(r"^asr-temp/\d{8}/[0-9a-f]{32}\.wav$")
    for key in storage.uploads:
        assert pattern.match(key), key


def test_upload_progress_milestones_printed(capsys):
    from twobyteasr.providers.temp_audio_storage import OssTemporaryStorage

    class _FakeBucket:
        def put_object(self, key, data, headers=None, progress_callback=None):
            total = len(data)
            progress_callback(total // 4, total)
            progress_callback(total, total)

    storage = OssTemporaryStorage(
        region="cn-hangzhou",
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="2byte",
        access_key_id="LTAI_FAKE",
        access_key_secret="FAKE_SECRET",
        bucket_impl=_FakeBucket(),
    )
    stored = storage.upload_audio(b"x" * 4096, "wav")
    out = capsys.readouterr().out
    assert "25%" in out and "上传完成" in out
    assert stored.size_bytes == 4096


# ---------------------------------------------------------------- 场景 2/3


def _oss_storage_with_http(*, status):
    from twobyteasr.providers.temp_audio_storage import OssTemporaryStorage

    class _FakeBucket:
        def __init__(self):
            self.deleted = []

        def put_object(self, key, data, headers=None, progress_callback=None):
            if progress_callback:
                progress_callback(len(data), len(data))

        def sign_url(self, method, key, expires, **kwargs):
            return f"https://2byte.oss-cn-hangzhou.aliyuncs.com/{key}?Signature=SECRETQUERY"

        def delete_object(self, key):
            self.deleted.append(key)

    bucket = _FakeBucket()

    class _FakeResponse:
        status_code = status

        def iter_content(self, chunk_size):
            yield b"x"

        def close(self):
            pass

    def fake_get(url, **kwargs):
        return _FakeResponse()

    storage = OssTemporaryStorage(
        region="cn-hangzhou",
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="2byte",
        access_key_id="LTAI_FAKE",
        access_key_secret="FAKE_SECRET",
        http_get=fake_get,
        bucket_impl=bucket,
    )
    return storage, bucket


def test_oss_connection_test_success_message():
    """场景 2：真实链路（上传→预签名 GET→删除）成功 → OSS 已连接 · region · bucket。"""
    storage, _bucket = _oss_storage_with_http(status=200)
    result = storage.test_connection()
    assert result.ok
    assert result.message == "OSS 已连接 · cn-hangzhou · 2byte"
    assert result.object_key.startswith("asr-temp/")


def test_expired_or_forbidden_url_blocks_and_cleans_up():
    """场景 3：预签名 URL 不可达（如过期 403）→ 测试失败且探针对象被删除。"""
    storage, bucket = _oss_storage_with_http(status=403)
    result = storage.test_connection()
    assert not result.ok
    assert "403" in result.message
    assert bucket.deleted, "探针对象必须删除"


# ---------------------------------------------------------------- 场景 6/7


def test_task_level_parameter_downgrade_retry(monkeypatch, media_file, capsys):
    """四十一轮用户实录：提交 200 但执行期 InvalidParameter.ParseError——
    提交侧 400 降级摸不到，必须任务级降级重提（撤 context → 撤 diarization）。"""
    from twobyteasr.recognition.asr import _transcribe_qwen_filetrans

    class _RetryFake(FakeFiletransRequests):
        """第一次任务 FAILED(InvalidParameter.ParseError)；第二次成功。"""

        def __init__(self):
            super().__init__()
            self._submits = 0

        def post(self, url, **kwargs):
            if not url.endswith("/cancel"):
                self._submits += 1
                self._fail_current = self._submits == 1
            return super().post(url, **kwargs)

        def get(self, url, **kwargs):
            if "/tasks/" in url and getattr(self, "_fail_current", False):
                return _Resp(
                    200,
                    {
                        "output": {
                            "task_id": "task-1",
                            "task_status": "FAILED",
                            "code": "InvalidParameter.ParseError",
                            "message": "task parameter parse error",
                        }
                    },
                )
            return super().get(url, **kwargs)

    fake = _RetryFake()
    storage = FakeStorage()
    import subtitle_core

    monkeypatch.setattr(
        subtitle_core,
        "RUNTIME_SETTINGS",
        {"models": {"qwen_asr_api_protocol": "dashscope_filetrans", "oss_auto_delete": True}},
    )
    rows = _transcribe_qwen_filetrans(
        str(media_file),
        _audio(),
        endpoint=dict(FILETRANS_ENDPOINT),
        requests_module=fake,
        storage=storage,
    )
    assert rows, "第二次（无 context）必须成功返回行"
    assert fake._submits == 2
    submits = [kw["json"] for url, kw in fake.posts if not url.endswith("/cancel")]
    assert "context" in submits[0]["input"]
    assert "context" not in submits[1]["input"]
    assert submits[1]["parameters"] == {"diarization_enabled": True}
    out = capsys.readouterr().out
    assert "降级为更保守参数重提" in out
    # 临时对象只上传一次，最终删除
    assert len(storage.uploads) == 1 and storage.deleted == [storage.uploads[0]]


def test_hard_task_failure_not_retried_and_object_deleted(monkeypatch, media_file):
    """场景 6 + 四十一轮：非参数类失败（FILE_DOWNLOAD_FAILED）不得降级重提
    （避免烧 API 费用），立即抛错且临时对象删除。"""
    fake = FakeFiletransRequests(task_status="FAILED")
    storage = FakeStorage()
    with pytest.raises(Exception, match="filetrans 任务失败"):
        _run_filetrans(monkeypatch, media_file, fake, storage)
    submits = [url for url, _kw in fake.posts if not url.endswith("/cancel")]
    assert len(submits) == 1, "非 InvalidParameter 失败只提交一次"
    assert storage.deleted == [storage.uploads[0]]


def test_filetrans_endpoint_migrated_to_workspace_domain():
    """四十一轮：旧 dashscope 中心域名 → 工作台域名；用户自定义地址不动。"""
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings

    legacy_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
    payload = {
        **DEFAULT_SETTINGS,
        "models": {
            **DEFAULT_SETTINGS["models"],
            "qwen_asr_api_provider": "qwen_filetrans",
            "qwen_asr_api_protocol": "dashscope_filetrans",
            "qwen_asr_api_url": legacy_url,
        },
    }
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    assert merged["models"]["qwen_asr_api_url"].startswith(
        "https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/"
    )
    assert any("workspace domain" in str(item) for item in warnings)

    custom = {**payload, "models": {**payload["models"], "qwen_asr_api_url": "https://my-own.example.com/x"}}
    merged_custom, _warnings = _merge_known_settings(DEFAULT_SETTINGS, custom)
    assert merged_custom["models"]["qwen_asr_api_url"] == "https://my-own.example.com/x"


def test_api_key_dialog_keeps_saved_custom_url(monkeypatch):
    """四十一轮："让用户能自行保存和确认 api 地址 而不是强制刷新"——
    已保存 provider 的自定义地址打开配置弹窗时必须原样保留。"""
    from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

    import subtitle_core as legacy
    from twobyteasr.app import ui as ui_module
    from twobyteasr.app.ui import MainWindow

    custom_url = (
        "https://my-workspace.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/asr/transcription"
    )
    captured = []

    class _RecordingDialog(QDialog):
        def exec(self):
            captured.append(self)
            return 0

    original_dialog = ui_module.SpringDialog
    ui_module.SpringDialog = _RecordingDialog
    # 无 QApplication 直接建 QWidget = 静默崩溃（二十九轮教训）
    QApplication.instance() or QApplication([])
    window = MainWindow([], legacy, object(), None)
    monkeypatch.setattr(
        legacy,
        "RUNTIME_SETTINGS",
        {
            **legacy.RUNTIME_SETTINGS,
            "models": {
                **legacy.RUNTIME_SETTINGS.get("models", {}),
                "qwen_asr_api_provider": "qwen_filetrans",
                "qwen_asr_api_protocol": "dashscope_filetrans",
                "qwen_asr_api_model": "qwen-audio-3.0-asr-flash-filetrans",
                "qwen_asr_api_url": custom_url,
            },
        },
    )
    try:
        window.qwen_asr_api_url.setText(custom_url)
        window._open_api_key_dialog_for_preset("qwen_filetrans")
    finally:
        ui_module.SpringDialog = original_dialog

    assert captured, "弹窗必须被创建"
    dialog = captured[0]
    urls = [
        edit.text()
        for edit in dialog.findChildren(QLineEdit)
        if edit.text().strip().startswith("https://")
    ]
    assert custom_url in urls, "用户保存的自定义地址不得被预设强制刷新"
    window.close()
    window.deleteLater()


def test_cleanup_on_user_cancel(monkeypatch, media_file):
    """场景 7：用户取消 → CancelledError 且临时对象删除 + 尽力取消云端任务。"""
    from twobyteasr.recognition import asr as asr_module
    from twobyteasr.recognition.run_context import get_runtime_context

    class _Token:
        is_cancelled = False

    token = _Token()
    context = get_runtime_context()
    original = context.cancellation_token
    context.cancellation_token = token

    class _CancelAfterSubmit(FakeFiletransRequests):
        def get(self, url, **kwargs):
            # 第一次轮询：返回 PENDING 并触发用户取消——下一轮循环的
            # _raise_if_queue_cancelled 必须立刻退出（不能继续识别）。
            token.is_cancelled = True
            if "/tasks/" in url:
                return _Resp(
                    200,
                    {"output": {"task_id": "task-40", "task_status": "PENDING"}},
                )
            return super().get(url, **kwargs)

    fake = _CancelAfterSubmit()
    storage = FakeStorage()
    try:
        with pytest.raises(asr_module.CancelledError):
            _run_filetrans(monkeypatch, media_file, fake, storage)
    finally:
        context.cancellation_token = original
    assert storage.deleted == [storage.uploads[0]], "取消路径也要清理临时对象"
    cancel_posts = [url for url, _kw in fake.posts if url.endswith("/cancel")]
    assert cancel_posts, "取消时必须尽力取消云端任务"


# ---------------------------------------------------------------- 场景 10


def test_existing_providers_unaffected():
    """场景 10：新增 filetrans 不破坏既有 provider/协议链。"""
    from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint
    from twobyteasr.app.ui import ASR_API_PRESETS

    assert ASR_API_PRESETS["openrouter_word"]["protocol"] == "openrouter_verbose_json"
    assert ASR_API_PRESETS["qwen_filetrans"]["protocol"] == "dashscope_filetrans"
    assert ASR_API_PRESETS["qwen_filetrans"]["model"] == "qwen-audio-3.0-asr-flash-filetrans"
    validate_qwen_asr_endpoint(
        {
            "provider": "openrouter_word",
            "protocol": "openrouter_verbose_json",
            "model": "microsoft/mai-transcribe-2",
            "url": "https://openrouter.ai/api/v1/audio/transcriptions",
            "api_key": "k",
        }
    )
    validate_qwen_asr_endpoint(
        {
            "provider": "qwen_filetrans",
            "protocol": "dashscope_filetrans",
            "model": "qwen-audio-3.0-asr-flash-filetrans",
            "url": "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
            "api_key": "k",
        }
    )


def test_settings_roundtrip_keeps_oss_fields():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings

    merged, _warnings = _merge_known_settings(DEFAULT_SETTINGS, DEFAULT_SETTINGS)
    models = merged["models"]
    assert models["oss_region"] == "cn-hangzhou"
    assert models["oss_endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"
    assert models["oss_bucket"] == "2byte"
    assert models["oss_prefix"] == "asr-temp/"
    assert models["oss_signed_url_ttl"] == 86400
    assert models["oss_auto_delete"] is True
    # 越界 TTL 钳制；非法 endpoint 回默认；前缀补斜杠
    tweaked, tweaked_warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {
            **DEFAULT_SETTINGS,
            "models": {
                **DEFAULT_SETTINGS["models"],
                "oss_signed_url_ttl": 99999999,
                "oss_endpoint": "http://insecure.example.com",
                "oss_prefix": "asr-temp",
            },
        },
    )
    assert tweaked["models"]["oss_signed_url_ttl"] == 604800
    assert tweaked["models"]["oss_endpoint"].startswith("https://")
    assert tweaked["models"]["oss_prefix"] == "asr-temp/"


def test_oss_credentials_dpapi_roundtrip(monkeypatch):
    from twobyteasr.providers import llm_config

    payload = {}
    written = {}
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: payload)
    monkeypatch.setattr(llm_config, "_write_encrypted_secrets", lambda p: written.update(p))
    llm_config.save_oss_credentials("LTAI_NEW_ID", "NEW_SECRET")
    assert payload["OSS_ACCESS_KEY_ID"] == "LTAI_NEW_ID"
    assert payload["OSS_ACCESS_KEY_SECRET"] == "NEW_SECRET"
    # 留空保持原值
    llm_config.save_oss_credentials("", "")
    assert payload["OSS_ACCESS_KEY_ID"] == "LTAI_NEW_ID"


def test_storage_from_settings_requires_credentials(monkeypatch):
    from twobyteasr.providers.temp_audio_storage import oss_storage_from_settings

    settings = {"models": {"oss_bucket": "2byte"}}
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "")
    import twobyteasr.providers.llm_config as llm_config

    monkeypatch.setattr(
        llm_config, "read_secret_value", lambda *names: ("", "未配置")
    )
    assert oss_storage_from_settings(settings, credentials=("", "")) is None
    storage = oss_storage_from_settings(
        settings, credentials=("LTAI_FAKE", "FAKE_SECRET")
    )
    assert storage.describe() == "cn-hangzhou · 2byte"


# ---------------------------------------------------------------- UI


def test_api_key_dialog_has_style_combo_and_selected_first():
    """图一实录：API 服务配置弹窗必须有转写风格下拉；API 服务下拉选中项置顶。"""
    from PySide6.QtWidgets import QApplication, QDialog

    import subtitle_core as legacy
    from twobyteasr.app import ui as ui_module
    from twobyteasr.design.main_ui_popup import FramelessPopupCombo
    from twobyteasr.app.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    captured = []

    class _RecordingDialog(QDialog):
        def exec(self):
            captured.append(self)
            return 0

    original_dialog = ui_module.SpringDialog
    ui_module.SpringDialog = _RecordingDialog
    try:
        window = MainWindow([], legacy, object(), None)
        # 当前服务商 = qwen_filetrans → OSS 区块应可见
        index = window.qwen_asr_api_provider.findData("qwen_filetrans")
        assert index >= 0
        window.qwen_asr_api_provider.setCurrentIndex(index)
        window._open_api_key_dialog()
    finally:
        ui_module.SpringDialog = original_dialog

    assert captured, "弹窗必须被创建"
    dialog = captured[0]
    combos = dialog.findChildren(FramelessPopupCombo)
    labels = [combo.itemText(i) for combo in combos for i in range(combo.count())]
    assert any("清爽" in label for label in labels), "弹窗内必须能找到转写风格选项"
    assert any("逐字" in label for label in labels)
    provider_combo = next(
        combo for combo in combos if combo.count() >= len(ui_module.ASR_API_PRESETS)
    )
    assert provider_combo.property("selectedFirst") is True
    # selectedFirst（2026-09-17 起一次性）：仅首次 showPopup 把当前项移到第 0 行
    app.processEvents()
    provider_combo.showPopup()
    assert provider_combo.currentData() == "qwen_filetrans"
    assert provider_combo.currentIndex() == 0
    provider_combo.hidePopup()
    window.close()
    window.deleteLater()


def test_selected_first_moves_current_item_to_front_once_per_widget():
    """首次打开置顶一次；会话内再次选择/打开不再改变行位置（2026-09-17）。"""
    from PySide6.QtWidgets import QApplication

    from twobyteasr.design.main_ui_popup import FramelessPopupCombo

    app = QApplication.instance() or QApplication([])
    combo = FramelessPopupCombo()
    combo.setProperty("selectedFirst", True)
    for index, name in enumerate(["A", "B", "C", "D"]):
        combo.addItem(name, index)
    combo.setCurrentIndex(2)  # C
    combo.showPopup()
    assert combo.currentIndex() == 0
    assert combo.currentText() == "C"
    combo.hidePopup()
    order_after_first = [combo.itemText(i) for i in range(combo.count())]
    assert order_after_first == ["C", "A", "B", "D"]
    # 用户改选 D（如点击模型后的配置动作）——列表不重排
    combo.setCurrentIndex(combo.findText("D"))
    combo.showPopup()
    combo.hidePopup()
    order_after_select = [combo.itemText(i) for i in range(combo.count())]
    assert order_after_select == order_after_first
    # 新 widget（下次构建/重开页面）恢复按当前选中置顶
    fresh = FramelessPopupCombo()
    fresh.setProperty("selectedFirst", True)
    for index, name in enumerate(["C", "A", "B", "D"]):
        fresh.addItem(name, index)
    fresh.setCurrentIndex(fresh.findText("D"))
    fresh.showPopup()
    assert fresh.currentText() == "D"
    assert [fresh.itemText(i) for i in range(fresh.count())] == ["D", "C", "A", "B"]
    fresh.hidePopup()
    combo.deleteLater()
    fresh.deleteLater()
