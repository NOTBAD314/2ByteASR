"""The three-step glossary submit sheet in the real app (2026-10-18).

Usage: python scripts/verify_glossary_submit_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
       [--theme grape|warm]
Runs on a private Windows desktop with isolated user data.  Example libraries
(not the user's) are written before start; the hub catalog is a local fake and
no submission page is opened.  See twobyteasr/acceptance/glossary_submit_audit.py.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOTWORDS = ["迪莫", "洛克贝贝", "魔力猫", "火神", "水灵", "雪影娃娃", "圣光迪莫", "喵喵", "小火猴", "恶魔狼",
            "冰晶龙", "拉布朵", "克拉克", "艾尔", "幽灵猫", "雷电猴", "魔法石", "天空城", "布鲁斯", "梅丽莎"]
ALIASES = [  # (from, to, heard in real audio)
    ("迪毛", "迪莫", True), ("火深", "火神", True), ("喵咪", "喵喵", True), ("水零", "水灵", True),
    ("艾儿", "艾尔", True), ("克拉", "克拉克", False), ("天空", "天空城", False),
    ("魔力毛", "魔力猫", True), ("雪影哇哇", "雪影娃娃", True), ("洛克背背", "洛克贝贝", False),
    ("恶魔郎", "恶魔狼", True), ("冰晶笼", "冰晶龙", False),
    ("雷电候", "雷电猴", False), ("雷电候", "雷电侯", False),
]


def seed(output: Path) -> None:
    import subtitle_core as legacy
    if not str(Path(legacy.LEARNED_TERMS_PATH).resolve()).startswith(str(output)):
        raise SystemExit(f"learned terms are not isolated: {legacy.LEARNED_TERMS_PATH}")

    def row(source, target, category, verified=False):
        return {"from": source, "to": target, "category": category, "confirmed": True,
                "provenance": legacy.TERM_PROVENANCE_USER_CONFIRMED,
                "origin": "用户整理" if verified else "手动", "reason": "示例：私人备注不会上传"}
    keys = {name: legacy.create_learned_content(game, create_new=True)
            for name, game in (("empty", "新游戏"), ("genshin", "原神"), ("rock", "洛克王国：世界"))}
    payload = legacy.load_learned_term_payload(strict=True)
    games = payload["games"]
    games[keys["rock"]]["mappings"] = (
        [row(word, word, "宠物") for word in HOTWORDS]
        + [row(source, target, "宠物", verified) for source, target, verified in ALIASES]
        + [{"from": "候选词", "to": "候选", "confirmed": False, "provenance": "candidate"}])
    games[keys["genshin"]]["mappings"] = [row("芙宁娜", "芙宁娜", "角色"), row("福宁娜", "芙宁娜", "角色"),
                                        row("那维莱特", "那维莱特", "角色")]
    games[keys["genshin"]]["hub"] = {"id": "genshin", "version": 1, "title": "原神（至冬 7.x）", "installed": {},
                                   "declined": [], "created": True}
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    short = sum(1 for source, _target, _verified in ALIASES if len(source) <= 2)
    (output / "seed.json").write_text(json.dumps({"keys": keys, "expected": {
        "rows": len(HOTWORDS) + len(ALIASES), "short": short, "left_out": ["恶魔郎", "恶魔狼"],
        "conflict_from": "雷电候"}}, ensure_ascii=False, indent=1), "utf8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--theme", default="grape")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "tmp") or output.exists():
        raise ValueError("Choose a fresh output directory under repository tmp")
    if args.exe and not args.exe.resolve().is_file():
        parser.error("--exe must identify an existing executable")
    output.mkdir(parents=True)
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output)
    from twobyteasr.test_isolation import install
    install()
    seed(output)
    # The acceptance gate wants an owned project file inside the output; this
    # scenario never opens Studio, so a placeholder is enough.
    placeholder = output / "projects" / "glossary-submit.2byteproj"
    placeholder.parent.mkdir(parents=True)
    placeholder.write_text("{}", "utf8")

    env = os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE",
                "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", "TWOBYTEASR_STARTUP_LEAVE_STUDIO"):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO="glossary-submit",
               TWOBYTEASR_STARTUP_PROJECT=str(placeholder),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_GLOSSARY_AUDIT_THEME=args.theme,
               QT_QPA_PLATFORM="windows", TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", PYTHONUTF8="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", NO_PROXY="127.0.0.1,localhost")
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    sys.path.insert(0, str(ROOT / "scripts"))
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / "process", timeout=600)
    receipt = output / "result.json"
    deadline = time.monotonic() + 60
    result = {}
    while time.monotonic() < deadline:  # launchers may return before the GUI finishes
        try:
            result = json.loads(receipt.read_text("utf8"))
            if result.get("gui_shutdown"):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result["launcher_exit"] = code
    result["passed"] = bool(result.get("passed") and code == 0 and result.get("gui_shutdown"))
    import psutil
    pid = result.get("pid")
    if pid and psutil.pid_exists(pid):
        try:
            result["child_exit"] = psutil.Process(pid).wait(timeout=25)
            result["passed"] = bool(result["passed"] and result["child_exit"] == 0)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result["passed"] = False
            result["error"] = "Owned glossary-submit GUI did not exit after normal close"
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    failed = [c["name"] for c in result.get("checks", []) if not c["passed"]]
    print(json.dumps(dict(passed=result["passed"], checks=len(result.get("checks", [])), failed=failed,
                          launcher_exit=code, error=(result.get("error") or "")[-800:],
                          executable=result.get("executable"), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
