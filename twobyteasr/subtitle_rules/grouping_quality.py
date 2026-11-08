"""One source index and quality gate for Chinese grouping and local repairs.

Offsets are content_exact Unicode code points. Raw characters are never
normalized or discarded. Request windows, retry windows and subtitles slice
this same map, including punctuation, combining marks and emoji.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import math
import re

from .text_rules import content_exact, display_length

QUALITY_VERSION = "grouping-quality-v1"


@dataclass(frozen=True)
class SourceIndex:
    text: str
    content: str
    raw_edges: tuple[int, ...]

    @classmethod
    def build(cls, text):
        positions = [i for i, char in enumerate(text) if content_exact(char)]
        content = content_exact(text)
        if len(positions) != len(content) or len(content) != display_length(text):
            raise ValueError("来源字符索引与长度口径不一致。")
        # Non-counting characters belong to the preceding content character.
        # A leading prefix belongs to the first piece.
        edges = (0, *positions[1:], len(text)) if positions else (0,)
        return cls(text, content, tuple(edges))

    def slice(self, start, end):
        return self.text[self.raw_edges[start]:self.raw_edges[end]]

    def pieces(self, boundaries):
        start = 0
        pieces = []
        for end in boundaries:
            pieces.append(self.slice(start, end))
            start = end
        return pieces


def enabled():
    from .language_rules import active_task_language
    return (active_task_language() or "zh").split("-")[0] in {"zh", "Chinese"}


def limits():
    try:
        from .segmentation_profiles import current_profile
    except ImportError:
        from subtitle_core import MAX_SUBTITLE_CHARS, MAX_SUBTITLE_SECONDS, MIN_SUBTITLE_SECONDS
        return MAX_SUBTITLE_CHARS, MAX_SUBTITLE_SECONDS, MIN_SUBTITLE_SECONDS
    profile = current_profile()
    return int(profile.hard_max), profile.max_seconds, profile.min_seconds


class BoundaryQuality:
    """Full-context lexical candidates, protected edges and local acceptance.

    Severe semantic violations are constraints. Length/timing preferences
    cannot buy a cut inside a word. An infeasible range remains readable and
    is returned with explicit review issues.
    """

    def __init__(self, text, *, units=(), required=(), pauses=None, max_chars=None,
                 max_seconds=None, min_seconds=None):
        from .segmentation import (boundary_word_spans, lexical_forbidden_boundary_offsets,
                                   semantically_awkward_boundary, lexical_boundary_terms)
        from .number_fidelity import numeric_unsafe_cut_offsets, numeric_spans
        self.index = SourceIndex.build(text)
        self.total = len(self.index.content)
        defaults = limits()
        self.max_chars = int(max_chars if max_chars is not None else defaults[0])
        self.max_seconds = max_seconds if max_seconds is not None else defaults[1]
        self.min_seconds = min_seconds if min_seconds is not None else defaults[2]
        self.units = list(units)
        if self.units and len(self.units) != self.total:
            raise ValueError("时间单元和正文索引不一致。")
        self.required = {int(x) for x in required if 0 < x < self.total}
        self.pauses = dict(pauses or {})
        self.forbidden = set()
        self.restarts = set()
        self.awkward = set()
        self.protected_conflicts = set()
        self.stable_boundaries = set()
        self.soft_dependencies = set()
        self.semantic_required = set()
        # Tokenize each protected turn separately. Concatenating overlapping
        # speakers must not manufacture a cross-speaker name or lexical word.
        start = 0
        for end in sorted(self.required | {self.total}):
            piece = self.index.slice(start, end)
            content = content_exact(piece)
            spans = boundary_word_spans(content)
            local = set(lexical_forbidden_boundary_offsets(piece))
            has_numbers = bool(re.search(r"[0-9零〇一二两三四五六七八九十百千万亿]",piece))
            numeric_unsafe = numeric_unsafe_cut_offsets(piece) if has_numbers else set()
            local.update(numeric_unsafe)
            for left, right, _ in spans:
                local.update(range(left + 1, right))
            for match in re.finditer(r"(.{1,4})\1+", content):
                if match.end()-match.start() <= self.max_chars:
                    local.update(range(match.start()+1,match.end()))
            # Generic grammar units absent from a general-purpose word lexicon.
            patterns = (
                r"[这那哪每本此该](?:一|两|几|\d+)?[场个种次位条件项份台名届]",
                r"[上下前后](?:一|两|几|\d+)次",
                r"[一二三四五六七八九十\d]+代[团队机车]",
                r"(?:总体|整体|总的|综合|一般|相对)(?:来说|来讲|而言)",
                r"[男女][团队]",
                r"[\u3400-\u9fff]得(?=[\u3400-\u9fff])",
                r"等于是",
                r"[A-Za-z][A-Za-z0-9]*(?:[-'’.][A-Za-z0-9]+)*",
                r"\d+(?:[.,]\d+)*(?:毫米|厘米|公里|千米|毫秒|分钟|小时|公斤|千克|千瓦|兆瓦|MB|GB|MHz|GHz|km|kg|ms|%|℃)",
            )
            strong_edges = set()
            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    local.update(range(match.start() + 1, match.end()))
                    if pattern.startswith(("[上下前后]", "[这那哪每本此该]", "(?:总体")):
                        strong_edges.update(match.span())
                        self.restarts.add(start+match.start())
            # A lecture can concatenate several complete values (十八十九二十).
            # The generic noun regex sees one long numeral string. The numeric
            # fidelity parser knows which edges preserve the actual values.
            explicit_terms = set()
            for term in lexical_boundary_terms():
                for match in re.finditer(re.escape(term),content):
                    explicit_terms.update(range(match.start()+1,match.end()))
            for a,b in numeric_spans(piece):
                numeric_unsafe.update(range(len(content_exact(piece[:a]))+1,len(content_exact(piece[:b]))))
            local.update(numeric_unsafe)
            for match in re.finditer(r"[零〇一二两三四五六七八九十百千万亿点\d]+",content):
                for cut in range(match.start()+1,match.end()):
                    if cut not in numeric_unsafe and cut not in explicit_terms:
                        local.discard(cut)
            # A tokenizer can invent 下上 across 情况下 | 上一次. Productive
            # complete phrases outrank that overlapping generic token, while
            # explicit names and numeric evidence keep their protections.
            for cut in strong_edges-explicit_terms-numeric_unsafe:
                local.discard(cut)
            self.forbidden.update(start + x for x in local if 0 < x < end-start)
            local_index = SourceIndex.build(piece)
            self.awkward.update(start + x for x in range(1, end-start)
                if semantically_awkward_boundary(
                    local_index.slice(max(0,x-30), min(len(content),x+30)), min(x,30)))
            self.awkward.difference_update(start+x for x in strong_edges-explicit_terms-numeric_unsafe)
            # Connectives are protected as words by the tokenizer. Their
            # ownership is additionally evaluated in the entire clause.
            for match in re.finditer(r"虽然|但是|然而|不过|所以|因此|而且|结果", content):
                left, right = match.span()
                word = match.group()
                before, after = content[max(0, left-40):left], content[right:right+18]
                nominal_result = word == "结果" and bool(re.match(
                    r"显示|表明|是|为|如何|不错|很好|出来|公布|揭晓", after))
                result_clause = (word != "结果" or not nominal_result and (
                    re.search(r"本来|原本|以为|预计|没想到", before)
                    or re.match(r"[\u3400-\u9fff]{1,6}(?:这个|这家|却|又|反而|竟然|先|就)", after)))
                # Punctuation or a true turn/pause can complete an isolated
                # spoken connective. It is not automatically sent right.
                raw_word = local_index.slice(left, right)
                terminal = bool(re.search(r"[。！？!?]", raw_word))
                if result_clause and before and after and not terminal:
                    self.forbidden.add(start + right)
                    self.restarts.add(start + left)
                    paired = list(re.finditer(r"本来|原本|以为|预计|没想到",before))
                    independent_subject = re.match(r"[\u3400-\u9fff]{1,6}(?:这个|这家|却|又|反而|竟然|先|就)",after)
                    if word=="结果" and paired and independent_subject and len(before)-paired[-1].start() >= self.max_chars:
                        self.semantic_required.add(start+left)
            # POS supplies productive dependencies and person names, including
            # words absent from the task's glossary. A stranded 又/已经/都 is
            # still bad when it happens to be a legal character/word index.
            import jieba.posseg as posseg
            tagged = list(posseg.cut(content))
            position = 0
            for i, token in enumerate(tagged):
                word_start, word_end = position, position+len(token.word)
                position = word_end
                if token.flag.startswith("nr"):
                    self.forbidden.update(range(start+word_start+1,start+word_end))
                if i+1 >= len(tagged):
                    continue
                following = tagged[i+1]
                terminal = bool(re.search(r"[。！？!?]",local_index.slice(word_start,word_end)))
                dependent = (token.flag in {"d","p","c"} and following.flag[0] in "vanrdmp")
                previous = i-1
                adjective = False
                while previous >= 0 and tagged[previous].flag in {"d","a","ad","an"}:
                    adjective = adjective or tagged[previous].flag.startswith("a")
                    previous -= 1
                complete_judgement = adjective and previous >= 0 and tagged[previous].word=="是"
                modifier = (token.flag == "uj" and following.flag.startswith("n")
                            and not complete_judgement and start+word_end not in self.restarts)
                if not terminal and (dependent or modifier):
                    self.forbidden.add(start+word_end)
                    if token.flag=="c":
                        self.restarts.add(start+word_start)
                if (not terminal and (token.flag.startswith("n") or token.flag=="r")
                        and (following.flag[0] in "dvtr" or following.word in {"还是","就是","也是","应该","可能","需要","能够"})
                        and self.pauses.get(start+word_end,0.) < .18):
                    self.soft_dependencies.add(start+word_end)
            start = end
        self.forbidden.difference_update(self.required)
        self.allowed = sorted(set(range(1, self.total+1)) - self.forbidden)

    def duration(self, start, end):
        if not self.units:
            return 0.
        return max(0., self.units[end-1].end-self.units[start].start)

    def inspect(self, boundaries):
        from .grouping_contract import validate_boundary_offsets
        validate_boundary_offsets(list(boundaries), self.total)
        issues = []
        for cut in sorted(self.required-set(boundaries)):
            issues.append(dict(kind="protected_boundary_missing", start=cut, end=cut))
        for cut in sorted(self.semantic_required-set(boundaries)):
            issues.append(dict(kind="connective_ownership",start=cut,end=cut))
        for cut in sorted(self.protected_conflicts):
            issues.append(dict(kind="pause_or_source_word_conflict",start=cut,end=cut))
        start = 0
        for end in boundaries:
            if end in self.forbidden:
                issues.append(dict(kind="semantic_boundary", start=end, end=end))
            elif end in self.awkward and end not in self.required:
                issues.append(dict(kind="semantic_cohesion", start=end, end=end))
            if end-start > self.max_chars:
                issues.append(dict(kind="length", start=start, end=end, length=end-start))
            duration = self.duration(start, end)
            if self.units and duration > self.max_seconds+.05:
                issues.append(dict(kind="duration", start=start, end=end, seconds=duration))
            if (self.units and duration < self.min_seconds-1e-6
                    and start not in self.required
                    and end not in self.required and len(boundaries) > 1):
                issues.append(dict(kind="short_tail", start=start, end=end))
            start = end
        return issues

    def windows(self, boundaries, issues=None):
        """A bad boundary sees both neighbours and a third cue for short tails."""
        edges = [0, *boundaries]
        intervals = []
        for issue in self.inspect(boundaries) if issues is None else issues:
            first = max(0, next((i for i, x in enumerate(edges) if x >= issue["start"]), len(edges)-1)-1)
            last = next((i for i, x in enumerate(edges) if x >= issue["end"]), len(edges)-1)
            first, last = max(0, first-1), min(len(edges)-1, last+1)
            left, right = edges[first], edges[last]
            intervals.append((left, right))
        # Issues are not necessarily ordered (missing protected cuts come first).
        merged = []
        for left, right in sorted(intervals):
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        return merged

    def _solve(self, left, right, original, *, fixed=(), relax_time=False, relax_length=False):
        from bisect import bisect_right
        points = [left, *(x for x in self.allowed if left < x < right), right]
        scores, previous = {left: 0.}, {}
        required = sorted(x for x in self.required | self.semantic_required | set(fixed) if left < x < right)
        for end_index, end in enumerate(points[1:], 1):
            for start in reversed(points[:end_index]):
                length = end-start
                if length > self.max_chars and not relax_length:
                    break
                if start not in scores:
                    continue
                if end < right and end in self.awkward and end not in original and end not in self.required:
                    continue
                if bisect_right(required, start) < bisect_right(required, end-1):
                    continue
                duration = self.duration(start, end)
                if self.units and duration > self.max_seconds+.05 and not relax_time:
                    continue
                cost = 3. + .055*(length-min(10, self.max_chars))**2
                if self.units and duration < self.min_seconds:
                    cost += 8. + 20.*(self.min_seconds-duration)**2
                cost += 500.*max(0, length-self.max_chars)**2
                cost += 25.*max(0., duration-self.max_seconds)**2
                if end < right:
                    cost += 25. if end in self.awkward else 0.
                    cost += 14. if end in self.soft_dependencies else 0.
                    cost -= 4. if end in original else 0.
                    cost -= min(7., self.pauses.get(end, 0.)*20.)
                    cost -= 3. if end in self.restarts else 0.
                total = scores[start]+cost
                if total < scores.get(end, math.inf):
                    scores[end], previous[end] = total, start
        if right not in previous:
            return None
        result, cursor = [], right
        while cursor != left:
            result.append(cursor)
            cursor = previous[cursor]
        return list(reversed(result))

    def repair(self, boundaries, *, record=None, rule="quality_local_window"):
        original = list(boundaries)
        issues = self.inspect(original)
        unstable = self.forbidden | self.awkward
        unstable = unstable | {edge for issue in issues if issue['kind']=='short_tail'
                               for edge in (issue['start'],issue['end'])}
        self.stable_boundaries = set(original)-unstable
        result = set(original)
        for left, right in self.windows(original, issues):
            before = sorted(x for x in result if left < x <= right)
            candidate = self._solve(left, right, set(before),fixed=self.stable_boundaries)
            reason = "length_semantics_time_passed"
            if candidate is None:
                candidate = self._solve(left, right, set(before), fixed=self.stable_boundaries,relax_time=True)
                reason = "timing_constraint_conflict_review"
            if candidate is None:
                candidate = self._solve(left, right, set(before),fixed=self.stable_boundaries,relax_time=True,relax_length=True)
                reason = "indivisible_term_length_conflict_review"
            if candidate is None:
                candidate = before
                reason = "no_safe_path_retained_review"
            accepted, rejection = self.accept_change(sorted(result),
                sorted((result-set(before)) | set(candidate)))
            if record:
                old_edges, new_edges = set(before), set(candidate)
                record("grouping_boundary_move", rule=rule, accepted=accepted,
                    reason=reason if accepted else rejection, content_start=left, content_end=right,
                    old_positions=before, new_positions=candidate,
                    removed_positions=sorted(old_edges-new_edges), added_positions=sorted(new_edges-old_edges),
                    before=self.index.pieces([left, *before])[1:] if left else self.index.pieces(before),
                    after=[self.index.slice(a,b) for a,b in zip([left,*candidate],candidate)])
            if accepted:
                result.difference_update(before)
                result.update(candidate)
        final = sorted(result)
        return final, self.inspect(final)

    def accept_change(self, before, after):
        if (self.required-set(after)) - set(self.required-set(before)):
            return False, "protected_boundary_missing"
        if not self.stable_boundaries.issubset(after):
            return False, "valid_model_boundary_changed"
        if (self.semantic_required-set(after)) - set(self.semantic_required-set(before)):
            return False, "connective_ownership_changed"
        old_bad = set(before) & self.forbidden
        new_bad = set(after) & self.forbidden
        if new_bad-old_bad:
            return False, "new_word_or_connective_damage"
        if (set(after) & self.awkward) - set(before):
            return False, "new_syntactic_damage"
        # Both arrays reconstruct exactly the same immutable raw source. New
        # positions cannot silently delete punctuation or change a number.
        if "".join(self.index.pieces(after)) != self.index.text:
            return False, "raw_text_conservation_failed"
        return True, "passed"


def quality_for_segments(segments, tokens=(), *, protected=()):
    from .segmentation_alignment import (segment_content_timeline,
        hard_break_character_offsets, protected_source_boundary_offsets,
        firered_pause_character_gaps)
    required = (set(protected) | hard_break_character_offsets(segments, tokens)
                | protected_source_boundary_offsets(segments))
    cursor = 0
    for left, right in zip(segments, segments[1:]):
        cursor += display_length(left.text)
        if left.speaker != right.speaker or right.start-left.end > 2.:
            required.add(cursor)
    units = []
    for segment in segments:
        private = copy.copy(segment)
        private.caption_arbitration = copy.deepcopy(segment.caption_arbitration)
        private.words = [w for w in segment.words if
            math.isfinite(w.start) and math.isfinite(w.end)
            and segment.start <= w.start < w.end <= segment.end+.001]
        units.extend(segment_content_timeline(private,tokens))
    quality = BoundaryQuality("".join(s.text for s in segments), units=units,
                              required=required, pauses=firered_pause_character_gaps(segments, tokens))
    cursor = 0
    for segment in segments:
        evidence = segment.caption_arbitration.get("word_timing", {})
        words = evidence.get("measured_words", ())
        if evidence.get("basis") != "uniform_display_estimate":
            content = content_exact(segment.text)
            position = 0
            for word in words:
                value = content_exact(word.get("text", ""))
                found = content.find(value,position) if value else -1
                if found >= 0:
                    quality.forbidden.update(range(cursor+found+1,cursor+found+len(value)))
                    position = found+len(value)
        cursor += display_length(segment.text)
    quality.forbidden.difference_update(quality.required)
    # True turn changes have independent lexical context. A measured pause
    # inside an otherwise indivisible name/number in the same turn is an
    # explicit conflict, not proof that the token became two valid words.
    from .segmentation import lexical_forbidden_boundary_offsets
    from .number_fidelity import numeric_unsafe_cut_offsets
    global_unsafe = set(lexical_forbidden_boundary_offsets(quality.index.text))
    global_unsafe.update(numeric_unsafe_cut_offsets(quality.index.text))
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9]+",quality.index.content):
        global_unsafe.update(range(match.start()+1,match.end()))
    handoffs, cursor = set(), 0
    for left,right in zip(segments,segments[1:]):
        cursor += display_length(left.text)
        if left.speaker != right.speaker:
            handoffs.add(cursor)
    quality.protected_conflicts = (quality.required & global_unsafe) - handoffs
    quality.allowed = sorted(set(range(1,quality.total+1))-quality.forbidden)
    return quality


def boundary_timing_basis(segments, tokens, seconds, edge, char):
    """A timestamp coincidence alone is insufficient evidence of a word edge."""
    from .segmentation_alignment import alignment_key
    for segment in segments:
        evidence = segment.caption_arbitration.get("word_timing", {})
        if evidence.get("basis") == "uniform_display_estimate":
            continue
        native = segment.caption_arbitration.get("provider_source", {}).get("valid_word_times")
        measured = evidence.get("measured_words")
        if native:
            observations = [(float(w[edge]), w.get("text", "")) for w in native]
        elif measured:
            observations = [(float(w[edge+"_ms"])/1000,w.get("text", "")) for w in measured]
        else:
            observations = [(getattr(w,edge), w.text) for w in segment.words]
        for stamp, text in observations:
            content = content_exact(text)
            if (content and math.isfinite(stamp) and segment.start <= stamp <= segment.end and abs(stamp-seconds)<.001
                    and alignment_key(content[0 if edge=="start" else -1])==alignment_key(char)):
                return ("provider_word" if native or evidence.get("basis")=="provider_words"
                        else "forced_aligner_word" if evidence.get("basis")=="aligner_words" else "source_word")
    for token in tokens:
        text = content_exact(token.get("text", ""))
        stamp = float(token.get(edge,-99))
        if (text and abs(stamp-seconds)<.001 and any(s.start <= stamp <= s.end for s in segments)
                and alignment_key(text[0 if edge=="start" else -1])==alignment_key(char)):
            return "firered_word"
    if any(abs(getattr(segment,edge)-seconds)<.001 for segment in segments):
        return "source_segment"
    return "estimate"


def cues_from_quality(segments, boundaries, tokens=(), *, protected=(), record=None):
    from ..recognition.transcript_data import SubtitleCue
    quality = quality_for_segments(segments, tokens, protected=protected)
    final, issues = quality.repair(boundaries, record=record)
    cues, start, cursor, owner_index = [], 0, 0, 0
    owner_ends = []
    for segment in segments:
        cursor += display_length(segment.text)
        owner_ends.append(cursor)
    for end, text in zip(final, quality.index.pieces(final)):
        while owner_index < len(segments)-1 and start >= owner_ends[owner_index]:
            owner_index += 1
        owners = [s for i,s in enumerate(segments)
                  if owner_ends[i] > start and owner_ends[i]-display_length(s.text) < end]
        unit_start = quality.units[start].start
        unit_end = quality.units[end-1].end
        # Preserve the measured/estimated acoustic envelope. A display minimum
        # never moves a cue into a different source or across a turn.
        low, high = min(s.start for s in owners), max(s.end for s in owners)
        cue_start = max(low, min(unit_start, high-.001))
        cue_end = max(cue_start+.001, min(high, unit_end))
        cues.append(SubtitleCue(0, cue_start, cue_end, text,
            speaker=segments[owner_index].speaker,
            timing_locked=all(s.timing_locked for s in owners)))
        cues[-1].start_timing_basis = boundary_timing_basis(owners,tokens,cue_start,"start",quality.index.content[start])
        cues[-1].end_timing_basis = boundary_timing_basis(owners,tokens,cue_end,"end",quality.index.content[end-1])
        cues[-1].timing_basis = (f"quality={QUALITY_VERSION};domain=acoustic_before_display;"
            f"start={cues[-1].start_timing_basis};end={cues[-1].end_timing_basis}")
        start = end
    from .grouping_contract import validate_grouping_result
    validate_grouping_result(segments, cues)
    if record:
        from collections import Counter
        record("grouping_timing_evidence", source_segment_ids=[s.segment_id for s in segments],
            boundary_basis_counts=dict(Counter(basis for cue in cues for basis in
                (cue.start_timing_basis,cue.end_timing_basis))),
            domain="acoustic_before_display", word_evidence_tokens=len(tokens))
        unresolved = [s.segment_id for i,s in enumerate(segments) if
            "UNCONFIRMED" in s.speaker and any(other.speaker==s.speaker and
                max(other.start,s.start)<min(other.end,s.end) for other in segments[:i])]
        if unresolved:
            from subtitle_core import add_review_item
            source_ids=[s.segment_id for s in segments]
            record("grouping_overlap_source_retained",source_segment_ids=source_ids,
                   reason="unresolved_speaker_overlap_preserved")
            add_review_item(segments[0].start,"重叠来源断句待审",
                "保留未确认身份来源的完整文字和真实重叠时间，需要核对说话人。",quality.index.text,
                priority=3,severity="warning",source_segment_ids=source_ids)
    if issues:
        from subtitle_core import add_review_item
        for issue in issues:
            position = min(issue["start"], max(0, quality.total-1))
            add_review_item(quality.units[position].start, "断句约束待复核",
                "语义、长度或显示时间约束无法同时满足，保留完整原文和来源时间。",
                quality.index.slice(issue["start"], issue["end"]), priority=3, severity="warning",
                grouping_quality=issue, grouping_origin="local_review")
        if record:
            record("grouping_quality_review", issues=issues, final_boundaries=final)
    return cues, final, issues
