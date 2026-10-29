"""Budgeted real translation through the production client, with isolated outputs.

Paid execution is opt-in. A single persistent ledger covers all runs, retries,
fallbacks and concurrent in-flight requests. Failed/unknown usage retains its
full reservation. No credentials or request headers are written.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class BudgetExceeded(RuntimeError):
    category = 'configuration_error'


class Ledger:
    """Peak USD rates, UTF-8 byte input bound + framing, bounded completion.

    Assumes only text Chat Completions, no tools/search/images. Prices verified
    2026-10-28 at https://api-docs.deepseek.com/quick_start/pricing/.
    Input tokens cannot exceed the byte representation plus the conservative
    4096-token framing allowance for these small text-only requests.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text('utf8')) if self.path.exists() else {
            'cap_usd': 10.0, 'price_source': 'https://api-docs.deepseek.com/quick_start/pricing/',
            'verified_date': '2026-10-28', 'basis': 'peak rates, cache charged at actual reported hit/miss',
            'rates_per_million': {'input_miss': .30, 'input_hit': .006, 'output': 1.20}, 'requests': []}
        if self.data['cap_usd'] != 10.0:
            raise BudgetExceeded('Unexpected ledger budget; refusing paid calls')
        self.flush()

    def flush(self):
        temporary = self.path.with_suffix('.writing')
        with temporary.open('w', encoding='utf8') as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def total(self):
        return float(self.total_decimal())

    def total_decimal(self):
        return sum((Decimal(str(r.get('usage_peak_usd', r['reserved_usd'])))
                    for r in self.data['requests']), Decimal(0))

    def reserve(self, body, tag):
        if body.get('model') != 'deepseek-flash' or any(body.get(k) for k in ['tools', 'functions', 'modalities']):
            raise BudgetExceeded('Unpriced model or chargeable extra; no request sent')
        output = body.get('max_tokens')
        if not isinstance(output, int) or not 1 <= output <= 8192:
            raise BudgetExceeded('Completion bound missing/outside tested limit; no request sent')
        encoded = json.dumps(body, ensure_ascii=False).encode('utf8')
        input_bound = len(encoded) + 4096
        reserve = (input_bound * Decimal('.30') + output * Decimal('1.20')) / Decimal(1000000)
        with self.lock:
            if self.total_decimal() + reserve > Decimal('10'):
                raise BudgetExceeded('USD 10 cumulative budget reached; no request sent')
            row = dict(number=len(self.data['requests']) + 1, tag=tag, state='inflight',
                       reserved_usd=float(reserve), input_token_bound=input_bound, max_output_tokens=output,
                       started_utc=datetime.now(timezone.utc).isoformat(),
                       body_sha256=hashlib.sha256(encoded).hexdigest(),
                       model=body['model'], thinking=body.get('thinking'),
                       temperature=body.get('temperature'), request_bytes=len(encoded))
            self.data['requests'].append(row)
            self.data['peak_occupied_usd'] = max(self.data.get('peak_occupied_usd', 0), self.total())
            self.flush()  # Write before issuing the request, including all in-flight reserves.
            return row

    def settle(self, row, response, seconds, error=None):
        with self.lock:
            row.update(state='unsettled', http_seconds=seconds, error=type(error).__name__ if error else None)
            if response is not None:
                row.update(http_status=response.status_code, header_seconds=response.elapsed.total_seconds())
                try:
                    payload = response.json()
                    usage = payload.get('usage') or {}
                    if isinstance(usage.get('prompt_tokens'), int) and isinstance(usage.get('completion_tokens'), int):
                        prompt, output = usage['prompt_tokens'], usage['completion_tokens']
                        hit = int(usage.get('prompt_cache_hit_tokens') or 0)
                        cost = ((prompt-hit)*Decimal('.30') + hit*Decimal('.006') + output*Decimal('1.20'))/Decimal(1000000)
                        if cost > Decimal(str(row['reserved_usd'])) or not 0 <= hit <= prompt:
                            raise BudgetExceeded('Provider usage exceeds reserved bound; STOP')
                        row.update(state='usage_reported', usage=usage, usage_peak_usd=float(cost),
                                   response_model=payload.get('model'),
                                   finish_reason=(payload.get('choices') or [{}])[0].get('finish_reason'))
                except (ValueError, KeyError, TypeError):
                    pass  # Keep entire failed/unknown charge reserved; never assume free.
            self.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--count', type=int, default=0, help='0 = all; otherwise evenly spaced 40-cue blocks')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--max-items', type=int, default=40)
    parser.add_argument('--execute-paid', action='store_true')
    args = parser.parse_args()
    if not args.execute_paid:
        parser.error('Paid test requires explicit --execute-paid')
    out = args.output.resolve()
    ledger_path = args.ledger.resolve()
    shared_ancestor = ledger_path.parent.name == 'tmp' and ROOT.is_relative_to(ledger_path.parent)
    if out.exists() or not out.is_relative_to(ROOT/'tmp') or not (ledger_path.is_relative_to(ROOT/'tmp') or shared_ancestor):
        parser.error('Fresh output and persistent ledger must be under checkout/tmp')
    out.mkdir(parents=True)
    # A process-wide exclusive ownership file also prevents cross-process budget races.
    lock_path = ledger_path.with_suffix('.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(handle, str(os.getpid()).encode('ascii'))
    try:
        return run(args, out, ledger_path)
    finally:
        os.close(handle)
        lock_path.unlink()


def run(args, out, ledger_path):
    from twobyteasr.storage.settings import load_runtime_settings
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.llm_config import endpoint_from_settings
    # Freeze the existing configuration and credential in memory before isolation.
    settings, _, _ = load_runtime_settings()
    snapshot = resolve_provider_snapshot(settings, stage='polish')
    endpoint = snapshot.endpoint()
    if (endpoint['provider'] != 'deepseek' or endpoint['model'] != 'deepseek-flash'
            or urlsplit(endpoint['base_url']).hostname != 'api.deepseek.com' or not endpoint.get('api_key')):
        raise BudgetExceeded('Existing configuration does not match the verified priced endpoint')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    ledger = Ledger(ledger_path)
    import requests
    original_send = requests.Session.send

    def send(session, request, **kwargs):
        url = urlsplit(request.url)
        if request.method == 'GET' and url.hostname == 'api.deepseek.com':
            return original_send(session, request, **kwargs)
        if request.method != 'POST' or url.hostname != 'api.deepseek.com' or not url.path.endswith('/chat/completions'):
            raise BudgetExceeded('Unpriced wire request blocked')
        body = json.loads(request.body)
        if body.get('stream') or kwargs.get('stream'):
            raise BudgetExceeded('This benchmark requires the production non-streaming path')
        row = ledger.reserve(body, out.name)
        started = time.perf_counter()
        response = None
        try:
            response = original_send(session, request, **kwargs)
        except BaseException as exc:
            ledger.settle(row, response, time.perf_counter()-started, exc)
            raise
        ledger.settle(row, response, time.perf_counter()-started)
        print(json.dumps({'wire':row['number'], 'seconds':row['http_seconds'],
                          'state':row['state'], 'budget_upper_usd':ledger.total()}), flush=True)
        return response

    requests.Session.send = send
    from twobyteasr.projects.studio_project import load_project, save_project
    from twobyteasr.subtitle_rules.subtitle_translation import translation_source, translate, apply_translation_result
    from twobyteasr.providers.ai_providers import provider_for_stage
    from twobyteasr.providers.llm_adapter import post_chat_completion
    start = time.perf_counter()
    data = args.project.read_bytes()
    project = load_project(args.project)
    source = translation_source(project)
    prepared = time.perf_counter()
    ids = [c.id for c in source.cues]
    if args.count:
        blocks = max(1, (args.count+39)//40)
        indexes = sorted(set(i for b in range(blocks) for i in range(
            round(b * max(0,len(ids)-40)/max(1,blocks-1)),
            min(len(ids),round(b * max(0,len(ids)-40)/max(1,blocks-1))+40))))[:args.count]
        ids = [ids[i] for i in indexes]
    provider = provider_for_stage(snapshot.execution_settings(), 'polish', sender=post_chat_completion)
    events=[]
    def event(row):
        safe = {k:v for k,v in row.items() if k not in {'messages','output','schema'}}
        safe['elapsed'] = time.perf_counter()-prepared
        events.append(safe)
    kwargs=dict(target='en', max_items=args.max_items, cache={}, event=event,
                game_context='洛克王国游戏实况，保留主播口语和角色称呼。')
    if 'workers' in inspect.signature(translate).parameters:
        kwargs['workers']=args.workers
    elif args.workers != 1:
        raise ValueError('Baseline has no parallel translation implementation')
    result=translate(source,ids,provider,**kwargs)
    translated=time.perf_counter()
    before,after=apply_translation_result(project,result)
    merged=time.perf_counter()
    save_project(project,out/'translated.2byteproj')
    finished=time.perf_counter()
    output=dict(project_sha256=hashlib.sha256(data).hexdigest(), source_language=source.language,
                target='en',cue_count=len(ids),source_chars=sum(len(source.cue(i).text) for i in ids),
                workers=args.workers,max_items=args.max_items,max_chars=2400,context_cues=3,
                game_context=kwargs['game_context'],prompt_version=result.prompt_version,
                model=endpoint['model'],provider=endpoint['provider'],endpoint=endpoint['url'],
                prepare_seconds=prepared-start,translate_seconds=translated-prepared,
                merge_seconds=merged-translated,save_seconds=finished-merged,total_seconds=finished-start,
                summary=result.summary(),failed=result.failed,problems=result.problems,
                source_unchanged=data==args.project.read_bytes(),events=events,
                translations={i:x.text for i,x in result.translations.items()},
                source_texts={i:source.cue(i).text for i in ids},budget_upper_usd=ledger.total())
    (out/'result.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:output[k] for k in ['cue_count','source_chars','total_seconds','summary','budget_upper_usd']},ensure_ascii=False),flush=True)
    return 0 if not result.failed and not result.pending and len(result.translations)==len(ids) else 1


if __name__=='__main__':
    raise SystemExit(main())
