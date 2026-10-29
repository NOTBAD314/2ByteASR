"""Proofread a fresh recognition result, then open Studio (real window).

2026-10-10 night (user): after proofreading, 打开字幕工作台 said 工程字幕数量或
文本时间摘要与已保存结果不一致. This copies the project and the glossary file
into a fresh tmp folder, stamps the copy as a fresh delivery of one
recognition job (the stamp a real recognition writes), and runs the normal
application on a private desktop twice: phase "edit" (result page →
proofreading edits → Studio after each kind of edit, safety refusals) and
phase "reopen" (a restart opens the saved project). The user's project,
media and glossary are only read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def deliver(source: Path, out: Path, job_id: str):
    """A stamped copy, as create_studio_outputs leaves a committed result."""
    from twobyteasr.recognition.recognition_result import committed_result_reference, media_identity_for_task, stamp_result
    from twobyteasr.projects.studio_project import load_project, save_project
    folder = out / "projects" / f"{source.stem}__{job_id}_1"
    for child in ("subtitles", "reports", "source", "autosave", "cache", "preview", "backup", "renders", "exports"):
        (folder / child).mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    target.write_bytes(source.read_bytes())
    project = load_project(target)
    identity = media_identity_for_task(project.media.path)
    stamp_result(project, target, job_id=job_id, media_identity=identity)
    save_project(project, target)
    reference = committed_result_reference(load_project(target), target)
    return target, json.dumps(reference, ensure_ascii=False), project.media.path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--glossary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Fresh repository tmp required")
    out.mkdir(parents=True)
    profile = out / "profile"
    local = profile / "local"
    (local / "2ByteASR").mkdir(parents=True)
    # Everything this script and the app write stays in the tmp profile.
    os.environ.update(LOCALAPPDATA=str(local), TWOBYTEASR_TEST_ROOT=str(profile))
    os.environ["2BYTEASR_USER_DATA_ROOT"] = str(local)
    data, glossary = args.project.read_bytes(), args.glossary.read_bytes()
    (local / "2ByteASR" / "learned_game_terms.json").write_bytes(glossary)
    project, reference, media = deliver(args.project.resolve(), out, "proofread-audit-job")
    other, other_reference, _media = deliver(args.project.resolve(), out, "proofread-other-job")
    (out / "delivery.json").write_text(json.dumps(dict(
        project_path=str(project), result_ref_json=reference, job_id="proofread-audit-job", media_path=media,
        other_project_path=str(other), other_result_ref_json=other_reference), ensure_ascii=False, indent=2), "utf8")
    (out / "seek").mkdir()
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="proofread-open", TWOBYTEASR_SEEK_CACHE_ROOT=str(out / "seek"),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows",
               PYTHONUTF8="1")
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    codes, results = {}, {}
    for phase in ("edit", "reopen"):
        # The audit guard wants the project inside the acceptance folder, so
        # both phases share it; the edit phase's files are kept under -edit names.
        phase_env = dict(env, TWOBYTEASR_AUDIT_PHASE=phase, TWOBYTEASR_STARTUP_PROJECT=str(project),
                         TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"))
        phase_env.update(TWOBYTEASR_STARTUP_OPEN_STUDIO="1") if phase == "reopen" else phase_env.update(
            TWOBYTEASR_STARTUP_RAISE="1")
        run = command
        if args.exe and args.exe.resolve() == ROOT / "2ByteASR.exe":
            # The root launcher hands over to the GUI; wait for the GUI itself.
            run = [sys.executable, str(ROOT / "scripts/verify_desktop_entry_bridge.py"), str(out), json.dumps(command)]
        codes[phase] = run_on_desktop(run, cwd=ROOT, env=phase_env, output=out / f"process-{phase}", timeout=900)
        path = out / "result.json"
        results[phase] = json.loads(path.read_text("utf8")) if path.exists() else {}
        for name in ("result.json", "startup.jsonl", "bridge-result.json"):
            if (out / name).exists():
                (out / name).replace(out / name.replace(".", f"-{phase}.", 1))
        if phase == "edit" and not (out / "expected.json").exists():
            break
    summary = dict(
        exit_codes=codes,
        original_project_unchanged=args.project.read_bytes() == data,
        original_glossary_unchanged=args.glossary.read_bytes() == glossary,
        original_sha256=hashlib.sha256(data).hexdigest(),
        phases={phase: dict(passed=value.get("passed"), checks=len(value.get("checks", [])),
                            failed=[x for x in value.get("checks", []) if not x["passed"]],
                            error=value.get("error"), gui_shutdown=value.get("gui_shutdown"))
                for phase, value in results.items()})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    ok = (all(value.get("passed") and value.get("gui_shutdown") for value in results.values())
          and all(code == 0 for code in codes.values()) and len(codes) == 2
          and summary["original_project_unchanged"] and summary["original_glossary_unchanged"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
