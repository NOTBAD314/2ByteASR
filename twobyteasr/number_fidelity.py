"""Conservative number spelling with ordered events and source provenance."""
import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher

RULE_VERSION = 'numeric-events-conservative-v3'
NUMBER_POLICY_PROMPT = (
    '数字策略：保留原话数字事件的顺序和每次重复，不求和、不拼接、不去重。'
    '普通整数1～9保留源文汉字，例如一个、两个办法、一技能、二技能；'
    '10及以上只有明确数值且不属于固定词语/专名时才由本地转为阿拉伯数字。'
    '小数、百分比和明确比例可转换，例如零点五秒→0.5秒、百分之二→2%、二比三→2比3。'
    '保留十有八九、一心一意等固定词语和十几个、二三十个、一百来个等约数，'
    '已确认规范词内部的数字写法受词库保护。校对时保留primary_text的数字写法，交给本地格式化；'
    '不得把一个改为1个，不得将原本的阿拉伯数字盲目反向改成汉字，编号/版本号不推测原写法。'
)
DIGITS = dict(zip('零〇一二两三四五六七八九', (0,0,1,2,2,3,4,5,6,7,8,9)))
UNITS = {'十':10,'百':100,'千':1000,'万':10000,'亿':100000000}
CN = '零〇一二两三四五六七八九十百千万亿'
TOKEN = re.compile(rf'(?:百分之)?(?:\d+(?:\.\d+)*(?:[万亿])?|[{CN}]+(?:点[零〇一二两三四五六七八九]+)*)(?:[%％])?')
FIXED = re.compile(r'一会儿?|一点(?:也|都|不)|死路一条|一丝不苟|一心一意|三心二意|七上八下|乱七八糟|说一不二|万一|万物|统一|一起|一切|一般|一定|一下|一直|一试|一样|两位数|三国|七日杀|最终幻想十四|十有八九|十全十美|十拿九稳|十恶不赦|十年树木|十面埋伏|三十六计|三十年河东|三十年河西|七十二变|十二生肖|十二星座|二十四节气|十八般武艺|百发百中|百战百胜|千方百计|千奇百怪|千军万马|千言万语')
CLOCK = re.compile(rf'[{CN}0-9]+点(?:半|[{CN}0-9]+分(?:[{CN}0-9]+秒)?)')
COUNTERS = '个张卡局颗刀抽层次只套发星年月日号分秒块元岁级把轮种位件台条枚份瓶杯米段小时倍'
APPROXIMATE = re.compile(rf'[{CN}]+(?:几|多|来|余)|(?:两三|二三|三四|四五|五六|六七|七八|八九)[十百千万亿]?')
RATIO = re.compile(rf'(?:\d+(?:\.\d+)?|[{CN}]+(?:点[零〇一二两三四五六七八九]+)?)\s*(?:比|[:：])\s*(?:\d+(?:\.\d+)?|[{CN}]+(?:点[零〇一二两三四五六七八九]+)?)')
IDENTIFIER_PREFIX = re.compile(r'(?:编号|号码|版本|序号|型号|ID|id)\s*$')
NUMBER_PREFIX = re.compile(r'(?:第|只有|一共|还剩|仅有|编号|号码|版本|序号|概率|伤害|威力|生命值|能量|攻击|防御|回复|恢复|加|减|乘|除|等于|到|至)\s*$')
NUMBER_SUFFIX = re.compile(rf'(?:[{COUNTERS}]|伤害|威力|生命值|血量|能量|攻击|防御|金币|连|届|成|%|％)')
# 2026-10-16 (found with a Japanese user's log; Chinese since 0.7.1): a lone
# 十 before 分 was always ten points, so 十分感谢 became 10分感谢. Usually it is
# the adverb (十分重要, 感到十分高兴, 打得十分精彩). It is a number only after a
# scoring word, before 钟/制/以上/以下/左右, or alone between clause edges.
SHIFEN = re.compile(rf'(?<![{CN}0-9])十分')
SHIFEN_SCORE_PREFIX = re.compile(
    r'(?:打了?|得了|考了?|拿了?|扣了?|加了?|减了?|差了?|满分?|领先|落后|赢了?|输了?'
    r'|超过|一共|只有|还剩|还差|总共)\s*$')
SHIFEN_NUMBER_SUFFIX = re.compile(r'钟|制|以上|以下|左右')
CLAUSE_EDGE = '，,、。.！!？?；;'


def _adverb_shifen_spans(text):
    spans = []
    for match in SHIFEN.finditer(text):
        start, end = match.span()
        before, after = text[start-1:start], text[end:end+1]
        number = (bool(SHIFEN_SCORE_PREFIX.search(text[:start]))
                  or bool(SHIFEN_NUMBER_SUFFIX.match(text, end))
                  or ((not before or before in CLAUSE_EDGE) and (not after or after in CLAUSE_EDGE)))
        if not number:
            spans.append((start, end))
    return spans


def _protected_spans(text, terms=()):
    # Adverb 十分 is protected like a fixed phrase, so formatting, the AI-edit
    # restore, safe cuts and the final check all read it the same way.
    spans = [m.span() for pattern in (FIXED, CLOCK) for m in pattern.finditer(text)]
    spans.extend(_adverb_shifen_spans(text))
    for match in APPROXIMATE.finditer(text):
        # Digits following 点 or an explicit code are not approximate speech.
        numeric = next((m for m in TOKEN.finditer(text)
                        if m.start() <= match.start() and match.end() <= m.end()), None)
        if numeric and ('点' in numeric.group() or IDENTIFIER_PREFIX.search(text[:numeric.start()])):
            continue
        spans.append(match.span())
    spans.extend(m.span() for term in terms if term
                 for m in re.finditer(re.escape(str(term)), text))
    return spans


def _overlaps(start, end, spans):
    return any(a < end and start < b for a, b in spans)


def integer_value(token):
    if token.isdigit(): return token
    if not token or any(c not in DIGITS and c not in UNITS for c in token): return None
    if token[0] in '百千万亿':return None
    if not any(c in UNITS for c in token): return ''.join(str(DIGITS[c]) for c in token)
    total=section=number=0; previous_unit=10000; had_digit=False; large_units=set()
    for char in token:
        if char in DIGITS:
            if had_digit and number != 0: return None  # ambiguous adjacent events
            number=DIGITS[char]; had_digit=True
        else:
            unit=UNITS[char]
            if unit<10000:
                if unit>=previous_unit: return None  # 二十二十 is not forty
                section+=(number if had_digit else 1)*unit
                previous_unit=unit; number=0; had_digit=False
            else:
                if unit in large_units:return None
                large_units.add(unit)
                section+=number
                if unit==100000000: total=(total+section)*unit
                else: total+=section*unit
                section=number=0; had_digit=False; previous_unit=10000
    return str(total+section+number)


@dataclass(frozen=True)
class NumericEvent:
    start: int
    end: int
    source: str
    value: str
    kind: str = 'integer'


def numeric_events(text, *, protected_terms=()):
    text=str(text)
    protected = _protected_spans(text, protected_terms)
    ratios = [m.span() for m in RATIO.finditer(text)]
    result=[]
    for match in TOKEN.finditer(text):
        start,end=match.span(); raw=match.group()
        if _overlaps(start, end, protected): continue
        before=text[start-1:start]; after=text[end:end+1]
        if before=='几' or after in ('几', '多', '来', '余'): continue
        percent=raw.startswith('百分之') or raw.endswith(('%','％'))
        body=raw.removeprefix('百分之').rstrip('%％')
        pieces=body.split('点')
        # Clock readings retain 点, e.g. 五点三十分. They are not decimals.
        if len(pieces)>1 and after in ('分','时'):
            continue
        if len(pieces)>1:
            first=integer_value(pieces[0]); tail=[''.join(str(DIGITS[c]) for c in x) for x in pieces[1:]]
            value='.'.join([first,*tail]) if first is not None else None
        elif re.fullmatch(r'\d+(?:\.\d+)?[万亿]',body):
            from decimal import Decimal
            value=format(Decimal(body[:-1])*UNITS[body[-1]],'f').rstrip('0').rstrip('.') if '.' in body else str(int(body[:-1])*UNITS[body[-1]])
        else: value=body if re.fullmatch(r'\d+(?:\.\d+)*',body) else integer_value(body)
        if value is None: continue
        ratio = _overlaps(start, end, ratios)
        decimal = len(pieces) > 1 or '.' in body
        identifier = bool(IDENTIFIER_PREFIX.search(text[:start]))
        # Adjacent Chinese digits without units are ambiguous speech unless
        # explicitly a code. 二三十/两三个 are protected approximate quantities.
        if (len(body) > 1 and all(c in DIGITS for c in body)
                and not identifier and not ratio and not percent): continue
        boundary_before = not before or before.isspace() or before in '，,、'
        boundary_after = not after or after.isspace() or after in '，,、!?？!'
        clear = (bool(re.search(r'\d', body)) or percent or decimal or ratio
                 or bool(NUMBER_PREFIX.search(text[:start]))
                 or bool(NUMBER_SUFFIX.match(text[end:]))
                 or (boundary_before and boundary_after)
                 or (before.isspace() and bool(re.search(r'[十百千万亿]', body)))
                 or bool(re.match(r'到|至|加|减|乘|除|等于|比', text[end:])))
        kind = 'percent' if percent else 'decimal' if decimal else 'ratio' if ratio else 'identifier' if identifier else 'integer'
        if clear: result.append(NumericEvent(start,end,raw,value+('%' if percent else ''),kind))
    return result


def restore_source_number_style(source_text, target_text, *, protected_terms=()):
    """Restore only aligned new numeric spelling; never reverse existing digits."""
    source, target = str(source_text or ''), str(target_text or '')
    protected = _protected_spans(source, protected_terms)
    ratios = [m.span() for m in RATIO.finditer(source)]
    plans = []
    for op, a, b, c, d in SequenceMatcher(None, source, target, autojunk=False).get_opcodes():
        old, new = source[a:b], target[c:d]
        if (op != 'replace' or not old or not new
                or not re.fullmatch(rf'[{CN}]+', old)
                or not re.fullmatch(r'\d+', new)):
            continue
        protected_hit = _overlaps(a, b, protected)
        value = integer_value(old)
        same_value = value is not None and int(value) == int(new)
        small = same_value and int(value) < 10
        if not protected_hit and (IDENTIFIER_PREFIX.search(source[:a]) or _overlaps(a, b, ratios)):
            continue
        if not protected_hit and not small:
            continue
        # Decimal/percentage parts below ten are intentional exceptions.
        if not protected_hit and (source[a-1:a] == '点' or source[:a].endswith('百分之')
                                  or source[b:b+1] in ('%', '％')):
            continue
        if protected_hit or same_value:
            plans.append((a, b, c, d, old, new))
    result = []; events = []; cursor = output_cursor = 0
    for a, b, c, d, old, new in plans:
        prefix = target[cursor:c]; result.extend((prefix, old)); output_cursor += len(prefix)
        events.append(dict(start=c, end=d, source=old, input=new, value=old,
            source_start=a, source_end=b, output_start=output_cursor, output_end=output_cursor+len(old),
            kind='source_style_restore', reason='protected_source_spelling' if _overlaps(a,b,protected) else 'spoken_small_integer'))
        output_cursor += len(old); cursor = d
    result.append(target[cursor:])
    return ''.join(result), events


def format_numbers(text, *, enabled=True, protected_terms=(), source_text=None):
    text=str(text); result=[]; events=[]; cursor=output_cursor=0
    if not enabled: return text, events
    restorations = []
    if source_text is not None:
        text, restorations = restore_source_number_style(source_text, text, protected_terms=protected_terms)
    formatting = []
    for event in numeric_events(text, protected_terms=protected_terms):
        if event.kind in ('integer', 'identifier') and re.fullmatch(rf'[{CN}]+', event.source) and int(event.value) < 10:
            continue
        if event.source == event.value:
            continue
        prefix=text[cursor:event.start]; result.extend((prefix,event.value))
        output_cursor+=len(prefix)
        formatting.append({**asdict(event),'output_start':output_cursor,'output_end':output_cursor+len(event.value)})
        output_cursor+=len(event.value);cursor=event.end
    result.append(text[cursor:])
    # Both stages return spans against their actual input and the same final
    # output. Restore records must not retain stale offsets after a prior >=10
    # conversion shortens the string; formatting records map back to input too.
    for event in restorations:
        record = dict(event)
        for field in ('output_start', 'output_end'):
            position = event[field]
            record[field] += sum(len(f['value'])-(f['end']-f['start'])
                                 for f in formatting if f['end'] <= position)
        events.append(record)
    for event in formatting:
        record = dict(event)
        for field in ('start', 'end'):
            position = event[field]
            record[field] -= sum((r['output_end']-r['output_start'])-(r['end']-r['start'])
                                 for r in restorations if r['output_end'] <= position)
        events.append(record)
    events.sort(key=lambda event: (event['start'], event['end']))
    return ''.join(result),events


def numeric_event_values(text):
    return tuple(event.value for event in numeric_events(text))


NUMERIC_CUT_WINDOW = 8


def numeric_unsafe_cut_offsets(text, window=NUMERIC_CUT_WINDOW):
    """Content offsets where cutting the text changes its numeric events.

    2026-10-16 (users: "字幕保真检查未通过" with AI line breaking off): the
    final check compares ``numeric_event_values`` per cue, and a Chinese
    numeral only counts with its context (第/还剩 before it, 个/把/金币 after
    it, or standing alone). Cuts that read fine - 一万｜金币, 一百多｜把,
    还剩｜一条命 - change what each side counts, so splitters avoid them.

    Offset ``b`` is the cut before the b-th content character, the index the
    line breakers use (``content_exact``). Each cut is judged inside a window
    of ``window`` content characters on both sides: the window edges affect
    "cut" and "not cut" alike, so only the cut itself can make a difference.
    """
    from .text_rules import content_exact
    text = str(text)
    positions = [index for index, char in enumerate(text) if content_exact(char)]
    if len(positions) < 2 or len(positions) != len(content_exact(text)):
        return set()
    unsafe = set()
    for offset in range(1, len(positions)):
        cut = positions[offset]
        low = positions[max(0, offset - window)]
        high = positions[min(len(positions), offset + window) - 1] + 1
        if numeric_event_values(text[low:cut]) + numeric_event_values(text[cut:high]) != numeric_event_values(text[low:high]):
            unsafe.add(offset)
    return unsafe


def preference():
    from .runtime import get_runtime_context
    context=get_runtime_context()
    settings=context.asr_settings_snapshot
    if not settings:
        import subtitle_core
        settings=subtitle_core.RUNTIME_SETTINGS
    return bool(settings.get('switches',{}).get('prefer_arabic_numbers',True))


def _number_words(original, formatted, words, events, start, end, confidence):
    """Keep separate numeric event spans even when Chinese digits share no letters."""
    compact = lambda s: re.sub(r'\s', '', s)
    source = compact(original)
    if (not words or compact(''.join(w.text for w in words)) != source
            or any(e.get('kind') == 'source_style_restore' for e in events)):
        from .terminology import remap_words
        return remap_words(original, formatted, words, start, end, confidence)
    from .models import WordUnit
    anchors = [w for w in words for _ in compact(w.text)]
    mapped = []; source_cursor = output_cursor = 0
    for event in events:
        for char in compact(formatted[output_cursor:event['output_start']]):
            mapped.append((char, anchors[source_cursor])); source_cursor += 1
        source_cursor += len(compact(event['source']))
        span = WordUnit(event['audio_start'], event['audio_end'], '', confidence)
        mapped.extend((char, span) for char in compact(event['value']))
        output_cursor = event['output_end']
    for char in compact(formatted[output_cursor:]):
        mapped.append((char, anchors[source_cursor])); source_cursor += 1
    result = []
    for char, anchor in mapped:
        if (result and (result[-1].start,result[-1].end,result[-1].probability)
                == (anchor.start,anchor.end,anchor.probability)):
            result[-1].text += char
        else:
            result.append(WordUnit(anchor.start,anchor.end,char,anchor.probability))
    return result


def format_segment(segment, *, source_text=None, protected_terms=None):
    """Map each replacement back to whole existing word spans, never fake chars."""
    original=segment.text
    if protected_terms is None:
        from .terminology import runtime_snapshot
        protected_terms = runtime_snapshot().canonical_terms
    formatted,events=format_numbers(original,enabled=preference(),protected_terms=protected_terms,source_text=source_text)
    segment.final_text = formatted
    if formatted==original:return
    words=getattr(segment,'words',())
    compact=lambda s: re.sub(r'\s','',s)
    aligned=compact(''.join(w.text for w in words))==compact(original)
    word_spans=[];cursor=0
    if aligned:
        for word in words:
            n=len(compact(word.text));word_spans.append((cursor,cursor+n,word));cursor+=n
    for event in events:
        a=len(compact(original[:event['start']]));b=len(compact(original[:event['end']]))
        hits=[w for x,y,w in word_spans if x<b and a<y]
        event.update(audio_start=min(w.start for w in hits) if hits else segment.start,
                     audio_end=max(w.end for w in hits) if hits else segment.end,
                     timing='existing-word-span' if hits else 'segment-only-no-word-alignment')
    segment.words = _number_words(original,formatted,words,events,segment.start,segment.end,segment.confidence)
    segment.caption_arbitration.setdefault('numeric_formatting',[]).append(
        {'version':RULE_VERSION,'source':original,'result':formatted,'events':events,
         'alignment_provenance':'numeric_local_mapping','requires_acoustic_alignment':True})
    segment.text=formatted


def mapped_content_timeline(segment):
    receipts=getattr(segment,'caption_arbitration',{}).get('numeric_formatting',())
    if not receipts:return None
    receipt=receipts[-1]
    if receipt['result'] != segment.text:return None
    words=getattr(segment,'words',())
    source=receipt['source']; output=receipt['result']
    # 2026-10-16 (user: Japanese task failed with "本地修复的文字与时间单元不一致"):
    # count the same characters as every other text comparison, kana included.
    # Kanji and ASCII alone left a formatted Japanese line with 22 times for 47
    # characters, and the final local re-cut of that line failed the file.
    from .language_rules import CONTENT_CHAR_CLASS
    content=lambda s: ''.join(re.findall(f'[{CONTENT_CHAR_CLASS}]',s))
    # 2026-10-16 (users: "字幕保真检查未通过" with AI line breaking off): a
    # number formatted while the segment's words were still one span
    # ("segment-only-no-word-alignment") has no character timing to map.
    # Mapping it gave every character the whole segment (6 s+), so the line
    # breaker made 5-second single-character cues and the final check failed;
    # None lets the caller use the FireRed character tokens instead.
    if len(words) <= 1 and len(content(output)) > 1:
        return None
    if content(''.join(w.text for w in words)) == content(output):
        from .models import WordUnit
        return [WordUnit(w.start,w.end,ch,w.probability) for w in words for ch in content(w.text)]
    # Conservative receipts (v2 on) all rewrite words with the text; only
    # older receipts fall through to the source mapping below.
    if str(receipt.get('version', '')).startswith('numeric-events-conservative-'):
        return None
    if content(''.join(w.text for w in words))!=content(source):return None
    anchors=[]
    for word in words:
        anchors.extend([word]*len(content(word.text)))
    from .models import WordUnit
    result=[];source_cursor=output_cursor=0
    for event in receipt['events']:
        for ch in output[output_cursor:event['output_start']]:
            if content(ch):
                w=anchors[source_cursor];result.append(WordUnit(w.start,w.end,ch,w.probability));source_cursor+=1
        source_cursor+=len(content(event['source']))
        for ch in event['value']:
            if content(ch):result.append(WordUnit(event['audio_start'],event['audio_end'],ch,segment.confidence))
        output_cursor=event['output_end']
    for ch in output[output_cursor:]:
        if content(ch):
            w=anchors[source_cursor];result.append(WordUnit(w.start,w.end,ch,w.probability));source_cursor+=1
    return result
