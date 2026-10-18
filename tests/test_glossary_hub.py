"""2026-10-17: online glossary hub (browse, install, update, remove, submit).

The hub is a signed catalog plus library files on GitCode and GitHub. These
tests use a throwaway Ed25519 key and a fake HTTP getter; the learned-terms
file is redirected to tmp. See docs/exec-plans/active/2026-10-17-online-glossary-hub.md.
"""
from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core as legacy
from twobyteasr import glossary_hub as hub
from twobyteasr import glossary_lint as lint

PRIVATE = bytes(range(32))
OTHER_PRIVATE = bytes(range(1, 33))


@pytest.fixture
def learned(tmp_path, monkeypatch):
    path = tmp_path / "2ByteASR" / "learned_game_terms.json"
    path.parent.mkdir()
    monkeypatch.setattr(legacy, "LEARNED_TERMS_PATH", str(path))
    return path


@pytest.fixture
def keys():
    key_id, public = hub.public_key_entry(PRIVATE)
    return {key_id: public}


class Response:
    def __init__(self, content=b"", status_code=200):
        self.content, self.status_code = content, status_code


class FakeWeb:
    """URL -> bytes; a missing URL answers 404, a listed host raises."""

    def __init__(self, files=None, down=()):
        self.files, self.down, self.calls = dict(files or {}), set(down), []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        if any(host in url for host in self.down):
            raise ConnectionError("unreachable")
        if url not in self.files:
            return Response(b"", 404)
        return Response(self.files[url])


def _library_doc(rows, library_id="genshin", game="原神"):
    return {"schema": 1, "id": library_id, "game": game, "title": game, "authors": ["t"],
            "license": "CC0-1.0", "mappings": rows}


def _served(label, sources):
    return ("GitCode" if label == "GitCode" else "GitHub") in sources


def _publish(libraries, *, private=PRIVATE, serial=1, sources=("GitCode", "GitHub")):
    """Files of one published hub, served by every listed source (GitHub covers its proxies)."""
    files, entries = {}, []
    for version, document in libraries:
        data = json.dumps(document, ensure_ascii=False).encode("utf-8")
        path = f"libraries/{document['id']}.json"
        entries.append({"id": document["id"], "game": document["game"], "title": document["title"],
                        "version": version, "rows": len(document["mappings"]), "path": path,
                        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                        "license": "CC0-1.0", "authors": ["t"], "updated": "2026-10-17"})
        files.update({url: data for label, url in hub.source_urls(path) if _served(label, sources)})
    index = json.dumps({"schema": 1, "serial": serial, "generated": "2026-10-17",
                        "libraries": entries}, ensure_ascii=False).encode("utf-8")
    signature = hub.signature_document_for_tests(index, private)
    for name, data in ((hub.INDEX_NAME, index), (hub.SIGNATURE_NAME, signature)):
        files.update({url: data for label, url in hub.source_urls(name) if _served(label, sources)})
    return files, entries


def _rows(identity):
    entry = legacy.load_learned_term_payload()["games"][identity]
    return {(row["from"], row["to"]): row for row in entry["mappings"]}


# ---------------------------------------------------------------- lint


def test_lint_blocks_conflicts_chains_and_filetrans_length():
    rows = [{"from": "爆米花", "to": "炮米花"}, {"from": "爆米花", "to": "苞米仔"},
            {"from": "炮米花", "to": "炮米花"}, {"from": "迪莫", "to": "迪莫"}, {"from": "迪毛", "to": "迪莫"},
            {"from": "克罗列夫茨基剧院科洛列夫茨基剧院", "to": "克罗列夫茨基剧院科洛列夫茨基剧院"},
            {"from": "炮米", "to": "炮米花"}, {"from": "炮米花丸", "to": "炮米"}]
    found = lint.lint_rows(rows)
    codes = {(item.source, item.target, item.code) for item in lint.blocking(found)}
    assert ("爆米花", "炮米花", "conflict") in codes and ("爆米花", "苞米仔", "conflict") in codes
    assert any(code == "filetrans" for _s, _t, code in codes)
    assert ("迪毛", "迪莫", "chain") not in codes            # 迪毛 is not anyone's canonical
    assert ("炮米花丸", "炮米", "chain") not in codes and any(
        item.code == "chain" for item in found if item.source == "炮米")  # 炮米 is 炮米花丸's target


def test_lint_warns_about_rewrites_that_change_real_speech():
    found = lint.findings_by_row(lint.lint_rows([
        {"from": "落地", "to": "跺地"}, {"from": "作战记录", "to": "高级作战记录"},
        {"from": "强攻特性", "to": "强攻"}, {"from": "ak", "to": "狂徒"}, {"from": "福宁娜", "to": "芙宁娜"},
        {"from": "芙宁娜", "to": "芙宁娜"}]))
    assert {item.code for item in found[("落地", "跺地")]} >= {"short_cjk", "common_word"}
    assert [item.code for item in found[("作战记录", "高级作战记录")]] == ["expands"]
    assert [item.code for item in found[("强攻特性", "强攻")]] == ["truncates"]
    assert [item.code for item in found[("ak", "狂徒")]] == ["short_ascii"]
    assert ("福宁娜", "芙宁娜") not in found and ("芙宁娜", "芙宁娜") not in found


# ---------------------------------------------------------------- catalog


def test_catalog_needs_a_trusted_signature(learned, keys):
    files, _ = _publish([(1, _library_doc([{"from": "芙宁娜", "to": "芙宁娜"}]))], private=OTHER_PRIVATE)
    with pytest.raises(hub.HubError, match="未受信任"):
        hub.fetch_catalog(request_get=FakeWeb(files).get, trusted_keys=keys, force=True)
    with pytest.raises(hub.HubError, match="还没有发布"):
        hub.fetch_catalog(request_get=FakeWeb(files).get, trusted_keys={}, force=True)


def test_catalog_works_when_only_one_source_answers_and_is_cached(learned, keys):
    files, _ = _publish([(1, _library_doc([{"from": "芙宁娜", "to": "芙宁娜"}]))], sources=("GitCode",))
    web = FakeWeb(files, down=("githubusercontent",))
    catalog = hub.fetch_catalog(request_get=web.get, trusted_keys=keys, now=1000.0)
    assert catalog.source == "GitCode" and catalog.entry("genshin")["version"] == 1
    offline = FakeWeb({}, down=("gitcode", "githubusercontent"))
    cached = hub.fetch_catalog(request_get=offline.get, trusted_keys=keys, now=1000.0 + 60)
    assert offline.calls == [] and not cached.stale            # fresh cache: no network
    stale = hub.fetch_catalog(request_get=offline.get, trusted_keys=keys, now=1000.0 + 2 * 86400)
    assert stale.stale and stale.entry("genshin")


def test_newer_serial_wins_within_the_grace_period(learned, keys):
    old, _ = _publish([(1, _library_doc([{"from": "芙宁娜", "to": "芙宁娜"}]))], serial=1, sources=("GitCode",))
    new, _ = _publish([(2, _library_doc([{"from": "芙宁娜", "to": "芙宁娜"}]))], serial=2, sources=("GitHub",))
    catalog = hub.fetch_catalog(request_get=FakeWeb({**old, **new}).get, trusted_keys=keys, force=True)
    assert catalog.document["serial"] == 2 and catalog.entry("genshin")["version"] == 2


def test_library_file_must_match_the_signed_hash(learned, keys):
    document = _library_doc([{"from": "芙宁娜", "to": "芙宁娜"}])
    files, entries = _publish([(1, document)])
    tampered = {url: (b'{"schema":1}' if "gitcode" in url and "libraries" in url else data)
                for url, data in files.items()}
    library = hub.fetch_library(entries[0], request_get=FakeWeb(tampered).get)
    assert library["mappings"] == [{"from": "芙宁娜", "to": "芙宁娜", "category": "其他"}]
    bad = {url: (b"x" if "libraries" in url else data) for url, data in files.items()}
    with pytest.raises(hub.HubError, match="对不上"):
        hub.fetch_library(entries[0], request_get=FakeWeb(bad).get)


# ---------------------------------------------------------------- install / update / remove


def _entry(version, rows, sha="0" * 64):
    return {"id": "genshin", "game": "原神", "title": "原神（至冬）", "version": version, "sha256": sha,
            "path": "libraries/genshin.json", "size": 10, "rows": len(rows)}


ROWS_V1 = [{"from": "芙宁娜", "to": "芙宁娜", "category": "角色"},
           {"from": "福宁娜", "to": "芙宁娜", "category": "角色"},
           {"from": "落地", "to": "跺地", "category": "技能"},
           {"from": "派蒙", "to": "派蒙", "category": "角色", "provenance": "official"}]


def test_install_creates_a_library_and_leaves_risky_rules_unticked(learned):
    plan = hub.plan_install(_entry(1, ROWS_V1), _library_doc(ROWS_V1))
    assert plan.target_key == "" and plan.target_name == "原神"
    ticked = {hub.row_key(item.row) for item in plan.rows if item.checked}
    assert "落地→跺地" not in ticked and "福宁娜→芙宁娜" in ticked
    result = hub.apply_install(plan)
    rows = _rows(result.library_key)
    assert set(rows) == {("芙宁娜", "芙宁娜"), ("福宁娜", "芙宁娜"), ("派蒙", "派蒙")}
    assert all(row["provenance"] == "user_confirmed" and row["hub"] == "genshin@1" for row in rows.values())
    record = legacy.load_learned_term_payload()["games"][result.library_key]["hub"]
    assert record["declined"] == ["落地→跺地"] and record["created"] is True


def test_install_merges_into_the_users_library_without_touching_their_rows(learned):
    mine = legacy.create_learned_content("原神", create_new=True)
    legacy.add_learned_mapping(mine, "福宁娜", "芙宁娜", category="其他", origin="手动")
    legacy.add_learned_mapping(mine, "派蒙", "应急食品", category="其他", origin="手动")
    plan = hub.plan_install(_entry(1, ROWS_V1), _library_doc(ROWS_V1))
    status = {hub.row_key(item.row): item.status for item in plan.rows}
    assert plan.target_key == mine
    assert status["福宁娜→芙宁娜"] == "same" and status["派蒙→派蒙"] == "conflict"
    hub.apply_install(plan)
    rows = _rows(mine)
    assert rows[("福宁娜", "芙宁娜")]["origin"] == "手动" and "hub" not in rows[("福宁娜", "芙宁娜")]
    assert ("派蒙", "派蒙") not in rows and ("派蒙", "应急食品") in rows


def test_update_keeps_user_edits_and_deletions(learned):
    first = hub.apply_install(hub.plan_install(_entry(1, ROWS_V1), _library_doc(ROWS_V1)))
    key = first.library_key
    legacy.edit_learned_mapping(key, ("芙宁娜", "芙宁娜"), "芙宁娜", "芙宁娜", category="水神")
    legacy.delete_learned_mappings(key, [("派蒙", "派蒙")])
    rows_v2 = [{"from": "芙宁娜", "to": "芙宁娜", "category": "角色"},
               {"from": "派蒙", "to": "派蒙", "category": "角色"},
               {"from": "那维莱特", "to": "那维莱特", "category": "角色"}]
    plan = hub.plan_install(_entry(2, rows_v2), _library_doc(rows_v2))
    status = {hub.row_key(item.row): item.status for item in plan.rows}
    assert plan.updating and status["派蒙→派蒙"] == "declined" and status["芙宁娜→芙宁娜"] == "same"
    assert [hub.row_key(row) for row in plan.removed] == ["福宁娜→芙宁娜"]
    result = hub.apply_install(plan)
    rows = _rows(key)
    assert rows[("芙宁娜", "芙宁娜")]["category"] == "水神" and "hub" not in rows[("芙宁娜", "芙宁娜")]
    assert ("派蒙", "派蒙") not in rows and ("福宁娜", "芙宁娜") not in rows
    assert rows[("那维莱特", "那维莱特")]["hub"] == "genshin@2"
    assert result.added == 1 and result.removed == 1
    assert hub.subscriptions()["genshin"][1]["version"] == 2


def test_uninstall_keeps_edits_and_drops_an_empty_created_library(learned):
    key = hub.apply_install(hub.plan_install(_entry(1, ROWS_V1), _library_doc(ROWS_V1))).library_key
    assert hub.uninstall("genshin") == 3
    assert key not in legacy.load_learned_term_payload()["games"]
    key = hub.apply_install(hub.plan_install(_entry(1, ROWS_V1), _library_doc(ROWS_V1))).library_key
    legacy.edit_learned_mapping(key, ("派蒙", "派蒙"), "派蒙", "派蒙", category="伙伴")
    assert hub.uninstall("genshin") == 2
    assert set(_rows(key)) == {("派蒙", "派蒙")} and "hub" not in _rows(key)[("派蒙", "派蒙")]


# ---------------------------------------------------------------- submit


def test_submission_sends_only_confirmed_rows_without_private_fields(learned):
    key = legacy.create_learned_content("洛克王国：世界", create_new=True)
    legacy.add_learned_mapping(key, "迪莫", "迪莫", category="角色", origin="手动")
    legacy.add_learned_mapping(key, "迪毛", "迪莫", category="角色", origin="手动")
    legacy.persist_learned_mappings(key, [{"from": "候选", "to": "候选词", "confirmed": False,
                                           "provenance": "candidate"}])
    payload = legacy.load_learned_term_payload()
    for row in payload["games"][key]["mappings"]:
        if row["from"] == "迪毛":
            row["origin"] = "用户整理"
            row["task_id"] = "secret-task"
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    document, findings = hub.build_submission(key, author="兔白", note="实况里听到的")
    assert [(row["from"], row["to"]) for row in document["mappings"]] == [("迪毛", "迪莫"), ("迪莫", "迪莫")]
    assert document["mappings"][0] == {"from": "迪毛", "to": "迪莫", "category": "角色", "verified_audio": True}
    assert "secret-task" not in json.dumps(document, ensure_ascii=False)
    assert document["license"] == "CC0-1.0" and document["authors"] == ["兔白"]
    assert not lint.blocking(findings)
    url = hub.issue_url("github", document, findings)
    assert url.startswith(hub.ISSUE_PAGES["github"] + "?title=") and len(url) < 6000
    assert hub.issue_url("gitcode", document, findings) == hub.ISSUE_PAGES["gitcode"]


def test_submit_lists_every_library_and_leaves_unticked_rows_home(learned):
    # 2026-10-18 redesign: step 1 lists the user's libraries, step 2 may untick rows.
    rock = legacy.create_learned_content("洛克王国：世界", create_new=True)
    legacy.add_learned_mapping(rock, "迪莫", "迪莫", category="角色", origin="手动")
    legacy.add_learned_mapping(rock, "迪毛", "迪莫", category="角色", origin="手动")
    legacy.persist_learned_mappings(rock, [{"from": "候选", "to": "候选词", "confirmed": False,
                                            "provenance": "candidate"}])
    genshin = legacy.create_learned_content("原神", create_new=True)
    legacy.add_learned_mapping(genshin, "芙宁娜", "芙宁娜", category="角色", origin="手动")
    payload = legacy.load_learned_term_payload()
    payload["games"][genshin]["hub"] = {"id": "genshin", "title": "原神（至冬 7.x）", "version": 1}
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    libraries = {item.key: item for item in hub.submittable_libraries()}
    assert (libraries[rock].game, libraries[rock].rows, libraries[rock].aliases,
            libraries[rock].unconfirmed, libraries[rock].hub_title) == ("洛克王国：世界", 2, 1, 1, "")
    assert libraries[genshin].hub_title == "原神（至冬 7.x）"
    document, _findings = hub.build_submission(rock, excluded={"迪毛→迪莫"})
    assert [(row["from"], row["to"]) for row in document["mappings"]] == [("迪莫", "迪莫")]


def test_findings_of_one_kind_are_grouped_blocking_kinds_first():
    # The user saw 37 identical "两字以内的改字规则" lines; the sheet now says it once.
    rows = [{"from": "迪毛", "to": "迪莫", "verified_audio": True}, {"from": "火深", "to": "火神", "verified_audio": True},
            {"from": "雷吉", "to": "雷姬"}, {"from": "史来姆", "to": "史莱姆"}, {"from": "史来姆", "to": "史莱母"}]
    groups = hub.group_findings(lint.lint_rows(rows), rows)
    assert (groups[0].level, groups[0].code, groups[0].keys) == (
        lint.BLOCK, "conflict", [("史来姆", "史莱姆"), ("史来姆", "史莱母")])
    short = [group for group in groups if group.code == "short_cjk"]
    assert len(short) == 1 and short[0].count == 3 and short[0].verified == 2
    assert short[0].keys[0] == ("迪毛", "迪莫")


def test_parse_library_never_trusts_provenance_from_the_file():
    data = json.dumps(_library_doc([{"from": "派蒙", "to": "派蒙", "provenance": "user_confirmed",
                                     "confirmed": True, "hub": "x@9", "reason": "r"}])).encode("utf-8")
    assert hub.parse_library(data)["mappings"] == [{"from": "派蒙", "to": "派蒙", "category": "其他"}]


# ---------------------------------------------------------------- hub repository (maintainer side)


def test_repository_versions_bump_only_when_content_changes(tmp_path):
    from twobyteasr import glossary_hub_repo as repo_tools
    submission = _library_doc([{"from": "福宁娜", "to": "芙宁娜", "category": "角色", "reason": "private"},
                               {"from": "芙宁娜", "to": "芙宁娜", "category": "角色"}])
    first, findings = repo_tools.normalize_library(submission, library_id="genshin-impact", today="2026-10-17")
    assert first["version"] == 1 and not lint.blocking(findings)
    assert all(set(row) <= {"from", "to", "category", "verified_audio", "note"} for row in first["mappings"])
    repo_tools.write_library(tmp_path, first)
    same, _ = repo_tools.normalize_library(submission, previous=first, library_id="genshin-impact", today="2026-10-18")
    assert same["version"] == 1 and same["updated"] == "2026-10-17"
    submission["mappings"].append({"from": "那维莱特", "to": "那维莱特", "category": "角色"})
    newer, _ = repo_tools.normalize_library(submission, previous=first, library_id="genshin-impact", today="2026-10-18")
    assert newer["version"] == 2 and newer["authors"] == ["t"]
    with pytest.raises(ValueError, match="CC0"):
        repo_tools.normalize_library({**submission, "license": "CC-BY-4.0"}, library_id="genshin-impact")


def test_repository_index_matches_files_and_the_app_accepts_it(tmp_path):
    from twobyteasr import glossary_hub_repo as repo_tools
    library, _ = repo_tools.normalize_library(_library_doc([{"from": "芙宁娜", "to": "芙宁娜"}]),
                                              library_id="genshin-impact")
    repo_tools.write_library(tmp_path, library)
    index = repo_tools.build_index(tmp_path)
    document = hub.parse_index(index)
    assert document["serial"] == 1 and document["libraries"][0]["rows"] == 1
    (tmp_path / "index.json").write_bytes(index)
    assert repo_tools.check_repo(tmp_path) == []
    again = repo_tools.build_index(tmp_path, previous=json.loads(index))
    assert json.loads(again)["serial"] == 1                      # nothing changed
    library["mappings"].append({"from": "派蒙", "to": "派蒙", "category": "其他"})
    library["mappings"].sort(key=lambda row: (row["to"], row["from"]))
    repo_tools.write_library(tmp_path, library)
    assert any("哈希过期" in line for line in repo_tools.check_repo(tmp_path))
    assert json.loads(repo_tools.build_index(tmp_path, previous=json.loads(index)))["serial"] == 2
