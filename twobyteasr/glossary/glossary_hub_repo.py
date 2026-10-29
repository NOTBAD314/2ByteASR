"""The online glossary repository: library files and the catalog (2026-10-17).

Pure standard library plus glossary_lint, so the hub repository's CI can run
a copy of this file (``tools/``) without the app.  The app reads what this
writes through glossary_hub.parse_index / parse_library.

Repository layout::

    index.json            catalog, built by build_index()
    index.json.sig        Ed25519 signature (maintainer's machine only)
    libraries/<id>.json   one library each

A library file::

    {"schema": 1, "id": "genshin-impact", "game": "原神", "title": "原神",
     "version": 3, "authors": ["…"], "license": "CC0-1.0", "note": "…",
     "updated": "2026-10-17",
     "mappings": [{"from": "福宁娜", "to": "芙宁娜", "category": "角色",
                   "verified_audio": true}, …]}
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Iterable, Mapping

try:
    from .glossary_lint import BLOCK, Finding, lint_rows
except ImportError:  # standalone copy in the hub repository
    from glossary_lint import BLOCK, Finding, lint_rows  # type: ignore[no-redef]

SCHEMA = 1
LICENSE = "CC0-1.0"
MAX_LIBRARY_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
_ROW_FIELDS = ("from", "to", "category")


# Internal category keys found in older libraries -> the label users see.
# Same table as main_ui_glossary._REFERENCE_CATEGORY_LABELS (kept here so the
# hub repository's standalone copy needs no app import).
CATEGORY_LABELS = {
    "character": "角色", "spirit": "角色", "skill": "技能", "item": "物品", "equipment": "装备",
    "material": "材料", "merchandise_name": "周边", "merchandise_term": "周边", "boss": "Boss",
    "location": "地点", "region": "地点", "mechanic": "机制", "game_mechanic": "机制",
    "game_system": "机制", "faction": "阵营", "event": "活动", "community": "玩家用语",
    "spoken_game_abbreviation": "玩家用语", "spoken_skill_abbreviation": "玩家用语",
    "game_term": "游戏术语", "game_collocation": "常用搭配", "common_collocation": "常用搭配",
    "art_term": "美术术语", "term": "术语", "currency": "货币", "other": "其他",
}


def _text(value) -> str:
    return " ".join(str(value or "").split())


def category_label(raw) -> str:
    text = _text(raw)
    return CATEGORY_LABELS.get(text.casefold(), text) or "其他"


def clean_rows(rows: Iterable) -> list[dict]:
    """from/to/category (+ verified_audio, note) only, unique, sorted."""
    clean, seen = [], set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        item = {"from": _text(row.get("from")), "to": _text(row.get("to")),
                "category": category_label(row.get("category"))}
        if not item["from"] or not item["to"] or (item["from"], item["to"]) in seen:
            continue
        seen.add((item["from"], item["to"]))
        if row.get("verified_audio") is True and item["from"] != item["to"]:
            item["verified_audio"] = True
        if _text(row.get("note")):
            item["note"] = _text(row.get("note"))[:120]
        clean.append(item)
    clean.sort(key=lambda item: (item["to"], item["from"]))
    return clean


def normalize_library(document: Mapping, *, previous: Mapping | None = None,
                      library_id: str = "", title: str = "", note: str = "",
                      today: str | None = None) -> tuple[dict, list[Finding]]:
    """A publishable library from a submission (or a seed); version bumps
    only when the rows or the description change."""
    today = today or time.strftime("%Y-%m-%d")
    library_id = library_id or _text(document.get("id"))
    if not _ID.match(library_id):
        raise ValueError(f"词库编号无效：{library_id!r}（小写字母、数字和连字符）")
    if _text(document.get("license") or LICENSE) != LICENSE:
        raise ValueError("线上词库只收 CC0-1.0 授权的词条")
    rows = clean_rows(document.get("mappings"))
    if not rows:
        raise ValueError("词库没有词条")
    authors = list(dict.fromkeys([*(previous or {}).get("authors", ()),
                                  *[_text(name)[:40] for name in document.get("authors", ()) if _text(name)]]))
    library = {
        "schema": SCHEMA,
        "id": library_id,
        "game": _text(document.get("game")) or _text((previous or {}).get("game")),
        "title": _text(title) or _text(document.get("title")) or _text((previous or {}).get("title")),
        "version": 1,
        "authors": authors,
        "license": LICENSE,
        "note": _text(note) or _text((previous or {}).get("note")) or _text(document.get("note"))[:300],
        "updated": today,
        "mappings": rows,
    }
    if not library["game"]:
        raise ValueError("词库缺少游戏名")
    library["title"] = library["title"] or library["game"]
    if previous:
        same = (previous.get("mappings") == rows and previous.get("title") == library["title"]
                and previous.get("note") == library["note"])
        library["version"] = int(previous.get("version") or 1) + (0 if same else 1)
        if same:
            library["updated"] = previous.get("updated") or today
    return library, lint_rows(rows)


def library_bytes(library: Mapping) -> bytes:
    data = (json.dumps(library, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if len(data) > MAX_LIBRARY_BYTES:
        raise ValueError("词库文件超过 2 MB")
    return data


def read_library(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def write_library(repo: Path, library: Mapping) -> Path:
    folder = repo / "libraries"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{library['id']}.json"
    path.write_bytes(library_bytes(library))
    return path


def check_library(path: Path) -> tuple[dict | None, list[str], list[Finding]]:
    """(library, errors, findings) for one file of the repository."""
    errors: list[str] = []
    try:
        library = read_library(path)
    except (OSError, ValueError) as exc:
        return None, [f"{path.name}: 无法读取：{exc}"], []
    if library.get("schema") != SCHEMA:
        errors.append(f"{path.name}: schema 必须是 {SCHEMA}")
    if library.get("id") != path.stem or not _ID.match(str(library.get("id") or "")):
        errors.append(f"{path.name}: id 必须和文件名一致，并且只用小写字母、数字和连字符")
    if library.get("license") != LICENSE:
        errors.append(f"{path.name}: license 必须是 {LICENSE}")
    if not isinstance(library.get("version"), int) or library["version"] < 1:
        errors.append(f"{path.name}: version 必须是正整数")
    if not _text(library.get("game")):
        errors.append(f"{path.name}: 缺少 game")
    rows = library.get("mappings")
    if not isinstance(rows, list) or not rows:
        errors.append(f"{path.name}: 没有词条")
        rows = []
    if clean_rows(rows) != rows:
        errors.append(f"{path.name}: 词条格式不规范（重复、空白或顺序），请用 scripts/glossary_hub.py add 生成")
    if path.stat().st_size > MAX_LIBRARY_BYTES:
        errors.append(f"{path.name}: 超过 2 MB")
    findings = lint_rows(rows)
    errors += [f"{path.name}: {item.source} → {item.target}：{item.message}"
               for item in findings if item.level == BLOCK]
    return library, errors, findings


def build_index(repo: Path, *, previous: Mapping | None = None, today: str | None = None) -> bytes:
    """The catalog for every library file; serial grows when anything changed."""
    today = today or time.strftime("%Y-%m-%d")
    entries = []
    for path in sorted((repo / "libraries").glob("*.json")):
        library, errors, _findings = check_library(path)
        if errors:
            raise ValueError("\n".join(errors))
        data = path.read_bytes()
        entries.append({
            "id": library["id"], "game": library["game"], "title": library.get("title") or library["game"],
            "version": library["version"], "rows": len(library["mappings"]),
            "aliases": sum(1 for row in library["mappings"] if row["from"] != row["to"]),
            "path": f"libraries/{path.name}", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "license": library["license"], "authors": library.get("authors", []),
            "note": library.get("note", ""), "updated": library.get("updated", today),
        })
    previous_entries = list((previous or {}).get("libraries", ()))
    serial = int((previous or {}).get("serial") or 0)
    if entries != previous_entries:
        serial += 1
    document = {"schema": SCHEMA, "serial": serial,
                "generated": today if entries != previous_entries else (previous or {}).get("generated", today),
                "license": LICENSE, "libraries": entries}
    return (json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def check_repo(repo: Path) -> list[str]:
    """Errors that must stop a merge: bad files, or an index that does not match them."""
    errors: list[str] = []
    for path in sorted((repo / "libraries").glob("*.json")):
        errors += check_library(path)[1]
    index_path = repo / "index.json"
    if index_path.is_file() and not errors:
        index = json.loads(index_path.read_text("utf-8"))
        listed = {entry["path"]: entry for entry in index.get("libraries", ())}
        files = {f"libraries/{path.name}": path for path in (repo / "libraries").glob("*.json")}
        for name, path in files.items():
            entry = listed.get(name)
            if entry is None:
                errors.append(f"index.json 没有列出 {name}（合并后由维护者重新生成并签名）")
            elif entry.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
                errors.append(f"index.json 里 {name} 的哈希过期（合并后由维护者重新生成并签名）")
        for name in set(listed) - set(files):
            errors.append(f"index.json 列出了不存在的 {name}")
    return errors
