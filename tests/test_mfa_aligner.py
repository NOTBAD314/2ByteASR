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


def test_process_count_follows_the_amount_of_audio(worker, monkeypatch):
    # 2026-10-22: 8 processes took 96-101 s on a 24-minute episode, 3-4 took ~72 s (same alignments).
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 32)
    windows = lambda seconds: [{"window_start_ms": 0, "window_end_ms": seconds * 1000}]
    assert worker.process_count(windows(5)) == 1           # one caption re-aligned in Studio
    assert worker.process_count(windows(953)) == 3         # the user's episode
    assert worker.process_count(windows(6 * 3600)) == 8    # long streams keep the old ceiling
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 4)
    assert worker.process_count(windows(6 * 3600)) == 3


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


MINI_DICT = {"上": "ʂ a˥˩ ŋ", "午": "u˨˩˦", "下": "ɕ a˥˩", "面": "m j e˥˩ n", "万": "w a˥˩ n", "物": "u˥˩",
             "晚": "w a˨˩˦ n", "安": "ʔ a˥ n", "阳": "j a˧˥ ŋ", "好": "x aw˨˩˦", "了": "l ə",
             "阴": "i˥ n", "影": "i˨˩˦ ŋ", "信": "ɕ i˥˩ n", "仰": "j a˨˩˦ ŋ|ʔ a˧˥ ŋ"}
MINI_RULES = """dialects:
  china:
  - {segment: ʔ, replacement: '', preceding_context: '', following_context: '', probability: 0.3}
  - {segment: n j, replacement: ɲ, preceding_context: '', following_context: '', probability: 0.09}
"""


def _phones(labels):
    return [(i / 10, (i + 1) / 10, label) for i, label in enumerate(labels.split())]


@pytest.fixture()
def readings(worker, tmp_path):
    folder = tmp_path / "dictionary"
    folder.mkdir()
    (folder / "mandarin_china_mfa.dict").write_text(
        "".join(f"{char}\t0.99\t0.1\t1.0\t1.0\t{phones}\n" for char, readings in MINI_DICT.items()
                for phones in readings.split("|"))
        + "上午\t0.99\t0.1\t1.0\t1.0\tʂ a˥˩ ŋ u˨˩˦\n", encoding="utf-8")
    (folder / "rules.yaml").write_text(MINI_RULES, encoding="utf-8")
    return worker.load_pronunciations(folder / "mandarin_china_mfa.dict")


@pytest.mark.parametrize("word, labels, with_dictionary, without_dictionary", [
    # 2026-10-22: the old rule gave 午 the ŋ of 上 and 下 the m of 面.
    ("上午", "ʂ a˥˩ ŋ u˨˩˦", [0, 3], [0, 3]),
    ("下面", "ɕ a˥˩ m j e˥˩ n", [0, 2], [0, 2]),
    # A lone n closes 万 here, but would open 怒 in 大怒: only the dictionary can tell.
    ("万物", "w a˥˩ n u˥˩", [0, 3], "coda_or_onset"),
    # MFA's rules drop the glottal stop of 安.
    ("晚安", "w a˨˩˦ n a˥ n", [0, 3], "coda_or_onset"),
    # n+j merged into one phone across the two characters: no place to cut,
    # even where the second character also has a reading without the j.
    ("安阳", "ʔ a˥ ɲ a˧˥ ŋ", "coda_or_onset", "coda_or_onset"),
    ("信仰", "ɕ i˥˩ ɲ a˨˩˦ ŋ", "coda_or_onset", "coda_or_onset"),
    # The dictionary writes the n of 阴 as ɲ before 影.
    ("阴影", "i˥ ɲ i˨˩˦ ŋ", [0, 2], "coda_or_onset"),
    # A neutral-tone syllable has no tone mark; the dictionary still finds it.
    ("好了", "x aw˨˩˦ l ə", [0, 2], "untoned_syllable"),
])
def test_chinese_character_cuts_come_from_the_dictionary_or_certain_syllable_rules(
        worker, readings, word, labels, with_dictionary, without_dictionary):
    phones = _phones(labels)
    for pronunciations, expected in ((readings, with_dictionary), (None, without_dictionary)):
        starts, method = worker.char_starts(word, phones, pronunciations)
        if isinstance(expected, str):
            assert (starts, method) == (None, expected)
        else:
            assert starts == [phones[i][0] for i in expected]
            assert method == ("dictionary" if pronunciations else "phonotactic")


def test_rows_keep_raw_mfa_tiers_and_doubtful_words_whole(worker):
    words = [(0.10, 0.50, "万物"), (0.50, 0.90, "上午")]
    phones = [(0.10, 0.20, "w"), (0.20, 0.32, "a˥˩"), (0.32, 0.38, "n"), (0.38, 0.50, "u˥˩"),
              (0.50, 0.60, "ʂ"), (0.60, 0.72, "a˥˩"), (0.72, 0.78, "ŋ"), (0.78, 0.90, "u˨˩˦")]
    row = worker.build_row(_job("万物上午", "Chinese"), _mfa([(0.0, 0.1, ""), *words], phones), window_ms=2000)
    assert row["mfa_raw"]["words"][0] == [0, 100, ""] and row["mfa_raw"]["phones"][2] == [320, 380, "n"]
    assert row["char_split"] == [[0, 1, "coda_or_onset"], [2, 3, "phonotactic"]]
    assert [u["text"] for u in row["char_units"]] == ["万物", "上", "午"]
    assert row["char_units"][2]["start_ms"] == 10780  # 午 starts after the ŋ of 上
    assert 1 not in [s["char_start"] for s in row["segments"]]  # never cut inside 万物
    assert (row["stats"]["char_split_phonotactic"], row["stats"]["char_split_kept_whole"]) == (1, 1)


def test_real_mandarin_dictionary_syllable_rules_never_contradict_it(worker):
    """Every rule cut agrees with the dictionary's own unique reading (MFA 3.4.3 model, 2026-10-22)."""
    dictionary = ROOT / "models" / "MFA-mandarin" / "dictionary" / "mandarin_china_mfa.dict"
    if not dictionary.is_file():
        pytest.skip("MFA Mandarin model not installed")
    plain, readings = {}, worker.load_pronunciations(dictionary)
    entries = []
    for line in dictionary.read_text("utf-8").splitlines():
        parts = line.split("\t")
        if len(parts[0]) == 1:
            plain.setdefault(parts[0], set()).add(tuple(worker._toneless(p) for p in parts[-1].split()))
        elif 2 <= len(parts[0]) <= 4 and all("一" <= c <= "鿿" for c in parts[0]):
            entries.append((parts[0], parts[-1].split()))
    checked = cut = 0
    for word, labels in entries:
        phones = [(i, i + 1, label) for i, label in enumerate(labels)]
        starts, _method = worker.char_starts(word, phones, readings)
        cut += starts is not None
        truth = worker._dictionary_splits(word, labels, plain)
        rule, _reason = worker._phonotactic_starts(labels, len(word))
        if len(truth) == 1:
            checked += 1
            assert rule is None or rule == list(next(iter(truth))), (word, labels)
            assert starts is None or starts[1:] == list(next(iter(truth))), (word, labels)
    assert checked > 50_000 and cut / len(entries) > 0.95


def test_aligner_receipts_are_kept_per_stage(tmp_path, monkeypatch):
    from twobyteasr.recognition import asr, timing_evidence
    payload = {"protocol": "mfa-aligner-units-v1", "results": [{
        "id": "S01@0.0-1.0", "text": "你好", "status": "aligned", "mfa_raw": {"words": [[300, 700, "你好"]], "phones": []},
        "segments": [{"char_start": 0, "char_end": 2, "start_ms": 300, "end_ms": 700,
                      "start_basis": "model", "end_basis": "model", "granularity": "word"}]}]}
    monkeypatch.setattr(asr, "run_qwen_aligner_worker", lambda audio, jobs: payload)
    events = []
    monkeypatch.setattr(asr, "record_run_event", lambda event, **data: events.append((event, data)))
    tokens = asr.transcribe_qwen_aligner_reference(np.zeros(32000, np.float32), [{"start": 0.0, "end": 1.0, "text": "你好"}],
                                                   language="Chinese", evidence_dir=tmp_path / "timing-evidence")
    assert [t["text"] for t in tokens] == ["你好"]
    saved = tmp_path / "timing-evidence" / "segments-chinese-mfa.json.gz"
    record = timing_evidence.load_receipt(saved)
    assert record["stage"] == "segments" and record["engine"] == "mfa" and record["payload"] == payload
    assert events[0][0] == "forced_alignment" and events[0][1]["evidence"] == str(saved)
    assert timing_evidence.save_aligner_payload(None, "segments", "Chinese", payload) is None


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
