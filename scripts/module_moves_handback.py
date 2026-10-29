"""Bring the 2026-10-15 architecture branch into another working tree (one-time tool).

The shared working tree keeps changing while a branch is prepared, so the
package move is not handed back as a diff.  Instead this tool:

1. builds R = "the branch's base snapshot after module_moves.py apply" in a
   temporary worktree and commits it, so ``git diff R <branch>`` is exactly
   the branch's hand-written edits (docs, fixes, tests, lazy imports...);
2. runs ``scripts/module_moves.py apply`` on the TARGET tree's current files
   (peers' newer edits are moved and rewritten along with everything else);
3. merges each hand-written edit into the target with ``git merge-file``
   (base = R, ours = target after the move, theirs = branch), keeping every
   file's own line endings and BOM.

Nothing is written to the target if any file conflicts; the conflicts are
listed instead.  Before writing, the target's current state is saved as a
commit on a backup branch (temporary index, the target's own index is not
touched), so it can be restored with ``git checkout <backup> -- .`` plus
removing the new folders.

Usage (from the branch checkout):
  python -X utf8 scripts/module_moves_handback.py --target <tree> --base <snapshot commit> [--write]
Without --write it is a dry run that only reports what would happen.
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH_ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd, env=None, check=True, text=True):
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=text, encoding="utf-8" if text else None)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout if text else result.stdout


def read(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = (raw[3:] if bom else raw).decode("utf-8")
    crlf = text.count("\r\n") > 0 and text.count("\r\n") == text.count("\n")
    return text.replace("\r\n", "\n"), bom, crlf


def write(path: Path, text: str, bom: bool, crlf: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def blob(commit: str, relative: str) -> str | None:
    result = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=BRANCH_ROOT, capture_output=True)
    if result.returncode != 0:
        return None
    data = result.stdout
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8").replace("\r\n", "\n")


def snapshot(tree: Path, message: str) -> str:
    with tempfile.TemporaryDirectory() as scratch:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / "index"))
        git("read-tree", "HEAD", cwd=tree, env=env)
        git("add", "-A", "--", ".", ":!.claude", ":!Claude outputs", ":!Microsoft", ":!.v2c", cwd=tree, env=env)
        tree_id = git("write-tree", cwd=tree, env=env).strip()
        return git("commit-tree", tree_id, "-p", "HEAD", "-m", message, cwd=tree).strip()


def build_reference(base: str, scratch: Path) -> tuple[str, Path]:
    """R = base snapshot + the scripted move, as a commit in the shared repository."""
    work = Path(tempfile.mkdtemp(prefix="arch-ref-", dir=scratch))
    shutil.rmtree(work)
    git("worktree", "add", "--detach", str(work), base, cwd=BRANCH_ROOT)
    for name in ("module_moves.py", "module_moves.json"):
        shutil.copy2(BRANCH_ROOT / "scripts" / name, work / "scripts" / name)
    subprocess.run([sys.executable, "-X", "utf8", "scripts/module_moves.py", "apply"], cwd=work, check=True)
    commit = snapshot(work, "architecture hand-back reference: base snapshot after module_moves.py apply (not for merge)")
    return commit, work


# Status logs that every session prepends to.  When a line merge conflicts
# only because others also added entries at the top, this round's own
# entries are inserted at the same list heads of the target's current text.
# Each rule: (first line of the inserted block, where it goes).
ANCHORED_INSERTS = {
    "docs/PROJECT_STATE.md": [
        ("1. **程序代码按功能分文件夹", ("before_first_prefix", "1. **")),
        ("- **架构整理还缺的**", ("after_heading", "## 还没结束的事")),
    ],
    "docs/RECENT_CHANGES.md": [
        ("## 2026-10-15（傍晚）：程序代码按功能分文件夹", ("before_first_prefix", "## 2026-")),
    ],
}


def anchored_insert(relative: str, base: str, theirs: str, ours: str) -> str | None:
    import difflib
    rules = ANCHORED_INSERTS.get(relative)
    if not rules:
        return None
    base_lines, their_lines = base.split("\n"), theirs.split("\n")
    blocks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=base_lines, b=their_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert":
            return None  # the branch also changed existing lines: leave it to a person
        blocks.append(their_lines[j1:j2])
    result = ours.split("\n")
    for block in blocks:
        while block and not block[0].strip():
            block = block[1:]
        while block and not block[-1].strip():
            block = block[:-1]
        rule = next((where for prefix, where in rules if block and block[0].startswith(prefix)), None)
        if rule is None:
            return None
        kind, anchor = rule
        if kind == "before_first_prefix":
            index = next((n for n, line in enumerate(result) if line.startswith(anchor)), None)
        else:
            heading = next((n for n, line in enumerate(result) if line.strip() == anchor), None)
            index = None if heading is None else heading + 2  # after the heading and its blank line
        if index is None:
            return None
        # A section placed before another heading keeps one blank line between them.
        result[index:index] = block + ([""] if anchor.startswith("#") else [])
    return "\n".join(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--base", required=True, help="snapshot commit the branch started from")
    parser.add_argument("--branch", default="HEAD")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--scratch", type=Path, default=BRANCH_ROOT / "tmp",
                        help="folder for the temporary reference worktree and target mirror")
    args = parser.parse_args()
    target = args.target.resolve()
    branch = git("rev-parse", args.branch, cwd=BRANCH_ROOT).strip()

    args.scratch.mkdir(parents=True, exist_ok=True)
    reference, ref_tree = build_reference(args.base, args.scratch.resolve())
    try:
        changes = [line.split("\t") for line in git("diff", "--no-renames", "--name-status", reference, branch,
                                                    cwd=BRANCH_ROOT).splitlines() if line]
    finally:
        git("worktree", "remove", "--force", str(ref_tree), cwd=BRANCH_ROOT)
    # A fresh checkout can show a file as modified only because git normalises
    # its line endings (e.g. a CRLF fixture under ``*.txt eol=lf``); the
    # reference snapshot then differs from the base while the branch never
    # touched the file.  Such files are not branch edits.  The document
    # catalog is generated: rebuild it in the target instead of merging it.
    generated = {"docs/CATALOG.md", "docs/library.html"}
    kept = []
    for status, relative in changes:
        if relative in generated:
            continue
        if status == "M" and blob(branch, relative) == blob(args.base, relative):
            continue
        kept.append((status, relative))
    skipped = len(changes) - len(kept)
    changes = kept
    print(f"reference {reference[:10]}; hand-written edits on the branch: {len(changes)} files"
          + (f" ({skipped} skipped: generated catalog or checkout-only line-ending changes)" if skipped else ""))

    # Work on a scratch copy of the target's affected files first: run the
    # move on the real target only after every merge is known to be clean.
    planned: list[tuple[str, str, str | None, str | None]] = []  # (status, path, new text, target text it was merged from)
    conflicts: list[str] = []
    moved_target = Path(tempfile.mkdtemp(prefix="arch-target-", dir=args.scratch.resolve()))
    try:
        # Mirror the target's Python/doc/script files so the move can be
        # computed without touching it (tracked + untracked, not ignored).
        listed = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", cwd=target).split("\0")
        for relative in filter(None, listed):
            source = target / relative
            if source.is_file() and not relative.startswith((".claude/", "Claude outputs/", "Microsoft/", ".v2c/")):
                destination = moved_target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        for name in ("module_moves.py", "module_moves.json"):
            shutil.copy2(BRANCH_ROOT / "scripts" / name, moved_target / "scripts" / name)
        subprocess.run([sys.executable, "-X", "utf8", str(BRANCH_ROOT / "scripts" / "module_moves.py"), "--root",
                        str(moved_target), "apply"], check=True)
        for status, relative in changes:
            ours_path = moved_target / relative
            theirs = blob(branch, relative)
            base_text = blob(reference, relative)
            if status == "A":
                if ours_path.is_file() and read(ours_path)[0] != theirs:
                    conflicts.append(f"{relative}: added on the branch but also present in the target")
                else:
                    planned.append(("A", relative, theirs, read(ours_path)[0] if ours_path.is_file() else None))
            elif status == "D":
                if ours_path.is_file() and read(ours_path)[0] != base_text:
                    conflicts.append(f"{relative}: deleted on the branch but changed in the target")
                else:
                    planned.append(("D", relative, None, read(ours_path)[0] if ours_path.is_file() else None))
            else:
                if not ours_path.is_file():
                    conflicts.append(f"{relative}: edited on the branch but missing in the target")
                    continue
                ours, _, _ = read(ours_path)
                if ours == base_text:
                    planned.append(("M", relative, theirs, ours))
                    continue
                with tempfile.TemporaryDirectory() as scratch:
                    files = []
                    for label, content in (("ours", ours), ("base", base_text or ""), ("theirs", theirs)):
                        path = Path(scratch) / label
                        path.write_text(content, encoding="utf-8", newline="\n")
                        files.append(str(path))
                    merged = subprocess.run(["git", "merge-file", "-p", *files], capture_output=True)
                if merged.returncode != 0:
                    inserted = anchored_insert(relative, base_text or "", theirs, ours)
                    if inserted is None:
                        conflicts.append(f"{relative}: both sides changed the same lines ({merged.returncode} conflict(s))")
                    else:
                        planned.append(("M", relative, inserted, ours))
                else:
                    planned.append(("M", relative, merged.stdout.decode("utf-8"), ours))
    finally:
        shutil.rmtree(moved_target, ignore_errors=True)

    for line in conflicts:
        print("CONFLICT", line)
    print(f"{len(planned)} edits merge cleanly, {len(conflicts)} conflict(s)")
    if conflicts or not args.write:
        return 1 if conflicts else 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = snapshot(target, f"backup before architecture hand-back {stamp} (not for merge)")
    git("branch", f"claude/arch-handback-backup-{stamp}", backup, cwd=target)
    print(f"backup of the target saved as claude/arch-handback-backup-{stamp} ({backup[:10]})")
    for name in ("module_moves.py", "module_moves.json"):
        shutil.copy2(BRANCH_ROOT / "scripts" / name, target / "scripts" / name)
    subprocess.run([sys.executable, "-X", "utf8", "scripts/module_moves.py", "apply"], cwd=target, check=True)
    drifted = [relative for _, relative, _, ours in planned
               if ((target / relative).is_file() and read(target / relative)[0]) != (ours if ours is not None else False)]
    if drifted:
        print("The target changed after the dry run; nothing merged. Restore from the backup branch or rerun:")
        for relative in drifted:
            print("  changed:", relative)
        return 2
    for status, relative, text, _ in planned:
        path = target / relative
        if status == "D":
            if path.exists():
                path.unlink()
            continue
        if path.is_file():
            _, bom, crlf = read(path)
        else:
            bom, crlf = False, False
        write(path, text, bom, crlf)
    print(f"applied {len(planned)} edits to {target}")
    catalog = subprocess.run([sys.executable, "-X", "utf8", "scripts/document_library.py", "build"], cwd=target)
    print("document catalog rebuilt" if catalog.returncode == 0 else "document catalog rebuild failed; run it by hand")
    return 0


if __name__ == "__main__":
    sys.exit(main())
