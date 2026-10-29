"""Read Mach-O deployment targets without loading code (also works on Windows).

This is a static compatibility gate, not an OS/API/Metal execution certificate.
SDK and deployment target are deliberately separate fields. Every slice is read;
only the requested execution architecture contributes to its system minimum.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from twobyteasr.system.macos_compatibility import parse_macos_version as version

MAGICS = {bytes.fromhex(x) for x in (
    'feedface', 'feedfacf', 'cefaedfe', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
CPU = {7: 'i386', 0x1000007: 'x86_64', 12: 'arm', 0x100000C: 'arm64'}


def packed_version(value: int) -> str:
    return f'{value >> 16}.{(value >> 8) & 255}.{value & 255}'


def _slice(data: bytes) -> dict:
    magic = data[:4]
    endian = '<' if magic in (bytes.fromhex('cefaedfe'), bytes.fromhex('cffaedfe')) else '>'
    is64 = magic in (bytes.fromhex('feedfacf'), bytes.fromhex('cffaedfe'))
    header = 32 if is64 else 28
    if len(data) < header:
        raise ValueError('Truncated Mach-O header')
    _, cpu, subtype, filetype, ncmds, cmdbytes, _ = struct.unpack_from(endian + '7I', data)
    limit = header + cmdbytes
    if limit > len(data) or ncmds > cmdbytes // 8:
        raise ValueError('Invalid Mach-O load-command table')
    row = dict(architecture=CPU.get(cpu, hex(cpu)), cpu_subtype=subtype, file_type=filetype,
               minimum_macos=None, sdk=None, linked=[], rpaths=[])
    cursor = header
    for _ in range(ncmds):
        if cursor + 8 > limit:
            raise ValueError('Truncated Mach-O load command')
        command, size = struct.unpack_from(endian + '2I', data, cursor)
        if size < 8 or cursor + size > limit:
            raise ValueError('Invalid Mach-O command size')
        base_command = command & 0x7fffffff
        if base_command in (0x24, 0x32):
            required = 24 if base_command == 0x32 else 16
            if size < required:
                raise ValueError('Truncated Mach-O version command')
            if base_command == 0x32:
                platform_id, minimum, sdk = struct.unpack_from(endian + '3I', data, cursor + 8)
                if platform_id != 1:
                    raise ValueError('Non-macOS Mach-O platform: ' + str(platform_id))
            else:
                minimum, sdk = struct.unpack_from(endian + '2I', data, cursor + 8)
            target = packed_version(minimum)
            if row['minimum_macos'] is None or version(target) > version(row['minimum_macos']):
                row.update(minimum_macos=target, sdk=packed_version(sdk))
        elif base_command in (0xc, 0x18, 0x1f, 0x20, 0x23, 0x1c):
            if size < 12:
                raise ValueError('Truncated Mach-O string command')
            offset = struct.unpack_from(endian + 'I', data, cursor + 8)[0]
            if not 12 <= offset < size:
                raise ValueError('Invalid Mach-O string offset')
            raw = data[cursor + offset:cursor + size]
            if b'\0' not in raw:
                raise ValueError('Unterminated Mach-O string')
            text = raw.split(b'\0', 1)[0].decode('utf8', 'strict')
            if base_command == 0x1c:
                row['rpaths'].append(text)
            else:
                row['linked'].append(dict(path=text, weak=base_command == 0x18))
        cursor += size
    if cursor != limit:
        raise ValueError('Mach-O command table length differs')
    return row


def parse_macho(data: bytes) -> list[dict]:
    magic = data[:4]
    if magic not in MAGICS:
        return []
    if magic not in {bytes.fromhex(x) for x in ('cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}:
        return [_slice(data)]
    endian = '>' if magic in (bytes.fromhex('cafebabe'), bytes.fromhex('cafebabf')) else '<'
    is64 = magic in (bytes.fromhex('cafebabf'), bytes.fromhex('bfbafeca'))
    if len(data) < 8:
        raise ValueError('Truncated fat header')
    count = struct.unpack_from(endian + 'I', data, 4)[0]
    width = 32 if is64 else 20
    if not 0 < count <= 64 or 8 + count * width > len(data):
        raise ValueError('Invalid fat architecture table')
    slices = []
    ranges = []
    for index in range(count):
        cpu, subtype, offset, size, *_ = struct.unpack_from(
            endian + ('IIQQII' if is64 else '5I'), data, 8 + index * width)
        if offset < 8 + count * width or size < 28 or offset + size > len(data):
            raise ValueError('Fat slice outside file')
        if any(offset < end and offset + size > start for start, end in ranges):
            raise ValueError('Overlapping fat slices')
        ranges.append((offset, offset + size))
        chunk = data[offset:offset + size]
        if chunk[:4] not in {bytes.fromhex(x) for x in ('feedface','feedfacf','cefaedfe','cffaedfe')}:
            raise ValueError('Invalid fat slice magic')
        row = _slice(chunk)
        if row['architecture'] != CPU.get(cpu, hex(cpu)) or row['cpu_subtype'] != subtype:
            raise ValueError('Fat architecture disagrees with slice')
        slices.append(row)
    return slices


def audit_tree(root: Path, *, arch: str, target: str, allow_external: bool = False) -> dict:
    root = root.resolve()
    minimum = version(target)
    rows, errors = [], []
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic not in MAGICS:
            continue
        name = path.relative_to(root).as_posix()
        data = path.read_bytes()
        try:
            slices = parse_macho(data)
        except (ValueError, struct.error) as exc:
            errors.append(dict(path=name, reason='malformed_macho', detail=str(exc)))
            continue
        row = dict(path=name, sha256=hashlib.sha256(data).hexdigest(), slices=slices)
        rows.append(row)
        selected = [s for s in slices if s['architecture'] == arch]
        if not selected:
            errors.append(dict(path=name, reason='missing_architecture', required=arch))
        for item in selected:
            if item['minimum_macos'] is None:
                errors.append(dict(path=name, reason='unknown_deployment_target'))
            elif version(item['minimum_macos']) > minimum:
                errors.append(dict(path=name, reason='minimum_macos', required=item['minimum_macos']))
            if not allow_external:
                for link in item['linked']:
                    value = link['path']
                    if value.startswith('/') and not value.startswith(('/usr/lib/', '/System/Library/')):
                        errors.append(dict(path=name, reason='external_dependency', dependency=value))
                for value in item['rpaths']:
                    if value.startswith('/') and not value.startswith(('/usr/lib/', '/System/Library/')):
                        errors.append(dict(path=name, reason='external_rpath', dependency=value))
    if not rows:
        errors.append(dict(reason='no_native_objects'))
    plist = root / 'Contents/Info.plist'
    declaration = None
    if plist.is_file():
        info = plistlib.loads(plist.read_bytes())
        declaration = info.get('LSMinimumSystemVersionByArchitecture', {}).get(arch, info.get('LSMinimumSystemVersion'))
        if not declaration or version(declaration) > minimum:
            errors.append(dict(path='Contents/Info.plist', reason='app_minimum_macos', required=declaration))
    return dict(schema_version=1, kind='static_macho_audit', architecture=arch, target_macos=target,
                declared_minimum=declaration, native_file_count=len(rows), objects=rows, errors=errors,
                passed=not errors, execution_verified=False, symbol_availability_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-external', action='store_true', help='For pre-relocation inputs only')
    args = parser.parse_args(argv)
    result = audit_tree(args.root, arch=args.arch, target=args.target, allow_external=args.allow_external)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({k: result[k] for k in ('passed','native_file_count','target_macos','architecture')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
