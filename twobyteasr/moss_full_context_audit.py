"""Local, explicitly invoked inference audit; all writable data stays in tmp."""
from pathlib import Path
import contextlib
import copy
import hashlib
import json
import os
import sys
import traceback


def main(spec_path):
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text('utf8'))
    output = Path(spec['output']).resolve()
    boundary = (Path(os.environ.get('TWOBYTEASR_INVOKER_CWD') or Path.cwd()) / 'tmp').resolve()
    if not output.is_relative_to(boundary) or not spec_path.is_relative_to(boundary):
        raise ValueError('Audit output/spec must live in invoking workspace tmp.')
    output.mkdir(parents=True, exist_ok=True)
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    from . import cache, reporting
    from .settings import DEFAULT_SETTINGS
    from .runtime import RuntimeContext, activate_runtime_context
    from .service import RunOptions, run_media_queue
    from .build_identity import source_snapshot_sha256
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings['switches'].update(enable_ai_polish=False, use_ai_grouping=False,
                               unified_glm_processing=False)
    settings['models'].update(primary_asr_backend='moss', speaker_source='moss',
                             qwen_asr_backend='local', firered_asr_backend='local')
    legacy.adopt_profile_runtime_settings(settings)
    legacy.CACHE_ROOT = cache.CACHE_ROOT = str(output/'cache')
    reporting.REPORT_ROOT = output/'reports'
    media = str(Path(spec['audio']).resolve())
    result = {'source': media, 'frozen': bool(getattr(sys, 'frozen', False)),
              'executable': sys.executable, 'paths': pipeline._script_paths(legacy),
              'test_kind': 'local_runtime_integrity_not_acoustic_accuracy'}
    with (output/'runtime.log').open('w', encoding='utf8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            if spec.get('pipeline'):
                # Caller supplies an owned media COPY: normal exports cannot touch the original.
                if not Path(media).is_relative_to(output):
                    raise ValueError('End-to-end media copy must live in audit output.')
                options = RunOptions(settings_snapshot_json=json.dumps(settings), speaker_source='moss',
                    output_speaker_tracks=True, expected_speakers=0,
                    studio_project_path=str(output/'result.2byteproj'))
                queue = run_media_queue([media], options=options)
                result['queue'] = [vars(item) for item in queue.results]
                result['passed'] = not queue.failures and bool(queue.successes)
            else:
                context = RuntimeContext(event_log_path=str(output/'events.jsonl'))
                with activate_runtime_context(context, legacy=legacy):
                    cache_context = legacy.media_cache_context(media)
                    audio = legacy.load_shared_audio(media, cache_context)
                    canonical = pipeline.transcribe_moss_global(media, audio, legacy, cache_context)
                    (output/'parsed.json').write_text(json.dumps(canonical, ensure_ascii=False, indent=2), 'utf8')
                    result.update(execution=canonical['execution'], passed=True)
            if result.get('frozen'):
                from .runtime_paths import detect_install_root
                result['build_identity'] = json.loads((detect_install_root()/'2byteasr_build.json').read_text('utf8'))
        except BaseException as exc:
            result.update(passed=False, error=f'{type(exc).__name__}: {exc}')
            traceback.print_exc()
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    return 0 if result['passed'] else 1
