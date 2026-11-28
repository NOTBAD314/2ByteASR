# SPDX-License-Identifier: GPL-3.0-only
"""Verify code-signing resources and the actual installed app after use."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.macos_package_dmg import inventory, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text('utf-8'))
    assert receipt['passed']
    expected_file = args.receipt.with_name(receipt['bundle_inventory']['file'])
    assert sha256(expected_file) == receipt['bundle_inventory']['sha256']
    expected = {row['path']: row for row in json.loads(expected_file.read_text('utf-8'))}
    actual = {row['path']: row for row in inventory(args.app)}
    seal = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(args.app)],
                          capture_output=True, text=True, timeout=180)
    added = sorted(actual.keys() - expected.keys())
    removed = sorted(expected.keys() - actual.keys())
    changed = [key for key in sorted(expected.keys() & actual.keys()) if expected[key] != actual[key]]
    result = {'passed': not (seal.returncode or added or removed or changed), 'dmg_sha256': receipt['artifact']['sha256'],
              'source_sha': receipt['source_identity']['git_sha'], 'entries': len(actual),
              'added': added, 'removed': removed, 'changed': changed, 'codesign_exit': seal.returncode,
              'codesign_stderr': seal.stderr}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({**result, 'codesign_stderr': seal.stderr[-600:]}, ensure_ascii=False))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
