# SPDX-License-Identifier: GPL-3.0-only
"""Scan every blob reachable from the given refs before a repository goes public.

    python -B scripts/release_history_scan.py --refs origin/main origin/codex/x v0.1.5 --output report.json

Reports (never prints matched secret values): credential-like tokens, private
key blocks, DPAPI signing-key records, personal mail addresses outside
licence/notice files, developer home paths, media/model/archive files and
large blobs, each with the first commit path that contains it.  Pattern
scanning cannot prove that encrypted or obfuscated secrets are absent.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "credential": re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{32,}|sk-ant-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{30,}"
                             rb"|gh[pousr]_[A-Za-z0-9]{32,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}"
                             rb"|AIza[0-9A-Za-z_-]{35}|xox[abp]-[A-Za-z0-9-]{20,}|LTAI[0-9A-Za-z]{12,})"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED |DSA )?PRIVATE KEY-----"),
    "signing_key_record": re.compile(rb'"dpapi"\s*:\s*"[A-Za-z0-9+/=]{40,}'),
    "developer_home": re.compile(rb"(?i)[a-z]:[\\/]+users[\\/]+12[\\/]"),
    "personal_email": re.compile(rb"[A-Za-z0-9._%+-]+@(?:gmail|qq|163|126|outlook|hotmail|foxmail|icloud)\.com"),
}
MEDIA = {".wav", ".mp3", ".mp4", ".flv", ".mov", ".mkv", ".m4a", ".aac", ".flac"}
WEIGHTS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx"}
ARCHIVES = {".zip", ".7z", ".rar", ".exe", ".dll", ".whl", ".dmg"}
NOTICE_HINTS = ("license", "licence", "notice", "copying", "authors", "contributors", "third_party", "licenses/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refs", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--large", type=int, default=20 * 1024 * 1024)
    args = parser.parse_args()
    listing = subprocess.run(["git", "rev-list", "--objects", *args.refs], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode("utf-8", "replace").splitlines()
    paths = defaultdict(set)
    for line in listing:
        sha, _, path = line.partition(" ")
        if path:
            paths[sha].add(path)
    shas = list(paths)
    process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE)
    findings, files, counts = [], [], Counter()
    for sha in shas:
        process.stdin.write(sha.encode() + b"\n")
        process.stdin.flush()
        header = process.stdout.readline().split()
        if len(header) < 3:
            continue
        kind, size = header[1].decode(), int(header[2])
        data = process.stdout.read(size)
        process.stdout.read(1)
        if kind != "blob":
            continue
        counts["blobs"] += 1
        names = sorted(paths[sha])
        suffixes = {Path(n).suffix.lower() for n in names}
        if suffixes & MEDIA:
            files.append({"category": "media", "paths": names[:5], "bytes": size})
        if suffixes & WEIGHTS:
            files.append({"category": "model_weight_like", "paths": names[:5], "bytes": size})
        if suffixes & ARCHIVES:
            files.append({"category": "binary_archive", "paths": names[:5], "bytes": size})
        if size >= args.large:
            files.append({"category": "large_blob", "paths": names[:5], "bytes": size})
        if size > 50 * 1024 * 1024:
            continue
        for name, pattern in PATTERNS.items():
            matches = pattern.findall(data)
            if not matches:
                continue
            if name == "personal_email" and all(any(h in n.lower() for h in NOTICE_HINTS) for n in names):
                counts["email_in_notices"] += 1
                continue
            findings.append({"category": name, "paths": names[:5], "matches": len(matches), "blob": sha})
    process.stdin.close()
    process.wait()
    commits = subprocess.run(["git", "rev-list", "--count", *args.refs], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
    report = {"refs": args.refs, "commits": int(commits), "objects": len(listing), **counts,
              "findings": findings, "files": files,
              "limitations": "pattern scan only; values are not printed; encrypted/obfuscated secrets cannot be excluded"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    summary = Counter(f["category"] for f in findings)
    print(json.dumps({"commits": report["commits"], "blobs": counts["blobs"], "findings": dict(summary),
                      "files": dict(Counter(f["category"] for f in files))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
