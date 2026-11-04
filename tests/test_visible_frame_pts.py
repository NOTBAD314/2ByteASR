from fractions import Fraction
import numpy as np
from scripts.match_visible_frame_pts import SourceFrameIndex


def test_vfr_pts_come_from_matched_frame_not_nominal_fps():
    rng=np.random.default_rng(83021)
    frames=rng.uniform(0,255,(7,36,64,3)).astype(np.float32)
    pts=[Fraction(x,1000) for x in (0,17,70,71,140,215,290)]
    index=SourceFrameIndex(frames,pts)
    for i,frame in enumerate(frames):
        result=index.match(frame)
        assert result['status']=='matched'
        assert Fraction(result['source_pts'])==pts[i]


def test_repeated_source_images_are_ambiguous():
    rng=np.random.default_rng(40)
    frame=rng.uniform(0,255,(36,64,3)).astype(np.float32)
    result=SourceFrameIndex([frame,frame,255-frame],[0,1,2]).match(frame)
    assert result['status']=='ambiguous'
    assert result['source_pts'] is None


def test_unrelated_pixels_do_not_get_a_timestamp():
    index=SourceFrameIndex([np.zeros((36,64,3)),np.ones((36,64,3))*30],[0,1])
    result=index.match(np.ones((36,64,3))*200)
    assert result['status']=='no_match'
    assert result['source_pts'] is None


def test_pruned_result_equals_exhaustive_global_nearest():
    rng=np.random.default_rng(237)
    frames=rng.uniform(0,255,(80,36,64,3)).astype(np.float32)
    # All frames share low-frequency appearance; fine differences decide.
    query=(frames[72]*.98+frames[71]*.02)
    exact=np.argsort(np.abs(frames-query).mean(axis=(1,2,3)))[:2]
    result=SourceFrameIndex(frames,range(80)).match(query)
    assert [result['best_source_index'],result['runner_up_source_index']]==list(exact)
