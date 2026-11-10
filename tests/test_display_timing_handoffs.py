"""Reading-gap compensation must not undo a protected speaker handoff."""
import pytest
import subtitle_core as core
from twobyteasr.subtitle_rules.display_timing import short_gap_bridges
from twobyteasr.subtitle_rules.grouping_quality import cues_from_quality
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
from twobyteasr.recognition.pipeline_runtime import finalize_cues


def test_half_open_handoff_does_not_bridge_past_another_speaker():
    rows=[('previous','A',0,100),('reply','B',100,500),('next','A',500,900)]
    assert short_gap_bridges(rows,500)=={}


def test_existing_overlap_can_keep_a_same_speaker_short_gap_bridge():
    rows=[('previous','A',0,100),('overlap','B',50,600),('next','A',500,900)]
    assert short_gap_bridges(rows,500)=={'previous':500}


def test_full_track_blank_still_closes_at_the_next_speaker():
    assert short_gap_bridges([('a','A',0,100),('b','B',200,500)],500)=={'a':200}


@pytest.mark.parametrize('fps',[24,30,60])
def test_e_final_frame_relock_preserves_both_handoffs(fps):
    rows=[core.SpeechSegment(71,114.74,115.64,'可以刷 对 我就',.9,[],speaker='A'),
          core.SpeechSegment(72,115.64,116.04,'可以刷',.9,[],speaker='B'),
          core.SpeechSegment(73,116.04,116.64,'可以刷 可以刷',.9,[],speaker='A')]
    for source in rows:
        source.moss_start=source.start;source.moss_end=source.end
        source.caption_arbitration={'word_timing':{'basis':'uniform_display_estimate'}}
    with language_scope('zh'),activate_runtime_context(RuntimeContext(task_language='zh'),legacy=core):
        cues,_,_=cues_from_quality(rows,[6,9,15])
        for i,cue in enumerate(cues,1):cue.cue_id=i
        final=finalize_cues(cues,rows,[],[],120,fps,core)
        assert [c.text for c in final]==[r.text for r in rows]
        assert final[0].end<=final[1].start+1e-6
        assert final[1].end<=final[2].start+1e-6
        assert .35<=final[1].end-final[1].start<=.45
        assert all(abs(c.start*fps-round(c.start*fps))<1e-6 for c in final)
