import copy
import json
import pytest

from twobyteasr.subtitle_rules.segmentation_profiles import (PROFILES,profile_for,language_tag,
    measure,graphemes,word_spans,task_language_tag)
from twobyteasr.subtitle_rules.language_rules import language_scope,resolve_task_language

SAMPLES={
    'it': "Kimi Antonelli guida l'auto dell'America, sostanzialmente davanti a Verstappen e Leclerc.",
    'es': '¿Qué pasó? ¡Increíble! El Dr. Pérez ganó 1,25 segundos con la versión 2.1.',
    'fr': "L'équipe pense qu'il gagnera aujourd'hui; est-ce vraiment possible avec Jean-Luc?",
    'de': 'Die Donaudampfschifffahrtsgesellschaft verbessert das Ergebnis, weil wir es geschafft haben.',
    'pt': 'Não mudamos a ação nem a posição do João; ele chegou do Brasil com 10,5 segundos.',
    'ru': 'Мы не меняем текст, и перед новым этапом надо сохранить 10,5 секунды и имя Ивана.',
    'en': "Kimi Antonelli didn't change the U.S. version 2.1; pick up 10.5 kg and keep going.",
    'ko': '이 사람은 안 해도 괜찮아요, 하지만 먹어 봐야 할 수 있는 것을 확인해요.',
    'ar': 'هذا النص يبقى بترتيبه المنطقي ولا نعكس الكلمات أو نحذف العلامات العربية.',
    'hi': 'यह कंप्यूटर और हिन्दी की मात्राएँ सुरक्षित रहें, हम पाठ को नहीं बदलते हैं।',
    'vi': 'Hồ Chí Minh nói rằng chúng tôi không thay đổi dấu tiếng Việt và phiên bản 2.1.',
    'th': 'ภาษาไทยไม่มีช่องว่างทุกคำจึงต้องเก็บประโยคเดิมเมื่อยังไม่มีตัวแบ่งคำที่เชื่อถือได้',
    'und': 'Αυτό το άγνωστο κείμενο παραμένει ακριβώς όπως δόθηκε.'}


def segment(text, duration=9., identity=1):
    from twobyteasr.recognition.transcript_data import SpeechSegment
    return SpeechSegment(identity,0,duration,text,.99,[],speaker='speaker')


@pytest.mark.parametrize('code',list(SAMPLES))
def test_actual_local_route_preserves_exact_source_and_graphemes(code):
    import subtitle_core
    from twobyteasr.subtitle_rules.grouping import group_subtitles
    text=SAMPLES[code]
    with language_scope(code):
        cues=group_subtitles([segment(text)],use_ai=False)
    assert ''.join(c.text for c in cues)==text
    parts=[p for c in cues for p in c.source_spans]
    assert ''.join(p['raw_text'] for p in parts)==text
    assert all(p['raw_text']==text[p['char_start']:p['char_end']] for p in parts)
    boundaries={0,*[b for a,b,g in graphemes(text)]}
    assert all(p['char_start'] in boundaries and p['char_end'] in boundaries for p in parts)
    assert all(0<=c.start<c.end<=9.01 for c in cues)


def test_locale_ui_and_translation_target_do_not_change_source_rules():
    assert language_tag('it_IT')=='it-IT'
    assert profile_for('it-IT')==profile_for('it')
    from twobyteasr.subtitle_rules.grouping_request import custom_grouping_guidance,word_grouping_system_prompt
    settings={'grouping_prompts':{'it':'Keep complete Italian clauses.','zh':'中文短句'},
              'appearance':{'language':'zh'},'subtitle_language':{'translation_script':'zh-Hans'}}
    with language_scope('it-IT'):
        assert task_language_tag()=='it-IT'
        assert profile_for(task_language_tag()).hard_max==84
        assert custom_grouping_guidance('it-IT',settings)=='Keep complete Italian clauses.'
        prompt=word_grouping_system_prompt('it')
        assert 'Italian' in prompt and '84' in prompt and 'zero_based_word_index' in prompt
    assert language_tag('pt_br')=='pt-BR' and language_tag('pt-pt')=='pt-PT'
    code,evidence=resolve_task_language('it-IT',['Kimi Antonelli and Verstappen'],asr_detected='Italian')
    assert code=='it' and evidence['locale']=='it-IT'


def test_combining_marks_emoji_apostrophes_and_whitespace_are_lossless():
    import subtitle_core
    from twobyteasr.subtitle_rules.grouping import group_subtitles
    text="L'e\u0301quipe  dell'America 👨‍👩‍👧‍👦 🇮🇹 fa una prova; qu'il reste 1,25 kg."
    with language_scope('fr'):
        cues=group_subtitles([segment(text,6.)],use_ai=False)
    assert ''.join(c.text for c in cues)==text
    assert measure('e\u0301','it')==1 and measure('🇮🇹','it')==1
    assert any("dell'America"==p[2] for p in word_spans(text))
    restored=subtitle_core.deserialize_cues(json.loads(json.dumps(subtitle_core.serialize_cues(cues))))
    assert [c.source_spans for c in restored]==[c.source_spans for c in cues]


def test_one_bad_boundary_does_not_remove_an_independent_good_boundary():
    from twobyteasr.subtitle_rules.english_segmentation import pieces_from_breaks,break_scores,FORBIDDEN_BREAK
    from twobyteasr.subtitle_rules.european_text import lexicon
    tokens=['Questo','funziona,','ma','continuiamo','ancora.']
    scores=break_scores(tokens,lexicon=lexicon('it'))
    good=next(i for i,s in enumerate(scores) if s>FORBIDDEN_BREAK)
    ranges=pieces_from_breaks(tokens,[good,999,-1],lexicon=lexicon('it'))
    assert ranges and (good+1) in [b for a,b in ranges]


def test_indivisible_long_word_does_not_request_ai_or_lose_time():
    from twobyteasr.subtitle_rules.english_segmentation import group_english_with_ai
    from twobyteasr.subtitle_rules.european_text import lexicon
    text='Donaudampfschifffahrtsgesellschaftskapitänsversicherungsverwaltungsgesellschaft'*2
    calls=[]
    with language_scope('de'):
        cues=group_english_with_ai([segment(text,12.)],complete=lambda m:calls.append(m) or '{}',lexicon=lexicon('de'))
    assert not calls and len(cues)==1 and cues[0].text==text and cues[0].end==12.
    import subtitle_core
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    with language_scope('de'):
        finalized=finalize_cues(cues,[segment(text,12.)],[],[],12.,30,subtitle_core)
    assert finalized[0].end==12. and finalized[0].text==text


def test_truncated_response_keeps_only_complete_known_utterances():
    from twobyteasr.subtitle_rules.english_segmentation import parse_ai_breaks,ai_breaks
    from twobyteasr.subtitle_rules.european_text import lexicon
    value=parse_ai_breaks('{"breaks":{"1":[2,5],"2":[],"3":[12,')
    assert value=={'1':[2,5],'2':[]} and value.partial
    duplicate=parse_ai_breaks('{"breaks":{"1":[2],"1":[3],"2":[]}}')
    assert duplicate=={'2':[]} and duplicate.partial
    text=(SAMPLES['it']+' ')*3
    rows=[segment(text,20.,1),segment(text,20.,2)]
    calls=[]
    with language_scope('it'):
        answer=ai_breaks(rows,None,complete=lambda m:calls.append(m) or '{"breaks":{"1":[2],"2":[',lexicon=lexicon('it'))
    assert answer=={'1':[2]} and len(calls)==1


def test_source_and_translation_profiles_keep_stable_cue_ids_separate():
    from twobyteasr.subtitle_rules import subtitle_translation as tr
    batch=tr.TranslationBatch((tr.BatchLine(id='stable-a',text=SAMPLES['it'],speaker='S1',translate=True),
                               tr.BatchLine(id='stable-b',text='Verstappen e Leclerc.',speaker='S1',translate=True)))
    messages=tr.build_messages(batch,source_language='it-IT',target='zh-Hans')
    body=json.loads(messages[1]['content'])
    assert body['output_ids']==['stable-a','stable-b']
    assert body['lines'][0]['text']==SAMPLES['it']
    assert body['language_policies']['source']['language']=='it-IT'
    assert body['language_policies']['source']['unit']=='graphemes_with_spaces'
    assert body['language_policies']['target']['language']=='zh-Hans'
    assert body['language_policies']['target']['unit']=='content_graphemes'
    assert body['language_policies']['target']['display_only'] is True
    assert tr.source_language_of('it-IT')=='it'
    assert tr.normalize_target('pt_br')=='pt-BR' and tr.normalize_target('pt-PT')=='pt-PT'


def test_language_policy_only_invalidates_dependent_grouping_stages():
    import subtitle_core
    from twobyteasr.recognition import cache
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    values={}
    for language in ('it','fr'):
        with activate_runtime_context(RuntimeContext(task_language=language),legacy=subtitle_core):
            values[language]=(cache.cache_stage_signature('audio'),cache.cache_stage_signature('grouped_local'))
    assert values['it'][0]==values['fr'][0]
    assert values['it'][1]!=values['fr'][1]


def test_unknown_short_nonempty_language_has_an_explicit_conservative_policy():
    code,evidence=resolve_task_language('auto',['Αυτό'])
    assert code=='und' and evidence['decided_by']=='unknown_conservative_policy'
    assert profile_for(code).strategy=='conservative'
    assert resolve_task_language('auto',[''])[0]=='zh'
    from types import SimpleNamespace
    from twobyteasr.subtitle_rules.language_rules import project_language
    assert project_language(SimpleNamespace(generation_metadata={'language':{'code':'und'}}))=='und'
