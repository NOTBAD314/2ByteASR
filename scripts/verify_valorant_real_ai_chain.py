"""Finite configured-provider validation on retained real project ASR, no ASR rerun.

Only writes a fresh repository tmp directory. Reads the original encrypted
credential store through the production readonly decoder without copying it.
Canonical forms are caller input; all aliases are removed for this audit.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, fields, replace
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--forms', nargs='+', required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--studio-preview', action='store_true',
        help='Use the exact current-glossary Studio backend on the retained project cues')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():
        raise ValueError('Use a fresh output under this repository tmp directory')
    original = args.original.resolve()
    project_path = next(original.glob('*.2byteproj'))
    report_path = next(original.glob('*467_字幕任务报告.json'))
    project = json.loads(project_path.read_text('utf-8-sig'))
    report = json.loads(report_path.read_text('utf-8-sig'))
    settings_path = Path(report['settings']['config_file'])
    settings_payload = json.loads(settings_path.read_text('utf-8-sig'))
    credentials_path = Path(os.environ['LOCALAPPDATA'])/'2ByteASR'/'secrets.dat'
    before_hashes = {str(path):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (project_path, report_path, settings_path, credentials_path)}

    # A concrete project_root disables settings migration; the merge itself
    # is pure. The encrypted source decoder is readonly on every invocation.
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.providers import llm_config
    read_original = llm_config._read_secrets
    llm_config._read_secrets = lambda **ignored: read_original(read_only_path=credentials_path)
    settings, warnings = settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS, settings_payload)
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    provider = resolve_provider_snapshot(settings, stage='polish')
    if provider.kind not in ('http', 'cli'):
        raise ValueError('Unsupported saved provider; no replacement is selected')
    if provider.kind == 'http' and not provider.endpoint().get('api_key'):
        raise ValueError('The saved provider credential could not be read; no request was issued')

    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    # Existing validated nonsecret settings govern the production path.
    # No key is serialized: credentials stay only in ProviderSnapshot memory.
    settings_module.save_runtime_settings(settings, out/'profile'/'config')
    import subtitle_core as core
    core.adopt_profile_runtime_settings(settings, warnings)
    from twobyteasr.subtitle_rules import polishing
    from twobyteasr.providers import provider_service
    from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
    from twobyteasr.glossary.terminology import GlossarySnapshot, TermEntry
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    old = GlossarySnapshot.from_dict(project['generation_metadata']['terminology_snapshot'])
    spelling = {value.casefold():value for value in args.forms}
    catalog = GlossarySnapshot(tuple(replace(lib,
        revision=lib.revision+'-canonical-only-user-spelling',
        terms=tuple(TermEntry(spelling.get(term.canonical.casefold(),term.canonical), (),
            term.confirmed, term.provenance, term.category, term.origin, term.priority)
            for term in {t.canonical:t for t in lib.terms}.values()),
        reference_terms=(), profile_json='') for lib in old.libraries))
    known = set(catalog.canonical_terms)
    if not set(args.forms) <= known or any(t.aliases for lib in catalog.libraries for t in lib.terms):
        raise ValueError('Audit must contain all supplied exact canonical forms and zero aliases')
    allowed_fields = {f.name for f in fields(SpeechSegment)}
    segments=[]
    for key, evidence in sorted(project['asr_evidence'].items(), key=lambda row:int(row[0].split(':')[1])):
        prior=copy.deepcopy(evidence.get('caption_arbitration',{}))
        before=prior.pop('terminology_polish',{})
        prior.pop('terminology_normalization',None)
        values = {k:copy.deepcopy(v) for k,v in evidence.items() if k in allowed_fields
            and k not in ('words','caption_arbitration','text','final_text')}
        values.update(segment_id=int(key.split(':')[1]), start=evidence['start_ms']/1000,
            end=evidence['end_ms']/1000, text=before.get('original_text',evidence['text']),
            speaker=evidence.get('speaker_id','S00'), confidence=evidence.get('confidence',.8),
            words=[WordUnit(word.get('start',word.get('start_ms',0)/1000),
                word.get('end',word.get('end_ms',0)/1000),word.get('text',''),
                word.get('probability',0.)) for word in evidence.get('words',[])], caption_arbitration=prior)
        segments.append(SpeechSegment(**values))
    source=copy.deepcopy(segments)
    def write(name, value):
        target=out/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n','utf8')
    context=RuntimeContext(game_name=old.libraries[0].name,enable_domain_terms=True,
        enabled_glossary_ids=[lib.id for lib in catalog.libraries],glossary_snapshot=catalog,
        provider_snapshot=provider,provider_snapshots={'polish':provider},
        asr_settings_snapshot=copy.deepcopy(settings),event_log_path=str(out/'events.jsonl'))
    write('scope.json',dict(project_sha256=before_hashes[str(project_path)], source_project=project_path.name,
        source_segment_count=len(segments), source_cue_count=len(project['cues']),
        canonical_count=len(catalog.canonical_terms), alias_count=0, supplied_forms=args.forms,
        provider=provider.public_identity(), network_request_limit=2, new_asr_requests=0,
        audio_passed_to_model=False, settings_warnings=warnings, run_requested=args.run))
    write('snapshot.json',catalog.to_dict())
    write('source-asr.json',[asdict(row) for row in source])
    requests=[]
    counter_lock=threading.Lock()
    original_submit=provider_service.ProviderService.submit
    def limited_submit(service, settings, stage, messages, **kwargs):
        from twobyteasr.providers.ai_providers import AIProviderError
        with counter_lock:
            if kwargs.get('operation_kind')!='polish' or len(requests)>=2:
                raise AIProviderError('Finite real validation request limit or stage scope reached',category='permission_denied')
            sequence=len(requests)+1
            requests.append({'sequence':sequence,'stage':stage,'operation':kwargs.get('operation_kind')})
            write(f'requests/{sequence:03d}-messages.json',list(messages))
        return original_submit(service,settings,stage,messages,**kwargs)
    provider_service.ProviderService.submit=limited_submit
    # The production SSE branch intentionally bypasses the legacy sender.
    # Capture at the provider's complete boundary, where both HTTP modes
    # return their exact final public answer, instead of that legacy seam.
    from twobyteasr.providers.ai_providers import CLIProvider, OpenAICompatibleProvider
    adapter_class = CLIProvider if provider.kind == 'cli' else OpenAICompatibleProvider
    original_complete=adapter_class.complete
    transport_lock=threading.Lock()
    sends=[]
    def measured_complete(adapter, messages, **kwargs):
        with transport_lock:
            sequence=len(sends)+1
            if sequence>2:raise RuntimeError('Finite transport request limit reached')
            sends.append(sequence)
        started=time.perf_counter()
        try:
            response=original_complete(adapter,messages,**kwargs)
            (out/f'requests/{sequence:03d}-response.txt').write_text(response,'utf8')
            return response
        except Exception as error:
            write(f'requests/{sequence:03d}-failure.json', {
                'type': type(error).__name__, 'category': getattr(error, 'category', 'unknown'),
                'message': str(error)})
            raise
        finally:
            write(f'requests/{sequence:03d}-transport.json',{'seconds':time.perf_counter()-started,
                'public_diagnostics':kwargs.get('request_diagnostics',{})})
    adapter_class.complete=measured_complete
    polishing.API_RETRIES=1
    result=dict(passed=False,requests=[],transport_count=0,source_unchanged=False,exception=None)
    started=time.perf_counter()
    try:
        if not args.run:
            result.update(prepared=True,passed=True)
            return
        if args.studio_preview:
            from twobyteasr.projects.studio_project import load_project
            from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
            actual_project = load_project(project_path)
            original_project_data = copy.deepcopy(actual_project.to_dict())
            preview = preview_glossary_correction(actual_project,
                [cue.id for cue in actual_project.cues], catalog, settings)
            write('studio-review-receipt.json', preview.receipt)
            write('studio-preview-hits.json', [asdict(hit) for hit in preview.hits])
            write('stage-diff.json', preview.receipt['segments'])
            result.update(passed=preview.receipt['fallback_cues'] == 0,
                verification_path='production Studio current-glossary preview backend; no UI in this phase',
                successful_cues=preview.receipt['successful_cues'],
                fallback_cues=preview.receipt['fallback_cues'],
                proposed_cues=preview.receipt['proposed_cues'],
                structure_preserved=actual_project.to_dict() == original_project_data,
                provider=preview.receipt['provider'])
            return
        with activate_runtime_context(context,legacy=core):
            final=polishing.polish_subtitles(segments,project['media']['display_name'],
                {'cache_dir':str(out/'cache'),'identity':{'hash':before_hashes[str(project_path)]}})
            write('segments-final.json',[asdict(row) for row in final])
            differences=[]
            for before,after in zip(source,final):
                receipt=after.caption_arbitration.get('terminology_polish',{})
                differences.append({'segment_id':before.segment_id,'speaker':before.speaker,
                    'start':before.start,'end':before.end,'primary_asr':before.text,
                    'moss':before.moss_text,'firered':before.firered_text,'qwen':before.qwen_asr_text,
                    'loaded_snapshot_digest':catalog.digest,
                    'retrieved':[x['canonical'] for x in receipt.get('retrieved_candidates',())],
                    'sent':[x['canonical'] for x in receipt.get('sent_candidates',())],
                    'returned_edits':receipt.get('returned_edits',()),
                    'accepted_edits':receipt.get('accepted_edits',()),
                    'rejected_edits':receipt.get('rejected_edits',()),
                    'validated_text':receipt.get('validated_text'), 'final':after.text,
                    'quality_state':receipt.get('quality_state'), 'candidate_usage':receipt.get('candidate_usage'),
                    'audio_verified':False})
            write('stage-diff.json',differences)
            write('reviews.json',context.review_items)
            write('polishing-summary.json',context.polishing_summary)
            unchanged_structure=all((a.segment_id,a.start,a.end,a.speaker)==(b.segment_id,b.start,b.end,b.speaker)
                for a,b in zip(source,final)) and len(source)==len(final)
            result.update(passed=unchanged_structure and context.polishing_summary.get('fallback_cues',1)==0,
                final_segment_count=len(final),structure_preserved=unchanged_structure,
                polish_summary=context.polishing_summary,
                sample_results=[row for row in differences if row['segment_id'] in (4,6,8,10,13,22,24)])
    except BaseException as error:
        result.update(exception=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    finally:
        result.update(requests=requests,transport_count=len(sends),seconds=time.perf_counter()-started,
            source_unchanged=all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value
                for path,value in before_hashes.items()),
            acoustic_validation='not performed; text ASR evidence only', new_asr_requests=0)
        write('result.json',result)
        print(json.dumps({'passed':result['passed'],'transport_count':len(sends),
            'source_unchanged':result['source_unchanged'],'exception':result['exception'],
            'seconds':result['seconds']},ensure_ascii=False))
        provider_service.GLOBAL_PROVIDER_SERVICE.shutdown(timeout=2)


if __name__=='__main__':
    main()
