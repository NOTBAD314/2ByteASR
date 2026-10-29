"""Source-backed clip suggestions. All times here are original-media milliseconds.

The existing HighlightCandidate remains the persisted and undoable object. This
module builds its evidence and validates editorial proposals; it never cuts media.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import bisect
from collections import Counter

from ..media.danmaku_binding import analysis_media, normalized_source
from ..timeline.studio_edit_sequence import HighlightCandidate, sequence_of
from ..projects.studio_project import StudioCue, analysis_transcript_cues
from ..i18n import tr


def source_project(project):
    """Use only captions whose source clock and source recording are known."""
    view = copy.copy(project)
    view.media = analysis_media(project)
    source = normalized_source(view.media.path)
    transcript = project.studio_state.get('analysis_transcript') or {}
    fast_source = transcript.get('source_path') or project.media.path
    fast = analysis_transcript_cues(project) if normalized_source(fast_source) == source else []
    if fast:
        view.cues = fast
        return view
    if project.render_settings.get('_cue_domain') != 'timeline':
        view.cues = list(project.cues) if normalized_source(project.media.path) == source else []
        return view
    from ..timeline.studio_edit_sequence import recording_sequence
    sequence = recording_sequence(project)[1]
    mapped = {}
    # Immutable source captions remain available after generating a shorter edit.
    receipt = project.studio_state.get('caption_timeline') or {}
    if normalized_source(project.media.path) == source:
        for raw in receipt.get('source_archive') or []:
            try:
                cue = StudioCue(**raw)
                mapped[(cue.start_ms, cue.end_ms, cue.text)] = cue
            except (TypeError, ValueError):
                continue
    for cue in project.cues:
        ownership=(receipt.get('instances') or {}).get(cue.id) or {}
        known={normalized_source(span.get('source_path','')) for span in ownership.get('source_spans',[])
               if isinstance(span,dict) and span.get('source_path')}
        if not known and ownership.get('source_path'):
            known={normalized_source(ownership['source_path'])}
        if known and known!={source}:
            continue
        if not known and normalized_source(project.media.path)!=source:
            continue  # timing overlap alone cannot attribute old captions to new footage
        for segment in sequence.segments:
            if normalized_source(segment.source_path) != source:
                continue
            if not segment.timeline_in_ms <= cue.start_ms < cue.end_ms <= segment.timeline_out_ms:
                continue
            scale = segment.source_duration_ms / max(1, segment.duration_ms)
            clone = copy.copy(cue)
            clone.start_ms = segment.source_in_ms + round((cue.start_ms - segment.timeline_in_ms) * scale)
            clone.end_ms = segment.source_in_ms + round((cue.end_ms - segment.timeline_in_ms) * scale)
            mapped[(clone.start_ms, clone.end_ms, clone.text)] = clone
    view.cues = sorted(mapped.values(), key=lambda cue: (cue.start_ms, cue.end_ms))
    return view


def worker_snapshot(project):
    """Detach only analysis inputs, not the project's large recognition cache."""
    from ..projects.studio_project import SubtitleProject
    view=source_project(project)
    return SubtitleProject(media=copy.deepcopy(view.media), cues=copy.deepcopy(view.cues),
                           speakers=copy.deepcopy(view.speakers), styles=copy.deepcopy(view.styles),
                           render_settings={'_cue_domain':'source'})


def stable_id(source, start, end):
    key = f'{normalized_source(source)}|{int(start)}|{int(end)}'
    return 'hl-' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]


def clock(ms):
    sec = max(0, int(ms)) // 1000
    return f'{sec // 3600}:{sec // 60 % 60:02}:{sec % 60:02}' if sec >= 3600 else f'{sec // 60:02}:{sec % 60:02}'


def prepare_evidence(project, locals_, document=None, *, offset_ms=0):
    from .studio_highlight_analyzer import signal_context_range
    event_times=[e.time_ms for e in document.events] if document else []
    for local in locals_:
        start, end = signal_context_range(project, local.start_ms, local.end_ms)
        rows = []
        for cue in project.cues:
            if cue.end_ms > start and cue.start_ms < end and cue.text.strip():
                rows.append(dict(id=f's:{cue.id}:{cue.start_ms}:{cue.end_ms}', kind='subtitle',
                                 start_ms=cue.start_ms, end_ms=cue.end_ms, text=cue.text,
                                 source_path=project.media.path))
        if document:
            seen = set()
            events = document.events[bisect.bisect_left(event_times,start):bisect.bisect_left(event_times,end)]
            # Keep actual comments, selected for reaction/diversity, with their
            # original timestamps. Never store an AI summary as a quotation.
            from .studio_danmaku import REACTION_PATTERNS, _is_promotional, _is_routine
            peak=local.danmaku.start_ms if local.danmaku else local.start_ms
            events.sort(key=lambda e: (abs(e.time_ms-peak)>30000,
                                      -sum(bool(p.search(e.text)) for _, p in REACTION_PATTERNS),
                                      abs(e.time_ms-peak)))
            for event in events:
                if event.text in seen or _is_promotional(event.text) or _is_routine(event.text):
                    continue
                seen.add(event.text)
                digest = hashlib.sha256(f'{document.path}|{event.time_ms}|{event.text}'.encode('utf-8')).hexdigest()[:20]
                rows.append(dict(id='d:' + digest,
                                 kind='danmaku', start_ms=event.time_ms, end_ms=event.time_ms,
                                 raw_time_ms=event.time_ms-offset_ms, text=event.text,
                                 source_path=project.media.path, file_path=document.path))
                if len(seen) >= 16:
                    break
        local.evidence_rows = rows


def reaction_copy(local):
    from .studio_danmaku import REACTION_PATTERNS
    rows = [r for r in getattr(local, 'evidence_rows', []) if r['kind'] == 'danmaku']
    focus = local.danmaku.start_ms if local.danmaku else local.start_ms
    rows = [r for r in rows if abs(r['start_ms']-focus)<=30000] or rows
    counts = Counter()
    for row in rows:
        for name, pattern in REACTION_PATTERNS:
            if pattern.search(row['text']):
                counts[name] += 1
    labels = {'lol': '笑声', 'shock': '惊讶', 'question': '疑问', 'hype': '赞叹', 'sad': '惋惜'}
    kinds = tr('与').join(tr(labels[k]) for k, _ in counts.most_common(2)) or tr('讨论')
    title = tr('{time} 附近{reaction}弹幕集中',time=clock(focus),reaction=kinds)
    quotes=[];seen=set()
    for row in rows:
        normalized=re.sub(r'(.)\1+',r'\1',row['text'].replace('？','?').replace('！','!'))
        if normalized in seen:continue
        seen.add(normalized);quotes.append(row['text'])
        if len(quotes)==2:break
    reason = (tr('观众接连发出{quotes}，可以先查看这一轮反应。',quotes='、'.join('「'+(t if len(t)<=18 else t[:17]+'…')+'」' for t in quotes))
              if quotes else tr('这一带观众反应增多，可查看前后内容再决定保留位置。'))
    return title, reason


def dialogue_range(project, local):
    """An extractive fallback: a complete, bounded speaking turn, never a
    guessed visual event. A long unbroken transcript stays a pending lead."""
    from .studio_highlight_analyzer import SEMANTIC_SUBTITLE_PATTERN
    rows = [r for r in getattr(local, 'evidence_rows', []) if r['kind'] == 'subtitle']
    groups = []
    for row in rows:
        if not groups or row['start_ms'] - groups[-1][-1]['end_ms'] >= 2000:
            groups.append([row])
        else:
            groups[-1].append(row)
    relevant = [g for g in groups if g[-1]['end_ms'] > local.start_ms and g[0]['start_ms'] < local.end_ms
                and any(SEMANTIC_SUBTITLE_PATTERN.search(r['text']) for r in g)]
    relevant.sort(key=lambda g: (-sum(bool(SEMANTIC_SUBTITLE_PATTERN.search(r['text'])) for r in g), g[0]['start_ms']))
    for group in relevant:
        start, end = group[0]['start_ms'], group[-1]['end_ms']
        if not 1500 <= end-start <= 180000 or end > project.media.duration_ms:
            continue
        # A context edge can cut a longer speaking turn. Require actual silence
        # outside both ends (or the source boundary), not a sampling boundary.
        before = [c for c in project.cues if c.start_ms < start]
        after = [c for c in project.cues if c.end_ms > end]
        if not before and start>250:
            continue
        if not after and end<project.media.duration_ms-250:
            continue
        if before and start-max(c.end_ms for c in before) < 2000:
            continue
        if after and min(c.start_ms for c in after)-end < 2000:
            continue
        core = next(r for r in group if SEMANTIC_SUBTITLE_PATTERN.search(r['text']))
        return group, core
    return None, None


def local_candidate(project, local):
    from .studio_highlight_analyzer import _danmaku_signal, signal_context_range
    start, end = signal_context_range(project, local.start_ms, local.end_ms)
    title, reason = reaction_copy(local)
    group, core = dialogue_range(project, local)
    if core:
        core_index=group.index(core)
        # Recognition splits a sentence across cues. Join adjacent fragments
        # before quoting a title, so it does not end at "感觉离真相".
        phrase=core['text'].strip()
        for following in group[core_index+1:core_index+3]:
            if (re.search(r'[。！？!?]$',phrase) or len(phrase)>=12
                    or following['text'].startswith(('尤其','然后','所以','接下来'))):break
            phrase+=following['text'].strip()
        title = tr('谈到「{quote}」',quote=phrase[:35])
        first, last = group[0]['text'][:22], group[-1]['text'][:22]
        reason = (tr('从「{first}」说到「{last}」，可保留这轮完整对话。',first=first,last=last) if len(group) > 1
                  else tr('「{quote}」表达了明确反应，可先看这句前后的现场。',quote=core['text'][:42]))
    elif local.danmaku is None:
        rows = [r for r in getattr(local, 'evidence_rows', []) if r['kind'] == 'subtitle']
        title = tr('字幕提到「{quote}」',quote=rows[0]['text'][:30]) if rows else tr('{time} 附近有对话线索',time=clock(local.start_ms))
        reason = tr('前后对话尚不能分成完整片段，请先查看现场并设置起止。')
    candidate = HighlightCandidate(
        id=stable_id(project.media.path, local.start_ms, local.end_ms), title=title,
        source_path=project.media.path, source_duration_ms=int(project.media.duration_ms or 0),
        source_in_ms=group[0]['start_ms'] if group else start,
        source_out_ms=group[-1]['end_ms'] if group else end,
        range_status='suggested' if group else 'unconfirmed', origin='local',
        score=local.score, reason=reason, clip_reason=reason,
        signal_in_ms=local.start_ms, signal_out_ms=local.end_ms,
        context_in_ms=start, context_out_ms=end, danmaku_signal=_danmaku_signal(local, local.danmaku),
        evidence=copy.deepcopy(getattr(local, 'evidence_rows', [])),
        boundary_refs=[group[0]['id'], group[-1]['id']] if group else [],
        key_moment_ms=core['start_ms'] if core else None,
        key_moment_ref=core['id'] if core else '',
        risk_notes=([tr('字幕描述的是话语，画面动作及结果仍需观看确认。')] if core else
                    [tr('请确认触发观众反应的内容，并设置实际剪辑起止。'),
                     tr('弹幕到达可能晚于事件；查看范围不是已确定的成片范围。')]))
    candidate.validate()
    if local.danmaku is not None:
        candidate.danmaku_signal['peak_in_ms']=local.danmaku.start_ms
        candidate.danmaku_signal['peak_out_ms']=local.danmaku.end_ms
    return candidate


def evidence_payload(project, local):
    from .studio_highlight_analyzer import signal_context_range
    start, end = signal_context_range(project, local.start_ms, local.end_ms)
    rows = getattr(local, 'evidence_rows', [])
    # A complete window may be long. Never silently label a sampled transcript
    # complete; the model must cite real rows for both editorial boundaries.
    selected = rows if len(rows) <= 80 else rows[:35]+rows[-35:]
    # Absolute local paths and repeated provenance stay in the project, not in
    # every LLM evidence row. IDs, original text and source times suffice.
    selected=[{key:row[key] for key in ('id','kind','start_ms','end_ms','text')}
              for row in selected]
    return dict(candidate_id=stable_id(project.media.path, local.start_ms, local.end_ms),
                context_range={'start_ms': start, 'end_ms': end},
                reaction_range={'start_ms': local.start_ms, 'end_ms': local.end_ms},
                transcript_complete=len(selected) == len(rows), evidence=selected)


def parse_proposals(content, project, locals_):
    """Reject unsupported types, invented references and guessed milliseconds.
    Only subtitle references can set automatic cuts; human confirmation is UI-only.
    """
    text = str(content).strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    data = json.loads(text)
    proposals = data.get('candidates') if isinstance(data, dict) else None
    if not isinstance(proposals, list):
        raise ValueError('剪辑建议没有有效候选列表')
    lookup = {stable_id(project.media.path, item.start_ms, item.end_ms): item for item in locals_}
    result, seen = [], set()
    for row in proposals:
        if not isinstance(row, dict) or not isinstance(row.get('candidate_id'), str):
            continue
        key = row['candidate_id']
        if key in seen or key not in lookup:
            continue
        seen.add(key)
        local = lookup[key]
        candidate = local_candidate(project, local)
        supplied = evidence_payload(project, local)['evidence']
        refs = {r['id']: r for r in supplied}
        citations = row.get('evidence_refs')
        valid_refs = (isinstance(citations, list) and bool(citations)
                      and all(isinstance(r, str) and r in refs for r in citations))
        # XML-only proposals cannot invent events. Keep deterministic, quoted
        # audience reactions, irrespective of the model's confidence.
        has_subtitles = valid_refs and any(refs[r]['kind'] == 'subtitle' for r in citations)
        title, reason = row.get('title'), row.get('clip_reason')
        if (not has_subtitles or not isinstance(title, str) or not 1 <= len(title.strip()) <= 90
                or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240):
            candidate.range_status = 'unconfirmed'
            candidate.key_moment_ms = None
            candidate.validate()
            result.append(candidate)
            continue
        candidate.origin = 'ai'
        candidate.title, candidate.clip_reason, candidate.reason = title.strip(), reason.strip(), reason.strip()
        candidate.event_summary = title.strip()
        candidate.range_status = 'unconfirmed'
        candidate.key_moment_ms, candidate.key_moment_ref = None, ''
        bounds = row.get('recommended_range')
        if isinstance(bounds, dict):
            a, b = bounds.get('start_ref'), bounds.get('end_ref')
            first, last = refs.get(a) if isinstance(a, str) else None, refs.get(b) if isinstance(b, str) else None
            if first and last and first['kind'] == last['kind'] == 'subtitle':
                start, end = first['start_ms'], last['end_ms']
                # Explicit milliseconds, if supplied, must match cited cues.
                exact = all(name not in bounds or type(bounds[name]) is int and bounds[name] == value
                            for name, value in [('start_ms', start), ('end_ms', end)])
                contiguous = all(r['id'] in refs for r in getattr(local,'evidence_rows',[])
                                 if r['kind']=='subtitle' and r['end_ms']>start and r['start_ms']<end)
                if exact and contiguous and 0 <= start < end <= project.media.duration_ms and end-start >= 40:
                    candidate.source_in_ms, candidate.source_out_ms = start, end
                    candidate.range_status = 'suggested'
                    candidate.boundary_refs = [a, b]
                    k = row.get('key_moment_ref')
                    key_row = refs.get(k) if isinstance(k, str) else None
                    if key_row and key_row['kind'] == 'subtitle' and start <= key_row['start_ms'] < end:
                        candidate.key_moment_ref, candidate.key_moment_ms = k, key_row['start_ms']
        candidate.risk_notes = [tr('AI 根据字幕提出建议，尚未经过人工观看确认。')]
        if not candidate.clip_range:
            candidate.risk_notes.append(tr('边界引用缺失或无效，请在现场设置起止。'))
        candidate.validate()
        result.append(candidate)
    if proposals and not result:
        raise ValueError('剪辑建议没有可追溯的来源引用')
    return result


def ranked_unique(candidates):
    """Never union context ranges into a cut. Keep different spoken events."""
    for candidate in candidates:candidate.validate()
    ordered = sorted(candidates, key=lambda c: (bool(c.clip_range), 'subtitle' in c.evidence_kinds,
                                               bool(c.boundary_refs), c.score, -c.source_in_ms), reverse=True)
    kept = []
    for item in ordered:
        duplicate = False
        for old in kept:
            if normalized_source(item.source_path) != normalized_source(old.source_path):
                continue
            a, b = item.clip_range or (item.signal_in_ms, item.signal_out_ms)
            c, d = old.clip_range or (old.signal_in_ms, old.signal_out_ms)
            overlap = max(0, min(b, d)-max(a, c)) / max(1, min(b-a, d-c))
            same_key = item.key_moment_ref and item.key_moment_ref == old.key_moment_ref
            shared = set(item.boundary_refs) & set(old.boundary_refs)
            if same_key or (overlap >= .65 and (shared or not item.clip_range or not old.clip_range
                                                or not item.evidence and not old.evidence)):
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept
