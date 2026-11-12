"""Syntactic evidence consumed by the shared boundary quality gate."""
import re

INDEPENDENT_RESPONSES = frozenset({
    "可以", "不行", "对的", "好的", "是的", "没错", "明白", "确实", "好吧",
    "没有", "有", "能", "不能", "行", "知道了", "可以的",
})
PERSONAL_PRONOUNS = frozenset({"我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "它们"})
DIRECTIONAL_COMPLEMENTS = frozenset({
    "出来", "起来", "进去", "出去", "上来", "下来", "下去", "上去",
    "进来", "回来", "回去", "过来", "过去",
})
RESULTATIVE_COMPLEMENTS = frozenset({"住", "掉", "完", "到", "走", "死", "清", "满"})


def repeated_units(content):
    for match in re.finditer(r"(.{1,4})\1+", content):
        unit = match.group(1)
        for width in range(1, len(unit)+1):
            if len(unit) % width == 0 and unit[:width]*(len(unit)//width) == unit:
                unit = unit[:width]
                break
        yield match.start(), match.end(), unit


def syntax_boundary_evidence(index, max_chars):
    """Return local phrase cohesion and clause edges in the immutable index."""
    import jieba.posseg as posseg
    import jieba
    content = index.content
    tokens = list(posseg.cut(content))
    starts = []
    cursor = 0
    for token in tokens:
        starts.append(cursor)
        cursor += len(token.word)
    spans = []
    clauses = set()
    completed_conditions = set()

    def protect(start, end, reason, *, indivisible=False):
        raw = index.slice(start, end).rstrip("，,。！？!?；; \t\r\n")
        if 1 < end-start and (indivisible or end-start <= max_chars) and not re.search(r"[，,。！？!?；;]", raw):
            spans.append((start, end, reason))

    for position, (token, following) in enumerate(zip(tokens, tokens[1:])):
        start = starts[position]
        edge = starts[position+1]
        following_end = edge+len(following.word)
        if (token.flag.startswith('n') and following.word.startswith('第') and following.flag == 'm'
                and position+2 < len(tokens) and tokens[position+2].flag.startswith('v')):
            protect(start, following_end+len(tokens[position+2].word), 'ranked_subject_predicate')
        if following.word in {'什么', '为什么', '怎么', '如何'} and token.flag.startswith('n'):
            clauses.add(edge)
        if (token.word in {'会不会','能不能','能否'}
                or token.word in {'会','能'} and following.word in {'不会','不能'}):
            clauses.add(start)
        if token.word in PERSONAL_PRONOUNS and (
                following.flag[0] in "vdapt" or following.word in {"这个", "那个", "这些", "那些"}):
            protect(start, following_end, "subject_or_possessor")
        # 满 can head a nominal modifier (满状态/满血), even after a verb.
        # A POS tag on the preceding verb does not prove result attachment.
        nominal_full = (following.word == '满' and position+2 < len(tokens)
                        and tokens[position+2].flag.startswith('n')
                        and not jieba.dt.FREQ.get(token.word+'满', 0))
        if (token.flag.startswith("v") and following.word in DIRECTIONAL_COMPLEMENTS | RESULTATIVE_COMPLEMENTS
                and not nominal_full):
            protect(start, following_end, "verb_complement")
        if nominal_full:
            protect(edge, following_end+len(tokens[position+2].word), 'nominal_modifier')
            clauses.add(edge)
        # POS tags vary with neighbouring ASR text: 最/a and 太/n are real
        # examples. The closed grammatical class plus its predicate is
        # stronger evidence than requiring the modifier itself to be /d.
        if token.word in {'最', '太', '更', '很', '非常', '十分', '特别', '更加'} and following.flag.startswith(('a', 'v')):
            protect(start, following_end, 'degree_predicate')
        if token.word in {"再", "去", "来", "继续", "开始", "尝试", "想", "要", "能", "会"} and following.flag.startswith("v"):
            protect(start, following_end, "serial_predicate")
        if token.word in {'能够', '可以', '必须', '应该', '需要', '会', '不会', '不能', '会不会', '能不能', '能否'} and following.flag.startswith(('v', 'l')):
            protect(start, following_end, 'modal_predicate')
        if token.word in {'是', '就是', '也是'} and (
                following.flag.startswith(('n', 'zg', 'eng'))
                or position+2 < len(tokens) and tokens[position+2].word in {'和', '与'}):
            protect(start, following_end, 'copula_head')
        # HMM may invent 力叠/v across a productive noun suffix and a real
        # predicate (…菊花力 | 叠的太…). Reconsider that guessed token only
        # with a noun on the left and an explicit degree-complement frame.
        if (position and token.word[:1] in '力率值量性度' and len(token.word) in {2,3}
                and tokens[position-1].flag.startswith('n')
                and not jieba.dt.FREQ.get(token.word,0)
                and jieba.dt.FREQ.get(token.word[1:],0)
                and following.word in {'的','得'} and position+2 < len(tokens)
                and tokens[position+2].word in {'太','最','很','非常','十分','更'}):
            protect(starts[position-1],start+1,'nominal_suffix_head')
            completed_conditions.add(start+1)
            clauses.add(start+1)
        if token.word in {"让", "叫", "请"} and following.flag.startswith(("n", "r")):
            protect(start, following_end, "causative_actor")
            if (position > 1 and tokens[position-1].flag.startswith("n")
                    and any(previous.flag.startswith("v") for previous in tokens[max(0, position-3):position-1])):
                clauses.add(start)
        if (following.word in PERSONAL_PRONOUNS and position+2 < len(tokens)
                and (tokens[position+2].flag[0] in "vdap" or tokens[position+2].word == "的")):
            clauses.add(edge)

    demonstrative = r"[这那哪每本此该](?:一|两|几|\d+)?[场个种次位条件项份台名届发招记把只轮]"
    possessive = r"(?:我|你|他|她|我们|你们|他们)的(?:[这那]?[一两几\d]+[个种位份件条把只轮])?"
    # Event/animate classifier heads need their noun (一轮毒罐、一只呆鸟).
    # Do not promote every 一个 + modifier chain into an indivisible phrase.
    numeric_classifier = r'[一两三四五六七八九十几\d]+[只轮]'
    quantifiers = f"(?:{demonstrative}|{possessive}|{numeric_classifier})"
    for match in re.finditer(quantifiers, content):
        tail = list(posseg.cut(content[match.end():match.end()+max_chars]))
        head_end = match.end()
        has_noun = False
        for tail_index, token in enumerate(tail):
            if token.flag.startswith("n") or token.flag == "eng":
                head_length = len(token.word)
                for repeat_start, _, unit in repeated_units(token.word):
                    if repeat_start == 0:
                        head_length = len(unit)
                        break
                head_end += head_length
                for component in tail[tail_index+1:]:
                    if not component.flag.startswith('n'):
                        break
                    head_end += len(component.word)
                has_noun = True
                break
            if token.flag[0] not in "admq" and token.flag != "uj":
                break
            head_end += len(token.word)
        if not has_noun:
            continue
        # Event classifiers can introduce a nominalised action name.
        if match.group()[-1] in "发招记":
            suffix = list(posseg.cut(content[head_end:head_end+max_chars]))
            if suffix and suffix[0].flag.startswith("v") and len(suffix[0].word) >= 2:
                head_end += len(suffix[0].word)
            elif (len(suffix) > 1 and suffix[0].word == '能' and suffix[1].flag.startswith('v')):
                head_end += len(suffix[0].word) + len(suffix[1].word)
        phrase_start = match.start()
        preceding = next((i for i, start in enumerate(starts) if start == phrase_start), None)
        if (preceding and tokens[preceding-1].flag.startswith("v")
                and tokens[preceding-1].word not in DIRECTIONAL_COMPLEMENTS | {"说", "讲", "问", "是"}):
            phrase_start = starts[preceding-1]
        protect(phrase_start, head_end, "determiner_object_phrase")

    for match in re.finditer(r"(?:左|右)(?:上|下)(?:角|方|边|侧|部|柱|路|位)", content):
        protect(match.start(), match.end(), "directional_noun")
    for match in re.finditer(r"[\u3400-\u9fff]得[了住完到下起出回走死好清满]", content):
        protect(match.start(), match.end(), "resultative_complement")
    for match in re.finditer(r"[\u3400-\u9fff](?:得|不)[上下进出回过起](?:来|去)(?:了|吗|呢)?", content):
        protect(match.start(), match.end(), 'potential_directional_predicate')
    for match in re.finditer(r"[一两三四五六七八九十\d]+[只名位][\u3400-\u9fff]{1,6}(?=选手|队员|玩家)", content):
        protect(match.start(), match.end(), 'classifier_named_head')
    for match in re.finditer(r'(?:对于|对)[\u3400-\u9fff]{1,10}?(?:来说|而言|来讲)',content):
        protect(match.start(),match.end(),'comparative_frame')
    # Institution-based team names use a recognised location/organisation
    # start and an explicit team suffix, never a hardcoded game team name.
    for position, token in enumerate(tokens):
        if token.flag not in {'ns', 'nt', 'nz'}:
            continue
        start = starts[position]
        match = re.match(r'[\u3400-\u9fff]{2,8}(?:大学|学院)[\u3400-\u9fff]{0,8}?战队', content[start:])
        if match:
            protect(start, start+match.end(), 'institution_team_name', indivisible=True)
    for match in re.finditer(r"然后|但是|不过|所以|因此|因为|如果|否则|而且|并且|或者|还是|这边|这里|之后|接下来", content):
        if match.start():
            clauses.add(match.start())
    condition = r"(?:我|你|他|她|我们|你们|他们)(?:今天|明天|后天|现在|马上)?一(?:来|走|到|动|开|上|下)"
    for match in re.finditer(condition, content):
        completed_conditions.add(match.end())
        clauses.add(match.end())
    return spans, clauses, completed_conditions


