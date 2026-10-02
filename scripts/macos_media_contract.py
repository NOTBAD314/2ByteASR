# SPDX-License-Identifier: GPL-3.0-only
"""Separate formula declarations, installed identities and executable evidence."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def keg_version(expected: dict) -> str:
    return expected['version']+('_'+str(expected['revision']) if expected['revision'] else '')


def formula_name(name: str, expected: dict) -> str:
    return expected.get('formula_name', name)


def verify_required_filters(output: str, required: list[str]) -> None:
    names={match.group(1) for line in output.splitlines()
           if (match:=re.match(r'^\s*[TSC.]{2,3}\s+([a-z0-9_]+)\s+[AVN|]+->[AVN|]+\s',line))}
    missing=set(required)-names
    if missing:raise RuntimeError('Required media filters absent: '+', '.join(sorted(missing)))


def verify_media_formula(formula: dict, name: str, expected: dict, *, require_installed=True) -> dict:
    version=formula.get("versions",{}).get("stable")
    revision=formula.get("revision")
    if formula.get("name")!=formula_name(name, expected) or version!=expected["version"] or revision!=expected["revision"]:
        raise RuntimeError(f"Media formula drift: {name}: observed {formula.get('name')}@{version}_{revision}, expected {formula_name(name, expected)}@{expected['version']}_{expected['revision']}")
    bottle=formula.get("bottle",{}).get("stable",{}).get("files",{}).get("arm64_sequoia",{})
    if bottle.get("sha256")!=expected["arm64_sequoia_bottle"]["sha256"]:
        raise RuntimeError("Media arm64_sequoia bottle checksum drift: "+name)
    if bottle.get('url') and bottle['url']!=expected['arm64_sequoia_bottle']['url']:
        raise RuntimeError('Media bottle source drift: '+name)
    if require_installed:
        versions=[row.get('version') for row in formula.get('installed',[])]
        if keg_version(expected) not in versions:
            raise RuntimeError(f'Installed keg differs: {name}: {versions}, expected {keg_version(expected)}')
    return {"name":name,"formula_name":formula_name(name, expected),"version":version,"revision":revision,"bottle_tag":"arm64_sequoia","bottle_sha256":bottle["sha256"],"installed_checked":require_installed}


def verify_keg_receipt(receipt: dict,keg: Path,name: str,expected: dict) -> None:
    if keg.name!=keg_version(expected) or keg.parent.name!=formula_name(name, expected):
        raise RuntimeError('Installed keg path/revision differs: '+str(keg))
    if receipt.get('arch')!='arm64' or not receipt.get('poured_from_bottle'):
        raise RuntimeError('Installed receipt is not an arm64 poured bottle: '+name)
    source=receipt.get('source',{})
    stable=source.get('versions',{}).get('stable')
    # Homebrew keg pkg_version includes revision; runtime --version does not.
    if stable is not None and stable!=expected['version']:
        raise RuntimeError('Installed receipt stable version differs: '+name)
    if source.get('revision') is not None and source['revision']!=expected['revision']:
        raise RuntimeError('Installed receipt revision differs: '+name)


def verify_binary_evidence(tool: dict,keg: Path,expected: dict) -> None:
    real=Path(tool['path']).resolve()
    if not real.is_relative_to(keg.resolve()) or Path(tool['path_selected']).resolve()!=real:
        raise RuntimeError('PATH executable does not belong to verified keg: '+str(real))
    if 'arm64' not in tool['architecture'].split():raise RuntimeError('Wrong media architecture: '+str(real))
    if tool.get('exit_code')!=0 or not re.search(r'(?<![0-9.])'+re.escape(expected['version'])+r'(?![0-9.])',tool['version']):
        raise RuntimeError('Media runtime version differs: '+str(real))
    if not real.is_file() or digest(real)!=tool['sha256']:raise RuntimeError('Media executable digest differs: '+str(real))


def load_verified_tools(path: Path,lock_path: Path) -> dict:
    """Recheck sealed executable hashes, never resolve another PATH or API."""
    record=json.loads(path.read_text('utf8'));lock=json.loads(lock_path.read_text('utf8'))
    if not record.get('passed') or record.get('lock_sha256')!=digest(lock_path):
        raise RuntimeError('Media installation receipt is not verified against this lock')
    if record.get('core_commit')!=lock['homebrew_core']['commit'] or record.get('target')!='darwin-arm64':
        raise RuntimeError('Media installation source/target differs')
    tools={}
    for name,expected in lock['media'].items():
        entry=record['media'][name]
        if entry['archive']['sha256']!=expected['arm64_sequoia_bottle']['sha256'] or entry['archive']['url']!=expected['arm64_sequoia_bottle']['url']:
            raise RuntimeError('Media archive provenance differs: '+name)
        keg=Path(entry['keg']);rp=keg/'INSTALL_RECEIPT.json'
        if digest(rp)!=entry['receipt_sha256']:raise RuntimeError('Installed receipt changed: '+name)
        tab=json.loads(rp.read_text('utf8'))
        verify_keg_receipt(tab,keg,name,expected)
        if tab.get('source',{}).get('tap_git_head')!=record['core_commit']:
            raise RuntimeError('Installed receipt core snapshot differs: '+name)
        for binary,tool in entry['tools'].items():
            verify_binary_evidence(tool,keg,expected)
            arch=subprocess.check_output(['/usr/bin/lipo','-archs',tool['path']],text=True).strip()
            if arch!=tool['architecture']:raise RuntimeError('Media architecture changed: '+binary)
            actual=subprocess.check_output([tool['path'],'--version' if binary=='mpv' else '-version'],text=True)
            if actual.splitlines()[0]!=tool['version']:raise RuntimeError('Media output changed: '+binary)
            if binary=='ffmpeg' and expected.get('required_filters'):
                verify_required_filters(subprocess.check_output([tool['path'],'-hide_banner','-filters'],text=True),expected['required_filters'])
            tools[binary]=dict(tool)
    if set(tools)!={'ffmpeg','ffprobe','mpv'}:raise RuntimeError('Incomplete verified media tools')
    return tools
