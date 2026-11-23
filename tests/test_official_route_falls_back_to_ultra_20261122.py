"""GitCode #2 follow-up (2026-11-22): settings still on 'official-v1' with only Ultra installed.

Install and repair download Ultra for the qwen_aligner key, and the profile
moves to 'ultra-v5' only on the launch after an Ultra proof. Until then a task
asked for the official 0.6B folder and stopped with path_mismatch.
"""
import pytest

from twobyteasr.recognition import alignment_backend
from twobyteasr.recognition.alignment_backend import selected_backend

OFFICIAL = {'models': {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'official-v1'}}


@pytest.fixture
def folders(monkeypatch, tmp_path):
    present = {}
    monkeypatch.setattr(alignment_backend, 'model_directory',
                        lambda backend=None: present.get('ultra' if backend in alignment_backend.ULTRA_ALIGNERS else 'official', ''))
    monkeypatch.delenv('2BYTEASR_QWEN3_ALIGNER_DIR', raising=False)
    return present


def test_only_ultra_installed_runs_ultra(folders):
    folders['ultra'] = 'models/Qwen3-ForcedAligner-Ultra'
    assert selected_backend(OFFICIAL) == 'qwen_ultra_aligner'
    assert selected_backend({'models': {'firered_asr_backend': 'qwen_aligner'}}) == 'qwen_ultra_aligner'
    head = {'models': dict(OFFICIAL['models'], qwen_alignment_head=True)}
    assert selected_backend(head) == 'qwen_ultra_head'
    from twobyteasr.app.ui import required_recognition_model_keys
    assert required_recognition_model_keys(OFFICIAL) == ('qwen_ultra_aligner',)


def test_official_folder_or_custom_path_keeps_the_official_route(folders, monkeypatch):
    folders.update(official='models/Qwen3-ForcedAligner-0.6B', ultra='models/Qwen3-ForcedAligner-Ultra')
    assert selected_backend(OFFICIAL) == 'qwen_aligner'
    folders.pop('official')
    monkeypatch.setenv('2BYTEASR_QWEN3_ALIGNER_DIR', 'D:/my-aligner')
    assert selected_backend(OFFICIAL) == 'qwen_aligner'


def test_nothing_installed_still_reports_the_official_route(folders):
    # No Ultra either: keep the saved route, so the preflight's missing-model
    # message names what the settings ask for.
    assert selected_backend(OFFICIAL) == 'qwen_aligner'
