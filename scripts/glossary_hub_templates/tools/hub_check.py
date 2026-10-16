# SPDX-License-Identifier: GPL-3.0-only
"""Check this repository's libraries (and, without --libraries-only, index.json).

glossary_lint.py and glossary_hub_repo.py are copies from 2ByteASR
(twobyteasr/glossary/); the maintainer refreshes them with
``scripts/glossary_hub.py init-repo --force``.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import glossary_hub_repo  # noqa: E402
from glossary_lint import WARN  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libraries-only", action="store_true")
    args = parser.parse_args()
    repo = HERE.parent
    errors = []
    for path in sorted((repo / "libraries").glob("*.json")):
        _library, file_errors, findings = glossary_hub_repo.check_library(path)
        errors += file_errors
        warns = [item for item in findings if item.level == WARN]
        if warns:
            print(f"! {path.stem}: {len(warns)} 条提醒（安装时默认不勾）")
    if not args.libraries_only:
        errors = list(dict.fromkeys(errors + glossary_hub_repo.check_repo(repo)))
    for line in errors:
        print("✗ " + line)
    if errors:
        sys.exit(f"{len(errors)} 个问题")
    print("检查通过")


if __name__ == "__main__":
    main()
