"""Move twobyteasr modules into feature packages and rewrite every reference.

2026-10-15 architecture round.  The package used to be one flat folder of
~700 modules.  ``scripts/module_moves.json`` records where each module lives
now (old dotted name -> new dotted name).  This tool replays that mapping on
any checkout, so the same move can be applied to a later snapshot of the
shared working tree, or to a branch that still uses the old flat names,
without hand-merging a large diff.

Commands (run from the repository root):

    python -X utf8 scripts/module_moves.py apply  [--dry-run]
        Move files that are still at their old path and rewrite references
        in the repository's code, scripts, tests, packaging and current
        architecture documents.  Files already at the new path are left
        alone, so running it twice is harmless.

    python -X utf8 scripts/module_moves.py rewrite FILE [FILE ...]
        Only rewrite references inside the given files (for porting a
        branch or a patch that was written against the flat layout).

    python -X utf8 scripts/module_moves.py check
        List remaining references to old module names or old file paths.

What it rewrites, and why each rule exists:

* relative imports inside ``twobyteasr`` (``from .x import y``), resolved
  from the importing module's *old* location and re-expressed from its new
  location, so the existing relative-import style is kept;
* dotted names such as ``twobyteasr.x`` in imports, ``monkeypatch.setattr``
  strings, ``importlib.import_module`` and ``python -m`` arguments;
* ``from twobyteasr import x`` when ``x`` is a moved module;
* path spellings such as ``twobyteasr/x.py``, ``twobyteasr\\x.py`` and
  ``"twobyteasr" / "x.py"`` used by build scripts, workers and tests.

It never changes code behaviour beyond those names: no formatting, no
identifier renames.  Each file keeps its own UTF-8 BOM and line endings
(the shared tree mixes LF and CRLF files).  ``__file__``-relative path
arithmetic is NOT rewritten automatically; ``check`` lists the moved
modules that use ``__file__`` so a person can review each one.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "scripts" / "module_moves.json"
PACKAGE = "twobyteasr"

# Files whose references are rewritten.  Historical records (exec plans,
# ADRs, archived reports, release notes, changelogs) keep the names that
# were true when they were written; docs/CODE_MAP.md lists old -> new.
CODE_GLOBS = (
    "*.py", "*.bat", "pytest.ini",
    "twobyteasr/**/*.py", "tests/**/*.py", "scripts/**/*.py", "scripts/**/*.ps1",
    "scripts/**/*.mjs", "scripts/**/*.cjs", "scripts/**/*.js",
    "packaging/**/*.spec", "packaging/**/*.py", "packaging/**/*.ps1", "packaging/**/*.sh",
    "installer/**/*.iss", "launcher/**/*.cs", ".github/workflows/*.yml",
    "renderer/*.mjs", "renderer/*.cjs",
)
CURRENT_DOC_FILES = (
    "AGENTS.md", "ARCHITECTURE.md", "CONTRIBUTING.md",
    "docs/VERIFICATION.md", "docs/KNOWN_ISSUES.md",
    "docs/architecture/recognition.md", "docs/architecture/studio.md",
    "docs/architecture/packaging.md", "docs/architecture/platform-support.md",
    "docs/architecture/web-demo.md", "twobyteasr/locales/README.md",
)
SKIP_PARTS = {"__pycache__", "node_modules", "tmp", ".git", "third_party", "dist", "build", "archive"}


# ---------------------------------------------------------------- mapping

def load_mapping(path: Path = MAPPING_PATH) -> tuple[dict[str, str], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    moves = {old: new for old, new in data["moves"].items() if old != new}
    packages = dict(data.get("packages", {}))
    for old, new in moves.items():
        if not (old.startswith(PACKAGE + ".") and new.startswith(PACKAGE + ".")):
            raise ValueError(f"mapping must stay inside {PACKAGE}: {old} -> {new}")
    if len(set(moves.values())) != len(moves):
        raise ValueError("two modules map to the same new name")
    return moves, packages


def module_path(root: Path, dotted: str) -> Path:
    return root.joinpath(*dotted.split(".")).with_suffix(".py")


def package_of(dotted: str) -> str:
    return dotted.rpartition(".")[0]


# ------------------------------------------------------- text preservation

def read_text(path: Path) -> tuple[str, bool, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    text = raw.decode("utf-8")
    crlf = text.count("\r\n") > 0 and text.count("\r\n") == text.count("\n")
    return text.replace("\r\n", "\n"), bom, crlf


def write_text(path: Path, text: str, bom: bool, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)


# ------------------------------------------------------------- rewriting

class Rewriter:
    def __init__(self, moves: dict[str, str]):
        self.moves = moves
        # Longest first is not needed for correctness (the boundary check
        # prevents prefix matches) but keeps the alternation deterministic.
        olds = sorted((m[len(PACKAGE) + 1:] for m in moves), key=len, reverse=True)
        self.short_moves = {old[len(PACKAGE) + 1:]: new[len(PACKAGE) + 1:] for old, new in moves.items()}
        alternation = "|".join(re.escape(o) for o in olds) or "(?!)"
        # Not part of a longer name (``foo_twobyteasr``), but allowed right
        # after an escape sequence written in source text (``"\\ttwobyteasr/x.py"``).
        start = r"(?:(?<![\w.])|(?<=\\[tnr]))"
        self.dotted = re.compile(start + PACKAGE + r"\.(" + alternation + r")(?![\w])")
        self.slash_path = re.compile(start + PACKAGE + r"(/|\\\\|\\)(" + alternation + r")\.py\b")
        self.joined_path = re.compile(
            r"(['\"])" + PACKAGE + r"\1(\s*[/,]\s*)(['\"])(" + alternation + r")\.py\3")
        # ``from twobyteasr import x`` written inside strings (subprocess code,
        # fixtures).  Real import statements are handled through the AST.
        self.from_package = re.compile(
            r"(?<![\w.])from " + PACKAGE + r" import (\w+(?: as \w+)?(?:, *\w+(?: as \w+)?)*)")

    def _from_package(self, match: re.Match) -> str:
        items = []
        for chunk in match.group(1).split(","):
            name, _, alias = chunk.strip().partition(" as ")
            items.append((name.strip(), alias.strip()))
        parents = {package_of(self.moves[f"{PACKAGE}.{name}"]) if f"{PACKAGE}.{name}" in self.moves else PACKAGE
                   for name, _ in items}
        if len(parents) != 1 or parents == {PACKAGE}:
            return match.group(0)  # mixed or unmoved names: left for `check` to report
        rendered = []
        for name, alias in items:
            leaf = self.moves[f"{PACKAGE}.{name}"].rpartition(".")[2]
            local = alias or (name if leaf != name else "")
            rendered.append(leaf + (f" as {local}" if local else ""))
        return f"from {parents.pop()} import {', '.join(rendered)}"

    # dotted names, path strings ------------------------------------------
    def rewrite_names(self, text: str) -> str:
        text = self.from_package.sub(self._from_package, text)
        text = self.dotted.sub(lambda m: f"{PACKAGE}.{self.short_moves[m.group(1)]}", text)

        def slash(m: re.Match) -> str:
            sep = m.group(1)
            return PACKAGE + sep + self.short_moves[m.group(2)].replace(".", sep) + ".py"

        text = self.slash_path.sub(slash, text)

        def joined(m: re.Match) -> str:
            q1, glue, q2, old = m.group(1), m.group(2), m.group(3), m.group(4)
            parts = self.short_moves[old].split(".")
            middle = glue.join(f"{q2}{p}{q2}" for p in parts[:-1])
            return f"{q1}{PACKAGE}{q1}{glue}{middle}{glue}{q2}{parts[-1]}.py{q2}"

        return self.joined_path.sub(joined, text)

    # python imports ------------------------------------------------------
    def rewrite_python(self, text: str, old_name: str | None, new_name: str | None,
                       is_package_init: bool = False) -> str:
        """Rewrite imports of one Python file.

        ``old_name``/``new_name`` are the file's own dotted module names
        (both None for files outside the package, e.g. tests and scripts).
        """
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self.rewrite_names(text)
        lines = text.split("\n")
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line) + 1)
        edits: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            replacement = self._import_from(node, old_name, new_name, is_package_init)
            if replacement is None:
                continue
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            edits.append((start, end, replacement(text[start:end])))
        for start, end, new in sorted(edits, reverse=True):
            text = text[:start] + new + text[end:]
        return self.rewrite_names(text)

    def _resolve(self, node: ast.ImportFrom, current: str | None, is_package_init: bool) -> str:
        if not node.level:
            return node.module or ""
        if current is None:
            raise ValueError("relative import outside the package")
        base = current.split(".")
        if not is_package_init:
            base = base[:-1]
        if node.level > 1:
            base = base[: len(base) - (node.level - 1)]
        return ".".join(base + (node.module.split(".") if node.module else []))

    def _relative(self, target: str, current_new: str, is_package_init: bool) -> str:
        here = current_new.split(".")
        if not is_package_init:
            here = here[:-1]
        parts = target.split(".")
        common = 0
        while common < min(len(here), len(parts)) and here[common] == parts[common]:
            common += 1
        if common == 0:
            return target  # outside our tree: keep absolute
        dots = "." * (len(here) - common + 1)
        rest = ".".join(parts[common:])
        return dots + rest

    def _import_from(self, node, old_name, new_name, is_package_init):
        if node.level and old_name is None:
            return None
        base = self._resolve(node, old_name, is_package_init)
        if not (base == PACKAGE or base.startswith(PACKAGE + ".")):
            return None
        names = [alias.name for alias in node.names]
        # Case 1: `from <pkg> import a, b` where some names are modules.
        submodules = {n: f"{base}.{n}" for n in names if f"{base}.{n}" in self.moves}
        if submodules:
            groups: dict[str, list[ast.alias]] = {}
            for alias in node.names:
                full = f"{base}.{alias.name}"
                new_full = self.moves.get(full, full)
                parent = package_of(new_full) if full in self.moves else base
                groups.setdefault(parent, []).append(alias)
            if len(groups) == 1 and next(iter(groups)) == base and (not node.level or new_name == old_name):
                return None
            indent = " " * node.col_offset

            def render(segment: str, groups=groups, node=node, base=base) -> str:
                statements = []
                for parent, aliases in groups.items():
                    spec = self._spec(parent, node.level, new_name, is_package_init)
                    names = []
                    for a in aliases:
                        moved = self.moves.get(f"{base}.{a.name}")
                        new_leaf = moved.rpartition(".")[2] if moved else a.name
                        # A renamed module keeps its old local name, so the
                        # code below the import does not change.
                        local = a.asname or (a.name if new_leaf != a.name else None)
                        names.append(new_leaf + (f" as {local}" if local else ""))
                    statements.append(f"from {spec} import {', '.join(names)}")
                # Each group becomes its own statement at the original indent.
                return ("\n" + indent).join(statements)
            return render
        # Case 2: `from <module> import attrs`.
        new_base = self.moves.get(base, base)
        if new_base == base and (not node.level or new_name == old_name):
            return None
        spec = self._spec(new_base, node.level, new_name, is_package_init)
        old_spec = "." * node.level + (node.module or "")
        if spec == old_spec:
            return None
        pattern = re.compile(r"^(from\s+)" + re.escape(old_spec) + r"(\s+import\b)")

        def render(segment: str) -> str:
            result, count = pattern.subn(lambda m: m.group(1) + spec + m.group(2), segment, count=1)
            if not count:
                raise ValueError(f"could not rewrite import: {segment[:80]!r}")
            return result
        return render

    def _spec(self, target: str, level: int, new_name: str | None, is_package_init: bool) -> str:
        if not level or new_name is None:
            return target
        return self._relative(target, new_name, is_package_init)


# ------------------------------------------------------------- planning

def iter_files(root: Path, patterns) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            rel = path.relative_to(root)
            if not path.is_file() or SKIP_PARTS.intersection(rel.parts[:-1]):
                continue
            seen[rel.as_posix().lower()] = path
    return sorted(seen.values())


def own_module_name(root: Path, path: Path) -> tuple[str | None, bool]:
    rel = path.relative_to(root)
    if rel.parts[0] != PACKAGE:
        return None, False
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def apply(root: Path, dry_run: bool) -> int:
    moves, packages = load_mapping(root / "scripts" / "module_moves.json")
    rewriter = Rewriter(moves)
    pending_moves = []
    for old, new in sorted(moves.items()):
        src, dst = module_path(root, old), module_path(root, new)
        if src.is_file() and dst.exists():
            raise SystemExit(f"both old and new paths exist: {src} / {dst}")
        if src.is_file():
            pending_moves.append((old, new, src, dst))
        elif not dst.is_file():
            print(f"skip (missing in this tree): {old}")
    changed = 0
    files = iter_files(root, CODE_GLOBS)
    for path in files:
        name, is_init = own_module_name(root, path)
        # A file still at its old path resolves its relative imports from
        # there and re-expresses them from its new home; a file already in
        # place keeps resolving from where it is.
        old_name, new_name = name, moves.get(name, name) if name else None
        text, bom, crlf = read_text(path)
        if path.suffix == ".py":
            updated = rewriter.rewrite_python(text, old_name, new_name, is_init)
        else:
            updated = rewriter.rewrite_names(text)
        if updated != text:
            changed += 1
            if not dry_run:
                write_text(path, updated, bom, crlf)
    for doc in CURRENT_DOC_FILES:
        path = root / doc
        if path.is_file():
            text, bom, crlf = read_text(path)
            updated = rewriter.rewrite_names(text)
            if updated != text:
                changed += 1
                if not dry_run:
                    write_text(path, updated, bom, crlf)
    for package, doc in packages.items():
        init = root.joinpath(*package.split(".")) / "__init__.py"
        if not init.exists() and not dry_run:
            init.parent.mkdir(parents=True, exist_ok=True)
            write_text(init, f'"""{doc}"""\n', False, False)
    for old, new, src, dst in pending_moves:
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
    print(f"{len(pending_moves)} modules moved, {changed} files rewritten" + (" (dry run)" if dry_run else ""))
    return 0


def rewrite_files(root: Path, files: list[str]) -> int:
    moves, _ = load_mapping(root / "scripts" / "module_moves.json")
    rewriter = Rewriter(moves)
    reverse = {new: old for old, new in moves.items()}
    for item in files:
        path = Path(item).resolve()
        text, bom, crlf = read_text(path)
        try:
            name, is_init = own_module_name(root, path)
        except ValueError:
            name, is_init = None, False
        old_name = reverse.get(name, name) if name else None
        new_name = moves.get(name, name) if name else None
        if path.suffix == ".py":
            updated = rewriter.rewrite_python(text, old_name, new_name, is_init)
        else:
            updated = rewriter.rewrite_names(text)
        if updated != text:
            write_text(path, updated, bom, crlf)
            print("rewritten", item)
    return 0


def check(root: Path) -> int:
    moves, _ = load_mapping(root / "scripts" / "module_moves.json")
    rewriter = Rewriter(moves)
    problems = 0
    for path in iter_files(root, CODE_GLOBS) + [root / d for d in CURRENT_DOC_FILES if (root / d).is_file()]:
        text, _, _ = read_text(path)
        for regex in (rewriter.dotted, rewriter.slash_path, rewriter.joined_path):
            for match in regex.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                print(f"{path.relative_to(root)}:{line}: old reference {match.group(0)!r}")
                problems += 1
        for match in rewriter.from_package.finditer(text):
            names = [chunk.strip().partition(" as ")[0] for chunk in match.group(1).split(",")]
            if any(f"{PACKAGE}.{name}" in moves for name in names):
                line = text.count("\n", 0, match.start()) + 1
                print(f"{path.relative_to(root)}:{line}: old package import {match.group(0)!r}")
                problems += 1
    for old, new in sorted(moves.items()):
        if module_path(root, old).exists():
            print(f"not moved yet: {old}")
            problems += 1
        dst = module_path(root, new)
        if dst.is_file() and "__file__" in dst.read_text(encoding="utf-8-sig"):
            print(f"review __file__ use: {dst.relative_to(root)}")
    print(f"{problems} old references")
    return 1 if problems else 0


def table(root: Path, output: Path) -> int:
    """Write the human-readable old -> new table (docs/MODULE_MOVES.md)."""
    moves, packages = load_mapping(root / "scripts" / "module_moves.json")
    by_package: dict[str, list[tuple[str, str]]] = {}
    for old, new in sorted(moves.items()):
        by_package.setdefault(package_of(new), []).append((old, new))
    lines = [
        "# 模組搬移對照表（2026-10-15）",
        "",
        "由 `python -X utf8 scripts/module_moves.py table` 從 `scripts/module_moves.json` 產生，不要手改。",
        "按新資料夾分組；檔名加註「改名」的是搬家時一併改了名稱。用途說明見 [程式碼地圖](CODE_MAP.md)。",
        "",
    ]
    for package in sorted(by_package):
        doc = packages.get(package, "")
        lines += [f"## `{package.replace('.', '/')}/`", ""]
        if doc:
            lines += [doc, ""]
        lines += ["| 舊位置 | 新位置 |", "| --- | --- |"]
        for old, new in by_package[package]:
            note = "（改名）" if old.rpartition(".")[2] != new.rpartition(".")[2] else ""
            lines.append(f"| `{old.replace('.', '/')}.py` | `{new.replace('.', '/')}.py`{note} |")
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {output} ({len(moves)} moves)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--dry-run", action="store_true")
    p_rewrite = sub.add_parser("rewrite")
    p_rewrite.add_argument("files", nargs="+")
    sub.add_parser("check")
    p_table = sub.add_parser("table")
    p_table.add_argument("--output", type=Path, default=ROOT / "docs" / "MODULE_MOVES.md")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "apply":
        return apply(root, args.dry_run)
    if args.command == "rewrite":
        return rewrite_files(root, args.files)
    if args.command == "table":
        return table(root, args.output)
    return check(root)


if __name__ == "__main__":
    sys.exit(main())
