"""Change Group 2：下载源可靠性回归测试。

覆盖产品不变量（先写测试，再实现）：
- 仅四个用户源：AUTO / MODELSCOPE / HF_MIRROR / HF_OFFICIAL
- 解析器产出真实 URL 与 hostname，而不是只改标签
- AUTO：仅当 lock 声明 ModelScope 仓库时才试 ModelScope；否则确定性跳过
- AUTO 顺序：ModelScope → HF 国内镜像 → HF 官方
- 显式源不得静默换源
- 续传同一产物；换源不得把残缺/错源当分片复用；不删可续传分片
- 用户错误含源/主机、失败类别、下一步；版本 URL 只进详情
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "dependencies.lock.json"
DOWNLOADER = PROJECT_ROOT / "scripts" / "download_file_fast.py"
WORKSHOP = PROJECT_ROOT / "twobyteasr" / "model_workshop.py"
DOWNLOAD_PS1 = PROJECT_ROOT / "scripts" / "download_models.ps1"

import twobyteasr.download_sources as sources

PAYLOAD = bytes(range(256)) * 8
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def lock():
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def test_canonical_modes_are_exactly_four():
    assert sources.SOURCE_MODES == ("AUTO", "MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL")
    labels = sources.user_facing_source_choices()
    assert [item["mode"] for item in labels] == list(sources.SOURCE_MODES)
    joined = " ".join(item["label"] for item in labels)
    assert "http" not in joined.lower()
    assert "modelscope.cn" not in joined
    assert "hf-mirror.com" not in joined
    assert "huggingface.co" not in joined


def test_legacy_aliases_normalize_to_canonical_modes():
    assert sources.normalize_source_mode("Auto") == "AUTO"
    assert sources.normalize_source_mode("ModelScope") == "MODELSCOPE"
    assert sources.normalize_source_mode("HfMirror") == "HF_MIRROR"
    assert sources.normalize_source_mode("HuggingFace") == "HF_OFFICIAL"
    assert sources.normalize_source_mode("auto") == "AUTO"
    with pytest.raises(sources.UnknownSourceModeError):
        sources.normalize_source_mode("Fastest")
    with pytest.raises(sources.UnknownSourceModeError):
        sources.normalize_source_mode("Aliyun")


def test_modelscope_availability_follows_lock(lock):
    assert sources.modelscope_declared(lock["models"]["moss"]) is True
    assert sources.modelscope_declared(lock["models"]["whisper_turbo"]) is True
    assert sources.modelscope_declared(lock["models"]["paraformer"]) is True


def test_resolve_moss_urls_and_hosts_per_mode(lock):
    spec = lock["models"]["moss"]
    artifact = "model-00000-of-00001.safetensors"

    ms = sources.resolve_artifact("moss", artifact, spec, "MODELSCOPE")
    assert len(ms) == 1
    assert ms[0].mode == "MODELSCOPE"
    assert ms[0].host == "modelscope.cn"
    assert ms[0].url.startswith(
        "https://modelscope.cn/api/v1/models/openmoss/MOSS-Transcribe-Diarize/repo?"
    )
    assert "FilePath=model-00000-of-00001.safetensors" in ms[0].url
    assert "Revision=" + spec['modelscope_revision'] in ms[0].url

    mirror = sources.resolve_artifact("moss", artifact, spec, "HF_MIRROR")
    assert len(mirror) == 1
    assert mirror[0].host == "hf-mirror.com"
    assert (
        mirror[0].url
        == "https://hf-mirror.com/OpenMOSS-Team/MOSS-Transcribe-Diarize/resolve/"
        "e6d68cdfcddbdad1a7e8454f0cb859cad76e2502/model-00000-of-00001.safetensors"
    )

    official = sources.resolve_artifact("moss", artifact, spec, "HF_OFFICIAL")
    assert len(official) == 1
    assert official[0].host == "huggingface.co"
    assert official[0].url.startswith("https://huggingface.co/OpenMOSS-Team/")
    assert "/resolve/" in official[0].url


def test_auto_sequence_prefers_modelscope_when_declared(lock):
    whisper = sources.resolve_artifact(
        "whisper_turbo",
        "model.safetensors",
        lock["models"]["whisper_turbo"],
        "AUTO",
    )
    assert [item.mode for item in whisper] == ["MODELSCOPE", "HF_OFFICIAL"]
    assert whisper[0].host == "modelscope.cn"

    moss = sources.resolve_artifact(
        "moss",
        "config.json",
        lock["models"]["moss"],
        "AUTO",
    )
    assert [item.mode for item in moss] == ["MODELSCOPE", "HF_OFFICIAL"]
    assert moss[0].host == "modelscope.cn"


def test_repository_downloader_uses_direct_http_without_modelscope_sdk():
    source = (PROJECT_ROOT / "twobyteasr" / "repository_download.py").read_text(
        encoding="utf-8"
    )
    assert "modelscope.hub" not in source
    assert "hf_hub_download" not in source
    assert "download_file_fast.py" in source
    assert "api/v1/models" in source


def test_large_downloader_retries_only_once():
    source = (PROJECT_ROOT / "scripts" / "download_file_fast.py").read_text(
        encoding="utf-8"
    )
    assert "RETRIES = 2" in source


def test_explicit_modelscope_does_not_add_hf_urls(lock):
    resolved = sources.resolve_artifact(
        "moss", "config.json", lock["models"]["moss"], "MODELSCOPE"
    )
    assert [item.host for item in resolved] == ["modelscope.cn"]


def test_explicit_modelscope_unavailable_is_fail_closed():
    spec_without_modelscope = {
        "repository": "official/demo",
        "revision": "abc123",
    }
    with pytest.raises(sources.SourceUnavailableError) as caught:
        sources.resolve_artifact(
            "demo",
            "model.safetensors",
            spec_without_modelscope,
            "MODELSCOPE",
        )
    error = sources.user_facing_error(caught.value)
    assert error.source_mode == "MODELSCOPE"
    assert error.category == "source_unavailable"
    assert "ModelScope" in error.message
    assert "换源" in error.next_action or "更换下载源" in error.next_action
    assert "huggingface.co" not in error.message


def test_user_facing_error_hides_urls_and_names_recovery():
    error = sources.user_facing_error(
        sources.DownloadSourceError(
            category="network_timeout",
            source_mode="HF_MIRROR",
            host="hf-mirror.com",
            detail="ReadTimeout after 300s on https://hf-mirror.com/org/model/resolve/x",
        )
    )
    assert error.message.startswith("HF 镜像（可能回源官方）")
    assert "hf-mirror.com" in error.message
    assert "https://" not in error.message
    assert error.next_action
    assert "https://" in error.details
    assert error.category == "network_timeout"


@pytest.mark.parametrize(
    "text,category",
    [
        ("404 Client Error: Not Found", "source_unavailable"),
        ("ReadTimeout", "network_timeout"),
        ("Connection reset", "network_timeout"),
        ("403 Forbidden", "http_access"),
        ("SHA-256 不匹配", "checksum"),
        ("磁盘空间不足", "disk"),
        ("下载已暂停", "cancelled"),
    ],
)
def test_classify_download_error(text, category):
    assert sources.classify_error_text(text) == category


def test_workshop_dropdown_uses_canonical_modes_without_url_wall():
    text = WORKSHOP.read_text(encoding="utf-8")
    assert "SOURCE_MODES" in text or "user_facing_source_choices" in text
    assert "source_combo" in text
    assert 'self.source_combo.addItem(choice["label"], choice["mode"])' in text
    assert "HfMirror" not in text
    assert "HuggingFace" not in text or "Hugging Face" in text
    ps1 = DOWNLOAD_PS1.read_text(encoding="utf-8-sig")
    assert "AUTO" in ps1 and "MODELSCOPE" in ps1
    assert "HF_MIRROR" in ps1 and "HF_OFFICIAL" in ps1


def test_powershell_calls_python_resolver_not_inline_url_guess():
    ps1 = DOWNLOAD_PS1.read_text(encoding="utf-8-sig")
    assert "download_sources" in ps1
    assert "-m twobyteasr.download_sources" in ps1 or "resolve_from_lock" in ps1


class _FailThenOkHandler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        type(self).hits.append(parsed.path)
        range_header = self.headers.get("Range", "")
        if parsed.path.startswith("/gone"):
            self.send_response(404)
            self.end_headers()
            return
        body = PAYLOAD
        if range_header.startswith("bytes="):
            start_text, end_text = range_header[6:].split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(PAYLOAD) - 1
            end = min(end, len(PAYLOAD) - 1)
            chunk = PAYLOAD[start : end + 1]
            self.send_response(200)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _run_downloader(urls, output: Path, extra=None):
    command = [sys.executable, str(DOWNLOADER)]
    for url in urls:
        command.extend(["--url", url])
    command.extend(["--out", str(output), "--sha256", PAYLOAD_SHA, "--threads", "4", "--min-parallel-size", "0"])
    if extra:
        command.extend(extra)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_auto_sequential_fallback_skips_unavailable_and_keeps_partials(tmp_path):
    _FailThenOkHandler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FailThenOkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        output = tmp_path / "auto.bin"
        # Seed a partial that belongs to the failing host so fallback must not
        # treat it as the successful artifact.
        (tmp_path / "auto.bin.part.gone_host.000").write_bytes(b"not-complete")
        result = _run_downloader(
            [
                f"http://127.0.0.1:{port}/gone/payload.bin",
                f"http://127.0.0.1:{port}/ok/payload.bin",
            ],
            output,
            extra=["--source-mode", "AUTO"],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == PAYLOAD
    assert any("/gone/" in path for path in _FailThenOkHandler.hits)
    assert any("/ok/" in path for path in _FailThenOkHandler.hits)
    assert "[2BYTEASR_SOURCE]" in result.stdout
    assert "source_unavailable" in result.stdout or "404" in result.stdout + result.stderr
    assert (tmp_path / "auto.bin.part.gone_host.000").is_file()
    assert "择源" not in result.stdout or "并行测速" not in result.stdout


def test_explicit_mode_does_not_try_next_url(tmp_path):
    _FailThenOkHandler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FailThenOkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        output = tmp_path / "explicit.bin"
        result = _run_downloader(
            [
                f"http://127.0.0.1:{port}/gone/payload.bin",
                f"http://127.0.0.1:{port}/ok/payload.bin",
            ],
            output,
            extra=["--source-mode", "MODELSCOPE"],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode != 0
    assert not output.exists()
    assert any("/gone/" in path for path in _FailThenOkHandler.hits)
    assert not any("/ok/" in path for path in _FailThenOkHandler.hits)
    assert "source_unavailable=source_unavailable" in result.stdout


def test_unsigned_legacy_part_is_not_spliced_into_locked_artifact(tmp_path):
    class RangeHandler(BaseHTTPRequestHandler):
        requests: list[str] = []

        def do_GET(self):  # noqa: N802
            range_header = self.headers.get("Range", "")
            type(self).requests.append(range_header)
            start = 0
            end = len(PAYLOAD) - 1
            if range_header.startswith("bytes="):
                start_text, end_text = range_header[6:].split("-", 1)
                start = int(start_text)
                end = int(end_text) if end_text else end
            chunk = PAYLOAD[start : end + 1]
            self.send_response(200)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
            self.end_headers()
            self.wfile.write(chunk)

        def log_message(self, *_args):
            pass

    RangeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "resume.bin"
        output.with_name("resume.bin.part.000").write_bytes(PAYLOAD[:512])
        result = _run_downloader(
            [f"http://127.0.0.1:{server.server_port}/resume.bin"],
            output,
            extra=["--source-mode", "HF_MIRROR"],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == PAYLOAD
    assert "bytes=0-511" in RangeHandler.requests
    assert output.with_name('resume.bin.part.000').read_bytes() == PAYLOAD[:512]


def test_wrong_size_file_is_not_treated_as_complete(tmp_path):
    output = tmp_path / "wrong.bin"
    output.write_bytes(b"too-small")
    meta = output.with_name("wrong.bin.download.json")
    meta.write_text(
        json.dumps(
            {
                "source_mode": "HF_OFFICIAL",
                "host": "huggingface.co",
                "size": len(PAYLOAD),
                "sha256": PAYLOAD_SHA,
            }
        ),
        encoding="utf-8",
    )
    assert sources.completed_artifact_is_valid(output, len(PAYLOAD), PAYLOAD_SHA) is False


def test_download_dialog_passes_canonical_mode(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from twobyteasr.model_workshop import MODELS, ModelDownloadDialog

    app = QApplication.instance() or QApplication([])
    model = next(item for item in MODELS if item.key == "moss")
    dialog = ModelDownloadDialog(PROJECT_ROOT, model)
    starts = []
    monkeypatch.setattr(dialog.process, "start", lambda program, args: starts.append(args))
    monkeypatch.setattr(dialog.process, "waitForStarted", lambda _timeout: True)
    labels = [dialog.source_combo.itemText(index) for index in range(dialog.source_combo.count())]
    assert "http" not in " ".join(labels).lower()
    modes = [dialog.source_combo.itemData(index) for index in range(dialog.source_combo.count())]
    assert modes == ["AUTO", "MODELSCOPE", "HF_MIRROR", "HF_OFFICIAL"]
    dialog.source_combo.setCurrentIndex(modes.index("MODELSCOPE"))
    dialog.start()
    assert starts
    args = starts[0]
    assert args[args.index("-Source") + 1] == "MODELSCOPE"
    dialog.deleteLater()
    app.processEvents()
