"""Read-only real project inputs; normal GUI on an owned private desktop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def dimensions(value):
    width, height = map(int, value.lower().split("x"))
    if min(width, height) < 500:
        raise argparse.ArgumentTypeError("Window dimensions must be at least 500 logical pixels")
    return [width, height]


def prepare(args):
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "tmp"):
        raise ValueError("Choose a fresh task output under repository tmp")
    project = args.project.resolve()
    raw = project.read_bytes()
    payload = json.loads(raw)
    project_id = str(payload.get("project_id", ""))
    if not project_id or len(payload.get("cues", [])) != 48:
        raise ValueError("This audit requires the explicitly selected real 48-cue project")
    if args.expected_project_id and project_id != args.expected_project_id:
        raise ValueError("Selected project identity does not match the operator's expected project ID")
    report = (args.report or Path(payload["report_path"])).resolve()
    report_payload = json.loads(report.read_text("utf8"))
    if report_payload.get("status") not in {"success", "degraded_success"}:
        raise ValueError("A real successful retained terminal report is required for completion replay")
    source_media = Path(payload["media"]["path"])
    if not source_media.is_file():
        raise ValueError("The project's actual source media is unavailable")
    source_root = (args.source_root or ROOT).resolve()
    if args.exe and args.source_root:
        raise ValueError("Choose a source snapshot or an exact EXE")
    if not args.exe and not (source_root / "quick_start.py").is_file():
        raise ValueError("Selected source snapshot has no normal quick_start.py entry")
    output.mkdir(parents=True)
    copied = output / "project" / project.name
    copied.parent.mkdir()
    copied.write_bytes(raw)
    copied_report = output / "retained-terminal.json"
    copied_report.write_bytes(report.read_bytes())
    originals = {str(path): digest(path) for path in (project, report, source_media)}
    source_files = ("studio/studio_workspace.py", "studio/studio_toolbar_layout.py", "design/studio_theme.py",
                    "design/theme_manager.py", "design/studio_qss.py", "design/control_qss.py", "design/surface_qss.py",
                    "design/main_ui_theme.py", "design/ui_theme.py", "design/typography.py")
    source_identity = {name: digest(source_root / "twobyteasr" / name) for name in source_files
                       if (source_root / "twobyteasr" / name).is_file()}
    plan = dict(project=str(copied), project_id=project_id, cue_count=48, report=str(copied_report),
                source_project=str(project), source_report=str(report), source_media=str(source_media),
                originals_sha256=originals, project_before_sha256=hashlib.sha256(raw).hexdigest(),
                speakers=[dict(id=row["id"], name=row.get("name", "")) for row in payload.get("speakers", [])],
                window_size=args.size, narrow_size=args.narrow_size, observe_only=args.observe_only,
                source_root=str(source_root), source_identity=source_identity, external_audit_only=bool(args.source_root),
                requested_scale=args.scale, terminal_origin="Actual retained report via _handle_result; no new ASR")
    (output / "toolbar-input.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), "utf8")
    return output, plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-project-id")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--source-root", type=Path, help="Existing read-only frozen source snapshot; only an external QA entry is loaded")
    parser.add_argument("--size", type=dimensions, default=[2048, 1105])
    parser.add_argument("--narrow-size", type=dimensions, default=[1000, 700])
    parser.add_argument("--scale", default="natural")
    parser.add_argument("--observe-only", action="store_true", help="Record baseline layout failures without stopping the later entry paths")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output, plan = prepare(args)
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, input=str(output / "toolbar-input.json")), ensure_ascii=False))
        return 0
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_STARTUP_TRACE=str(output / "startup-trace.jsonl"))
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO", "TWOBYTEASR_STARTUP_RAISE", "TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", "TWOBYTEASR_STARTUP_LEAVE_STUDIO"):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO="toolbar-scope",
               TWOBYTEASR_STARTUP_PROJECT=plan["project"], TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows", PYTHONUTF8="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    if args.scale == "natural":
        for key in ("QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI", "QT_SCALE_FACTOR_ROUNDING_POLICY"):
            env.pop(key, None)
    else:
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING="0", QT_FONT_DPI="96")
    source_root = Path(plan["source_root"])
    if args.exe:
        command = [str(args.exe.resolve())]
    elif args.source_root:
        bootstrap = output / "audit-bootstrap.py"
        # This overrides only the existing opt-in audit entry. All production
        # modules, assets and normal quick_start come from the untouched source.
        bootstrap.write_text("\n".join([
            "import importlib.util, os, runpy, sys",
            "from pathlib import Path",
            "sys.path.insert(0, " + repr(str(source_root)) + ")",
            "os.chdir(" + repr(str(source_root)) + ")",
            "from twobyteasr.test_isolation import install",
            "install()",
            "from twobyteasr.acceptance import studio_acceptance_audit as qa",
            "from twobyteasr.acceptance.blank_project_audit import install_offline_guards",
            "spec=importlib.util.spec_from_file_location('twobyteasr.acceptance.toolbar_scope_audit', " + repr(str(ROOT / "twobyteasr/acceptance/toolbar_scope_audit.py")) + ")",
            "audit=importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(audit)",
            "qa.isolate_acceptance_settings=install_offline_guards",
            "qa.start_acceptance=lambda window:audit.start(window, Path(os.environ['TWOBYTEASR_ACCEPTANCE_DIR']))",
            "runpy.run_path(" + repr(str(source_root / "quick_start.py")) + ", run_name='__main__')",
            "",
        ]), "utf8")
        command = [sys.executable, "-B", str(bootstrap)]
    else:
        command = [sys.executable, "-B", str(ROOT / "quick_start.py")]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=source_root, env=env, output=output / "process", timeout=300)
    receipt = output / "toolbar-result.json"
    result = json.loads(receipt.read_text("utf8")) if receipt.is_file() else dict(passed=False, error="No normal GUI receipt")
    after = {path: digest(path) for path in plan["originals_sha256"]}
    result.update(process_exit=code, originals_after_sha256=after, originals_unchanged=after == plan["originals_sha256"], actual_entry_command=command)
    transport_ok = bool(result.get("gui_shutdown") and code == 0 and result.get("provider_calls") == 0 and result["originals_unchanged"])
    result["passed"] = bool(result.get("passed") and transport_ok)
    result["driver_success"] = bool(transport_ok and (result["passed"] or (args.observe_only and result.get("observations_complete") and not result.get("error"))))
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(dict(passed=result["passed"], driver_success=result["driver_success"], checks=len(result.get("checks", [])),
                          error=result.get("error"), output=str(output)), ensure_ascii=False))
    return 0 if result["driver_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
