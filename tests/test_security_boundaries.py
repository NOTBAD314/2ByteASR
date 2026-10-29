import hashlib
import json

import pytest

from twobyteasr.glossary import domain_terms
from twobyteasr.providers.llm_config import validate_transport_url
from twobyteasr.model_integrity import ModelIntegrityError, verify_model_files


def test_model_integrity_rejects_modified_security_file(tmp_path):
    model = tmp_path / "models" / "demo"
    model.mkdir(parents=True)
    artifact = model / "model.bin"
    artifact.write_bytes(b"trusted")
    lock = {
        "schema_version": 1,
        "models": {
            "demo": {
                "path": "models/demo",
                "sha256": {"model.bin": hashlib.sha256(b"trusted").hexdigest()},
            }
        },
    }
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    assert verify_model_files("demo", root=tmp_path) == model.resolve()
    artifact.write_bytes(b"changed")
    with pytest.raises(ModelIntegrityError, match="校验失败"):
        verify_model_files("demo", root=tmp_path)


def test_model_integrity_checks_required_files_even_without_hash(tmp_path):
    model = tmp_path / "models" / "demo"
    model.mkdir(parents=True)
    lock = {
        "schema_version": 1,
        "models": {
            "demo": {
                "path": "models/demo",
                "required_files": ["runtime-required.bin"],
                "sha256": {},
            }
        },
    }
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ModelIntegrityError, match="模型必需文件缺失"):
        verify_model_files("demo", root=tmp_path)


def test_model_integrity_rejects_unknown_external_override(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('twobyteasr.runtime_paths.get_runtime_paths',lambda:SimpleNamespace(model_root=tmp_path/'models',install_root=tmp_path))
    outside = tmp_path.parent / "outside-model"
    lock = {"schema_version": 1, "models": {"demo": {"path": "models/demo", "sha256": {}}}}
    (tmp_path / "dependencies.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ModelIntegrityError, match="未知位置"):
        verify_model_files("demo", outside, root=tmp_path)


def test_transport_requires_https_except_loopback():
    validate_transport_url("https://api.example.test/v1")
    validate_transport_url("http://127.0.0.1:8000/v1")
    validate_transport_url("http://[::1]:8000/v1")
    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_transport_url("http://api.example.test/v1")


class _Response:
    def __init__(self, url, *, status=200, headers=None, chunks=()):
        self.url = url
        self.status_code = status
        self.headers = headers or {}
        self.encoding = "utf-8"
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, **_kwargs):
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def close(self):
        self.closed = True


class _Requests:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_source_verifier_checks_redirect_before_following(monkeypatch):
    requests = _Requests([_Response("https://public.example", status=302, headers={"Location": "https://127.0.0.1/private"})])
    monkeypatch.setattr(domain_terms, "_public_https_url", lambda url: "127.0.0.1" not in url)
    assert domain_terms.verify_term_source_urls("术语", ["https://public.example"], requests) == []
    assert len(requests.calls) == 1
    assert requests.calls[0][1]["allow_redirects"] is False


def test_source_verifier_stops_oversized_stream(monkeypatch):
    response = _Response(
        "https://public.example",
        chunks=[b"x" * 1_000_000, "术语".encode("utf-8") + b"x" * 600_000],
    )
    requests = _Requests([response])
    monkeypatch.setattr(domain_terms, "_public_https_url", lambda _url: True)
    assert domain_terms.verify_term_source_urls("术语", ["https://public.example"], requests) == []
    assert response.closed
