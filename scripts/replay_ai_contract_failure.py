"""Offline, immutable request evidence and contract replay. No provider calls."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():
        raise ValueError('Use a new output directory under repository tmp')
    out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='offscreen')
    from twobyteasr.caption_creative_pipeline import ThemeLedger
    from twobyteasr.authored_repair import collect_issues
    from twobyteasr.structured_output import response_object
    original = out/'original'
    original.mkdir()
    hashes = {}
    for path in args.source.iterdir():
        if path.is_file() and path.suffix in ('.json', '.txt'):
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            shutil.copyfile(path, original/path.name)
    ledger = ThemeLedger.open(original/'ledger.json')
    ledger.save = lambda: None
    payload = response_object((original/'provider-original.txt').read_text('utf8'))
    result = dict(provider_calls=0, original_sha256=hashes, before=collect_issues(payload, ledger), children=[])
    for record in ledger.value.get('technical_repairs', []):
        if record['operation'] != 'regenerate_candidate':
            continue
        child = response_object(json.loads((original/f"technical-{record['repair_request_id']}.json").read_text('utf8')))
        replay = copy.deepcopy(payload)
        replay['candidates'][record['candidate_index']] = child
        result['children'].append(dict(repair_request_id=record['repair_request_id'],
            issues=collect_issues(replay, ledger), changed_paths=record.get('changed_paths'),
            source=child['generated_source'], original_record=record))
    result['source_unchanged'] = all(hashlib.sha256((args.source/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())
    (out/'replay.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(output=str(out), before=result['before'],
        children=[dict(repair_request_id=r['repair_request_id'], issues=r['issues']) for r in result['children']],
        source_unchanged=result['source_unchanged']), ensure_ascii=False))


if __name__ == '__main__':
    main()
