"""Generate the 简体 ⇄ 繁體 tables for recognized subtitles (2026-10-19).

Development tool only, like ``make_zh_hant.py``: it needs OpenCC
(``pip install opencc``, Apache-2.0) in the interpreter that runs it; the app
reads the generated JSON and never imports OpenCC.

Output, both UTF-8 with LF and read by ``twobyteasr/subtitle_rules/chinese_script.py``:
``twobyteasr/locales/zh-Hant-subtitles.json`` (简 → 繁, OpenCC ``s2tw``) and
``twobyteasr/locales/zh-Hans-subtitles.json`` (繁 → 简, OpenCC ``tw2s``, for the
workbench command that converts a project back; same layout, its phrases from
``TSPhrases`` and ``TWVariantsRevPhrases``):

* ``chars``   — one Simplified character → its OpenCC ``s2tw`` character;
* ``phrases`` — phrases of OpenCC's ``STPhrases`` whose ``s2tw`` result differs
  from converting them character by character (头发 → 頭髮, 之后 → 之後);
* ``same``    — the other ``STPhrases`` keys. They convert character by
  character but still take part in the longest match, as in OpenCC, so a
  shorter phrase never starts inside them (路径 must not become 路逕).

``s2tw`` changes character forms only (裡, 為, 著), never vocabulary (视频
stays 視頻), so every entry keeps its length and word timings stay valid; so
does ``tw2s``. The script checks both, and compares the app's longest match
with OpenCC: 简 → 繁 on every Chinese UI string of the repository, 繁 → 简 on
their Traditional UI translations.

Run in an environment that has ``opencc``::

    python -X utf8 scripts/make_zh_hant_subtitles.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "twobyteasr" / "locales" / "zh-Hant-subtitles.json"
PHRASE_DICTS = ("STPhrases", "STPhrases_GeneratedFromRegionalPhrases")
# 繁 → 简 (2026-10-19): the reverse table for converting a project back.
REVERSE_OUTPUT = ROOT / "twobyteasr" / "locales" / "zh-Hans-subtitles.json"
REVERSE_PHRASE_DICTS = ("TSPhrases", "TWVariantsRevPhrases")
REVERSE_CHAR_DICTS = ("TSCharacters", "TSCharactersExt", "TWVariantsRev")


def dump_dictionary(opencc_dir: Path, name: str, folder: Path) -> dict[str, list[str]]:
    """An OpenCC .ocd2 dictionary as {key: [candidates]} (via the bundled opencc_dict)."""
    target = folder / f"{name}.txt"
    subprocess.run([str(opencc_dir / "clib" / "bin" / "opencc_dict.exe"),
                    "-i", str(opencc_dir / "clib" / "share" / "opencc" / f"{name}.ocd2"),
                    "-o", str(target), "-f", "ocd2", "-t", "text"], check=True)
    rows = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            key, values = line.split("\t", 1)
            rows[key] = values.split(" ")
    return rows


def build(convert, phrase_keys, char_keys, config="s2tw") -> dict:
    chars = {}
    # The BMP ideographs plus the dictionary's own characters (Extension B and beyond).
    for ch in sorted({chr(code) for code in range(0x3400, 0xA000)} | {key for key in char_keys if len(key) == 1}):
        value = convert(ch)
        if len(value) == 1 and value != ch:
            chars[ch] = value

    def charwise(text: str) -> str:
        return "".join(chars.get(ch, ch) for ch in text)

    phrases, same = {}, []
    for key in sorted(phrase_keys):
        if len(key) < 2:
            continue
        value = convert(key)
        if len(value) != len(key):
            raise SystemExit(f"length changed by {config}: {key} -> {value}")
        if value != charwise(key):
            phrases[key] = value
        else:
            same.append(key)
    return {"chars": dict(sorted(chars.items())), "phrases": phrases, "same": same}


def compare_with_opencc(convert) -> tuple[int, int, list]:
    sys.path.insert(0, str(ROOT))
    from twobyteasr.subtitle_rules import chinese_script
    chinese_script._TABLE = None
    corpus = set(json.loads((ROOT / "twobyteasr" / "locales" / "en.json").read_text(encoding="utf-8")))
    corpus |= set(json.loads((ROOT / "twobyteasr" / "locales" / "zh-Hant-literals.json").read_text(encoding="utf-8")))
    corpus = sorted(text for text in corpus if re.search(r"[㐀-鿿]", text))
    differ = [(text, chinese_script.to_traditional(text), convert(text)) for text in corpus
              if chinese_script.to_traditional(text) != convert(text)]
    return len(corpus), len(differ), differ[:10]


def compare_reverse_with_opencc(convert) -> dict:
    """繁 → 简 against OpenCC on the Traditional UI translations; and how often 简 → 繁 → 简 returns the original."""
    sys.path.insert(0, str(ROOT))
    from twobyteasr.subtitle_rules import chinese_script
    chinese_script._TABLE = chinese_script._REVERSE = None
    locales = ROOT / "twobyteasr" / "locales"
    hans = set(json.loads((locales / "en.json").read_text(encoding="utf-8")))
    hans |= set(json.loads((locales / "zh-Hant-literals.json").read_text(encoding="utf-8")))
    hans = sorted(text for text in hans if re.search(r"[㐀-鿿]", text))
    hant = set(json.loads((locales / "zh-Hant.json").read_text(encoding="utf-8")).values())
    hant |= set(json.loads((locales / "zh-Hant-literals.json").read_text(encoding="utf-8")).values())
    hant = sorted(text for text in hant if isinstance(text, str) and re.search(r"[㐀-鿿]", text))
    differ = [(text, chinese_script.to_simplified(text), convert(text)) for text in hant
              if chinese_script.to_simplified(text) != convert(text)]
    round_trip = [(text, chinese_script.to_simplified(chinese_script.to_traditional(text))) for text in hans
                  if chinese_script.to_simplified(chinese_script.to_traditional(text)) != text]
    return {"checked_strings": len(hant), "differ_from_opencc": len(differ), "samples": differ[:10],
            "round_trip_checked": len(hans), "round_trip_changed": len(round_trip),
            "round_trip_samples": round_trip[:10]}


def write_table(path: Path, opencc, config: str, table: dict, direction: str) -> None:
    payload = {
        "about": (f"{direction} for recognized subtitles. Generated by scripts/make_zh_hant_subtitles.py "
                  f"from OpenCC (https://github.com/BYVoid/OpenCC, Apache-2.0) {config} dictionaries; "
                  "do not edit by hand."),
        "opencc": getattr(opencc, "__version__", ""),
        **table,
    }
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=False) + "\n")


def main() -> int:
    import opencc
    opencc_dir = Path(opencc.__file__).resolve().parent
    convert = opencc.OpenCC("s2tw").convert
    with tempfile.TemporaryDirectory() as folder:
        phrase_keys = set()
        for name in PHRASE_DICTS:
            phrase_keys |= set(dump_dictionary(opencc_dir, name, Path(folder)))
        char_keys = set(dump_dictionary(opencc_dir, "STCharacters", Path(folder)))
    table = build(convert, phrase_keys, char_keys)
    write_table(OUTPUT, opencc, "s2tw", table, "简体 → 繁體")
    total, differ, samples = compare_with_opencc(convert)
    print(json.dumps({"chars": len(table["chars"]), "phrases": len(table["phrases"]), "same": len(table["same"]),
                      "bytes": OUTPUT.stat().st_size, "checked_strings": total, "differ_from_opencc": differ},
                     ensure_ascii=False))
    for text, ours, theirs in samples:
        print(f"  {text[:40]!r}\n    app    {ours[:40]!r}\n    opencc {theirs[:40]!r}")
    reverse = opencc.OpenCC("tw2s").convert
    with tempfile.TemporaryDirectory() as folder:
        phrase_keys = set()
        for name in REVERSE_PHRASE_DICTS:
            phrase_keys |= set(dump_dictionary(opencc_dir, name, Path(folder)))
        char_keys = set()
        for name in REVERSE_CHAR_DICTS:
            char_keys |= set(dump_dictionary(opencc_dir, name, Path(folder)))
    table = build(reverse, phrase_keys, char_keys, "tw2s")
    write_table(REVERSE_OUTPUT, opencc, "tw2s", table, "繁體 → 简体")
    report = compare_reverse_with_opencc(reverse)
    samples, round_trip = report.pop("samples"), report.pop("round_trip_samples")
    print(json.dumps({"reverse_chars": len(table["chars"]), "reverse_phrases": len(table["phrases"]),
                      "reverse_same": len(table["same"]), "reverse_bytes": REVERSE_OUTPUT.stat().st_size, **report},
                     ensure_ascii=False))
    for text, ours, theirs in samples:
        print(f"  {text[:40]!r}\n    app    {ours[:40]!r}\n    opencc {theirs[:40]!r}")
    for text, back in round_trip:
        print(f"  round trip {text[:40]!r} -> {back[:40]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
