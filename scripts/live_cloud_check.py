"""Opt-in REAL cloud recognition check with your own saved key (may cost money) — 2026-10-14.

Never part of the normal test suite. It runs only when you pass
``--i-accept-charges`` and uses the key, OSS settings and provider address
you already saved in 兔白 (read-only: the real settings file and encrypted key
store are read, never written; everything else runs in an isolated folder
under ``tmp/``). Steps, each reported separately:

1. free checks (format, connection, key, model; upload route for 录音文件识别);
2. one short real recognition through the production cloud worker, with the
   bundled ~6 s synthetic English sample (none of your material) or
   ``--audio`` (your own file, at most 60 s).

Example::

    python -X utf8 scripts/live_cloud_check.py --provider mosi_moss_pro --i-accept-charges --output tmp/live-mosi

The report (``report.json``) contains no key, AccessKey or signed link.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--provider', required=True,
                        help='mosi_moss_pro, qwen31_filetrans, qwen_cloud_filetrans, spark_asr_v2, groq, openai, ...')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audio', type=Path, help='your own audio, at most 60 s (default: bundled synthetic sample)')
    parser.add_argument('--model', default='', help='override the saved model for this check')
    parser.add_argument('--upload', choices=('own_oss', 'provider_temporary'),
                        help='录音文件识别: override the saved upload route for this check')
    parser.add_argument('--i-accept-charges', action='store_true',
                        help='required: the recognition step uploads audio and may be billed by the provider')
    args = parser.parse_args()
    if not args.i_accept_charges:
        print('Refusing to run: this check uploads audio to a paid service. Add --i-accept-charges to proceed.')
        return 2
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise SystemExit('Choose a fresh output directory under the repository tmp/')
    real_root = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / '2ByteASR'
    real_settings = real_root / '2byteasr_settings.json'
    real_secrets = real_root / 'secrets.dat'
    settings = json.loads(real_settings.read_text('utf-8')) if real_settings.is_file() else {}
    out.mkdir(parents=True)
    # Everything the app writes goes to the isolated folder; only the key
    # store is read (read-only) from your real data folder.
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr import llm_config
    original = llm_config._read_secrets
    llm_config._read_secrets = lambda **_kw: original(read_only_path=real_secrets)
    from twobyteasr import cloud_api_test as checks
    from twobyteasr.api_setup_catalog import guide_for, upload_mode_label, resolve_upload_mode
    from twobyteasr.ui import ASR_API_PRESETS
    preset = ASR_API_PRESETS.get(args.provider)
    if preset is None:
        raise SystemExit(f'Unknown provider {args.provider}')
    models = dict(settings.get('models') or {})
    if args.upload:
        models['filetrans_upload'] = args.upload
        settings = dict(settings, models=models)
    same = models.get('qwen_asr_api_provider') == args.provider
    url = str(models.get('qwen_asr_api_url') or '') if same else ''
    url = url or preset['url']
    model = args.model or (str(models.get('qwen_asr_api_model') or '') if same else '') or preset['model']
    endpoint = {'provider': args.provider, 'protocol': preset['protocol'], 'model': model, 'url': url,
                'speaker_source': 'native'}
    if args.provider == 'spark_asr_v2':
        endpoint.update(llm_config.read_spark_credentials(url))
    else:
        endpoint['api_key'] = llm_config.read_asr_api_key(args.provider, url)[0]
    if not endpoint.get('api_key'):
        raise SystemExit(f'No saved key for {args.provider} at {url}. Save it in 兔白 first (申请与设置 API).')
    guide = guide_for(args.provider, 'asr')
    report = {'provider': args.provider, 'model': model, 'host': url.split('/')[2] if '://' in url else url,
              'audio': str(args.audio) if args.audio else checks.SAMPLE_AUDIO}
    if guide is not None and guide.needs_storage:
        report['upload_route'] = upload_mode_label(resolve_upload_mode(models, args.provider))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    free = checks.free_checks(endpoint, values=models)
    report['free_checks'] = [vars(c) for c in free.checks]
    storage_credentials = ()
    if guide is not None and guide.needs_storage:
        storage_credentials = llm_config.read_oss_credentials()
        storage = checks.storage_check(endpoint, settings, models, storage_credentials)
        report['free_checks'] += [vars(c) for c in storage.checks]
    report['cost_note'] = checks.estimate_test_cost(endpoint, free.price)
    real = checks.short_recognition(endpoint, settings, audio_path=str(args.audio) if args.audio else None,
                                    storage_credentials=storage_credentials if all(storage_credentials or ('',)) else ())
    report['recognition'] = [vars(c) for c in real.checks]
    report['sample_text'] = real.models
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if real.status('recognition') == checks.PASS else 1


if __name__ == '__main__':
    raise SystemExit(main())
