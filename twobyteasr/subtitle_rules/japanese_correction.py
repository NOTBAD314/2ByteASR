"""Japanese writing equivalence and evidence decisions, separate from Chinese length rules."""
import re
import unicodedata


def kana_form(text):
    text=unicodedata.normalize('NFKC',text)
    return ''.join(chr(ord(c)-0x60) if 'ァ'<=c<='ヶ' else c for c in text)


def preserves_final_particle(source,target):
    a=re.search(r'(のに|けど|って|ね|よ|さ)[ーっ…]*(?:[。！？!?\s]*)$',source)
    return a is None or bool(re.search(re.escape(a.group(1))+r'[ーっ…]*(?:[。！？!?\s]*)$',target))


def assess_patch(source,target,independent_sources,terms=()):
    if kana_form(source)==kana_form(target):
        return 'keep','equivalent_kana_notation'
    from .number_fidelity import numeric_events
    a,b=numeric_events(source),numeric_events(target)
    if (a and b and tuple(e.value for e in a)==tuple(e.value for e in b)
            and re.sub(r'[\d零〇一二三四五六七八九十百千万億]+','',source)
                == re.sub(r'[\d零〇一二三四五六七八九十百千万億]+','',target)):
        return 'keep','equivalent_numeric_notation'
    if any(t.get('status')=='confirmed' and t.get('canonical')==target and source in t.get('aliases',())
           and not t.get('ambiguous') for t in terms):
        return 'accept','confirmed_exact_japanese_alias'
    if not preserves_final_particle(source,target):
        return 'review','japanese_particle_preservation'
    def family_of(value):
        value=str(value).casefold()
        if any(part in value for part in ('align','ctc','forced','llm','polish','current')):return ''
        return 'review' if value.startswith('qwen') or value=='review' else value
    families={family_of(family) for family,text in independent_sources if target in text and source not in text}-{''}
    if len(families)>=2 and max(len(source),len(target))<=24:
        return 'accept','independent_local_japanese_transcripts'
    # nagisa supplies segmentation/POS, not a pronunciation dictionary. A
    # kana/kanji change may preserve sound but may also change meaning. Keep
    # an anchored one-model candidate for explicit acceptance, never pretend
    # Chinese pinyin or a character-count change establishes Japanese truth.
    return 'review','japanese_semantic_needs_listening'
