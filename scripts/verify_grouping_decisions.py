"""Replay the frozen 10ab task without ASR or external model requests."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--fixture',type=Path,default=ROOT/'tests/fixtures/grouping_contract/luoke_10ab.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--media',type=Path)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--reverse-completion',action='store_true')
    parser.add_argument('--baseline',action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh directory under source/tmp.')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    sys.path.insert(0,str(args.source_root.resolve()))
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install(); install_pytest_network_guard()
    spec = importlib.util.spec_from_file_location('decision_audit',ROOT/'twobyteasr/acceptance/grouping_decision_audit.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    fixture = json.loads(args.fixture.read_text(encoding='utf-8'))
    result,rows,cues = audit.replay(fixture,workers=args.workers,reverse_completion=args.reverse_completion)
    if not args.baseline:
        result = audit.save_replay(output,fixture,result,rows,cues,media=args.media)
    else:
        result['recorded_batches_reproduced'] = all(
            detail['after'] == batch['final_texts'] for detail,batch in zip(result['details'],fixture['batches']))
    (output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('passed','checks','timeline_sha256')},ensure_ascii=False))
    return 0 if result['passed'] or args.baseline and result['recorded_batches_reproduced'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
