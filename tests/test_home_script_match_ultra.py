"""匹配文稿 accepts an Ultra-only Qwen3 aligner install (2026-11-26)."""
from __future__ import annotations

import sys

from twobyteasr.app import home_script_match as hsm


def _patch(monkeypatch, installed, aligner_dir, backend='qwen_ultra_aligner'):
    import twobyteasr.local_models.model_registry as registry
    import twobyteasr.recognition.asr as asr
    monkeypatch.setattr(registry, 'installed_model_keys', lambda *a, **k: set(installed))
    monkeypatch.setattr(asr, 'resolve_qwen_aligner_local_source', lambda: aligner_dir)
    monkeypatch.setattr(asr, 'selected_qwen_aligner_backend', lambda: backend)
    monkeypatch.setattr(asr, '_main_worker_python', lambda: sys.executable)


def test_ultra_only_install_is_ready(monkeypatch):
    # The official 0.6B folder was retired; only Ultra is on disk.
    _patch(monkeypatch, {'qwen_asr', 'qwen_ultra_aligner'}, 'C:/models/Qwen3-ForcedAligner-Ultra')
    assert hsm.timestamp_model_ready('en') == (True, '')
    assert hsm.qwen_aligner_label() == 'Qwen3 对齐 · Ultra'


def test_missing_aligner_names_the_selected_route(monkeypatch):
    _patch(monkeypatch, {'qwen_asr'}, '')
    ready, reason = hsm.timestamp_model_ready('ja')
    assert not ready
    assert 'Ultra' in reason and 'ForcedAligner 0.6B' not in reason


def test_missing_asr_still_reported(monkeypatch):
    _patch(monkeypatch, {'qwen_ultra_aligner'}, 'C:/models/ultra')
    ready, reason = hsm.timestamp_model_ready('en')
    assert not ready and hsm.QWEN_ASR_MODEL in reason
