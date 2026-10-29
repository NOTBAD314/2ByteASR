from fractions import Fraction
import pytest
from twobyteasr.timeline.caption_frame_time import ass_frame_ms,observed_frame_ms


@pytest.mark.parametrize('rate',[Fraction(24),Fraction(30),Fraction(60),Fraction(60000,1001)])
@pytest.mark.parametrize('start,end',[(0,1000),(1000,2000),(1001,2000),(1100,2000),(900,2000),(999,1001)])
def test_ass_events_keep_exact_media_frame_membership(rate,start,end):
    ass_start=ass_frame_ms(start,rate);ass_end=ass_frame_ms(end,rate)
    for index in range(int(rate*2)+2):
        pts=index*1000/rate
        assert (start<=pts<end)==(ass_start<=pts<ass_end),(pts,start,end,ass_start,ass_end)


def test_microsecond_ipc_rounding_does_not_drop_5994_frame():
    rate=Fraction(60000,1001)
    assert observed_frame_ms(1017.683,rate)==Fraction(61061,60)
    assert observed_frame_ms(1000,Fraction(60))==1000


def test_same_endpoint_is_shared_but_real_one_ms_gap_stays_empty():
    rate=Fraction(60)
    assert ass_frame_ms(1000,rate)==1000
    assert ass_frame_ms(1001,rate)==1010
    assert not (ass_frame_ms(1001,rate)<=1000<ass_frame_ms(2000,rate))
def test_visibility_transaction_cannot_cross_to_a_different_frame_mid_commit():
    from twobyteasr.timeline.caption_frame_time import caption_sample_transaction
    from types import SimpleNamespace
    values=iter((2033,2050));owner=SimpleNamespace(_caption_tick_time_ms=None)
    owner._caption_sample_ms=lambda:owner._caption_tick_time_ms if owner._caption_tick_time_ms is not None else next(values)
    @caption_sample_transaction
    def commit(self):return self._caption_sample_ms(),self._caption_sample_ms()
    assert commit(owner)==(2033,2033)
    assert owner._caption_tick_time_ms is None
    assert commit(owner)==(2050,2050)
