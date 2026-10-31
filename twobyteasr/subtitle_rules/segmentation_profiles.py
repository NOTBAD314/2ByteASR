"""One language policy for prompts, local boundaries, validation and caches.

Recognition-model capabilities remain in language_rules. A processing policy
does not claim that a local recognizer supports the language.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import hashlib
import json
import re
import unicodedata

VERSION = 'subtitle-language-policy-v1'
SPAN_VERSION = 'source-codepoint-spans-v1'


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    script: str
    strategy: str
    unit: str
    preferred: float
    soft_max: float
    hard_max: float
    max_seconds: float
    lines: int
    line_max: float
    comfortable_cps: float
    warning_cps: float
    critical_cps: float
    guidance: str
    dedicated: bool = True
    long_pause_seconds: float = 3.
    min_seconds: float = .8
    line_preferred: float = 32.
    minimum_units: float = 8.
    source_contiguity_max_gap: float = 2.

    @property
    def fingerprint(self):
        data = dict(asdict(self), version=VERSION, spans=SPAN_VERSION)
        return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]

    @property
    def index_unit(self):
        return 'content_exact_unicode_codepoint' if self.strategy == 'cjk' else 'zero_based_word_index'


_SPECIFIC = {
    'en': ('English', 'Latin', "Keep complete words, contractions, abbreviations (Dr., U.S.), phrasal verbs, names, decimal numbers and units. Prefer sentences, clauses and measured pauses; avoid stranded articles, auxiliaries and prepositions."),
    'it': ('Italian', 'Latin', "Keep Italian words, accents and apostrophe forms intact: l'auto, dell'America, perché, è. Keep person names together when feasible. Prefer complete phrases/clauses and real pauses; do not strand articles, prepositions or non before its verb."),
    'es': ('Spanish', 'Latin', "Preserve accents, ñ, complete words, contractions al/del, abbreviations and decimal punctuation. Keep ¿/¡ with the following question/exclamation and closing punctuation with the preceding phrase. Do not strand articles, prepositions or tightly connected phrases."),
    'fr': ('French', 'Latin', "Keep apostrophe contractions and connected hyphen forms intact: l'équipe, qu'il, aujourd'hui, est-ce. Do not isolate clitics or leave determiners/prepositions at a subtitle edge. Prefer complete clauses and measured pauses."),
    'de': ('German', 'Latin', "Never split a German compound word by character count. Capitalization of nouns alone does not establish a name. Prefer clauses and real pauses; keep articles/prepositions with their phrase and clause-final auxiliaries with the verb where feasible."),
    'pt': ('Portuguese', 'Latin', "Preserve accents, nasal signs, contractions and connected forms: não, ação, do/da, pelo. Keep the selected pt-BR/pt-PT locale; do not change spelling or vocabulary. Prefer phrases and clauses, preserving names, numbers and units."),
    'ru': ('Russian', 'Cyrillic', "Use actual whitespace word boundaries in Cyrillic; preserve abbreviations, punctuation, names, quantities and units. Avoid isolated short prepositions/particles and keep не with its verb when feasible. Prefer complete clauses and measured pauses."),
}
PROFILES = {
    'zh': LanguageProfile('zh','Chinese','Han','cjk','content_graphemes',10,12,16,5.,1,16,8,9,12,
        '中文按完整口语成分和真实气口断句，保护词语、姓名、数字、单位和混合语言完整单词；保留原文重复。常见5–10个可计数字符，软上限12，必要时保留完整成分，最多16。'),
    'ja': LanguageProfile('ja','Japanese','Japanese','cjk','content_graphemes',18,22,26,7.,2,13,8,10,13,
        '日本語は文節・節と実際の間を優先し、漢字と送り仮名、助詞、助動詞、連体詞と名詞を不自然に切り離さない。固有名詞・数字・単位・混在する単語を保護し、本文は一字も変えない。'),
    'ko': LanguageProfile('ko','Korean','Hangul','eojeol','hangul_display_units',24,28,32,7.,2,16,12,14,18,
        '한국어는 어절·구·절과 실제 쉼을 기준으로 나눈다. 음절이나 어미 내부를 자르지 않는다. 보조 용언, 의존 명사, 관형사, 수와 단위, 안/못과 서술어를 보호한다. 한글 음절은1, 공백·라틴문자·숫자·문장부호는0.5 단위로 센다.'),
}
for _code, (_name,_script,_guidance) in _SPECIFIC.items():
    # Existing two-line policy shared by these spaced languages, measured in
    # display graphemes including spaces, never a fixed number of words.
    PROFILES[_code] = LanguageProfile(_code,_name,_script,'space','graphemes_with_spaces',60,72,84,7.,2,42,17,20,25,_guidance)
PROFILES['ru']=replace(PROFILES['ru'],preferred=56,soft_max=68,hard_max=78,line_max=39)
PROFILES['ru']=replace(PROFILES['ru'],line_preferred=30)
PROFILES['ko']=replace(PROFILES['ko'],line_preferred=12,minimum_units=4)
for _code,_name,_script,_strategy,_guidance in (
    ('ar','Arabic','Arabic','space','Generic Unicode word-boundary policy: preserve logical RTL order and diacritics. Never reverse text. This is not a specialized Arabic syntactic segmenter.'),
    ('hi','Hindi','Devanagari','space','Generic whitespace/Unicode-grapheme policy: preserve conjuncts, matras, names, quantities and units. This is not a specialized Hindi syntactic segmenter.'),
    ('vi','Vietnamese','Latin','space','Generic whitespace and grapheme policy: preserve all tone marks and mixed-language names. Whitespace syllables are not claimed to be complete lexical words; prefer sentence/phrase pauses conservatively.'),
    ('th','Thai','Thai','conservative','No reliable Thai lexical tokenizer is configured. Retain the source utterance unless trusted source boundaries/speaker changes require a split; never claim character cuts are word segmentation.'),
    ('und','Unspecified Unicode','Unicode','conservative','Unknown language: retain original utterance and grapheme integrity; use only reliable source/speaker/pause boundaries. Never silently use Chinese short-character limits.')):
    PROFILES[_code] = LanguageProfile(_code,_name,_script,_strategy,'graphemes_with_spaces',60,72,84,7.,2,42,17,20,25,_guidance,False)

_ALIASES = {'chinese':'zh','cn':'zh','jp':'ja','japanese':'ja','english':'en','eng':'en',
    'italian':'it','ita':'it','spanish':'es','spa':'es','german':'de','deu':'de','ger':'de',
    'french':'fr','fra':'fr','fre':'fr','portuguese':'pt','por':'pt','russian':'ru','rus':'ru',
    'korean':'ko','kor':'ko','kr':'ko','arabic':'ar','hindi':'hi','vietnamese':'vi','thai':'th'}


def language_tag(value):
    text = str(value or '').strip().replace('_','-')
    parts = text.split('-')
    base = _ALIASES.get(parts[0].lower(),parts[0].lower())
    if base in ('','auto','und'):return 'und'
    if base not in PROFILES:return 'und'
    suffix = [p.title() if len(p)==4 else p.upper() if len(p)==2 else p for p in parts[1:]]
    return '-'.join([base,*suffix])


def profile_for(language):
    return PROFILES[language_tag(language).split('-')[0]]


def task_language_tag(default=None):
    from .language_rules import active_task_language, _SCOPE
    scoped=getattr(_SCOPE,'language_tag',None)
    current=active_task_language() or default
    base=language_tag(current) if current else 'zh'  # legacy unlabelled Chinese projects
    if scoped:return scoped
    try:
        from ..recognition.run_context import get_runtime_context
        context=get_runtime_context()
        evidence=getattr(context,'language_evidence',{}) or {}
        requested=(context.asr_settings_snapshot.get('subtitle_language') or {}).get('recognition_language')
        for raw in (evidence.get('locale'),evidence.get('requested_locale'),requested):
            tag=language_tag(raw)
            if tag!='und' and tag.split('-')[0]==base.split('-')[0]:return tag
    except (AttributeError,TypeError):
        pass
    return base


def current_profile():
    return profile_for(task_language_tag())


def prompt_languages():
    codes = ('zh','ja','en','it','es','fr','de','pt','pt-BR','pt-PT','ru','ko','ar','hi','vi','th','und')
    labels = {'zh':'中文字幕','ja':'日语字幕','en':'英语字幕','it':'意大利语字幕','es':'西班牙语字幕',
        'fr':'法语字幕','de':'德语字幕','pt':'葡萄牙语字幕','pt-BR':'葡萄牙语（巴西）字幕','pt-PT':'葡萄牙语（葡萄牙）字幕',
        'ru':'俄语字幕','ko':'韩语字幕','ar':'阿拉伯语（通用策略）','hi':'印地语（通用策略）',
        'vi':'越南语（通用策略）','th':'泰语（保守策略）','und':'其他语言（保守策略）'}
    return tuple((c,labels[c]) for c in codes)


def canonical_prompt_values(values):
    """Known aliases migrate without losing raw/unknown custom entries."""
    if not isinstance(values,dict):return {}
    result=dict(values)
    for key,value in values.items():
        tag=language_tag(key)
        if tag!='und' or str(key).lower() in ('und','auto'):
            if tag not in values:result[tag]=value
    return result


def graphemes(text):
    try:
        import regex
        return [(m.start(),m.end(),m.group()) for m in regex.finditer(r'\X',str(text))]
    except ImportError:
        # Conservative fallback: combine marks, ZWJ sequences and virama
        # conjuncts; no reliable lexical boundaries are invented.
        result=[];start=0;previous=''
        for i,ch in enumerate(str(text)):
            regional=0x1f1e6<=ord(ch)<=0x1f1ff
            previous_regional=bool(previous and 0x1f1e6<=ord(previous)<=0x1f1ff)
            joins=bool(i and (unicodedata.category(ch).startswith('M') or ch in '\u200d\ufe0f\ufe0e'
                or 0x1f3fb<=ord(ch)<=0x1f3ff or regional and previous_regional and i-start==1
                or previous=='\u200d' or 'VIRAMA' in unicodedata.name(previous,'')))
            if i and not joins:
                result.append((start,i,str(text)[start:i]));start=i
            previous=ch
        if text:result.append((start,len(text),str(text)[start:]))
        return result


def measure(text, language):
    profile=profile_for(language)
    clusters=[g for _,_,g in graphemes(str(text).strip())]
    if profile.unit=='content_graphemes':
        return sum(any(ch.isalnum() or ch in '々ー' for ch in g) for g in clusters)
    if profile.unit=='hangul_display_units':
        return sum(1. if any(unicodedata.east_asian_width(ch) in ('F','W') and not ch.isascii()
            and not unicodedata.category(ch).startswith(('P','S','Z')) for ch in g) else .5 for g in clusters)
    return len(clusters)


def word_spans(text):
    # A separator with attached combining marks is one indivisible cluster.
    # It belongs to a boundary, not to the next word's character index.
    result=[];start=None;end=0
    for a,b,cluster in graphemes(text):
        if cluster[0].isspace():
            if start is not None:result.append((start,end,str(text)[start:end]));start=None
        else:
            if start is None:start=a
            end=b
    if start is not None:result.append((start,end,str(text)[start:end]))
    return result


def slice_word_pieces(text, pieces):
    """Exact, contiguous source spans. Boundary whitespace belongs to the left."""
    spans=word_spans(text)
    result=[];cursor=0
    for first,last in pieces:
        end=spans[last][0] if last<len(spans) else len(text)
        result.append((cursor,end,text[cursor:end]));cursor=end
    if cursor!=len(text) or ''.join(p[2] for p in result)!=text:
        raise ValueError('Word boundaries did not conserve the exact source text')
    return result


def fixed_constraints(language,*,index_unit=None):
    p=profile_for(language)
    return (f'Effective language: {language_tag(language)}; policy {VERSION}/{p.fingerprint}. '
        f'Length unit: {p.unit}; preferred {p.preferred:g}, soft {p.soft_max:g}, '
        f'cue maximum {p.hard_max:g}, at most {p.lines} display lines of {p.line_max:g} units; '
        f'duration maximum {p.max_seconds:g}s, reading comfort/warning/critical {p.comfortable_cps:g}/{p.warning_cps:g}/{p.critical_cps:g} units/s. '
        f'Index unit: {index_unit or p.index_unit}; source spans use Python Unicode code points, never UTF-16 positions. '
        'Only choose supplied legal boundaries. Do not rewrite, translate, correct spelling, add punctuation or remove repetitions. '
        f'Speaker changes and confirmed pauses >= {p.long_pause_seconds:g}s are mandatory. '
        f'Distinct source records separated by more than {p.source_contiguity_max_gap:g}s cannot be merged as contiguous evidence. '
        'Never split a grapheme or a whole word. An indivisible atom over a limit is retained with a local warning; '
        'do not loop requests or reject other valid utterances. Timed-cue boundaries and display line wrapping are different operations.')


def indivisible(text,language):
    p=profile_for(language)
    if p.strategy=='conservative':return True
    tokens=[w[2] for w in word_spans(text)]
    if len(tokens)<2:return True
    if p.code=='ko':
        from .korean_segmentation import break_scores,FORBIDDEN_BREAK
        scores=break_scores(tokens)
    else:
        from .english_segmentation import break_scores,FORBIDDEN_BREAK
        from .european_text import lexicon
        scores=break_scores(tokens,lexicon=lexicon(p.code) if p.code!='en' else None)
    return not any(score>FORBIDDEN_BREAK for score in scores)


def legal_raw_boundaries(text,language):
    """End-exclusive source positions; never token IDs or Qt UTF-16 offsets."""
    p=profile_for(language)
    clusters={b for a,b,g in graphemes(text) if b<len(text)}
    if p.strategy=='conservative':return set()
    if p.strategy=='cjk':return clusters
    spans=word_spans(text)
    tokens=[w[2] for w in spans]
    if p.code=='ko':
        from .korean_segmentation import break_scores,FORBIDDEN_BREAK
        scores=break_scores(tokens)
    else:
        from .english_segmentation import break_scores,FORBIDDEN_BREAK
        from .european_text import lexicon
        scores=break_scores(tokens,lexicon=lexicon(p.code) if p.code!='en' else None)
    allowed=set()
    for i,score in enumerate(scores):
        if score>FORBIDDEN_BREAK:
            allowed.update((spans[i][1],spans[i+1][0]))
    return allowed&clusters


def project_language_tag(project):
    value=(getattr(project,'generation_metadata',{}) or {}).get('language') or {}
    if isinstance(value,dict):
        evidence=value.get('evidence') or {}
        raw=value.get('locale') or evidence.get('locale') or value.get('code')
    else:raw=value
    return language_tag(raw)


def unit_label(language):
    unit=profile_for(language).unit
    return {'content_graphemes':'可计数字符（组合字符算一个）',
        'graphemes_with_spaces':'可见字符（含内部空格，组合字符算一个）',
        'hangul_display_units':'韩语显示单位（韩字1、空格/拉丁字母/数字0.5）'}[unit]
