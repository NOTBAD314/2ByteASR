"""Japanese AI line breaking: one candidate set for every entry, partial acceptance.

2026-11-25 (three real Japanese reports, 1.json / Ninja Spy / 真拳伝説 03):

* Qwen local + DeepSeek Flash: 13/13 grouping batches fell back. The Japanese
  answer was accepted all-or-nothing (``accepted_japanese_boundaries``): one
  line over 26 characters or 7 s, one mandatory pause inside a word
  (返してくださ｜い from a degraded aligner) or one pick off the marks threw
  the whole batch away, and the retry sent the same unsolvable request again.
* MOSS long material: the shard pipeline never built the nagisa document and
  ``japanese_break_candidates`` then offered *every* character gap as a
  bunsetsu boundary (break_candidate_count == total_length in all 30
  requests). 785 of 794 lines stayed source lines and the final length gate
  failed the whole task.

This module is the single Japanese engine used by the normal pipeline, the
long-material shards and Studio re-grouping:

``build_candidates``   phrase ends from the task's morphology document, else
                       the script-class heuristic (never every character);
                       mandatory breaks inside a word move to the nearest
                       phrase edge; stretches longer than the limit get local
                       supplementary cuts so a legal path exists.
``finalize_batch``     the model's picks are snapped onto candidates, lines
                       are checked one by one, only the failing windows go
                       back to the model with the exact error, and what the
                       model still cannot fix is split locally on legal
                       candidates and labelled ``local_*`` (never reported as
                       AI). An indivisible span is kept with a review note.

Offsets are ``content_exact`` positions (kana, kanji, latin, digits; no
punctuation or spaces), the unit every grouping helper indexes. Raw text is
sliced through ``SourceIndex`` so punctuation stays with the preceding
character; timing comes from ``segment_content_timeline``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json

from .text_rules import content_exact, display_length

PROTOCOL = "ja-grouping-v2-candidate-marks-partial-acceptance"

# Hiragana after which a person may start a new line when a stretch has no
# measured phrase edge (particles, te/ta forms, sentence-final particles).
_SUPPLEMENT_AFTER = set("はがをにでともへねよかてたぞさわや")
_NO_START = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮーゝゞヽヾ々")
_FINAL_ENDINGS = ("よ", "ね", "ぞ", "ぜ", "わ", "さ", "な", "か", "かい", "ー", "っ")
# Lines shorter than this are kept only at strong edges (standalone replies).
SHORT_LINE = 5
# Below this many characters per second a line's time is not speech-rate
# evidence (eight characters in a 25-second ASR window); its duration is not
# a reason to cut. Japanese speech runs about 6-9 kana per second.
MIN_TIMED_DENSITY = 2.5


def timing_is_evidence(units, seconds) -> bool:
    return seconds <= 0 or units / seconds >= MIN_TIMED_DENSITY


@dataclass
class CandidateSet:
    content: str
    candidates: list[int]
    phrase_ends: list[int]
    mandatory: list[int]
    strong: frozenset = frozenset()
    moved_mandatory: list[dict] = field(default_factory=list)
    supplemental: list[int] = field(default_factory=list)
    indivisible: list[tuple[int, int]] = field(default_factory=list)
    source: str = "heuristic"

    @property
    def total(self) -> int:
        return len(self.content)

    def receipt(self) -> dict:
        return dict(protocol=PROTOCOL, candidate_source=self.source, total_length=self.total,
                    candidate_count=len(self.candidates), phrase_end_count=len(self.phrase_ends),
                    mandatory=list(self.mandatory), mandatory_moved=list(self.moved_mandatory),
                    supplemental=list(self.supplemental),
                    indivisible=[dict(start=a, end=b, units=b - a) for a, b in self.indivisible])


def _phrase_ends(content: str) -> tuple[set[int], str, frozenset, set[int]]:
    """(phrase ends, source, strong breaks, word edges) of ``content``."""
    from .japanese_morphology import document_phrase_spans, document_strong_breaks, document_word_edges
    from .language_rules import heuristic_japanese_phrase_spans, split_repeated_chants, _script_class
    spans = document_phrase_spans(content)
    if spans is not None:
        strong = frozenset(document_strong_breaks(content) or ())
        ends = {end for _start, end, _word in spans if 0 < end <= len(content)}
        words = set(document_word_edges(content) or ()) | ends
        return ends, "morphology_document", strong, words
    spans = split_repeated_chants(heuristic_japanese_phrase_spans(content))
    ends = {end for _start, end, _word in spans if 0 < end <= len(content)}
    # Script runs the heuristic drops ("other") still end where the next run starts.
    ends |= {start for start, _end, _word in spans if 0 < start < len(content)}
    # Without morphology a word edge is a script change or a gap after a particle.
    words = set(ends) | {p for p in range(1, len(content))
                         if content[p] not in _NO_START
                         and (_script_class(content[p - 1]) != _script_class(content[p])
                              or content[p - 1] in _SUPPLEMENT_AFTER)}
    # A phrase closed by a sentence-final particle or a lengthened vowel is a
    # strong edge (本当だよ｜): a standalone line there is not a fragment.
    strong = frozenset(e for e in ends if 0 < e < len(content) and content[:e].endswith(_FINAL_ENDINGS))
    return ends, "script_heuristic", strong, words


def _supplement(content: str, left: int, right: int, limit: int) -> list[int]:
    """Extra legal cuts inside ``content[left:right]`` when it exceeds ``limit``."""
    from .language_rules import _script_class
    found = [p for p in range(left + 1, right)
             if content[p - 1] in _SUPPLEMENT_AFTER and content[p] not in _NO_START
             and _script_class(content[p - 1]) == "hira"]
    if not found:
        found = [p for p in range(left + 1, right)
                 if _script_class(content[p - 1]) != _script_class(content[p])
                 and content[p] not in _NO_START and _script_class(content[p]) in ("kanji", "kata", "latin")]
    return found


def build_candidates(source_text: str, mandatory=(), *, segment_offsets=(), hard_max: int = 26) -> CandidateSet | None:
    """Legal Japanese cut offsets for one batch text, or None when it cannot be indexed."""
    content = content_exact(source_text)
    total = len(content)
    if total <= 0 or display_length(source_text) != total:
        return None
    ends, source, strong, word_edges = _phrase_ends(content)
    joins = {int(x) for x in segment_offsets if 0 < int(x) < total}
    ends |= joins | {total}
    phrase_sorted = sorted(ends)
    kept, moved = set(), []
    for offset in sorted({int(x) for x in mandatory if 0 < int(x) < total}):
        if offset in ends or offset in word_edges:
            # A measured long pause on a word edge is a real cut even where the
            # phrase rules would not cut (いただきます｜殿 after an 8 s pause).
            kept.add(offset)
            continue
        inner = [e for e in phrase_sorted if 0 < e < total]
        if not inner:
            kept.add(offset)
            continue
        target = min(inner, key=lambda e: (abs(e - offset), -e))
        kept.add(target)
        moved.append(dict(given=offset, used=target, reason="mandatory_break_inside_word"))
    candidates = ends | kept
    supplemental, indivisible = [], []
    edges = [0, *sorted(candidates)]
    for left, right in zip(edges, edges[1:]):
        if right - left <= hard_max:
            continue
        extra = _supplement(content, left, right, hard_max)
        supplemental.extend(extra)
        inner = [left, *extra, right]
        if any(b - a > hard_max for a, b in zip(inner, inner[1:])):
            indivisible.extend((a, b) for a, b in zip(inner, inner[1:]) if b - a > hard_max)
    candidates |= set(supplemental)
    return CandidateSet(content, sorted(c for c in candidates if 0 < c <= total), phrase_sorted,
                        sorted(kept), strong, moved, sorted(supplemental), indivisible, source)


def snap(boundaries, candidates: CandidateSet) -> tuple[list[int], list[dict]]:
    """Model picks on the nearest candidate (later on a tie) plus every mandatory break."""
    marks = candidates.candidates
    total = candidates.total
    result, moves = set(), []
    for raw in boundaries:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if value >= total:
            result.add(total)
            continue
        if value in marks:
            result.add(value)
            continue
        target = min(marks, key=lambda m: (abs(m - value), -m))
        result.add(target)
        moves.append(dict(given=value, used=target))
    result |= set(candidates.mandatory) | {total}
    return sorted(result), moves


# --- timing ------------------------------------------------------------------------------------

def _spread_in_row(segment):
    from ..recognition.transcript_data import WordUnit
    length = max(1, display_length(segment.text))
    step = max(0.001, (float(segment.end) - float(segment.start)) / length)
    return [WordUnit(float(segment.start) + i * step, float(segment.start) + (i + 1) * step, "", 0.0)
            for i in range(display_length(segment.text))]


def _inside_row(units, segment):
    """Unit times kept inside the row's own sentence envelope.

    2026-11-26 (比利犬 13/16/17, three Japanese episodes failed at stage 9):
    aligner word times ran past their row (おらい 793.76-794.40 s), the cue cut
    from them claimed seconds outside its source, the contract rejected the
    batch, and the retained-source fallback, split on the same times, was
    rejected too, so the whole task failed. Word evidence may place a cut
    inside the row; it never widens the row. Evidence that mostly lies outside
    the row is from another time domain and is replaced by an even spread.
    """
    from ..recognition.transcript_data import WordUnit
    low, high = float(segment.start), float(segment.end)
    if not units or high <= low:
        return units
    inside = sum(1 for unit in units if float(unit.end) > low and float(unit.start) < high)
    if inside * 2 < len(units):
        return _spread_in_row(segment)
    result, floor = [], low
    for unit in units:
        start = min(max(float(unit.start), floor), high)
        end = min(max(float(unit.end), start), high)
        result.append(WordUnit(start, end, getattr(unit, "text", ""), getattr(unit, "probability", 0.0)))
        floor = start
    return result


def _timeline(segment_batch, firered_tokens):
    from .segmentation_alignment import segment_content_timeline, tokens_near_segments
    firered_tokens = tokens_near_segments(segment_batch, firered_tokens)   # same answer, far fewer tokens
    units = []
    for segment in segment_batch:
        own = segment_content_timeline(segment, firered_tokens)
        if len(own) != display_length(segment.text):
            # No usable unit timing for this row: spread inside the row's own bounds.
            own = _spread_in_row(segment)
        units.extend(_inside_row(own, segment))
    return units


def piece_seconds(timeline, left, right) -> float:
    if right <= left or right > len(timeline):
        return 0.0
    return max(0.0, float(timeline[right - 1].end) - float(timeline[left].start))


def cues_for(segment_batch, boundaries, firered_tokens=(), speech_regions=()):
    """One cue per boundary piece; text sliced from the source, times from the timeline."""
    from .grouping_quality import SourceIndex
    from ..recognition.transcript_data import SubtitleCue
    source_text = "".join(segment.text for segment in segment_batch)
    index = SourceIndex.build(source_text)
    timeline = _timeline(segment_batch, firered_tokens)
    if len(timeline) != len(index.content):
        raise ValueError("日语断句时间单元与正文长度不一致。")
    locked, cursor = [], 0
    for segment in segment_batch:
        length = display_length(segment.text)
        locked.append((cursor, cursor + length, bool(getattr(segment, "timing_locked", False))))
        cursor += length
    cues, left = [], 0
    for right in boundaries:
        text = index.slice(left, right)
        start = float(timeline[left].start)
        end = max(start + 0.001, float(timeline[right - 1].end))
        is_locked = any(a <= left and right <= b and flag for a, b, flag in locked)
        cues.append(SubtitleCue(len(cues) + 1, start, end, text, is_locked))
        left = right
    from .grouping import _bind_cue_speakers
    cues = _bind_cue_speakers(cues, segment_batch)
    from .segmentation_alignment import snap_internal_cue_boundaries
    cues = snap_internal_cue_boundaries(cues, segment_batch, firered_tokens, speech_regions)
    # A cue never claims seconds outside the rows its characters come from
    # (the same envelope cues_from_quality keeps for the other languages).
    spans, cursor = [], 0
    for segment in segment_batch:
        length = display_length(segment.text)
        spans.append((cursor, cursor + length, segment))
        cursor += length
    left = 0
    for cue, right in zip(cues, boundaries):
        owners = [segment for a, b, segment in spans if a < right and left < b] or [
            segment for a, b, segment in spans if a <= left <= b][:1]
        if owners:
            low, high = min(float(s.start) for s in owners), max(float(s.end) for s in owners)
            cue.start = max(low, min(float(cue.start), high - 0.001))
            cue.end = max(cue.start + 0.001, min(high, float(cue.end)))
        left = right
    return cues


# --- checking and local repair -----------------------------------------------------------------

@dataclass
class LineIssue:
    start: int
    end: int
    kind: str
    units: int
    seconds: float
    fixable: bool

    def to_dict(self):
        return dict(start=self.start, end=self.end, kind=self.kind, units=self.units,
                    seconds=round(self.seconds, 3), fixable=self.fixable)


def line_issues(boundaries, candidates: CandidateSet, timeline, *, hard_max, max_seconds) -> list[LineIssue]:
    """Lines over the length or duration limit; ``fixable`` when a legal cut exists inside."""
    issues, left = [], 0
    for right in boundaries:
        units = right - left
        seconds = piece_seconds(timeline, left, right)
        inner = [c for c in candidates.candidates if left < c < right]
        if units > hard_max:
            issues.append(LineIssue(left, right, "length", units, seconds, bool(inner)))
        elif seconds > max_seconds + 0.05 and inner and timing_is_evidence(units, seconds):
            # Duration is fixable only when a cut actually shortens the line:
            # a 25-second ASR window around eight characters is weak timing,
            # not a reason to chop the phrase.
            best = min(max(piece_seconds(timeline, left, c), piece_seconds(timeline, c, right)) for c in inner)
            issues.append(LineIssue(left, right, "duration", units, seconds,
                                    best < seconds - 0.5 and units >= 2 * SHORT_LINE))
        left = right
    return issues


def _fragment_edge(left_units, right_units, edge, candidates, pauses, preferred, merged_seconds, max_seconds):
    """A cut that leaves a short dependent piece the reader would rather see joined."""
    if edge in candidates.mandatory or edge in candidates.strong or pauses.get(edge, 0.0) >= 0.4:
        return False
    if min(left_units, right_units) >= SHORT_LINE or left_units + right_units > preferred:
        return False
    return merged_seconds <= max_seconds + 0.05 or not timing_is_evidence(left_units + right_units, merged_seconds)


def fragment_issues(boundaries, candidates: CandidateSet, timeline, *, preferred, max_seconds, pauses=None):
    """Runs of over-split short pieces (一生｜懸命｜やれば, 2026-11-25 live run)."""
    pauses = pauses or {}
    edges = [0, *boundaries]
    pieces = list(zip(edges, edges[1:]))
    issues, run = [], None
    for (a, b), (c, d) in zip(pieces, pieces[1:]):
        if _fragment_edge(b - a, d - c, b, candidates, pauses, preferred, piece_seconds(timeline, a, d), max_seconds):
            run = [run[0] if run else a, d]
        elif run:
            issues.append(LineIssue(run[0], run[1], "fragment", run[1] - run[0],
                                    piece_seconds(timeline, run[0], run[1]), True))
            run = None
    if run:
        issues.append(LineIssue(run[0], run[1], "fragment", run[1] - run[0],
                                piece_seconds(timeline, run[0], run[1]), True))
    return issues


def _replace_inside(boundaries, issue, cuts):
    return sorted({b for b in boundaries if not issue.start < b < issue.end} | set(cuts))


def _pause_seconds(segment_batch, firered_tokens):
    try:
        from .segmentation_alignment import firered_pause_character_gaps
        return dict(firered_pause_character_gaps(segment_batch, firered_tokens))
    except Exception:
        return {}


def local_split(left, right, candidates: CandidateSet, timeline, *, hard_max, preferred, max_seconds,
                pauses=None) -> list[int]:
    """Cheapest legal cuts inside [left, right] (dynamic programming over candidates)."""
    pauses = pauses or {}
    points = [left, *[c for c in candidates.candidates if left < c < right], right]
    strong = candidates.strong
    mandatory = set(candidates.mandatory)
    best = {left: (0.0, None)}
    for j, point in enumerate(points[1:], 1):
        options = []
        for i in range(j - 1, -1, -1):
            start = points[i]
            if start not in best:
                continue
            if any(start < m < point for m in mandatory):
                break
            units = point - start
            seconds = piece_seconds(timeline, start, point)
            cost = 0.0
            if units > hard_max:
                cost += 1000.0 + (units - hard_max) * 100.0
            if units > preferred:
                cost += (units - preferred) ** 2 * 0.5
            if units < SHORT_LINE and not (point in strong or point == right or pauses.get(point, 0) >= 0.4):
                cost += 40.0
            if seconds > max_seconds + 0.05 and timing_is_evidence(units, seconds):
                cost += 200.0 + (seconds - max_seconds) * 20.0
            if point in strong:
                cost -= 6.0
            cost -= min(4.0, pauses.get(point, 0.0) * 4.0)
            cost += 3.0     # every extra line has a reading cost
            options.append((best[start][0] + cost, start))
        if options:
            best[point] = min(options)
    cuts, point = [], right
    while point != left and point in best:
        cuts.append(point)
        point = best[point][1]
        if point is None:
            break
    return sorted(c for c in cuts if c != right)


# --- AI repair ---------------------------------------------------------------------------------

REPAIR_PROMPT = (
    "你是日语影视字幕编辑，修复少数几条未通过校验的日语字幕断句。只在windows内选择换字幕的位置，不改写、不翻译。"
    "每个window的marked_text是原文，‹N›是可以换字幕的位置，N为该window内之前的可计数字符数。"
    "problem说明这一条为什么不合格（length=超过字数上限；duration=超过时长上限；"
    "fragment=切得太碎：current_boundaries把不能独立成句的短片段单独成条，请与前后合并成完整意群，独立应答和呼唤可以保留）。"
    "请在合适的完整从句、语义转折或自然文节处换字幕，使每一条都不超过hard_max个可计数字符；"
    "推荐每条12～18字，不要切出两三个字的碎片，助词和助动词不得放在下一条开头，独立应答可以单独成条。"
    "must_keep里的位置必须保留。只输出JSON对象{\"windows\":[{\"id\":\"w1\",\"boundaries\":[N1,…,total_length]}]}，"
    "boundaries严格递增且最后一个等于该window的total_length，无Markdown或解释。")


def repair_messages(windows) -> list[dict]:
    return [{"role": "system", "content": REPAIR_PROMPT},
            {"role": "user", "content": json.dumps({"windows": windows}, ensure_ascii=False, separators=(",", ":"))}]


def _window_payload(window_id, issue, source_index, candidates: CandidateSet, *, hard_max, max_seconds,
                    boundaries=()):
    from .segmentation import marked_break_text
    left, right = issue.start, issue.end
    local = [c - left for c in candidates.candidates if left < c < right]
    raw = source_index.slice(left, right)
    return dict(id=window_id, marked_text=marked_break_text(raw, local + [right - left]),
                total_length=right - left,
                problem=dict(kind=issue.kind, units=issue.units, seconds=round(issue.seconds, 2),
                             hard_max=hard_max, max_seconds=max_seconds),
                must_keep=[m - left for m in candidates.mandatory if left < m < right],
                current_boundaries=[b - left for b in boundaries if left < b <= right],
                hard_max=hard_max, preferred=18)


def _parse_windows(content) -> dict:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            return {}
    rows = value.get("windows") if isinstance(value, dict) else None
    result = {}
    for row in rows or ():
        if isinstance(row, dict) and isinstance(row.get("boundaries"), list):
            result[str(row.get("id"))] = row["boundaries"]
    return result


def _valid_window_answer(values, issue, candidates, timeline, *, hard_max, max_seconds, preferred=18, pauses=None):
    left, right = issue.start, issue.end
    try:
        local = [int(v) for v in values]
    except (TypeError, ValueError):
        return None, "non_integer"
    if not local or local != sorted(set(local)) or local[-1] != right - left:
        return None, "not_strictly_increasing_or_wrong_total"
    legal = sorted(c for c in set(candidates.candidates) | {right} if left < c <= right)
    # A repair pick between marks moves to the nearest mark, like the first answer.
    absolute = sorted({min(legal, key=lambda m: (abs(m - (left + v)), -m)) for v in local})
    if absolute[-1] != right:
        return None, "off_candidate"
    if not {m for m in candidates.mandatory if left < m < right} <= set(absolute):
        return None, "mandatory_missing"
    cuts = [c for c in absolute if c != right]
    edges = [left, *cuts, right]
    for a, b in zip(edges, edges[1:]):
        if b - a > hard_max and any(a < c < b for c in candidates.candidates):
            return None, "still_over_length"
        if b - a < 2 and len(edges) > 2:
            return None, "fragment"
    if issue.kind == "duration" and len(edges) == 2:
        return None, "duration_not_split"
    if issue.kind == "fragment" and any(
            _fragment_edge(b - a, d - c, b, candidates, pauses or {}, preferred, piece_seconds(timeline, a, d),
                           max_seconds)
            for (a, b), (c, d) in zip(zip(edges, edges[1:]), zip(edges[1:], edges[2:]))):
        return None, "still_fragmented"
    return cuts, ""


def finalize_batch(segment_batch, model_boundaries, candidates: CandidateSet, *, firered_tokens=(),
                   speech_regions=(), hard_max=26, preferred=18, max_seconds=7.0, complete=None,
                   record=lambda *a, **k: None, batch_index=None, max_rounds=3):
    """Cues for one Japanese batch; never rejects the batch for a local line problem.

    ``complete(messages) -> str`` sends one targeted repair request (None: no AI repair).
    Returns (cues, receipt). Each cue gets ``grouping_origin``:
    ai_accepted | ai_targeted_correction | local_fallback_split | local_indivisible_retained.
    """
    from .grouping_quality import SourceIndex
    source_text = "".join(segment.text for segment in segment_batch)
    index = SourceIndex.build(source_text)
    timeline = _timeline(segment_batch, firered_tokens)
    boundaries, moves = snap(model_boundaries, candidates)
    pauses = _pause_seconds(segment_batch, firered_tokens)
    origins = {}          # piece end -> origin
    rejected = []
    rounds = 0
    seen_answers = set()
    def all_issues():
        return (line_issues(boundaries, candidates, timeline, hard_max=hard_max, max_seconds=max_seconds)
                + fragment_issues(boundaries, candidates, timeline, preferred=preferred, max_seconds=max_seconds,
                                  pauses=pauses))
    issues = all_issues()
    while complete is not None and rounds < max_rounds:
        fixable = [issue for issue in issues if issue.fixable]
        if not fixable:
            break
        rounds += 1
        windows = {f"w{n}": issue for n, issue in enumerate(fixable, 1)}
        payload = [_window_payload(key, issue, index, candidates, hard_max=hard_max, max_seconds=max_seconds,
                                   boundaries=boundaries)
                   for key, issue in windows.items()]
        try:
            answer = _parse_windows(complete(repair_messages(payload)))
        except Exception as error:   # the local repair below still runs
            record("japanese_grouping_repair_failed", batch_index=batch_index, round=rounds,
                   error=str(error)[:300], category=getattr(error, "category", type(error).__name__))
            break
        fingerprint = json.dumps(answer, sort_keys=True)
        if fingerprint in seen_answers:
            record("japanese_grouping_repair_repeated", batch_index=batch_index, round=rounds)
            break
        seen_answers.add(fingerprint)
        accepted_any = False
        for key, issue in windows.items():
            values = answer.get(key)
            if values is None:
                rejected.append(dict(round=rounds, window=issue.to_dict(), reason="missing_window"))
                continue
            cuts, reason = _valid_window_answer(values, issue, candidates, timeline, hard_max=hard_max,
                                                max_seconds=max_seconds, preferred=preferred, pauses=pauses)
            if cuts is None:
                rejected.append(dict(round=rounds, window=issue.to_dict(), reason=reason, answer=values[:40]))
                continue
            boundaries = _replace_inside(boundaries, issue, cuts)
            for end in [*cuts, issue.end]:
                origins[end] = "ai_targeted_correction"
            accepted_any = True
        issues = all_issues()
        if not accepted_any:
            break
    # What the model could not fix is split locally on legal candidates.
    for issue in [i for i in issues if i.fixable]:
        cuts = local_split(issue.start, issue.end, candidates, timeline, hard_max=hard_max,
                           preferred=preferred, max_seconds=max_seconds, pauses=pauses)
        if not cuts and issue.kind != "fragment":
            continue
        boundaries = _replace_inside(boundaries, issue, cuts)
        for end in [*cuts, issue.end]:
            origins[end] = "local_fallback_split"
    remaining = line_issues(boundaries, candidates, timeline, hard_max=hard_max, max_seconds=max_seconds)
    for issue in remaining:
        if issue.kind == "length":
            origins[issue.end] = "local_indivisible_retained"
    cues = cues_for(segment_batch, boundaries, firered_tokens, speech_regions)
    left = 0
    counts = dict(ai_accepted=0, ai_targeted_correction=0, local_fallback_split=0, local_indivisible_retained=0)
    for cue, right in zip(cues, boundaries):
        origin = origins.get(right, "ai_accepted")
        cue.grouping_origin = origin
        cue.grouping_boundary_receipt = dict(origin=origin, content_start=left, content_end=right,
                                             protocol=PROTOCOL,
                                             model_boundaries=[int(x) for x in model_boundaries
                                                               if isinstance(x, (int, float)) and left < x <= right],
                                             final_boundaries=[right])
        counts[origin] = counts.get(origin, 0) + 1
        left = right
    receipt = dict(candidates.receipt(), batch_index=batch_index, model_boundaries=list(model_boundaries)[:400],
                   final_boundaries=boundaries, snapped=moves, repair_rounds=rounds, rejected_repairs=rejected,
                   remaining_issues=[i.to_dict() for i in remaining], counts=counts, cues=len(cues))
    record("japanese_grouping_receipt", **receipt)
    return cues, receipt


def local_only(segment_batch, candidates: CandidateSet, *, firered_tokens=(), speech_regions=(), hard_max=26,
               preferred=18, max_seconds=7.0):
    """No usable AI answer: source boundaries plus legal local splits (labelled local)."""
    from .segmentation_alignment import source_segment_character_offsets
    source = sorted(set(source_segment_character_offsets(segment_batch)) | set(candidates.mandatory)
                    | {candidates.total})
    cues, receipt = finalize_batch(segment_batch, source, candidates, firered_tokens=firered_tokens,
                                   speech_regions=speech_regions, hard_max=hard_max, preferred=preferred,
                                   max_seconds=max_seconds, complete=None)
    for cue in cues:
        if cue.grouping_origin == "ai_accepted":
            cue.grouping_origin = "local_source_boundary"
            cue.grouping_boundary_receipt["origin"] = "local_source_boundary"
    return cues, receipt
