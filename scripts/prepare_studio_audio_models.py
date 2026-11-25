"""Install the optional Studio audio assets into the current profile."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.media import vocal_enhancement as vocal
from twobyteasr.recognition import lyric_scene, lyrics_ctc
from twobyteasr.repository_download import preparation_lock


@dataclass(frozen=True)
class Asset:
    url: str
    name: str
    size: int
    sha256: str


CRISP = "https://github.com/CrispStrobe/CrispASR/releases/download/v0.8.55/"
DEMUCS = "https://huggingface.co/cstr/htdemucs-GGUF/resolve/e24b8c69380f69b5ad96d8fa5d0e01b1aa2867db/"
SYLLA = "https://huggingface.co/radiant-lyrics/sylla-600m-v1/resolve/0a228acf0c1351ad0e2734604ee921d497d861e8/"
YAMNET = Asset("https://www.kaggle.com/api/v1/models/google/yamnet/tfLite/classification-tflite/1/download",
               "yamnet-v1.tar.gz", 3_240_957, "1b971b2132760273a5fb8f5dc504e86783b27853bb3135d555ae06f1e1e365f3")
LITERT = Asset("https://files.pythonhosted.org/packages/ff/e8/86474c749bed207e61cb2637eed3ef8536b897f697001349660ec07939c4/"
               "ai_edge_litert-2.2.0-cp310-cp310-win_amd64.whl", "ai_edge_litert-2.2.0-cp310-cp310-win_amd64.whl",
               17_913_145, "0154ee9f3f942c9574ae2383d92b8da7857785fab4947d0b6a6db371471188b7")


def _matches(path, size, digest):
    return path.is_file() and path.stat().st_size == size and vocal._sha256(path, None) == digest


def _copy_bounded(source, target, byte_count):
    remaining = byte_count
    with target.open("wb") as output:
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError(f"Unexpected length of {target.name}")
            output.write(block)
            remaining -= len(block)
        if source.read(1):
            raise ValueError(f"Unexpected length of {target.name}")


def _fetch(asset, stage, cache):
    source = cache / asset.name if cache is not None else None
    if source is not None and source.is_file():
        if not _matches(source, asset.size, asset.sha256):
            raise ValueError(f"Invalid offline asset: {asset.name}")
        return source
    if cache is not None:
        raise FileNotFoundError(f"Missing offline asset: {asset.name}")
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry

    path = stage / asset.name
    print(f"Downloading {asset.name}", flush=True)
    try:
        with requests.Session() as session:
            session.mount("https://", HTTPAdapter(max_retries=Retry(
                total=2, backoff_factor=.5, status_forcelist=(429, 500, 502, 503, 504))))
            with session.get(asset.url, timeout=(20, 60), stream=True,
                             headers={"Accept-Encoding": "identity"}) as reply:
                reply.raise_for_status()
                if not reply.url.startswith("https://"):
                    raise ValueError(f"Unencrypted asset response: {asset.name}")
                _copy_bounded(reply.raw, path, asset.size)
    except requests.RequestException as exc:
        status = f" HTTP {exc.response.status_code}" if exc.response is not None else ""
        raise RuntimeError(f"Could not download {asset.name}: {type(exc).__name__}{status}") from None
    if not _matches(path, asset.size, asset.sha256):
        raise ValueError(f"Invalid downloaded asset: {asset.name}")
    return path


def _publish(source, target, stage):
    if target.exists():
        if not target.is_file() or vocal._sha256(source, None) != vocal._sha256(target, None):
            raise ValueError(f"Existing {target.name} differs from the verified asset")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asset-", dir=target.parent) as directory:
        ready = Path(directory) / target.name
        try:
            if source.parent != stage:
                shutil.copyfile(source, ready)
            else:
                os.link(source, ready)
        except OSError:
            shutil.copyfile(source, ready)
        os.replace(ready, target)


def _stage_vocal(paths, stage, cache, backend):
    stem = f"crispasr-windows-x86_64-{backend}"
    size, digest = {
        "cpu": (9_702_256, "f3b9643b7874e66cd366cda81d37d101677f18ab6e3a3255ff65dae19a439740"),
        "cuda": (788_371_022, "1ffe6eea9b1705f4585bd47fda83996a416e6918baac6f91bb2cd20350eb77a2"),
    }[backend]
    name = stem + ".zip"
    files = vocal._CUDA_FILES if backend == "cuda" else vocal._TOOL_FILES
    folder = "crispasr-cuda" if backend == "cuda" else "crispasr"
    target = vocal.managed_tools_root(paths) / folder
    model = Asset(DEMUCS + vocal._MODEL_NAME, vocal._MODEL_NAME, 84_329_376, vocal._MODEL_SHA256)
    weights = paths.model_root / "HTDemucs" / model.name
    if not _matches(weights, model.size, model.sha256):
        _publish(_fetch(model, stage, cache), weights, stage)
    if all((target / file).is_file() and vocal._sha256(target / file, None) == expected
           for file, expected in files.items()):
        return
    archive = _fetch(Asset(CRISP + name, name, size, digest), stage, cache)
    with ZipFile(archive) as bundle:
        for file in (*files, "LICENSE", "THIRD_PARTY_NOTICES.txt"):
            member = bundle.getinfo(f"{stem}/{file}")
            ready = stage / file
            with bundle.open(member) as source:
                _copy_bounded(source, ready, member.file_size)
            if file in files and vocal._sha256(ready, None) != files[file]:
                raise ValueError(f"CrispASR integrity check failed: {file}")
            _publish(ready, target / file, stage)


def _stage_lyrics(paths, stage, cache):
    target = paths.model_root / "Sylla-600M"
    sizes = {"config.json": 1863, "preprocessor_config.json": 229, "vocab.json": 12_488}
    files = [(name, sizes[name], digest) for name, digest in lyrics_ctc._CONFIGS.items()]
    files += [
        ("LICENSE", 35_149, "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"),
        ("NOTICE", 1519, "d0bd8c5c8b8b6679903e4ec359aed25a18d5cbbdf1408e17a7567a895749b8e6"),
        ("model.safetensors", 2_325_850_852, lyrics_ctc._SHA256),
    ]
    for name, size, digest in files:
        if not _matches(target / name, size, digest):
            _publish(_fetch(Asset(SYLLA + name, name, size, digest), stage, cache), target / name, stage)


def _stage_scene(paths, stage, cache):
    from twobyteasr.system.processes import run_hidden_subprocess

    if sys.platform != "win32" or sys.version_info[:2] != (3, 10) or sys.maxsize <= 2**32:
        raise ValueError("The pinned Studio scene runtime requires Windows x64 and the Python 3.10 main runtime")
    target = paths.model_root / "YAMNet"
    model = target / "yamnet.tflite"
    if not _matches(model, lyric_scene.MODEL_SIZE, lyric_scene.MODEL_SHA256):
        archive = _fetch(YAMNET, stage, cache)
        ready = stage / model.name
        with tarfile.open(archive, "r:gz") as bundle:
            member = bundle.getmember("1.tflite")
            if not member.isfile():
                raise ValueError("Missing YAMNet model payload")
            with bundle.extractfile(member) as source:
                _copy_bounded(source, ready, lyric_scene.MODEL_SIZE)
        if not _matches(ready, lyric_scene.MODEL_SIZE, lyric_scene.MODEL_SHA256):
            raise ValueError("Invalid YAMNet model payload")
    else:
        ready = model
    runtime = lyric_scene.managed_runtime_directory(paths)
    if not runtime.is_dir():
        wheel = _fetch(LITERT, stage, cache)
        runtime.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="litert-", dir=runtime.parent) as directory:
            staged = Path(directory) / "package"
            run_hidden_subprocess([sys.executable, "-m", "pip", "--disable-pip-version-check", "install",
                                   "--no-index", "--no-deps", "--target", str(staged), str(wheel)],
                                  purpose="Install pinned Studio LiteRT", check=True, timeout=120)
            os.replace(staged, runtime)
    _publish(ready, model, stage)


def main():
    from twobyteasr.runtime_paths import bootstrap_runtime_paths
    from twobyteasr.test_isolation import install

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", choices=("vocal-cpu", "vocal-cuda", "lyrics", "scene"))
    parser.add_argument("--offline-dir", type=Path, help="Use only the verified original files from this directory")
    args = parser.parse_args()
    install()
    paths = bootstrap_runtime_paths(install_root=ROOT, persist=False)
    paths.model_root.mkdir(parents=True, exist_ok=True)
    with preparation_lock(paths.model_root / ".studio-audio-prepare.lock"):
        with tempfile.TemporaryDirectory(prefix="studio-audio-", dir=paths.model_root) as directory:
            stage = Path(directory)
            if args.feature.startswith("vocal-"):
                _stage_vocal(paths, stage, args.offline_dir, args.feature.removeprefix("vocal-"))
            elif args.feature == "lyrics":
                _stage_lyrics(paths, stage, args.offline_dir)
            else:
                _stage_scene(paths, stage, args.offline_dir)
    print(f"Ready: {args.feature}", flush=True)


if __name__ == "__main__":
    main()
