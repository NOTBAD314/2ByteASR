from twobyteasr.recognition.speaker_recovery import candidate_snapshot, confirmation_message


def rows(*labels):
    return [{'speaker': label, 'start': i * 2., 'end': i * 2. + 1., 'text': 'speech'}
            for i, label in enumerate(labels)]


def test_single_anonymous_label_is_pending_but_does_not_claim_multiple_people():
    state = candidate_snapshot(rows('API_S00'), source='filetrans')
    assert state['needs_confirmation']
    message = confirmation_message(state)
    assert '一个说话人标签' in message and '不能证明' in message
    assert '多个' not in message


def test_multiple_labels_are_not_described_as_confirmed_humans():
    state = candidate_snapshot(rows('S00', 'S01'), source='filetrans')
    assert state['needs_confirmation']
    message = confirmation_message(state)
    assert '多个说话人标签' in message and '不等于真人数量' in message


def test_failed_diarization_is_described_as_failure():
    state = candidate_snapshot(rows('S00'), source='filetrans')
    state['processing'] = {'status': 'failed'}
    assert '未能完成' in confirmation_message(state)
