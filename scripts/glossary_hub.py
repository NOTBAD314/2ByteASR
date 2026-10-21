# SPDX-License-Identifier: GPL-3.0-only
"""Maintain the online glossary repository (2ByteASR-glossaries), 2026-10-17.

The repository is a plain Git checkout (``--repo``).  Typical round:

    python -X utf8 scripts/glossary_hub.py add  <submission.json> --repo <hub>   # review first
    python -X utf8 scripts/glossary_hub.py check --repo <hub>
    python -X utf8 scripts/glossary_hub.py build --repo <hub>
    python -X utf8 scripts/glossary_hub.py sign  --repo <hub>
    python -X utf8 scripts/glossary_hub.py publish --repo <hub> --yes          # GitHub + GitCode

One-time:

    keygen      the hub signing key, DPAPI-protected outside the repository
                (separate from the update-manifest key); embed the printed
                public key in twobyteasr/glossary/glossary_hub.py TRUSTED_HUB_KEYS
    init-repo   README, licence, issue form, CI and the standalone checker
    seed        the maintainer's own personal libraries as the first content

Nothing here runs on its own; publish refuses to push without --yes.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from twobyteasr.glossary import glossary_hub as hub  # noqa: E402
from twobyteasr.glossary import glossary_hub_repo as repo_tools  # noqa: E402
from twobyteasr.glossary.glossary_lint import BLOCK, WARN  # noqa: E402

DEFAULT_KEY = Path(os.environ.get("TWOBYTEASR_HUB_SIGNING_KEY")
                   or Path.home() / ".2byteasr-release" / "glossary-hub-signing-key.dpapi")
GITHUB_URL = f"https://github.com/{hub.GITHUB_REPOSITORY}.git"
GITCODE_URL = f"https://gitcode.com/{hub.GITCODE_REPOSITORY}.git"
TEMPLATES = ROOT / "scripts" / "glossary_hub_templates"

# The maintainer's own libraries (2026-10-17 cleanup) -> hub id, title, note.
SEED = {
    "洛克王国世界": ("roco-kingdom-world", "洛克王国：世界", "含实况里核对过的误听改字规则；S4「月涌狂想」新精灵已收录。"),
    "原神": ("genshin-impact", "原神", "角色、地区、执行官、元素反应；含至冬 7.x 新内容。"),
    "明日方舟终末地": ("arknights-endfield", "明日方舟：终末地", "干员、首领、四号谷地与武陵地区、集成工业术语；含 1.6。"),
    "绝区零": ("zenless-zone-zero", "绝区零", "代理人、邦布、阵营、首领与玩法；含 3.x 新代理人。"),
    "瓦罗兰特": ("valorant", "瓦罗兰特（国服＋台服名称）", "特工、武器、地图、大招；国服与台服两套名称都在。"),
    "我的世界": ("minecraft", "我的世界", "Java 版官方简体译名：维度、结构、生物群系、关键物品、魔咒、常见玩法。"),
    "异环": ("neverness-to-everness", "异环", "角色、海特洛市城区、势力、环合反应等玩法术语。"),
}


def _print_findings(name: str, findings) -> int:
    blocks = [item for item in findings if item.level == BLOCK]
    warns = [item for item in findings if item.level == WARN]
    for item in blocks:
        print(f"  ✗ {name}: {item.source} → {item.target}：{item.message}")
    if warns:
        print(f"  ! {name}: {len(warns)} 条提醒（安装时默认不勾）")
    return len(blocks)


def cmd_keygen(args) -> None:
    from release_signing import generate
    record = generate(args.key_file)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print("把 key_id 和 public 加进 twobyteasr/glossary/glossary_hub.py 的 TRUSTED_HUB_KEYS。")


def cmd_seed(args) -> None:
    import subtitle_core as legacy
    payload = legacy.load_learned_term_payload()
    games = payload.get("games") or {}
    for key, (library_id, title, note) in SEED.items():
        if key not in games:
            print(f"跳过 {key}：这台电脑没有这个词库")
            continue
        document, _findings = hub.build_submission(key)
        path = args.repo / "libraries" / f"{library_id}.json"
        previous = repo_tools.read_library(path) if path.is_file() else None
        library, findings = repo_tools.normalize_library(document, previous=previous, library_id=library_id,
                                                         title=title, note=note)
        if _print_findings(library_id, findings):
            print(f"  没有写入 {library_id}")
            continue
        repo_tools.write_library(args.repo, library)
        print(f"{library_id}: v{library['version']} · {len(library['mappings'])} 条")


def cmd_add(args) -> None:
    document = json.loads(Path(args.submission).read_text("utf-8"))
    library_id = args.id or document.get("id") or hub.slugify(document.get("game", ""))
    path = args.repo / "libraries" / f"{library_id}.json"
    previous = repo_tools.read_library(path) if path.is_file() else None
    library, findings = repo_tools.normalize_library(document, previous=previous, library_id=library_id,
                                                     title=args.title or "", note=args.note or "")
    if _print_findings(library_id, findings):
        raise SystemExit("有必须先改的问题，没有写入")
    repo_tools.write_library(args.repo, library)
    print(f"{library_id}: v{library['version']} · {len(library['mappings'])} 条 → {path}")


def cmd_check(args) -> None:
    errors = []
    for path in sorted((args.repo / "libraries").glob("*.json")):
        _library, file_errors, findings = repo_tools.check_library(path)
        errors += file_errors
        _print_findings(path.stem, [item for item in findings if item.level == WARN])
    if not args.libraries_only:
        errors = list(dict.fromkeys(errors + repo_tools.check_repo(args.repo)))
    for line in errors:
        print("  ✗ " + line)
    if errors:
        raise SystemExit(f"{len(errors)} 个问题")
    print("检查通过")


def cmd_build(args) -> None:
    index_path = args.repo / hub.INDEX_NAME
    previous = json.loads(index_path.read_text("utf-8")) if index_path.is_file() else None
    data = repo_tools.build_index(args.repo, previous=previous)
    index_path.write_bytes(data)
    hub.parse_index(data)  # the app must accept what we publish
    document = json.loads(data)
    print(f"index.json: serial {document['serial']} · {len(document['libraries'])} 个词库")


def cmd_sign(args) -> None:
    from release_signing import load_private
    index_path = args.repo / hub.INDEX_NAME
    data = index_path.read_bytes()
    signature = hub.signature_document_for_tests(data, load_private(args.key_file))
    key_id = json.loads(signature)["key_id"]
    if key_id not in hub.TRUSTED_HUB_KEYS and not args.allow_untrusted:
        raise SystemExit(f"密钥 {key_id} 还没有写进 TRUSTED_HUB_KEYS；程序不会接受这个签名")
    hub.verify_index(data, signature, hub.TRUSTED_HUB_KEYS if not args.allow_untrusted
                     else {key_id: hub.public_key_entry(load_private(args.key_file))[1]})
    (args.repo / hub.SIGNATURE_NAME).write_bytes(signature)
    print(f"index.json.sig: key {key_id}")


def cmd_init_repo(args) -> None:
    args.repo.mkdir(parents=True, exist_ok=True)
    for source in TEMPLATES.rglob("*"):
        if source.is_file():
            target = args.repo / source.relative_to(TEMPLATES)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not args.force:
                print(f"保留已有 {target.relative_to(args.repo)}")
                continue
            shutil.copyfile(source, target)
    tools = args.repo / "tools"
    tools.mkdir(exist_ok=True)
    from twobyteasr.glossary import glossary_lint
    for module in (glossary_lint, repo_tools):   # wherever the package layout puts them
        shutil.copyfile(module.__file__, tools / Path(module.__file__).name)
    print(f"已写入仓库骨架：{args.repo}")


def _git(repo: Path, *argv, env=None) -> str:
    result = subprocess.run(["git", *argv], cwd=repo, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise SystemExit(f"git {' '.join(argv[:2])}: {result.stderr.strip()}")
    return result.stdout.strip()


def _push_gitcode(repo: Path, branch: str) -> None:
    from gitcode_release import read_token
    token = read_token()
    with tempfile.TemporaryDirectory() as folder:
        askpass = Path(folder) / "askpass.cmd"
        owner = hub.GITCODE_REPOSITORY.split("/")[0]
        askpass.write_text('@echo off\r\necho %1 | findstr /i "Username" >nul && (echo ' + owner
                           + ') || (echo %GITCODE_PUSH_TOKEN%)\r\n', "ascii")
        env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0", GITCODE_PUSH_TOKEN=token)
        result = subprocess.run(["git", "-c", "credential.helper=", "push", "--no-verify", GITCODE_URL,
                                 f"{branch}:{branch}"], cwd=repo, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        output = ((result.stdout or "") + (result.stderr or "")).replace(token, "***").strip()
        print("gitcode: " + output)
        if result.returncode:
            raise SystemExit("GitCode 推送失败")


def cmd_publish(args) -> None:
    if not args.yes:
        raise SystemExit("publish 会推送到 GitHub 和 GitCode；确认后加 --yes")
    cmd_check(argparse.Namespace(repo=args.repo, libraries_only=False))
    hub.verify_index((args.repo / hub.INDEX_NAME).read_bytes(), (args.repo / hub.SIGNATURE_NAME).read_bytes())
    branch = _git(args.repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(args.repo, "add", "-A")
    if _git(args.repo, "status", "--porcelain"):
        _git(args.repo, "commit", "-m", args.message or "更新线上词库")
    print(_git(args.repo, "push", GITHUB_URL, f"{branch}:{branch}"))
    _push_gitcode(args.repo, branch)
    print("已推送到 GitHub 和 GitCode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, func, repo=True):
        sub = commands.add_parser(name)
        sub.set_defaults(func=func)
        if repo:
            sub.add_argument("--repo", type=Path, required=True)
        return sub

    keygen = command("keygen", cmd_keygen, repo=False)
    keygen.add_argument("--key-file", type=Path, default=DEFAULT_KEY)
    command("seed", cmd_seed)
    add = command("add", cmd_add)
    add.add_argument("submission")
    add.add_argument("--id")
    add.add_argument("--title")
    add.add_argument("--note")
    check = command("check", cmd_check)
    check.add_argument("--libraries-only", action="store_true", help="for pull requests: skip index.json")
    command("build", cmd_build)
    sign = command("sign", cmd_sign)
    sign.add_argument("--key-file", type=Path, default=DEFAULT_KEY)
    sign.add_argument("--allow-untrusted", action="store_true", help="local preview with a key the app does not trust")
    init = command("init-repo", cmd_init_repo)
    init.add_argument("--force", action="store_true")
    publish = command("publish", cmd_publish)
    publish.add_argument("--yes", action="store_true")
    publish.add_argument("--message")
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
