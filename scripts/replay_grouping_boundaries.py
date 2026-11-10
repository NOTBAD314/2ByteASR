"""Replay fixed model answers without media decoding, accounts or network."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch


def fixture_from_report(report_path,window_receipts=None):
    """Read validated upstream data; never mutate a report, cache or project."""
    report=json.loads(report_path.read_text(encoding='utf-8-sig'))
    writes=[e for e in report['events'] if e['event']=='cache_write' and e.get('stage')=='polished']
    if not writes:
        raise ValueError('The report has no saved corrected-source cache.')
    cache=json.loads(Path(writes[-1]['path']).read_text(encoding='utf-8-sig'))
    if cache.get('identity',{}).get('fingerprint')!=report['media']['identity']['fingerprint']:
        raise ValueError('Saved source cache belongs to another media identity.')
    rows=cache['data']
    finals={e['cue_id']:e['details']['final_text'] for e in report['events'] if e['event']=='terminology_polish_final'}
    previews={r['cue_id']:r for e in report['events'] if e['event']=='cloud_batch_preview'
              and e.get('stage')=='polished' for r in e['rows']}
    if set(finals)!={r['segment_id'] for r in rows}:
        raise ValueError('Corrected source IDs are incomplete or have changed.')
    for row in rows:
        old=previews[row['segment_id']]
        if (row['text']!=finals[row['segment_id']] or abs(row['start']-old['start'])>.002
                or abs(row['end']-old['end'])>.002):
            raise ValueError('Corrected source text/timing differs from the saved report.')
    batches=[e for e in report['events'] if e['event']=='grouping_trace']
    by_id={r['segment_id']:r for r in rows}
    covered=[]
    for trace in batches:
        covered.extend(trace['source_segment_ids'])
        if ''.join(by_id[i]['text'] for i in trace['source_segment_ids'])!=trace['source_text']:
            raise ValueError('Saved model answers have a stale source identity.')
    if len(covered)!=len(rows) or set(covered)!=set(by_id):
        raise ValueError('Saved model responses do not cover every corrected source exactly once.')
    from twobyteasr.recognition.asr_schema import normalize_firered_worker_result,flatten_segment_tokens
    raw={r['segment_id']:r for e in report['events'] if e['event']=='asr_evidence_delta'
         and e.get('backend')=='firered' for r in e.get('rows',[])}
    tokens=[]
    rejected_words=set()
    if raw:
        if window_receipts:
            receipts=json.loads(window_receipts.read_text(encoding='utf-8'))['results']
            for receipt in receipts:
                old=raw[receipt['segment_id']]
                if old['text']!=receipt['text'] or old['timestamp']!=receipt['timestamp']:
                    raise ValueError('The new window receipt does not exactly match the reported window.')
                if receipt['timestamp_reliability']!='measured':
                    rejected_words.update((t['text'],round((old['offset']+t['start'])*1000),
                        round((old['offset']+t['end'])*1000)) for t in old['timestamp'])
                old.update({key:receipt[key] for key in ('evidence_version','transcription_status',
                    'alignment_status','timestamp_source','timestamp_reliability')})
        raw=[r for _,r in sorted(raw.items())]
        jobs=[{k:r[k] for k in ('segment_id','offset','duration')} for r in raw]
        tokens=flatten_segment_tokens(normalize_firered_worker_result({'results':raw},jobs))
    quarantined=0
    for row in rows:
        arbitration=row.get('caption_arbitration',{})
        words=arbitration.get('acoustic_words',[])
        kept=[w for w in words if (w.get('text'),w.get('start_ms'),w.get('end_ms')) not in rejected_words]
        quarantined+=len(words)-len(kept)
        if len(kept)!=len(words):
            arbitration['acoustic_words']=kept
            arbitration['grouping_replay_quarantine']='exactly_matched_failed_window_receipt'
    phase=next(e for e in report['events'] if e['event']=='display_boundary_phase' and e['phase']=='final_half_open_display')
    return dict(segments=rows,batches=batches,acoustic_tokens=tokens,
        audio_seconds=report['media']['audio_seconds'],fps=phase['fps'],media_path=report['media']['path'],
        source_job_id=report['job_id'],quarantined_evidence_references=quarantined,
        report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser()
    root=Path(__file__).resolve().parents[1]
    parser.add_argument('--source-root',type=Path,default=root)
    parser.add_argument('--fixture',type=Path,default=root/'tests/fixtures/grouping_contract/arknights_boundaries.json')
    parser.add_argument('--report',type=Path,help='Regroup saved corrected sources/model answers; no ASR, polish or network.')
    parser.add_argument('--window-receipts',type=Path,help='Verified worker result matching original windows exactly.')
    parser.add_argument('--exclude-known-untrusted',action='store_true',help='Use separately verified filtered evidence from the fixture.')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--reverse-completion',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    profile=root/'tmp/grouping-replay-profiles'/hashlib.sha256(str(output).encode()).hexdigest()[:12]
    os.environ['TWOBYTEASR_TEST_ROOT']=str(profile)
    sys.path.insert(0,str(args.source_root.resolve()))
    from twobyteasr.test_isolation import install,install_pytest_network_guard
    install();install_pytest_network_guard()
    import subtitle_core as core
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_contract import attach_grouping_spans
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.projects.studio_project import project_from_runtime_cues,create_studio_outputs,save_project,load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    fixture=fixture_from_report(args.report,args.window_receipts) if args.report else json.loads(args.fixture.read_text(encoding='utf-8'))
    if args.exclude_known_untrusted:
        fixture['acoustic_tokens']=fixture['filtered_acoustic_tokens']
    traces={tuple(b['source_segment_ids']):b for b in fixture['batches']}
    rows=core.deserialize_segments(fixture['segments'])
    events=[];requests=[]
    def record(event,**data): events.append(dict(event=event,**data))
    def complete(messages,**kwargs):
        body=json.loads(messages[1]['content'])
        requests.append(dict(batch=kwargs.get('batch_index'),body=body))
        if 'failed_constraints' in body:
            return json.dumps(dict(boundaries=body['current_boundaries']))
        trace=traces[tuple(s['id'] for s in body['segments'])]
        if trace['source_text']!=body['source_text']:
            raise ValueError('Model replay source changed.')
        if args.reverse_completion:
            time.sleep((20-trace['batch_index'])*.003)
        return json.dumps(dict(boundaries=trace['model_boundaries']))
    snapshot=resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline-fixed-answers'}}}})
    context=RuntimeContext(task_language='zh',requested_language='zh',provider_snapshot=snapshot)
    started=time.perf_counter()
    with language_scope('zh'),activate_runtime_context(context,legacy=core),patch.object(
            grouping,'provider_for_stage',return_value=SimpleNamespace(complete=complete)),patch.object(
            grouping,'record_run_event',side_effect=record),patch.object(core,'record_run_event',side_effect=record),patch.object(
            grouping,'PARALLEL_CLOUD_BATCHES',True),patch.object(grouping,'CLOUD_BATCH_WORKERS',args.workers):
        cues=grouping.group_subtitles(rows,fixture['acoustic_tokens'],use_ai=True,
                                     provider_snapshot=snapshot,max_workers=args.workers)
        attach_grouping_spans(rows,cues)
        grouped=core.serialize_cues(cues)
        final=finalize_cues(copy.deepcopy(cues),rows,fixture['acoustic_tokens'],[],fixture['audio_seconds'],fixture['fps'],core)
        media_path=fixture.get('media_path',str(output/'fixture.mp4'))
        if args.report:
            audit_report=output/'regroup-report.json'
            audit_report.write_text(json.dumps(dict(report_kind='offline_regroup',source_job_id=fixture['source_job_id'],
                media=dict(path=media_path,audio_seconds=fixture['audio_seconds']),
                review_items=context.review_items,events=events,
                result=dict(cue_count=len(final),real_network_requests=0,reused_stages=['ASR','polish','model_answers'])),
                ensure_ascii=False,indent=2),encoding='utf-8')
            paths=create_studio_outputs(media_path,final,txt_path='',srt_path='',report_path=str(audit_report),
                segments=rows,generation_metadata={'language':{'code':'zh'},'created_by':'offline grouping replay'},
                target_project_path=str(output/'replay.2byteproj'),decoded_audio_seconds=fixture['audio_seconds'])
            if paths.get('project_error'):
                raise ValueError(paths['project_error'])
            path=output/'replay.2byteproj'
        else:
            project=project_from_runtime_cues(media_path,final,
                generation_metadata={'language':{'code':'zh'}},initialize_layout=False)
            project.media.duration_ms=round(fixture['audio_seconds']*1000)
            path=save_project(project,output/'replay.2byteproj')
        reopened=load_project(path)
        artifacts=export_language_layers(reopened,output/'export','replay',layers=('original',))
        original=next(a for a in artifacts.artifacts if a.layer=='original')
        exported=parse_srt(original.path.read_text(encoding='utf-8'))[0]
        short=[item for item in context.review_items if item['category']=='显示过短']
        short_source=next((c for c in final if c.text.strip()=='可以刷' and c.speaker=='API_S01'
                           and 115.6<c.start<115.7),None)
        checks={
            'A_object_preserved':any(c.text.strip()=='我觉得要相信他' for c in final),
            'A_no_moved_object':not any(c.text.startswith('他如果我们') for c in final),
            'B_complete_selection':any(c.text.strip()=='选这个东西' for c in final),
            'B_complete_trust':any(c.text.strip()=='你得对你的队友足够信任' for c in final),
            'C_measure_preserved':any(c.text.strip()=='不行 我们我们来一把' for c in final),
            'D_predicate_quantity':any('他要兜27个' in core.content_exact(c.text) for c in final),
            'E_no_manufactured_flash':not any(c.text.strip()=='刷' and 115<c.start<117 for c in final),
            'E_complete_short_source':any(c.text.strip()=='可以刷' and c.speaker=='API_S01'
                and 115.6<c.start<115.7 and .35<=c.end-c.start<=.45 for c in final),
            'E_no_artificial_speaker_overlap':bool(short_source) and not any(c.speaker!=short_source.speaker
                and max(c.start,short_source.start)<min(c.end,short_source.end)-1e-6 for c in final),
            'per_speaker_text_conserved':all(''.join(core.content_exact(c.text) for c in final if c.speaker==s)
                ==''.join(core.content_exact(r.text) for r in rows if r.speaker==s) for s in {r.speaker for r in rows}),
            'source_order_preserved':all([c.text for c in final if c.speaker==s]==[c['text'] for c in grouped if c['speaker']==s]
                for s in {r.speaker for r in rows}),
            'saved_reopened_identical':[(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in reopened.cues]
                ==[(c.text,round(c.start*1000),round(c.end*1000),c.speaker) for c in final],
            'exported_identical':[(c.text,c.start_ms,c.end_ms) for c in exported]
                ==[(c.text,c.start_ms,c.end_ms) for c in reopened.cues],
            'final_review_exact':all(any(item.get('cue_id')==c.cue_id and item.get('actual_duration_ms')==round((c.end-c.start)*1000)
                and item['timestamp']==c.start for c in final) for item in short),
        }
        if args.report:
            checks['original_evidence_retained']=len(reopened.asr_evidence)==len(rows)
            checks['cue_evidence_references_retained']=all(c.evidence_refs for c in reopened.cues)
        retry=[e for e in events if e['event']=='grouping_quality_retry']
        moves=[e for e in events if e['event']=='grouping_boundary_move']
        result=dict(passed=all(checks.values()),checks=checks,source=str(args.source_root.resolve()),
            elapsed_seconds=time.perf_counter()-started,real_network_requests=0,project=str(path),
            stats=dict(source_segments=len(rows),acoustic_tokens=len(fixture['acoustic_tokens']),model_batches=len(traces),model_cues=sum(len(b['model_boundaries']) for b in traces.values()),
                grouped=len(grouped),final_cues=len(final),local_changes=sum(e['accepted'] for e in moves),
                quarantined_evidence_references=fixture.get('quarantined_evidence_references',0),
                retry_outcomes=dict(Counter(e.get('outcome','legacy_accepted' if e['accepted'] else 'rejected') for e in retry)),
                request_statuses=dict(Counter(e.get('result_status') for e in events if e['event']=='asr_provider_request')),
                short_final=len(short),estimated_edges=sum('estimate' in c.timing_basis for c in final),
                quality_review=sum(e['event']=='grouping_quality_review' for e in events)),
            final_cues=core.serialize_cues(final),grouped=grouped,events=events,requests=requests,
            review_items=context.review_items,
            timeline_sha256=hashlib.sha256(json.dumps(core.serialize_cues(final),ensure_ascii=False,sort_keys=True).encode()).hexdigest())
    (output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['passed','checks','stats','elapsed_seconds','timeline_sha256']},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
