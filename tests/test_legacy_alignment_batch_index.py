import random

import pytest

from twobyteasr.recognition.cue_word_alignment import TokenAlignmentIndex, align_text_to_tokens


@pytest.mark.parametrize('overlap', [False, True])
def test_indexed_matching_keeps_exact_results_and_failure_reasons(overlap):
    records = [(index*100,index*100+90,'abc'[index%3],str(index//5)) for index in range(200)]
    if overlap:
        records.append((40,90,'different','alternative'))
    prepared = TokenAlignmentIndex(records)
    rng = random.Random(20261109)
    for _ in range(500):
        start = rng.randrange(0,19000)
        interval = start, start+rng.randrange(100,2000)
        text = rng.choice(['abc','bca','abab','bc','ac',' abc! ', '完全不同'])
        assert align_text_to_tokens(text,records,interval,index=prepared) == align_text_to_tokens(text,records,interval)


def test_legacy_conversion_reads_fallback_evidence_only_once(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, KEY
    from twobyteasr.recognition import cue_word_alignment as alignment
    project = SubtitleProject(StudioMedia('missing.mp4',duration_ms=60000), cues=[
        StudioCue(str(index),index*1000,index*1000+800,'测试') for index in range(50)],
        asr_evidence={str(index):dict(words=[dict(text='测试',start_ms=index*1000,end_ms=index*1000+800)])
                      for index in range(50)})
    expected = {cue.id:alignment.cue_words(project,cue) for cue in project.cues}
    original = alignment.evidence_tokens
    calls = []
    def observe(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(alignment,'evidence_tokens',observe)
    ensure_independent_captions(project)
    assert len(calls) == 1
    instances = project.studio_state[KEY]['instances']
    for cue in project.cues:
        words, reason = expected[cue.id]
        assert instances[cue.id]['word_alignment'] == reason
        assert [(row['text'],row['start_ms'],row['end_ms']) for row in instances[cue.id]['words']] == [
            (word.text,word.start_ms,word.end_ms) for word in words]
