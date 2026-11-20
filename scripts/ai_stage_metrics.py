"""Counters of the AI proofreading / grouping stages in task journals.

    python scripts/ai_stage_metrics.py task.json            # one run, as JSON
    python scripts/ai_stage_metrics.py before.json after.json   # what changed

The journal is the task JSON the app saves (recognition history / 診斷報告). Run the same
material before and after a prompt or policy change and compare.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.recognition.ai_stage_metrics import compare, load, measure  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__)
        return 2
    runs = [measure(load(path)) for path in argv]
    if len(runs) == 1:
        print(json.dumps(runs[0], ensure_ascii=False, indent=2))
        return 0
    changed = compare(*runs)
    if not changed:
        print('No counter changed.')
    for path, before, after in changed:
        print(f'{path}: {before} -> {after}')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main(sys.argv[1:]))
