"""Prepare native compatibility inputs from immutable official sources.

No Mach-O deployment markers are rewritten. Tesseract is compiled; Remotion's
complete FFmpeg 7.1 library set is selected with architecture, versioned dylib
ABI and imported-symbol checks. Its current Rust compositor and JS stay intact.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import urllib.request

from scripts.macos_binary_audit import parse_macho, version, audit_tree


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def acquire(spec, path):
    path=Path(path)
    if not path.exists():
        with urllib.request.urlopen(spec['url'],timeout=60) as response,path.open('wb') as out:
            shutil.copyfileobj(response,out)
    if sha256(path)!=spec['sha256']:
        raise RuntimeError('Compatibility source checksum mismatch: '+path.name)
    return path


def native_symbols(data):
    slices=parse_macho(data)
    if len(slices)!=1 or slices[0]['architecture']!='arm64' or data[:4]!=bytes.fromhex('cffaedfe'):
        raise RuntimeError('Symbol contract requires a thin arm64 Mach-O')
    cursor=32;links=[];sym=None;identity=None
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        cmd,size=struct.unpack_from('<2I',data,cursor)
        if (cmd&0x7fffffff) in (0xc,0x18,0x1f,0x20,0x23):
            offset=struct.unpack_from('<I',data,cursor+8)[0]
            links.append(data[cursor+offset:cursor+size].split(b'\0')[0].decode())
        if cmd==0xd:
            identity=struct.unpack_from('<6I',data,cursor)[-2:]
        if cmd==2:sym=struct.unpack_from('<6I',data,cursor)[2:]
        cursor+=size
    exports=set();required=[]
    if not sym:raise RuntimeError('Native symbol table missing')
    offset,count,strings,length=sym
    if offset+count*16>len(data) or strings+length>len(data):raise RuntimeError('Invalid symbol table bounds')
    for index in range(count):
        name_index,kind,_,description,_value=struct.unpack_from('<IBBHQ',data,offset+16*index)
        if name_index>=length:raise RuntimeError('Invalid native symbol name')
        name=data[strings+name_index:strings+length].split(b'\0')[0].decode('utf8','strict')
        if kind&0xe0:continue
        if kind&1 and kind&0xe:exports.add(name)
        elif kind&1 and not kind&0xe and 0<description>>8<=len(links):
            required.append((links[(description>>8)-1],name,bool(description&0x40)))
    return exports,required,identity


def install_renderer_media(renderer, work, spec):
    destination=renderer/'node_modules/@remotion/compositor-darwin-arm64'
    package=json.loads((destination/'package.json').read_text('utf8'))
    if package['version']!=spec['consumer_version']:
        raise RuntimeError('Review the compatible native library contract before changing Remotion')
    original_rust=sha256(destination/'remotion')
    archive=acquire(spec,work/'remotion-ffmpeg.tgz')
    native={}
    with tarfile.open(archive) as bundle:
        for name,expected in spec['files'].items():
            member=bundle.getmember('package/'+name)
            if not member.isfile() or Path(name).name!=name:raise RuntimeError('Unsafe renderer media member')
            data=bundle.extractfile(member).read()
            if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Renderer media member checksum differs')
            slices=parse_macho(data)
            if len(slices)!=1 or slices[0]['architecture']!='arm64' or version(slices[0]['minimum_macos'])>version('14.0'):
                raise RuntimeError('Renderer media architecture/deployment target differs')
            native[name]=data
    exports={}
    for name,data in native.items():
        if not name.endswith('.dylib'):continue
        new,_,new_id=native_symbols(data)
        _,_,old_id=native_symbols((destination/name).read_bytes())
        if new_id!=old_id:raise RuntimeError('Renderer FFmpeg dylib ABI/version changed: '+name)
        exports[name]=new
    _,imports,_=native_symbols((destination/'remotion').read_bytes())
    imports=[(Path(lib).name,name,weak) for lib,name,weak in imports if Path(lib).name in exports]
    if not imports:raise RuntimeError('No compositor-to-FFmpeg imports checked')
    missing=[name for lib,name,weak in imports if not weak and name not in exports[lib]]
    if missing:raise RuntimeError('Compatible FFmpeg lacks required compositor symbols: '+','.join(missing))
    for name,data in native.items():
        path=destination/name;path.write_bytes(data);path.chmod(0o755)
    if sha256(destination/'remotion')!=original_rust:raise RuntimeError('Current compositor was unexpectedly replaced')
    return dict(source=spec,checked_imports=len(imports),missing_symbols=[],rust_unchanged_sha256=original_rust,
                javascript_package_version=package['version'],execution_verified=False)


def build_tesseract(work, spec, *, environment):
    work.mkdir(parents=True,exist_ok=False)
    archive=acquire(spec,work/'tesseract.tar.gz')
    source=work/'source';source.mkdir()
    from scripts.macos_build import unpack_verified_node
    unpack_verified_node(archive,source)
    source=source/spec['source_directory']
    prefix=work/'install';build=work/'build'
    env=dict(environment,MACOSX_DEPLOYMENT_TARGET='14.0')
    cmake=shutil.which('cmake')
    if not cmake:raise RuntimeError('Build host requires CMake for the pinned Tesseract source')
    commands=[
        [cmake,'-S',source,'-B',build,'-DCMAKE_BUILD_TYPE=Release',f'-DCMAKE_INSTALL_PREFIX={prefix}',
         '-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0','-DCMAKE_OSX_ARCHITECTURES=arm64',
         '-DCMAKE_INSTALL_NAME_DIR=@rpath','-DCMAKE_INSTALL_RPATH=@loader_path;@loader_path/../lib',
         '-DCMAKE_PREFIX_PATH=/opt/homebrew','-DBUILD_SHARED_LIBS=ON','-DBUILD_TRAINING_TOOLS=OFF',
         '-DBUILD_TESTS=OFF','-DENABLE_NATIVE=OFF','-DOPENMP_BUILD=OFF'],
        [cmake,'--build',build,'--parallel','3'],[cmake,'--install',build]]
    with (work/'build.log').open('wb') as log:
        for command in commands:
            log.write((json.dumps(list(map(str,command)))+'\n').encode());log.flush()
            subprocess.run(list(map(str,command)),env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
    audit=audit_tree(prefix,arch='arm64',target='14.0',allow_external=True)
    (work/'binary-compatibility.json').write_text(json.dumps(audit,indent=2)+'\n','utf8')
    if not audit['passed']:raise RuntimeError('Recompiled Tesseract still exceeds target')
    libraries=[dict(path=str(p),sha256=sha256(p)) for p in sorted((prefix/'lib').glob('libtesseract*.dylib'))]
    if not any(Path(p['path']).name=='libtesseract.5.dylib' for p in libraries):
        raise RuntimeError('Tesseract ABI 5 output missing')
    return dict(source=spec,libraries=libraries,minimum_macos='14.0',compiled=True,commands=[list(map(str,c)) for c in commands])
