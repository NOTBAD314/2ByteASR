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

from .grouping_syntax import (
    INDEPENDENT_RESPONSES, PERSONAL_PRONOUNS, repeated_units, syntax_boundary_evidence,
)
from .text_rules import content_exact, display_length


def _dictionary_identity():
    import hashlib
    import jieba
    with jieba.get_dict_file() as dictionary:
        digest = hashlib.sha256(dictionary.read()).hexdigest()
    return dict(name='jieba', version=jieba.__version__, dictionary_sha256=digest)


from functools import lru_cache
_dictionary_identity = lru_cache(maxsize=1)(_dictionary_identity)

QUALITY_VERSION = "grouping-quality-v6-ai-owned-boundaries"
STANDALONE_RESPONSES = frozenset({'对撞', '不急', '等一下', '没错', '明白', '知道了', '好的', '对的', '是的', '好吧', '可以的'})


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
        from subtitle_core import MIN_SUBTITLE_SECONDS
        self.display_floor = min(self.min_seconds, MIN_SUBTITLE_SECONDS)
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
        self.confirmed_expressions = []
        self.soft_dependencies = set()
        self.semantic_required = set()
        self.independent_edges = set()
        self.source_ranges = set()
        self.source_edges = set()
        self.boundary_reasons = {edge: 'explicit_protected_boundary' for edge in self.required}
        self.estimated_ranges = []
        self.estimated_split_offsets = set()
        self.candidate_edges = set(self.required) | {self.total}
        self.syntax_reasons = {}
        self.syntax_spans = []
        self.tagged_tokens = []
        self.clause_edges = set()
        self.known_word_interiors = set()
        self.named_entity_interiors = set()
        self.named_component_interiors = set()
        self.inferred_word_interiors = set()
        self.explicit_word_interiors = set()
        self.pos_dependency_edges = set()
        completed_conditions = set()
        # Tokenize each protected turn separately. Concatenating overlapping
        # speakers must not manufacture a cross-speaker name or lexical word.
        start = 0
        for end in sorted(self.required | {self.total}):
            piece = self.index.slice(start, end)
            content = content_exact(piece)
            spans = boundary_word_spans(content)
            repeat_edges = set()
            self.candidate_edges.update(start+x for a,b,_ in spans for x in (a,b))
            local = set(lexical_forbidden_boundary_offsets(piece))
            self.explicit_word_interiors.update(start+x for x in local)
            has_numbers = bool(re.search(r"[0-9零〇一二两三四五六七八九十百千万亿]",piece))
            numeric_unsafe = numeric_unsafe_cut_offsets(piece) if has_numbers else set()
            local.update(numeric_unsafe)
            self.explicit_word_interiors.update(start+x for x in numeric_unsafe)
            import jieba
            for left, right, word in spans:
                local.update(range(left + 1, right))
                if jieba.dt.FREQ.get(word, 0):
                    self.known_word_interiors.update(start+x for x in range(left+1, right))
                else:
                    self.inferred_word_interiors.update(start+x for x in range(left+1, right))
            for repeat_start, repeat_end, unit in repeated_units(content):
                repeat_edges.update(range(repeat_start+len(unit), repeat_end, len(unit)))
                for unit_start in range(repeat_start, repeat_end, len(unit)):
                    local.update(range(unit_start+1, unit_start+len(unit)))
            removable_repeat_edges = {edge for edge in repeat_edges
                if start+edge not in self.known_word_interiors | self.explicit_word_interiors}
            local.difference_update(removable_repeat_edges)
            self.candidate_edges.update(start+edge for edge in repeat_edges)
            # Generic grammar units absent from a general-purpose word lexicon.
            patterns = (
                r"[这那哪每本此该](?:一|两|几|\d+)?[场个种次位条件项份台名届]",
                r"[上下前后](?:一|两|几|\d+)次",
                r"[一二三四五六七八九十\d]+代[团队机车]",
                r"(?:总体|整体|总的|综合|一般|相对)(?:来说|来讲|而言)",
                r"[男女][团队]",
                r"[\u3400-\u9fff]得(?=[\u3400-\u9fff])",
                r"等于是",
                r"(?:足够|充分|非常|更加)(?:信任|相信|了解|理解|支持|尊重)",
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
            token_cursor = start
            for token in tagged:
                self.tagged_tokens.append(dict(start=token_cursor, end=token_cursor+len(token.word),
                                               text=token.word, pos=token.flag))
                token_cursor += len(token.word)
            position = 0
            for i, token in enumerate(tagged):
                word_start, word_end = position, position+len(token.word)
                position = word_end
                if token.flag.startswith("nr"):
                    name_interiors = set(range(start+word_start+1,start+word_end))
                    name_interiors.difference_update(start+edge for edge in removable_repeat_edges)
                    self.forbidden.update(name_interiors)
                    self.named_entity_interiors.update(name_interiors)
                if i+1 >= len(tagged):
                    continue
                following = tagged[i+1]
                terminal = bool(re.search(r"[。！？!?]",local_index.slice(word_start,word_end)))
                if (following.word in PERSONAL_PRONOUNS and token.flag.startswith('a')
                        and i+2 < len(tagged) and tagged[i+2].flag[0] in 'vdap'):
                    self.independent_edges.add(start+word_end)
                if (token.flag.startswith('a') and following.flag.startswith('n')
                        and i and tagged[i-1].flag == 'd'
                        and any(t.word in PERSONAL_PRONOUNS for t in tagged[max(0, i-4):i])):
                    self.independent_edges.add(start+word_end)
                if (token.flag.startswith('nr') and following.flag.startswith('nr')
                        and word_end not in removable_repeat_edges
                        and not re.search(r'[\s，,、。！？!?]',local_index.slice(word_start,word_end))):
                    self.forbidden.add(start+word_end)
                    self.named_entity_interiors.add(start+word_end)
                    self.named_component_interiors.update(range(start+word_start+1,
                        start+word_end+len(following.word)))
                dependent = (token.flag in {"d","p","c"} and following.flag[0] in "vanrdmp")
                if token.word in {'其实','本来','原本'} and following.flag == 'p':
                    dependent = False
                    self.soft_dependencies.add(start+word_end)
                # Modal predicates and verb objects are not complete clauses.
                dependent = dependent or (token.word in {"可以","能够","必须","应该","需要"}
                    and following.flag.startswith("v"))
                dependent = dependent or (token.flag.startswith('v') and following.flag=='m'
                    and (i+2 < len(tagged) and tagged[i+2].flag=='q'
                         or len(following.word)>1 and following.word[-1] in '把个次位张块枚轮只'))
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
                    self.pos_dependency_edges.add(start+word_end)
                    if token.flag=="c":
                        self.restarts.add(start+word_start)
                if (not terminal and (token.flag.startswith("n") or token.flag=="r")
                        and (following.flag[0] in "dvtr" or following.word in {"还是","就是","也是","应该","可能","需要","能够"})
                        and self.pauses.get(start+word_end,0.) < .18):
                    self.soft_dependencies.add(start+word_end)
            phrase_spans, clauses, conditions = syntax_boundary_evidence(local_index, self.max_chars)
            for left, right, reason in phrase_spans:
                self.syntax_spans.append((start+left, start+right, reason))
                for cut in range(start+left+1, start+right):
                    self.forbidden.add(cut)
                    self.syntax_reasons[cut] = reason
            self.clause_edges.update(start+edge for edge in clauses)
            completed_conditions.update(start+edge for edge in conditions)
            start = end
        self.forbidden.difference_update(completed_conditions-self.known_word_interiors-self.explicit_word_interiors)
        self.soft_dependencies.difference_update(self.clause_edges)
        self.forbidden.difference_update(self.required)
        from .segmentation_profiles import legal_raw_boundaries
        raw_allowed = legal_raw_boundaries(text, 'zh') | {len(text)}
        self.forbidden.update(edge for edge in range(1, self.total)
                              if self.index.raw_edges[edge] not in raw_allowed)
        self.candidate_edges.update(self.restarts | self.semantic_required | set(self.pauses))
        self.candidate_edges.update(self.clause_edges)
        self.allowed = sorted(set(range(1, self.total+1)) - self.forbidden)

    def duration(self, start, end):
        if not self.units:
            return 0.
        return max(0., self.units[end-1].end-self.units[start].start)

    def independent_expression(self, start, end):
        text = self.index.content[start:end]
        return (text in STANDALONE_RESPONSES
                or bool(re.fullmatch(r'[对嗯哎诶哦啊呀唉好是行]+', text or ' ')))

    def can_join(self, start, cut, end):
        """Only optional cuts in one readable continuous expression can go."""
        if cut in self.required | self.semantic_required | self.independent_edges or end-start > self.max_chars:
            return False
        if self.units and self.duration(start, end) > self.max_seconds+.05:
            return False
        if (self.independent_expression(start, cut) or self.independent_expression(cut, end)
                or re.search(r'[。！？!?]', self.index.slice(start, cut))):
            return False
        # A new explicit subject in an already complete clause is evidence of
        # an independent sentence. A connective alone is not such evidence.
        following = self.index.content[cut:end]
        import jieba.posseg as posseg
        tagged = list(posseg.cut(following))
        if (tagged and tagged[0].flag.startswith('n')
                and any(token.flag[0] in 'va' for token in tagged[1:4])
                and cut not in self.forbidden | self.awkward):
            return False
        if re.match(r'(?:我|你|他|她|我们|你们|他们)', following) and cut not in self.forbidden | self.awkward:
            return False
        # A new deictic/causative clause belongs to its right-hand predicate.
        # The next cue may currently contain only its opening words.
        right_context = self.index.content[cut:min(self.total, end+16)]
        if re.match(r'(?:这里|这边|那里|那边)(?:就|是)|并且|让(?:我|你|他|她|我们|你们|他们)', right_context):
            return False
        if cut in self.forbidden | self.awkward | self.soft_dependencies:
            return True
        left_text = self.index.content[start:cut]
        left_tokens = list(posseg.cut(left_text))
        if not left_tokens or not tagged:
            return False
        tail, head = left_tokens[-1], tagged[0]
        # Positive attachment evidence: modifier/head, predicate/object, or
        # successive actions sharing an implicit subject. Adjacency and spare
        # character capacity alone never justify joining two expressions.
        if tail.word in {'的', '得', '地', '把', '被'}:
            return True
        if tail.flag.startswith('v') and head.flag.startswith(('n', 'r')):
            return True
        if tail.word == '没有' and any(t.flag.startswith('n') for t in tagged):
            return True
        if tail.flag.startswith('v') and re.match(r'(?:到|往|向|回)(?:前|后|上|下|左|右|家|里|外|这|那)', following):
            return True
        if tail.flag in {'d', 'p', 'c'} and head.flag.startswith(('v', 'a', 'n', 'r')):
            return True
        if tail.word in {'来说','而言','来讲'} and head.flag.startswith(('a','d')):
            return True
        return bool(re.match(r'然后(?=.{1,12})', following)
                    and (any(t.flag.startswith('v') for t in left_tokens)
                         or tail.word in {'过去','回来','回去','上来','下来','上去','下去'}))

    def explain_boundary(self, edge):
        """Observable evidence, with soft guesses kept separate from locks."""
        reasons = []
        for name, offsets in (
                ('dictionary_word', self.known_word_interiors),
                ('explicit_term_or_number', self.explicit_word_interiors),
                ('inferred_token', self.inferred_word_interiors),
                ('pos_dependency', self.pos_dependency_edges),
                ('clause_start', self.clause_edges), ('source_edge', self.source_edges)):
            if edge in offsets:
                reasons.append(name)
        return dict(offset=edge, left=self.index.slice(max(0,edge-16),edge),
            right=self.index.slice(edge,min(self.total,edge+16)),
            hard=edge in self.required, allowed=edge not in self.forbidden,
            reasons=reasons, syntax=[dict(start=a,end=b,reason=r) for a,b,r in self.syntax_spans if a < edge < b],
            pause_seconds=self.pauses.get(edge), boundary_origin=self.boundary_reasons.get(edge))

    def tokenizer_identity(self):
        import hashlib
        import json
        from .segmentation import lexical_boundary_terms
        return dict(_dictionary_identity(), protected_terms_sha256=hashlib.sha256(
            json.dumps(sorted(lexical_boundary_terms()),ensure_ascii=False).encode('utf-8')).hexdigest())

    def dependent_fragment(self, start, end):
        # This is a contextual span check, not a minimum cue length or a list
        # of banned answers. A separate 去吗？ has no crossing dependency.
        return (0 < end-start <= 4 and any(
            a < edge < b for a,b,_ in self.syntax_spans for edge in (start,end)
            if edge not in self.required))

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
        edges = [0, *boundaries]
        for start, cut, end in zip(edges, edges[1:], edges[2:]):
            if self.can_join(start, cut, end):
                issues.append(dict(kind='unnecessary_boundary', start=cut, end=cut,
                                   reason='complete_expression_within_limit'))
        start = 0
        for end in boundaries:
            if end in self.forbidden:
                issue = dict(kind="semantic_boundary", start=end, end=end)
                if end in self.syntax_reasons:
                    issue['reason'] = self.syntax_reasons[end]
                issues.append(issue)
            elif end in self.awkward and end not in self.required:
                issues.append(dict(kind="semantic_cohesion", start=end, end=end))
            if end-start > self.max_chars:
                issues.append(dict(kind="length", start=start, end=end, length=end-start))
            duration = self.duration(start, end)
            if self.units and duration > self.max_seconds+.05:
                issues.append(dict(kind="duration", start=start, end=end, seconds=duration))
            if (self.units and duration < self.display_floor-1e-6
                    and not self.independent_short(start, end)
                    and (start not in self.required or end not in self.required)
                    and len(boundaries) > 1):
                issues.append(dict(kind="short_tail", start=start, end=end))
            if (end-start == 1 and not self.independent_short(start,end)
                    and (start not in self.required or end not in self.required)):
                issues.append(dict(kind='dependent_fragment',start=start,end=end))
            if self.dependent_quantity(start,end):
                issues.append(dict(kind='dependent_fragment',start=start,end=end))
            elif self.dependent_fragment(start,end):
                issues.append(dict(kind='dependent_fragment',start=start,end=end))
            if end in self.estimated_split_offsets:
                issues.append(dict(kind="estimated_source_split", start=end, end=end))
            start = end
        return issues

    def independent_short(self, start, end):
        """A complete short source or reaction is evidence, not a length target."""
        if (start,end) in self.source_ranges:
            return True
        text = self.index.content[start:end]
        if text in INDEPENDENT_RESPONSES:
            return True
        if re.fullmatch(r"[对嗯哎诶哦啊呀唉好是行]+", text or " "):
            return True
        return bool(re.search(r"[。！？!?]",self.index.slice(start,end)))

    def dependent_quantity(self,start,end):
        return bool(start and start not in self.required and not self.independent_short(start,end)
            and self.pauses.get(start,0.) < .35 and re.fullmatch(
                r'[零〇一二两三四五六七八九十百千万亿\d]+(?:个|把|次|位|张|块|枚)',self.index.content[start:end]))

    def new_single_character_has_evidence(self, start, end, original):
        if end-start != 1 or (start, end) in self.source_ranges:
            return True
        if start in original | {0} and end in original:
            return True
        return self.pauses.get(start, 0.) >= .18 or self.pauses.get(end, 0.) >= .18

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
        internal = sorted(x for x in original if left < x < right)
        if (right-left <= self.max_chars and self.duration(left, right) <= self.max_seconds+.05
                and not any(left < x < right for x in self.required | self.semantic_required | self.independent_edges | set(fixed))
                and all(self.can_join(left, cut, right) for cut in internal)):
            return [right]
        points = [left, *(x for x in self.allowed if left < x < right
                         and (x in original or x in self.candidate_edges)
                         and not any(a < x < b for a,b in self.confirmed_expressions)), right]
        scores, previous = {left: 0.}, {}
        required = sorted(x for x in self.required | self.semantic_required | set(fixed) if left < x < right)
        required = sorted(set(required) | {x for x in self.independent_edges if left < x < right})
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
                if self.dependent_quantity(start,end):
                    continue
                if self.dependent_fragment(start,end):
                    continue
                if not self.new_single_character_has_evidence(start, end, original):
                    continue
                if self.units and duration > self.max_seconds+.05 and not relax_time:
                    continue
                if (self.units and duration < self.display_floor-1e-6
                        and not self.independent_short(start, end)
                        and (start not in original | {left} or end not in original)
                        and not relax_time):
                    continue
                cost = 20.  # Optional breaths never pay for extra short cues.
                if (self.units and duration < self.display_floor
                        and not self.independent_short(start,end)):
                    cost += 30. + 20.*(self.min_seconds-duration)**2
                cost += 500.*max(0, length-self.max_chars)**2
                cost += 25.*max(0., duration-self.max_seconds)**2
                if end < right:
                    cost += 25. if end in self.awkward else 0.
                    cost += 14. if end in self.soft_dependencies else 0.
                    cost += -2. if end in original else 2.
                    cost -= 1. if end in self.source_edges else 0.
                    cost -= min(3.5, self.pauses.get(end, 0.)*10.)
                    cost -= 2. if end in self.restarts else 0.
                    cost -= 6. if end in self.clause_edges else 0.
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
        result = list(boundaries)
        while True:
            # Newly adjacent expressions can change attachment evidence. A
            # fixed point must survive a fresh quality object as well as a
            # second pass on this instance.
            self.confirmed_expressions = self.complete_expressions(result)
            final, issues = self._repair_pass(result, record=record, rule=rule)
            if final == result:
                return final, issues
            # Every accepted pass strictly improves inspect's quality tuple.
            # Reevaluate newly adjacent cues within this call for idempotency.
            result = final

    def complete_expressions(self, boundaries):
        """Protect a baseline only when its context supports completeness."""
        import jieba.posseg as posseg
        confirmed = []
        edges = [0, *boundaries]
        for number, (start,end) in enumerate(zip(edges,edges[1:])):
            if end-start > self.max_chars or self.duration(start,end) > self.max_seconds+.05:
                continue
            if any(start < edge < end for edge in self.required | self.semantic_required):
                continue
            if (start in self.forbidden or end in self.forbidden
                    or self.dependent_fragment(start,end)):
                continue
            if number and self.can_join(edges[number-1],start,end):
                continue
            if number+2 < len(edges) and self.can_join(start,end,edges[number+2]):
                continue
            text = self.index.content[start:end]
            if re.search(r'(?:的|得|地|把|被|能够|可以|必须|应该|需要|就是|也是|是|会|要)$',text):
                continue
            if (self.independent_expression(start,end)
                    or any(t.flag.startswith(('v','a')) for t in posseg.cut(text))):
                confirmed.append((start,end))
        return confirmed

    def _repair_pass(self, boundaries, *, record=None, rule="quality_local_window"):
        original = list(boundaries)
        issues = self.inspect(original)
        unstable = self.forbidden | self.awkward | self.soft_dependencies
        unstable = unstable | {edge for issue in issues if issue['kind'] in {'short_tail','dependent_fragment'}
                               for edge in (issue['start'],issue['end'])
                               if edge not in self.source_edges}
        unstable.update(issue['start'] for issue in issues if issue['kind']=='estimated_source_split')
        unstable.update(issue['start'] for issue in issues if issue['kind']=='unnecessary_boundary')
        unstable.difference_update(edge for span in self.confirmed_expressions for edge in span)
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
            proposed = sorted((result-set(before)) | set(candidate))
            if accepted and proposed != sorted(result) and not self.improves(sorted(result),proposed):
                accepted, rejection = False, "no_quality_improvement_retained"
            if record and candidate != before:
                old_edges, new_edges = set(before), set(candidate)
                record("grouping_boundary_move", rule=rule, accepted=accepted,
                    reason=reason if accepted else rejection, content_start=left, content_end=right,
                    old_positions=before, new_positions=candidate,
                    removed_positions=sorted(old_edges-new_edges), added_positions=sorted(new_edges-old_edges),
                    removed_reasons={str(edge): 'complete_expression_within_limit' for edge in old_edges-new_edges
                                     if any(i['kind']=='unnecessary_boundary' and i['start']==edge for i in issues)},
                    protected_reasons=self.boundary_reasons,
                    removed_evidence=[self.explain_boundary(edge) for edge in sorted(old_edges-new_edges)],
                    added_evidence=[self.explain_boundary(edge) for edge in sorted(new_edges-old_edges)],
                    quality_before=self.inspect(sorted(result)), quality_after=self.inspect(proposed),
                    before=self.index.pieces([left, *before])[1:] if left else self.index.pieces(before),
                    after=[self.index.slice(a,b) for a,b in zip([left,*candidate],candidate)])
            if accepted:
                result.difference_update(before)
                result.update(candidate)
        final = sorted(result)
        return final, self.inspect(final)

    def improves(self, before, after):
        old, new = self.inspect(before), self.inspect(after)
        # Semantic damage is never compensated by fewer/longer subtitles.
        severe = {"semantic_boundary","semantic_cohesion","protected_boundary_missing",
                  "connective_ownership","estimated_source_split","dependent_fragment"}
        def score(issues):
            return (sum(i['kind'] in severe for i in issues),
                    sum(i['kind'] in {'length','duration'} for i in issues), len(issues))
        return score(new) < score(old)

    def accept_change(self, before, after, *, preserve_stable=True):
        if (self.required-set(after)) - set(self.required-set(before)):
            return False, "protected_boundary_missing"
        if preserve_stable and not self.stable_boundaries.issubset(after):
            return False, "valid_model_boundary_changed"
        if (self.semantic_required-set(after)) - set(self.semantic_required-set(before)):
            return False, "connective_ownership_changed"
        old_bad = set(before) & self.forbidden
        new_bad = set(after) & self.forbidden
        if new_bad-old_bad:
            return False, "new_word_or_connective_damage"
        if (set(after) & self.awkward) - set(before):
            return False, "new_syntactic_damage"
        if any(a < edge < b for edge in set(after)-set(before) for a,b in self.confirmed_expressions):
            return False, 'complete_expression_regression'
        # A lone POS-based subject/predicate preference is a cost in the
        # solver, not an absolute ban on otherwise understandable clauses.
        old_issues, new_issues = self.inspect(before), self.inspect(after)
        for kind in ("length","duration","short_tail","estimated_source_split","dependent_fragment"):
            if sum(i['kind']==kind for i in new_issues)>sum(i['kind']==kind for i in old_issues):
                return False, "new_"+kind+"_conflict"
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
        independent_response = any(
            content_exact(item.text) in STANDALONE_RESPONSES
            or re.fullmatch(r'[对嗯哎诶哦啊呀唉好是行]+', content_exact(item.text) or ' ')
            for item in (left, right))
        if (left.speaker != right.speaker or right.start-left.end > 2.
                or right.start < left.end-.001
                or left.caption_arbitration.get('protected_end')
                or right.caption_arbitration.get('protected_start') or independent_response):
            required.add(cursor)
    units, cursor = [], 0
    pauses = firered_pause_character_gaps(segments, tokens)
    native_long_pauses = set()
    for segment in segments:
        private = copy.copy(segment)
        private.caption_arbitration = copy.deepcopy(segment.caption_arbitration)
        private.words = [w for w in segment.words if
            math.isfinite(w.start) and math.isfinite(w.end)
            and segment.start <= w.start < w.end <= segment.end+.001]
        units.extend(segment_content_timeline(private,tokens))
        evidence = segment.caption_arbitration.get('word_timing', {})
        if (evidence.get('basis') in {'aligner_words', 'provider_words'}
                or segment.caption_arbitration.get('timing_evidence', {}).get('independent_acoustic')):
            measured = private.words
            if ''.join(content_exact(w.text) for w in measured) == content_exact(segment.text):
                offset = cursor
                for left_word, right_word in zip(measured, measured[1:]):
                    offset += display_length(left_word.text)
                    gap = right_word.start-left_word.end
                    if gap >= .18:
                        pauses[offset] = max(pauses.get(offset, 0.), gap)
                        if gap >= 3.:
                            required.add(offset)
                            native_long_pauses.add(offset)
        cursor += display_length(segment.text)
    quality = BoundaryQuality("".join(s.text for s in segments), units=units,
                              required=required, pauses=pauses)
    quality.boundary_reasons.update({edge: 'measured_long_silence' for edge in native_long_pauses})
    cursor = 0
    for left, right in zip(segments, segments[1:]):
        cursor += display_length(left.text)
        if cursor in quality.required:
            quality.boundary_reasons[cursor] = (
                'speaker_change' if left.speaker != right.speaker else
                'overlapping_source' if right.start < left.end-.001 else
                'manual_protected_cut' if left.caption_arbitration.get('protected_end') or right.caption_arbitration.get('protected_start') else
                'source_gap_or_independent_turn')
        else:
            quality.boundary_reasons[cursor] = 'optional_source_chunk'
        # Separate complete source expressions plus a fresh causative actor
        # can disambiguate a cross-source /d + /v guess (并肩 | 让我们…).
        # This does not lock arbitrary short ASR chunks or remove real words.
        if (cursor not in quality.required and 4 <= display_length(left.text) <= quality.max_chars
                and display_length(right.text) <= quality.max_chars
                and re.match(r'(?:让|请)(?:我|你|他|她|我们|你们|他们)', content_exact(right.text))
                and not re.search(r'(?:想|要|能|会|继续|开始)$', content_exact(left.text))
                and cursor in quality.pos_dependency_edges
                and cursor not in quality.known_word_interiors | quality.explicit_word_interiors | set(quality.syntax_reasons)):
            quality.forbidden.discard(cursor)
            quality.pos_dependency_edges.discard(cursor)
            quality.independent_edges.add(cursor)
            quality.clause_edges.add(cursor)
            quality.boundary_reasons[cursor] = 'source_expression_with_new_actor'
    cursor = 0
    for segment in segments:
        end = cursor+len(content_exact(segment.text))
        quality.source_ranges.add((cursor,end))
        quality.source_edges.update((cursor,end))
        # Inspect verb/object attachment within the actual source utterance.
        # Concatenating two utterances can otherwise mistake 信任 | 我跟你说
        # for a verb followed by its object.
        import jieba.posseg as posseg
        tagged=list(posseg.cut(content_exact(segment.text)))
        position=cursor
        for token,following in zip(tagged,tagged[1:]):
            position+=len(token.word)
            if (token.flag.startswith('v') and token.word not in {'说','讲','问','可以','能够','必须','应该','需要','能','会','要'}
                    and following.word in PERSONAL_PRONOUNS
                    and position not in quality.clause_edges
                    and quality.pauses.get(position,0.)<.35):
                quality.forbidden.add(position)
        evidence = segment.caption_arbitration.get("word_timing", {})
        if evidence.get("basis") == "uniform_display_estimate":
            quality.estimated_ranges.append((cursor,end))
            if end-cursor<=quality.max_chars and quality.duration(cursor,end)<2*quality.display_floor:
                quality.estimated_split_offsets.update(range(cursor+1,end))
        words = evidence.get("measured_words", ())
        if evidence.get("basis") != "uniform_display_estimate":
            content = content_exact(segment.text)
            position = 0
            for word in words:
                value = content_exact(word.get("text", ""))
                found = content.find(value,position) if value else -1
                if found >= 0:
                    # Provider/alignment blocks can contain several lexical
                    # words. They constrain timing; the lexical analyser owns
                    # indivisibility. An interior cue endpoint is estimated
                    # unless its own word observation can substantiate it.
                    position = found+len(value)
        cursor += display_length(segment.text)
    # A pronoun at the end of a real utterance may be an object (相信他),
    # and 把 in 一把 is a measure word. The generic suffix heuristic cannot
    # overrule an intact source edge; actual lexical violations still apply.
    quality.awkward.difference_update(quality.source_edges-quality.forbidden)
    quality.candidate_edges.update(quality.source_edges)
    # Dictionary words and explicit grammatical dependencies remain stronger
    # than source edges. An unknown HMM word alone cannot overrule them.
    reliable_interiors = (quality.known_word_interiors | quality.named_component_interiors
                          | quality.explicit_word_interiors | quality.pos_dependency_edges
                          | set(quality.syntax_reasons))
    quality.forbidden.difference_update((quality.source_edges & quality.inferred_word_interiors)-reliable_interiors)
    quality.awkward.difference_update(quality.source_edges-quality.forbidden)
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


def cues_from_quality(segments, boundaries, tokens=(), *, protected=(), record=None, repair=True):
    from ..recognition.transcript_data import SubtitleCue
    quality = quality_for_segments(segments, tokens, protected=protected)
    if repair:
        final, issues = quality.repair(boundaries, record=record)
    else:
        from .ai_boundary_policy import inspect
        final, issues = list(boundaries), inspect(quality,boundaries)
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
