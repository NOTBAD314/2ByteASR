import json
from types import SimpleNamespace
import pytest
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.subtitle_rules.segmentation_profiles import measure, profile_for
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
from twobyteasr.subtitle_rules.sentence_refine_ranges import build_range_replacement

SAMPLE = "And uh but I just also say you what I'm going to do here does require studio."


def project(text=SAMPLE, *, measured=True):
    cue = StudioCue('c132',321039,326720,text)
    p = SubtitleProject(media=StudioMedia(path='fixture.wav',duration_ms=327000), cues=[cue])
    p.generation_metadata['language'] = {'code':'en','requested':'en'}
    p.validate()
    if measured:
        import re
        tokens = list(re.finditer(r'\S+',text))
        # Deliberately uneven observations; no character-ratio timing.
        weights = [1+(i%4) for i in range(len(tokens))]
        total = sum(weights); elapsed=0
        words=[]
        for token, weight in zip(tokens, weights):
            a=321039+round(elapsed/total*5681);elapsed+=weight
            b=321039+round(elapsed/total*5681)
            words.append(dict(text=token.group(),start_ms=a,end_ms=b))
        cue.evidence_refs=['fixture']
        p.asr_evidence['fixture']={'words':words}
    return p


def run(monkeypatch,p,rows):
    calls=[]
    def complete(messages,**kwargs):
        payload=json.loads(messages[-1]['content']);calls.append(payload)
        return json.dumps({'results':[dict(cue_id='c132',**rows[min(len(calls)-1,len(rows)-1)])]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a,**k:SimpleNamespace(complete=complete))
    result=refine_cues_with_llm(p.cues,project=p,runtime_settings={'models':{'group_model':'test'}},boundary_only=True)
    return result,calls


def test_visible_count_and_separate_limits():
    assert len(SAMPLE)==77 and measure(SAMPLE,'en')==77
    assert measure("{\\b1}<i>I'm 3.14</i>\n don't",'en')==14
    assert measure('a '*20,'en')==40
    assert measure('Use {data} and 3.14.','en')==20
    assert profile_for('en').hard_max==40 and profile_for('en').lines==2
    assert profile_for('ja').line_max==13


@pytest.mark.parametrize('size',[39,40,41])
def test_boundaries(monkeypatch,size):
    text='We can play '+('a'*(size-13))+'.'
    p=project(text)
    result,calls=run(monkeypatch,p,[dict(action='keep')])
    if size<=40:
        assert len(calls)==1 and result.actions[0].action in {'keep','wrap'}
    else:
        assert len(calls)==2 and result.actions[0].action=='split'


def test_unchanged_ai_retries_then_exact_measured_split(monkeypatch):
    p=project();result,calls=run(monkeypatch,p,[dict(action='keep')])
    assert len(calls)==2 and calls[1]['repair']['errors'][0]['category']=='constraint_conflict'
    assert calls[0]['cues'][0]['length_and_layout']['cue_max']==40
    assert result.llm_status=='completed' and result.results['c132']['local_fallback']
    replacement=build_range_replacement(result.ranges[0], result.actions[0], p, set())
    assert ''.join(c.text for c in replacement).replace('\n','')==SAMPLE
    assert all(measure(c.text,'en')<=40 for c in replacement)
    assert replacement[0].start_ms==321039 and replacement[-1].end_ms==326720
    measured={w['start_ms'] for w in p.asr_evidence['fixture']['words']}
    assert all(c.start_ms in measured for c in replacement)


def test_valid_ai_boundaries_retained(monkeypatch):
    text='We played the game for hours. Then we went home.'
    p=project(text);edges=[text.index('.')]
    result,calls=run(monkeypatch,p,[dict(action='split',split_after_chars=edges)])
    assert len(calls)==1 and result.actions[0].split_after_chars==edges


def test_bad_inside_word_does_not_destroy_contraction(monkeypatch):
    p=project();result,calls=run(monkeypatch,p,[dict(action='split',split_after_chars=[SAMPLE.index("I'm")])])
    assert len(calls)==2
    replacement=build_range_replacement(result.ranges[0], result.actions[0], p, set())
    assert any("I'm" in c.text for c in replacement)


def test_missing_timing_only_wraps_and_reports_pending(monkeypatch):
    p=project(measured=False);result,calls=run(monkeypatch,p,[dict(action='keep')])
    assert result.actions[0].action=='wrap' and result.actions[0].alignment_pending
    replacement=build_range_replacement(result.ranges[0],result.actions[0],p,set())
    assert len(replacement)==1 and replacement[0].text.replace('\n','')==SAMPLE
    assert (replacement[0].start_ms,replacement[0].end_ms)==(321039,326720)
    assert result.results['c132']['alignment_pending']


def test_indivisible_url_fails_honestly(monkeypatch):
    p=project('https://example.com/'+('unbreakable'*9),measured=False)
    result,calls=run(monkeypatch,p,[dict(action='keep')])
    assert result.llm_status=='failed' and not result.actions
    assert result.results['c132']['category']=='indivisible_overflow'


def test_clear_english_text_not_ui_or_legacy_cjk_language(monkeypatch):
    p=project();p.generation_metadata['language']={'code':'zh','requested':'zh'}
    result,calls=run(monkeypatch,p,[dict(action='keep')])
    assert calls[0]['cues'][0]['language_policy']['language']=='en'
    assert len(result.actions[0].split_after_chars)>0


def test_preserve_authored_size_and_maximum_lines(monkeypatch):
    p=project();p.styles[0].font_size=120
    original=p.styles[0].font_size
    result,calls=run(monkeypatch,p,[dict(action='keep')])
    assert p.styles[0].font_size==original
    replacement=build_range_replacement(result.ranges[0],result.actions[0],p,set())
    assert all(len(c.text.splitlines())<=2 for c in replacement)


def test_translation_layout_command_keeps_source_and_undo():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.translation_sentence_refine import TranslationLayoutCommand
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual,_empty_container,normalize_target
    app=QApplication.instance() or QApplication([])
    p=project('このゲームはとても面白いです',measured=False)
    p.generation_metadata['language']={'code':'ja','requested':'ja'}
    p.generation_metadata['translation_records']=_empty_container(normalize_target('en'))
    set_manual(p,'c132',SAMPLE,target='en')
    command=TranslationLayoutCommand(p,{'c132':SAMPLE.replace(' what','\nwhat')})
    command.redo();command.undo()  # Python exceptions must not escape a C++ undo virtual.
    stack=QUndoStack();stack.push(command)
    assert '\n' in p.generation_metadata['translations']['c132']
    assert p.cues[0].text=='このゲームはとても面白いです'
    stack.undo();assert p.generation_metadata['translations']['c132']==SAMPLE
    stack.redo();assert '\n' in p.generation_metadata['translations']['c132']
