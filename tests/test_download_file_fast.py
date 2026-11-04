from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADER = ROOT / "scripts" / "download_file_fast.py"
PAYLOAD = bytes(range(256)) * 8
RESUME_PAYLOAD = bytes(range(256)) * (12 * 1024)


def identity_part(output, url, payload, *, chunk=None):
    # Layout version is part of the production resume identity. A fixture
    # with the old layout must not be silently reused by the new downloader.
    digest = hashlib.sha256(json.dumps([url,len(payload),hashlib.sha256(payload).hexdigest(),4,2],sort_keys=True).encode()).hexdigest()[:12]
    return output.with_name(output.name + '.part.127_0_0_1_' + digest + (f'.{chunk:03d}' if chunk is not None else ''))


class RangeHandler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        range_header = self.headers.get("Range", "")
        type(self).requests.append(range_header)
        if range_header.startswith("bytes="):
            start_text, end_text = range_header[6:].split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(PAYLOAD) - 1
            end = min(end, len(PAYLOAD) - 1)
            body = PAYLOAD[start : end + 1]
            # ModelScope's API gateway currently rewrites range responses to
            # HTTP 200 while retaining a correct Content-Range header.
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
        else:
            body = PAYLOAD
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class SlowRangeHandler(RangeHandler):
    def do_GET(self):  # noqa: N802
        time.sleep(0.25)
        super().do_GET()


class JsonRangeHandler(RangeHandler):
    def end_headers(self):
        self.send_header('Content-Type', 'application/json')
        super().end_headers()


def test_chunked_json_model_artifact_uses_original_file_type(tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), JsonRangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        output = tmp_path/'tokenizer.json'
        result = subprocess.run([sys.executable, str(DOWNLOADER), '--url',
            f'http://127.0.0.1:{server.server_port}/tokenizer.json', '--out', str(output),
            '--min-parallel-size', '0', '--sha256', hashlib.sha256(PAYLOAD).hexdigest()],
            capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_bytes() == PAYLOAD
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


class InterruptOnceRangeHandler(RangeHandler):
    interrupted = False

    def do_GET(self):  # noqa: N802
        range_header = self.headers.get("Range", "")
        type(self).requests.append(range_header)
        start_text, end_text = range_header[6:].split("-", 1)
        start = int(start_text)
        end = int(end_text)
        body = RESUME_PAYLOAD[start : end + 1]
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(RESUME_PAYLOAD)}")
        self.end_headers()
        if start == 0 and end == 0:
            self.wfile.write(body)
            return
        if not type(self).interrupted:
            type(self).interrupted = True
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(1)
            return
        self.wfile.write(body)


def test_range_downloader_reuses_completed_chunks_and_checks_hash(tmp_path):
    RangeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / 'new-manifest' / "payload.bin"
        output.parent.mkdir()
        previous = tmp_path / 'previous-manifest' / output.name
        previous.parent.mkdir()
        url = f"http://127.0.0.1:{server.server_port}/payload.bin"
        # Four threads create 512-byte chunks. Seed chunk zero to simulate an
        # interrupted previous run; it must not be requested again.
        identity_part(previous, url, PAYLOAD, chunk=0).write_bytes(PAYLOAD[:512])
        result = subprocess.run(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                f"http://127.0.0.1:{server.server_port}/payload.bin",
                "--out",
                str(output),
                "--resume-root",
                str(tmp_path),
                "--threads",
                "4",
                "--min-parallel-size",
                "0",
                "--sha256",
                hashlib.sha256(PAYLOAD).hexdigest(),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == PAYLOAD
    assert "bytes=0-511" not in RangeHandler.requests
    assert not list(tmp_path.glob("payload.bin.part.*"))
    progress_lines = [
        line.removeprefix("[2BYTEASR_PROGRESS] ")
        for line in result.stdout.splitlines()
        if line.startswith("[2BYTEASR_PROGRESS] ")
    ]
    assert progress_lines, "the GUI downloader needs machine-readable progress"
    final_progress = json.loads(progress_lines[-1])
    assert final_progress["percent"] == 100
    assert final_progress["downloaded"] == len(PAYLOAD)
    assert final_progress["total"] == len(PAYLOAD)
    assert final_progress["phase"] == "verify"


def test_range_downloader_resumes_bytes_inside_an_interrupted_chunk(tmp_path):
    InterruptOnceRangeHandler.requests = []
    InterruptOnceRangeHandler.interrupted = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), InterruptOnceRangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "resumed.bin"
        result = subprocess.run(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                f"http://127.0.0.1:{server.server_port}/resumed.bin",
                "--out",
                str(output),
                "--threads",
                "1",
                "--min-parallel-size",
                "0",
                "--sha256",
                hashlib.sha256(RESUME_PAYLOAD).hexdigest(),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == RESUME_PAYLOAD
    data_requests = [
        request for request in InterruptOnceRangeHandler.requests if request != "bytes=0-0"
    ]
    assert data_requests[0] == f"bytes=0-{len(RESUME_PAYLOAD) - 1}"
    resumed_starts = [int(request[6:].split("-", 1)[0]) for request in data_requests[1:]]
    assert any(0 < start < len(RESUME_PAYLOAD) for start in resumed_starts)


def test_modelscope_large_files_use_conservative_concurrency():
    import importlib.util

    spec = importlib.util.spec_from_file_location("download_file_fast", DOWNLOADER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    large = 4 * 1024**3
    assert module._effective_threads(16, large, "MODELSCOPE") == 4
    assert module._effective_threads(16, large, "HF_OFFICIAL") == 16
    assert module._effective_threads(16, 1024**3, "MODELSCOPE") == 16


def test_downloader_auto_tries_sources_in_listed_order(tmp_path):
    slow_server = ThreadingHTTPServer(("127.0.0.1", 0), SlowRangeHandler)
    fast_server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threads = [
        threading.Thread(target=slow_server.serve_forever, daemon=True),
        threading.Thread(target=fast_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    first_url = f"http://127.0.0.1:{slow_server.server_port}/payload.bin"
    second_url = f"http://127.0.0.1:{fast_server.server_port}/payload.bin"
    try:
        output = tmp_path / "ordered.bin"
        result = subprocess.run(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                first_url,
                "--url",
                second_url,
                "--out",
                str(output),
                "--sha256",
                hashlib.sha256(PAYLOAD).hexdigest(),
                "--source-mode",
                "AUTO",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        slow_server.shutdown()
        fast_server.shutdown()
        slow_server.server_close()
        fast_server.server_close()
        for thread in threads:
            thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == PAYLOAD
    assert "[2BYTEASR_SOURCE]" in result.stdout
    assert "并行测速" not in result.stdout
    first_pos = result.stdout.find(first_url)
    second_pos = result.stdout.find(second_url)
    assert first_pos != -1
    assert first_pos < second_pos or second_pos == -1


def test_release_lock_prefers_official_modelscope_for_available_models():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    assert lock["models"]["moss"]["modelscope_repository"] == "openmoss/MOSS-Transcribe-Diarize"
    assert lock["models"]["firered_vad"]["modelscope_repository"] == "FireRedTeam/FireRedVAD"
    assert lock["models"]["firered_aed"]["modelscope_repository"] == "FireRedTeam/FireRedASR2-AED"
    assert lock["models"]["qwen_asr"]["modelscope_repository"] == "Qwen/Qwen3-ASR-1.7B"
    assert lock["models"]["whisper_turbo"]["modelscope_repository"] == "openai-mirror/whisper-large-v3-turbo"
    assert lock["models"]["paraformer"]["modelscope_repository"].startswith("iic/speech_paraformer-")
    assert lock["models"]["glm_asr_nano"]["modelscope_repository"] == "ZhipuAI/GLM-ASR-Nano-2512"
    assert lock["models"]["canary_qwen"]["modelscope_repository"] == "nv-community/canary-qwen-2.5b"
    assert lock["models"]["omni_asr_llm_7b"]["modelscope_repository"] == "facebook/omniASR-LLM-7B"
    assert (
        lock["models"]["speaker_embedding"]["modelscope_repository"]
        == "speechbrain/spkrec-ecapa-voxceleb"
    )


def test_download_script_prioritizes_moss_primary_model():
    script = (ROOT / "scripts" / "download_models.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert 'if ($_.Name -eq "moss") { 0 } else { 1 }' in script


def test_runtime_model_dependencies_are_all_locked_and_hashed():
    import json

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    expected = {
        "firered_vad": {"VAD/model.pth.tar", "VAD/cmvn.ark"},
        "firered_aed": {"model.pth.tar", "cmvn.ark"},
        "speaker_embedding": {
            "hyperparams.yaml",
            "embedding_model.ckpt",
            "mean_var_norm_emb.ckpt",
            "classifier.ckpt",
            "label_encoder.txt",
        },
    }
    for model_name, required in expected.items():
        spec = lock["models"][model_name]
        assert required <= set(spec["required_files"])
        assert set(spec["required_files"]) <= set(spec["sha256"])


def test_single_stream_resume_accepts_modelscope_200_range_status(tmp_path):
    RangeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "stream.bin"
        identity_part(output, f"http://127.0.0.1:{server.server_port}/stream.bin", PAYLOAD).write_bytes(PAYLOAD[:700])
        result = subprocess.run(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                f"http://127.0.0.1:{server.server_port}/stream.bin",
                "--out",
                str(output),
                "--threads",
                "4",
                "--sha256",
                hashlib.sha256(PAYLOAD).hexdigest(),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_bytes() == PAYLOAD
    assert "bytes=700-" in RangeHandler.requests
