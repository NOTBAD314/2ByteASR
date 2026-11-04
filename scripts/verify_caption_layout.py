"""Prepare or render the caption-layout matrix in an isolated tmp directory.

--implementation lets the same fixture and audit code exercise a frozen old
source tree. It never modifies that tree or reads the operator's preferences.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--implementation', type=Path, default=root)
    parser.add_argument('--cases', default='')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):
        raise ValueError('Use a fresh directory under this worktree tmp/')
    output.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/'profile'), QT_QPA_PLATFORM='offscreen',
                      TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', PYTHONDONTWRITEBYTECODE='1',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    sys.path.insert(0, str(args.implementation.resolve()))
    from twobyteasr.test_isolation import install
    install()
    spec = importlib.util.spec_from_file_location('twobyteasr.acceptance.caption_layout_audit',
                                                  root/'twobyteasr/acceptance/caption_layout_audit.py')
    audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
    manifest = args.fixtures.resolve()/'cases.json' if args.fixtures else output/'fixtures/cases.json'
    if not args.fixtures:
        audit.fixtures(manifest.parent)
    if args.prepare_only:
        print(manifest)
        return 0
    return 0 if audit.render_matrix(manifest, output/'rendered',
                                    selected=set(filter(None, args.cases.split(',')))) else 1


if __name__ == '__main__':
    raise SystemExit(main())
