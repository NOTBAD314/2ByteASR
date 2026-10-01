"""Reproduce the private x64 runtime from the unmodified official installer.

Requires the verified InnoUnp 2.71.1 utility; does not run the installer, install
file associations, change a personal profile, or overwrite an existing runtime.
"""
import argparse,hashlib,json,re,shutil,subprocess,tempfile
from pathlib import Path

INSTALLER_SHA256='9337cccbc01d4098ee7a3dab215b3afbe6ece99c5287c92441d6f12cf541ebca'
SOURCE_SHA256='40b15e90ad0c0c631b76da3c467ea9847fa5c24f37413ac5b492804860a28cd8'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def deploy(extracted,destination):
    extracted=Path(extracted).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Destination exists; preserve it and choose a new directory')
    files=[]
    for line in (extracted/'install_script.iss').read_text(encoding='utf-8-sig').splitlines():
        if not line.startswith('Source: "{app}\\'):continue
        fields={}
        for match in re.finditer(r'(\w+):\s*(?:"([^"]*)"|([^;]+))',line):
            fields[match[1]]=(match[2] if match[2] is not None else match[3]).strip()
        component=fields.get('Components','')
        if 'dontcopy' in fields.get('Flags','') or re.search(r'\b(?:dev|debug)',component):continue
        if 'ARM64' in component and 'X64' not in component:continue
        if not fields.get('DestDir','').startswith('{app}'):continue
        source=extracted/fields['Source']
        target=destination/fields['DestDir'].removeprefix('{app}').lstrip('\\')/fields.get('DestName',source.name)
        if not source.resolve().is_relative_to(extracted) or not target.resolve().is_relative_to(destination):raise ValueError('Unsafe installer path')
        if target.exists() and sha(source)!=sha(target):raise ValueError('Conflicting component destinations')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        files.append(dict(path=target.relative_to(destination).as_posix(),bytes=target.stat().st_size,sha256=sha(target)))
    (destination/'2byte-runtime-files.json').write_text(json.dumps(files,indent=2),encoding='utf8')
    return files


def main():
    p=argparse.ArgumentParser();p.add_argument('--installer',type=Path,required=True);p.add_argument('--unpacker',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    args=p.parse_args()
    if sha(args.installer)!=INSTALLER_SHA256 or sha(args.source)!=SOURCE_SHA256:raise ValueError('Official archive hash mismatch')
    root=Path(__file__).resolve().parents[1];tmp=root/'tmp';tmp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gimp-deploy-',dir=tmp) as temporary:
        extracted=Path(temporary)/'extracted'
        subprocess.run([str(args.unpacker.resolve()),'-x','-b','-q','-m','-a','-d'+str(extracted),str(args.installer.resolve())],check=True)
        files=deploy(extracted,args.destination)
    notices=args.destination/'source-and-licenses';notices.mkdir()
    shutil.copy2(args.source,notices/'gimp-3.2.6.tar.xz')
    resources=root/'assets/gimp'
    for filename in ('COPYING-GIMP.txt','RUNTIME-NOTICE.md','runtime.json'):
        shutil.copy2(resources/filename,notices/filename)
    print(json.dumps(dict(files=len(files),bytes=sum(f['bytes'] for f in files),destination=str(args.destination.resolve()))))


if __name__=='__main__':main()
