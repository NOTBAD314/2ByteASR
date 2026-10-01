# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import shutil
import json
import sys

from PyInstaller.utils.hooks import collect_data_files


ROOT = Path(SPECPATH).resolve().parent
NODE = ROOT / 'tools/node/node.exe'
if not NODE.is_file():
    raise RuntimeError("The application-owned tools/node/node.exe is required to build the renderer")

datas = collect_data_files("certifi")
build_metadata = Path(
    os.environ.get("TWOBYTEASR_BUILD_METADATA", ROOT / "build" / "2byteasr_build.json")
)
if not build_metadata.is_file():
    raise RuntimeError(f"Build identity metadata is missing: {build_metadata}")
datas.append((str(build_metadata), "."))
# Public bundles always ship factory defaults, never this machine's settings.
sys.path.insert(0, str(ROOT))
from twobyteasr.settings import DEFAULT_SETTINGS
defaults_dir = ROOT / 'tmp' / 'frozen-defaults'
defaults_dir.mkdir(parents=True, exist_ok=True)
(defaults_dir / '2byteasr_settings.json').write_text(
    json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2), encoding='utf-8')
datas.append((str(defaults_dir / '2byteasr_settings.json'), '.'))
if os.environ.get('TWOBYTEASR_QA_BUILD') == '1':
    marker = defaults_dir / '2byteasr-qa-profile.marker'
    marker.write_text('Isolated QA build: uses install/tmp/qa-profile.\n', encoding='utf-8')
    datas.append((str(marker), '.'))
for source, destination in (
    ("assets", "assets"),
    ("licenses", "licenses"),
    ("docs/design/caption-preferences.json", "docs/design"),
    ("lexicons", "lexicons"),
    ("renderer", "renderer"),
    ("scripts", "scripts"),
    ("third_party", "third_party"),
    ("tools/ffmpeg", "tools/ffmpeg"),
    ("tools/mpv", "tools/mpv"),
):
    path = ROOT / source
    if path.exists():
        datas.append((str(path), destination))

# Only locally present wheels with published upstream checksums are bundled.
# The manifest is part of the source/build identity and verified again at use.
_wheel_manifest = ROOT / 'packaging' / 'model_wheels.json'
if _wheel_manifest.is_file():
    import hashlib
    _wheel_contract = json.loads(_wheel_manifest.read_text(encoding='utf8'))
    datas.append((str(_wheel_manifest), 'wheels'))
    for _item in _wheel_contract['wheels']:
        _wheel = ROOT / 'wheels' / _item['file']
        if hashlib.sha256(_wheel.read_bytes()).hexdigest() != _item['sha256']:
            raise RuntimeError('Bundled wheel checksum mismatch: '+str(_wheel))
        datas.append((str(_wheel), 'wheels'))

for filename in (
    "LICENSE",
    "PROJECT_LICENSE.md",
    "SOURCE_DELIVERY.md",
    "BUILD_FROM_SOURCE.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md",
    "2byteasr_version.json",
    "dependencies.lock.json",
    "game_profiles.json",
    "glossary.txt",
    "requirements-main.txt",
    # 2026-09-19: asr_api_worker.py runs under the external .venv-main python
    # and imports the repo-root facade module directly; without this copy the
    # frozen API-primary path dies with "No module named 'subtitle_core'".
    "subtitle_core.py",
    "moss_worker.py", "canary_asr_worker.py",
    "firered_llm_worker.py",
    "firered_aed_worker.py",
    "firered_vad_worker.py",
    "asr_api_worker.py", "nemotron_worker.py",
    "qwen_asr_worker.py",
    "glm_asr_worker.py",
    "sensevoice_worker.py",
    "extract_target_speaker.py",
    "speaker_embed_worker.py",
    "register_host_voiceprint.py",
):
    path = ROOT / filename
    if path.is_file():
        datas.append((str(path), "."))

# Standalone stdlib-only probe: external role venvs run it directly because
# they cannot import frozen twobyteasr.* modules from the exe archive.
# NOTE: the datas destination must be the DIST ROOT directory (".").
# A filename destination makes PyInstaller create a DIRECTORY named
# environment_probe.py/ and the runtime probe locator then sees no file.
_probe_source = ROOT / "twobyteasr" / "environment_probe.py"
if _probe_source.is_file():
    datas.append((str(_probe_source), "."))

# P8C-R3.1: the role workers (moss_worker.py / firered_llm_worker.py) run in
# EXTERNAL venv pythons and import twobyteasr.model_integrity (stdlib-only
# chain). Ship the package as real sources so those imports resolve from the
# install root; the frozen GUI itself keeps using the compiled archive.
for _source_file in sorted((ROOT / "twobyteasr").glob("*.py")):
    datas.append((str(_source_file), "twobyteasr"))

# P8C-R3.1: pyd-free copy of the MOSS worker for the packaged runtime. The
# install root carries the GUI's cp310 .pyd files; a 3.12 role venv running
# a script from that directory resolves stdlib extensions from it and dies
# with "Module use of python310.dll conflicts". The workers/ subdirectory
# keeps the isolated worker clear of those files.
_moss_worker_source = ROOT / "moss_worker.py"
if _moss_worker_source.is_file():
    datas.append((str(_moss_worker_source), "workers"))

# P8C-R3.1: ECAPA speaker embeddings must run inside the main runtime venv
# (the frozen GUI has no torch). Same workers/ pyd-free layout.
_speaker_embed_worker = ROOT / "speaker_embed_worker.py"
if _speaker_embed_worker.is_file():
    datas.append((str(_speaker_embed_worker), "workers"))

# P9A-R7: real local FireRed-AED and Qwen3-ASR launchers.  Keep copies in the
# pyd-free workers directory as well as the install root because packaged
# startup resolves their paths from both locations across older bundles.
for _asr_worker in (ROOT / "firered_aed_worker.py", ROOT / "firered_vad_worker.py", ROOT / "qwen_asr_worker.py", ROOT / "sensevoice_worker.py", ROOT / "asr_api_worker.py", ROOT / "nemotron_worker.py"):
    if _asr_worker.is_file():
        datas.append((str(_asr_worker), "."))
        datas.append((str(_asr_worker), "workers"))

datas += collect_data_files("qtawesome")
# Optional, isolated acceptance-only WASAPI loopback recorder.
import importlib.util
if importlib.util.find_spec('soundcard') is not None:
    datas += collect_data_files('soundcard')
binaries = [(str(Path(NODE).resolve()), "tools/node")]

excluded_modules = [
    # Photopea was the sole QtWebEngine consumer. Subtitle HTML rendering uses
    # the separately shipped Remotion/Chromium route, which is unchanged.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    # qtpy imports this compatibility alias under suppress(ImportError).
    # No application consumer; the isolated frozen payload was verified without it.
    "qtpy.QtDataVisualization", "PySide6.QtDataVisualization",
    "accelerate",
    "funasr",
    "gradio",
    "librosa",
    "modelscope",
    "numba",
    "pandas",
    "qwen_asr",
    "scipy",
    "sklearn",
    "speechbrain",
    "torch",
    "torchaudio",
    "transformers",
]

a = Analysis(
    [str(ROOT / "quick_start.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PySide6.QtNetwork", "PIL.Image", "qtawesome", "oss2", "oss2.defaults", "crcmod"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)
# Expanded directory inputs must not leak developer Git metadata, generated
# previews, logs, or user projects. Chromium under node_modules is retained.
def distributable(entry):
    target = Path(entry[0])
    parts = {part.lower() for part in target.parts}
    if parts & {'.git', '__pycache__', '.pytest_cache', '.mimosa', '.cache', 'tmp', 'logs', 'reports'}:
        return False
    if target.suffix.lower() in {'.pyc', '.pyo', '.log', '.2byteproj', '.2byteasr'}:
        return False
    if target.name.lower() in {'secrets.json', 'secrets.dat', '.env'}:
        return False
    return True

a.datas = [entry for entry in a.datas if distributable(entry)]
# QtGui's hook sweeps platforminputcontexts, including an unused GPL-only
# virtual keyboard. Keep Windows native IME and every other Qt plugin intact.
# These four precise files were absent in the independently verified payload copy.
_unused_qt_binaries = {
    "PySide6/QtDataVisualization.pyd",
    "PySide6/Qt6DataVisualization.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
}
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).as_posix() not in _unused_qt_binaries]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="2ByteASR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "assets" / "app_icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="2ByteASR",
)
