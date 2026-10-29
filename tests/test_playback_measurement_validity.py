from twobyteasr.diagnostics.playback_metrics import desktop_cadence, distribution

def rows(fps=60,seconds=20):
    return [dict(desktop_qpc_s=i/fps,acquired_qpc_s=i/fps+.001,copy_decode_ms=.3,
                 accumulated_frames=1,frame_code=i,roi_hash=i) for i in range(round(fps*seconds))]

def test_sixty_fps_complete_data_passes():
    r=desktop_cadence(rows(),1,19,source_fps=60,display_hz=60)
    assert r['measurement_valid'] and r['performance_pass'] is True
    assert r['different_frames_per_second']==60

def test_thirty_fps_cannot_pass_sixty_gate():
    r=desktop_cadence(rows(30),1,19,source_fps=60,display_hz=60)
    assert r['performance_pass'] is not True

def test_missing_or_occluded_capture_is_unverified():
    data=rows()
    for r in data:r['frame_code']=-1
    for data in (data,[]):
        r=desktop_cadence(data,1,19,source_fps=60,display_hz=60)
        assert not r['measurement_valid']
        assert r['performance_pass']=='UNVERIFIED'

def test_probe_loss_is_not_called_player_stutter():
    data=rows()
    for r in data[120:200]:r['accumulated_frames']=2
    r=desktop_cadence(data,1,19,source_fps=60,display_hz=60)
    assert not r['measurement_valid'] and r['performance_pass']=='UNVERIFIED'

def test_repeat_is_failure_even_without_decoder_drops():
    data=rows()
    for r in data[120:150]:r['frame_code']=120
    r=desktop_cadence(data,1,19,source_fps=60,display_hz=60)
    assert r['measurement_valid'] and r['performance_pass'] is False
    assert r['change_intervals_ms']['over_100ms']==1

def test_twenty_four_fps_and_fast_playback_use_feasible_cadence():
    assert desktop_cadence(rows(24),1,19,source_fps=24,display_hz=60)['performance_pass'] is True
    assert desktop_cadence(rows(),1,19,source_fps=60,display_hz=60,rate=4)['performance_pass'] is True

def test_empty_latency_is_not_zero_latency():
    assert distribution([])['p95'] is None

def test_system_events_match_pid_swapchain_and_display_not_submission():
    from twobyteasr.diagnostics.playback_metrics import system_cadence
    data=[dict(Application='mpv.exe',ProcessID='100',SwapChainAddress='0x1',PresentMode='Composed: Flip',
        CPUStartQPCTime=str(i*1000/60),FrameTime=str(1000/60),DisplayLatency='50',DisplayedTime=str(1000/60),GPUBusy='1') for i in range(1200)]
    other=[{**r,'ProcessID':'101'} for r in data]
    assert system_cadence(data+other,1,19,process_id=100,source_fps=60,display_hz=60)['performance_pass'] is True
    for i,row in enumerate(data):
        if i%2:row['DisplayedTime']='NA'
    result=system_cadence(data,1,19,process_id=100,source_fps=60,display_hz=60)
    assert result['measurement_valid'] and result['performance_pass'] is False
    assert result['system_display_events_per_second']==30
    assert result['submitted_frames']==1080

def test_interrupted_etw_capture_is_unverified():
    from twobyteasr.diagnostics.playback_metrics import system_cadence
    assert system_cadence([],1,19,process_id=100,source_fps=60,display_hz=60)['performance_pass']=='UNVERIFIED'

def test_presentmon_csv_encoding_and_bom(tmp_path):
    from twobyteasr.diagnostics.playback_metrics import read_system_trace
    for encoding in ('utf-8','utf-8-sig'):
        path=tmp_path/(encoding+'.csv')
        path.write_text('Application,ProcessID\nmpv.exe,100\n',encoding=encoding)
        assert read_system_trace(path)==[{'Application':'mpv.exe','ProcessID':'100'}]
