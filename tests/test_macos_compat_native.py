import json
import struct
import pytest

from scripts.macos_compat_native import acquire, native_symbols, install_renderer_media


def object_with_symbol(*,defined=False):
    link=b'@rpath/libavcodec.dylib\0'
    size=(24+len(link)+7)//8*8
    dylib=struct.pack('<6I',0xc,size,24,0,0,0)+link+bytes(size-24-len(link))
    names=b'\0_avcodec_find_decoder\0'
    offset=32+24+24+len(dylib)
    commands=struct.pack('<6I',0x32,24,1,0xe0000,0xf0000,0)+struct.pack('<6I',2,24,offset,1,offset+16,len(names))+dylib
    return (struct.pack('<8I',0xfeedfacf,0x100000c,0,6,3,len(commands),0,0)+commands+
            struct.pack('<IBBHQ',1,0xf if defined else 1,1 if defined else 0,0 if defined else 0x100,0)+names)


def test_import_symbol_keeps_its_library_ordinal():
    exports,imports,identity=native_symbols(object_with_symbol())
    assert exports==set() and identity is None
    assert imports==[('@rpath/libavcodec.dylib','_avcodec_find_decoder',False)]
    exports,imports,_=native_symbols(object_with_symbol(defined=True))
    assert exports=={'_avcodec_find_decoder'} and imports==[]


def test_corrupt_symbol_table_is_rejected():
    value=bytearray(object_with_symbol())
    struct.pack_into('<I',value,32+24+8,0xffffffff)
    with pytest.raises(RuntimeError,match='bounds'):native_symbols(bytes(value))


def test_incompatible_consumer_refused_before_modifying_packages(tmp_path):
    package=tmp_path/'renderer/node_modules/@remotion/compositor-darwin-arm64'
    package.mkdir(parents=True)
    (package/'package.json').write_text(json.dumps({'version':'9.0.0'}))
    (package/'remotion').write_bytes(b'original')
    with pytest.raises(RuntimeError,match='before changing Remotion'):
        install_renderer_media(tmp_path/'renderer',tmp_path,{'consumer_version':'4.0.513'})
    assert (package/'remotion').read_bytes()==b'original'


def test_corrupt_cached_source_is_not_executed_or_overwritten(tmp_path):
    path=tmp_path/'source.tar.gz';path.write_bytes(b'corrupt')
    with pytest.raises(RuntimeError,match='checksum mismatch'):
        acquire({'url':'https://example.invalid/unused','sha256':'0'*64},path)
    assert path.read_bytes()==b'corrupt'
