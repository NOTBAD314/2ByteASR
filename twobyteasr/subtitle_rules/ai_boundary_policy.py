"""AI boundary acceptance: hard validation and strictly owned repair windows.

Two layers (2026-11-18):

* Hard constraints decide acceptance or retention of the original source: protected
  boundaries, explicit terms/numbers, and the character limit.
* Advisory risks only send a window back to the AI for a bounded second look:
  a cut inside a dictionary word, a named entity or a grammatical dependency
  (的|名词, 也|可以, 两个|快捷键, 说话|人, 记得|在…), and a short tail that
  depends on the previous cue. When the AI keeps its answer, or no request is
  available, the AI boundary stays. Local POS guesses never overrule it.
"""
import math
import re

from .grouping_contract import validate_boundary_offsets

HARD_KINDS = frozenset({'protected_boundary_missing', 'semantic_boundary', 'length',
                        'incomplete_expression', 'excessive_fragmentation'})
ADVISORY_KINDS = frozenset({'word_or_dependency_split', 'dependent_tail', 'dependent_opener', 'fragmented',
                            'dangling_edge'})

# 2026-11-22 (real DeepSeek run on the 崩铁 report: no line over 14, but
# 无敌的｜飞飞狐, 让我们在这场｜本该, 上演一出｜漂亮的, 被他吞下｜后,
# 如你们所见他｜对这片银河, 这些都不重要因为｜在受罪…). A line that stops on
# the word whose head or object is on the next line. Advisory: the window goes
# back to the AI and its best answer prefers fewer of these; nothing moves locally.
DANGLING_CONJUNCTIONS = frozenset({
    '因为', '所以', '但是', '但', '而且', '而', '如果', '虽然', '并且', '或者', '不过', '可是', '然后',
    '只要', '只有', '除非', '即使', '尽管', '无论', '不管', '既然', '和', '跟', '与', '及', '以及'})
DANGLING_PREPOSITIONS = frozenset({'把', '被', '让', '给', '对', '向', '往', '从', '比', '用', '将', '由',
                                   '对于', '关于', '朝', '替'})
LOCALIZER_OPENERS = frozenset('后前里中内外上下')
_MEASURE_TAILS = frozenset('个条位张块枚轮只次本部件项份台名届种套款把支首段句集期页步回场出些')
_NEW_CLAUSE_POS = ('r', 'c', 'p', 'd', 't', 'y', 'e', 'o', 'u', 'w', 'x', 'm')
_SUBJECT_PRONOUNS = frozenset({'我', '你', '他', '她', '它'})
# What follows a subject left at the end of a line (你｜会这么容易, 他｜对这片银河);
# an ordinary verb after it is usually a new clause (这杯敬你｜说说).
_SUBJECT_FOLLOWERS = frozenset({'会', '能', '要', '就', '都', '也', '还', '才', '对', '把', '被', '可以',
                                '已经', '一直', '却', '并', '竟然', '必须', '应该', '得'})
_ADVERBIAL_MEASURES = frozenset({'一些', '一点', '一下', '一样', '有些', '一点儿', '一会', '一会儿'})
# Verbs that close a clause before a new subject (我觉得｜阿布…, 你看｜弹幕).
_CLAUSE_FINAL_VERBS = frozenset({'说', '觉得', '知道', '看', '想', '感觉', '发现', '听', '以为', '认为', '好像',
                                 '比如说', '是不是', '对不对', '有没有', '行', '好', '来', '走', '去', '吧'})
_HEDGE_ADVERBS = frozenset({'可能', '也许', '大概', '估计', '其实', '一定', '肯定', '真的', '已经', '还是', '就是'})
_LOCALIZER_WORDS = frozenset({'之后', '之前', '以后', '以前', '之间', '之内', '以内', '以上', '以下'})
_DIRECTIONAL_OPENERS = frozenset({'出来', '起来', '进去', '出去', '上来', '下来', '下去', '上去', '进来',
                                  '回来', '回去', '过来', '过去'})


def _token_maps(quality):
    cached = getattr(quality, '_dangling_token_maps', None)
    if cached is None:
        tokens = getattr(quality, 'tagged_tokens', ()) or ()
        cached = ({t['end']: t for t in tokens}, {t['start']: t for t in tokens})
        try:
            quality._dangling_token_maps = cached
        except AttributeError:
            pass
    return cached


def dangling_edges(quality, boundaries):
    """Advisory ``dangling_edge`` issues: a line ends on a word that needs the next line."""
    ends, starts = _token_maps(quality)
    if not ends:
        return []
    issues = []
    for edge in boundaries:
        if edge >= quality.total or edge in quality.required or quality.pauses.get(edge, 0) >= .45:
            continue
        left_raw = quality.index.text[:quality.index.raw_edges[edge]].rstrip()
        if left_raw.endswith(('。', '！', '？', '，', '、', '.', '!', '?', ',', '；', ';', '…', '：', ':')):
            continue
        from .grouping_quality_request import pause_space
        if pause_space(quality.index.text, quality.index.raw_edges[edge]):
            continue  # a marked pause (2026-11-22) is a clause edge
        left, right = ends.get(edge), starts.get(edge)
        if left is None or right is None:
            continue
        lw, lp, rw, rp = left['text'], left['pos'], right['text'], right['pos']
        reason = None
        if (lw in ('的', '地') and lp.startswith('u')
                and (rp.startswith('n') or rp in ('vn', 'an', 'a', 'b'))):
            reason = 'modifier_without_head'
        elif lw in DANGLING_CONJUNCTIONS:
            reason = 'conjunction_at_line_end'
        elif lw in DANGLING_PREPOSITIONS and lp.startswith('p') and not rw.startswith(('不', '没')):
            reason = 'preposition_at_line_end'
        elif (lp in ('m', 'mq', 'q') and len(lw) >= 2 and lw[-1] in _MEASURE_TAILS
              and lw not in _ADVERBIAL_MEASURES
              and not rp.startswith(('r', 'c', 'p', 't', 'y', 'e', 'o', 'u', 'w', 'x'))):
            reason = 'measure_without_noun'
        elif rw in LOCALIZER_OPENERS and rp.startswith('f'):
            reason = 'localizer_opener'
        elif lw in _SUBJECT_PRONOUNS and lp.startswith('r') and rw in _SUBJECT_FOLLOWERS:
            reason = 'subject_at_line_end'
        # 2026-11-22 (real DeepSeek reruns of the 1 h stream): the reference cut
        # and the AI copied it at 或者是使用｜幸运大转盘, 不管是开｜buff,
        # 阿布现在是｜80 级, 我们一定是｜比他快, 他带了一个｜什么防防御技能,
        # 他打死｜之后, 食尘短绒｜出来.
        elif (lp.startswith('v') and rp.startswith(('n', 'm', 'eng')) and lw not in _CLAUSE_FINAL_VERBS
              and not lw.endswith(('了', '过', '着'))):
            reason = 'verb_object_split'
        elif lw == '是' and lp.startswith('v') and not rp.startswith(('y', 'c', 'e', 'o', 'w', 'x')):
            reason = 'copula_at_line_end'
        elif lw in _HEDGE_ADVERBS and not rp.startswith(('y', 'c', 'e', 'o', 'w', 'x', 'r')):
            reason = 'adverb_at_line_end'      # 我觉得可能｜是第一把
        elif (lp in ('m', 'mq', 'q') and lw[-1:] in _MEASURE_TAILS and lw not in _ADVERBIAL_MEASURES
              and not rp.startswith(('c', 'y', 'e', 'o', 'w', 'x'))):
            reason = 'measure_without_noun'
        elif rw in _LOCALIZER_WORDS:
            reason = 'localizer_opener'
        elif rw in _DIRECTIONAL_OPENERS and lp.startswith(('n', 'v', 'r')):
            reason = 'complement_opener'
        if reason:
            issues.append(dict(kind='dangling_edge', start=edge, end=edge, reason=reason))
    return issues
# 2026-11-22 (user, 4 h stream, Qwen Audio 3.1 + DeepSeek flash): 1,370 window
# corrections were logged "improved" while splitting phrases no local check
# saw: 联系不上｜你我担心你, 永远陪着｜你如果你愿意, 应该是住｜在对门,
# 红包中了会｜有人, 这里是梦大家｜讨论的时候, 过了｜段时间, 您所｜拨打,
# 杀不｜掉的. Each fixed an over-long line (a hard issue), so the gate let
# them through. These are hard now: the answer goes back to the AI.
_POTENTIAL_COMPLEMENTS = frozenset('上下掉到完动起住懂见着出开走过来去清好通透满')
_POSTURE_VERBS = frozenset('住睡坐站躺放摆挂写停落留待呆藏躲关贴装堆种埋扔丢印刻')
_OBJECT_PRONOUNS = frozenset({'你', '我', '他', '她', '它', '你们', '我们', '他们', '她们', '咱们'})
_PLURAL_SUBJECTS = frozenset({'大家', '我们', '你们', '他们', '她们', '咱们'})
_LINE_END_MODALS = frozenset({'会', '能', '可以', '应该', '要', '敢', '肯'})
_ASPECT_AFTER_VERB = frozenset({'着', '了', '过'})


def phrase_split(quality, edge):
    """Why a cut at ``edge`` separates words that read as one phrase, or None."""
    ends, starts = _token_maps(quality)
    left, right = ends.get(edge), starts.get(edge)
    interiors = getattr(quality, '_complement_interiors', None)
    if interiors is None:
        interiors = {x for t in getattr(quality, 'tagged_tokens', ()) or () if _potential_complement(t['text'])
                     for x in range(t['start']+1, t['end'])}
        try:
            quality._complement_interiors = interiors
        except AttributeError:
            pass
    if edge in interiors:
        return 'potential_complement_split'          # 杀不｜掉, 联系不｜上
    if left is None or right is None:
        return None
    lw, lp, rw, rp = left['text'], left['pos'], right['text'], right['pos']
    after = starts.get(right['end'])
    if _potential_complement(rw) and lp.startswith(('v', 'n')):
        return 'potential_complement_split'          # 联系｜不上, 杀｜不掉
    if lw == '所' and lp.startswith('u') and rp.startswith('v'):
        return 'suo_before_verb'                     # 您所｜拨打
    if lw in _POSTURE_VERBS and lp.startswith('v') and rw in ('在', '到'):
        return 'verb_and_place_split'                # 住｜在对门
    if (rw in _OBJECT_PRONOUNS and rp.startswith('r')
            and (lp.startswith('v') or lw in _ASPECT_AFTER_VERB and lp.startswith('u'))
            and (after is None or after['text'] in _OBJECT_PRONOUNS or after['pos'].startswith(('c', 'w', 'y')))):
        return 'object_pronoun_split'                # 陪着｜你如果, 联系不上｜你我
    if lw in _LINE_END_MODALS and lp.startswith('v') and not rp.startswith(('c', 'y', 'e', 'o', 'w', 'x')):
        before = ends.get(left['start'])
        if not (before and before['text'] in ('不', '没', '没有', '才')):
            return 'modal_at_line_end'               # 红包中了会｜有人
    if lw in _PLURAL_SUBJECTS and rp.startswith(('v', 'd')):
        return 'subject_at_line_end'                 # 这里是梦大家｜讨论的时候
    if (lw in ('了', '过') or lp.startswith('m')) and rw[:1] in _MEASURE_TAILS and len(rw) > 1:
        return 'measure_opener'                      # 过了｜段时间
    return None


def _potential_complement(text):
    return (len(text) == 2 and text[0] == '不' and text[1] in _POTENTIAL_COMPLEMENTS
            or len(text) == 3 and text[0] == '不' and text[1:] in _DIRECTIONAL_PAIRS)


_DIRECTIONAL_PAIRS = frozenset({'出来', '起来', '进去', '出去', '上来', '下来', '下去', '上去',
                                '进来', '回来', '回去', '过来', '过去'})


# Particles that complete the previous words (来自星穹铁道｜的客人).
DEPENDENT_OPENERS = frozenset('了的得地着过吗呢吧么嘛')


def _dependent_opener(quality, edge):
    """A line that opens with a particle completing the previous line; 的确/地刺/过来 are words."""
    content = quality.index.content
    return (edge < len(content) and content[edge] in DEPENDENT_OPENERS and edge in quality.awkward
            and edge not in quality.required
            and edge+1 not in getattr(quality, 'known_word_interiors', ()))


def length_cost(quality, left, right):
    measure = getattr(quality, "length_cost", None)
    return measure(left, right) if measure is not None else right - left


def lines_needed(quality, left, right):
    """Lines the character limit and the duration limit require for [left, right)."""
    needed = math.ceil(length_cost(quality, left, right) / max(1, quality.max_chars))
    if getattr(quality, 'units', None) and quality.max_seconds:
        needed = max(needed, -(-int(quality.duration(left, right)*100)//max(1, int(quality.max_seconds*100))))
    return max(1, needed)


# 2026-11-22 (user, 1 h 洛克王国 stream): lines counted against "length ÷ 14"
# pushed every retry toward 13–14 character lines that cut clauses in half
# (你们别着急这时候罗隐开完古镜｜之后…). Natural spoken lines average about
# 60% of the limit; line-count checks use that, not the hard limit.
NATURAL_LINE_SHARE = .6
# A correction may join lines only into a short one (碎片并成一条); joining
# complete clauses into a long line is not an improvement.
SHORT_JOIN_SHARE = .7
# A measured gap this long is a clause edge a correction may not remove.
CLAUSE_PAUSE_SECONDS = .3


def natural_lines(quality, left, right):
    """Lines a stretch reads as when cut at clauses: at least what the limits need."""
    target = max(1., NATURAL_LINE_SHARE*max(1, int(quality.max_chars)))
    return max(lines_needed(quality, left, right), int(-(-(right-left)//target)))


def short_join_limit(quality):
    return max(1, int(SHORT_JOIN_SHARE*max(1, int(quality.max_chars))))


def _fragmented_stretches(quality, boundaries):
    """Stretches between protected edges cut into more lines than clauses explain.

    2026-11-20 (reported job): 梦游步梦游步会｜召唤三名空军局｜士兵一同向敌人｜发起攻击而｜…
    put one 50-character sentence on seven lines where four suffice. The
    prompt says 14 is a cap, not a target; nothing checked it.
    2026-11-22: counted against natural line length (``natural_lines``); a
    79-character turn on nine clause lines is not fragmented.
    """
    edges = [0, *boundaries]
    hard = [0, *sorted(x for x in quality.required if 0 < x < quality.total), quality.total]
    result = []
    for left, right in zip(hard, hard[1:]):
        lines = sum(1 for x in edges[1:] if left < x <= right)
        if lines > natural_lines(quality, left, right)+1:
            result.append((left, right))
    return result


def flagged_edges(quality, boundaries):
    """Cuts a correction may remove: those with an issue of their own, and the
    edges of a dependent short tail (it may join either neighbour)."""
    flagged = set()
    for issue in inspect(quality, boundaries, advisory=True):
        if issue['start'] == issue['end']:
            flagged.add(issue['start'])
        elif issue['kind'] == 'dependent_tail':
            flagged.update((issue['start'], issue['end']))
    return flagged - {0, quality.total}


def _reliable_interiors(quality):
    """Edges whose damage is evidenced by more than an HMM/unknown token."""
    reliable = (getattr(quality, 'known_word_interiors', set())
                | getattr(quality, 'named_entity_interiors', set())
                | getattr(quality, 'named_component_interiors', set())
                | getattr(quality, 'pos_dependency_edges', set())
                | set(getattr(quality, 'syntax_reasons', {})))
    return (reliable & quality.forbidden) - quality.required


def _dependent_tail(quality, start, end, boundaries):
    """A 1–2 character cue that only completes its neighbour (做成｜字幕)."""
    if end-start > 2 or len(boundaries) < 2:
        return False
    if start in quality.required and end in quality.required:
        return False
    if (start, end) in getattr(quality, 'source_ranges', set()):
        return False
    independent = getattr(quality, 'independent_short', None)
    if callable(independent) and independent(start, end):
        return False
    return bool(re.search(r'[㐀-鿿A-Za-z0-9]', quality.index.content[start:end]))


def indivisible_spans(quality, left=0, right=None):
    """Report impossible length constraints without selecting a segmentation."""
    right = quality.total if right is None else right
    edges = [left, *(edge for edge in quality.allowed if left < edge < right), right]
    return [(a, b) for a, b in zip(edges, edges[1:]) if length_cost(quality, a, b) > quality.max_chars]


def select_model_boundary_domain(quality):
    from .segmentation_profiles import legal_raw_boundaries

    raw_allowed = legal_raw_boundaries(quality.index.text, 'zh')
    numeric_interiors = {pos for match in re.finditer(r'[0-9０-９]+', quality.index.text)
                         for pos in range(match.start() + 1, match.end())}
    blocked = (quality.explicit_word_interiors - quality.required) | quality.hard_lexical_interiors
    quality.allowed = [edge for edge in range(1, quality.total)
                       if quality.index.raw_edges[edge] in raw_allowed and edge not in blocked
                       and (edge in quality.required or quality.index.raw_edges[edge] not in numeric_interiors)]
    quality.allowed.append(quality.total)
    quality.strict_model_boundaries = True


def blocked_evidence_edges(quality):
    """Keep independently supported lexical/dependency findings in the AI domain."""
    cached = getattr(quality, '_blocked_evidence_edges', None)
    if cached is not None:
        return cached
    blocked = set()
    # A recipient immediately followed by a determiner is still in the same
    # giving phrase, even when the tokenizer joined 给 to the previous name.
    recipient_edges = {match.end() for match in re.finditer(
        r'给(?=(?:我们|你们|他们|她们|咱们|我|你|他|她)(?:那个|这个|这些|那些|一个|一次|一条))',
        quality.index.content)}
    ends, starts = _token_maps(quality)
    # Use both POS and a known aspect adverb. A POS guess alone can mark a
    # real clause break as dependent in game dialogue.
    aspect_edges = {edge for edge in getattr(quality, 'pos_dependency_edges', ())
                    if ends.get(edge, {}).get('text') in {'已经', '正在', '仍然', '依然'}
                    and starts.get(edge, {}).get('pos', '').startswith('v')}
    for edge in (aspect_edges | recipient_edges) - quality.required:
        before = quality.index.text[:quality.index.raw_edges[edge]].rstrip()
        if (quality.pauses.get(edge, 0) < .55
                and not before.endswith(('。', '！', '？', '.', '!', '?', '；', ';'))):
            blocked.add(edge)
    quality._blocked_evidence_edges = frozenset(blocked)
    return quality._blocked_evidence_edges


def inspect(quality, boundaries, *, advisory=False):
    validate_boundary_offsets(list(boundaries), quality.total)
    issues = [dict(kind='protected_boundary_missing', start=x, end=x)
              for x in sorted(quality.required-set(boundaries))]
    # Explicit terms and numeric units are hard evidence. POS/HMM, relative
    # length, inferred timing and complete-expression preferences are advisory.
    confirmed = quality.explicit_word_interiors-quality.required
    immutable = getattr(quality, "hard_lexical_interiors", set())
    issues.extend(dict(kind='semantic_boundary', start=x, end=x, reason='immutable_word_split')
                  for x in boundaries if x in immutable)
    issues.extend(dict(kind='semantic_boundary', start=x, end=x, reason='confirmed_term_split')
                  for x in boundaries if x in confirmed and x != quality.total)
    if getattr(quality, 'strict_model_boundaries', False):
        allowed = set(quality.allowed) - blocked_evidence_edges(quality)
        issues.extend(dict(kind='semantic_boundary', start=x, end=x, reason='boundary_not_allowed')
                      for x in boundaries if x not in allowed and x not in confirmed and x not in immutable)
    indivisible = set(indivisible_spans(quality))
    edges = [0, *boundaries]
    for left, right in zip(edges, boundaries):
        units = length_cost(quality, left, right)
        if units > quality.max_chars:
            issue = dict(kind='length',start=left,end=right,length=units)
            if (left, right) in indivisible:
                issue['reason'] = 'indivisible_unit'
            issues.append(issue)
        for match in re.finditer(r'(?:太对了|说得对|是啊|对啊|好了)(?=(?:我们|你们|他们|咱们))',
                                 quality.index.content[left:right]):
            offset = left + match.end()
            if quality.pauses.get(offset, 0) >= .45:
                issues.append(dict(kind='incomplete_expression', start=left, end=right,
                                   reason='standalone_response_then_new_turn', preferred_cut=offset))
    content = quality.index.content
    for left, edge, right in zip(edges, edges[1:], edges[2:]):
        if edge in quality.required or edge in confirmed or edge in immutable:
            continue
        ltext, rtext = content[left:edge], content[edge:right]
        raw_edge = quality.index.raw_edges[edge]
        left_raw = quality.index.text[:raw_edge].rstrip()
        if left_raw.endswith(('。', '！', '？', '.', '!', '?', '；', ';')):
            continue
        if (rtext.startswith('的') and not rtext.startswith(('的确', '的士', '的卢'))
                or rtext.startswith('了') and not rtext.startswith(('了解', '了结', '了然', '了得', '了不起', '了断'))):
            issues.append(dict(kind='incomplete_expression', start=edge, end=edge,
                               reason='detached_postposition'))
            continue
        if quality.pauses.get(edge, 0) >= .55:
            continue
        inside_word = (edge in getattr(quality, 'known_word_interiors', ())
                       or edge in getattr(quality, 'named_entity_interiors', ()))
        repeated_syllable = ltext[-1:] == rtext[:1] and ltext[-1:] in '咕喵汪吱嗡呜'
        if inside_word or repeated_syllable:
            issues.append(dict(kind='semantic_boundary', start=edge, end=edge,
                               reason='known_word_split' if inside_word else 'split_reduplicated_sound'))
            continue
        split = phrase_split(quality, edge)
        if split:
            issues.append(dict(kind='semantic_boundary', start=edge, end=edge, reason=split))
            continue
        right_pos = str(_token_maps(quality)[1].get(edge, {}).get('pos', ''))
        dependent = (
            re.search(r'(?:等到|直到|来到)$', ltext)
            or re.search(r'(?:才能|才可以|就能|就可以|以便)$', ltext) and bool(rtext)
            or re.search(r'(?:到|的)$', ltext) and rtext.startswith(('那个', '这个', '时候', '各项'))
            or ltext.endswith('们') and re.search(r'^(?:在|等到|直到)[^。！？]{1,10}$', ltext)
               and re.match(r'[^。！？]{1,5}的', rtext)
            # 这个｜东西 waits for its noun; 关于这个｜我这边, 提到了这个｜一直没想通
            # and 拿这个｜靠近 start a new clause (2026-11-22 snaps moved them to
            # 关于这个我｜这边 and 这个新｜版本).
            or re.search(r'(?:那个|这个)$', ltext) and rtext[0:1].isalpha() and not rtext[0:1].isascii()
               and not right_pos.startswith(('r', 'c', 'd', 'p', 'v', 't', 'y', 'e', 'u', 'm'))
            or getattr(quality, 'dependent_quantity', lambda *_: False)(edge, right)
        )
        if dependent:
            issues.append(dict(kind='incomplete_expression', start=edge, end=edge,
                               reason='dependent_adjacent_text'))
    for left, right in _fragmented_stretches(quality, boundaries):
        if any(left <= issue['start'] < right and issue['kind'] in {'semantic_boundary', 'incomplete_expression'}
               for issue in issues):
            issues.append(dict(kind='excessive_fragmentation', start=left, end=right))
    if advisory:
        reliable = _reliable_interiors(quality)-confirmed
        issues.extend(dict(kind='word_or_dependency_split', start=x, end=x,
                           reason=quality.syntax_reasons.get(x, 'word_or_dependency'))
                      for x in boundaries if x in reliable and x != quality.total)
        for left, right in zip([0,*boundaries],boundaries):
            if _dependent_tail(quality, left, right, boundaries):
                issues.append(dict(kind='dependent_tail', start=left, end=right))
        issues.extend(dict(kind='dependent_opener', start=x, end=x) for x in boundaries
                      if x != quality.total and x not in reliable and _dependent_opener(quality, x))
        issues.extend(dict(kind='fragmented', start=left, end=right)
                      for left, right in _fragmented_stretches(quality, boundaries))
        flagged = {(x['start'], x['end']) for x in issues}
        issues.extend(x for x in dangling_edges(quality, boundaries) if (x['start'], x['end']) not in flagged)
    return issues


_DE_WORDS = ('的确', '的士', '的卢')
_LE_WORDS = ('了解', '了结', '了然', '了得', '了不起', '了断')


def break_candidates(quality):
    """Cut positions offered to the model as ‹N› marks (2026-11-22).

    The model copied numbers off an indexed list and missed by one or two
    (英雄了各｜位). It now picks marks placed in the gaps themselves, and gaps
    inside a dictionary word, a confirmed term or before a dependent 的/了 get
    no mark. Required cuts always have one. Where the remaining marks leave a
    stretch longer than the limit, that stretch gets every allowed mark back,
    so a legal segmentation always exists.
    """
    content, total = quality.index.content, quality.total
    blocked = set(getattr(quality, 'known_word_interiors', ())) | set(getattr(quality, 'explicit_word_interiors', ()))
    for edge in range(1, total):
        right = content[edge:]
        if (right.startswith('的') and not right.startswith(_DE_WORDS)
                or right.startswith('了') and not right.startswith(_LE_WORDS)):
            left_raw = quality.index.text[:quality.index.raw_edges[edge]].rstrip()
            if not left_raw.endswith(('。', '！', '？', '.', '!', '?', '；', ';')):
                blocked.add(edge)
        # 2026-11-22: 联系不上｜你我, 住｜在对门 … were offered marks and picked.
        elif quality.pauses.get(edge, 0) < .55 and phrase_split(quality, edge):
            left_raw = quality.index.text[:quality.index.raw_edges[edge]].rstrip()
            if not left_raw.endswith(('。', '！', '？', '，', '、', '.', '!', '?', ',', '；', ';', '…')):
                blocked.add(edge)
    # The model's legal domain (select_model_boundary_domain); without it every
    # gap is a candidate. Syntax preferences (移动｜到) are never removed here.
    strict = getattr(quality, 'strict_model_boundaries', False)
    domain = quality.allowed if strict else range(1, total+1)
    blocked_by_evidence = blocked_evidence_edges(quality) if strict else set()
    allowed = (({edge for edge in domain if 0 < edge <= total} | {total})
               - getattr(quality, "hard_lexical_interiors", set()) - blocked_by_evidence)
    required = {edge for edge in quality.required if 0 < edge < total}
    marks = (allowed - blocked) | required | {total}
    edges = [0, *sorted(marks)]
    for left, right in zip(edges, edges[1:]):
        if length_cost(quality, left, right) > quality.max_chars:
            marks.update(edge for edge in allowed if left < edge < right)
    return sorted(marks)


def place_on_marks(boundaries, marks, *, left=0, right=None, immutable=()):
    """A pick between marks moves to the nearest mark; returns (boundaries, moves)."""
    marks = set(marks)
    right = max(boundaries, default=0) if right is None else right
    inner = sorted(mark for mark in marks if left < mark < right)
    result, moves = set(), []
    for value in boundaries:
        if value in marks or value in immutable or not left < value < right or not inner:
            result.add(value)
            continue
        target = min(inner, key=lambda option: (abs(option-value), option))
        result.add(target)
        moves.append((value, target))
    return sorted(result), moves


# What still blocks acceptance after the AI has had its rounds: a line over the
# limit that could be cut, a missing protected cut, a split confirmed term.
# Dictionary/POS evidence keeps sending a window back but no longer turns the
# AI's final answer into the ASR sentence (user, 2026-11-22: AI only).
def blocking_issues(issues):
    return [x for x in issues
            if x['kind'] == 'length' and x.get('reason') != 'indivisible_unit'
            or x['kind'] == 'protected_boundary_missing'
            or x['kind'] == 'semantic_boundary' and x.get('reason') in {
                'confirmed_term_split', 'immutable_word_split', 'boundary_not_allowed'}]


def unsplittable_lengths(quality, issues):
    """Length issues on a span with no legal cut inside under ``quality``'s domain.

    2026-11-22 (user, 1 h stream): 87249，8724987249 (15 characters, digits
    only) has no legal cut, but the display-side check offers the comma and
    reported it as a cuttable over-long line, so the whole 32-sentence batch
    was left as 断句待重试 and the task as partial. Nothing can fix it.
    """
    spans = set(indivisible_spans(quality))
    return [x for x in issues if x['kind'] == 'length' and (x['start'], x['end']) in spans]


def answer_score(quality, boundaries, left=0, right=None):
    """Lower is better: blocking issues, then other hard issues, then advisory risks."""
    right = quality.total if right is None else right
    issues = [x for x in inspect(quality, boundaries, advisory=True) if left <= x['start'] < right]
    hard = [x for x in issues if x['kind'] in HARD_KINDS]
    blocking = blocking_issues(hard)
    overflow = sum(x.get('length', 0) - quality.max_chars for x in blocking if x['kind'] == 'length')
    return (len(blocking), overflow, len(hard), len(issues))


EDGE_DAMAGE_KINDS = frozenset({'semantic_boundary', 'incomplete_expression'})
# The observed miss is one character late; then one early, then two either way.
SNAP_STEPS = (-1, 1, -2, 2)


# Advisory splits (有点｜低, 两发｜暴风雪) never move locally: 这把比较｜难打
# would become 比较难｜打. They go back to the AI as a window retry.


def _edge_damage(quality, boundaries, edge):
    return [x for x in inspect(quality, boundaries)
            if x['start'] == x['end'] == edge and x['kind'] in EDGE_DAMAGE_KINDS]


def _hard_between(quality, boundaries, left, right):
    return [x for x in inspect(quality, boundaries) if left <= x['start'] < right]


def snap_offset_errors(quality, boundaries, *, left=0, right=None, record=None, batch_index=None):
    """Move an AI cut that landed one or two characters off a legal edge.

    2026-11-22 (崩铁 2-hour report): 56 of the 60 first answers that cut inside
    a word were clean one character earlier (英雄了各｜位小心, 阿格尼丝所｜以,
    复杂我｜们先): the model returned the number printed on the next line's
    first character. Window retries, which carry no numbered text, missed by
    one or two (持续关｜注, 阿格｜尼丝, 动力｜学构造). Each miss was a hard
    failure, the retry answer was rejected and the whole range fell back to the
    ASR sentence: 204 of 1,546 cues over 14 characters, up to 34.

    Only a cut with hard damage at its own edge (a dictionary word, a confirmed
    term or a detached particle) moves; it moves to the nearest
    allowed edge within two characters that removes that damage and leaves
    fewer hard issues in its two lines. Protected cuts never move. Returns
    (boundaries, [(old, new), ...]).
    """
    right = quality.total if right is None else right
    result = list(boundaries)
    blocked_by_evidence = (blocked_evidence_edges(quality)
                           if getattr(quality, 'strict_model_boundaries', False) else set())
    allowed = set(quality.allowed) - blocked_by_evidence if getattr(quality, 'allowed', None) else None
    moves = []
    known = getattr(quality, 'known_word_interiors', set())
    interiors = {x for t in getattr(quality, 'tagged_tokens', ()) or () for x in range(t['start']+1, t['end'])}
    for edge in [x for x in boundaries if left < x < right]:
        if edge in quality.required or edge in getattr(quality, "hard_lexical_interiors", ()) or edge not in result:
            continue
        # A guessed personal name alone (王敬 in 末王｜敬未到场) is weaker
        # evidence than the model's own cut; that edge keeps the retry path.
        if not [x for x in _edge_damage(quality, result, edge)
                if x.get('reason') != 'known_word_split' or edge in known]:
            continue
        index = result.index(edge)
        prev = result[index-1] if index else 0
        nxt = result[index+1]
        before = len(_hard_between(quality, result, prev, nxt))
        for step in SNAP_STEPS:
            target = edge+step
            if not max(prev, left) < target < min(nxt, right):
                continue
            if allowed is not None and target not in allowed:
                continue
            # 2026-11-22: a move may not land inside a tokenizer word or open a
            # line with 着/了/的 (住｜在对门 → 住在对｜门, 陪着｜你 → 陪｜着你).
            if target in interiors or quality.index.content[target:target+1] in DEPENDENT_OPENERS:
                continue
            candidate = sorted((set(result)-{edge}) | {target})
            if _edge_damage(quality, candidate, target):
                continue
            if len(_hard_between(quality, candidate, prev, nxt)) >= before:
                continue
            result = candidate
            moves.append((edge, target))
            break
    if record is not None and moves:
        content = quality.index.content
        record('grouping_boundary_snapped', batch_index=batch_index, rule='ai_offset_within_two',
               moves=[dict(model=a, final=b, model_text=content[max(0, a-6):a]+'｜'+content[a:a+6],
                           final_text=content[max(0, b-6):b]+'｜'+content[b:b+6]) for a, b in moves])
    return result, moves


def windows(quality, boundaries, *, advisory=False):
    """The minimal invalid AI segment; a bad edge owns its two adjacent pieces."""
    edges=[0,*boundaries]
    ranges=[]
    for issue in inspect(quality,boundaries,advisory=advisory):
        a,b=issue['start'],issue['end']
        if a==b:
            a=max((x for x in edges if x<a),default=0)
            b=min((x for x in edges if x>b),default=quality.total)
        elif issue['kind'] == 'dependent_tail':
            # The tail and both neighbours: it may belong to either side.
            a=max((x for x in edges if x<a),default=0)
            b=min((x for x in edges if x>b),default=quality.total)
        ranges.append((a,b))
    result=[]
    for a,b in sorted(set(ranges)):
        if result and a < result[-1][1]:
            result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:
            result.append((a,b))
    return result


def _retry_status(statuses, left, right):
    """The AI retry status of the window overlapping [left, right)."""
    found = [status for (a, b), status in (statuses or {}).items() if a < right and left < b]
    if not found:
        return 'retry_not_attempted'
    order = ('request_failed', 'input_budget_conflict', 'not_allocated', 'no_answer',
             'rejected_by_gate', 'unchanged_with_violations', 'unchanged', 'improved')
    return min(found, key=lambda s: order.index(s) if s in order else len(order))


FALLBACK_REASONS = {
    'not_allocated': 'retry_budget_not_allocated',
    'input_budget_conflict': 'retry_input_budget_conflict',
    'request_failed': 'retry_request_failed',
    'no_answer': 'retry_no_answer',
    'rejected_by_gate': 'retry_answer_rejected',
    'unchanged_with_violations': 'retry_unchanged_with_violations',
    'retry_not_attempted': 'retry_not_attempted',
}


def minimal_fallback(quality, boundaries, *, record=None, statuses=None):
    """Never borrow characters from accepted neighbours or relax the limit.

    Only hard failures (length, protected edges, explicit terms) are repaired
    locally; advisory risks keep the AI answer. The receipt reason says why
    the AI did not fix the window (budget not allocated, request failed,
    answer rejected...), never a blanket 'retry exhausted'.
    """
    result=list(boundaries)
    receipts=[]
    # Conservative local construction may avoid an inferred quantity/noun
    # seam. This scoring constraint never participates in AI acceptance.
    import copy
    solver=copy.copy(quality)
    quantity_tails={m.end() for m in re.finditer(r'(?:非常多|这么多|那么多|很多|许多|大量)(?:的)?',quality.index.content)}
    for left,right in windows(quality,boundaries):
        before=[x for x in result if left < x <= right]
        issues = inspect(quality, result)
        bad_edges = {x['start'] for x in issues
                     if x['kind'] in {'semantic_boundary', 'incomplete_expression'}
                     and x['start'] == x['end'] and left < x['start'] < right}
        measured_cuts = {x['preferred_cut'] for x in issues if x.get('preferred_cut') is not None
                         and left < x['preferred_cut'] < right and x['preferred_cut'] not in bad_edges}
        solver.allowed = sorted((set(quality.allowed) | measured_cuts) - quantity_tails - bad_edges)
        fixed = {left, right} | quality.required | measured_cuts
        existing = sorted((set(before) - bad_edges) | measured_cuts)
        candidate = existing
        if not measured_cuts or any(b - a > quality.max_chars for a, b in zip([left, *existing], existing)):
            mandatory = sorted(edge for edge in fixed if left <= edge <= right)
            candidate = []
            for a, b in zip(mandatory, mandatory[1:]):
                selected = solver._solve(a, b, set(before), fixed=fixed, relax_time=True)
                if not selected:
                    candidate = None
                    break
                candidate.extend(selected)
        proposed=sorted({x for x in result if not left < x <= right}|set(candidate or before))
        failures=[x for x in inspect(quality,proposed) if left <= x['start'] < right]
        accepted=bool(candidate) and not failures
        if accepted:
            result=proposed
        status=_retry_status(statuses,left,right)
        receipt=dict(content_start=left,content_end=right,
                     origin='local_minimal_fallback' if accepted else 'unresolved',
                     before=before,after=candidate if accepted else before,
                     reason=FALLBACK_REASONS.get(status, 'retry_'+status),retry_status=status,
                     remaining_issues=failures,
                     remaining_advisory=[x for x in inspect(quality,proposed if accepted else result,advisory=True)
                                         if left <= x['start'] < right and x['kind'] in ADVISORY_KINDS])
        receipts.append(receipt)
        if record:
            record('grouping_minimal_fallback',**receipt)
    return result,receipts


def _retained_windows(quality, boundaries, retain):
    edges = [0, *boundaries]
    ranges = []
    for issue in inspect(quality, boundaries):
        if not retain(issue):
            continue
        a, b = issue['start'], issue['end']
        if a == b:
            a = max((x for x in edges if x < a), default=0)
            b = min((x for x in edges if x > b), default=quality.total)
        ranges.append((a, b))
    return sorted(set(ranges))


def must_retain_source(issue):
    """Keep the source when the model has no safe decision for a hard boundary."""
    return (issue['kind'] == 'protected_boundary_missing'
            or issue['kind'] == 'semantic_boundary' and issue.get('reason') in {
                'confirmed_term_split', 'immutable_word_split', 'boundary_not_allowed'})


def preserve_rejected_windows(quality, boundaries, source_boundaries, *, record=None, statuses=None,
                              retain=None):
    """Retain original source boundaries wherever a model decision failed.

    Expand a rejected window to common endpoints so later AI cuts never
    inherit part of a rejected cue or ownership from a different source.
    ``retain(issue)`` limits which issues count as failed (default: every hard issue).
    """
    common = sorted({0, *source_boundaries} & {0, *boundaries})
    rejected = []
    for left, right in (windows(quality, boundaries) if retain is None
                        else _retained_windows(quality, boundaries, retain)):
        start = max(edge for edge in common if edge <= left)
        end = min(edge for edge in common if edge >= right)
        if rejected and start < rejected[-1][1]:
            rejected[-1] = (rejected[-1][0], max(end, rejected[-1][1]))
        else:
            rejected.append((start, end))
    result = list(boundaries)
    receipts = []
    for left, right in rejected:
        before = [edge for edge in boundaries if left < edge <= right]
        after = [edge for edge in source_boundaries if left < edge <= right]
        issues = [issue for issue in inspect(quality, boundaries) if left <= issue['start'] < right
                  and (retain is None or retain(issue))]
        retry_status = _retry_status(statuses, left, right)
        receipt = dict(content_start=left, content_end=right, origin='unresolved',
                       before=before, after=after, remaining_issues=issues,
                       reason=FALLBACK_REASONS.get(retry_status, 'retry_' + retry_status),
                       retry_status=retry_status)
        receipts.append(receipt)
        result = sorted({edge for edge in result if not left < edge <= right} | set(after))
        if record:
            record('grouping_source_range_retained', **receipt)
    return result, receipts


def annotate(cues, model_boundaries, final_boundaries, receipts):
    cursor=0
    for cue,end in zip(cues,final_boundaries):
        overlaps=[r for r in receipts if r['content_start'] < end and cursor < r['content_end']]
        cue.grouping_origin=next((r['origin'] for r in reversed(overlaps)), 'ai_accepted')
        cue.grouping_boundary_receipt=dict(origin=cue.grouping_origin,content_start=cursor,
            content_end=end,model_boundaries=[x for x in model_boundaries if cursor < x <= end],
            final_boundaries=[end],repairs=overlaps)
        cursor=end


def provenance(cues, validated):
    origins={getattr(c,'grouping_origin','ai_accepted') for c in cues}
    if not validated or 'unresolved' in origins:
        return 'fallback','unresolved'
    if any(o.startswith(('local_','source_retained')) for o in origins):
        return 'mixed','local_minimal_fallback'
    return 'ai','ai_targeted_correction' if 'ai_targeted_correction' in origins else 'ai_accepted'
