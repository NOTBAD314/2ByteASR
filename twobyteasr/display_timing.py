"""Distinguish source acoustic overlap from editorial display tails.

Unknown evidence is retained for review. No text, speaker, or cue is removed.
"""
from __future__ import annotations

import math
import re
import statistics


def project_frame_ms(project):
    rates=[float(asset.video_metadata.get("fps") or 0) for asset in project.media_pool]
    fps=next((rate for rate in rates if 1<=rate<=240),float(project.render_settings.get("fps") or 30))
    return 1000/max(1,min(240,fps))


def _evidence_points(project,cue,keys):
    points=[]
    for ref in cue.evidence_refs:
        row=project.asr_evidence.get(ref,{})
        for key in keys:
            for item in row.get(key,[]) if isinstance(row.get(key),list) else []:
                if not isinstance(item,dict):continue
                try:
                    a=float(item['start_ms']) if 'start_ms' in item else float(item['start'])*1000
                    b=float(item['end_ms']) if 'end_ms' in item else float(item['end'])*1000
                except (KeyError,TypeError,ValueError):continue
                if math.isfinite(a+b) and b>a:points.append((round(a),round(b)))
    return sorted(set(points))


def independent_overlap_verified(project,left,right):
    """MOSS overlap or mono VAD alone is not independent simultaneous speech."""
    spans=[]
    for cue,other in ((left,right),(right,left)):
        independent=[]
        for ref in cue.evidence_refs:
            row=project.asr_evidence.get(ref,{})
            if other.id in (row.get('verified_overlap_with') or []):
                return True
            if row.get('speaker_independent') is True:
                independent.extend(_evidence_points(project,cue,('independent_speech_intervals',)))
        spans.append(independent)
    return classify_overlap(*spans)=='acoustic' if all(spans) else False


def project_display_tail_plan(project):
    rows=[dict(id=c.id,start_ms=c.start_ms,end_ms=c.end_ms,speaker=c.speaker_id) for c in project.cues]
    acoustic={c.id:project_acoustics(project,c) for c in project.cues}
    changes,audit=protect_intervals(rows,acoustic)
    by_id={c.id:c for c in project.cues}
    frame=project_frame_ms(project)
    for pair in audit:
        left,right=by_id[pair['left']],by_id[pair['right']]
        pair.update(raw_labels=[left.speaker_id,right.speaker_id],
                    display_labels=[next((s.name or s.id for s in project.speakers if s.id==c.speaker_id),c.speaker_id) for c in (left,right)],
                    cue_before=[[left.start_ms,left.end_ms],[right.start_ms,right.end_ms]],frame_ms=frame,
                    independently_verified=independent_overlap_verified(project,left,right))
        if pair['classification']!='acoustic' or pair['independently_verified']:
            continue
        words_left=_evidence_points(project,left,('word_timestamps','words','tokens','alignment'))
        words_right=_evidence_points(project,right,('word_timestamps','words','tokens','alignment'))
        token_durations=[b-a for a,b in words_left+words_right]
        if not token_durations:
            token_durations=[(c.end_ms-c.start_ms)/max(1,len(re.sub(r'\W','',c.text))) for c in (left,right)]
        # Boundary uncertainty scales with frame cadence and local token/turn
        # duration, not a universal 200ms cutoff or a voiceprint threshold.
        uncertainty=max(2*frame,min(statistics.median(token_durations),
                        .15*min(left.end_ms-left.start_ms,right.end_ms-right.start_ms)))
        pair['handoff_uncertainty_ms']=round(uncertainty,3)
        if pair['overlap_ms']>uncertainty:
            pair['classification']='unverified_long_overlap'
            pair['review_required']=True
            continue
        vad=_evidence_points(project,left,('speech_regions','vad','regions'))+_evidence_points(project,right,('speech_regions','vad','regions'))
        vad += [(round(x['start']*1000),round(x['end']*1000)) for x in project.generation_metadata.get('speaker_recovery',{}).get('vad_intervals',[])
                if isinstance(x,dict) and 'start' in x and 'end' in x]
        window_start=max(left.start_ms+50,right.start_ms-uncertainty)
        candidates=[(end,'word_end') for _start,end in words_left if window_start<=end<=right.start_ms]
        candidates += [(start,'word_start') for start,_end in words_right if window_start<=start<=right.start_ms]
        candidates += [(point,'vad_boundary') for span in vad for point in span if window_start<=point<=right.start_ms]
        boundary,reason=min(candidates,key=lambda x:abs(x[0]-right.start_ms)) if candidates else (right.start_ms,'incoming_cue_frame_boundary')
        snapped=min(boundary,round(math.floor((boundary+.5)/frame)*frame))
        if snapped-left.start_ms<50:continue
        changes[left.id]=min(changes.get(left.id,left.end_ms),snapped)
        pair.update(classification='handoff_boundary_error',boundary_ms=snapped,boundary_source=reason,
                    nearby_word_intervals=words_left+words_right,nearby_vad_boundaries=[p for span in vad for p in span if abs(p-right.start_ms)<1000])
    report=dict(policy_version=2,status='applied',pairs_before=audit,changed_ends=changes,
                counts={name:sum(p['classification']==name for p in audit) for name in
                        ('display_compensation','acoustic','uncertain','handoff_boundary_error','unverified_long_overlap')},
                source='source intervals + independent overlap evidence + frame/token/VAD handoff boundary')
    return changes,report


def classify_overlap(left_spans, right_spans):
    if not left_spans or not right_spans:
        return "uncertain"
    if any(min(b, d) > max(a, c) for a, b in left_spans for c, d in right_spans):
        return "acoustic"
    if max(b for _, b in left_spans) <= min(a for a, _ in right_spans):
        return "display_compensation"
    if max(b for _, b in right_spans) <= min(a for a, _ in left_spans):
        return "display_compensation"
    return "uncertain"


def protect_intervals(rows, acoustic):
    """Return end-only changes and a pre-change cross-speaker overlap audit."""
    ends = {row["id"]: row["end_ms"] for row in rows}
    audit = []
    ordered = sorted(rows, key=lambda row: (row["start_ms"], row["end_ms"], row["id"]))
    for index, left in enumerate(ordered):
        for right in ordered[index+1:]:
            if right["start_ms"] >= left["end_ms"]:
                break
            a, b = acoustic.get(left["id"], []), acoustic.get(right["id"], [])
            kind = classify_overlap(a, b)
            if left["speaker"] != right["speaker"]:
                audit.append({"left": left["id"], "right": right["id"], "classification": kind,
                              "left_acoustic": a, "right_acoustic": b,
                              "overlap_ms": min(left["end_ms"], right["end_ms"]) - right["start_ms"]})
            if kind == "display_compensation" and a and b and max(end for _, end in a) <= min(start for start, _ in b):
                if right["start_ms"] > left["start_ms"]:
                    ends[left["id"]] = min(ends[left["id"]], right["start_ms"])
    return {row["id"]: ends[row["id"]] for row in rows if ends[row["id"]] != row["end_ms"]}, audit


def project_acoustics(project, cue):
    spans = []
    for ref in cue.evidence_refs:
        row = project.asr_evidence.get(ref, {})
        if "acoustic_start_ms" in row and "acoustic_end_ms" in row:
            a, b = row["acoustic_start_ms"], row["acoustic_end_ms"]
        elif (row.get("firered_end", 0) > row.get("firered_start", 0)
              and row.get("firered_alignment_confidence", 0) >= 0.65
              and "degraded" not in str(row.get("final_timing_owner", "")).lower()):
            a, b = round(row["firered_start"]*1000), round(row["firered_end"]*1000)
        elif row.get("moss_end", 0) > row.get("moss_start", 0):
            a, b = round(row["moss_start"]*1000), round(row["moss_end"]*1000)
        else:
            continue
        if b > a:
            spans.append((a, b))
    return sorted(set(spans))


def protect_project_display_tails(project):
    changes,report=project_display_tail_plan(project)
    for cue in project.cues:
        if cue.id in changes:
            cue.end_ms = changes[cue.id]
    project.generation_metadata["display_overlap_audit"] = report
    return report['pairs_before']


def protect_runtime_display_tails(cues, segments):
    if not segments:
        return []  # No source evidence: leave timing unchanged for review.
    rows = [dict(id=str(cue.cue_id), start_ms=round(cue.start*1000), end_ms=round(cue.end*1000), speaker=cue.speaker)
            for cue in cues]
    acoustic = {}
    for cue in cues:
        spans = []
        for segment in segments:
            if segment.speaker != cue.speaker or segment.end <= cue.start or segment.start >= cue.end:
                continue
            firered = (getattr(segment, "firered_alignment_confidence", 0) >= .65
                       and "degraded" not in str(getattr(segment, "final_timing_owner", "")).lower()
                       and getattr(segment, "firered_end", 0) > getattr(segment, "firered_start", 0))
            a = getattr(segment, "firered_start", 0) if firered else getattr(segment, "moss_start", 0)
            b = getattr(segment, "firered_end", 0) if firered else getattr(segment, "moss_end", 0)
            if b > a:
                spans.append((round(a*1000), round(b*1000)))
        acoustic[str(cue.cue_id)] = spans
    changes, audit = protect_intervals(rows, acoustic)
    for cue in cues:
        if str(cue.cue_id) in changes:
            cue.end = changes[str(cue.cue_id)] / 1000
    return audit
