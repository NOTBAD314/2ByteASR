"""Isolated Montreal Forced Aligner worker (the ``mfa`` conda runtime) (2026-10-19).

Experimental 字幕时间轴 backend for Chinese and Japanese. Same manifest as
``qwen_aligner_worker.py``: each job is one text against one window of the
shared task PCM. The worker writes the windows as a small MFA corpus, runs
``montreal_forced_aligner align`` (Kaldi GMM-HMM, CPU) with the pinned MFA
3.4.3 acoustic model, dictionary and G2P of the language (Hugging Face
``MontrealCorpusTools/<language>_mfa`` folders), and turns the word and
phone tiers back into units with spans in the original text
(``twobyteasr.forced_alignment``), so the receipt rows are interchangeable
with the Qwen3 aligner's.

Words MFA did not output (or that cannot be matched to the text) become
units with interpolated times, which never offer a boundary. A Chinese
word also gets per-character times when its phones split into its
characters without doubt (``char_starts``); otherwise it stays whole. MFA
has no per-boundary posterior; its Viterbi phone boundaries count as
measured. Each row keeps MFA's raw word and phone tiers and how every
word was split (2026-10-22), so a time can be traced back to MFA.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
import wave
from pathlib import Path

PROTOCOL = "mfa-aligner-units-v1"
MODEL_KEY = "mfa_aligner"
MFA_VERSION = "3.4.3"
# language -> dictionary / G2P name in the model folder (acoustic/, dictionary/<name>.dict, g2p/<name>/)
MODEL_NAMES = {"Chinese": "mandarin_china_mfa", "Japanese": "japanese_mfa"}
MODEL_IDS = {"Chinese": "MontrealCorpusTools/mandarin_mfa (MFA 3.4.3 models)",
             "Japanese": "MontrealCorpusTools/japanese_mfa (MFA 3.4.3 models)"}


def model_paths(folder: Path, language: str) -> tuple[Path, Path, Path]:
    """(acoustic folder, dictionary file, G2P folder) of one language's model folder."""
    name = MODEL_NAMES[language]
    return folder / "acoustic", folder / "dictionary" / f"{name}.dict", folder / "g2p" / name
# A wide beam aligns every line of an anime episode where the default (10/40) drops some (2026-10-19).
BEAM, RETRY_BEAM = 100, 400
# Utterances per MFA speaker folder: real speakers are split into groups of this
# size so one long monologue still runs on several processes; fMLLR adapts per group.
GROUP_SIZE = 60
EDGE_MS = 10
TONES = frozenset("˥˦˧˨˩")
# mandarin_mfa phones (2026-10-22): ŋ and ɻ only close a syllable; n closes
# 安 and opens 难, and ɲ is n+j merged by MFA's own rules, so a lone n, n
# before a glide, or ɲ between two syllables may belong to either side.
CODA_ONLY = frozenset({"ŋ", "ɻ"})
GLIDES = frozenset({"j", "w", "ɥ"})
# Toneless vowels (neutral-tone syllables), syllabic consonants and noise:
# a syllable the tone marks cannot place.
UNTONED = frozenset({"a", "e", "i", "o", "u", "y", "ə", "aj", "ej", "aw", "ow", "z̩", "ʐ̩", "ŋ̍", "spn", "sil"})


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_MFA_ALIGNER] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def activated_environment(prefix: Path, base: dict | None = None) -> dict:
    """``conda activate`` for a Windows env: its DLL folders first on PATH (soundfile, Kaldi)."""
    env = dict(os.environ if base is None else base)
    if os.name == "nt":
        folders = [prefix, prefix / "Library/mingw-w64/bin", prefix / "Library/usr/bin", prefix / "Library/bin",
                   prefix / "Scripts", prefix / "bin"]
    else:
        folders = [prefix / "bin"]
    env["PATH"] = os.pathsep.join([str(folder) for folder in folders] + [env.get("PATH", "")])
    env["CONDA_PREFIX"] = str(prefix)
    # pkuseg's segmentation / POS models, installed by scripts/install_mfa_runtime.py
    # (otherwise it downloads them from GitHub into ~/.pkuseg on first use).
    env["PKUSEG_HOME"] = str(prefix / "share" / "pkuseg")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


# ── turning MFA tiers into units ─────────────────────────────────────────────

def _label_chars(label: str) -> str:
    from twobyteasr.forced_alignment import kept_char
    return "".join(c for c in unicodedata.normalize("NFKC", str(label)).lower() if kept_char(c))


def match_words(text: str, words: list) -> list:
    """``[(word, first content index, last content index)]`` for MFA words found in order in ``text``.

    MFA normalises words (lower case, punctuation removed); a word that does
    not fit the next few content characters (``<unk>``, ``spn``) is skipped.
    """
    from twobyteasr.forced_alignment import content_char_map
    content = [c.lower() for c, _a, _b in content_char_map(text)]
    position, out = 0, []
    for word in words:
        cleaned = _label_chars(word[2])
        if not cleaned:
            continue
        for start in range(position, min(len(content), position + 8)):
            if "".join(content[start:start + len(cleaned)]) == cleaned:
                out.append((word, start, start + len(cleaned) - 1))
                position = start + len(cleaned)
                break
    return out


def _toneless(label: str) -> str:
    return "".join(c for c in str(label) if c not in TONES)


def _rule_variants(phones: tuple, rules: list, limit: int = 32) -> set:
    """``phones`` and the variants MFA's pronunciation rules can make of it."""
    out, todo = {phones}, [phones]
    while todo and len(out) < limit:
        current = todo.pop()
        for segment, replacement in rules:
            for i in range(len(current) - len(segment) + 1):
                if current[i:i + len(segment)] == segment:
                    variant = current[:i] + replacement + current[i + len(segment):]
                    if variant and variant not in out:
                        out.add(variant)
                        todo.append(variant)
    return out


def load_pronunciations(dictionary: Path) -> dict:
    """``{character: {tone-free phones}}`` from the single-character entries of an MFA dictionary.

    Tones are left out because tone sandhi changes them inside words. The
    variants of the model's ``rules.yaml`` (glottal stop or ɻ dropped,
    onset and glide merged), which MFA applies while aligning, are added,
    and a final n may be ɲ: the dictionary writes the n of 阴 before 影 that
    way (阴影 ``i ɲ i ŋ``). ``_dictionary_splits`` accepts that ɲ only
    before i or y; in 信仰 ``ɕ i ɲ a ŋ`` it is the n of 信 merged with the
    j of 仰, which no cut can separate.
    """
    rules = []
    rules_file = Path(dictionary).parent / "rules.yaml"
    if rules_file.is_file():
        try:
            import yaml
            data = yaml.safe_load(rules_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - without rules only exact readings match
            data = {}
        listed = list(data.get("rules") or ())
        for group in (data.get("dialects") or {}).values():
            listed.extend(group or ())
        for rule in listed:
            if rule.get("preceding_context") or rule.get("following_context"):
                continue  # none in the 3.4.3 models; never guess a context
            pair = (tuple(str(rule.get("segment") or "").split()), tuple(str(rule.get("replacement") or "").split()))
            if pair[0] and pair not in rules:
                rules.append(pair)
    found = {}
    with Path(dictionary).open(encoding="utf-8") as stream:
        for line in stream:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or len(parts[0]) != 1:
                continue
            phones = tuple(_toneless(p) for p in parts[-1].split())
            if phones:
                variants = _rule_variants(phones, rules)
                variants |= {variant[:-1] + ("ɲ",) for variant in variants if variant[-1] == "n"}
                found.setdefault(parts[0], set()).update(variants)
    return {char: frozenset(readings) for char, readings in found.items()}


def _dictionary_splits(chars: str, labels: list, pronunciations: dict, limit: int = 2) -> set:
    """Distinct ways (phone index of each later character) to read ``labels`` as the characters' readings."""
    sequence = tuple(_toneless(label) for label in labels)
    found = set()

    def walk(k, position, starts):
        if len(found) >= limit:
            return
        if k == len(chars):
            if position == len(sequence):
                found.add(tuple(starts))
            return
        for reading in pronunciations.get(chars[k], ()):
            end = position + len(reading)
            if sequence[position:end] == reading and (reading[-1] != "ɲ" or sequence[end:end + 1] in (("i",), ("y",))):
                walk(k + 1, end, (starts + [position]) if k else starts)

    walk(0, 0, [])
    return found


def _phonotactic_starts(labels: list, count: int) -> tuple:
    """Phone index of each later syllable where Mandarin syllable structure decides it, else ``(None, reason)``."""
    if any(label in UNTONED for label in labels):
        return None, "untoned_syllable"
    nuclei = [i for i, label in enumerate(labels) if any(t in label for t in TONES)]
    if len(nuclei) != count:
        return None, "syllable_count_mismatch"
    starts = []
    for left, right in zip(nuclei, nuclei[1:]):
        between = [_toneless(label) for label in labels[left + 1:right]]
        codas = 0
        while codas < len(between) and between[codas] in CODA_ONLY:
            codas += 1
        rest = between[codas:]
        if not rest:
            starts.append(right)
        elif not codas and (rest[0] == "ɲ" or rest[0] == "n" and (len(rest) == 1 or rest[1] in GLIDES)):
            return None, "coda_or_onset"
        elif not codas and rest[0] == "n":
            starts.append(left + 2)  # n closes the left syllable; the next consonant opens the right one
        else:
            starts.append(left + 1 + codas)
    return starts, "phonotactic"


def char_starts(chars: str, phones: list, pronunciations: dict | None = None) -> tuple:
    """Start time of each character of one Mandarin word from its phones, or ``(None, reason)``.

    The phones are read as the characters' own dictionary readings first;
    exactly one reading must fit. Without one (a G2P word, a reading across
    characters) the syllable structure decides where it is certain. A word
    that could be cut in more than one place stays whole (2026-10-22: the
    earlier rule treated m as a coda and ŋ as a possible onset, and cut
    2.4% of the dictionary's multi-character readings one consonant off).
    """
    labels = [str(phone[2]) for phone in phones]
    if len(chars) < 2 or len(labels) < len(chars):
        return None, "too_few_phones"
    splits = _dictionary_splits(chars, labels, pronunciations) if pronunciations else set()
    if len(splits) > 1:
        return None, "dictionary_ambiguous"
    if splits:
        indices, method = list(next(iter(splits))), "dictionary"
    else:
        indices, method = _phonotactic_starts(labels, len(chars))
        if indices is None:
            return None, method
    return [phones[0][0]] + [phones[i][0] for i in indices], method


def _raw_tier(entries) -> list:
    return [[round(float(a) * 1000), round(float(b) * 1000), str(label)] for a, b, label in entries or ()]


def build_row(row: dict, mfa: dict | None, *, window_ms: int, quality: dict | None = None,
              pronunciations: dict | None = None) -> dict:
    """Fill ``row`` (id, text, language, window_*) from one utterance's MFA JSON.

    ``pronunciations``: ``load_pronunciations`` of the Chinese dictionary.
    """
    from twobyteasr import forced_alignment as fa
    text = row["text"]
    content = fa.content_char_map(text)
    if mfa is None:
        row["status"] = "not_aligned"
        return row
    tiers = mfa.get("tiers") or {}
    words = [w for w in (tiers.get("words") or {}).get("entries") or () if str(w[2]).strip()]
    phones = list((tiers.get("phones") or {}).get("entries") or ())
    matched = match_words(text, words)
    row["mapping"] = "mfa_words"
    row["tokenizer_words"] = [str(w[2]) for w in words]
    # MFA's own output in window milliseconds, before anything is mapped or merged.
    row["mfa_raw"] = {"words": _raw_tier((tiers.get("words") or {}).get("entries")), "phones": _raw_tier(phones)}
    row["char_split"] = []  # [first char, last char, method or reason] of every multi-character Chinese word
    offset = int(row["window_start_ms"])

    def basis(ms):
        return "window_edge" if ms <= EDGE_MS or ms >= window_ms - EDGE_MS else "model"

    def unit(first, last, kind, index):
        span = content[first:last + 1]
        return fa.AlignUnit("".join(c for c, _a, _b in span), span[0][1], span[-1][2], kind, index)

    def kind_of(chars):
        return ("number" if chars.isdigit() else "latin" if chars.isascii() and chars.isalpha() else "word")

    # Word units over the whole text: matched words, and the unmatched runs between them.
    plan, cursor = [], 0
    for word, first, last in matched:
        if first > cursor:
            plan.append((None, cursor, first - 1))
        plan.append((word, first, last))
        cursor = last + 1
    if cursor < len(content):
        plan.append((None, cursor, len(content) - 1))
    word_timed, char_timed = [], []
    for index, (word, first, last) in enumerate(plan):
        base = unit(first, last, kind_of("".join(c for c, _a, _b in content[first:last + 1])), index)
        if word is not None:
            a, b = round(float(word[0]) * 1000), round(float(word[1]) * 1000)
            start_basis, end_basis = basis(a), basis(b)
        else:  # interpolated between neighbours: never a measured boundary
            previous = next((p for p in reversed(plan[:index]) if p[0] is not None), None)
            following = next((p for p in plan[index + 1:] if p[0] is not None), None)
            a = round(float(previous[0][1]) * 1000) if previous else 0
            b = round(float(following[0][0]) * 1000) if following else window_ms
            b = max(a, b)
            start_basis = end_basis = "interpolated"
        word_timed.append(fa.TimedUnit(base.text, base.char_start, base.char_end, base.kind, index, a, b,
                                       a + offset, b + offset, start_basis, end_basis, 1.0, 1.0, 1.0, 1.0))
        chars = last - first + 1
        if word is not None and row.get("language") == "Chinese" and chars > 1 and base.kind == "word":
            inside = [p for p in phones if float(p[0]) >= float(word[0]) - 1e-6 and float(p[1]) <= float(word[1]) + 1e-6]
            starts, method = char_starts(_label_chars(word[2]), inside, pronunciations)
            row["char_split"].append([first, last, method])
            if starts is not None and len(starts) == chars:
                for k in range(chars):
                    ca = round(float(starts[k]) * 1000)
                    cb = round(float(starts[k + 1]) * 1000) if k + 1 < chars else b
                    piece = unit(first + k, first + k, "char", index)
                    char_timed.append(fa.TimedUnit(piece.text, piece.char_start, piece.char_end, "char", index, ca, cb,
                                                   ca + offset, cb + offset, start_basis if k == 0 else "model",
                                                   end_basis if k + 1 == chars else "model", 1.0, 1.0, 1.0, 1.0))
                continue
        char_timed.append(word_timed[-1])
    chinese = row.get("language") == "Chinese"
    segments, stats = fa.reliable_segments(word_timed, char_timed if chinese else None)
    stats["mfa_words"] = len(words)
    stats["mfa_words_unmatched"] = len(words) - len(matched)
    stats["interpolated_units"] = sum(1 for word, _f, _l in plan if word is None)
    if chinese:
        methods = [method for _first, _last, method in row["char_split"]]
        stats["char_split_dictionary"] = methods.count("dictionary")
        stats["char_split_phonotactic"] = methods.count("phonotactic")
        stats["char_split_kept_whole"] = len(methods) - stats["char_split_dictionary"] - stats["char_split_phonotactic"]
    if quality:  # MFA's own per-line scores; kept out of ``stats``, which receipts sum
        row["mfa_quality"] = quality
    row["status"] = "aligned"
    row["word_units"] = fa.unit_rows(word_timed)
    row["char_units"] = fa.unit_rows(char_timed) if chinese else None
    row["segments"] = fa.unit_rows(fa.cover_display_span(text, segments))
    row["stats"] = stats
    return row


# ── running MFA ──────────────────────────────────────────────────────────────

def _speaker_folder(job: dict) -> str:
    speaker = str(job.get("speaker") or "")
    if not speaker and "@" in str(job["id"]):
        speaker = str(job["id"]).split("@", 1)[0]
    cleaned = "".join(c if c.isalnum() else "_" for c in speaker)[:32]
    return cleaned or "S00"


def _quality(path: Path) -> dict:
    out = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as stream:
        for line in csv.DictReader(stream):
            values = {}
            for key in ("speech_log_likelihood", "phone_duration_deviation", "snr"):
                try:
                    values[key] = round(float(line.get(key) or "nan"), 3)
                except ValueError:
                    continue
            out[line.get("file", "")] = {k: v for k, v in values.items() if v == v}
    return out


def align_language(prepared: list, language: str, model_dir: Path, work: Path, jobs_count: int) -> tuple[dict, dict]:
    """Run MFA once for ``prepared`` = [(utterance name, folder, pcm int16 bytes, text)]."""
    acoustic, dictionary, g2p = model_paths(model_dir, language)
    corpus, output = work / "corpus", work / "out"
    for name, folder, pcm, text in prepared:
        target = corpus / folder
        target.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target / f"{name}.wav"), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(pcm)
        (target / f"{name}.lab").write_text(text, encoding="utf-8")
    env = activated_environment(Path(sys.prefix))
    env["MFA_ROOT_DIR"] = str(work / "mfa-root")
    # -I and cwd=work: the app's folder (cwd) holds PyInstaller's 3.10 .pyd files (2026-10-19).
    command = [sys.executable, "-I", "-m", "montreal_forced_aligner", "align", str(corpus), str(dictionary), str(acoustic),
               str(output), "--output_format", "json", "--clean", "--overwrite", "--quiet",
               "--num_jobs", str(jobs_count), "--g2p_model_path", str(g2p),
               "--beam", str(BEAM), "--retry_beam", str(RETRY_BEAM), "--temporary_directory", str(work / "mfa-temp")]
    result = subprocess.run(command, env=env, cwd=str(work), capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-1500:]
        raise RuntimeError(f"MFA align failed ({result.returncode}): {tail}")
    found = {}
    for path in output.rglob("*.json"):
        found[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return found, _quality(output / "alignment_analysis.csv")


def process_count(jobs: list) -> int:
    """MFA processes for these jobs (``--num_jobs``).

    2026-10-22, the user's 24-minute episode (384 utterances, 953 s of windows,
    16-core CPU): 2/4/6/8/16 processes took 74/72/80/96-101/139 s with identical
    alignments. Each process costs ~5-6 s to start while the alignment itself
    was under a minute, so sqrt(window seconds / 95) balances the two: 3 here,
    1 for a single caption, 8 only past ~1.7 hours of speech.
    """
    seconds = sum(max(0, int(job["window_end_ms"]) - int(job["window_start_ms"])) for job in jobs) / 1000
    return max(1, min(8, (os.cpu_count() or 2) - 1, round(math.sqrt(seconds / 95))))


def mfa_version() -> str:
    try:
        from importlib.metadata import version
        return version("montreal_forced_aligner")
    except Exception:
        return ""


def main() -> None:
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", action="append", default=[], help="LANGUAGE=folder, e.g. Chinese=D:/models/MFA-mandarin")
    parser.add_argument("--jobs", type=int, default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    sys.path.append(str(root))
    import numpy as np
    from twobyteasr import forced_alignment as fa

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    policy = manifest.get("policy", {})
    if policy.get("version") != PROTOCOL or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported MFA aligner protocol")
    sample_rate = int(policy.get("sample_rate", 0))
    if sample_rate != 16000:
        raise RuntimeError("Invalid MFA aligner policy")
    audio_spec = manifest.get("audio") or {}
    pcm = np.load(str(audio_spec["path"]), mmap_mode="r", allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(audio_spec["samples"]):
        raise RuntimeError("Aligner input is not the declared mono float32 PCM")
    jobs = manifest.get("jobs") or []
    if not jobs:
        raise RuntimeError("Aligner manifest is empty")
    model_dirs = {}
    for item in args.model_dir:
        language, _sep, folder = item.partition("=")
        model_dirs[language] = Path(folder)
    jobs_count = args.jobs or process_count(jobs)
    _emit("loading", python=sys.executable, models={k: str(v) for k, v in model_dirs.items()}, pid=os.getpid(), jobs=len(jobs),
          mfa_version=mfa_version(), processes=jobs_count)
    started = time.perf_counter()
    results, by_language, counts = {}, {}, {}
    for number, job in enumerate(jobs):
        text = str(job.get("text") or "")
        language = str(job.get("language") or "")
        start = max(0, int(job["window_start_ms"]) * sample_rate // 1000)
        end = min(pcm.size, int(job["window_end_ms"]) * sample_rate // 1000)
        row = {"id": job["id"], "text": text, "language": language,
               "window_start_ms": int(job["window_start_ms"]), "window_end_ms": int(job["window_end_ms"])}
        results[str(job["id"])] = row
        if language not in MODEL_NAMES or language not in model_dirs:
            row["status"] = "language_not_supported"
        elif end - start > fa.ALIGNER_MAX_SECONDS * sample_rate:
            row["status"] = "window_too_long"
        elif end - start < int(0.08 * sample_rate):
            row["status"] = "window_too_short"
        elif not fa.content_char_map(text):
            row["status"] = "no_alignable_text"
        else:
            folder = _speaker_folder(job)
            counts[folder] = counts.get(folder, 0) + 1
            group = f"{folder}_g{(counts[folder] - 1) // GROUP_SIZE}"
            clip = np.clip(np.asarray(pcm[start:end], dtype=np.float32), -1.0, 1.0)
            by_language.setdefault(language, []).append(
                (f"u{number:05d}", group, (clip * 32767.0).astype("<i2").tobytes(), text, row, end - start))
    aligned = 0
    with tempfile.TemporaryDirectory(prefix="2byteasr_mfa_") as temp:
        for language, items in by_language.items():
            for path in model_paths(model_dirs[language], language):
                if not path.exists():
                    raise RuntimeError(f"MFA model file missing: {path}")
            work = Path(temp) / language
            _emit("aligning", language=language, utterances=len(items))
            found, quality = align_language([(n, g, b, t) for n, g, b, t, _r, _s in items], language,
                                            model_dirs[language], work, jobs_count)
            readings = (load_pronunciations(model_paths(model_dirs[language], language)[1])
                        if language == "Chinese" else None)
            for name, _group, _bytes, _text, row, samples in items:
                build_row(row, found.get(name), window_ms=round(samples * 1000 / sample_rate),
                          quality=quality.get(name), pronunciations=readings)
                aligned += row.get("status") == "aligned"
            _emit("progress", language=language, aligned=sum(1 for *_x, r, _s in items if r.get("status") == "aligned"),
                  total=len(items))
    inference_ms = (time.perf_counter() - started) * 1000.0
    languages = sorted(by_language)
    _atomic_write(Path(args.output), {
        "protocol": PROTOCOL, "policy": policy, "results": [results[str(job["id"])] for job in jobs],
        "audio_sha256": audio_spec.get("sha256"), "python": sys.executable, "pid": os.getpid(),
        "device": "cpu", "backend": "mfa-kaldi-cpu", "dtype": "", "torch_version": "",
        "model": "; ".join(MODEL_IDS[language] for language in languages) or "Montreal Forced Aligner",
        "model_revision": f"montreal-forced-aligner {mfa_version() or MFA_VERSION}",
        "code": f"montreal-forced-aligner=={mfa_version() or MFA_VERSION} align --beam {BEAM} --retry_beam {RETRY_BEAM}",
        "unit_policy": "mfa-words-v2", "load_ms": 0.0, "inference_ms": round(inference_ms, 3)})
    _emit("completed", aligned=aligned, jobs=len(jobs), inference_ms=round(inference_ms, 3))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
