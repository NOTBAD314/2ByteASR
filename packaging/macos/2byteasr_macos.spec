# SPDX-License-Identifier: GPL-3.0-only
# A real native arm64 onedir .app; run only through scripts/macos_build.py.
from pathlib import Path
import json
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.hooks.qt import get_qt_library_info

if sys.platform != 'darwin':
    raise RuntimeError('This .app spec requires native macOS; no Windows cross-build')
ROOT=Path(os.environ['TWOBYTEASR_MAC_SOURCE']).resolve()
WORK=Path(os.environ['TWOBYTEASR_MAC_BUILD_ROOT']).resolve()
sys.path.insert(0,str(ROOT))
from twobyteasr.platform_macos import cpu_factory_settings
from twobyteasr.settings import DEFAULT_SETTINGS
from scripts.macos_build import is_macho, selected_media_libraries
native=json.loads(Path(os.environ['TWOBYTEASR_MAC_NATIVE_INPUTS']).read_text(encoding='utf8'))
VERSION=json.loads((ROOT/'2byteasr_version.json').read_text(encoding='utf8'))['version']
# Local MCP server (2026-10-12): the same official SDK modules as the Windows spec;
# the CLI and FastMCP extras are not used.
mcp_hidden=(collect_submodules('mcp',filter=lambda name: not name.startswith(('mcp.cli','mcp.server.fastmcp')))
            +collect_submodules('mcp_types'))
factory=WORK/'factory'
factory.mkdir()
(factory/'2byteasr_settings.json').write_text(json.dumps(cpu_factory_settings(DEFAULT_SETTINGS),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
datas=collect_data_files('certifi')+collect_data_files('qtawesome')
datas.extend([(os.environ['TWOBYTEASR_BUILD_METADATA'],'.'),(str(factory/'2byteasr_settings.json'),'.'),
              (os.environ['TWOBYTEASR_MAC_NATIVE_INPUTS'],'.')])
binaries=[(native['native_tools']['node']['path'],'tools/node'),
          (native['native_tools']['mpv']['path'],'tools/mpv'),
          (native['native_tools']['ffmpeg']['path'],'tools/ffmpeg/bin'),
          (native['native_tools']['ffprobe']['path'],'tools/ffmpeg/bin')]
# mpv's standard FFmpeg dependency shares these basenames. Explicit selected
# full-build libraries precede discovered dependencies in Analysis's TOC.
binaries.extend((str(path),'.') for path in selected_media_libraries(Path(native['native_tools']['ffmpeg']['path'])))
# QVideoSink uses Qt's native multimedia decoder plugin. Collect the precise
# plugin class explicitly, while Analysis handles its linked libraries.
binaries.extend(get_qt_library_info('PySide6').collect_plugins('multimedia'))
for directory in ('assets','licenses','lexicons','renderer','twobyteasr','third_party','docs/design','scripts','packaging/macos'):
    for path in (ROOT/directory).rglob('*'):
        if not path.is_file(): continue
        relative=path.relative_to(ROOT)
        if set(relative.parts) & {'.git','__pycache__','.pytest_cache','tmp','logs','reports'}:continue
        if path.suffix.casefold() in {'.exe','.dll','.pyd','.whl','.bat','.cmd','.ps1','.pyc','.pyo','.log','.2byteproj','.2byteasr'}:continue
        destination=relative.parent.as_posix()
        (binaries if is_macho(path) else datas).append((str(path),destination))
for path in ROOT.iterdir():
    if path.is_file() and (path.suffix=='.py' or path.name in {'2byteasr_version.json','dependencies.lock.json','game_profiles.json','glossary.txt','requirements-main.txt','LICENSE','PROJECT_LICENSE.md','SOURCE_DELIVERY.md','BUILD_FROM_SOURCE.md','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md'}):datas.append((str(path),'.'))
datas.append((str(ROOT/'twobyteasr/environment_probe.py'),'.'))
excluded=['torch','torchaudio','transformers','funasr','modelscope','librosa','numba','scipy','sklearn','speechbrain','accelerate','qwen_asr','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick','PySide6.QtDataVisualization','qtpy.QtDataVisualization']
a=Analysis([str(ROOT/'scripts/macos_launch.py')],pathex=[str(ROOT)],binaries=binaries,datas=datas,
           hiddenimports=['PySide6.QtNetwork','PySide6.QtMultimedia','PIL.Image','qtawesome','oss2','oss2.defaults','crcmod',*mcp_hidden],
           hookspath=[],hooksconfig={},runtime_hooks=[],excludes=excluded,noarchive=False,optimize=1)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='2ByteASR',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,argv_emulation=False,target_arch='arm64',codesign_identity=None,entitlements_file=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='2ByteASR')
app=BUNDLE(coll,name='2ByteASR.app',icon=native['app_icon']['path'],bundle_identifier='org.2byteasr.desktop.experimental',
           info_plist={'CFBundleName':'2ByteASR','CFBundleDisplayName':'兔白字幕 / 2ByteASR',
                       'CFBundleShortVersionString':VERSION,'CFBundleVersion':VERSION,
                       'LSMinimumSystemVersion':'15.0','NSHighResolutionCapable':True})
