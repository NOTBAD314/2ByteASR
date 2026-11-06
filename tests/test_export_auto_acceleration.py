from dataclasses import replace
from types import SimpleNamespace
import pytest
from twobyteasr.exports.studio_render import RenderJob,RenderSettings
from twobyteasr.exports.parallel_export_policy import parallel_decision
from twobyteasr.exports.parallel_video_export import requested_segments

@pytest.fixture
def setup(tmp_path,monkeypatch):
    import psutil,shutil
    from twobyteasr.exports import export_acceleration as acceleration
    device=dict(device='device-uuid',driver='driver-version',free_vram_bytes=8*1024**3,
        total_vram_bytes=12*1024**3,gpu_percent=5,encoder_percent=0,decoder_percent=0)
    monkeypatch.setattr(acceleration,'device_observation',lambda:dict(device))
    monkeypatch.setattr(acceleration,'history_key',lambda *a:'workload')
    monkeypatch.setattr(acceleration,'read_history',lambda *a:{})
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=32*1024**3))
    monkeypatch.setattr(psutil,'cpu_percent',lambda **kw:10)
    monkeypatch.setattr(shutil,'disk_usage',lambda p:SimpleNamespace(free=200*1024**3))
    job=RenderJob(str(tmp_path/'source.mp4'),'',str(tmp_path/'output.mp4'),
        RenderSettings(encoder='h264_nvenc',width=1920,height=1080,fps=60,quality_mode='cq',quality=20),duration_seconds=180)
    return job,device

def test_default_automatic_uses_two_sessions_for_eligible_measured_scale(setup):
    job,_=setup
    assert requested_segments(job)==0
    decision=parallel_decision(job,'ffmpeg')
    assert decision['segments']==2 and decision['mode']=='auto'
    assert decision['estimated_dual_seconds']<decision['estimated_single_seconds']

def test_short_jobs_and_explicit_choices(setup):
    job,_=setup
    short=replace(job,duration_seconds=20)
    assert parallel_decision(short,'ffmpeg')['segments']==1
    short.export_context={'parallel_segments':2}
    assert parallel_decision(short,'ffmpeg')['segments']==2
    job.export_context={'parallel_segments':1}
    assert parallel_decision(job,'ffmpeg')['segments']==1

@pytest.mark.parametrize('change',[{'free_vram_bytes':1024**2},{'encoder_percent':99},{'gpu_percent':99},{'unavailable':True}])
def test_resource_pressure_keeps_single_session(setup,change):
    job,device=setup;device.update(change)
    assert parallel_decision(job,'ffmpeg')['segments']==1

def test_full_task_history_includes_mux_and_checks_and_can_reject_dual(setup,monkeypatch):
    import twobyteasr.exports.export_acceleration as a
    job,_=setup
    monkeypatch.setattr(a,'read_history',lambda key:dict(samples={'1':[20,21],'2':[22,23]}))
    assert parallel_decision(job,'ffmpeg')['segments']==1
    monkeypatch.setattr(a,'read_history',lambda key:dict(samples={'1':[25,26],'2':[18,19]}))
    assert parallel_decision(job,'ffmpeg')['segments']==2

def test_recent_session_failure_and_unsupported_routes_do_not_retry_dual(setup,monkeypatch):
    import twobyteasr.exports.export_acceleration as a
    import time
    job,_=setup
    monkeypatch.setattr(a,'read_history',lambda key:dict(session_failure_until=time.time()+100))
    assert parallel_decision(job,'ffmpeg')['segments']==1
    job=replace(job,composition_resolved=True)
    assert parallel_decision(job,'ffmpeg')['segments']==1
    job=replace(job,settings=replace(job.settings,encoder='libx264'))
    assert parallel_decision(job,'ffmpeg')['segments']==1

def test_advanced_route_diagnostic_keeps_the_requested_mode(setup):
    from twobyteasr.exports.export_acceleration import advanced_selection
    job,_=setup;advanced_selection(job)
    assert job.completion_metadata['parallel_selection']['mode']=='auto'
    assert job.completion_metadata['parallel_selection']['segments']==1
