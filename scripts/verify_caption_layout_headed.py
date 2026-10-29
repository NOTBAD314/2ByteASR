"""Normal source/EXE entry on an isolated Windows desktop; fixed tmp projects."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import shutil


def _artifact(folder, name):
    if not isinstance(name, str) or not name:
        raise ValueError('artifact path is missing')
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('artifact is absent, empty, or outside its case directory')
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic(rows):
    return [{key: row[key] for key in ('cue_id', 'text', 'layout', 'position', 'word_animation')}
            for row in rows]


def caption_completion_errors(result, cases, output, *, require_render):
    """Reject old/incomplete audits, reused targets and wrong-canvas pairings."""
    rows = result.get('cases')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return ['case receipts are missing or malformed']
    expected_ids, observed_ids = [case['id'] for case in cases], [row.get('id') for row in rows]
    if (len(observed_ids) != len(expected_ids) or set(observed_ids) != set(expected_ids)
            or len(set(observed_ids)) != len(observed_ids)):
        return ['requested case IDs were not completed exactly once']
    if not require_render:
        return []
    from PIL import Image
    errors = []
    observed = {row['id']: row for row in rows}
    for case in cases:
        try:
            record = observed[case['id']]
            folder = (Path(output) / case['id']).resolve()
            if not folder.is_relative_to(Path(output).resolve()):
                raise ValueError('case directory is outside this run')
            requested = case.get('sample_ms') or [150, 650, 1500, 2700]
            targets = [round(float(value)*30/1000) for value in requested]
            if len(set(targets)) != len(targets):
                raise ValueError('requested sample targets are duplicated')
            samples = json.loads(_artifact(folder, 'gui-animation-samples.json').read_text('utf8'))
            if not isinstance(samples, list) or len(samples) != len(targets) or record.get('animation_samples') != len(targets):
                raise ValueError('requested actual-PTS sample pairs are missing')
            if record.get('decoded_frames') != 90 or _sha(_artifact(folder, 'gui-export.mp4')) != record.get('movie_sha256'):
                raise ValueError('complete final movie decode/identity receipt is missing')
            changed = case['output'][0]*case['canvas'][1] != case['output'][1]*case['canvas'][0]
            design = [round(case['canvas'][1]*case['output'][0]/case['output'][1]), case['canvas'][1]] if changed else case['canvas']
            canvas = record.get('output_canvas') or {}
            if (record.get('original_canvas') != case['canvas'] or canvas.get('design') != design
                    or canvas.get('output') != case['output'] or canvas.get('relayout') != changed):
                raise ValueError('case output canvas identity differs')
            expected_layout = _semantic(json.loads(_artifact(folder, 'preview-layout-receipt.json').read_text('utf8')))
            seen_targets, seen_export_paths, seen_preview_paths = set(), set(), set()
            export_pixels, preview_pixels, preview_sizes = [], [], []
            for requested_ms, frame, sample in zip(requested, targets, samples):
                pts_ms = float(Fraction(str(sample['time_base'])) * int(sample['pts']) * 1000)
                values = [float(sample[key]) for key in ('actual_ms', 'requested_preview_ms', 'actual_playhead_ms')]
                if (sample.get('frame') != frame or sample.get('requested_ms') != requested_ms
                        or not all(map(math.isfinite, [pts_ms, *values]))
                        or abs(pts_ms-frame*1000/30) > .1 or abs(values[0]-pts_ms) > .001
                        or abs(values[1]-pts_ms) > .001 or abs(values[2]-pts_ms) > 2 or frame in seen_targets):
                    raise ValueError('duplicate or incorrectly timed encoded/preview sample')
                seen_targets.add(frame)
                if (sample.get('original_canvas') != case['canvas'] or sample.get('sampled_canvas') != design
                        or sample.get('render_truth', {}).get('project', {}).get('play_res') != design
                        or sample.get('complete_layout_semantics') is not True or _semantic(sample['layout']) != expected_layout):
                    raise ValueError('sample semantic/canvas identity differs')
                reopening = sample.get('gui_reopen') or {}
                if reopening.get('required') is not changed:
                    raise ValueError('derived GUI reopen requirement is missing')
                if changed:
                    derived_path = _artifact(folder, 'derived-output-preview.2byteproj')
                    if (reopening.get('performed') is not True or reopening.get('entry_calls') != [str(derived_path)]
                            or Path(reopening.get('project_path') or '').resolve() != derived_path
                            or reopening.get('old_object_id') == reopening.get('new_object_id')
                            or not isinstance(reopening.get('before_generation'), int)
                            or not isinstance(reopening.get('reopened_generation'), int)
                            or reopening['reopened_generation'] <= reopening['before_generation']):
                        raise ValueError('derived output project was not genuinely reopened in GUI')
                scene = sample.get('scene') or {}
                if case.get('route') in {'legacy', 'graph'} and scene.get('active') is not True:
                    raise ValueError('animated preview has no current caption scene')
                if scene.get('active') and (scene.get('current') is not True or scene.get('sample_ms') is None
                        or abs(float(scene['sample_ms'])-pts_ms) > 2
                        or any(row.get('status') != 'rendered' for row in scene.get('cue_pixels', []))):
                    raise ValueError('sample uses a stale/unprepared caption scene')
                export = _artifact(folder, sample['file']); preview = _artifact(folder, sample['preview'])
                if export in seen_export_paths or preview in seen_preview_paths:
                    raise ValueError('one PNG path is reused for different requested targets')
                seen_export_paths.add(export); seen_preview_paths.add(preview)
                if _sha(export) != sample.get('sha256') or _sha(preview) != sample.get('preview_sha256'):
                    raise ValueError('sample PNG file hash differs')
                with Image.open(export) as image:
                    rgb = image.convert('RGB'); export_hash = hashlib.sha256(rgb.tobytes()).hexdigest()
                    if list(rgb.size) != case['output'] or sample.get('dimensions') != case['output'] or export_hash != sample.get('rgb_sha256'):
                        raise ValueError('encoded PNG dimensions/pixels differ from decoded frame receipt')
                with Image.open(preview) as image:
                    rgb = image.convert('RGB'); preview_hash = hashlib.sha256(rgb.tobytes()).hexdigest()
                    if list(rgb.size) != sample.get('preview_dimensions') or preview_hash != sample.get('preview_rgb_sha256'):
                        raise ValueError('actual preview PNG pixels differ from its receipt')
                    preview_sizes.append(rgb.size)
                export_pixels.append(export_hash); preview_pixels.append(preview_hash)
            if len(set(preview_sizes)) != 1:
                raise ValueError('preview raster dimensions changed during the sample sequence')
            if case.get('route') in {'legacy', 'graph'}:
                settled = requested.index(1500)
                probes = [0] + ([requested.index(2850)] if 2850 in requested else [])
                if any(export_pixels[i] == export_pixels[settled] or preview_pixels[i] == preview_pixels[settled] for i in probes):
                    raise ValueError('animated entrance/exit reused settled pixels')
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError) as error:
            errors.append(case['id']+': '+str(error))
    return errors


def main():
    from isolated_windows_desktop import run_on_desktop
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--cases', default='native-chinese,dynamic-letter-stagger,changed-aspect-bilingual')
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):
        raise ValueError('Fresh worktree tmp directory required')
    output.mkdir(parents=True)
    manifest = args.fixtures.resolve()/'cases.json'
    cases = json.loads(manifest.read_text('utf-8'))['cases']
    selected = set(filter(None, args.cases.split(',')))
    ids = [case['id'] for case in cases]
    if len(ids) != len(set(ids)) or selected-set(ids):
        raise ValueError('Requested case IDs are missing or duplicated in the manifest')
    cases = [case for case in cases if not selected or case['id'] in selected]
    if not cases:
        raise ValueError('No selected cases')
    for case in cases:
        project = json.loads(Path(case['project']).read_text('utf-8-sig'))
        if not Path(project['media']['path']).is_file():
            raise ValueError('Fixture video is missing; run verify_caption_layout.py first: '+case['id'])
        copied = output/(case['id']+'.2byteproj')
        shutil.copyfile(case['project'], copied)
        case['project'] = str(copied)
    manifest = output/'cases.json'
    manifest.write_text(json.dumps({'cases': cases}, ensure_ascii=False, indent=2), 'utf-8')
    env = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
        TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime', TWOBYTEASR_CAPTION_AUDIT_MODE='layout-export',
        TWOBYTEASR_LAYOUT_MANIFEST=str(manifest), TWOBYTEASR_LAYOUT_CASES=args.cases,
        TWOBYTEASR_LAYOUT_RENDER='1' if args.render else '0',
        TWOBYTEASR_STARTUP_PROJECT=cases[0]['project'], TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root/'quick_start.py')]
    code = run_on_desktop(command, cwd=root, env=env, output=output/'process', timeout=960)
    result = json.loads((output/'result.json').read_text('utf-8')) if (output/'result.json').exists() else {}
    completion_errors = caption_completion_errors(result, cases, output, require_render=args.render)
    passed = code == 0 and result.get('passed') and result.get('gui_shutdown') and not completion_errors
    (output/'runner-completion.json').write_text(json.dumps(dict(passed=bool(passed),
        requested_cases=[case['id'] for case in cases], sample_ms={case['id']:case.get('sample_ms') for case in cases},
        errors=completion_errors, visual_review='independent review still required'), ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=bool(passed), exit=code, checks=len(result.get('checks', [])),
                         error=result.get('error'), completion_errors=completion_errors,
                         failed=[row['name'] for row in result.get('checks', []) if not row['passed']]),
                     ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
