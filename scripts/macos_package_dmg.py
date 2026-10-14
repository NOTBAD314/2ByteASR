# SPDX-License-Identifier: GPL-3.0-only
"""Create and verify a native DMG using only a disposable installation copy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.macos_build import bundle_inventory, product_version, sha256


def isolated_output(value: Path) -> Path:
    if not value.is_absolute():
        raise ValueError('An absolute disposable tmp output is required')
    output = value.resolve()
    if 'tmp' not in {part.casefold() for part in output.parts} or output.exists():
        raise ValueError('Select a fresh directory within a disposable tmp boundary')
    return output


def app_identity(app: Path) -> dict:
    candidates = [app/'Contents'/folder/'2byteasr_build.json'
                  for folder in ('Resources', 'Frameworks')]
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise ValueError('The built app is missing its exact 2byteasr_build.json identity')
    if len({sha256(path) for path in candidates}) != 1:
        raise ValueError('App build-identity copies disagree')
    identity = json.loads(candidates[0].read_text('utf8'))
    version = product_version()
    if (identity.get('app_version') != version
            or not re.fullmatch(r'[0-9a-fA-F]{40}', identity.get('git_sha', ''))
            or not re.fullmatch(r'[0-9a-fA-F]{64}', identity.get('source_sha256', ''))
            or not isinstance(identity.get('source_file_count'), int)
            or identity['source_file_count'] <= 0):
        raise ValueError(f'Expected an exact {version} native build identity')
    return identity


def inventory(app: Path) -> list[dict]:
    return [dict(path='.', kind='directory', mode=stat.S_IMODE(app.stat().st_mode))] + bundle_inventory(app)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Real builder-produced 2ByteASR.app')
    parser.add_argument('--output', type=Path, required=True, help='New absolute tmp directory')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required; no placeholder DMG is created')
    output = isolated_output(args.output)
    app = args.app.resolve()
    if app.name != '2ByteASR.app' or not (app/'Contents/MacOS/2ByteASR').is_file():
        raise ValueError('--app must identify the actual builder-produced 2ByteASR.app')
    identity = app_identity(app)
    expected = inventory(app)
    output.mkdir(parents=True)
    saved = output/'dmg-result.json'
    receipt = dict(passed=False, source_app=str(app), source_identity=identity,
                   target='darwin-arm64', developer_id_signed=False, notarized=False,
                   real_applications_modified=False, validation={})
    log = output/'dmg.log'
    mount = output/'mounted'
    mounted = False

    def write():
        saved.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', 'utf8')

    def execute(command, timeout=300):
        result = subprocess.run(list(map(str, command)), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
        with log.open('ab') as stream:
            stream.write(('COMMAND '+json.dumps(list(map(str, command)), ensure_ascii=False)+'\n').encode('utf8'))
            stream.write(result.stdout)
            stream.write(result.stderr)
        if result.returncode:
            raise RuntimeError(f'Native packaging command failed ({result.returncode}); see {log}')
        return result.stdout

    def match(actual: Path, label: str):
        if inventory(actual) != expected:
            raise RuntimeError(label+' app bytes, permissions or symlinks differ from the built app')
        execute(['/usr/bin/codesign', '--verify', '--deep', '--strict', actual], timeout=90)
        receipt['validation'][label] = dict(bytes_permissions_symlinks_match=True,
                                            ad_hoc_signature_verified=True)

    write()
    try:
        execute(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], timeout=90)
        staging = output/'image-root'
        staging.mkdir()
        execute(['/usr/bin/ditto', app, staging/app.name])
        match(staging/app.name, 'staging')
        os.symlink('/Applications', staging/'Applications')
        (staging/'安装说明.txt').write_text(
            f'兔白字幕 / 2ByteASR {product_version()}\n\n'
            '将 2ByteASR.app 拖到 Applications（应用程序）即可安装。\n'
            '适用于 macOS 15 或更新版本的 Apple Silicon Mac。\n'
            '本包使用 ad hoc 签名，尚未 Developer ID 签名或公证。\n', 'utf8')
        manifest = output/'dmg-bundle-inventory.json'
        manifest.write_text(json.dumps(expected, ensure_ascii=False, indent=2)+'\n', 'utf8')
        receipt['bundle_inventory'] = dict(file=manifest.name, sha256=sha256(manifest),
                                           entries=len(expected))
        dmg = output/f'2ByteASR-{product_version()}-macos-arm64-Setup.dmg'
        # hdiutil create can fail with "Resource busy" while the system still
        # scans the freshly copied app (2026-10-14 CI run 38525301867, same
        # source built fine in the run before): retry a few times, nothing else.
        for attempt in range(4):
            try:
                execute(['/usr/bin/hdiutil', 'create', '-volname', f'2ByteASR {product_version()}',
                         '-srcfolder', staging, '-fs', 'HFS+', '-format', 'UDZO', dmg], timeout=600)
                break
            except RuntimeError:
                busy = b'Resource busy' in log.read_bytes()[-4096:]
                if attempt == 3 or not busy:
                    raise
                dmg.unlink(missing_ok=True)
                receipt.setdefault('validation', {}).setdefault('hdiutil_busy_retries', 0)
                receipt['validation']['hdiutil_busy_retries'] += 1
                time.sleep(15 * (attempt + 1))
        receipt['artifact'] = dict(file=dmg.name, bytes=dmg.stat().st_size, sha256=sha256(dmg))
        execute(['/usr/bin/hdiutil', 'verify', dmg], timeout=180)
        receipt['validation']['dmg_verified'] = True
        mount.mkdir()
        attached = execute(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse',
                            '-noautoopen', '-mountpoint', mount, '-plist', dmg], timeout=180)
        mounted = True
        entities = plistlib.loads(attached).get('system-entities', [])
        if not any(Path(row.get('mount-point', '/')).resolve() == mount for row in entities):
            raise RuntimeError('DMG did not mount at its isolated expected location')
        applications = mount/'Applications'
        if not applications.is_symlink() or os.readlink(applications) != '/Applications':
            raise RuntimeError('DMG is missing the exact Applications drag-install link')
        receipt['validation']['applications_link'] = '/Applications'
        match(mount/app.name, 'mounted_read_only')
        installed_parent = output/'installed'/'兔白 字幕・安裝測試'
        installed_parent.mkdir(parents=True)
        installed = installed_parent/app.name
        execute(['/usr/bin/ditto', mount/app.name, installed])
        match(installed, 'installed_unicode_copy')
        receipt['installed_app'] = str(installed)
        receipt['installed_executable'] = str(installed/'Contents/MacOS/2ByteASR')
        if app_identity(installed) != identity or inventory(app) != expected:
            raise RuntimeError('Installed identity or original built app changed during packaging')
        receipt['validation']['source_app_unchanged'] = True
    except Exception:
        receipt['error'] = traceback.format_exc()
    finally:
        # A timed-out or failing attach can still have mounted its image.
        # Only the explicitly owned mountpoint is considered for cleanup.
        if mounted or os.path.ismount(mount):
            try:
                execute(['/usr/bin/hdiutil', 'detach', mount], timeout=90)
                receipt['validation']['detached_normally'] = True
            except Exception:
                receipt['detach_error'] = traceback.format_exc()
        receipt['passed'] = bool('error' not in receipt and 'detach_error' not in receipt
                                 and receipt['validation'].get('detached_normally'))
        write()
    print(json.dumps(dict(passed=receipt['passed'], artifact=receipt.get('artifact'),
                          installed_app=receipt.get('installed_app'), receipt=str(saved)), ensure_ascii=False))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
