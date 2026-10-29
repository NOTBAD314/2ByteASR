r"""Put an exact copy of locked Hugging Face model files on a maintainer-owned ModelScope repository.

For models that only Hugging Face hosts (2026-10-22: the two MFA models, which
mainland users without a proxy cannot fetch from huggingface.co or
hf-mirror.com). The copy adds a download source, never a different model:
the downloader still checks every file against dependencies.lock.json.

    set MODELSCOPE_API_TOKEN=<访问令牌>
    .venv-main\Scripts\python.exe -X utf8 scripts\mirror_models_to_modelscope.py --namespace <空间名> --write-pin

For each --model (default: mfa_aligner and mfa_aligner_ja):

1. Fetch every locked file from huggingface.co at the locked revision into
   tmp/modelscope-mirror/ (or take it from --from KEY=DIR) and check its SHA-256
   against the lock. Nothing is uploaded unless every file matches.
2. Add the original model card (README.md at the same revision) and
   MIRROR_NOTICE.md (origin, license, file hashes).
3. Create <namespace>/<name> as a public model repository if needed and upload.
4. Read the newest commit and its file list through the public ModelScope API
   and require every locked file to carry the locked SHA-256.
5. Print the pin; --write-pin adds it to scripts/model_download_sources.json.

--dry-run stops after step 2. --verify-only skips steps 1–3 (for a copy uploaded
through the ModelScope web page). The token is read from the environment only.
Afterwards: python scripts/verify_model_download_sources.py --allow-network
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HF_ENDPOINT = "https://huggingface.co"
MODELSCOPE_API = "https://modelscope.cn/api/v1/models"
DEFAULT_MODELS = ("mfa_aligner", "mfa_aligner_ja")
NOTICE = "MIRROR_NOTICE.md"
# A fresh upload can take a little while to appear in the public file list.
REMOTE_ATTEMPTS = 6
REMOTE_DELAY_S = 10.0


class MirrorError(RuntimeError):
    pass


def _session():
    import requests
    from twobyteasr.local_models.download_diagnostics import AnonymousAuth
    session = requests.Session()
    session.trust_env = True
    session.auth = AnonymousAuth()
    return session


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locked_files(key: str, spec: dict) -> dict[str, str]:
    """Every required file with its locked SHA-256; refuses models without a full hash table."""
    hashes = {name: str(value).lower() for name, value in (spec.get("sha256") or {}).items()}
    files = list(spec.get("required_files") or ())
    missing = [name for name in files if name not in hashes]
    if not files or missing:
        raise MirrorError(f"{key}：锁定清单没有为每个文件写 SHA-256（{missing or '无文件'}），不能做可核对的副本")
    for name in files:
        if name.startswith(("/", ".")) or ".." in Path(name).parts or ":" in name:
            raise MirrorError(f"{key}：无效文件路径 {name!r}")
    return {name: hashes[name] for name in files}


def _hf_url(spec: dict, relative: str) -> str:
    return (f"{HF_ENDPOINT}/{spec['repository']}/resolve/{quote(spec['revision'], safe='')}/"
            f"{quote(relative, safe='/')}")


def _download(session, url: str, target: Path) -> None:
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    with session.get(url, stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for block in response.iter_content(1024 * 1024):
                stream.write(block)
    os.replace(partial, target)


def fetch_locked_files(key: str, spec: dict, folder: Path, session, source_dir: Path | None = None) -> None:
    for relative, expected in locked_files(key, spec).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and _sha256(target) == expected:
            print(f"[已核对] {key}/{relative}", flush=True)
            continue
        local = source_dir / relative if source_dir else None
        if local is not None and local.is_file() and _sha256(local) == expected:
            shutil.copy2(local, target)
            print(f"[本地] {key}/{relative}", flush=True)
            continue
        print(f"[下载] {key}/{relative}", flush=True)
        _download(session, _hf_url(spec, relative), target)
        actual = _sha256(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise MirrorError(f"{key}/{relative} 的 SHA-256 与锁定不同（{actual[:16]}…），未上传任何文件")


def write_model_card_and_notice(key: str, spec: dict, folder: Path, session, target: str) -> None:
    card = folder / "README.md"
    try:
        _download(session, _hf_url(spec, "README.md"), card)
    except Exception as exc:  # noqa: BLE001 - the notice still carries the attribution
        print(f"[提示] 没有取得原模型卡 README.md（{type(exc).__name__}），仅写 {NOTICE}", flush=True)
    origin = f"{HF_ENDPOINT}/{spec['repository']}/tree/{spec['revision']}"
    rows = "\n".join(f"| `{name}` | `{digest}` |" for name, digest in locked_files(key, spec).items())
    license_name = spec.get("license") or "见原仓库"
    (folder / NOTICE).write_text(
        f"# {target}\n\n"
        f"本仓库是 [{spec['repository']}]({origin})（提交 `{spec['revision']}`）的原样副本，"
        f"供 2ByteASR 在无法访问 Hugging Face 的网络下载。文件未做任何修改；版权归原作者，"
        f"许可证 {license_name}，详见原模型卡 README.md。\n\n"
        f"This repository is an unmodified copy of [{spec['repository']}]({origin}) at commit "
        f"`{spec['revision']}`, kept so that 2ByteASR can download it where Hugging Face is unreachable. "
        f"All rights remain with the original authors; license {license_name} (see README.md).\n\n"
        f"| 文件 / File | SHA-256 |\n|---|---|\n{rows}\n",
        encoding="utf-8", newline="\n")


def _hub_api(token: str):
    from modelscope.hub.api import HubApi
    api = HubApi()
    api.login(token)
    return api


def upload(api, target: str, folder: Path, spec: dict, key: str) -> None:
    api.create_repo(target, visibility="public", license=spec.get("license") or None,
                    chinese_name=None, exist_ok=True)
    api.upload_folder(repo_id=target, folder_path=str(folder),
                      commit_message=f"Exact copy of {spec['repository']}@{spec['revision']} ({key})",
                      ignore_patterns=["*.part", ".ms_upload_cache*"])


def remote_check(session, target: str, expected: dict[str, str], *, attempts: int | None = None,
                 delay: float | None = None) -> str:
    """Newest commit of ``target`` whose public file list carries every locked hash."""
    attempts = REMOTE_ATTEMPTS if attempts is None else attempts
    delay = REMOTE_DELAY_S if delay is None else delay
    problem = ""
    for attempt in range(1, attempts + 1):
        try:
            commits = session.get(f"{MODELSCOPE_API}/{target}/commits", timeout=(10, 40)).json()
            revision = str((((commits.get("Data") or {}).get("Commit") or [{}])[0]).get("Id") or "")
            if not revision:
                raise MirrorError("ModelScope 还没有返回提交号")
            listing = session.get(f"{MODELSCOPE_API}/{target}/repo/files",
                                  params={"Revision": revision, "Recursive": "true"}, timeout=(10, 40)).json()
            files = {item.get("Path"): item for item in ((listing.get("Data") or {}).get("Files") or [])}
            wrong = [name for name, digest in expected.items()
                     if str((files.get(name) or {}).get("Sha256") or "").lower() != digest]
            if not wrong:
                in_check = [name for name in expected if (files.get(name) or {}).get("InCheck")]
                if in_check:
                    print(f"[提示] ModelScope 仍在审核 {len(in_check)} 个文件；审核结束前下载可能失败", flush=True)
                return revision
            problem = f"提交 {revision[:12]} 上有 {len(wrong)} 个文件缺失或哈希不同：{wrong[:4]}"
        except Exception as exc:  # noqa: BLE001 - retried, then reported
            problem = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            print(f"[等待] {target}：{problem}；{delay:.0f} 秒后第 {attempt + 1}/{attempts} 次查询", flush=True)
            time.sleep(delay)
    raise MirrorError(f"{target} 核对失败：{problem}")


def write_pin(path: Path, key: str, repository: str, revision: str) -> None:
    """Add or replace one line in the ``modelscope`` object, keeping the file's layout and line endings."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace("\r\n", "\n").split("\n")
    entry = f'    "{key}": {json.dumps({"repository": repository, "revision": revision})}'
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == '"modelscope": {')
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() in ("}", "},"))
    except StopIteration:
        raise MirrorError(f"{path.name} 的格式和预期不同，请手动加入：{entry.strip()}") from None
    existing = next((i for i in range(start + 1, end) if lines[i].strip().startswith(f'"{key}":')), None)
    if existing is not None:
        lines[existing] = entry + ("," if lines[existing].rstrip().endswith(",") else "")
    else:
        if end - 1 > start:
            lines[end - 1] = lines[end - 1].rstrip().rstrip(",") + ","
        lines.insert(end, entry)
    text = newline.join(lines)
    if json.loads(text)["modelscope"][key] != {"repository": repository, "revision": revision}:
        raise MirrorError(f"写入 {path.name} 后核对失败")
    path.write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把锁定的 Hugging Face 模型文件原样放到维护者的 ModelScope 空间")
    parser.add_argument("--namespace", required=True, help="ModelScope 个人空间或组织名")
    parser.add_argument("--model", action="append", help="dependencies.lock.json 里的模型键；默认两个 MFA 模型")
    parser.add_argument("--from", dest="sources_from", action="append", default=[], metavar="KEY=DIR",
                        help="已有的本地模型目录（哈希相同的文件不再下载）")
    parser.add_argument("--dry-run", action="store_true", help="只下载并核对，不上传")
    parser.add_argument("--verify-only", action="store_true", help="只核对已上传的副本（例如网页上传后）")
    parser.add_argument("--write-pin", action="store_true", help="核对通过后写入 model_download_sources.json")
    parser.add_argument("--lock", type=Path, default=ROOT / "dependencies.lock.json")
    parser.add_argument("--sources", type=Path, default=ROOT / "scripts" / "model_download_sources.json")
    parser.add_argument("--work", type=Path, default=ROOT / "tmp" / "modelscope-mirror")
    args = parser.parse_args(argv)

    lock = json.loads(args.lock.read_text(encoding="utf-8-sig")).get("models") or {}
    keys = args.model or list(DEFAULT_MODELS)
    local_dirs = {}
    for item in args.sources_from:
        key, _, folder = item.partition("=")
        if not folder:
            parser.error(f"--from 需要 KEY=DIR：{item}")
        local_dirs[key] = Path(folder)
    unknown = [key for key in [*keys, *local_dirs] if key not in lock]
    if unknown:
        parser.error(f"锁定清单中没有：{unknown}")
    token = ""
    if not (args.dry_run or args.verify_only):
        token = os.environ.get("MODELSCOPE_API_TOKEN", "").strip()
        if not token:
            print("请先设置 MODELSCOPE_API_TOKEN（在 https://modelscope.cn 的“访问令牌”页创建）。")
            return 2

    session = _session()
    api = None
    pins = {}
    try:
        for key in keys:
            spec = lock[key]
            expected = locked_files(key, spec)
            target = f"{args.namespace}/{str(spec['repository']).split('/')[-1]}"
            if not args.verify_only:
                folder = args.work / key / str(spec["revision"])[:12]
                fetch_locked_files(key, spec, folder, session, local_dirs.get(key))
                write_model_card_and_notice(key, spec, folder, session, target)
                print(f"[通过] {key}：{len(expected)} 个文件与锁定 SHA-256 相同 → {folder}", flush=True)
                if args.dry_run:
                    continue
                api = api or _hub_api(token)
                print(f"[上传] {key} → {target}", flush=True)
                upload(api, target, folder, spec, key)
            revision = remote_check(session, target, expected)
            print(f"[通过] {target}@{revision}：{len(expected)} 个文件哈希与锁定相同", flush=True)
            pins[key] = dict(repository=target, revision=revision)
    except MirrorError as exc:
        print(f"[失败] {exc}", flush=True)
        return 1
    for key, pin in pins.items():
        line = f'"{key}": {json.dumps(pin)}'
        if args.write_pin:
            write_pin(args.sources, key, pin["repository"], pin["revision"])
            print(f"[已写入] {args.sources.name}：{line}", flush=True)
        else:
            print(f"[声明] 加入 {args.sources.name} 的 modelscope：{line}", flush=True)
    if pins:
        print("下一步：python -X utf8 scripts/verify_model_download_sources.py --allow-network", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
