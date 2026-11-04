"""Author review pictures for the curated motion catalog, with isolated data.

  python -X utf8 scripts/verify_motion_catalog.py --output tmp/<new dir> [--part sheets|ass|remotion|gallery]

sheets: every preset sampled across its window (LIVE renderer).
ass: LIVE frame next to the libass frame of the compiled ASS.
remotion: gradient captions exported through Remotion next to LIVE.
gallery: labelled MP4 of every preset.
"""
from pathlib import Path
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--part', choices=('sheets', 'ass', 'remotion', 'gallery', 'all'), default='all')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Output must be under repository tmp/')
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/'data'), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
                      TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance import motion_catalog_audit as audit
    parts = ('sheets', 'ass', 'remotion', 'gallery') if args.part == 'all' else (args.part,)
    for part in parts:
        target = output/part
        {'sheets': audit.contact_sheets, 'ass': audit.ass_comparison,
         'remotion': audit.remotion_comparison, 'gallery': audit.gallery_video}[part](target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
