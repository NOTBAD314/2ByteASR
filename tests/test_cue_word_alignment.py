import copy
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.cue_word_alignment import cue_words
from twobyteasr.studio_timing import resolve_split
from twobyteasr.sentence_refine import allocate_split_times, build_replacement_cues, CueRefineAction
from twobyteasr.studio_commands import split_cue_command


def project(text='啊，这个 FPS60 好好', words=None):
    words = words or [('前句', 0, 70), ('啊', 100, 200), ('这个', 600, 900),
                      ('FPS60', 950, 1300), ('好', 1400, 1550), ('好', 1600, 1750)]
    cue = StudioCue('a', 100, 1800, text, evidence_refs=['segment'])
    return SubtitleProject(media=StudioMedia(path='missing.mp4',duration_ms=3000),cues=[cue],
        asr_evidence={'segment': {'words': [dict(text=t,start_ms=a,end_ms=b) for t,a,b in words]}})


def test_subcue_mapping_excludes_parent_prefix_punctuation_and_spaces():
    p=project(); words, reason=cue_words(p,p.cues[0])
    assert reason == 'exact_token_text'
    assert [(w.text,w.char_start,w.start_ms) for w in words][:3] == [('啊',0,100),('这个',2,600),('fps60',5,950)]
    timing, estimated=allocate_split_times(p.cues[0],[1],project=p)
    assert timing==[(100,200),(600,1800)] and not estimated


def test_automatic_refuses_inside_token_or_beside_unheard_text_without_losing_tail():
    p=project()
    assert allocate_split_times(p.cues[0],[2],project=p)==([],True)
    # Edited text is realigned to the heard tokens, not to stale indices.
    # Unheard text joins both neighbours: no boundary is claimed beside it.
    p.cues[0].text='啊这个FPS60非常好'
    words, reason = cue_words(p,p.cues[0])
    assert reason == 'derived_term_source_span'
    assert [(p.cues[0].text[w.char_start:w.char_end], w.start_ms, w.end_ms) for w in words] == [
        ('啊',100,200),('这个',600,900),('FPS60非常好',950,1550)]
    assert build_replacement_cues(p.cues[0],CueRefineAction('a','split',[7]),project=p)==[]
    assert build_replacement_cues(p.cues[0],CueRefineAction('a','split',[9]),project=p)==[]
    assert allocate_split_times(p.cues[0],[0],project=p)==([(100,200),(600,1800)],False)


def test_unrelated_text_is_never_aligned():
    p=project()
    p.cues[0].text='完全不同的句子'
    assert cue_words(p,p.cues[0])==((),'text_changed_or_inside_multi_character_token')


# 2026-10-12（用户要求）：切在停顿空格处时空格就是边界，不留在左段句尾
# （旧期望为 '啊，这个 ' / '啊，这个 FPS60 '）。
@pytest.mark.parametrize('at, left',[(500,'啊，'),(700,'啊，这个'),(1350,'啊，这个 FPS60')])
def test_manual_retains_cut_and_assigns_indivisible_words(at,left):
    p=project(); cut=resolve_split(p.cues[0],at,project=p)
    assert cut.split_ms==at and cut.left_text==left
    assert not cut.right_text.startswith(' ')
    assert cut.left_text+cut.right_text==p.cues[0].text or cut.left_text+' '+cut.right_text==p.cues[0].text
    assert cut.timing_source=='exact_token_text'


def test_missing_evidence_manual_fallback_is_explicit():
    p=project();p.asr_evidence.clear()
    cut=resolve_split(p.cues[0],700,project=p)
    assert cut.split_ms==700 and cut.timing_source=='estimated_text_allocation'
    assert allocate_split_times(p.cues[0],[1],project=p)==([],True)


def test_seconds_units_do_not_depend_on_magnitude():
    p=project('甲乙',[('甲',100000,100100),('乙',100200,100400)])
    p.cues[0].start_ms=100000;p.cues[0].end_ms=100500
    for w in p.asr_evidence['segment']['words']:
        w['start']=w.pop('start_ms')/1000;w['end']=w.pop('end_ms')/1000
    assert cue_words(p,p.cues[0])[0][1].start_ms==100200


def test_undo_reopen_repeat_split_preserves_evidence_and_text(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=project(); original=copy.deepcopy(p.asr_evidence);stack=QUndoStack()
    cut=resolve_split(p.cues[0],500,project=p)
    stack.push(split_cue_command(p,'a',cut.split_ms,cut.left_text,cut.right_text))
    assert cue_words(p,p.cues[1])[0][0].start_ms==600
    stack.undo();assert len(p.cues)==1
    stack.redo();save_project(p,tmp_path/'p.2byteproj');q=load_project(tmp_path/'p.2byteproj')
    assert q.asr_evidence==original
    again=resolve_split(q.cues[1],1350,project=q)
    assert again.right_text=='好好'


def test_reorder_repeated_speed_clip_maps_tokens_once():
    from twobyteasr.studio_edit_sequence import EditSequence, VideoSegment, store_sequence, projected_cues
    p=project('甲乙',[('甲',100,300),('乙',900,1100)])
    p.cues[0].end_ms=1200
    store_sequence(p,EditSequence(source_path='missing.mp4',source_duration_ms=3000,segments=[
        VideoSegment('fast','missing.mp4',0,2000,3000,4000),
        VideoSegment('again','missing.mp4',0,2000,5000,7000)]))
    views=projected_cues(p)
    assert [(w.start_ms,w.end_ms) for w in cue_words(p,views[0])[0]]==[(3050,3150),(3450,3550)]
    assert cue_words(p,views[1])[0][1].start_ms==5900


def test_pause_hint_uses_original_punctuation_index_and_casefold_width():
    from twobyteasr.sentence_refine import pause_hints_for_cue
    p=project('啊， 这个 FPS60 好好')
    words,_=cue_words(p,p.cues[0])
    assert pause_hints_for_cue(p.cues[0],[(w.text,w.start_ms,w.end_ms) for w in words])==[{'after_chars':0,'gap_ms':400}]
    p=project('A，ß B',[('a',100,200),('SS',400,600),('B',700,900)])
    words,_=cue_words(p,p.cues[0])
    assert [(w.char_start,w.char_end) for w in words]==[(0,1),(2,3),(4,5)]
