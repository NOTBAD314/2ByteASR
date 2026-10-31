import pytest
from twobyteasr.recognition.transcript_fidelity import transcript_spans, word_tokens
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context


def convert(text, pieces, speakers=None):
    from twobyteasr.recognition.asr import _api_transcription_rows
    words = [dict(start=i/10, end=(i+1)/10, text=t, speaker=(speakers or ['A']*len(pieces))[i])
             for i,t in enumerate(pieces)]
    result = dict(segments=[dict(start=0,end=len(pieces)/10,text=text,speaker='A')], words=words,
                  timestamp_source='qwen31_native')
    with activate_runtime_context(RuntimeContext(task_language='it')):
        return _api_transcription_rows(result, dict(start=0,end=len(pieces)/10))


def test_provider_subwords_are_not_words():
    rows = convert('Andrea Kimi Antonelli, sostanzialmente.',
                   [' Andrea',' Kim','i',' Anton','elli',',',' sost','anz','ial','mente','.'])
    assert rows[0]['text'] == 'Andrea Kimi Antonelli, sostanzialmente.'
    assert [t['text'] for t in rows[0]['tokens']] == ['Andrea','Kimi','Antonelli','sostanzialmente']
    assert rows[0]['tokens'][1]['start'] == .1
    assert rows[0]['tokens'][1]['end'] == .3


def test_numbers_accents_apostrophes_and_normal_spaces():
    text="e Max Verstappen si è risolto al 49esimo con Leclerc e l'acqua."
    pieces=['e',' Max',' Verst','appen',' si',' è',' risol','to',' al',' 4','9','esimo',' con',' Le','clerc'," e l'",'acqua.']
    rows=convert(text,pieces)
    assert rows[0]['text']==text
    assert '49esimo' in [t['text'] for t in rows[0]['tokens']]
    assert 'Max Verstappen' in rows[0]['text']
    assert transcript_spans('e è',['è',' e']) is None


def test_speaker_boundaries_do_not_merge_or_steal_words():
    rows=convert('Ciao Luca. Ciao Matteo.', [' Ciao',' Luca.',' Ciao',' Matteo.'],['A','A','B','B'])
    assert [r['text'] for r in rows]==['Ciao Luca.','Ciao Matteo.']
    assert [r['speaker'] for r in rows]==['A','B']
    assert rows[0]['end'] <= rows[1]['start']


def test_mismatched_words_retain_full_sentence_without_false_word_timing():
    rows=convert('Non è mondiale.', [' Non',' è'])
    assert rows[0]['text']=='Non è mondiale.'
    assert not rows[0].get('tokens')


def test_cjk_tokens_are_not_merged_as_latin_subwords():
    tokens=[dict(start=0,end=.1,text='你'),dict(start=.1,end=.2,text='好')]
    assert len(word_tokens('你好',tokens))==2


def test_bare_english_provider_uses_transcript_boundaries():
    rows=convert('Hello everyone.', ['Hello','everyone.'])
    assert rows[0]['text']=='Hello everyone.'
    assert [t['text'] for t in rows[0]['tokens']]==['Hello','everyone']
