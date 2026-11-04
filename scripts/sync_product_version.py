# SPDX-License-Identifier: GPL-3.0-only
"""Synchronize first-party metadata from 2byteasr_version.json; never dependencies."""
from pathlib import Path
import argparse,json,re

ROOT=Path(__file__).resolve().parents[1]
def synchronize(check=False):
    version=json.loads((ROOT/'2byteasr_version.json').read_text('utf-8-sig'))['version']
    match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-test\.(\d+))?',version)
    if not match:raise ValueError('Unsupported product resource version: '+version)
    parts=tuple(int(n or 0) for n in match.groups())
    updates={}
    resource=ROOT/'packaging/version_info.txt'
    text=resource.read_text('utf8')
    text=re.sub(r'(filevers|prodvers)=\([\d, ]+\)',lambda m:m[1]+'='+str(parts),text)
    text=re.sub(r"StringStruct\(u'FileVersion', u'[^']+'\)",f"StringStruct(u'FileVersion', u'{'.'.join(map(str,parts))}')",text)
    text=re.sub(r"StringStruct\(u'ProductVersion', u'[^']+'\)",f"StringStruct(u'ProductVersion', u'{version}')",text)
    updates[resource]=text
    for folder in ['renderer','website']:
        path=ROOT/folder/'package.json'
        if path.is_file():
            payload=json.loads(path.read_text('utf8'));payload['version']=version
            updates[path]=json.dumps(payload,ensure_ascii=False,indent=2)+'\n'
        lock=ROOT/folder/'package-lock.json'
        if lock.is_file():
            payload=json.loads(lock.read_text('utf8'));payload['version']=version
            if '' in payload.get('packages',{}):payload['packages']['']['version']=version
            updates[lock]=json.dumps(payload,ensure_ascii=False,indent=2)+'\n'
    mismatches=[]
    for path,text in updates.items():
        old=path.read_text('utf8')
        if old!=text:
            mismatches.append(path.relative_to(ROOT).as_posix())
            if not check:path.write_text(text,encoding='utf8',newline='\n')
    if check and mismatches:raise ValueError('Product metadata differs: '+', '.join(mismatches))
    return {'version':version,'windows_resource_version':list(parts),'updated':mismatches,'dependencies_changed':False}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true')
    print(json.dumps(synchronize(ap.parse_args().check),ensure_ascii=False))

