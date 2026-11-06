from twobyteasr.playback.play_intent import PendingPlay


def test_repeated_wait_observations_do_not_create_or_extend_an_intent():
    intent=PendingPlay(('project',3,8),1.,11.)
    for i in range(1000):
        assert intent.decision(('project',3,8),1.+i*.005)=='waiting'
    assert intent.started==1. and intent.deadline==11.
    assert intent.decision(('project',3,8),11.)=='timeout'


def test_stale_project_or_seek_cannot_auto_start_after_ready():
    intent=PendingPlay(('project',3,8),1.,11.)
    assert intent.decision(('new-project',3,8),2.,ready=True)=='cancelled'
    assert intent.decision(('project',4,8),2.,ready=True)=='cancelled'


def test_endpoint_failure_wins_over_a_stale_ready_signal():
    intent=PendingPlay(('project',3),1.,11.)
    assert intent.decision(('project',3),2.,ready=True,failure=True)=='failed'
    assert intent.decision(('project',3),2.,ready=True)=='ready'
