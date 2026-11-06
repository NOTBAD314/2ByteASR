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
# Keep the pinned browser font contract with the exact distributed source.
datas.append((str(ROOT / 'packaging/renderer_fonts.json'), 'packaging'))
# Public bundles always ship factory defaults, never this machine's settings.
sys.path.insert(0, str(ROOT))
from twobyteasr.storage.settings import DEFAULT_SETTINGS
from twobyteasr.diagnostics.build_identity import is_current_delivery_file
defaults_dir = ROOT / 'tmp' / 'frozen-defaults'
defaults_dir.mkdir(parents=True, exist_ok=True)
_defaults_file = defaults_dir / '2byteasr_settings.json'
_defaults_text = json.dumps(DEFAULT_SETTINGS, ensure_ascii=False, indent=2)
if not _defaults_file.is_file() or _defaults_file.read_text(encoding='utf-8') != _defaults_text:
    _defaults_file.write_text(_defaults_text, encoding='utf-8')
datas.append((str(defaults_dir / '2byteasr_settings.json'), '.'))
if os.environ.get('TWOBYTEASR_QA_BUILD') == '1':
    marker = defaults_dir / '2byteasr-qa-profile.marker'
    marker.write_text('Isolated QA build: uses install/tmp/qa-profile.\n', encoding='utf-8')
    datas.append((str(marker), '.'))
for source, destination in (
    ("assets", "assets"),
    ("licenses", "licenses"),
    ("docs/design/caption-preferences.json", "docs/design"),
    # In-app 「申请与设置 API」 guides (2026-10-13); same files as the repo docs.
    ("docs/api-setup", "docs/api-setup"),
    ("lexicons", "lexicons"),
    ("renderer", "renderer"),
    ("scripts", "scripts"),
    ("third_party", "third_party"),
    ("tools/ffmpeg", "tools/ffmpeg"),
    ("tools/yt-dlp", "tools/yt-dlp"),
    ("tools/mpv", "tools/mpv"),
    ("tools/diagnostics", "tools/diagnostics"),
    # mpv's fallback Vulkan loader (2026-10-17). Installed outside tools/ so it
    # belongs to the 主程序 update component: older installs reject a tools/
    # path inside the app archive, and tools/ itself would re-download ~211 MB.
    ("tools/vulkan-loader", "third_party/vulkan-loader"),
):
    path = ROOT / source
    if path.exists():
        if source in {"scripts", "third_party"}:
            # Also enforce retirement if a builder still has old source files.
            for retained in sorted(path.rglob('*')):
                if retained.is_file() and is_current_delivery_file(retained.relative_to(ROOT).as_posix()):
                    datas.append((str(retained), retained.parent.relative_to(ROOT).as_posix()))
        else:
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
    "qwen_asr_worker.py",
    "qwen_aligner_worker.py",
    "mfa_aligner_worker.py",
    "glm_asr_worker.py",
    "sensevoice_worker.py",
    "asr_api_worker.py",
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
# 2026-10-15: the package has feature subfolders (twobyteasr/<feature>/),
# and those imports follow them (e.g. runtime_paths -> local_models), so the
# whole tree is copied with its folder structure.
for _source_file in sorted((ROOT / "twobyteasr").rglob("*.py")):
    if "__pycache__" in _source_file.parts:
        continue
    _relative = _source_file.relative_to(ROOT)
    if is_current_delivery_file(_relative.as_posix()):
        datas.append((str(_source_file), _relative.parent.as_posix()))
# UI translation catalogs, read by twobyteasr.i18n next to its own module.
for _locale_file in sorted((ROOT / "twobyteasr" / "locales").glob("*.json")):
    datas.append((str(_locale_file), "twobyteasr/locales"))

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
for _asr_worker in (ROOT / "firered_aed_worker.py", ROOT / "firered_vad_worker.py", ROOT / "qwen_asr_worker.py", ROOT / "qwen_aligner_worker.py", ROOT / "ctc_aligner_worker.py", ROOT / "mfa_aligner_worker.py", ROOT / "sensevoice_worker.py", ROOT / "asr_api_worker.py"):
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
    # PyInstaller's analysis adds this automatically; list it explicitly so
    # the next run can reuse the identical completed Analysis exclusions.
    "__main__",
]

# Local MCP server (2026-10-12): ``2ByteASR.exe --mcp-stdio`` imports the
# official SDK lazily; its protocol-version modules load by name.
from PyInstaller.utils.hooks import collect_submodules
_mcp_hidden = (collect_submodules("mcp", filter=lambda name: not name.startswith(("mcp.cli", "mcp.server.fastmcp")))
               + collect_submodules("mcp_types"))

a = Analysis(
    [str(ROOT / "quick_start.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PySide6.QtNetwork", "PIL.Image", "PIL.GifImagePlugin", "PIL.PngImagePlugin", "sqlite3", "qtawesome", "oss2", "oss2.defaults", "crcmod", *_mcp_hidden],
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
# A local daily may retain validated native/Tcl bytes while rebuilding its
# Python/archive and external scripts. Pin before COLLECT, never splice DLLs
# into the frozen output afterwards. Every selected file must already exist.
_pin_root = os.environ.get('TWOBYTEASR_PIN_PACKAGE_ROOT')
if _pin_root:
    _pin_root = Path(_pin_root).resolve()
    def pinned_entry(entry):
        previous = _pin_root / entry[0]
        if not previous.is_file():
            raise RuntimeError('Baseline package lacks build dependency: '+entry[0])
        return (entry[0], str(previous), *entry[2:])
    a.binaries = [pinned_entry(entry) for entry in a.binaries]
    a.datas = [pinned_entry(entry) if (entry[0].replace('\\', '/').startswith(('_tcl_data/', '_tk_data/'))
               or entry[0] == 'base_library.zip') else entry for entry in a.datas]
    # Source-only snapshots omit unmodified images and API-guide assets.
    # Retain the verified predecessor's resources before collection too.
    _known = {entry[0].replace('\\', '/') for entry in a.binaries + a.datas}
    for _resource_folder in ('assets', 'docs'):
        for _resource in sorted((_pin_root / _resource_folder).rglob('*')):
            if not _resource.is_file():
                continue
            _destination = _resource.relative_to(_pin_root).as_posix()
            if _destination not in _known:
                a.datas.append((_destination, str(_resource), 'DATA'))
                _known.add(_destination)
    # Finalize provenance after a valid Analysis cache is reused; changing
    # only build identity must not force analysis of unchanged Python code.
    from twobyteasr.diagnostics.build_identity import write_build_metadata
    write_build_metadata(ROOT, build_metadata, channel=os.environ.get('TWOBYTEASR_BUILD_CHANNEL', ''))
    print('Validated native/Tcl inputs pinned before collection:', _pin_root)
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
    icon=str((_pin_root if _pin_root else ROOT) / "assets" / "app_icon.ico"),
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
