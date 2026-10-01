"""Read-only distribution evidence collector (no network, no product imports).

Writes only --output under repository tmp/. Never prints matched credentials.
Modes: inventory PATH, scan PATH, git REPOSITORY, frozen EXE, packages PATH.
Use a Python matching the frozen archive for `frozen`, with PyInstaller installed.
Results are leads, not a security clearance or a legal opinion. Encrypted data,
media pixels/audio, obfuscated strings and omitted oversized members need review.
"""
from __future__ import annotations

import argparse
import email.parser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types
import zipfile
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 32 * 1024 * 1024
TEXT_EXT = {'.py','.ps1','.json','.txt','.md','.js','.mjs','.cjs','.ts','.tsx','.jsx',
            '.html','.css','.yml','.yaml','.ini','.bat','.cmd','.toml','.xml','.conf',
            '.map','.csv','.srt','.ass','.vtt','.env','.pem','.key','.rst','.config','.log'}
RULES = {
    'provider_token': re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|LTAI[A-Za-z0-9]{16,})\b'),
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'credential_literal': re.compile(rb'''(?i)["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret[_-]?key|access[_-]?key[_-]?secret|password|authorization|cookie)["']?\s*[:=]\s*["']([^"'\r\n]{8,500})["']'''),
    'signed_url': re.compile(rb'(?i)https?://[^\s"<>]{0,400}(?:[?&](?:x-amz-signature|x-oss-signature|signature|access_token|token|api_key|sig)=)[^\s"<>]{5,250}'),
    'private_home': re.compile(rb'(?i)(?:[a-z]:[\\/]+Users[\\/]+[^\\/\s"\x00]+[\\/]|/home/[^/\s"\x00]+/|/Users/[^/\s"\x00]+/)'),
    'email': re.compile(rb'\b[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
}
PLACEHOLDER = re.compile(rb'(?i)(example|placeholder|your[_ -]|dummy|fake|test|mock|sample|redacted|replace|changeme|xxx|abcdef|123456|\$\{|\{\{|os\.environ|process\.env)')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git','-C',str(repo),*args], stderr=subprocess.DEVNULL)


def safe_path(value):
    return re.sub(r'(?i)([A-Z]:[/\\]+Users[/\\]+)[^/\\]+',r'\1<user>',str(value))


def files(root, exclusions=()):
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in exclusions and not (Path(current)/d).is_symlink())
        for name in sorted(names):
            p=Path(current)/name
            if p.is_file() and not p.is_symlink(): yield p


class Scanner:
    def __init__(self):
        self.hits=[]; self.coverage=Counter(); self.skipped=[]; self._seen={}

    def data(self, data, location, binary=False):
        self.coverage['streams']+=1;self.coverage['bytes']+=len(data)
        for category, pattern in RULES.items():
            # email/path counts are useful for privacy triage; never output literals.
            matches=list(pattern.finditer(data))
            if not matches: continue
            if category in {'email','private_home'}:
                m=matches[0]
                self.hits.append(dict(path=safe_path(location),category=category,count=len(matches),
                    line=None if binary else data.count(b'\n',0,m.start())+1,
                    classification='privacy_or_upstream_attribution_review',evidence='literal omitted'))
                continue
            for m in matches:
                value=m.group(1) if category=='credential_literal' else m.group(0)
                placeholder=bool(PLACEHOLDER.search(value)) or len(set(value))<5
                self.hits.append(dict(path=safe_path(location),category=category,
                    line=None if binary else data.count(b'\n',0,m.start())+1,
                    fingerprint=hashlib.sha256(value).hexdigest()[:16],length=len(value),
                    classification='example_placeholder_candidate' if placeholder else 'suspected_secret',
                    evidence='matched value fully redacted; validity not tested'))

    def stream(self, stream, location):
        """Scan large binaries without loading the whole file; keep boundary overlap."""
        tail=b'';offset=0
        while True:
            block=stream.read(8*1024*1024)
            if not block:break
            self.data(tail+block,location+'@byte'+str(max(0,offset-len(tail))),True)
            tail=block[-1024:];offset+=len(block)
        self.coverage['streamed_binary_files']+=1

    def archive(self, stream, location, depth=0):
        try:
            with zipfile.ZipFile(stream) as z:
                self.coverage['zip_archives']+=1
                for item in z.infolist():
                    if item.is_dir(): continue
                    label=location+'!'+item.filename
                    self.coverage['archive_members']+=1
                    if item.flag_bits&1:
                        self.skipped.append(dict(path=safe_path(label),reason='encrypted_member',bytes=item.file_size));continue
                    ext=Path(item.filename).suffix.lower()
                    if item.file_size>LIMIT:
                        with z.open(item) as f:self.stream(f,label)
                        continue
                    if ext in TEXT_EXT or Path(item.filename).name.lower().startswith(('license','copying','notice','metadata','pkg-info')) or ext=='.pyc':
                        self.data(z.read(item),label,binary=ext=='.pyc')
                    elif ext in {'.zip','.whl'} and depth<2:
                        data=z.read(item)
                        if data.startswith(b'PK'):self.archive(io.BytesIO(data),label,depth+1)
                        else:
                            self.data(data,label,True)
                            self.coverage['archive_suffix_nonzip_members']+=1
                    elif ext in {'.exe','.dll','.pyd','.node','.db','.dat','.sqlite'}:
                        self.data(z.read(item),label,True)
        except (OSError,ValueError,zipfile.BadZipFile,RuntimeError) as exc:
            self.skipped.append(dict(path=safe_path(location),reason=type(exc).__name__))

    def path(self,p,location):
        self.coverage['files']+=1
        ext=p.suffix.lower();size=p.stat().st_size
        if ext in {'.zip','.whl'}: self.archive(p,location);return
        istext=ext in TEXT_EXT or p.name.lower().startswith(('license','copying','notice','metadata','pkg-info'))
        suspicious=p.name.lower() in {'.env','secrets.json','secrets.dat','cookies','login data','history'} or ext in {'.sqlite','.db','.pfx','.p12','.2byteasr','.2byteproj'}
        if suspicious: self.hits.append(dict(path=safe_path(location),category='sensitive_file_name',classification='review',evidence='contents not printed'))
        if size>LIMIT:
            with p.open('rb') as f:self.stream(f,location)
            return
        if istext or ext in {'.exe','.dll','.pyd','.pyc','.dat','.db','.sqlite'}:
            self.data(p.read_bytes(),location,binary=not istext)
        else:self.coverage['nontext_not_content_scanned']+=1

    def result(self):
        return dict(coverage=dict(self.coverage),hits=self.hits,skipped=self.skipped,
                    limitation='Offline heuristic triage only; no credentials validated; no image OCR/audio transcription; large binaries scanned in chunks with 1024-byte overlap; encoded/encrypted secrets can be missed.')


def inventory(root):
    result=[]
    for p in files(root, {'.git'}):
        result.append(dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
    return dict(root=safe_path(root),files=result,file_count=len(result),bytes=sum(x['bytes'] for x in result))


def scan(root, tracked=False):
    s=Scanner()
    if tracked:
        paths=git(root,'ls-files','-z','--cached','--others','--exclude-standard').decode('utf8').split('\0')
        for rel in sorted(set(paths)):
            if not rel or rel.startswith(('reports/','2ByteASR Projects/','.git/')):continue
            p=root/rel
            if p.is_file() and not p.is_symlink():s.path(p,rel)
    else:
        for p in files(root,{'.git'}):s.path(p,p.relative_to(root).as_posix())
    return s.result()


def scan_git(root):
    s=Scanner()
    refs=git(root,'for-each-ref','--format=%(refname) %(objectname)').decode().splitlines()
    reachable=git(root,'rev-list','--objects','--all','--reflog').decode('utf8',errors='replace').splitlines()
    paths={line.split(' ',1)[0]:line.split(' ',1)[1] for line in reachable if ' ' in line}
    objects=git(root,'cat-file','--batch-all-objects','--batch-check=%(objectname) %(objecttype) %(objectsize)').decode().splitlines()
    proc=subprocess.Popen(['git','-C',str(root),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    blobs=0; metadata_objects=0; oversized=[]
    try:
        for item in objects:
            oid,kind,length=item.split();length=int(length)
            if kind not in {'blob','commit','tag'}:continue
            if kind=='blob':blobs+=1
            else:metadata_objects+=1
            label='git:'+oid+':'+(paths.get(oid,'<unreachable-or-unmapped>') if kind=='blob' else '<'+kind+'-metadata>')
            if length>LIMIT:
                oversized.append(dict(oid=oid,path=safe_path(paths.get(oid,'')),bytes=length));continue
            proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
            header=proc.stdout.readline();data=proc.stdout.read(length);proc.stdout.read(1)
            if len(data)!=length:raise RuntimeError('Incomplete Git blob read')
            if data.startswith(b'PK\x03\x04'):s.archive(io.BytesIO(data),label)
            else:s.data(data,label,binary=b'\x00' in data[:4096])
    finally:
        proc.stdin.close();proc.wait()
    return dict(refs=refs,head=git(root,'rev-parse','HEAD').decode().strip(),
                commits=int(git(root,'rev-list','--all','--count')),objects=len(objects),blobs=blobs,
                oversized_blobs=oversized,metadata_objects=metadata_objects,
                includes_unreachable_objects=True,**s.result())


def frozen(exe):
    from PyInstaller.archive.readers import CArchiveReader
    reader=CArchiveReader(str(exe));s=Scanner();members=[]
    def constants(code,label):
        s.data(code.co_filename.encode('utf8',errors='replace'),label+':co_filename')
        for i,c in enumerate(code.co_consts):
            if isinstance(c,types.CodeType):constants(c,label+'/'+c.co_name)
            elif isinstance(c,str):s.data(c.encode('utf8',errors='replace'),label+':const'+str(i))
            elif isinstance(c,bytes):s.data(c,label+':bytes'+str(i),True)
    for name,meta in reader.toc.items():
        members.append(dict(name=name,type=meta[-1]))
        if meta[-1]=='z':
            pyz=reader.open_embedded_archive(name)
            for mod in pyz.toc:
                try:
                    val=pyz.extract(mod)
                    if isinstance(val,types.CodeType):constants(val,'PYZ:'+mod)
                    elif isinstance(val,bytes):s.data(val,'PYZ:'+mod,True)
                except Exception as exc:s.skipped.append(dict(path=mod,reason=type(exc).__name__))
            members.extend(dict(name=n,type='PYZ_module') for n in pyz.toc)
        elif meta[-1]=='s':
            import marshal
            try:constants(marshal.loads(reader.extract(name)),'CArchive:'+name)
            except Exception as exc:s.skipped.append(dict(path=name,reason=type(exc).__name__))
    return dict(exe_sha256=sha(exe),members=members,**s.result())


def packages(root):
    npm=[]; wheels=[]; licenses=[]
    for p in files(root,{'.git'}):
        rel=p.relative_to(root).as_posix()
        if p.name=='package.json' and 'node_modules' in p.parts:
            try:d=json.loads(p.read_text('utf8'))
            except (ValueError,OSError):continue
            if not d.get('name') or not d.get('version'):continue
            lic=[dict(path=x.relative_to(root).as_posix(),sha256=sha(x)) for x in p.parent.iterdir() if x.is_file() and x.name.lower().startswith(('license','notice','copying'))]
            npm.append(dict(name=d['name'],version=d['version'],path=rel,declared_license=d.get('license'),upstream=d.get('repository'),license_files=lic,sha256=sha(p)))
        if p.suffix=='.whl':
            with zipfile.ZipFile(p) as z:
                meta=next((n for n in z.namelist() if n.endswith('.dist-info/METADATA')),None)
                if not meta:continue
                m=email.parser.BytesParser().parsebytes(z.read(meta))
                lic=[dict(path=rel+'!'+n,sha256=hashlib.sha256(z.read(n)).hexdigest()) for n in z.namelist() if not n.endswith('/') and any(Path(n).name.lower().startswith(x) for x in ('license','copying','notice'))]
                wheels.append(dict(name=m.get('Name'),version=m.get('Version'),path=rel,sha256=sha(p),declared_license=m.get('License-Expression') or m.get('License'),license_files=lic,upstream=m.get_all('Project-URL') or m.get('Home-page'),requires_dist=m.get_all('Requires-Dist',[])))
        if p.name.lower().startswith(('license','notice','copying')) or '/licenses/' in '/'+rel.lower():
            licenses.append(dict(path=rel,sha256=sha(p),bytes=p.stat().st_size))
    return dict(npm=npm,wheels=wheels,license_files=licenses)


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('mode',choices=['inventory','scan','git','frozen','packages']);a.add_argument('path',type=Path)
    a.add_argument('--tracked',action='store_true');a.add_argument('--output',type=Path,required=True)
    args=a.parse_args();out=args.output.resolve();root=args.path.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Output must be inside repository tmp/')
    if out.exists():raise ValueError('Choose a new output file; evidence is not overwritten')
    if args.mode=='scan':result=scan(root,args.tracked)
    else:result={'inventory':inventory,'git':scan_git,'frozen':frozen,'packages':packages}[args.mode](root)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(mode=args.mode,output=safe_path(out),items={k:len(v) for k,v in result.items() if isinstance(v,list)},coverage=result.get('coverage')),ensure_ascii=False))


if __name__=='__main__':main()
