"""Compare every real bilingual display cue with the whole-project renderer."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        parser.error('Fresh output under repository tmp required')
    out.parent.mkdir(parents=True, exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out.parent/'equivalence-profile')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from twobyteasr.test_isolation import install, require_isolated_paths
    install()
    require_isolated_paths('all real caption equivalence')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache, materialize_captions
    from twobyteasr.caption_style.caption_layer_transform import resolved_values
    from tests.test_caption_geometry_fast_path import reference
    raw = args.project.read_bytes()
    project = load_project(args.project)
    revision = StudioRevisionStore(project).render
    started = time.perf_counter()
    full = materialize_captions(revision)[0]
    expected = {c.id: asdict(c) for c in full.project.cues}
    cache = PlaybackCaptionCache()
    seen = set()
    errors = []
    previous = None
    cues = revision.timeline_cues if revision.timeline_cues is not None else revision.cues
    for index in range(0, len(cues), 11):
        window = cache._window_revision(revision, tuple(c.id for c in cues[index:index+11]))
        current = materialize_captions(window, previous)[0]
        previous = current
        for cue in current.project.cues:
            seen.add(cue.id)
            if asdict(cue) != expected.get(cue.id):
                errors.append({'cue': cue.id, 'problem': 'display geometry/content mismatch'})
    for cue in project.cues:
        if resolved_values(project, cue, 'original', geometry_only=True) != reference(project, cue, 'original'):
            errors.append({'cue': cue.id, 'problem': 'numeric geometry mismatch'})
    from twobyteasr.caption_style.scoped_transform import transform_plan
    from twobyteasr.caption_style.bulk_transform_preparation import prepare_plan
    authoring = StudioRevisionStore(project).authoring_render()
    ids = [c.id for c in project.cues]
    cases = [{'position_x':1000., 'position_y':900.}, {'scale_x':115.}, {'rotation':8.}]
    for fields in cases:
        expected_plan = transform_plan(project, ids, 'linked', fields, reference_id=ids[0])
        detached_plan = prepare_plan(authoring, ids, 'linked', fields, reference_id=ids[0])
        if expected_plan != detached_plan:
            errors.append({'problem':'bulk transform mismatch', 'fields':fields})
    cache.close()
    result = {'original_sha256': hashlib.sha256(raw).hexdigest(),
        'original_unchanged': args.project.read_bytes()==raw, 'source_cues':len(cues),
        'full_display_cues':len(expected), 'window_display_cues':len(seen),
        'all_display_cues_equal':seen==set(expected) and not errors,
        'numeric_geometry_cues':len(project.cues), 'errors':errors,
        'bulk_transform_cases':len(cases),
        'elapsed_s':time.perf_counter()-started}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
    return not result['all_display_cues_equal'] or not result['original_unchanged']


if __name__ == '__main__':
    raise SystemExit(main())
