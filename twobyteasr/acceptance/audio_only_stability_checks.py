"""Actual audio-only clock, explicit silent preview and owned process recovery."""
import os


def run(page,output,check,pump,wait):
    from ..system.processes import stop_process_tree
    check('audio-only source uses its physical audio clock',not page.video._media_has_video)
    page.volume_slider.setValue(0)
    page.video.set_paused(False)
    check('audio-only playback starts with real PCM',wait(lambda:not page.video._paused
        and page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>20000,15))
    start=page.timeline.playhead_ms;pump(.5)
    check('audio-only timeline progresses from the audio clock',page.timeline.playhead_ms>start+150
        and page.video._external_clock_sequence>0
        and abs(page.video._playback_clock.snapshot().observed_media_ms
                -page.audio_engine.telemetry_snapshot().get('estimated_source_ms',-10000))<200)
    bridge=page.audio_engine._worker;old=bridge._endpoint_generation
    stop_process_tree(bridge.process)
    check('real audio-only endpoint loss is bounded and recoverable',wait(lambda:page.video._paused
        or (bridge._endpoint_generation>old and page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>20000),10))
    dialog=getattr(page,'_audio_failure_dialog',None)
    if dialog is not None:dialog.reject()
    if page.video._paused:page._retry_audio_output()
    check('audio-only endpoint recovery restores fresh PCM',wait(lambda:bridge._endpoint_generation>old
        and not page.video._paused and page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>20000,20))
    start=page.timeline.playhead_ms;pump(.5)
    check('new endpoint sequence does not pin the playhead',page.timeline.playhead_ms>start+150
        and getattr(page.video,'_external_clock_owner',(None,None))[1]==bridge._endpoint_generation
        and abs(page.video._playback_clock.snapshot().observed_media_ms
                -page.audio_engine.telemetry_snapshot().get('estimated_source_ms',-10000))<200)
    page.video.set_paused(True);os.environ['TWOBYTEASR_TEST_AUDIO_FAULT']='no-device'
    page._retry_audio_output()
    check('audio-only device failure remains a terminal output state',wait(lambda:page.audio_engine.playback_readiness().failed,10))
    dialog=getattr(page,'_audio_failure_dialog',None)
    if dialog is not None:next(x for x in dialog.buttons() if x.text()=='无声预览').click()
    else:page.audio_silent_button.click()
    check('audio-only silent preview is an explicit local-clock choice',wait(lambda:not page.video._paused,8)
        and page._silent_preview_selected and not page.video._external_clock_enabled)
    start=page.timeline.playhead_ms;pump(.5)
    check('silent audio-only preview remains usable',page.timeline.playhead_ms>start+150)
    os.environ.pop('TWOBYTEASR_TEST_AUDIO_FAULT',None)
    page.video.set_paused(True);page.audio_retry_button.click()
    check('retry restores the audio clock before audible playback',wait(lambda:not page.video._paused
        and page.video._external_clock_enabled and page.video._external_clock_sequence>0
        and getattr(page.video,'_external_clock_owner',(None,None))[1]==page.audio_engine._worker._endpoint_generation
        and page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>20000,20))
    page.grab().save(str(output/'audio-only-recovered.png'))
    page.video.set_paused(True);os.environ['TWOBYTEASR_TEST_AUDIO_FAULT']='delay'
    page._retry_audio_output();pump(.2)
    check('audio-only close cancels a pending preparation',bool(page.video._buffered_play_pending or page.video._startup_play_requested))
