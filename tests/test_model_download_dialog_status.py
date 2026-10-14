"""Download window wording for the 2026-10-14 mainland round: whole-model progress,
current source, automatic source switch, resume, reuse and final verification."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.model_workshop import MODELS, ModelDownloadDialog

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import reset_runtime_paths, MODEL_ROOT_ENV, USER_DATA_ENV
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / 'models'))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / 'local'))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _line(prefix, **payload):
    return f"{prefix} {json.dumps(payload, ensure_ascii=False)}"


def _dialog():
    QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.download_key == 'funasr_nano')
    return ModelDownloadDialog(ROOT, model)


def test_status_shows_source_switch_reuse_whole_model_progress_resume_and_verification():
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
               attempt=1, total=2, status='trying'))
    feed(_line('[2BYTEASR_FILE]', file='Qwen3-0.6B/config.json', index=1, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
               attempt=1, total=2, status='failed', category='network_timeout'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    text = dialog.progress_status.text()
    assert 'Hugging Face 官方 没有完成（连接超时），自动改试 HF 镜像（可能回源官方）（hf-mirror.com）' in text
    assert '第 2/2 个来源' in text

    feed(_line('[2BYTEASR_CACHE]', file='multilingual.tiktoken', bytes=1_000_000, origin='verified staging', network_bytes=0))
    assert '已沿用校验过的文件：multilingual.tiktoken' in dialog.progress_status.text()

    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_PROGRESS]', percent=50, downloaded=985_574_715, total=1_971_149_431,
               speed=20 * 1024 ** 2, phase='download'))
    text = dialog.progress_status.text()
    assert '整个模型 0.92 / 1.85 GiB（49%）' in text and '剩余约' in text
    assert '来源：HF 镜像（可能回源官方） (hf-mirror.com)  ·  第 2/2 个来源' in text
    assert dialog.progress.value() == 49

    feed('第 1 次中断（已有进展，保留断点续传），1.0 秒后重试：Connection broken')
    feed(_line('[2BYTEASR_PROGRESS]', percent=60, downloaded=1_182_689_658, total=1_971_149_431,
               speed=20 * 1024 ** 2, phase='download'))
    assert '网络中断，已从断点续传（第 1 次）' in dialog.progress_status.text()
    feed('[重试] model.pt：来源暂时没有响应（network_timeout），4 秒后第 1 次重试；已下载部分保留')
    assert '来源暂时没有响应，稍后自动重试（第 2 次），已下载的部分保留' in dialog.progress_status.text()

    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='selected'))
    assert dialog._source_detail_line().endswith('全部文件已通过 SHA-256 校验，与锁定版本一致')
    dialog.deleteLater()


def test_failure_after_every_source_explains_what_the_user_can_do():
    dialog = _dialog()
    for line in (
        _line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co', attempt=1, total=2, status='trying'),
        _line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com', attempt=2, total=2, status='trying'),
        _line('[2BYTEASR_ERROR]', model='funasr_nano', phase='weights_downloading', category='network_timeout',
              detail='HF_OFFICIAL: Read timed out；HF_MIRROR: Read timed out'),
    ):
        dialog.log.appendPlainText(line)
    message = dialog._actionable_failure_message(1)
    assert 'Hugging Face 官方 → HF 镜像（可能回源官方）（已尝试备援）' in message
    assert '所有下载来源都没有连通' in message and '继续重试' in message
    assert 'HF_OFFICIAL →' not in message
    dialog.deleteLater()


def test_runtime_preparation_lines_show_what_is_happening_not_model_verification():
    dialog = _dialog()
    dialog._phase = 'tools_preparing'
    dialog._handle_progress_line('[工具] 获取固定版本 uv 0.11.7，每个来源都校验 SHA-256')
    assert dialog.progress_status.text() == '获取固定版本 uv 0.11.7，每个来源都校验 SHA-256'
    dialog._handle_progress_line('[工具] GitHub 未成功（curl exit 28）')
    assert dialog.progress_status.text() == 'GitHub 未成功（curl exit 28）'
    dialog._handle_progress_line('uv.exe SHA-256 ok')
    assert '模型文件' not in dialog.progress_status.text()
    dialog._phase = 'weights_downloading'
    dialog._handle_progress_line('SHA-256 校验中')
    assert dialog.progress_status.text() == '正在校验模型文件完整性…'
    dialog.deleteLater()


def test_downloader_per_file_lines_do_not_replace_model_level_source_or_file_count():
    # Real window, mainland run 2026-10-14: per-file events showed "HF_MIRROR" and "文件 16 / 16".
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', host='hf-mirror.com', attempt=1, total=1, status='trying',
               url='https://hf-mirror.com/FunAudioLLM/Fun-ASR-Nano-2512/resolve/x/model.pt'))
    feed(_line('[2BYTEASR_FILE]', file='model.pt', size=1_971_149_431))
    feed(_line('[2BYTEASR_PROGRESS]', percent=10, downloaded=197_114_943, total=1_971_149_431,
               speed=8 * 1024 ** 2, phase='download'))
    text = dialog.progress_status.text()
    assert '文件 9 / 10' in text
    assert '来源：HF 镜像（可能回源官方） (hf-mirror.com)  ·  第 2/2 个来源' in text
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', host='hf-mirror.com', attempt=1, total=1, status='selected',
               url='https://hf-mirror.com/FunAudioLLM/Fun-ASR-Nano-2512/resolve/x/model.pt'))
    assert 'SHA-256 校验' not in dialog._source_detail_line()  # one file done is not the whole model
    dialog.deleteLater()


def test_label_less_source_events_show_a_readable_name():
    dialog = _dialog()
    dialog._handle_progress_line(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', host='huggingface.co', attempt=1,
                                       total=1, status='trying', url='https://huggingface.co/x/resolve/r/model.pt'))
    assert 'HF_OFFICIAL' not in dialog.progress_status.text()
    assert 'Hugging Face 官方' in dialog.progress_status.text()
    dialog.deleteLater()


def test_downloader_source_line_carries_the_label():
    import importlib.util
    import io
    from contextlib import redirect_stdout
    spec = importlib.util.spec_from_file_location('dff_label', ROOT / 'scripts' / 'download_file_fast.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        module._emit_source_line('https://hf-mirror.com/a/resolve/b/c.bin', 'HF_MIRROR', 1, 1, 'trying')
    payload = json.loads(buffer.getvalue().split(' ', 1)[1])
    assert payload['label'] == 'HF 镜像（可能回源官方）' and payload['host'] == 'hf-mirror.com'


def test_reuse_note_clears_when_the_next_file_starts():
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    feed(_line('[2BYTEASR_CACHE]', file='configuration.json', bytes=398, origin='verified staging', network_bytes=0))
    assert '已沿用' in dialog._source_detail_line()
    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    assert '已沿用' not in dialog._source_detail_line()
    dialog.deleteLater()
