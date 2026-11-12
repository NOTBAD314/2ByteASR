"""Derived ownership for mixed-audio readings in overlapping source segments.

Native ASR speaker labels are deliberately never compared with project labels.
The original evidence mapping is read-only. Time, input channel, unique local
text anchors and competing source context must agree before a patch is offered.
"""
from collections import defaultdict
from difflib import SequenceMatcher

from .caption_arbitration import content

POLICY = 'overlap-candidate-v3-local-patch-owner'


def local_match(source, reading):
    replacement = str(reading).strip()
    source, reading = content(source), content(reading)
    if not source or not reading or max(len(source), len(reading)) > 512:
        return None
    blocks = SequenceMatcher(None, reading, source, autojunk=False).get_matching_blocks()
    anchor = max(blocks, key=lambda block: block.size)
    if anchor.size < min(2, len(reading)) or sum(b.size for b in blocks) < max(2, len(reading)*.6):
        return None
    start = max(0, anchor.b-anchor.a)
    end = min(len(source), start+len(reading))
    expected = source[start:end]
    score = SequenceMatcher(None, expected, reading, autojunk=False).ratio()
    if score < .65 or source.count(expected) != 1:
        return None
    return dict(start=start, end=end, expected=expected, replacement=replacement, score=score)


def source_text(row):
    original = (row.get('caption_arbitration') or {}).get('independent_input_evidence') or {}
    return original.get('primary') or row.get('moss_text') or row.get('text') or ''


def associations(project, *, refresh=False):
    from ..subtitle_rules.studio_qc import _EvidenceTimeIndex
    from ..subtitle_rules.current_issues import digest
    evidence = project.asr_evidence
    runtime=getattr(project,'_studio_state_runtime',None)
    key = (id(evidence), len(evidence), POLICY, getattr(runtime,'qc_revision',None))
    cached = getattr(project, '_overlap_candidate_mapping', None)
    if not refresh and cached is not None and cached[0] == key:
        return cached[1]
    index = _EvidenceTimeIndex(evidence)
    assigned, suppressed = defaultdict(list), set()
    for ref, row in evidence.items():
        if not isinstance(row, dict) or row.get('cue_alignment'):
            continue
        arbitration = row.get('caption_arbitration') or {}
        coverage = arbitration.get('source_coverage') or row.get('source_coverage') or {}
        scopes = coverage.get('firered') or ()
        scopes = scopes if isinstance(scopes,(list,tuple)) else ()
        hypotheses = row.get('hypotheses') or ()
        hypotheses = hypotheses if isinstance(hypotheses,(list,tuple)) else ()
        owned = lambda scope: isinstance(scope,dict) and (scope.get('project_speaker_id') or
            scope.get('speaker_independent') is True or scope.get('speaker_verified') is True)
        explicit_aux = (row.get('speaker_independent') is True or any(owned(scope) for scope in scopes)
            or any(owned(scope) for scope in hypotheses
                   if isinstance(scope,dict) and 'firered' in str(scope.get('model') or scope.get('source') or '').casefold()))
        if explicit_aux:continue
        original = arbitration.get('independent_input_evidence') or {}
        reading = original.get('firered') or row.get('firered_text')
        if not reading:
            continue
        a = round(float(row.get('firered_start') or 0)*1000) or int(row.get('start_ms') or 0)
        b = round(float(row.get('firered_end') or 0)*1000) or int(row.get('end_ms') or 0)
        peers = [(target, other) for _, target, other in index.overlapping(a, b, 0)
                 if not other.get('cue_alignment') and source_text(other)
                 and min(b, int(other.get('end_ms') or 0)) > max(a, int(other.get('start_ms') or 0))]
        # Multiple records from the same speaker can simply be a sentence split.
        speakers = {str(other.get('speaker_id') or other.get('speaker') or '') for _, other in peers}
        if len(speakers) < 2:
            continue
        suppressed.add(ref)
        matches = []
        for target, other in peers:
            if any(row.get(k) is not None and other.get(k) is not None and row[k] != other[k]
                   for k in ('audio_lane', 'input_channel', 'source_path')):
                continue
            match = local_match(source_text(other), reading)
            if match:
                matches.append((match['score'], target, match))
        matches.sort(key=lambda item: (-item[0], item[1]))
        reliable = bool(matches) and (len(matches) == 1 or matches[0][0]-matches[1][0] >= .2)
        payload = dict(candidate_id=digest([POLICY, ref, 'firered', a, b, reading]),
                       model='firered', observed_text=str(reading), reference=ref,
                       original_start_ms=a, original_end_ms=b,
                       input_channel=row.get('input_channel'), audio_lane=row.get('audio_lane'),
                       source_path=row.get('source_path'),
                       recognition_window=row.get('recognition_window'),
                       native_words=row.get('firered_words') or
                           (row.get('caption_arbitration') or {}).get('acoustic_words') or [],
                       related_references=[target for target, _ in peers],
                       ownership='local_anchor_and_time' if reliable else 'needs_confirmation')
        if reliable:
            _, target, match = matches[0]
            owner = str(evidence[target].get('speaker_id') or '')
            competing = [(peer, str(other.get('speaker_id') or ''), str(source_text(other)))
                for peer,other in peers if str(other.get('speaker_id') or '') not in {'',owner}]
            assigned[target].append(dict(payload, **match, speaker_id=owner, speaker_verified=bool(owner),
                                         competing_utterances=competing))
        else:
            for target, _ in peers:
                assigned[target].append(dict(payload))
    result = (dict(assigned), suppressed)
    project._overlap_candidate_mapping = (key, result)
    return result


def project_candidate(candidate, cue):
    """Offer a full context-preserving text only for a unique literal span."""
    from ..subtitle_rules.current_issues import digest
    positions = [i for i, char in enumerate(cue.text) if content(char)]
    current = ''.join(cue.text[i] for i in positions)
    expected = candidate.get('expected') or ''
    replacement = candidate.get('replacement') or candidate['observed_text']
    start = current.find(expected) if expected else -1
    certain = start >= 0 and current.find(expected, start+1) < 0
    if (not certain and candidate['ownership'] != 'needs_confirmation'
            and current and expected.count(current) == 1):
        # One original recognition sentence can become several display cues.
        # Slice the text patch by its literal source range, never a time ratio.
        from ..subtitle_rules.review_suggestions import _map
        offset = expected.index(current)
        operations = SequenceMatcher(None, expected, replacement, autojunk=False).get_opcodes()
        replacement = replacement[_map(operations, offset):_map(operations, offset+len(current))]
        expected, start, certain = current, 0, True
    # After adoption the same observation supports the corrected fragment.
    if not certain and replacement and current.count(content(replacement)) == 1:
        expected = content(replacement)
        start = current.find(expected)
        certain = candidate['ownership'] != 'needs_confirmation'
    if certain:
        left, right = positions[start], positions[start+len(expected)-1]+1
        text = cue.text[:left]+replacement+cue.text[right:]
    else:
        if candidate['ownership'] != 'needs_confirmation' and not local_match(expected, current):
            return None
        left, right, text = None, None, candidate['observed_text']
    contaminated = False
    if certain and not candidate.get('speaker_independent'):
        # A long unique source anchor identifies the utterance, not every
        # changed word inside a mono mixture. Do not move a competing reply
        # into this speaker merely because the surrounding sentence matches.
        for tag,a,b,c,d in SequenceMatcher(None,expected,replacement,autojunk=False).get_opcodes():
            new = content(replacement[c:d])
            if tag=='equal' or not new:continue
            if any(new==content(other) or len(new)>=2 and new in content(other)
                   or len(new)==1 and content(other) and set(content(other))=={new}
                   for _,_,other in candidate.get('competing_utterances',())):
                contaminated=True;break
    result = dict(candidate, text=text, source='firered',
        reference='candidate:'+candidate['candidate_id'],
        candidate_partial=certain, context_only=not certain, coverage_unknown=not certain,
        ownership='local_anchor_and_time' if certain else 'needs_confirmation',
        start_ms=max(cue.start_ms, candidate['original_start_ms']),
        end_ms=min(cue.end_ms, candidate['original_end_ms']),
        cue_start_ms=cue.start_ms, cue_end_ms=cue.end_ms,
        cue_text_length=len(current), cue_text_start=start if certain else None,
        cue_text_end=start+len(expected) if certain else None,
        comparison_text=cue.text if certain else '',
        patch_start=left, patch_end=right, expected_text=expected,
        speaker_id=candidate.get('speaker_id',''), speaker_verified=candidate.get('speaker_verified',False), confidence=None,
        input_version=digest([cue.id, cue.text, cue.start_ms, cue.end_ms, candidate['candidate_id']]))
    if contaminated:
        result.update(context_only=True,coverage_unknown=True,speaker_verified=False,
                      ownership='needs_confirmation',ownership_reason='replacement_matches_other_speaker')
    return result
