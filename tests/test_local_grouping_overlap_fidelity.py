"""Retain unresolved overlapping source utterances without relaxing fidelity."""
import copy
import pytest


def overlap_sources():
    import subtitle_core as core
    # Actual failing B source22/23 shape; labels remain unresolved, not identities.
    return [core.SpeechSegment(22,53.18,55.61,"却与四本人不受拘束的行事风格",.78,[],speaker="SPEAKER_UNCONFIRMED"),
            core.SpeechSegment(23,54.21,55.11,"战斗规则的",.78,[],speaker="SPEAKER_UNCONFIRMED")]


def test_local_overlap_keeps_whole_sources_real_times_and_review(monkeypatch):
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    rows=overlap_sources(); original=copy.deepcopy(rows); events=[]
    monkeypatch.setattr(grouping,"record_run_event",lambda event,**data:events.append((event,data)))
    with activate_runtime_context(RuntimeContext(),legacy=core):
        with core.capture_review_items() as reviews:
            cues=grouping.group_subtitles(rows,use_ai=False,max_workers=1)
    assert [(c.text,c.speaker,c.start,c.end) for c in cues] == [
        ("却与四本人不受拘束的行事风格","SPEAKER_UNCONFIRMED",53.18,55.61),
        ("战斗规则的","SPEAKER_UNCONFIRMED",54.21,55.11)]
    # Existing no-word-alignment diagnostics may annotate arbitration metadata;
    # the immutable source content, word evidence and ownership remain intact.
    protected=lambda source:(source.segment_id,source.text,source.start,source.end,
                              source.speaker,source.words,source.timing_locked)
    assert [protected(s) for s in rows]==[protected(s) for s in original]
    assert any(event=="grouping_local_source_boundary_fallback" and d["source_segment_ids"]==[22,23] for event,d in events)
    assert any(r["category"]=="重叠来源断句待审" and r["source_segment_ids"]==[22,23] for r in reviews)
    assert cues.origin=="local" and not cues.validated


@pytest.mark.parametrize("damage",["drop","duplicate","source_word_reversal","copy_to_other_owner"])
def test_batch_protection_still_rejects_corrupted_local_producer(monkeypatch,damage):
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    rows=[core.SpeechSegment(1,0,1,"先确认宝箱位置",.8,[],speaker="S01"),
          core.SpeechSegment(2,.5,1.5,"我检查右边",.8,[],speaker="S02")]
    def damaged(batch,*args):
        cues=[core.SubtitleCue(0,s.start,s.end,s.text,speaker=s.speaker) for s in batch]
        if damage=="drop": cues[0].text="先确认宝箱位"
        elif damage=="duplicate": cues[0].text="先确认宝箱位置置"
        elif damage=="source_word_reversal": cues[0].text="先确认位置宝箱"
        else:
            cues[0].text=cues[1].text="先确认宝箱位置我检查右边"
        return cues
    monkeypatch.setattr(grouping,"fallback_group",damaged)
    with pytest.raises(ValueError,match="本地断句未保持来源正文"):
        grouping.group_subtitles(rows,use_ai=False,max_workers=1)


def test_nonoverlapping_sources_keep_normal_local_resegmentation(monkeypatch):
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    events=[]
    monkeypatch.setattr(grouping,"record_run_event",lambda event,**data:events.append(event))
    row=core.SpeechSegment(1,10,13,"可以说是对迄今战斗规则的一种颠覆",.8,[],speaker="S01")
    cues=grouping.group_subtitles([row],use_ai=False,max_workers=1)
    assert len(cues)>1
    assert "".join(c.text for c in cues)=="可以说是对迄今战斗规则的一种颠覆"
    assert all(c.speaker=="S01" and 10<=c.start<c.end<=13 for c in cues)
    assert "grouping_local_source_boundary_fallback" not in events
