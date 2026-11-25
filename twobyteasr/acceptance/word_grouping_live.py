"""Paid, real-model rerun of word-based grouping for spaced languages and Korean (2026-11-25).

Runs the production entry points (``english_segmentation.group_english_with_ai``
with each language's lexicon, ``korean_segmentation.group_korean_with_ai``) with
the configured grouping provider on spoken-style utterances
(``tests/fixtures/multilingual_grouping_live.json`` by default). Only the
grouping requests are sent. A cost ledger stops before the authorized budget.

    python -X utf8 -m twobyteasr.acceptance.word_grouping_live out.json --ledger ledger.json --budget-usd 2.5 [--languages en,es]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'multilingual_grouping_live.json'
WATCHED = {'word_grouping_batch', 'word_grouping_batch_unresolved', 'word_grouping_local_fallback',
           'word_grouping_sentence_kept', 'word_grouping_line_repair', 'api_usage'}


def segments_for(language, texts):
    import subtitle_core as core
    from ..subtitle_rules.segmentation_profiles import word_spans
    rows, clock = [], 0.0
    per_word = 0.45 if language == 'ko' else 0.33
    for index, text in enumerate(texts, 1):
        words = max(1, len(word_spans(text)))
        rows.append(core.SpeechSegment(index, round(clock, 3), round(clock + words * per_word, 3), text, .9, [],
                                       speaker='S01'))
        clock += words * per_word + 0.6
    return rows


def evaluate(language, segments, cues):
    from ..subtitle_rules.segmentation_profiles import profile_for, measure, word_spans
    profile = profile_for(language)
    if language == 'ko':
        from ..subtitle_rules.korean_segmentation import break_scores
        scorer = lambda tokens: break_scores(tokens)
    else:
        from ..subtitle_rules.english_segmentation import break_scores
        from ..subtitle_rules.european_text import lexicon
        lex = lexicon(language) if language != 'en' else None
        scorer = lambda tokens: break_scores(tokens, lexicon=lex)
    from ..subtitle_rules.english_segmentation import FORBIDDEN_BREAK
    by_source = {}
    for cue in cues:
        source = (cue.source_spans or [{}])[0].get('source_id')
        by_source.setdefault(source, []).append(cue)
    over, bad_cuts, singles, conserved = [], [], [], True
    for segment in segments:
        own = by_source.get(segment.segment_id, [])
        words = [w[2] for w in word_spans(segment.text)]
        produced = [w[2] for cue in own for w in word_spans(cue.text)]
        conserved = conserved and produced == words
        scores = scorer(words)
        cursor = 0
        for cue in own[:-1]:
            cursor += len(word_spans(cue.text))
            if 0 < cursor <= len(scores) and scores[cursor - 1] <= FORBIDDEN_BREAK:
                bad_cuts.append(dict(after=words[cursor - 1], line=cue.text))
        for cue in own:
            if measure(cue.text.strip(), language) > profile.hard_max:
                over.append(dict(text=cue.text, units=measure(cue.text.strip(), language)))
            if len(own) > 1 and len(word_spans(cue.text)) == 1:
                singles.append(cue.text)
    origins = {}
    for cue in cues:
        origin = getattr(cue, 'grouping_origin', '') or ''
        origins[origin] = origins.get(origin, 0) + 1
    long_sources = sum(measure(s.text, language) > profile.hard_max for s in segments)
    return dict(cues=len(cues), long_sources=long_sources, origins=origins, over_limit=over,
                forbidden_cuts=bad_cuts, single_word_lines=singles, conserved=conserved,
                lines=[dict(text=c.text, origin=getattr(c, 'grouping_origin', '')) for c in cues])


def run_language(language, texts, snapshot, settings):
    import subtitle_core as legacy
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    from ..recognition.cache import run_event_observer
    from ..subtitle_rules.language_rules import language_scope
    segments = segments_for(language, texts)
    events = []

    def record(name, payload):
        if name in WATCHED:
            events.append(dict(event=name, **payload))
    context = RuntimeContext(task_language=language, requested_language=language, enable_domain_terms=False,
                             asr_settings_snapshot=settings, provider_snapshots={'group': snapshot})
    with run_event_observer(record), language_scope(language), activate_runtime_context(context, legacy=legacy):
        if language == 'ko':
            from ..subtitle_rules.korean_segmentation import group_korean_with_ai
            cues = group_korean_with_ai(segments, (), snapshot)
        else:
            from ..subtitle_rules.english_segmentation import group_english_with_ai
            from ..subtitle_rules.european_text import lexicon
            cues = group_english_with_ai(segments, (), snapshot,
                                         lexicon=lexicon(language) if language != 'en' else None)
    usd = sum(float((e.get('estimated_cost') or {}).get('high') or 0) for e in events if e['event'] == 'api_usage')
    result = evaluate(language, segments, cues)
    result.update(usd_high=round(usd, 6), requests=sum(e['event'] == 'api_usage' for e in events),
                  unresolved_batches=[e for e in events if e['event'] == 'word_grouping_batch_unresolved'],
                  batches=[{k: e.get(k) for k in ('attempt', 'source_ids', 'received_ids', 'source_retained_ids')}
                           for e in events if e['event'] == 'word_grouping_batch'])
    return result


def main(argv=None):
    import copy
    import subtitle_core as legacy
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    parser = argparse.ArgumentParser()
    parser.add_argument('out')
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--budget-usd', type=float, required=True)
    parser.add_argument('--languages')
    parser.add_argument('--fixture', default=str(FIXTURE))
    args = parser.parse_args(argv)
    material = {k: v for k, v in json.loads(Path(args.fixture).read_text('utf-8')).items() if not k.startswith('_')}
    languages = args.languages.split(',') if args.languages else list(material)
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text('utf-8')) if ledger_path.is_file() else dict(runs=[])
    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    snapshot = resolve_provider_snapshot(settings, stage='group')
    results = {}
    for language in languages:
        spent = sum(float(r.get('usd_high') or 0) for r in ledger['runs'])
        if spent >= args.budget_usd:
            print(f'budget reached: ${spent:.4f}')
            break
        started = time.perf_counter()
        result = run_language(language, material[language], snapshot, settings)
        result['seconds'] = round(time.perf_counter() - started, 1)
        results[language] = result
        ledger['runs'].append(dict(at=time.strftime('%Y-%m-%dT%H:%M:%S'), language=language, model=snapshot.model,
                                   usd_high=result['usd_high'], requests=result['requests']))
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), 'utf-8')
        print(language, json.dumps({k: result[k] for k in ('cues', 'long_sources', 'origins', 'conserved', 'requests',
                                                           'usd_high', 'seconds')}, ensure_ascii=False),
              'over', len(result['over_limit']), 'forbidden', len(result['forbidden_cuts']),
              'single', len(result['single_word_lines']), 'unresolved_batches', len(result['unresolved_batches']))
    Path(args.out).write_text(json.dumps(dict(model=snapshot.model, results=results), ensure_ascii=False, indent=1),
                              'utf-8')
    print('total spent', round(sum(float(r.get('usd_high') or 0) for r in ledger['runs']), 6))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
