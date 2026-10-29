"""Package layout guardrails (2026-10-15 architecture round).

The rules and their reasons are written up in twobyteasr/README.md.  These
checks only read source files (plus one stdlib-only import probe), so they
are fast and need no Qt, models or user data.
"""
import ast
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "twobyteasr"

# twobyteasr/ root: package entry, interface language, and modules that code
# outside the package loads by import name or file path from other Python
# environments (model workers, PowerShell `-m`, the runtime probe locator).
ROOT_MODULES = {
    "__init__", "__main__", "test_isolation", "i18n", "i18n_widgets",
    "model_integrity", "read_only_weights", "forced_alignment", "python_runtime_identity",
    "optional_speaker_evidence", "runtime_paths", "environment_probe",
    "download_sources", "environment_repair", "repository_download",
}
# Imported by model workers inside their own Python environments.
WORKER_IMPORTED = ("model_integrity", "read_only_weights", "forced_alignment",
                   "python_runtime_identity", "optional_speaker_evidence", "runtime_paths")
PACKAGES = {
    "app", "recognition", "providers", "glossary", "subtitle_rules", "projects", "timeline",
    "studio", "playback", "media", "exports", "caption_style", "caption_design", "rendering",
    "cover", "design", "local_models", "system", "storage", "diagnostics", "local_mcp", "acceptance",
}
# Packages whose modules must not load Qt at import time, with the named
# screen modules that are allowed to.
QT_FREE = {
    "subtitle_rules": set(), "system": set(), "media": set(),
    "recognition": {"recognition_history"},
    "providers": {"api_setup_dialog", "endpoint_editor_ui"},
    "storage": {"storage_ui", "storage_relocation_ui"},
    "local_models": {"model_storage", "model_workshop", "model_language_badges", "download_widgets"},
}
QT_ROOTS = ("PySide6", "qtawesome", "shiboken6")


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _python_files():
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _module_level_imports(path: Path) -> set[str]:
    """Absolute names imported while the module body runs (not inside functions)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    name = _module_name(path)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                for item in child.orelse:
                    visit(ast.Module(body=[item], type_ignores=[]))
                continue
            if isinstance(child, ast.Import):
                found.update(alias.name for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    base = package.split(".")[: len(package.split(".")) - (child.level - 1)]
                    module = ".".join(base + ([child.module] if child.module else []))
                else:
                    module = child.module or ""
                found.add(module)
                found.update(f"{module}.{alias.name}" for alias in child.names)
            visit(child)

    visit(tree)
    return found


def test_package_root_holds_only_entry_language_and_external_contract_modules():
    unexpected = sorted(p.stem for p in PKG.glob("*.py") if p.stem not in ROOT_MODULES)
    assert not unexpected, (
        "新模組請放進功能資料夾（見 twobyteasr/README.md）；根目錄只留外部程式直接載入的模組: "
        + ", ".join(unexpected))


def test_every_module_lives_in_a_known_feature_package():
    folders = {p.parent.relative_to(PKG).parts[0] for p in _python_files() if p.parent != PKG}
    assert folders <= PACKAGES, sorted(folders - PACKAGES)


def test_feature_package_inits_only_document_their_package():
    """Importing twobyteasr.<feature>.x must not load the rest of that feature."""
    for package in sorted(PACKAGES):
        init = PKG / package / "__init__.py"
        assert init.is_file(), f"{package}/__init__.py missing"
        assert not _module_level_imports(init), f"{package}/__init__.py imports at module level"


def test_product_code_does_not_import_acceptance_at_module_level():
    offenders = []
    for path in _python_files():
        if "acceptance" in path.relative_to(PKG).parts:
            continue
        hits = [m for m in _module_level_imports(path) if m.startswith("twobyteasr.acceptance")]
        if hits:
            offenders.append(f"{_module_name(path)} -> {sorted(hits)[0]}")
    assert not offenders, offenders


def test_logic_packages_do_not_load_qt_at_import_time():
    offenders = []
    for package, allowed in QT_FREE.items():
        for path in sorted((PKG / package).glob("*.py")):
            if path.stem in allowed:
                continue
            if any(m.split(".")[0] in QT_ROOTS for m in _module_level_imports(path)):
                offenders.append(f"{package}/{path.name}")
    assert not offenders, offenders


def test_foundation_packages_depend_only_on_root_modules_at_import_time():
    offenders = []
    for package in ("system", "diagnostics"):
        for path in sorted((PKG / package).glob("*.py")):
            for module in _module_level_imports(path):
                parts = module.split(".")
                if parts[0] != "twobyteasr" or len(parts) < 2:
                    continue
                if parts[1] in ROOT_MODULES or parts[1] == package:
                    continue
                offenders.append(f"{package}/{path.name} -> {module}")
    assert not offenders, sorted(set(offenders))


def test_worker_imported_modules_load_with_the_standard_library_only():
    """Model workers import these from other venvs that lack the GUI's packages."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            + "; ".join(f"import twobyteasr.{name}" for name in WORKER_IMPORTED)
            + "; bad = sorted(m for m in sys.modules if m.split('.')[0] in "
              "('PySide6', 'numpy', 'requests', 'shiboken6', 'qtawesome')); print(bad); "
              "raise SystemExit(1 if bad else 0)")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    completed = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(ROOT)], cwd=ROOT, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_module_move_table_matches_the_tree():
    from twobyteasr.diagnostics.build_identity import is_current_delivery_file
    moves = json.loads((ROOT / "scripts" / "module_moves.json").read_text(encoding="utf-8"))["moves"]
    for old, new in moves.items():
        if not is_current_delivery_file(new.replace('.', '/') + '.py'):
            continue  # retired modules remain in the historical move table
        assert not ROOT.joinpath(*old.split(".")).with_suffix(".py").exists(), f"old path still present: {old}"
        assert ROOT.joinpath(*new.split(".")).with_suffix(".py").is_file(), f"missing: {new}"
