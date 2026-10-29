"""Only independent corroboration repairs a weak word onset, never a global shift."""
from types import SimpleNamespace
from twobyteasr.recognition.ctc_alignment import disputed_char_start, propose

def evidence():
    fields = ['char_start', 'start_basis', 'start_ms', 'end_ms', 'start_p', 'start_local']
    return dict(unit_fields=fields, units_word=[[0, 'model', 13493, 13813, .2104, .2825]],
                units_char=[[0, 'model', 12773, 12933, .4351, .7657]])

def rows():
    return [SimpleNamespace(id='1', start_ms=11553, end_ms=13472, speaker='A'),
            SimpleNamespace(id='2', start_ms=13472, end_ms=14014, speaker='A'),
            SimpleNamespace(id='overlap', start_ms=12500, end_ms=13200, speaker='B')]

def test_original_boundary_requires_ctc_plus_reliable_character_pass():
    alt = disputed_char_start(evidence())
    assert alt == 12773
    assert not propose(rows(), {'2':12864}, lambda r:13493)
    changes = propose(rows(), {'2':12864}, lambda r:13493, alternate_start=lambda r:alt)
    assert len(changes) == 1
    assert (changes[0].new_ms, changes[0].followers) == (12864, (('1',12864),))
    assert changes[0].reference == 'aligner_char_conflict'
    assert not propose(rows(), {'2':12200}, lambda r:13493, alternate_start=lambda r:alt)

def test_high_confidence_word_and_repaired_character_are_not_overridden():
    a=evidence(); a['units_word'][0][4]=.6
    assert disputed_char_start(a) is None
    a=evidence(); a['units_char'][0][1]='nearest'
    assert disputed_char_start(a) is None

def test_edited_cue_does_not_reuse_old_disputed_evidence():
    from twobyteasr.studio.studio_ctc_refine import _alternate_start
    cue=SimpleNamespace(evidence_refs=['cue-align:2'],text='スラマッパギー',start_ms=13472,end_ms=14014)
    p=SimpleNamespace(asr_evidence={'cue-align:2':dict(text=cue.text,start_ms=13472,end_ms=14014,
        caption_arbitration={'forced_alignment':evidence()})})
    assert _alternate_start(p,cue)==12773
    cue.start_ms=12900
    assert _alternate_start(p,cue) is None


def test_corroborated_word_onset_is_atomic_and_undo_restores_evidence():
    import copy
    from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
    from twobyteasr.studio.studio_ctc_refine import RefineStartsCommand
    from twobyteasr.timeline.studio_caption_timeline import KEY
    p=SubtitleProject(media=StudioMedia(path='missing.mp4'),cues=[StudioCue('1',11553,13472,'ミオちゃんマイちゃん',speaker_id='A'),
                           StudioCue('2',13472,14014,'スラマッパギー',speaker_id='A')])
    p.render_settings['_cue_domain']='timeline'
    word=dict(text=p.cues[1].text,start_ms=13493,end_ms=13813,char_start=0,char_end=7,evidence_ref='cue-align:2')
    receipt=dict(text=p.cues[1].text,word_alignment='exact_token_text',words=[word],
        word_base_interval=[13472,14014],word_base_words=[copy.deepcopy(word)])
    p.studio_state[KEY]=dict(version=1,instances={'2':receipt})
    before=copy.deepcopy(p.studio_state[KEY]); raw=copy.deepcopy(p.asr_evidence)
    change=propose(rows(),{'2':12864},lambda r:13493,alternate_start=lambda r:12773)
    command=RefineStartsCommand(p,change); command.redo()
    assert p.cues[0].end_ms==p.cues[1].start_ms==12864
    assert p.studio_state[KEY]['instances']['2']['words'][0]['start_ms']==12864
    assert p.asr_evidence==raw
    command.undo()
    assert p.cues[0].end_ms==p.cues[1].start_ms==13472
    assert p.studio_state[KEY]['instances']['2']['words'][0]==word
    command.redo()
    assert p.studio_state[KEY]['instances']['2']['words'][0]['start_ms']==12864
