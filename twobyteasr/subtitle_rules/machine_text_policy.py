"""Default machine-edit protection; human editing and undo stay unrestricted."""
from difflib import SequenceMatcher
import re
from .pronouns import NON_PRONOUN_WORDS

VERSION='machine-text-protection-v2-normal-responses'
_WORDS=('我们','你们','他们','她们','它们','咱们','这里','那里','这个','那个','这些','那些','他','她','它','我','你','您','咱','这','那')
_TOKENS=re.compile('|'.join(map(re.escape,sorted(_WORDS,key=len,reverse=True))))
_RESPONSE=re.compile(r'(?:好|行|对|嗯|是的|是|可以|试试|没事|好的|行的|对的)+(?:吧|啊|呀|哦)?')
_EXCLUDED=re.compile('|'.join(map(re.escape,(*NON_PRONOUN_WORDS,'维他命','自我','忘我','无我','迷你','那曲'))))

def protected_spans(text):
    excluded=[m.span() for m in _EXCLUDED.finditer(text)]
    return [(m.start(),m.end(),m.group()) for m in _TOKENS.finditer(text)
            if not any(a<=m.start() and m.end()<=b for a,b in excluded)]

def protected_deletions(original, proposed):
    if not isinstance(original,str) or not isinstance(proposed,str):return ('invalid_candidate',)
    compact=lambda text:re.sub(r'[\W_]+','',text,flags=re.UNICODE)
    before,after=compact(original),compact(proposed)
    if len(before)<=12 and _RESPONSE.fullmatch(before) and len(after)<len(before):
        return ('normal_spoken_response',)
    protected=protected_spans(original)
    removed=[]
    for tag,a,b,c,d in SequenceMatcher(None,original,proposed,autojunk=False).get_opcodes():
        if tag=='delete' or tag=='replace' and len(proposed[c:d])<len(original[a:b]):
            removed.extend(word for start,end,word in protected if start<b and a<end)
    return tuple(dict.fromkeys(removed))

def machine_text_allowed(original, proposed):
    return isinstance(proposed,str) and not protected_deletions(original,proposed)

def compliant_candidate(original, proposed):
    """Keep independent valid edits; reject an inseparable compound edit."""
    if not isinstance(proposed,str):return original
    value=original
    for tag,a,b,c,d in reversed(SequenceMatcher(None,original,proposed,autojunk=False).get_opcodes()):
        if tag=='equal':continue
        candidate=original[:a]+proposed[c:d]+original[b:]
        if machine_text_allowed(original,candidate):value=value[:a]+proposed[c:d]+value[b:]
    return value
