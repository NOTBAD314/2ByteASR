"""Online glossary hub: browse, install, update and submit term libraries (2026-10-17).

User request (2026-10-17): users upload their own term libraries, others
download them, and it must work for users in mainland China.

How it works (ADR 0127, plan docs/exec-plans/active/2026-10-17-online-glossary-hub.md):

* The hub is a Git repository, ``2ByteASR-glossaries``: GitHub is the source,
  GitCode a mirror.  It holds ``index.json`` (the catalog), ``index.json.sig``
  (Ed25519, same format as update manifests, but a separate hub key) and
  ``libraries/<id>.json``.  There is no server, account or telemetry.
* The app asks GitCode and GitHub at the same time and keeps the first catalog
  with a valid signature (like ``updater._stable_manifest``); a mainland user
  never waits for GitHub to time out.  Library files may come from any mirror
  or proxy because their SHA-256 sits in the signed catalog.
* Installing writes ordinary rows into the user's personal library
  (``learned_game_terms.json``).  The library entry gets an optional ``hub``
  record and each installed row a ``hub`` marker, so an update replaces only
  rows that came from the hub and that the user did not edit or delete.
* Submitting exports a cleaned file and opens the hub's issue page; the
  maintainer reviews it and publishes with ``scripts/glossary_hub.py``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .glossary_lint import BLOCK, WARN, Finding, lint_rows

GITHUB_REPOSITORY = "NOTBAD314/2ByteASR-glossaries"
GITCODE_REPOSITORY = "Notbad314/2ByteASR-glossaries"
BRANCH = "main"
INDEX_NAME = "index.json"
SIGNATURE_NAME = "index.json.sig"
INDEX_SCHEMA = 1
LIBRARY_SCHEMA = 1
LICENSE = "CC0-1.0"
MAX_INDEX_BYTES = 1024 * 1024
MAX_LIBRARY_BYTES = 2 * 1024 * 1024
CHECK_INTERVAL = 24 * 3600
RACE_GRACE = 3.0
CONNECT_TIMEOUT, READ_TIMEOUT = 6, 20
GITHUB_PROXIES = ("https://ghfast.top/", "https://ghproxy.net/")
HUB_ORIGIN = "线上词库"
USER_AGENT = "2ByteASR-glossary-hub"

# Ed25519 public keys trusted for the hub catalog (key id -> raw key, base64).
# Separate from TRUSTED_UPDATE_KEYS: a mistake in the glossary repository can
# never sign a program update.  The private half lives outside the repository,
# DPAPI-protected (scripts/glossary_hub.py keygen).
TRUSTED_HUB_KEYS: dict[str, str] = {
    # 2026-10-17 hub key; private half DPAPI-protected on the maintainer's machine
    # (%USERPROFILE%\.2byteasr-release\glossary-hub-signing-key.dpapi).
    "ca0787882b1f6c4d": "6OoecPV8jDnXr7ZljQiiHNPh08cMFlmusXmrMg9dX9c=",
}

ISSUE_PAGES = {
    "github": f"https://github.com/{GITHUB_REPOSITORY}/issues/new",
    "gitcode": f"https://gitcode.com/{GITCODE_REPOSITORY}/issues",
}
HUB_PAGES = {
    "github": f"https://github.com/{GITHUB_REPOSITORY}",
    "gitcode": f"https://gitcode.com/{GITCODE_REPOSITORY}",
}

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_KEY_SEP = "→"
_PRIVATE_FIELDS = ("reason", "sources", "task_id", "updated", "provenance", "confirmed", "priority",
                   "frequency_note", "category_key", "verification", "origin", "hub", "evidence")
_AUDIO_ORIGINS = {"用户整理", "Studio 手动修改（自动记入）"}


class HubError(Exception):
    """A user-facing reason the hub could not be read or written."""


# --------------------------------------------------------------------------
# Small helpers


def _text(value) -> str:
    return " ".join(str(value or "").split())


def row_key(row: Mapping) -> str:
    return f"{_text(row.get('from'))}{_KEY_SEP}{_text(row.get('to'))}"


def _legacy(legacy=None):
    if legacy is not None:
        return legacy
    import subtitle_core
    return subtitle_core


def hub_cache_dir(legacy=None) -> Path:
    return Path(os.path.dirname(_legacy(legacy).LEARNED_TERMS_PATH)) / "glossary-hub"


def slugify(text: str) -> str:
    """A stable ASCII id; CJK names fall back to a short digest."""
    ascii_part = re.sub(r"[^a-z0-9]+", "-", _text(text).lower()).strip("-")
    if len(ascii_part) >= 2 and ascii_part.isascii():
        return ascii_part[:40]
    return "lib-" + hashlib.sha256(_text(text).encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------------------
# Catalog


def source_urls(path: str, prefer: str = "") -> list[tuple[str, str]]:
    """Every place one hub file can come from, preferred source first."""
    quoted = urllib.parse.quote(path)
    github = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/{BRANCH}/{quoted}"
    gitcode = (f"https://api.gitcode.com/api/v5/repos/{GITCODE_REPOSITORY}/raw/{quoted}"
               f"?ref={BRANCH}")
    primary = [("GitCode", gitcode), ("GitHub", github)]
    if prefer == "GitHub":
        primary.reverse()
    return primary + [("GitHub 代理", prefix + github) for prefix in GITHUB_PROXIES]


def _http_get(url: str, request_get: Callable | None):
    import requests
    getter = request_get or requests.get
    return getter(url, headers={"User-Agent": USER_AGENT}, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                  stream=False, allow_redirects=True)


def _get_bytes(url: str, request_get: Callable | None, limit: int) -> bytes:
    response = _http_get(url, request_get)
    status = int(getattr(response, "status_code", 200))
    if status >= 400:
        raise HubError(f"HTTP {status}")
    data = response.content
    if len(data) > limit:
        raise HubError("文件过大")
    return data


def verify_index(index_bytes: bytes, signature: bytes, trusted_keys: Mapping[str, str] | None = None) -> str:
    from .update_manifest import ManifestError, verify_manifest_signature
    keys = TRUSTED_HUB_KEYS if trusted_keys is None else trusted_keys
    if not keys:
        raise HubError("线上词库还没有发布")
    try:
        return verify_manifest_signature(index_bytes, signature, keys)
    except ManifestError as exc:
        raise HubError(str(exc).replace("更新清单", "线上词库目录")) from exc


def parse_index(index_bytes: bytes) -> dict:
    try:
        document = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HubError("线上词库目录无法解析") from exc
    if not isinstance(document, dict) or document.get("schema") != INDEX_SCHEMA:
        raise HubError("线上词库目录格式不受支持，请更新程序")
    libraries = document.get("libraries")
    if not isinstance(libraries, list):
        raise HubError("线上词库目录缺少词库列表")
    seen, clean = set(), []
    for entry in libraries:
        if not isinstance(entry, dict):
            raise HubError("线上词库目录有无效条目")
        library_id = str(entry.get("id") or "")
        if (not _ID.match(library_id) or library_id in seen
                or entry.get("path") != f"libraries/{library_id}.json"
                or not _SHA.match(str(entry.get("sha256") or ""))
                or not isinstance(entry.get("version"), int) or entry["version"] < 1
                or not isinstance(entry.get("size"), int) or not 0 < entry["size"] <= MAX_LIBRARY_BYTES
                or not _text(entry.get("game"))):
            raise HubError(f"线上词库目录有无效条目：{library_id or '无编号'}")
        seen.add(library_id)
        clean.append(dict(entry))
    document["libraries"] = clean
    document["serial"] = int(document.get("serial") or 0)
    return document


@dataclass
class Catalog:
    document: dict
    source: str
    fetched_at: float
    stale: bool = False
    note: str = ""

    @property
    def entries(self) -> list[dict]:
        return list(self.document.get("libraries", ()))

    def entry(self, library_id: str) -> dict | None:
        return next((row for row in self.entries if row.get("id") == library_id), None)


def _read_cache(legacy=None, trusted_keys=None) -> Catalog | None:
    folder = hub_cache_dir(legacy)
    try:
        index = (folder / INDEX_NAME).read_bytes()
        signature = (folder / SIGNATURE_NAME).read_bytes()
        state = json.loads((folder / "state.json").read_text("utf-8"))
        verify_index(index, signature, trusted_keys)
        return Catalog(parse_index(index), str(state.get("source") or ""), float(state.get("fetched_at") or 0))
    except (OSError, ValueError, TypeError, HubError):
        return None


def _write_cache(index: bytes, signature: bytes, source: str, now: float, legacy=None) -> None:
    folder = hub_cache_dir(legacy)
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in ((INDEX_NAME, index), (SIGNATURE_NAME, signature),
                       ("state.json", json.dumps({"source": source, "fetched_at": now}).encode("utf-8"))):
        temp = folder / (name + ".tmp")
        temp.write_bytes(data)
        os.replace(temp, folder / name)


def _family(label: str) -> str:
    return "GitCode" if label == "GitCode" else "GitHub"


def _fetch_signed(family: str, request_get, trusted_keys) -> tuple[str, bytes, bytes, dict]:
    """The signed catalog from one source family (GitHub falls back to its proxies)."""
    indexes = [(label, url) for label, url in source_urls(INDEX_NAME) if _family(label) == family]
    signatures = [url for label, url in source_urls(SIGNATURE_NAME) if _family(label) == family]
    errors = []
    for (label, index_url), signature_url in zip(indexes, signatures):
        try:
            index = _get_bytes(index_url, request_get, MAX_INDEX_BYTES)
            signature = _get_bytes(signature_url, request_get, 64 * 1024)
        except Exception as exc:  # noqa: BLE001 - try the next address of this source
            errors.append(f"{label} {' '.join(str(exc).split())[:80]}")
            continue
        verify_index(index, signature, trusted_keys)  # an unsigned answer never wins
        return family, index, signature, parse_index(index)
    raise HubError("；".join(errors) or "没有可用地址")


def fetch_catalog(*, request_get: Callable | None = None, force: bool = False, legacy=None,
                  trusted_keys: Mapping[str, str] | None = None, now: float | None = None,
                  grace: float = RACE_GRACE) -> Catalog:
    """The signed catalog: from the cache when it is fresh, else GitCode and
    GitHub at the same time.  Offline, the last cached catalog is kept."""
    now = time.time() if now is None else now
    keys = TRUSTED_HUB_KEYS if trusted_keys is None else trusted_keys
    if not keys:
        raise HubError("线上词库还没有发布")
    cached = _read_cache(legacy, keys)
    if cached and not force and 0 <= now - cached.fetched_at < CHECK_INTERVAL:
        return cached
    results: queue.Queue = queue.Queue()
    labels = ("GitCode", "GitHub")
    for label in labels:
        def run(label=label):
            try:
                results.put((label, _fetch_signed(label, request_get, keys), None))
            except Exception as exc:  # noqa: BLE001 - each source reports its own failure
                results.put((label, None, exc))
        threading.Thread(target=run, name=f"glossary-hub-{label}", daemon=True).start()
    best, errors, deadline = None, [], None
    for _ in labels:
        timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            label, answer, error = results.get(timeout=timeout)
        except queue.Empty:
            break
        if error is not None:
            errors.append(f"{label}：{' '.join(str(error).split())[:120]}")
            continue
        if best is None or answer[3]["serial"] > best[3]["serial"]:
            best = answer
        deadline = deadline or time.monotonic() + grace
    if best is None:
        if cached:
            cached.stale, cached.note = True, "离线，显示上次获取的目录"
            return cached
        raise HubError("无法获取线上词库目录。\n" + "\n".join(errors))
    label, index, signature, document = best
    try:
        _write_cache(index, signature, label, now, legacy)
    except OSError:
        pass
    return Catalog(document, label, now)


# --------------------------------------------------------------------------
# Library files


def parse_library(data: bytes, entry: Mapping | None = None) -> dict:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HubError("词库文件无法解析") from exc
    if not isinstance(document, dict) or document.get("schema") != LIBRARY_SCHEMA:
        raise HubError("词库文件格式不受支持，请更新程序")
    if entry is not None and document.get("id") != entry.get("id"):
        raise HubError("词库文件和目录不一致")
    rows = document.get("mappings")
    if not isinstance(rows, list):
        raise HubError("词库文件缺少词条")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source, target = _text(row.get("from")), _text(row.get("to"))
        if not source or not target:
            continue
        item = {"from": source, "to": target, "category": _text(row.get("category")) or "其他"}
        if row.get("verified_audio") is True:
            item["verified_audio"] = True
        if _text(row.get("note")):
            item["note"] = _text(row.get("note"))[:120]
        clean.append(item)
    document["mappings"] = clean
    return document


def fetch_library(entry: Mapping, catalog: Catalog | None = None, *,
                  request_get: Callable | None = None) -> dict:
    """Download one library; any mirror is fine because the hash is signed."""
    errors = []
    for label, url in source_urls(str(entry["path"]), catalog.source if catalog else ""):
        try:
            data = _get_bytes(url, request_get, MAX_LIBRARY_BYTES)
        except Exception as exc:  # noqa: BLE001 - network errors vary by stack
            errors.append(f"{label}：{' '.join(str(exc).split())[:100]}")
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            errors.append(f"{label}：内容和目录对不上")
            continue
        return parse_library(data, entry)
    raise HubError("每个来源的文件都和目录对不上，没有安装。\n" + "\n".join(errors))


# --------------------------------------------------------------------------
# Install, update, remove


def subscriptions(legacy=None, payload: Mapping | None = None) -> dict[str, tuple[str, dict]]:
    """hub id -> (library key, hub record) for every installed hub library."""
    legacy = _legacy(legacy)
    payload = payload if payload is not None else legacy.load_learned_term_payload()
    found = {}
    for key, entry in (payload.get("games") or {}).items():
        hub = entry.get("hub") if isinstance(entry, dict) else None
        if isinstance(hub, dict) and hub.get("id"):
            found[str(hub["id"])] = (str(key), hub)
    return found


def catalog_status(entry: Mapping, subs: Mapping[str, tuple[str, dict]]) -> str:
    current = subs.get(str(entry.get("id")))
    if not current:
        return "none"
    return "update" if int(current[1].get("version") or 0) < int(entry.get("version") or 0) else "installed"


def _managed(entry: Mapping) -> tuple[list[dict], list[dict], set[str]]:
    """(rows the hub still owns, rows the user edited, keys the user deleted)."""
    hub = entry.get("hub") or {}
    installed = dict(hub.get("installed") or {})
    managed, edited, present = [], [], set()
    for row in entry.get("mappings", []):
        if not isinstance(row, dict) or not str(row.get("hub") or "").startswith(f"{hub.get('id')}@"):
            continue
        key = row_key(row)
        present.add(key)
        if key in installed and _text(row.get("category")) == installed[key]:
            managed.append(row)
        else:
            edited.append(row)
    deleted = set(installed) - present
    return managed, edited, deleted


@dataclass
class PlanRow:
    row: dict
    findings: list[Finding]
    status: str          # new | same | installed | declined | conflict | blocked
    checked: bool

    @property
    def is_alias(self) -> bool:
        return self.row["from"] != self.row["to"]


@dataclass
class InstallPlan:
    entry: dict
    library: dict
    target_key: str            # "" = create a new library
    target_name: str
    updating: bool
    rows: list[PlanRow] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)   # hub rows the new version drops

    def count(self, *statuses: str) -> int:
        return sum(1 for item in self.rows if item.status in statuses)


def _same_game_keys(games: Mapping, game: str, legacy) -> list[str]:
    identity = legacy.runtime_game_identity(legacy.canonicalize_runtime_game_name(game))
    return [str(key) for key, entry in games.items() if isinstance(entry, dict)
            and legacy.runtime_game_identity(entry.get("game", "")) == identity]


def plan_install(entry: Mapping, library: Mapping, *, legacy=None, payload: Mapping | None = None) -> InstallPlan:
    """What installing (or updating to) ``library`` would do, row by row."""
    legacy = _legacy(legacy)
    payload = payload if payload is not None else legacy.load_learned_term_payload()
    games = payload.get("games") or {}
    subs = subscriptions(legacy, payload)
    hub_id = str(entry["id"])
    updating = hub_id in subs
    if updating:
        target_key = subs[hub_id][0]
    else:
        same = _same_game_keys(games, library.get("game") or entry["game"], legacy)
        target_key = same[0] if len(same) == 1 else ""
    target = games.get(target_key, {}) if target_key else {}
    target_name = _text(target.get("game")) if target else _text(library.get("game") or entry["game"])
    managed, edited, deleted = _managed(target) if updating else ([], [], set())
    managed_keys = {row_key(row) for row in managed}
    declined = set((target.get("hub") or {}).get("declined") or ()) | deleted if updating else set()
    user_rows = [row for row in target.get("mappings", []) if isinstance(row, dict)
                 and row_key(row) not in managed_keys]
    user_keys = {row_key(row) for row in user_rows}
    user_aliases = {_text(row.get("from")): _text(row.get("to")) for row in user_rows}
    rows = library.get("mappings", [])
    findings = lint_rows(rows, existing=user_rows)
    by_key: dict[str, list[Finding]] = {}
    for finding in findings:
        by_key.setdefault(f"{finding.source}{_KEY_SEP}{finding.target}", []).append(finding)
    plan = InstallPlan(dict(entry), dict(library), target_key, target_name, updating)
    seen = set()
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        found = by_key.get(key, [])
        if key in user_keys:
            status, checked = "same", False
        elif any(item.level == BLOCK for item in found):
            status, checked = ("conflict" if any(item.code in {"conflict", "chain"} for item in found)
                               else "blocked"), False
        elif user_aliases.get(row["from"], row["to"]) != row["to"]:
            status, checked = "conflict", False
        elif key in declined:
            status, checked = "declined", False
        elif key in managed_keys:
            status, checked = "installed", True
        else:
            status = "new"
            checked = row["from"] == row["to"] or not any(item.level == WARN for item in found)
        plan.rows.append(PlanRow(dict(row), found, status, checked))
    new_keys = {row_key(row) for row in rows}
    plan.removed = [row for row in managed if row_key(row) not in new_keys]
    return plan


def _installed_row(row: Mapping, entry: Mapping) -> dict:
    record = {
        "from": row["from"], "to": row["to"],
        "reason": f"线上词库《{_text(entry.get('title') or entry.get('game'))}》v{entry['version']}",
        "sources": [{"url": HUB_PAGES["github"], "title": f"{entry['id']} v{entry['version']}"}],
        "verification": "user_manual",            # the user ticked it in the install preview
        "confirmed": True,
        "provenance": "user_confirmed",            # set here, never copied from the file
        "category": _text(row.get("category")) or "其他",
        "origin": HUB_ORIGIN,
        "updated": time.strftime("%Y-%m-%d"),
        "hub": f"{entry['id']}@{entry['version']}",
    }
    return record


@dataclass
class InstallResult:
    library_key: str
    added: int
    removed: int
    kept_edits: int


def apply_install(plan: InstallPlan, checked_keys: Iterable[str] | None = None, *, legacy=None) -> InstallResult:
    """Write the plan into the personal library in one atomic write."""
    legacy = _legacy(legacy)
    checked = ({row_key(item.row) for item in plan.rows if item.checked}
               if checked_keys is None else set(checked_keys))
    payload = legacy.load_learned_term_payload(strict=True)
    payload["schema"] = max(2, int(payload.get("schema", 1) or 1))
    games = payload.setdefault("games", {})
    entry_meta = plan.entry
    key = plan.target_key
    created = False
    if key and key not in games:
        raise HubError("目标词库已经不存在，请重新打开线上词库")
    if not key:
        key = "library:" + uuid.uuid4().hex
        games[key] = {"game": plan.target_name, "library_id": key, "content_type": "game",
                      "revision": 0, "mappings": []}
        created = True
        payload["hidden_profile_ids"] = [item for item in payload.get("hidden_profile_ids", []) if item != key]
    entry = games[key]
    hub = dict(entry.get("hub") or {})
    if hub and hub.get("id") != entry_meta["id"]:
        raise HubError("这个词库已经装了另一个线上词库")
    created = created or bool(hub.get("created"))
    managed, edited, deleted = _managed(entry) if hub else ([], [], set())
    managed_ids = {id(row) for row in managed}
    for row in edited:
        row.pop("hub", None)                 # an edited hub row becomes the user's row
    rows = [row for row in entry.get("mappings", []) if id(row) not in managed_ids]
    present = {row_key(row) for row in rows}
    installed, declined = {}, set(hub.get("declined") or ()) | deleted
    for item in plan.rows:
        row_id = row_key(item.row)
        if item.status in {"same", "conflict", "blocked"}:
            continue
        if row_id not in checked:
            declined.add(row_id)
            continue
        declined.discard(row_id)
        if row_id in present:
            continue
        rows.append(_installed_row(item.row, entry_meta))
        present.add(row_id)
        installed[row_id] = _text(item.row.get("category")) or "其他"
    entry["mappings"] = rows
    entry["hub"] = {"id": entry_meta["id"], "version": entry_meta["version"],
                    "sha256": entry_meta["sha256"], "title": _text(entry_meta.get("title") or entry_meta["game"]),
                    "installed": installed, "declined": sorted(declined), "created": created,
                    "installed_at": time.strftime("%Y-%m-%d")}
    legacy._touch_glossary_entry(entry, key)
    os.makedirs(os.path.dirname(legacy.LEARNED_TERMS_PATH), exist_ok=True)
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    before = {row_key(row) for row in managed}
    return InstallResult(key, len(set(installed) - before), len(before - set(installed)), len(edited))


def uninstall(hub_id: str, *, legacy=None) -> int:
    """Remove the hub rows the user did not edit; return how many went."""
    legacy = _legacy(legacy)
    payload = legacy.load_learned_term_payload(strict=True)
    subs = subscriptions(legacy, payload)
    if hub_id not in subs:
        return 0
    key = subs[hub_id][0]
    entry = payload["games"][key]
    managed, edited, _deleted = _managed(entry)
    managed_ids = {id(row) for row in managed}
    for row in edited:
        row.pop("hub", None)
    entry["mappings"] = [row for row in entry.get("mappings", []) if id(row) not in managed_ids]
    created = bool(entry["hub"].get("created"))
    entry.pop("hub", None)
    if created and not entry["mappings"] and not entry.get("ai_note"):
        del payload["games"][key]
    else:
        legacy._touch_glossary_entry(entry, key)
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    return len(managed)


# --------------------------------------------------------------------------
# Submissions


def _verified_audio(row: Mapping) -> bool:
    return (_text(row.get("origin")) in _AUDIO_ORIGINS
            or _text(row.get("reason")).startswith("从旧版用户核验")
            or _text(row.get("verification")) == "manual_srt")


def build_submission(library_key: str, *, author: str = "", title: str = "", note: str = "",
                     legacy=None, app_version: str = "") -> tuple[dict, list[Finding]]:
    """A cleaned library file for the hub, plus the shared check's findings.

    Only confirmed rows are sent, and only from/to/category (and whether an
    alias was heard in real audio).  Reasons, sources, task ids and dates stay
    on this computer.
    """
    legacy = _legacy(legacy)
    payload = legacy.load_learned_term_payload()
    entry = (payload.get("games") or {}).get(library_key)
    if not isinstance(entry, dict):
        raise HubError("找不到这个词库")
    rows, seen = [], set()
    for row in entry.get("mappings", []):
        if not isinstance(row, dict):
            continue
        provenance = legacy.learned_mapping_provenance(row)
        if provenance != legacy.TERM_PROVENANCE_USER_CONFIRMED or not row.get("confirmed", True):
            continue
        item = {"from": _text(row.get("from")), "to": _text(row.get("to")),
                "category": _text(row.get("category")) or "其他"}
        if not item["from"] or not item["to"] or row_key(item) in seen:
            continue
        seen.add(row_key(item))
        if item["from"] != item["to"] and _verified_audio(row):
            item["verified_audio"] = True
        rows.append(item)
    rows.sort(key=lambda item: (item["to"], item["from"]))
    game = _text(entry.get("game")) or library_key
    hub = entry.get("hub") or {}
    document = {
        "schema": LIBRARY_SCHEMA,
        "id": str(hub.get("id") or slugify(game)),
        "game": game,
        "title": _text(title) or game,
        "authors": [_text(author)[:40]] if _text(author) else [],
        "license": LICENSE,
        "note": _text(note)[:500],
        "submitted": time.strftime("%Y-%m-%d"),
        "app_version": _text(app_version),
        "mappings": rows,
    }
    return document, lint_rows(rows)


def submission_filename(document: Mapping) -> str:
    return f"2byteasr-glossary-{document['id']}-{document['submitted']}.json"


def write_submission(document: Mapping, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / submission_filename(document)
    path.write_bytes((json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return path


def issue_text(document: Mapping, findings: Iterable[Finding]) -> tuple[str, str]:
    """Title and body for the submission issue (the file itself is attached)."""
    warnings = [item for item in findings if item.level == WARN]
    aliases = sum(1 for row in document["mappings"] if row["from"] != row["to"])
    title = f"[投稿] {document['title']} · {len(document['mappings'])} 条"
    body = "\n".join([
        f"游戏：{document['game']}",
        f"词条：{len(document['mappings'])} 条（其中改字规则 {aliases} 条）",
        f"作者：{', '.join(document['authors']) or '未署名'}",
        f"授权：{document['license']}（我同意以 CC0 公开这些词条）",
        f"检查：没有阻止发布的问题；提醒 {len(warnings)} 条",
        f"说明：{document.get('note') or '无'}",
        "",
        f"请把 2ByteASR 导出的文件 {submission_filename(document)} 拖进这里。",
    ])
    return title, body


def issue_url(provider: str, document: Mapping, findings: Iterable[Finding]) -> str:
    """GitHub accepts a prefilled title and body; GitCode opens its issue list."""
    if provider != "github":
        return ISSUE_PAGES["gitcode"]
    title, body = issue_text(document, findings)
    return ISSUE_PAGES["github"] + "?" + urllib.parse.urlencode({"title": title, "body": body})


def signature_document_for_tests(index_bytes: bytes, private_raw: bytes) -> bytes:
    """Sign a catalog with a throwaway key (tests and local previews only)."""
    from .update_manifest import sign_manifest
    return sign_manifest(index_bytes, private_raw)


def public_key_entry(private_raw: bytes) -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from .update_manifest import key_id_for
    public = Ed25519PrivateKey.from_private_bytes(private_raw).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key_id_for(public), base64.b64encode(public).decode("ascii")
