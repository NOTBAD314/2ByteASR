"""Check scripts/model_download_sources.json against the product lock (network, opt-in).

For every ModelScope pin: list the repository at the pinned commit through the
public API and require each locked file to exist with the locked SHA-256. Also
reports whether the pin is actually applied (the lock wins when it already pins
a commit or declares the source incompatible). Reads metadata only; no weights.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.allow_network:
        parser.error('需要显式 --allow-network（只读取 ModelScope 公开元数据）')
    import requests
    from twobyteasr.download_diagnostics import AnonymousAuth
    from twobyteasr.repository_download import effective_spec, load_model_sources, planned_sources

    lock = json.loads((ROOT / 'dependencies.lock.json').read_text('utf-8-sig'))['models']
    pins = load_model_sources().get('modelscope') or {}
    session = requests.Session()
    session.trust_env = True
    session.auth = AnonymousAuth()
    report, ok = {}, True
    from twobyteasr.repository_download import partial_source_manifest
    entries = [(key, pin, None) for key, pin in sorted(pins.items())]
    entries += [(key, pin, 'partial') for key, pin in sorted((load_model_sources().get('modelscope_partial') or {}).items())]
    for key, pin, kind in entries:
        row = dict(repository=pin.get('repository'), revision=pin.get('revision'))
        spec = lock.get(key)
        if not spec:
            row.update(status='FAIL', reason='lock 中没有该模型')
            ok = False
            report[key] = row
            continue
        if kind == 'partial':
            modelscope = partial_source_manifest(key, spec)
            row['partial_files'] = list(modelscope.files) if modelscope else []
        else:
            modelscope = next((m for m in planned_sources(effective_spec(key, spec), 'AUTO') if m.mode == 'MODELSCOPE'), None)
        row['applied'] = bool(modelscope and modelscope.revision == pin.get('revision'))
        url = (f"https://modelscope.cn/api/v1/models/{pin['repository']}/repo/files"
               f"?Revision={quote(str(pin['revision']), safe='')}&Recursive=true")
        try:
            response = session.get(url, timeout=(10, 40))
            files = {f['Path']: f for f in ((response.json().get('Data') or {}).get('Files') or [])}
        except (requests.RequestException, ValueError) as exc:
            row.update(status='FAIL', reason=f'{type(exc).__name__}: {exc}')
            ok = False
            report[key] = row
            continue
        checked = list(modelscope.files) if kind == 'partial' and modelscope else list(spec.get('required_files') or [])
        mismatches = [name for name in checked
                      if (files.get(name) or {}).get('Sha256', '').lower() != str((spec.get('sha256') or {}).get(name, '')).lower()]
        row.update(status='PASS' if not mismatches and row['applied'] else 'FAIL', mismatches=mismatches,
                   checked_files=len(checked))
        ok = ok and row['status'] == 'PASS'
        report[key + (' (partial)' if kind else '')] = row
        print(f"{key + (' (partial)' if kind else ''):24} {row['status']} applied={row['applied']} mismatches={mismatches}", flush=True)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
