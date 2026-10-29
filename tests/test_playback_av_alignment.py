from twobyteasr.diagnostics.playback_av_alignment import desktop_pcm_alignment


def data():
    rows=[{'desktop_qpc_s':1+i/60,'acquired_qpc_s':1+i/60+.0005,
           'frame_code':i%4096,'accumulated_frames':1} for i in range(3900)]
    telemetry=[{'audio':{'source_path':'video.mp4','sink_state':'ActiveState','effective_rate':1,
        'clock_perf_counter_ts':1+i/2,'estimated_source_ms':i*500,'transport_generation':[1,0],
        'clock_sample_uncertainty_ms':.01,'underruns':0}} for i in range(131)]
    return rows,telemetry


def analyze(rows,telemetry):
    return desktop_pcm_alignment(rows,telemetry,start=2,end=65,play_start=1,source_start_ms=0,
                                 source_fps=60,source_path='video.mp4')


def test_matching_qpc_clocks_and_frame_counter_pass_without_request_clock():
    rows,telemetry=data();r=analyze(rows,telemetry)
    assert r['measurement_valid'] and r['performance_pass'] is True
    assert r['absolute_delta_ms']['max']<.001


def test_missing_high_resolution_audio_time_is_unverified():
    rows,telemetry=data()
    for item in telemetry:item['audio'].pop('clock_perf_counter_ts')
    r=analyze(rows,telemetry)
    assert r['measurement_valid'] is False and r['performance_pass']=='UNVERIFIED'


def test_real_offset_fails_and_other_source_cannot_be_used_as_evidence():
    rows,telemetry=data()
    for item in telemetry:item['audio']['estimated_source_ms']-=80
    r=analyze(rows,telemetry)
    assert r['measurement_valid'] and r['performance_pass'] is False
    for item in telemetry:item['audio']['source_path']='background-music.mp4'
    assert analyze(rows,telemetry)['measurement_valid'] is False


def test_declared_counter_wrap_is_unwrapped_but_seek_generation_is_not():
    rows,telemetry=data()
    for i,row in enumerate(rows):row['frame_code']=i%1800
    r=desktop_pcm_alignment(rows,telemetry,start=2,end=65,play_start=1,source_start_ms=0,
        source_fps=60,source_path='video.mp4',code_period=1800)
    assert r['performance_pass'] is True
    telemetry[-1]['audio']['transport_generation']=[2,0]
    r=analyze(rows,telemetry)
    assert r['measurement_valid'] is False and r['performance_pass']=='UNVERIFIED'
