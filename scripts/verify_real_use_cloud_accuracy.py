"""New full-source Filetrans request through the production owned API worker.

Original settings and encrypted credentials are read-only. Only this repo's tmp
contains runtime registration, media decoding, cache and public evidence.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        raise ValueError('Use a fresh repository tmp output')
    original = root/'tmp/completion-current-20261004/original'
    project_path = next(original.glob('*.2byteproj'))
    project = json.loads(project_path.read_text('utf-8-sig'))
    report_path = next(original.glob('*报告.json'))
    report = json.loads(report_path.read_text('utf-8-sig'))
    source = Path(project['media']['path'])
    config = Path(report['settings']['config_file'])
    secrets = Path(os.environ['LOCALAPPDATA'])/'2ByteASR/secrets.dat'
    protected = [source, project_path, report_path, config, secrets]
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {str(p): sha(p) for p in protected}
    out.mkdir(parents=True)
    def write(name, value):
        path = out/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', 'utf8')
    from twobyteasr.providers import llm_config
    from twobyteasr.storage import settings as settings_module
    decoder = llm_config._read_secrets
    llm_config._read_secrets = lambda **_: decoder(read_only_path=secrets)
    settings, warnings = settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS,
        json.loads(config.read_text('utf-8-sig')))
    settings['models']['primary_asr_backend'] = 'api'
    settings['models']['speaker_source'] = 'filetrans'
    endpoint = llm_config.qwen_asr_endpoint_from_settings(settings)
    from twobyteasr.providers.qwen31_asr import FILETRANS
    if endpoint['model'] != FILETRANS or not endpoint.get('api_key'):
        raise ValueError('Saved workspace is missing the migrated Filetrans credential')
    from twobyteasr.glossary.terminology import GlossarySnapshot, TermEntry
    original_snapshot = GlossarySnapshot.from_dict(project['generation_metadata']['terminology_snapshot'])
    forms = {'berlin': 'BerLIN', 's0pp': 'S0pp', 'zhe': 'Zhe'}
    baseline_text = '\n'.join(c['text'] for c in project['cues'])
    terms = [t for lib in original_snapshot.libraries for t in lib.terms
        if t.canonical.casefold() in forms or t.canonical.casefold() in baseline_text.casefold()]
    canonical = tuple(TermEntry(forms.get(t.canonical.casefold(), t.canonical), (),
        t.confirmed, t.provenance, t.category, t.origin, t.priority) for t in terms)
    snapshot = GlossarySnapshot(tuple(replace(lib, terms=canonical, reference_terms=(), profile_json='')
        for lib in original_snapshot.libraries[:1]))
    write('scope.json', {'kind': 'new_full_source_asr_canonical_only',
        'original_project_id': project['project_id'], 'original_cues': len(project['cues']),
        'media_sha256': before[str(source)], 'provider': endpoint['provider'], 'model': endpoint['model'],
        'primary_backend': 'api', 'speaker_source': 'filetrans', 'canonical_terms': list(snapshot.canonical_terms),
        'alias_count': 0, 'warnings': warnings, 'new_external_asr_requested': args.run})
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'profile')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from twobyteasr.test_isolation import install
    install()
    # Owned source runtime registered inside the test boundary. Dependencies
    # are read from the already installed main venv, never downloaded.
    venv_root = out/'profile/local/2ByteASR/runtimes/main/.venv-main'
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(venv_root)], check=True)
    site = venv_root/'Lib/site-packages'; site.mkdir(parents=True, exist_ok=True)
    (site/'existing-main-dependencies.pth').write_text(str(root/'.venv-main/Lib/site-packages')+'\n', 'utf8')
    os.environ['TWOBYTEASR_MAIN_PYTHON'] = str(venv_root/'Scripts/python.exe')
    settings_module.save_runtime_settings(settings, out/'profile/config')
    import subtitle_core as legacy
    legacy.adopt_profile_runtime_settings(settings, warnings)
    probe = subprocess.run([str(root/'tools/ffmpeg/bin/ffprobe.exe'), '-v', 'error',
        '-select_streams', 'a:0', '-show_packets', '-of', 'json', str(source)],
        capture_output=True, encoding='utf8', check=True)
    packets = json.loads(probe.stdout)['packets']
    import numpy as np
    decode = subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'), '-nostdin', '-v', 'error',
        '-i', str(source), '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 'f32le', 'pipe:1'],
        capture_output=True, check=True)
    audio = np.frombuffer(decode.stdout, dtype='<f4').copy()
    np.save(out/'full-decoded-audio.npy', audio)
    seconds = len(audio)/16000
    write('audio-range.json', {'samples': len(audio), 'sample_rate': 16000, 'decoded_seconds': seconds,
        'container_ms': project['media']['duration_ms'],
        'first_packet_pts': packets[0].get('pts_time'), 'first_packet_side_data': packets[0].get('side_data_list'),
        'last_packet_end': float(packets[-1]['pts_time'])+float(packets[-1]['duration_time']),
        'audio_sha256': hashlib.sha256(decode.stdout).hexdigest(),
        'tail_rms': float(np.sqrt(np.mean(audio[int(55.64*16000):]**2))),
        'time_stretch': False})
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.service import CancellationToken
    token = CancellationToken()
    context = RuntimeContext(speaker_source='filetrans', enable_domain_terms=True,
        glossary_snapshot=snapshot, enabled_glossary_ids=[x.id for x in snapshot.libraries],
        cancellation_token=token, asr_settings_snapshot=copy.deepcopy(settings),
        asr_endpoint_snapshot=dict(endpoint), event_log_path=str(out/'events.jsonl'))
    result = {'passed': False, 'new_asr_completed': False}
    started = time.perf_counter()
    timer = threading.Timer(300, token.cancel)
    try:
        if not args.run:
            result['prepared'] = True; return
        timer.start()
        from twobyteasr.providers.asr_api_process import transcribe
        with activate_runtime_context(context, legacy=legacy):
            rows = transcribe(source, [dict(audio=(audio,16000), start=0., end=seconds)], publish_primary=True)
        write('new-native-asr.json', rows)
        result.update(passed=bool(rows), new_asr_completed=bool(rows), rows=len(rows),
            first_start=min(x['start'] for x in rows), last_end=max(x['end'] for x in rows),
            transcript=''.join(x['text'] for x in rows),
            native_speakers=sorted({x.get('speaker','') for x in rows}),
            overlapping_pairs=[{'left':i, 'right':j, 'start':max(a['start'], b['start']),
                'end':min(a['end'], b['end'])} for i,a in enumerate(rows) for j,b in enumerate(rows)
                if i<j and a.get('speaker')!=b.get('speaker') and min(a['end'],b['end'])>max(a['start'],b['start'])])
    except Exception as exc:
        from twobyteasr.providers.provider_diagnostics import redact_diagnostics
        result.update(error=redact_diagnostics(str(exc)), exception_type=type(exc).__name__)
    finally:
        timer.cancel()
        result.update(seconds=time.perf_counter()-started,
            protected_sources_unchanged=all(sha(Path(p))==h for p,h in before.items()),
            source_hashes=[{'path':p, 'sha256':h} for p,h in before.items() if not p.endswith('secrets.dat')])
        write('result.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
