"""Offline checks for files intended to be published to GitHub."""

from __future__ import annotations

import re
import json
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".mimosa",
    ".venv-main",
    ".venv-moss",
    ".pytest_cache",
    "__pycache__",
    "archive",
    "backups",
    "models",
    "MOSS-Transcribe-Diarize",
    "FireRedASR2S",
    "outputs",
    "output",
    "tmp",
    "artifacts",
    "dist",
    "reports",
    "review_tracks",
}
FORBIDDEN_PREFIXES = (
    ".mimosa/",
    "archive/",
    "backups/",
    "models/",
    "outputs/",
    "reports/",
    "review_tracks/",
    "output/",
    "tmp/",
    "artifacts/",
    "dist/",
    "third_party/MOSS-Transcribe-Diarize/",
    "third_party/FireRedASR2S/",
)
FORBIDDEN_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".aac",
    ".safetensors",
    ".ckpt",
    ".pth",
    ".exe",
}
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".yml", ".yaml", ".bat", ".ps1", ".source"}
TEXT_NAMES = {".gitignore", ".gitattributes"}
GENERATED_BINARY_NAMES = {"2ByteASR.exe", "2ByteASR-Configure.exe", "ShortcutIdentity.exe"}
FORBIDDEN_SECRET_NAMES = {"secrets.json", "secrets.dat"}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{24,}\b"),
)
PRIVATE_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:\\Users\\[^\\\s]+\\", re.IGNORECASE),
)


def public_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            [
                "git",
                "-c",
                f"safe.directory={ROOT.as_posix()}",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            stderr=subprocess.DEVNULL,
        )
        if output:
            return [ROOT / item.decode("utf-8") for item in output.split(b"\0") if item]
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        pass
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name not in GENERATED_BINARY_NAMES
        and not any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts)
    ]


def approved_example_media(errors):
    """Exact, bounded public demos, already linked by the example READMEs."""
    manifest=ROOT/'examples/web-themes/release-media.json'
    if not manifest.exists():return set()
    approved=set();total=0
    try:
        entries=json.loads(manifest.read_text('utf8'))['files']
        for entry in entries:
            relative=entry['path'];path=(ROOT/relative).resolve()
            if not relative.startswith('examples/web-themes/') or '..' in Path(relative).parts or not path.is_relative_to(ROOT/'examples/web-themes') or path.suffix!='.mp4':
                raise ValueError('invalid example media path')
            size=path.stat().st_size;total+=size
            if size!=entry['bytes'] or size>2*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('example media size/hash mismatch: '+relative)
            approved.add(relative)
        if total>32*1024*1024:raise ValueError('public demo media exceeds 32 MiB')
    except (ValueError,KeyError,TypeError,OSError) as exc:
        errors.append('示例媒体 manifest 无效：'+str(exc));return set()
    return approved


def main() -> int:
    errors: list[str] = []
    approved_media=approved_example_media(errors)
    files = public_files()
    if not (ROOT / "LICENSE").is_file():
        errors.append("缺少 LICENSE")
    if not (ROOT / "THIRD_PARTY_NOTICES.md").is_file():
        errors.append("缺少 THIRD_PARTY_NOTICES.md")

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        # docs/reports/archive/ holds committed historical engineering evidence
        # (log excerpts quoted verbatim); local machine paths there are by
        # design and only the private-path rule is waived for it. Secrets,
        # forbidden suffixes and other rules still apply.
        is_evidence_archive = relative.startswith("docs/reports/archive/")
        if path.name.lower() in FORBIDDEN_SECRET_NAMES:
            errors.append(f"不应发布的密钥文件：{relative}")
        if relative.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"不应发布的路径：{relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES and relative not in approved_media:
            errors.append(f"不应发布的大文件类型：{relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        if path.suffix.lower() == ".bat":
            # cmd 对 LF 换行的 bat 会拆散 if/else 多行块（"exe 不是内部或外部命令"），必须 CRLF。
            if b"\r\n" not in path.read_bytes():
                errors.append(f"bat 必须使用 CRLF 换行：{relative}")
                continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"不是有效 UTF-8：{relative}")
            continue
        except FileNotFoundError:
            # 已从磁盘删除但仍留在 git 索引中的文件（待 git add -A 提交删除）
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"疑似真实密钥：{relative}")
                break
        for pattern in PRIVATE_PATH_PATTERNS:
            if not is_evidence_archive and pattern.search(text):
                errors.append(f"疑似本机用户绝对路径：{relative}")
                break

    if errors:
        print("[发布检查失败]")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1
    print(f"[发布检查通过] 已检查 {len(files)} 个公开候选文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
