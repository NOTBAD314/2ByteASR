"""Create the Montreal Forced Aligner runtime: ``<runtime root>\\mfa`` (2026-10-19).

MFA needs Kaldi, OpenFst and pynini, which only conda-forge builds for
Windows, so this runtime is a conda environment instead of a uv venv:

1. micromamba (conda-forge package ``micromamba``, pinned version and
   SHA-256 in ``dependencies.lock.json`` ``environments.mfa``);
2. ``micromamba create`` from the pinned explicit list
   ``scripts/mfa_runtime_win64.txt`` (every package checked against its md5);
3. three small pure-Python packages MFA's Chinese tokenizer needs, from PyPI
   with ``--require-hashes`` (not on conda-forge), and the two pkuseg models it
   loads (``<env>\\share\\pkuseg``, SHA-256 pinned; GitHub, then GitHub proxies);
4. a smoke test (``montreal_forced_aligner version`` and the tokenizers);
5. the completion marker ``conda-meta/2byteasr-mfa-runtime.json``.

Sources: conda.anaconda.org first, then the USTC and NJU mirrors (measured
2026-10-19: both serve identical files; TUNA/BFSU refused). With
``2BYTEASR_RUNTIME_SOURCE=mirror`` (a mainland download source chosen in the
download window) the mirrors come first. The env is created in place (conda
writes its own path into files; micromamba refuses an existing folder), with
the pending marker ``mfa.install-pending.json`` next to it until it is complete.

usage: python -I scripts/install_mfa_runtime.py [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

OFFICIAL = "https://conda.anaconda.org/conda-forge"
MIRRORS = ("https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge",
           "https://mirrors.nju.edu.cn/anaconda/cloud/conda-forge")
MARKER = "2byteasr-mfa-runtime.json"
PENDING = "mfa.install-pending.json"  # next to the env folder"


def say(text: str) -> None:
    print(text, flush=True)


def phase(name: str) -> None:
    say('[2BYTEASR_PHASE] ' + json.dumps({"phase": name}))


def spec() -> dict:
    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    return lock["environments"]["mfa"]


def channel_order() -> list[str]:
    if os.environ.get("2BYTEASR_RUNTIME_SOURCE", "") == "mirror":
        return [*MIRRORS, OFFICIAL]
    return [OFFICIAL, *MIRRORS]


def prefix() -> Path:
    from twobyteasr.recognition.mfa_aligner import runtime_prefix
    return runtime_prefix()


def _download(url: str, target: Path, sha256: str) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "2ByteASR"})
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    except Exception as exc:
        say(f"[运行库] 下载失败，换下一个来源：{url}（{type(exc).__name__}: {exc}）")
        return False
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != sha256:
        say(f"[运行库] 校验不符，换下一个来源：{url}")
        return False
    return True


def micromamba(work: Path, pinned: dict) -> Path:
    """micromamba.exe from the pinned conda-forge package (checked by SHA-256)."""
    exe = work / "micromamba.exe"
    if exe.is_file():
        return exe
    archive = work / pinned["file"].split("/")[-1]
    for base in channel_order():
        url = f"{base}/{pinned['file']}"
        say(f"[运行库] 获取 micromamba {pinned['version']}：{url}")
        if _download(url, archive, pinned["sha256"]):
            with tarfile.open(archive, "r:bz2") as package:
                member = package.getmember("Library/bin/micromamba.exe")
                with package.extractfile(member) as source, exe.open("wb") as out:
                    shutil.copyfileobj(source, out)
            archive.unlink()
            return exe
    raise RuntimeError("无法下载 micromamba（官方源与国内镜像都失败）。请检查网络后重试。")


def explicit_packages() -> list[tuple[str, str]]:
    """``(path under the channel, md5)`` of every pinned package, e.g. ``("win-64/kaldi-….conda", "…")``."""
    out = []
    for line in (ROOT / spec()["explicit"]).read_text(encoding="utf-8").splitlines():
        if line.startswith(OFFICIAL + "/"):
            url, _sep, md5 = line.partition("#")
            out.append((url[len(OFFICIAL) + 1:], md5.strip()))
    return out


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fetch_one(item: tuple[str, str], pkgs: Path) -> tuple[str, int, str]:
    """One package into the cache from the first source that serves it with the pinned md5."""
    relative, md5 = item
    target = pkgs / relative.split("/")[-1]
    if target.is_file() and _md5(target) == md5:
        return relative, target.stat().st_size, "cache"
    errors = []
    for base in channel_order():
        part = target.with_suffix(target.suffix + ".part")
        try:
            request = urllib.request.Request(f"{base}/{relative}", headers={"User-Agent": "2ByteASR"})
            with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
            if _md5(part) == md5:
                os.replace(part, target)
                return relative, target.stat().st_size, base
            errors.append(f"{base}: md5")
        except Exception as exc:
            errors.append(f"{base}: {type(exc).__name__}")
        part.unlink(missing_ok=True)
    raise RuntimeError(f"{relative} 下载失败（{'；'.join(errors)}）")


def fetch_packages(work: Path) -> dict:
    """Every pinned package into micromamba's cache, each from the first source that has it.

    Per file, not per channel: a mirror that has not synced the newest
    packages yet (2026-10-19: NJU/USTC lacked a package published the day
    before) only costs those files a second source.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    pkgs = work / "root" / "pkgs"
    pkgs.mkdir(parents=True, exist_ok=True)
    items = explicit_packages()
    done, total_bytes, used = 0, 0, {}
    say(f"[运行库] 下载 MFA 运行环境的 {len(items)} 个包（约 340 MB）")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(_fetch_one, item, pkgs) for item in items]):
            _relative, size, source = future.result()
            done += 1
            total_bytes += size
            used[source] = used.get(source, 0) + 1
            if done % 20 == 0 or done == len(items):
                say(f"[运行库] MFA 运行环境：{done}/{len(items)} 个包，{total_bytes / 1048576:.0f} MB")
    return used


def mamba_env(work: Path) -> dict:
    env = dict(os.environ)
    env["MAMBA_ROOT_PREFIX"] = str(work / "root")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("CONDA_PREFIX", None)
    return env


# The download script runs in the program folder, which in the packaged app holds PyInstaller's
# Python 3.10 .pyd files; `python -m` would put that folder first on sys.path and the env's 3.11
# loads the wrong _socket.pyd (2026-10-19). Every env python call: -I (3.11 adds no cwd) + a neutral cwd.
def create_env(exe: Path, work: Path, target: Path) -> dict:
    used = fetch_packages(work)
    say("[运行库] 正在组装 MFA 运行环境（不再联网）")
    result = subprocess.run([str(exe), "create", "-y", "--offline", "-p", str(target),
                             "--file", str(ROOT / spec()["explicit"])],
                            env=mamba_env(work), cwd=str(work), capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"MFA 运行环境组装失败：{(result.stderr or result.stdout or '')[-1200:]}")
    return used


def pip_install(target: Path, work: Path) -> None:
    from twobyteasr.download_sources import pip_index_urls
    lines = []
    for name, item in spec()["pip"].items():
        hashes = " ".join(f"--hash=sha256:{value}" for value in item["sha256"])
        lines.append(f"{name}=={item['version']} {hashes}")
    requirements = work / "mfa-pip.txt"
    requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")
    python = python_path(target)
    indexes = pip_index_urls()
    if os.environ.get("2BYTEASR_RUNTIME_SOURCE", "") == "mirror":
        indexes = indexes[1:] + indexes[:1]
    last = ""
    for index in indexes:
        result = subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-build-isolation",
                                 "--require-hashes", "--disable-pip-version-check", "--no-input", "--index-url", index,
                                 "-r", str(requirements)], env=activated(target), cwd=str(work), capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            return
        last = (result.stderr or result.stdout or "")[-800:]
        say(f"[运行库] PyPI 来源失败，换下一个：{index}")
    raise RuntimeError(f"MFA 中文分词依赖安装失败：{last}")


GITHUB_PROXIES = ("https://ghfast.top/", "https://ghproxy.net/", "https://gh-proxy.org/")  # as app/updater.py


def install_pkuseg(target: Path) -> None:
    """spacy_ontonotes (segmentation) and postag: pkuseg would fetch them from GitHub on first use."""
    import zipfile
    home = target / "share" / "pkuseg"
    home.mkdir(parents=True, exist_ok=True)
    for name, item in spec()["pkuseg"].items():
        archive = home / f"{name}.zip"
        if not (archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == item["sha256"]):
            say(f"[运行库] 下载中文分词模型 {name}（约 {item['bytes'] // 1048576} MB）")
            if not any(_download(prefix + item["url"], archive, item["sha256"]) for prefix in ("", *GITHUB_PROXIES)):
                raise RuntimeError(f"中文分词模型 {name} 下载失败（GitHub 与镜像都失败）。请检查网络后重试。")
        with zipfile.ZipFile(archive) as package:
            package.extractall(home / name)


def python_path(target: Path) -> Path:
    return target / ("python.exe" if os.name == "nt" else "bin/python")


def activated(target: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from mfa_aligner_worker import activated_environment
    env = activated_environment(target)
    env["MFA_ROOT_DIR"] = str(Path(tempfile.gettempdir()) / "2byteasr-mfa-check")
    return env


def smoke(target: Path) -> str:
    env = activated(target)
    python = str(python_path(target))
    version = subprocess.run([python, "-I", "-m", "montreal_forced_aligner", "version"], env=env, cwd=str(target),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    found = (version.stdout or "").strip().splitlines()[-1:] or [""]
    if version.returncode != 0 or found[0].strip() != spec()["packages"]["montreal-forced-aligner"]:
        raise RuntimeError(f"MFA 运行环境自检失败：{(version.stderr or version.stdout)[-800:]}")
    imports = subprocess.run([python, "-I", "-c", "import sudachipy, dragonmapper.hanzi, hanziconv, pynini, _kalpy, spacy_pkuseg; "
                              "assert spacy_pkuseg.pkuseg(postag=True).cut('今天天气很好')"],
                             env=env, cwd=str(target), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300)
    if imports.returncode != 0:
        raise RuntimeError(f"MFA 分词组件自检失败：{imports.stderr[-800:]}")
    return found[0].strip()


def ready(target: Path) -> bool:
    return (python_path(target).is_file() and (target / "conda-meta" / MARKER).is_file()
            and not (target.parent / PENDING).exists())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only report whether the runtime is complete")
    args = parser.parse_args()
    target = prefix()
    if args.check:
        say(json.dumps({"ready": ready(target), "prefix": str(target)}, ensure_ascii=False))
        return 0 if ready(target) else 1
    if os.name != "nt":
        raise SystemExit("MFA 运行环境目前只为 Windows 准备。")
    if ready(target):
        say(f"[跳过] MFA 运行环境已就绪：{target}")
        return 0
    phase("runtime_installing")
    pending = target.parent / PENDING
    if target.exists():
        if not (pending.exists() or (target / "conda-meta").is_dir()):
            raise RuntimeError(f"{target} 已存在且不是 MFA 运行环境，未改动。")
        say(f"[运行库] 清理上次未完成的 MFA 运行环境：{target}")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pinned = spec()
    pending.write_text(json.dumps({"started": time.time()}), encoding="utf-8")
    work = target.parent / "mfa-install"
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    exe = micromamba(work, pinned["micromamba"])
    sources = create_env(exe, work, target)
    pip_install(target, work)
    install_pkuseg(target)
    version = smoke(target)
    (target / "conda-meta" / MARKER).write_text(json.dumps({
        "montreal_forced_aligner": version, "explicit": pinned["explicit"],
        "explicit_sha256": hashlib.sha256((ROOT / pinned["explicit"]).read_bytes()).hexdigest(),
        "package_sources": sources, "micromamba": pinned["micromamba"]["version"],
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")
    pending.unlink()
    shutil.rmtree(work / "root", ignore_errors=True)  # package cache: the env keeps its own copies
    say(f"[运行库] MFA 运行环境就绪：{target}（MFA {version}，{time.perf_counter() - started:.0f} 秒）")
    phase("runtime_ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        say(f"[错误] {exc}")
        raise SystemExit(1)
