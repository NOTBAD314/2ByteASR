from twobyteasr.playback.audio_recovery import EndpointRecovery


def test_three_failures_do_not_restart_forever_when_a_window_expires():
    budget=EndpointRecovery()
    assert budget.begin(0)==(True,'starting')
    assert budget.begin(.1)==(False,'backoff')
    assert budget.begin(.5)==(True,'starting')
    assert budget.begin(1.)==(False,'backoff')
    assert budget.begin(2.5)==(True,'starting')
    for now in [3,30,300,3000]:assert budget.begin(now)==(False,'exhausted')


def test_only_explicit_reset_or_new_session_reopens_budget():
    budget=EndpointRecovery(attempts=3,next_attempt_at=500)
    assert not budget.begin(1000)[0]
    budget.reset()
    assert budget.begin(0)[0] and budget.attempts==1
