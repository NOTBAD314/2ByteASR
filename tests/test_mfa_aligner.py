"""Montreal Forced Aligner as an experimental 字幕时间轴 backend (2026-10-19)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def worker():
    spec = importlib.util.spec_from_file_location("mfa_aligner_worker_under_test", ROOT / "mfa_aligner_worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job(text, language, start=10_000, end=12_000):
    return {"id": "S01@10000-12000", "text": text, "language": language, "window_start_ms": start, "window_end_ms": end}


def _mfa(words, phones=()):
    return {"start": 0, "end": 2.0, "tiers": {"words": {"type": "interval", "entries": [list(w) for w in words]},
                                              "phones": {"type": "interval", "entries": [list(p) for p in phones]}}}


def test_chinese_words_give_per_character_times_from_tone_syllables(worker):
    # 看 / 开头 / 路面: one tone-marked phone per syllable, so two-character words split per character.
    words = [(0.13, 0.34, "看"), (0.34, 0.79, "开头"), (1.00, 1.44, "路面")]
    phones = [(0.13, 0.19, "kʰ"), (0.19, 0.30, "a˥˩"), (0.30, 0.34, "n"),
              (0.34, 0.48, "kʰ"), (0.48, 0.59, "aj˥"), (0.59, 0.68, "tʰ"), (0.68, 0.79, "ow˧˥"),
              (1.00, 1.05, "l"), (1.05, 1.24, "u˥˩"), (1.24, 1.30, "m"), (1.30, 1.44, "j̃ɛn˥˩")]
    row = worker.build_row(_job("看开头，路面", "Chinese"), _mfa(words, phones), window_ms=2000)
    assert row["status"] == "aligned" and row["mapping"] == "mfa_words"
    starts = {u["text"]: u["start_ms"] for u in row["char_units"]}
    assert starts == {"看": 10130, "开": 10340, "头": 10590, "路": 11000, "面": 11240}
    # Segments tile the visible text and only measured boundaries are offered.
    assert row["segments"][0]["char_start"] == 0 and row["segments"][-1]["char_end"] == len("看开头，路面")
    assert all(s["start_basis"] == "model" for s in row["segments"])
    assert row["char_units"] is not None and "mfa_quality" not in row


def test_unmatched_words_are_interpolated_and_offer_no_boundary(worker):
    # MFA drops an out-of-dictionary name: its span is filled between neighbours, never measured.
    words = [(0.30, 0.50, "じゃあ"), (1.20, 1.40, "っぽい")]
    row = worker.build_row(_job("じゃあミオちゃんっぽい", "Japanese"), _mfa(words), window_ms=2000)
    units = row["word_units"]
    assert [u["text"] for u in units] == ["じゃあ", "ミオちゃん", "っぽい"]
    assert units[1]["start_basis"] == units[1]["end_basis"] == "interpolated"
    assert (units[1]["start_ms"], units[1]["end_ms"]) == (10500, 11200)
    assert row["char_units"] is None  # Japanese: words only
    assert row["stats"]["interpolated_units"] == 1
    cuts = [s["char_start"] for s in row["segments"]][1:]
    assert 3 not in cuts and 8 not in cuts  # no boundary next to the guessed span


def test_window_edges_and_missing_utterances(worker):
    row = worker.build_row(_job("メガネ", "Japanese"), _mfa([(0.0, 2.0, "メガネ")]), window_ms=2000)
    assert row["word_units"][0]["start_basis"] == row["word_units"][0]["end_basis"] == "window_edge"
    assert worker.build_row(_job("メガネ", "Japanese"), None, window_ms=2000)["status"] == "not_aligned"


def test_words_match_lowercase_latin_and_skip_unknown_tokens(worker):
    matched = worker.match_words("CRPG的玩法吗", [(0, 1, "crpg"), (1, 2, "<unk>"), (2, 3, "的"), (3, 4, "玩法")])
    assert [(w[2], a, b) for w, a, b in matched] == [("crpg", 0, 3), ("的", 4, 4), ("玩法", 5, 6)]


def test_activated_environment_puts_the_conda_dll_folders_first(worker, tmp_path):
    env = worker.activated_environment(tmp_path, {"PATH": "C:/Windows", "PYTHONHOME": "x"})
    first = env["PATH"].split(os.pathsep)
    assert first[0] == str(tmp_path) and str(tmp_path / "Library/bin") in first
    assert first[-1] == "C:/Windows" and "PYTHONHOME" not in env and env["CONDA_PREFIX"] == str(tmp_path)


def test_selected_mfa_takes_chinese_and_japanese_jobs_only(monkeypatch):
    from twobyteasr.recognition import asr, mfa_aligner
    from twobyteasr.recognition.run_context import get_runtime_context
    monkeypatch.setattr(get_runtime_context(), "asr_settings_snapshot",
                        {"models": {"firered_asr_backend": "mfa_aligner"}}, raising=False)
    calls = []
    monkeypatch.setattr(mfa_aligner, "run_aligner", lambda audio, jobs, **kw: calls.append(jobs) or {"results": []})
    audio = np.zeros(16000, np.float32)
    job = {"id": "a", "window_start_ms": 0, "window_end_ms": 1000, "text": "你好"}
    assert asr.run_qwen_aligner_worker(audio, [dict(job, language="Chinese")]) == {"results": []}
    assert asr.run_qwen_aligner_worker(audio, [dict(job, language="Japanese")]) == {"results": []}
    assert len(calls) == 2
    # English stays with Qwen3: here that means the Qwen model lookup, not MFA.
    monkeypatch.setattr(asr, "resolve_qwen_aligner_local_source", lambda: None)
    with pytest.raises(asr.AlignerUnavailableError, match="Qwen3-ForcedAligner"):
        asr.run_qwen_aligner_worker(audio, [dict(job, language="English", text="hello")])
    assert len(calls) == 2


def test_missing_mfa_runtime_is_aligner_unavailable(monkeypatch):
    from twobyteasr.recognition import asr, mfa_aligner
    from twobyteasr.recognition.run_context import get_runtime_context
    monkeypatch.setattr(get_runtime_context(), "asr_settings_snapshot",
                        {"models": {"firered_asr_backend": "mfa_aligner"}}, raising=False)
    monkeypatch.setattr(mfa_aligner, "runtime_python", lambda: None)
    with pytest.raises(asr.AlignerUnavailableError, match="MFA 运行环境"):
        asr.run_qwen_aligner_worker(np.zeros(16000, np.float32), [
            {"id": "a", "window_start_ms": 0, "window_end_ms": 1000, "text": "你好", "language": "Chinese"}])


def test_language_timeline_and_host_limits():
    from twobyteasr.recognition.recognition_choices import HostProfile, language_timeline, unavailable_on_host
    ja = language_timeline("mfa_aligner", "ja", {"switches": {"use_ja_ctc_aligner": False}})
    assert ja["rerouted"] is False and ja["name"] == "MFA（实验）"
    en = language_timeline("mfa_aligner", "en", {})
    assert en["rerouted"] is True and en["name"] == "Qwen3 对齐"
    mac = HostProfile("darwin", "arm64", False, True, True)
    windows = HostProfile("win32", "x86_64", False, True, False)
    assert unavailable_on_host("timeline", "mfa_aligner", mac) == "目前只能在 Windows 上运行"
    assert unavailable_on_host("timeline", "mfa_aligner", windows) == ""  # CPU: no NVIDIA needed


def test_settings_accept_mfa_backend():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, {"models": {"firered_asr_backend": "mfa_aligner"}})
    assert merged["models"]["firered_asr_backend"] == "mfa_aligner"
    assert not [w for w in warnings if "backend" in w]


def test_workshop_card_needs_its_runtime_and_stays_usable_for_japanese(monkeypatch):
    from twobyteasr.local_models import model_workshop
    cards = {model.key: model for model in model_workshop.MODELS}
    card = cards["mfa_aligner"]
    assert card.install_keys == ("mfa_aligner", "mfa_aligner_ja") and "实验" in card.name
    page = SimpleNamespace(runtime_settings={"models": {}}, _installed={"mfa_aligner", "mfa_aligner_ja"},
                           _registry=None, _active_download_dialog=lambda key: None)
    monkeypatch.setattr(model_workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr("twobyteasr.recognition.mfa_aligner.runtime_python", lambda: None)
    assert model_workshop.ModelWorkshopPage._compute_model_state(page, card, "timeline") == "runtime_missing"
    monkeypatch.setattr(model_workshop, "_host_platform_tag", lambda: "darwin-arm64")
    assert model_workshop.ModelWorkshopPage._compute_model_state(page, card, "timeline") == "platform_unavailable"
    japanese = {"models": {"firered_asr_backend": "mfa_aligner"}, "subtitle_language": {"recognition_language": "ja"}}
    english = dict(japanese, subtitle_language={"recognition_language": "en"})
    state = model_workshop._spoken_timeline_state
    assert state(japanese, card, "timeline", "selected") == "selected"
    assert state(english, card, "timeline", "selected") == "language_unused"
    assert state(japanese, cards["qwen_aligner"], "timeline", "installed") == "installed"
    assert state(english, cards["qwen_aligner"], "timeline", "installed") == "selected"


def test_lock_pins_models_runtime_and_pip_packages():
    lock = json.loads((ROOT / "dependencies.lock.json").read_text("utf-8"))
    for key in ("mfa_aligner", "mfa_aligner_ja"):
        spec = lock["models"][key]
        assert spec["repository"].startswith("MontrealCorpusTools/") and len(spec["revision"]) == 40
        assert set(spec["required_files"]) == set(spec["sha256"]) and spec["license"] == "CC-BY-4.0"
        assert any(name.startswith("acoustic/") for name in spec["required_files"])
    assert lock["models"]["mfa_aligner_ja"]["resource_only"] is True
    env = lock["environments"]["mfa"]
    lines = (ROOT / env["explicit"]).read_text("utf-8").splitlines()
    packages = [line for line in lines if line.startswith("https://")]
    assert packages and all(line.startswith("https://conda.anaconda.org/conda-forge/") and "#" in line
                            for line in packages)
    assert any("/montreal-forced-aligner-3.4.3-" in line for line in packages)
    assert any("/kaldi-" in line and "cpu_" in line for line in packages)
    assert len(env["micromamba"]["sha256"]) == 64
    assert all(item["sha256"] for item in env["pip"].values())


def test_mfa_align_runs_isolated_from_the_program_folder(worker, monkeypatch, tmp_path):
    """The packaged app's folder holds PyInstaller's 3.10 .pyd files: -I and a neutral cwd (2026-10-19)."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    found, quality = worker.align_language([("u00000", "S01_g0", b"\0\0" * 1600, "你好")], "Chinese",
                                           tmp_path / "MFA-mandarin", tmp_path / "work", 2)
    command, kwargs = calls[0]
    assert command[1:4] == ["-I", "-m", "montreal_forced_aligner"]
    assert kwargs["cwd"] == str(tmp_path / "work")
    assert found == {} and quality == {}
