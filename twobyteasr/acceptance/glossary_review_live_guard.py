"""Two existing-provider text requests for opt-in actual-project UI acceptance."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import threading


def install(output):
    from ..app.ui import EndpointEditor
    from ..studio.studio_ai_flow import StudioAIFlowMixin
    from ..providers.provider_service import ProviderService
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..providers import llm_config, network_policy

    output = Path(output)
    source = Path(os.environ['TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE']).resolve()
    settings_source = Path(os.environ['TWOBYTEASR_ACCEPTANCE_SETTINGS_SOURCE']).resolve()
    if source.name != 'secrets.dat' or settings_source.name != '2byteasr_settings.json' or source.parent != settings_source.parent:
        raise ValueError('Only the existing application settings and credential store are authorized')
    reader = llm_config._read_secrets
    llm_config._read_secrets = lambda: reader(read_only_path=source)
    EndpointEditor._queue_model_discovery = lambda *a: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **kw: None
    expected = json.loads((output / 'studio-replay-plan.json').read_text('utf8'))['provider']
    submit = ProviderService.submit
    post = network_policy.post
    counters = {'submitted': 0, 'actual_http_requests': 0}
    lock = threading.Lock()
    requests_dir = output / 'requests'
    requests_dir.mkdir()

    def guarded_submit(service, settings, stage, messages, **kwargs):
        snapshot = resolve_provider_snapshot(settings, stage='polish')
        identity = snapshot.public_identity()
        if (stage != 'polish' or kwargs.get('_adapter_stage') != 'polished'
                or kwargs.get('operation_kind') != 'polish'
                or any(identity.get(key) != expected.get(key) for key in ('provider', 'model', 'endpoint_identity'))):
            raise RuntimeError('Only the current configured text-polish role is authorized')
        with lock:
            if counters['submitted'] >= 2:
                raise RuntimeError('This UI acceptance permits at most two provider submissions')
            counters['submitted'] += 1
            number = counters['submitted']
        (requests_dir / f'{number:03d}-messages.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf8')
        return submit(service, settings, stage, messages, **kwargs)

    def guarded_post(url, **kwargs):
        body = kwargs.get('json', {})
        if (url != expected['endpoint_identity'].rstrip('/') + '/chat/completions'
                or body.get('model') != expected['model']
                or not isinstance(body.get('messages'), list)):
            raise RuntimeError('Unapproved HTTP destination, model, or request shape')
        # Check actual dispatch, including any transport retries. No Authorization
        # header or credential is included in the persisted measurement.
        with lock:
            if counters['actual_http_requests'] >= 2:
                raise RuntimeError('Actual HTTP request limit reached')
            counters['actual_http_requests'] += 1
            number = counters['actual_http_requests']
        (requests_dir / f'{number:03d}-request-body.json').write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf8')
        response = post(url, **kwargs)
        content = response.iter_content
        def observed(*args, **options):
            raw = bytearray()
            try:
                for chunk in content(*args, **options):
                    raw.extend(chunk)
                    if len(raw) > 32 * 1024 * 1024:
                        raise RuntimeError('Measured response exceeds protocol size limit')
                    yield chunk
            finally:
                (requests_dir / f'{number:03d}-response-wire.bin').write_bytes(raw)
                (requests_dir / f'{number:03d}-response-metadata.json').write_text(json.dumps({
                    'sequence': number, 'endpoint': url, 'model': body['model'],
                    'http_status': response.status_code, 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest()}, ensure_ascii=False, indent=2), encoding='utf8')
        response.iter_content = observed
        return response

    ProviderService.submit = guarded_submit
    network_policy.post = guarded_post
    network_policy.get = lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError('Readiness/search/model-list requests are outside this acceptance scope'))
    from ..recognition.cache import add_run_event_observer
    def event(name, payload):
        with lock:
            with (output / 'events.jsonl').open('a', encoding='utf8') as stream:
                stream.write(json.dumps({'event': name, **payload}, ensure_ascii=False) + '\n')
    add_run_event_observer(event)
    return counters
