"""Fixed response replay with assertions independent of BoundaryQuality scores."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch


def replay(fixture, *, workers=1, reverse_completion=False):
    import subtitle_core as core
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments, QUALITY_VERSION
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    snapshot = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
        'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'recorded-offline-answers'}}}})
    events, requests = [], []
    rows = core.deserialize_segments(fixture['segments'])
    original = copy.deepcopy(rows)

    def record(event, **payload):
        events.append(dict(event=event, **payload))

    def complete(messages, **options):
        body = json.loads(messages[1]['content'])
        requests.append(dict(batch=options.get('batch_index'), body=body, system=messages[0]['content']))
        if 'failed_constraints' in body:
            return json.dumps({'boundaries': body['current_boundaries']})
        ids = [row['id'] for row in body['segments']]
        batch = next(b for b in fixture['batches'] if b['source_segment_ids'] == ids)
        if body['source_text'] != batch['source_text']:
            raise ValueError('Recorded source text changed before the model call.')
        if reverse_completion:
            time.sleep((len(fixture['batches'])-batch['batch_index'])*.03)
        return json.dumps({'boundaries': batch['model_boundaries']}, separators=(',', ':'))

    context = RuntimeContext(task_language='zh', requested_language='zh', enable_domain_terms=False,
                             provider_snapshot=snapshot)
    context.review_items.extend(copy.deepcopy(fixture.get('upstream_reviews',[])))
    with language_scope('zh'), activate_runtime_context(context, legacy=core), patch.object(
            grouping, 'provider_for_stage', return_value=SimpleNamespace(complete=complete)), patch.object(
            grouping, 'record_run_event', side_effect=record), patch.object(core, 'record_run_event', side_effect=record), patch.object(
            grouping, 'GROUP_API_BATCH_MAX_CUES', 32), patch.object(grouping, '_clear_short_utterance', return_value=False):
        cues = grouping.group_subtitles(rows, fixture['acoustic_tokens'], use_ai=True,
            provider_snapshot=snapshot, max_workers=workers)
        details = []
        for batch in fixture['batches']:
            selected = [s for s in rows if s.segment_id in batch['source_segment_ids']]
            quality = quality_for_segments(selected, fixture['acoustic_tokens'], protected=batch['protected_source_offsets'])
            cuts, issues = quality.repair(batch['model_boundaries'])
            again, _ = quality.repair(cuts)
            details.append(dict(batch=batch['batch_index'], before=batch['model_texts'], after=quality.index.pieces(cuts),
                cuts=cuts, issues=issues, stable=again == cuts))
        final = [dict(text=c.text, start=c.start, end=c.end, speaker=c.speaker,
                      timing_basis=getattr(c,'timing_basis','')) for c in cues]
        digest = hashlib.sha256(json.dumps(final,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        checks = dict(immutable_sources=rows == original, per_speaker_raw_conservation=all(
            ''.join(c.text for c in cues if c.speaker == speaker) == ''.join(s.text for s in rows if s.speaker == speaker)
            for speaker in {s.speaker for s in rows}),
            all_at_most_14=all(core.display_length(c.text) <= 14 for c in cues),
            four_recorded_main_responses=len([r for r in requests if 'failed_constraints' not in r['body']]) == 4,
            no_fallback=not any(e['event'] == 'grouping_api_fallback' for e in events),
            upstream_reviews_retained=all(item in context.review_items for item in fixture.get('upstream_reviews',[])),
            idempotent=all(d['stable'] for d in details))
        text_edges = set()
        cursor = 0
        for cue in cues:
            cursor += core.display_length(cue.text)
            text_edges.add(cursor)
        content = ''.join(core.content_exact(c.text) for c in cues)
        for term in ('吃得下去吗','满状态','最热烈','太舒服了','菊花力','广东工业大学毛豆后援会战队','一只呆鸟'):
            positions = [i for i in range(len(content)) if content.startswith(term,i)]
            checks['intact_'+term] = bool(positions) and all(
                not start < edge < start+len(term) for start in positions for edge in text_edges)
        texts = [c.text for c in cues]
        checks['complete_5_plus_14'] = ('因热爱并肩' in texts and '让我们把最热烈的掌声送给他们' in texts)
        checks['right_clause_ownership'] = not any(
            '镜像反射的这里' in text or '太多了并且' in text for text in texts)
        checks['short_responses_retained'] = all(text in texts for text in ('好','是的'))
    return dict(quality_version=QUALITY_VERSION, checks=checks, passed=all(checks.values()),
                cues=final, details=details, events=events, requests=requests, reviews=context.review_items,
                timeline_sha256=digest), rows, cues


def save_replay(output, fixture, result, rows, cues, *, media=None):
    """Use normal display finalisation, project saving/reopening and SRT export."""
    import subtitle_core as core
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.projects.studio_project import create_studio_outputs, load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.subtitle_rules.timing import refresh_final_cue_reviews
    output = Path(output)
    before = [(c.text,c.speaker) for c in cues]
    context = RuntimeContext(task_language='zh', enable_domain_terms=False)
    context.review_items.extend(copy.deepcopy(fixture.get('upstream_reviews',[])))
    with language_scope('zh'), activate_runtime_context(context,legacy=core):
        cues = finalize_cues(cues, rows, fixture['acoustic_tokens'], [], fixture['audio_seconds'], fixture['fps'], core)
        result['checks']['display_preserves_text_and_speaker'] = [(c.text,c.speaker) for c in cues] == before
        for index,cue in enumerate(cues,1):
            cue.cue_id = index
        refresh_final_cue_reviews(cues,rows,legacy=core,audio_seconds=fixture['audio_seconds'])
        report_path=output/'regroup-report.json'
        report_path.write_text(json.dumps(dict(report_kind='recorded_grouping_replay',job_id=fixture['job_id'],
            events=result['events'],review_items=context.review_items),ensure_ascii=False,indent=2),encoding='utf-8')
        paths = create_studio_outputs(str(media or output/'fixture.mp4'), cues, segments=rows,
            txt_path='',srt_path='',report_path=str(report_path),target_project_path=str(output/'replay.2byteproj'),
            decoded_audio_seconds=fixture['audio_seconds'], generation_metadata={'language':{'code':'zh'}})
        if paths.get('project_error'):
            raise ValueError(paths['project_error'])
        project = load_project(output/'replay.2byteproj')
        result['checks']['saved_reopened_text'] = [c.text for c in project.cues] == [c.text for c in cues]
        parts={row.segment_id:[] for row in rows}
        for span in project.generation_metadata['segmentation_source_spans']['cues'].values():
            for part in span['parts']:
                parts[part['source_id']].append(part)
        result['checks']['per_source_raw_mapping_conserved'] = all(
            ''.join(part['raw_text'] for part in sorted(parts[row.segment_id],key=lambda p:p['char_start'])) == row.text
            for row in rows)
        result['checks']['final_upstream_reviews_retained'] = all(
            item in context.review_items for item in fixture.get('upstream_reviews',[]))
        artifacts = export_language_layers(project,output/'subtitles','replay',layers=('original',))
        result['checks']['srt_exported'] = all(a.path.is_file() for a in artifacts.artifacts)
    result['passed'] = all(result['checks'].values())
    result['reviews']=context.review_items
    return result
