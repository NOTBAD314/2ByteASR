"""Generate the 繁體中文 (zh-Hant) UI catalog and tutorials from the Simplified sources (2026-10-14).

Development tool only: needs OpenCC (``pip install opencc``, Apache-2.0) in the
interpreter that runs it; the app itself never imports OpenCC.

Outputs (UTF-8, LF):

* ``twobyteasr/locales/zh-Hant.json`` — every key of ``en.json`` (the UI
  source strings, Simplified Chinese) → Traditional Chinese with Taiwan
  wording (OpenCC ``s2twp``: 設定, 影片, 軟體, 匯出, 預設 …) plus the small
  override list below. Same key order as ``en.json``.
* ``twobyteasr/locales/zh-Hant-literals.json`` — every other Chinese string
  constant in the program source (``twobyteasr/**/*.py`` and the root
  ``*.py``) whose Traditional form differs: help texts, tooltips and labels
  that have no English translation yet. Loaded only for 繁體中文.
* ``twobyteasr/locales/zh-Hant-chars.json`` — single-character fallback
  (OpenCC ``s2t`` per character) that ``i18n.translate`` uses for UI strings
  added after this catalog was generated. User content is never converted.
* ``docs/api-setup/<name>.zh-Hant.md`` — the API setup tutorials, shown in the
  dialog when the UI language is 繁體中文.

Run after adding UI strings::

    python -X utf8 scripts/make_zh_hant.py
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "twobyteasr" / "locales"
GUIDES = ROOT / "docs" / "api-setup"

# Product words where the common Taiwan UI form differs from OpenCC's choice.
OVERRIDES = (
    ("工作臺", "工作台"),
    ("質量", "品質"),
    ("後臺", "後台"),
    ("平臺", "平台"),
    ("臺式", "桌上型"),
)


def converter():
    import opencc
    phrase = opencc.OpenCC("s2twp")
    # Taiwan character forms (裡, not 裏) for the per-character fallback.
    char = opencc.OpenCC("s2tw")

    def convert(text: str) -> str:
        value = phrase.convert(text)
        for old, new in OVERRIDES:
            value = value.replace(old, new)
        return value
    return convert, char


CJK = re.compile(r"[\u3400-\u9fff]")
# Longer constants are model prompts and reference data, never UI text.
LITERAL_MAX_CHARS = 1200


def _folded(node, names: dict[str, str]):
    """The string of a constant, a module-level string name, or ``a + b`` of those."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left, names), _folded(node.right, names)
        if left is not None and right is not None:
            return left + right
    return None


def code_literals(skip: set[str]) -> list[str]:
    """Chinese string constants of the program source, minus ``skip``.

    Also folds ``CONSTANT + '…'`` concatenations (catalog help texts built from
    a shared sentence), so they get the phrase conversion, not per character.
    """
    found: set[str] = set()
    paths = [*sorted((ROOT / "twobyteasr").rglob("*.py")), *sorted(ROOT.glob("*.py"))]
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        names: dict[str, str] = {}
        for statement in tree.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 \
                    and isinstance(statement.targets[0], ast.Name):
                value = _folded(statement.value, names)
                if value is not None:
                    names[statement.targets[0].id] = value
        for node in ast.walk(tree):
            if isinstance(node, (ast.Constant, ast.BinOp)):
                value = _folded(node, names)
                if (value is not None and CJK.search(value) and len(value) <= LITERAL_MAX_CHARS
                        and value not in skip):
                    found.add(value)
    return sorted(found)


def write_json(path: Path, table: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(table, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    convert, char = converter()
    source = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    table = {key: convert(key) for key in source}
    write_json(LOCALES / "zh-Hant.json", table)
    literals = {}
    for text in code_literals(set(table)):
        value = convert(text)
        # ASCII (placeholders, URLs, punctuation) must survive unchanged.
        if value != text and re.sub(r"[^\x00-\x7f]", "", value) == re.sub(r"[^\x00-\x7f]", "", text):
            literals[text] = value
    write_json(LOCALES / "zh-Hant-literals.json", literals)
    chars = {}
    for code in range(0x3400, 0xA000):
        ch = chr(code)
        converted = char.convert(ch)
        # 台 stays 台 (the common Taiwan UI form, as in OVERRIDES).
        if len(converted) == 1 and converted != ch and ch != "台":
            chars[ch] = converted
    write_json(LOCALES / "zh-Hant-chars.json", chars)
    written = 0
    for path in sorted(GUIDES.glob("*.zh-CN.md")):
        target = path.with_name(path.name.replace(".zh-CN.md", ".zh-Hant.md"))
        text = convert(path.read_text(encoding="utf-8")).replace(".zh-CN.md", ".zh-Hant.md")
        text = ("<!-- 由 scripts/make_zh_hant.py 從簡體版自動轉換；請改簡體原文後重新產生。 -->\n" + text)
        with target.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        written += 1
    readme = GUIDES / "README.md"
    if readme.is_file():
        with (GUIDES / "README.zh-Hant.md").open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(convert(readme.read_text(encoding="utf-8")).replace(".zh-CN.md", ".zh-Hant.md"))
    print(json.dumps({"ui_strings": len(table), "code_literals": len(literals), "fallback_chars": len(chars),
                      "tutorials": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
