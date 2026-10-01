"""Ordered numeric events: spelling changes never perform arithmetic or dedup."""
import re
from dataclasses import dataclass, asdict

RULE_VERSION = 'numeric-events-v1'
DIGITS = dict(zip('零〇一二两三四五六七八九', (0,0,1,2,2,3,4,5,6,7,8,9)))
UNITS = {'十':10,'百':100,'千':1000,'万':10000,'亿':100000000}
CN = '零〇一二两三四五六七八九十百千万亿'
TOKEN = re.compile(rf'(?:百分之)?(?:\d+(?:\.\d+)*(?:[万亿])?|[{CN}]+(?:点[零〇一二两三四五六七八九]+)*)(?:[%％])?')
FIXED = re.compile(r'一会儿?|一点(?:也|都|不)|死路一条|一丝不苟|一心一意|三心二意|七上八下|乱七八糟|说一不二|万一|万物|统一|一起|一切|一般|一定|一下|一直|一试|一样|两位数|三国|七日杀|最终幻想十四')
CLOCK = re.compile(rf'[{CN}0-9]+点(?:半|[{CN}0-9]+分(?:[{CN}0-9]+秒)?)')
COUNTERS = '个张卡局颗刀抽层次只套发星年月日号分秒块元岁级把轮种位件台条枚份瓶杯米段小时倍'


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


def numeric_events(text, *, protected_terms=()):
    text=str(text)
    protected=[m.span() for pattern in (FIXED, CLOCK) for m in pattern.finditer(text)]
    protected.extend(m.span() for term in protected_terms if term for m in re.finditer(re.escape(term),text))
    result=[]
    for match in TOKEN.finditer(text):
        start,end=match.span(); raw=match.group()
        if any(a<end and start<b for a,b in protected): continue
        before=text[start-1:start]; after=text[end:end+1]
        if before=='几' or after=='几': continue
        percent=raw.startswith('百分之') or raw.endswith(('%','％'))
        body=raw.removeprefix('百分之').rstrip('%％')
        if body=='一' and after in ('个','种','次') and not text[:start].endswith(('只有','一共','还剩','仅有')):
            continue  # indefinite article: 一个办法/一种感觉, not an asserted count
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
        clear=(bool(re.search(r'\d|[十百千万亿点]',body)) or percent or before=='第'
               or text[:start].endswith(('编号','号码','版本','概率','伤害','威力'))
               or bool(after and after in COUNTERS) or (not before or before.isspace() or before in '，,、')
               and (not after or after.isspace() or after in '，,、'))
        if clear: result.append(NumericEvent(start,end,raw,value+('%' if percent else '')))
    return result


def format_numbers(text, *, enabled=True, protected_terms=()):
    text=str(text); result=[]; events=[]; cursor=output_cursor=0
    if not enabled: return text, events
    for event in numeric_events(text, protected_terms=protected_terms):
        prefix=text[cursor:event.start]; result.extend((prefix,event.value))
        output_cursor+=len(prefix)
        events.append({**asdict(event),'output_start':output_cursor,'output_end':output_cursor+len(event.value)})
        output_cursor+=len(event.value);cursor=event.end
    result.append(text[cursor:])
    return ''.join(result),events


def numeric_event_values(text):
    return tuple(event.value for event in numeric_events(text))


def preference():
    from .runtime import get_runtime_context
    context=get_runtime_context()
    settings=context.asr_settings_snapshot
    if not settings:
        import subtitle_core
        settings=subtitle_core.RUNTIME_SETTINGS
    return bool(settings.get('switches',{}).get('prefer_arabic_numbers',True))


def format_segment(segment):
    """Map each replacement back to whole existing word spans, never fake chars."""
    original=segment.text
    formatted,events=format_numbers(original,enabled=preference())
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
    segment.caption_arbitration.setdefault('numeric_formatting',[]).append(
        {'version':RULE_VERSION,'source':original,'result':formatted,'events':events})
    segment.text=formatted


def mapped_content_timeline(segment):
    receipts=getattr(segment,'caption_arbitration',{}).get('numeric_formatting',())
    if not receipts:return None
    receipt=receipts[-1]
    if receipt['result'] != segment.text:return None
    words=getattr(segment,'words',())
    source=receipt['source']; output=receipt['result']
    content=lambda s: ''.join(re.findall(r'[\u3400-\u9fffA-Za-z0-9]',s))
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
