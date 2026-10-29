from twobyteasr.acceptance.long_project_acceptance_audit import mpv_timecode_ms


def test_real_mpv_drop_frame_labels_do_not_create_long_recording_offsets():
    assert abs(mpv_timecode_ms('00:10:11;50')-611234)<1
    assert abs(mpv_timecode_ms('01:24:45;14')-5080167)<1
    assert mpv_timecode_ms('00:00:00;00')==0
    assert mpv_timecode_ms('00:10:11:50')>611800
