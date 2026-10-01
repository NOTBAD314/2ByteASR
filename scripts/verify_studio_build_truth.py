"""Compare a new onedir build with its source fingerprint and compiled code."""
import argparse
import hashlib
import json
import marshal
from pathlib import Path
import sys
import types


def normalized(code):
    return code.replace(co_filename='<source>', co_consts=tuple(
        normalized(item) if isinstance(item, types.CodeType) else item
        for item in code.co_consts))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('exe',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    from twobyteasr.build_identity import source_snapshot_files,source_snapshot_sha256
    from PyInstaller.archive.readers import CArchiveReader
    exe=args.exe.resolve();bundle=exe.parent
    archive=CArchiveReader(str(exe))
    pyz=archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz')))
    metadata=json.loads((bundle/'2byteasr_build.json').read_text(encoding='utf8'))
    files=source_snapshot_files(root)
    digest,count=source_snapshot_sha256(root,files)
    result={'exe':str(exe),'bytes':exe.stat().st_size,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'metadata':metadata,'current_source_sha256':digest,'source_file_count':count,
        'raw':[],'compiled':[],'build_inputs':[],'errors':[]}
    if digest!=metadata['source_sha256'] or count!=metadata['source_file_count']:
        result['errors'].append('source fingerprint mismatch')
    for source in files:
        relative=source.relative_to(root)
        # Wheel metadata is intentionally installed beside the wheel payload.
        packed=bundle/('wheels/model_wheels.json' if relative.as_posix()=='packaging/model_wheels.json' else relative)
        if packed.is_file():
            if source.read_bytes()!=packed.read_bytes():result['errors'].append(f'raw mismatch: {relative}')
            result['raw'].append(relative.as_posix())
        elif (source.suffix in {'.spec', '.iss'} or relative.as_posix() in {
                'packaging/version_info.txt',
                '.github/workflows/macos-experimental.yml'}
                or relative.as_posix().startswith('packaging/macos/')):
            result['build_inputs'].append({'path':relative.as_posix(),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
        elif source.suffix!='.py':
            result['errors'].append(f'missing source input: {relative}')
        if source.suffix=='.py':
            module='.'.join(relative.with_suffix('').parts)
            if module.endswith('.__init__'):module=module[:-9]
            code=None
            if module in pyz.toc:code=pyz.extract(module)
            elif module in archive.toc:code=marshal.loads(archive.extract(module))
            if code is not None:
                expected=compile(source.read_bytes(),str(source),'exec',optimize=1)
                if normalized(code)!=normalized(expected):result['errors'].append(f'compiled mismatch: {module}')
                result['compiled'].append(module)
            elif not packed.is_file():result['errors'].append(f'missing compiled module: {module}')
    # Assets are outside the historical fingerprint; protect the theme touched
    # in the preceding delivery with explicit byte comparisons as well.
    result['theme_assets']=[]
    for source in (root/'assets').rglob('*'):
        if source.is_file() and 'balatro' in str(source).lower():
            relative=source.relative_to(root)
            if not (bundle/relative).is_file() or source.read_bytes()!=(bundle/relative).read_bytes():
                result['errors'].append(f'theme mismatch: {relative}')
            result['theme_assets'].append(relative.as_posix())
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({key:(len(value) if isinstance(value,list) and key!='errors' else value)
        for key,value in result.items() if key!='metadata'},ensure_ascii=False,indent=2))
    return bool(result['errors'])


if __name__=='__main__':
    raise SystemExit(main())
