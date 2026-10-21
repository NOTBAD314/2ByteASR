# SPDX-License-Identifier: GPL-3.0-only
"""Repeatable Windows release: fixed build, Setup, component feed, sums, draft upload.

Typical next release (only the version file changes by hand):

    python scripts/sync_product_version.py              # after editing 2byteasr_version.json
    python -B scripts/release_pipeline.py freeze --version 0.6.6 --output tmp/release-066/build-r1
    python -B scripts/release_pipeline.py feed --build tmp/release-066/build-r1 --assets releases/0.6.6 \
        --notes-json docs/releases/0.6.6.in-app.json \
        --previous-manifest https://github.com/NOTBAD314/2ByteASR/releases/download/v0.6.5/2ByteASR-update.json
    python -B scripts/release_pipeline.py sources --build tmp/release-066/build-r1 --assets releases/0.6.6
    python -B scripts/release_pipeline.py sums --assets releases/0.6.6
    python -B scripts/release_signing.py sign --manifest releases/0.6.6/SHA256SUMS.txt
    python -B scripts/release_pipeline.py verify-source --build tmp/release-066/build-r1 --commit <commit>
    python -B scripts/release_pipeline.py upload --assets releases/0.6.6 --tag v0.6.6 --target <commit> \
        --notes-file docs/releases/0.6.6.md
    # after the owner publishes:
    python -B scripts/release_pipeline.py verify-public --tag v0.6.6 --assets releases/0.6.6
    # mainland mirror (token in ~/.config/gitcode/token.txt or GITCODE_TOKEN):
    python -B scripts/release_pipeline.py gitcode --tag v0.6.6 --assets releases/0.6.6

Rules: outputs are never overwritten; a published release or its assets are
never replaced (``upload`` refuses); the signing key stays outside the
repository; component archives whose content did not change are referenced
from the earlier release instead of being uploaded again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))  # gitcode_release

from twobyteasr.app.update_manifest import (  # noqa: E402
    APP_ID, ARCH, ARCHIVE_INDEX_NAME, COMPONENT_ORDER, COMPONENTS_FILENAME, PLATFORM, PRODUCT,
    UPDATE_MANIFEST_NAME, UPDATE_SCHEMA, UPDATE_SIGNATURE_NAME, build_installed_manifest,
    entries_from_record, environment_contracts, file_sha256, model_contracts, parse_update_manifest,
    parse_version, validate_installed_manifest, verify_manifest_signature,
)

REPOSITORY = "NOTBAD314/2ByteASR"
DOWNLOAD_BASE = f"https://github.com/{REPOSITORY}/releases/download"
STORED_SUFFIXES = {".whl", ".zip", ".gz", ".xz", ".7z", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".woff2"}
POWERSHELL = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def _write_json(path: Path, payload, *, exclusive: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _run(command, *, cwd: Path | None = None, env=None, log: Path | None = None) -> None:
    _log("run: " + " ".join(str(c) for c in command))
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as stream:
            subprocess.run([str(c) for c in command], cwd=cwd, env=env, check=True, stdout=stream,
                           stderr=subprocess.STDOUT)
    else:
        subprocess.run([str(c) for c in command], cwd=cwd, env=env, check=True)


def _version_file() -> dict:
    return json.loads((ROOT / "2byteasr_version.json").read_text("utf-8-sig"))


# --------------------------------------------------------------------------- freeze


def cmd_freeze(args) -> None:
    version = str(parse_version(args.version))
    declared = _version_file()
    if declared.get("version") != version:
        raise SystemExit(f"2byteasr_version.json says {declared.get('version')}, not {version}")
    _run([sys.executable, "-B", ROOT / "scripts" / "sync_product_version.py", "--check"])
    out = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    if out.exists():
        raise SystemExit(f"Output exists, never overwritten: {out}")
    _run([sys.executable, "-B", ROOT / "scripts" / "build_release.py", "--output", out,
          "--channel", f"release-{version}"])
    _finish(out, version)


# Payload scan findings a person has reviewed: (path, category) -> exact file SHA-256.
REVIEWED_PAYLOAD_FINDINGS = {
    # dotenv 17.3.1 README files show a truncated, non-functional RSA key placeholder ("Kh9NV...").
    ("renderer/node_modules/dotenv/README.md", "private_key"):
        "2d1919cb803aa866a036b5dd7ce2cb7237138e003a3e0307a809aab56ad3be08",
    ("renderer/node_modules/dotenv/README-es.md", "private_key"):
        "f959eeb6e96caa8cd4f47fa5a280465be0d263e12ee4a2768145558feab769dd",
}


def _review_payload_scan(payload: Path, scan: Path, review: Path) -> None:
    result = json.loads(scan.read_text("utf-8"))
    accepted, blocking = [], []
    for error in result.get("errors", []):
        expected = REVIEWED_PAYLOAD_FINDINGS.get((error["path"], error["category"]))
        actual = file_sha256(payload / error["path"]) if expected else ""
        (accepted if expected and actual == expected else blocking).append({**error, "sha256": actual or None})
    _write_json(review, {"scan": str(scan), "raw_passed": result.get("passed"), "accepted_reviewed": accepted,
                         "blocking": blocking, "passed": not blocking}, exclusive=False)
    if blocking:
        raise SystemExit(f"Payload scan has unreviewed findings: {blocking}")


def cmd_finish(args) -> None:
    out = Path(args.output).resolve()
    version = str(parse_version(args.version))
    if (out / "setup" / f"2ByteASR-Setup-{version}.exe").exists():
        raise SystemExit("Setup already built for this output")
    _finish(out, version)


def _finish(out: Path, version: str) -> None:
    stage, payload, evidence = out / "source", out / "payload" / "2ByteASR", out / "evidence"
    identity = json.loads((evidence / "2byteasr_build.json").read_text("utf-8"))
    if identity.get("app_version") != version:
        raise SystemExit("Build identity version mismatch")
    # The updater helper is compiled from the fixed snapshot, never the live tree.
    if not (payload / "2ByteASRUpdater.exe").is_file():
        _run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
              stage / "scripts" / "build_updater.ps1", "-Output", payload / "2ByteASRUpdater.exe"],
             log=evidence / "updater-build.log")
    manifest = build_installed_manifest(payload, version=version, build=identity)
    validate_installed_manifest(manifest)
    (payload / COMPONENTS_FILENAME).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    summary = {name: {k: v for k, v in record.items() if k != "files"}
               for name, record in manifest["components"].items()}
    _write_json(evidence / "components-summary.json", summary, exclusive=False)
    scan = subprocess.run([sys.executable, "-B", str(stage / "scripts" / "check_release_payload.py"), str(payload),
                           "--output", str(evidence / "payload-scan.json")], cwd=stage)
    _log(f"payload scan exit {scan.returncode}; reviewing findings")
    _review_payload_scan(payload, evidence / "payload-scan.json", evidence / "payload-scan-review.json")
    _run([sys.executable, "-B", stage / "scripts" / "verify_studio_build_truth.py", payload / "2ByteASR.exe",
          "--output", evidence / "build-truth.json"], cwd=stage, log=evidence / "build-truth.log")
    setup_dir = out / "setup"
    _run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", stage / "scripts" / "build_frozen_setup.ps1",
          "-PayloadDir", payload, "-ReleaseDir", setup_dir], log=evidence / "setup-build.log")
    setup = setup_dir / f"2ByteASR-Setup-{version}.exe"
    record = {"version": version, "identity": identity, "payload": str(payload), "stage": str(stage),
              "setup": {"path": str(setup), "size": setup.stat().st_size, "sha256": file_sha256(setup)},
              "components": summary, "frozen_at": datetime.now(timezone.utc).isoformat()}
    _write_json(evidence / "freeze.json", record)
    _log(f"frozen {version}: setup {record['setup']['size']} bytes {record['setup']['sha256']}")


# ----------------------------------------------------------------------------- feed


def _zip_component(payload: Path, name: str, record: dict, target: Path) -> None:
    entries = entries_from_record(record)
    index = {"component": name, "content_sha256": record["content_sha256"],
             "files": [e.as_list() for e in entries]}
    temporary = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(temporary, "x", allowZip64=True) as bundle:
        info = zipfile.ZipInfo(ARCHIVE_INDEX_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        bundle.writestr(info, json.dumps(index, ensure_ascii=False, separators=(",", ":")))
        for entry in entries:
            source = payload / entry.path
            if source.stat().st_size != entry.size:
                raise SystemExit(f"Payload changed after manifest: {entry.path}")
            info = zipfile.ZipInfo(entry.path, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = (zipfile.ZIP_STORED if source.suffix.lower() in STORED_SUFFIXES
                                  else zipfile.ZIP_DEFLATED)
            with source.open("rb") as reader, bundle.open(info, "w", force_zip64=True) as writer:
                digest = hashlib.sha256()
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(block)
                    digest.update(block)
            if digest.hexdigest() != entry.sha256:
                raise SystemExit(f"Payload changed after manifest: {entry.path}")
    os.replace(temporary, target)


def _load_previous(reference: str | None):
    if not reference:
        return None
    if reference.startswith("https://"):
        import requests
        manifest = requests.get(reference, timeout=(10, 60)).content
        signature = requests.get(reference + ".sig", timeout=(10, 60)).content
    else:
        manifest = Path(reference).read_bytes()
        signature = Path(reference + ".sig").read_bytes()
    verify_manifest_signature(manifest, signature)
    return json.loads(manifest.decode("utf-8"))


def cmd_feed(args) -> None:
    build = Path(args.build).resolve()
    freeze = json.loads((build / "evidence" / "freeze.json").read_text("utf-8"))
    version, payload = freeze["version"], Path(freeze["payload"])
    tag = args.tag or f"v{version}"
    base = (args.base_url.rstrip("/") + "/") if args.base_url else f"{DOWNLOAD_BASE}/{tag}/"
    assets = Path(args.assets).resolve()
    assets.mkdir(parents=True, exist_ok=True)
    manifest_path = assets / UPDATE_MANIFEST_NAME
    if manifest_path.exists():
        raise SystemExit(f"Manifest exists, never overwritten: {manifest_path}")
    installed = validate_installed_manifest(json.loads((payload / COMPONENTS_FILENAME).read_text("utf-8")))
    previous = _load_previous(args.previous_manifest)
    if previous and parse_version(previous["version"]) >= parse_version(version):
        raise SystemExit("Previous manifest is not older than this version")
    components, uploaded, reused = {}, [], []
    for name in COMPONENT_ORDER:
        record = installed["components"][name]
        entry = {k: record[k] for k in ("content_sha256", "file_count", "bytes")}
        earlier = (previous or {}).get("components", {}).get(name)
        if earlier and earlier.get("content_sha256") == record["content_sha256"] and earlier.get("archive"):
            entry["archive"] = earlier["archive"]  # identical content: reference the fixed earlier asset
            reused.append(name)
        elif args.skip_archives and name in args.skip_archives:
            entry["archive"] = None
        else:
            archive = assets / f"2ByteASR-{version}-{name}-{record['content_sha256'][:12]}.zip"
            if archive.exists():
                raise SystemExit(f"Archive exists, never overwritten: {archive}")
            _log(f"archive {name}: {record['file_count']} files, {record['bytes']} bytes")
            _zip_component(payload, name, record, archive)
            entry["archive"] = {"name": archive.name, "size": archive.stat().st_size,
                                "sha256": file_sha256(archive), "urls": [base + archive.name]}
            uploaded.append(name)
        components[name] = entry
    setup_src = Path(freeze["setup"]["path"])
    setup_name = setup_src.name
    if args.copy_setup:
        target = assets / setup_name
        if target.exists():
            raise SystemExit(f"Setup exists in assets, never overwritten: {target}")
        shutil.copy2(setup_src, target)
        if file_sha256(target) != freeze["setup"]["sha256"]:
            raise SystemExit("Setup copy mismatch")
    lock = json.loads((payload / "dependencies.lock.json").read_text("utf-8-sig"))
    notes = json.loads(Path(args.notes_json).read_text("utf-8")) if args.notes_json else {}
    manifest = {
        "schema": UPDATE_SCHEMA, "product": PRODUCT, "app_id": APP_ID, "version": version, "tag": tag,
        "channel": args.channel, "platform": PLATFORM, "arch": ARCH, "min_os_build": 17763,
        "published": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "release_page": args.release_page or f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        "notes": notes,
        "setup": {"name": setup_name, "size": freeze["setup"]["size"], "sha256": freeze["setup"]["sha256"],
                  "urls": [base + setup_name]},
        "components": components,
        "environments": environment_contracts(lock),
        "models": model_contracts(lock),
        "build": freeze["identity"],
        "data_migrations": [],
    }
    data = (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    parse_update_manifest(data, allow_http_local=bool(args.base_url))
    with manifest_path.open("xb") as stream:
        stream.write(data)
    _run([sys.executable, "-B", ROOT / "scripts" / "release_signing.py", "sign", "--manifest", manifest_path,
          "--out", assets / UPDATE_SIGNATURE_NAME])
    verify_manifest_signature(manifest_path.read_bytes(), (assets / UPDATE_SIGNATURE_NAME).read_bytes())
    _write_json(build / "evidence" / f"feed-{args.channel}-{version}.json",
                {"assets": str(assets), "uploaded_components": uploaded, "referenced_components": reused,
                 "manifest_sha256": file_sha256(manifest_path), "base_url": base}, exclusive=False)
    _log(f"feed {version}: new archives {uploaded}, referenced {reused}")


# -------------------------------------------------------------------------- sources


def cmd_sources(args) -> None:
    build = Path(args.build).resolve()
    freeze = json.loads((build / "evidence" / "freeze.json").read_text("utf-8"))
    assets = Path(args.assets).resolve()
    stage = Path(freeze["stage"])
    extract = build / "source-extract-check"
    _run([sys.executable, "-B", ROOT / "scripts" / "package_source_attachments.py", "--stage", stage,
          "--release", assets, "--extract", extract, "--review-commit", args.review_commit,
          "--exclude-prefix", *args.exclude_prefix])
    shutil.rmtree(extract, ignore_errors=True)
    for extra in args.extra or ():
        source = Path(extra)
        target = assets / source.name
        if target.exists():
            raise SystemExit(f"Exists, never overwritten: {target}")
        _log(f"copy fixed third-party material {source.name}")
        shutil.copy2(source, target)
        if file_sha256(source) != file_sha256(target):
            raise SystemExit("Copy mismatch: " + source.name)


# ----------------------------------------------------------------------------- sums


def cmd_sums(args) -> None:
    assets = Path(args.assets).resolve()
    target = assets / "SHA256SUMS.txt"
    if target.exists():
        raise SystemExit(f"Exists, never overwritten: {target}")
    lines = []
    for path in sorted(assets.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.name != target.name and path.suffix not in (".sha256",) \
                and not path.name.endswith((".tmp", ".part")) and path.name not in ("source-attachments.json",
                                                                                     "SHA256SUMS.txt.sig") \
                and not path.name.startswith(("draft-verification-", "public-verification-")):
            lines.append(f"{file_sha256(path)}  {path.name}")
    target.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    _log(f"SHA256SUMS: {len(lines)} files")


def upload_list(assets: Path) -> list[Path]:
    sums = (assets / "SHA256SUMS.txt").read_text("ascii").splitlines()
    names = [line.split("  ", 1)[1] for line in sums if line.strip()]
    signed = [assets / "SHA256SUMS.txt.sig"] if (assets / "SHA256SUMS.txt.sig").is_file() else []
    return [assets / name for name in names] + [assets / "SHA256SUMS.txt"] + signed


# --------------------------------------------------------------------------- upload


def _gh(*args, capture: bool = True) -> str:
    result = subprocess.run(["gh", *[str(a) for a in args]], check=True, capture_output=capture,
                            text=True, encoding="utf-8")
    return result.stdout if capture else ""


def _release_by_tag(tag: str) -> dict | None:
    releases = json.loads(_gh("api", f"repos/{REPOSITORY}/releases?per_page=100"))
    matches = [r for r in releases if r.get("tag_name") == tag]
    if len(matches) > 1:
        raise SystemExit(f"Several releases use tag {tag}; resolve manually")
    return matches[0] if matches else None


def cmd_upload(args) -> None:
    assets = Path(args.assets).resolve()
    files = upload_list(assets)
    for path in files:
        if not path.is_file():
            raise SystemExit(f"Missing asset listed in SHA256SUMS: {path}")
    tags = subprocess.run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{args.tag}"], capture_output=True,
                          text=True, cwd=ROOT, check=True).stdout.strip()
    release = _release_by_tag(args.tag)
    if release and not release.get("draft"):
        raise SystemExit(f"{args.tag} is already published; published assets are never replaced")
    if tags and not release:
        raise SystemExit(f"Tag {args.tag} already exists on the remote; not moving or reusing it")
    if release is None:
        command = ["release", "create", args.tag, "--repo", REPOSITORY, "--draft", "--target", args.target,
                   "--title", args.title, "--notes-file", args.notes_file]
        if args.prerelease:
            command.append("--prerelease")
        _gh(*command)
        release = _release_by_tag(args.tag)
    existing = {a["name"]: a for a in release.get("assets", [])}
    for path in files:
        local = {"size": path.stat().st_size, "sha256": file_sha256(path)}
        if path.name in existing:
            remote = existing[path.name]
            digest = str(remote.get("digest") or "").removeprefix("sha256:")
            if remote.get("size") != local["size"] or (digest and digest != local["sha256"]):
                raise SystemExit(f"Remote asset {path.name} differs from the local file; refusing to replace it")
            _log(f"already uploaded: {path.name}")
            continue
        for attempt in range(4):
            try:
                _log(f"upload {path.name} ({local['size']} bytes), attempt {attempt + 1}")
                _gh("release", "upload", args.tag, str(path), "--repo", REPOSITORY, capture=False)
                break
            except subprocess.CalledProcessError:
                # A failed upload may leave a broken asset; delete only that asset of this draft.
                fresh = {a["name"]: a for a in _release_by_tag(args.tag).get("assets", [])}
                broken = fresh.get(path.name)
                if broken and broken.get("state") != "uploaded":
                    _gh("api", "-X", "DELETE", f"repos/{REPOSITORY}/releases/assets/{broken['id']}")
                if attempt == 3:
                    raise
                time.sleep(15 * (attempt + 1))
    cmd_verify_draft(args)


def cmd_verify_draft(args) -> None:
    assets = Path(args.assets).resolve()
    release = _release_by_tag(args.tag)
    if release is None:
        raise SystemExit("Release not found")
    remote = {a["name"]: a for a in release.get("assets", [])}
    report = {"tag": args.tag, "draft": release.get("draft"), "prerelease": release.get("prerelease"),
              "html_url": release.get("html_url"), "target": release.get("target_commitish"), "assets": []}
    for path in upload_list(assets):
        item = remote.get(path.name)
        local_sha = file_sha256(path)
        digest = str((item or {}).get("digest") or "").removeprefix("sha256:")
        row = {"name": path.name, "local_size": path.stat().st_size, "local_sha256": local_sha,
               "remote_size": (item or {}).get("size"), "remote_digest": digest or None,
               "state": (item or {}).get("state")}
        row["ok"] = bool(item and row["remote_size"] == row["local_size"] and item.get("state") == "uploaded"
                         and (not digest or digest == local_sha))
        report["assets"].append(row)
    extra = sorted(set(remote) - {p.name for p in upload_list(assets)})
    report["unexpected_remote_assets"] = extra
    # Authenticated read-back of the small files (draft assets are not public).
    check = assets.parent / f".draft-readback-{args.tag}"
    shutil.rmtree(check, ignore_errors=True)
    check.mkdir()
    for name in (UPDATE_MANIFEST_NAME, UPDATE_SIGNATURE_NAME, "SHA256SUMS.txt", "SHA256SUMS.txt.sig"):
        if name in remote:
            for attempt in range(4):  # a just-uploaded asset can briefly fail to download
                try:
                    _gh("release", "download", args.tag, "--repo", REPOSITORY, "--pattern", name, "--dir", str(check))
                    break
                except subprocess.CalledProcessError:
                    if attempt == 3:
                        raise
                    time.sleep(10 * (attempt + 1))
            report.setdefault("readback", {})[name] = (file_sha256(check / name) == file_sha256(assets / name))
    shutil.rmtree(check, ignore_errors=True)
    report["all_ok"] = all(r["ok"] for r in report["assets"]) and not extra and all(report.get("readback", {}).values())
    out = assets / f"draft-verification-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    _write_json(out, report)
    _log(f"draft verification all_ok={report['all_ok']} -> {out}")
    if not report["all_ok"]:
        raise SystemExit(1)


# --------------------------------------------------------------------- verify-public


def cmd_verify_public(args) -> None:
    """Anonymous checks only: no token, no gh, no cookies."""
    import requests
    session = requests.Session()
    session.trust_env = False  # ignore netrc/proxy credentials from the environment
    session.headers.update({"User-Agent": "2ByteASR-release-verify"})
    assets = Path(args.assets).resolve()
    base = f"{DOWNLOAD_BASE}/{args.tag}/"
    report = {"tag": args.tag, "checked_at": datetime.now(timezone.utc).isoformat(), "anonymous": True, "assets": []}
    for path in upload_list(assets):
        url = base + path.name
        row = {"name": path.name, "url": url}
        try:
            response = session.get(url, stream=True, timeout=(10, 60), allow_redirects=True)
            row["status"] = response.status_code
            row["length"] = int(response.headers.get("Content-Length") or -1)
            if args.full or path.stat().st_size < 50 * 1024 * 1024:
                digest = hashlib.sha256()
                for block in response.iter_content(1024 * 1024):
                    digest.update(block)
                row["sha256_ok"] = digest.hexdigest() == file_sha256(path)
            response.close()
            row["ok"] = row["status"] == 200 and row["length"] == path.stat().st_size and row.get("sha256_ok", True)
        except Exception as exc:  # noqa: BLE001 - record and continue
            row["error"] = str(exc)[:300]
            row["ok"] = False
        report["assets"].append(row)
    latest = f"https://github.com/{REPOSITORY}/releases/latest/download/{UPDATE_MANIFEST_NAME}"
    try:
        manifest = session.get(latest, timeout=(10, 60)).content
        signature = session.get(latest + ".sig", timeout=(10, 60)).content
        verify_manifest_signature(manifest, signature)
        parsed = parse_update_manifest(manifest)
        urls = [parsed.setup.urls[0]] + [c.archive.urls[0] for c in parsed.components.values() if c.archive]
        reachable = {}
        for url in urls:
            response = session.head(url, timeout=(10, 60), allow_redirects=True)
            reachable[url] = response.status_code
        report["latest_feed"] = {"version": str(parsed.version), "signature_ok": True, "referenced": reachable,
                                 "ok": all(code == 200 for code in reachable.values())}
    except Exception as exc:  # noqa: BLE001
        report["latest_feed"] = {"ok": False, "error": str(exc)[:300]}
    report["all_ok"] = all(r["ok"] for r in report["assets"]) and report["latest_feed"].get("ok", False)
    out = assets / f"public-verification-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    _write_json(out, report)
    _log(f"public verification all_ok={report['all_ok']} -> {out}")
    if not report["all_ok"]:
        raise SystemExit(1)


# --------------------------------------------------------------------------- gitcode


def cmd_gitcode(args) -> None:
    """Mirror the published GitHub release to GitCode, then check it anonymously.

    Safe to run again: files already on GitCode are skipped. Older component
    archives that the update manifest still references are fetched from
    GitHub, checked against the signed manifest and added to their own tag.
    """
    import gitcode_release as gc
    assets = Path(args.assets).resolve()
    files = upload_list(assets)
    release = _release_by_tag(args.tag)
    if not release or release.get("draft"):
        raise SystemExit(f"{args.tag} is not published on GitHub; GitCode only mirrors published releases")
    manifest_bytes = (assets / UPDATE_MANIFEST_NAME).read_bytes()
    verify_manifest_signature(manifest_bytes, (assets / UPDATE_SIGNATURE_NAME).read_bytes())
    manifest = json.loads(manifest_bytes)
    if manifest.get("tag") != args.tag:
        raise SystemExit(f"{assets / UPDATE_MANIFEST_NAME} belongs to {manifest.get('tag')}, not {args.tag}")
    token = gc.read_token(Path(args.token_file) if args.token_file else None)
    client = gc.GitCode(token, log=_log)
    title = args.title or release.get("name") or args.tag
    notes = Path(args.notes_file).read_text("utf-8") if args.notes_file else (release.get("body") or args.tag)
    referenced = gc.referenced_archives(manifest, args.tag)
    tags = [args.tag] + sorted({item["tag"] for item in referenced})
    if not args.skip_push:
        _run(["git", "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main",
              *[f"refs/tags/{t}:refs/tags/{t}" for t in tags]], cwd=ROOT)
        gc.push_refs(ROOT, ["+refs/remotes/origin/main:refs/heads/main",
                            *[f"refs/tags/{t}:refs/tags/{t}" for t in tags]], token, log=_log)
    current = client.release(args.tag) or client.create_release(args.tag, title, notes,
                                                                bool(release.get("prerelease")))
    have = client.uploaded(current)
    for path in files:
        if path.name in have:
            _log(f"gitcode: already there: {args.tag}/{path.name}")
        else:
            client.upload(args.tag, path)
    cache = ROOT / "tmp" / "gitcode-referenced"
    for tag in tags[1:]:
        older = client.release(tag) or client.create_release(
            tag, f"2ByteASR {tag.lstrip('v')}（程序内更新组件镜像）", gc.COMPONENT_NOTES.format(tag=tag))
        have = client.uploaded(older)
        for item in referenced:
            if item["tag"] == tag and item["name"] not in have:
                path = gc.fetch_verified(item["github"], cache / tag / item["name"], item["size"], item["sha256"])
                client.upload(tag, path)
    if not release.get("prerelease"):
        client.mark_latest(args.tag, title, notes)
    _gitcode_verify(args, assets, files, referenced, release, gc)


def _gitcode_verify(args, assets: Path, files: list[Path], referenced: list[dict], release: dict, gc) -> None:
    handlers = [urllib.request.ProxyHandler({"https": args.verify_proxy, "http": args.verify_proxy}
                                           if args.verify_proxy else {})]
    opener = urllib.request.build_opener(*handlers)
    report = {"tag": args.tag, "checked_at": datetime.now(timezone.utc).isoformat(), "anonymous": True,
              "proxy": args.verify_proxy or "", "assets": [], "referenced": []}
    small = 50 * 1024 * 1024
    for path in files:
        size = path.stat().st_size
        row = gc.verify_download(f"{gc.DOWNLOAD}{args.tag}/{urllib.parse.quote(path.name)}", size,
                                 file_sha256(path) if args.full or size < small else None, opener=opener)
        report["assets"].append({"name": path.name, **row})
    for item in referenced:
        row = gc.verify_download(f"{gc.DOWNLOAD}{item['tag']}/{urllib.parse.quote(item['name'])}", item["size"],
                                 item["sha256"] if args.full or item["size"] < small else None, opener=opener)
        report["referenced"].append({"name": item["name"], "tag": item["tag"], **row})
    report["latest_tag"] = gc.GitCode().latest_tag()
    report["latest_ok"] = bool(release.get("prerelease")) or report["latest_tag"] == args.tag
    report["all_ok"] = (report["latest_ok"] and all(r["ok"] for r in report["assets"])
                        and all(r["ok"] for r in report["referenced"]))
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    out = assets / f"gitcode-verification-{stamp}.json"
    number = 1
    while out.exists():  # reports are never overwritten; a quick re-run gets its own file
        number += 1
        out = assets / f"gitcode-verification-{stamp}-{number}.json"
    _write_json(out, report)
    _log(f"gitcode verification all_ok={report['all_ok']} -> {out}")
    if not report["all_ok"]:
        raise SystemExit(1)


# --------------------------------------------------------------------- verify-source


def cmd_verify_source(args) -> None:
    """A clean checkout of the release commit must reproduce the build's source fingerprint."""
    import tempfile
    build = Path(args.build).resolve()
    identity = json.loads((build / "payload" / "2ByteASR" / "2byteasr_build.json").read_text("utf-8"))
    paths = sorted((p for p in (build / "evidence" / "source-paths.z").read_bytes().decode("utf-8").split("\0") if p),
                   key=str.lower)
    with tempfile.TemporaryDirectory(prefix="verify-source-", dir=ROOT / "tmp") as folder:
        checkout = Path(folder) / "checkout"
        subprocess.run(["git", "worktree", "add", "--detach", str(checkout), args.commit], cwd=ROOT, check=True,
                       capture_output=True)
        try:
            digest, missing, differing = hashlib.sha256(), [], []
            for rel in paths:
                path = checkout / rel
                if not path.is_file():
                    missing.append(rel)
                    continue
                data = path.read_bytes()
                if data != (build / "source" / rel).read_bytes():
                    differing.append(rel)
                raw = rel.encode("utf-8")
                digest.update(len(raw).to_bytes(4, "big"))
                digest.update(raw)
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(checkout)], cwd=ROOT, capture_output=True)
    report = {"commit": args.commit, "build_fingerprint": identity["source_sha256"], "inputs": len(paths),
              "checkout_fingerprint": digest.hexdigest(), "missing": missing, "differing": differing,
              "ok": digest.hexdigest() == identity["source_sha256"] and not missing and not differing}
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}))
    if not report["ok"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--version", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_freeze)
    p = sub.add_parser("finish", help="continue a freeze after a reviewed stop (no PyInstaller rerun)")
    p.add_argument("--version", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_finish)
    p = sub.add_parser("feed")
    p.add_argument("--build", required=True)
    p.add_argument("--assets", required=True)
    p.add_argument("--tag")
    p.add_argument("--channel", default="stable")
    p.add_argument("--base-url", help="QA only: local feed base URL instead of the GitHub release")
    p.add_argument("--release-page")
    p.add_argument("--notes-json")
    p.add_argument("--previous-manifest")
    p.add_argument("--skip-archives", nargs="*", default=[])
    p.add_argument("--no-copy-setup", dest="copy_setup", action="store_false",
                   help="QA feeds: reference the Setup without copying it into the assets folder")
    p.set_defaults(func=cmd_feed)
    p = sub.add_parser("sources")
    p.add_argument("--build", required=True)
    p.add_argument("--assets", required=True)
    p.add_argument("--review-commit", required=True)
    p.add_argument("--extra", nargs="*", help="Fixed third-party source archives to ship unchanged")
    p.add_argument("--exclude-prefix", nargs="*", default=["website/", "tests/"],
                   help="Non-build attachments left out of the public source package")
    p.set_defaults(func=cmd_sources)
    p = sub.add_parser("sums")
    p.add_argument("--assets", required=True)
    p.set_defaults(func=cmd_sums)
    p = sub.add_parser("upload")
    p.add_argument("--assets", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--notes-file", required=True)
    p.add_argument("--prerelease", action="store_true")
    p.set_defaults(func=cmd_upload)
    p = sub.add_parser("verify-draft")
    p.add_argument("--assets", required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(func=cmd_verify_draft)
    p = sub.add_parser("verify-public")
    p.add_argument("--assets", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_verify_public)
    p = sub.add_parser("gitcode", help="mirror the published release to GitCode (mainland download source)")
    p.add_argument("--assets", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--title", help="release title (default: the GitHub release title)")
    p.add_argument("--notes-file", help="release notes (default: the GitHub release body)")
    p.add_argument("--token-file", help="file holding only the GitCode token (default ~/.config/gitcode/token.txt "
                                         "or GITCODE_TOKEN)")
    p.add_argument("--skip-push", action="store_true", help="tags and main are already on GitCode")
    p.add_argument("--full", action="store_true", help="hash every file in the check, not only small ones")
    p.add_argument("--verify-proxy", help="check downloads through this proxy (e.g. a mainland relay)")
    p.set_defaults(func=cmd_gitcode)
    p = sub.add_parser("verify-source", help="clean checkout of the release commit reproduces the build fingerprint")
    p.add_argument("--build", required=True)
    p.add_argument("--commit", required=True)
    p.set_defaults(func=cmd_verify_source)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
