# SPDX-License-Identifier: GPL-3.0-only
"""Release QA on real Setup/installed EXE inside an isolated profile under tmp.

A profile folder holds an AUDIT install (``Programs/2ByteASR``), the
application's test root (``root``: LOCALAPPDATA, APPDATA, TEMP, USERPROFILE,
models, config) and evidence.  Setup runs with /AUDIT=1, so the real Start
menu, desktop, file associations and the real uninstall entry are not touched;
/AUDITSHORTCUTS writes the same shortcut into the profile for checking.

    python -B scripts/verify_release_install.py install --setup <Setup.exe> --profile tmp/x/profile --label v065
    python -B scripts/verify_release_install.py snapshot --profile ... --label after-upgrade
    python -B scripts/verify_release_install.py compare --profile ... --a before --b after
    python -B scripts/verify_release_install.py recognize --profile ... --media <wav> --label run1 [--backend sensevoice]
    python -B scripts/verify_release_install.py startup --profile ... --runs 3
    python -B scripts/verify_release_install.py uninstall --profile ... --label v065
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import winreg
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
AUDIT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}-IsolatedAudit_is1"
REAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}_is1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_paths(profile: Path) -> dict:
    profile = profile.resolve()
    if not profile.is_relative_to(ROOT / "tmp"):
        raise SystemExit("Profiles must stay in repository tmp")
    root = profile / "root"
    return {"profile": profile, "root": root, "install": profile / "Programs" / "2ByteASR",
            "local": root / "local", "data": root / "local" / "2ByteASR", "models": root / "models",
            "evidence": profile / "evidence", "shortcuts": profile / "shortcuts"}


def isolated_env(paths: dict) -> dict:
    root = paths["root"]
    for name in ("local", "roaming", "temp", "profile", "config", "models"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k.casefold() not in {"path", "pythonpath", "pythonhome", "virtual_env", "conda_prefix", "uv_cache_dir"}
           and not k.upper().startswith(("TWOBYTEASR_", "2BYTEASR_", "HF_", "MODELSCOPE_"))
           and not k.upper().endswith(("_API_KEY", "_TOKEN"))}
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env.update(Path=os.pathsep.join([system_root, str(Path(system_root) / "System32"),
                                     str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0")]),
               LOCALAPPDATA=str(root / "local"), APPDATA=str(root / "roaming"), TEMP=str(root / "temp"),
               TMP=str(root / "temp"), USERPROFILE=str(root / "profile"), TWOBYTEASR_TEST_ROOT=str(root),
               PYTHONUTF8="1")
    env["2BYTEASR_USER_DATA_ROOT"] = str(root / "local")
    return env


def received_bytes() -> int:
    """Machine-wide received bytes of physical adapters (an upper bound for downloads)."""
    output = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "(Get-NetAdapterStatistics | Measure-Object -Property ReceivedBytes -Sum).Sum"],
                            capture_output=True, text=True).stdout.strip()
    try:
        return int(output.split()[0])
    except (ValueError, IndexError):
        return -1


def registry_entry(key: str) -> dict | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            values = {}
            for name in ("DisplayVersion", "InstallLocation", "DisplayName", "UninstallString"):
                try:
                    values[name] = winreg.QueryValueEx(handle, name)[0]
                except OSError:
                    pass
            return values
    except OSError:
        return None


def tree_manifest(folder: Path, *, hash_limit: int | None = None) -> dict:
    rows = {}
    if not folder.exists():
        return rows
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            stat = path.stat()
            rows[path.relative_to(folder).as_posix()] = {
                "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                "sha256": sha(path) if hash_limit is None or stat.st_size <= hash_limit else None}
    return rows


def write(paths: dict, name: str, payload) -> Path:
    paths["evidence"].mkdir(parents=True, exist_ok=True)
    target = paths["evidence"] / name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    return target


def cmd_install(args) -> None:
    paths = profile_paths(Path(args.profile))
    env = isolated_env(paths)
    setup = Path(args.setup).resolve()
    paths["evidence"].mkdir(parents=True, exist_ok=True)
    real_before = registry_entry(REAL_KEY)
    before = tree_manifest(paths["install"], hash_limit=64 * 1024 * 1024)
    net0, started = received_bytes(), time.monotonic()
    command = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL", "/SP-", "/AUDIT=1",
               f"/DIR={paths['install']}", f"/LOG={paths['evidence'] / ('setup-' + args.label + '.log')}",
               f"/AUDITSHORTCUTS={paths['shortcuts']}", "/TASKS=desktopicon"]
    code = subprocess.run(command, env=env, timeout=1800).returncode
    elapsed = round(time.monotonic() - started, 3)
    after = tree_manifest(paths["install"], hash_limit=64 * 1024 * 1024)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k]["size"] != after[k]["size"]
                     or before[k]["sha256"] != after[k]["sha256"])
    version = json.loads((paths["install"] / "2byteasr_version.json").read_text("utf-8-sig")).get("version")
    shortcut = paths["shortcuts"] / "2ByteASR.lnk"
    record = {"label": args.label, "setup": str(setup), "setup_sha256": sha(setup), "exit_code": code,
              "seconds": elapsed, "installed_version": version, "files": len(after), "added": len(added),
              "removed": len(removed), "changed": len(changed), "removed_paths": removed[:200],
              "audit_registry": registry_entry(AUDIT_KEY), "real_registry_unchanged": registry_entry(REAL_KEY) == real_before,
              "shortcut": shortcut_target(shortcut) if shortcut.exists() else None,
              "machine_received_bytes": received_bytes() - net0 if net0 >= 0 else None,
              "finished": datetime.now(timezone.utc).isoformat()}
    write(paths, f"install-{args.label}.json", {**record, "manifest": after})
    print(json.dumps(record, ensure_ascii=False, indent=1)[:4000])
    if code != 0 or (args.expect_version and version != args.expect_version):
        raise SystemExit(1)


def shortcut_target(path: Path) -> dict:
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "[pscustomobject]@{target=$s.TargetPath;workdir=$s.WorkingDirectory;icon=$s.IconLocation}|ConvertTo-Json"
              % str(path).replace("'", "''"))
    output = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    return json.loads(output or "{}")


def cmd_uninstall(args) -> None:
    paths = profile_paths(Path(args.profile))
    env = isolated_env(paths)
    uninstaller = paths["install"] / "unins000.exe"
    before = tree_manifest(paths["install"], hash_limit=0)
    code = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/AUDIT=1",
                           f"/LOG={paths['evidence'] / ('uninstall-' + args.label + '.log')}"], env=env,
                          timeout=900).returncode
    time.sleep(3)  # the uninstaller stub deletes itself after returning
    remaining = sorted(p.relative_to(paths["install"]).as_posix() for p in paths["install"].rglob("*")
                       if p.is_file()) if paths["install"].exists() else []
    record = {"exit_code": code, "files_before": len(before), "remaining": remaining,
              "audit_registry_after": registry_entry(AUDIT_KEY)}
    write(paths, f"uninstall-{args.label}.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=1)[:3000])


def cmd_snapshot(args) -> None:
    paths = profile_paths(Path(args.profile))
    record = {"taken": datetime.now(timezone.utc).isoformat(), "machine_received_bytes": received_bytes()}
    for name in ("data", "models", "install"):
        record[name] = tree_manifest(paths[name], hash_limit=16 * 1024 * 1024)
    record["config"] = tree_manifest(paths["root"] / "config", hash_limit=None)
    target = write(paths, f"snapshot-{args.label}.json", record)
    print(json.dumps({k: (len(v) if isinstance(v, dict) else v) for k, v in record.items()}), target)


def cmd_compare(args) -> None:
    paths = profile_paths(Path(args.profile))
    a = json.loads((paths["evidence"] / f"snapshot-{args.a}.json").read_text("utf-8"))
    b = json.loads((paths["evidence"] / f"snapshot-{args.b}.json").read_text("utf-8"))
    report = {"a": args.a, "b": args.b}
    for name in ("data", "models", "config", "install"):
        left, right = a.get(name, {}), b.get(name, {})
        changed = sorted(k for k in set(left) & set(right)
                         if (left[k]["size"], left[k]["sha256"], left[k]["mtime_ns"] if left[k]["sha256"] is None else 0)
                         != (right[k]["size"], right[k]["sha256"], right[k]["mtime_ns"] if right[k]["sha256"] is None else 0))
        added = sorted(set(right) - set(left))
        report[name] = {"files_a": len(left), "files_b": len(right), "added": added[:300], "added_count": len(added),
                        "added_bytes": sum(right[k]["size"] for k in added),
                        "removed": sorted(set(left) - set(right))[:300], "changed": changed[:300],
                        "changed_count": len(changed)}
    if a.get("machine_received_bytes", -1) >= 0 and b.get("machine_received_bytes", -1) >= 0:
        report["machine_received_bytes_between"] = b["machine_received_bytes"] - a["machine_received_bytes"]
    write(paths, f"compare-{args.a}-{args.b}.json", report)
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if not isinstance(vv, list) or kk in ("removed",)}
                          if isinstance(v, dict) else v) for k, v in report.items()}, ensure_ascii=False, indent=1)[:5000])


def _settings_for(backend: str) -> dict:
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    models = settings.setdefault("models", {})
    if backend == "sensevoice":
        models.update(primary_asr_backend="sensevoice", firered_asr_backend="off", qwen_asr_backend="off")
    elif backend == "quality":
        models.update(primary_asr_backend="moss", firered_asr_backend="local", qwen_asr_backend="local")
    settings.setdefault("switches", {}).update(enable_ai_polish=False, use_ai_grouping=False)
    return settings


def cmd_recognize(args) -> None:
    """Home → add media → Start, in the installed EXE, with the profile's own runtimes and models."""
    paths = profile_paths(Path(args.profile))
    env = isolated_env(paths)
    # Acceptance output must contain LOCALAPPDATA/APPDATA, so it is the test root itself.
    out = paths["root"]
    run_dir = out / f"recognize-{args.label}"
    if run_dir.exists():
        raise SystemExit(f"exists: {run_dir}")
    run_dir.mkdir(parents=True)
    (out / "perf-recognition.json").unlink(missing_ok=True)
    media = run_dir / Path(args.media).name
    shutil.copy2(args.media, media)
    config = paths["root"] / "config" / "2byteasr_settings.json"
    if args.backend and not config.exists():
        config.write_text(json.dumps(_settings_for(args.backend), ensure_ascii=False, indent=2), "utf-8")
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    startup_project = save_project(SubtitleProject(media=StudioMedia(path=str(media), duration_ms=1000),
                                                   cues=[StudioCue("c1", 0, 900, "placeholder")]),
                                   run_dir / "startup-project.2byteproj")
    # The Home acceptance hook requires an explicit, hashed declaration of the
    # runtimes and model root it may use; here they are the profile's own ones
    # (downloaded by the installed program), read from its runtime registry.
    registry = json.loads((paths["data"] / "runtimes" / "registry.json").read_text("utf-8"))["runtimes"]
    roles = {}
    for role, row in registry.items():
        python = Path(row["python_executable"])
        config = python.parent.parent / "pyvenv.cfg"
        roles[role] = {"python": str(python), "python_sha256": sha(python),
                       "venv_config": str(config), "venv_config_sha256": sha(config)}
    if "moss" not in roles:  # the hook insists on both; a light profile reuses main for the declaration only
        roles["moss"] = dict(roles["main"])
    sentinels = []
    for folder in sorted(p for p in paths["models"].iterdir() if p.is_dir()):
        candidate = next((p for p in sorted(folder.rglob("*.json")) if p.stat().st_size < 1_000_000), None)
        if candidate:
            sentinels.append({"path": str(candidate), "sha256": sha(candidate)})
    manifest_path = run_dir / "own-resources.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "roles": roles, "model_root": {
        "path": str(paths["models"]), "sentinels": sentinels}}, ensure_ascii=False, indent=1), "utf-8")
    env["TWOBYTEASR_LIVE_BORROWED_RESOURCES"] = str(manifest_path)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO="perf-recognition", TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_TRACE=str(run_dir / "startup.jsonl"),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", PERF_RECOGNITION_MEDIA=str(media),
               PERF_RECOGNITION_RUNS=str(args.runs), TWOBYTEASR_STARTUP_PROJECT=str(startup_project),
               PERF_TIMEOUT_S=str(max(120, args.timeout - 120)), QT_QPA_PLATFORM="windows")
    net0 = received_bytes()
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([str(paths["install"] / "2ByteASR.exe")], cwd=paths["install"], env=env,
                          output=run_dir / "process", timeout=args.timeout)
    result_path = out / "perf-recognition.json"
    if result_path.is_file():
        shutil.copy2(result_path, run_dir / "perf-recognition.json")
    result = json.loads(result_path.read_text("utf8")) if result_path.is_file() else {}
    outputs = sorted(p.relative_to(paths["root"]).as_posix() for p in paths["root"].rglob("*")
                     if p.is_file() and p.suffix.lower() in (".srt", ".ass", ".2byteproj", ".json")
                     and p.stat().st_mtime > run_dir.stat().st_ctime and "recognize-" not in p.as_posix())
    summary = {"exit_code": code, "finished": result.get("finished"), "errors": result.get("errors"),
               "runs": [{k: r.get(k) for k in ("wall_s", "statuses")} for r in result.get("runs", [])],
               "new_output_files": outputs[:50],
               "machine_received_bytes": received_bytes() - net0 if net0 >= 0 else None}
    write(paths, f"recognize-{args.label}.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:4000])


def cmd_startup(args) -> None:
    """Measure process start → first interactive mark of the installed EXE (normal startup, no audit)."""
    paths = profile_paths(Path(args.profile))
    env = isolated_env(paths)
    rows = []
    for index in range(args.runs):
        trace = paths["evidence"] / f"startup-{args.label}-{index}.jsonl"
        trace.unlink(missing_ok=True)
        env.update(TWOBYTEASR_STARTUP_TRACE=str(trace), TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE="1",
                   TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows")
        if args.disable_update_check:
            env["TWOBYTEASR_DISABLE_UPDATE_CHECK"] = "1"
        else:
            env.pop("TWOBYTEASR_DISABLE_UPDATE_CHECK", None)
        launched = time.time()
        code = subprocess.run([str(paths["install"] / "2ByteASR.exe")], cwd=paths["install"], env=env,
                              timeout=300).returncode
        marks = {}
        if trace.is_file():
            for line in trace.read_text("utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                marks.setdefault(item.get("stage") or item.get("mark") or item.get("event"), item)
        interactive = marks.get("INTERACTIVE") or {}
        rows.append({"run": index, "exit_code": code, "launched_epoch": launched,
                     "interactive": interactive, "marks": sorted(k for k in marks if k)})
    write(paths, f"startup-{args.label}.json", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=1)[:4000])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install"); p.add_argument("--setup", required=True); p.add_argument("--profile", required=True)
    p.add_argument("--label", required=True); p.add_argument("--expect-version"); p.set_defaults(func=cmd_install)
    p = sub.add_parser("uninstall"); p.add_argument("--profile", required=True); p.add_argument("--label", required=True)
    p.set_defaults(func=cmd_uninstall)
    p = sub.add_parser("snapshot"); p.add_argument("--profile", required=True); p.add_argument("--label", required=True)
    p.set_defaults(func=cmd_snapshot)
    p = sub.add_parser("compare"); p.add_argument("--profile", required=True); p.add_argument("--a", required=True)
    p.add_argument("--b", required=True); p.set_defaults(func=cmd_compare)
    p = sub.add_parser("recognize"); p.add_argument("--profile", required=True); p.add_argument("--media", required=True)
    p.add_argument("--label", required=True); p.add_argument("--backend", choices=["sensevoice", "quality"])
    p.add_argument("--runs", type=int, default=1); p.add_argument("--timeout", type=int, default=3600)
    p.set_defaults(func=cmd_recognize)
    p = sub.add_parser("startup"); p.add_argument("--profile", required=True); p.add_argument("--label", required=True)
    p.add_argument("--runs", type=int, default=3); p.add_argument("--disable-update-check", action="store_true")
    p.set_defaults(func=cmd_startup)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
