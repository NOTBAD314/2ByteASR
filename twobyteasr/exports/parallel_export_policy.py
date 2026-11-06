"""Conservative resource guard for the explicit two-session native export option."""
from pathlib import Path
import shutil


def temporary_space_estimate(job):
    width = int(job.settings.width or (job.direct_video_graph or {}).get('width') or 1920)
    height = int(job.settings.height or (job.direct_video_graph or {}).get('height') or 1080)
    fps = float(job.settings.fps or 30)
    if job.settings.quality_mode in {'vbr', 'cbr'}:
        bits = max(job.settings.bitrate_kbps, job.settings.max_bitrate_kbps) * 1000
    else:
        # CQ output is content-dependent. This is an estimate, with a second
        # exact-size/free-space check once the video segments are closed.
        quality_scale = max(1., 2 ** ((20-job.settings.quality)/6))
        bits = max(8_000_000, width*height*fps*.4*quality_scale)
    video = int(bits*float(job.duration_seconds or 0)/8)
    audio = int(max(320, job.settings.audio_bitrate_kbps)*1000*float(job.duration_seconds or 0)/8)
    source_audio = 2*audio if float(job.duration_seconds or 0) >= 600 else 0
    return dict(video_bytes=video, audio_bytes=audio, source_audio_bytes=source_audio,
                required_bytes=2*(video+audio)+source_audio+1024**3,
                required_memory_bytes=max(3*1024**3, width*height*8*32))


def parallel_decision(job, ffmpeg_path=None):
    from .parallel_video_export import requested_segments
    requested = requested_segments(job)
    automatic=requested==0
    result = dict(mode='auto' if automatic else 'single' if requested==1 else 'dual',
        requested_segments=requested, segments=1, preview='live', reason='explicit single-session export' if requested==1 else 'standard single-session export')
    if requested == 1 and not ffmpeg_path: return result
    if not job.settings.encoder.endswith('_nvenc'):
        result['reason'] = 'two sessions require an available NVENC encoder'; return result
    if (job.settings.container not in {'mp4', 'mov', 'mkv'} or job.settings.fps <= 0
            or (job.duration_seconds or 0) <= 0 or job.composition_resolved or job.edit_segments):
        result['reason'] = 'output clock, container or composed video is outside the verified native route'; return result
    if job.direct_video_graph:
        from .export_filtergraph import simple_video_clips
        if simple_video_clips(job.direct_video_graph) is None:
            result['reason'] = 'video graph requires the full compositor'; return result
    estimate = temporary_space_estimate(job)
    result.update(estimate)
    parent = Path(job.output_path).resolve().parent
    while not parent.exists(): parent = parent.parent
    result['free_disk_bytes'] = shutil.disk_usage(parent).free
    try:
        import psutil
        result['available_memory_bytes'] = psutil.virtual_memory().available
    except (ImportError, OSError):
        result['reason'] = 'available memory could not be verified'; return result
    if result['available_memory_bytes'] < estimate['required_memory_bytes']:
        result['reason'] = 'available memory is below the two-session budget'; return result
    if result['free_disk_bytes'] < estimate['required_bytes']:
        result['reason'] = 'temporary disk cannot hold two video segments and the staged output'; return result
    if ffmpeg_path:
        from .export_acceleration import device_observation,history_key,read_history
        device=device_observation();result['device_observation']=device
        if not device.get('unavailable'):
            try:result['history_key']=history_key(job,device,ffmpeg_path)
            except (OSError,ValueError):pass
    if requested==1:return result
    if automatic:
        device=result.get('device_observation') or {}
        if device.get('unavailable') or not device:
            result['reason']='automatic: current device memory/load is unavailable';return result
        width=int(job.settings.width or (job.direct_video_graph or {}).get('width') or 1920)
        height=int(job.settings.height or (job.direct_video_graph or {}).get('height') or 1080)
        result['required_vram_bytes']=max(512*1024**2,width*height*256)
        if device['free_vram_bytes']<result['required_vram_bytes']:
            result['reason']='automatic: free device memory is below the two-session budget';return result
        import psutil
        result['system_cpu_percent']=psutil.cpu_percent(interval=.05)
        if (result['system_cpu_percent']>=90 or device['encoder_percent']>=75
                or device['decoder_percent']>=85 or device['gpu_percent']>=90):
            result['reason']='automatic: current CPU/GPU load leaves insufficient headroom';return result
        if job.duration_seconds<60:
            result['reason']='automatic: short export cannot reliably amortize parallel startup and final mux';return result
        # A deliberately conservative initial estimate. Full successful elapsed
        # times (including preparation, mux and checks) replace it for repeated
        # workloads. No synthetic calibration is performed on the click path.
        pixels=width*height*float(job.settings.fps)*float(job.duration_seconds)
        single=pixels/1_000_000_000
        dual=single/1.30+2
        estimate_source='conservative pixel-work estimate including 2s startup/mux allowance'
        from .export_acceleration import read_history
        history=read_history(result['history_key']) if result.get('history_key') else {}
        if history.get('session_failure_until',0)>__import__('time').time():
            result['reason']='automatic: recent concurrent-session failure; cooldown uses single session';return result
        samples=history.get('samples',{})
        if samples.get('1') and samples.get('2'):
            import statistics
            single=statistics.median(samples['1']);dual=statistics.median(samples['2'])
            estimate_source='recent complete exports of the same device, driver, media and output settings'
        result.update(estimated_single_seconds=single,estimated_dual_seconds=dual,cost_source=estimate_source)
        if single-dual<max(1.,single*.03):
            result['reason']='automatic: expected complete-task saving does not cover startup/mux/check overhead';return result
    result.update(segments=2, preview='completion poster only',
        reason='automatic two-session NVENC; supported native route, positive complete-task saving and available resources' if automatic else 'explicit two-session NVENC; supported native video graph and sufficient memory/temporary disk',
        duration_note='short export; extra probes and mux may offset gains' if job.duration_seconds < 120 else 'long export')
    return result
