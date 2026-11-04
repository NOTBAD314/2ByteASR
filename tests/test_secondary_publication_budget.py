from twobyteasr.playback.video_decode_worker import next_publication_deadline

def test_small_wakeup_lateness_does_not_accumulate_into_a_lower_frame_rate():
    deadline=next_publication_deadline(0,0)
    for _ in range(600):
        deadline=next_publication_deadline(deadline,deadline+.001)
    assert abs(deadline-601/60)<1e-9

def test_late_worker_skips_missed_deadlines_without_catchup_work():
    deadline=next_publication_deadline(1/60,.115)
    assert .115<deadline<=.115+1/60
    assert abs(deadline-7/60)<1e-9
