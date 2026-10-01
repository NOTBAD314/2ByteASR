"""Scan an actual frozen/installed payload without printing matched secrets."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('payload',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.payload.resolve()
    errors=[];files=[];texts=0
    forbidden={'.git','__pycache__','.pytest_cache','.mimosa','.cache','logs','reports','projects','models'}
    forbidden_names={'secrets.json','secrets.dat','.env','2byteasr-qa-profile.marker','registry.json'}
    patterns={
        'credential': re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{32,}|hf_[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16})\b'),
        'developer_home': re.compile(rb'(?i)[a-z]:[\\/]+Users[\\/]+12[\\/]'),
        'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    }
    text_ext={'.py','.ps1','.json','.txt','.md','.js','.mjs','.cjs','.html','.css','.yml','.yaml','.ini','.bat','.toml','.xml','.conf','.map'}
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(root);parts={s.lower() for s in rel.parts}
        # Third-party source packages can legitimately contain a models code package.
        if parts.intersection(forbidden-{'models'}) or rel.parts[0].lower()=='models':
            errors.append(dict(category='user_or_build_directory',path=rel.as_posix()))
        if p.name.lower() in forbidden_names or p.suffix.lower() in {'.log','.2byteasr','.2byteproj','.safetensors','.ckpt','.pt'}:
            errors.append(dict(category='user_or_weight_file',path=rel.as_posix()))
        if p.suffix.lower() in {'.mp4','.mov','.mp3','.wav','.flv','.mkv'} and rel.as_posix()!='assets/diagnostics/speech_en.wav':
            errors.append(dict(category='unexpected_media',path=rel.as_posix()))
        h=hashlib.sha256()
        with p.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
        files.append(dict(path=rel.as_posix(),bytes=p.stat().st_size,sha256=h.hexdigest()))
        if p.suffix.lower() in text_ext or p.name.lower().startswith(('license','notice','copying')):
            texts+=1;data=p.read_bytes()
            for category,pattern in patterns.items():
                if pattern.search(data):errors.append(dict(category=category,path=rel.as_posix()))
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from twobyteasr.settings import DEFAULT_SETTINGS
    settings=json.loads((root/'2byteasr_settings.json').read_text('utf-8-sig'))
    if settings!=DEFAULT_SETTINGS:errors.append(dict(category='nonfactory_settings',path='2byteasr_settings.json'))
    result=dict(passed=not errors,file_count=len(files),text_count=texts,total_bytes=sum(x['bytes'] for x in files),errors=errors,files=files,
                scope='Actual payload paths/text/factory config and whole-file hashes; encrypted/obfuscated secrets cannot be proven absent by pattern scanning.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
