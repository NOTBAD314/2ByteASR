"""Check external download-worker imports in an assembled bundle, without network.

Frozen GUI imports cannot satisfy the independent managed Python worker. Its
project imports must also be present as ordinary source files in the payload.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def check_bundle(bundle: Path) -> dict:
    pending = [(bundle / 'scripts' / name, '') for name in
               ('download_file_fast.py', 'run_repository_download.py')]
    checked, missing = set(), set()
    while pending:
        path, module = pending.pop()
        relative = path.relative_to(bundle).as_posix()
        if relative in checked:
            continue
        checked.add(relative)
        if not path.is_file():
            missing.add(relative)
            continue
        tree = ast.parse(path.read_text('utf-8-sig'), filename=str(path))
        # Imports inside functions are optional/lazy; this gate checks startup.
        nodes = list(tree.body)
        while nodes:
            node = nodes.pop()
            if isinstance(node, (ast.If, ast.Try)):
                nodes.extend(node.body + node.orelse)
                if isinstance(node, ast.Try):
                    nodes.extend(node.finalbody)
                    for handler in node.handlers:
                        nodes.extend(handler.body)
            names = []
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
                if node.level:
                    package = module.split('.')[:-node.level]
                    name = '.'.join([*package, name])
                names = [name]
            for name in names:
                if not name.startswith('twobyteasr.'):
                    continue
                source = bundle.joinpath(*name.split('.')).with_suffix('.py')
                package_init = bundle.joinpath(*name.split('.'), '__init__.py')
                pending.append((package_init if package_init.is_file() else source, name))
    return dict(passed=not missing, checked=sorted(checked), missing=sorted(missing),
                scope='Static startup dependency closure for external model download workers; no execution/network, not full runtime acceptance.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = check_bundle(args.bundle.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
