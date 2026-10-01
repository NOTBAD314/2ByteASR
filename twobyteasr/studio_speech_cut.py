"""Local voice activity on the exact edited audio graph, with reviewable cuts."""
from __future__ import annotations

import json
import subprocess
import time
import wave
from pathlib import Path
from types import SimpleNamespace

from .studio_clip_edit import merge_ranges, video_track_locked


def pause_candidates(speech, coverage, duration_ms, minimum_ms=1000, padding_ms=200):
    """Protect every detected voice, outer program edges, and intentional gaps."""
    speech = merge_ranges((max(0,a), min(duration_ms,b)) for a,b in speech)
    coverage = merge_ranges(coverage)
    candidates = []
    stats = {'speech_regions':len(speech), 'short_pauses':0, 'protected_pauses':0}
    # No speech is not proof that a whole game sequence is disposable.
    for left,right in zip(speech,speech[1:]):
        a,b = left[1],right[0]
        if b-a < minimum_ms:
            stats['short_pauses'] += 1
            continue
        for lo,hi in coverage:
            start,end = max(a,lo),min(b,hi)
            if end-start < minimum_ms:
                continue
            # Exactly one user-specified guard on each side.
            start += padding_ms
            end -= padding_ms
            if end-start < 250:
                stats['protected_pauses'] += 1
                continue
            candidates.append({'start_ms':start, 'end_ms':end, 'pause_ms':b-a,
                'reason':'本地人声检测：两段人声之间无持续人声；每侧保护已扣除',
                'confidence':'中 · 混合音轨无法区分主播与游戏台词'})
    return candidates,stats


def _check_cancel(request):
    if request is not None and request.is_cancelled:
        raise RuntimeError('检测已取消')


def _wait_process(command, work, name, request, poll):
    from .processes import popen_hidden_subprocess, stop_process_tree
    with (work/(name+'.log')).open('w',encoding='utf8') as log:
        process = popen_hidden_subprocess(command, purpose='studio local speech pauses',
            stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                _check_cancel(request)
                poll()
                time.sleep(.15)
            if process.returncode:
                detail = (work/(name+'.log')).read_text('utf8',errors='replace')[-900:]
                raise RuntimeError(f'{name}失败：{detail}')
            poll()
        finally:
            if process.poll() is None:
                stop_process_tree(process)


def _render_audio(snapshot, work, ffmpeg, request, progress):
    from .audio_export import audio_mix_arguments
    total = snapshot['duration_ms']/1000
    job = SimpleNamespace(start_seconds=0, duration_seconds=total,
                          video_graph={'duration_ms':snapshot['duration_ms']})
    args = audio_mix_arguments(str(ffmpeg), job, snapshot['audio_graph']['segments'])
    if args == ['-an']:
        raise ValueError('当前范围没有可分析音频')
    wav = work/'timeline.wav'
    progress_file = work/'decode-progress.txt'
    command = [str(ffmpeg),'-hide_banner','-nostdin','-y','-f','lavfi','-i',
        f'anullsrc=r=16000:cl=mono:d={total:.6f}',*args,'-t',f'{total:.6f}',
        '-ac','1','-ar','16000','-c:a','pcm_s16le','-progress',str(progress_file),str(wav)]
    (work/'decode-command.json').write_text(json.dumps(command,ensure_ascii=False),'utf8')
    def poll():
        if progress_file.exists():
            values=[line.split('=',1)[1] for line in progress_file.read_text(errors='replace').splitlines() if line.startswith('out_time_us=')]
            if values:
                progress('解码当前时间轴音频',min(total,max(0,int(values[-1])/1e6)),total)
    _wait_process(command,work,'audio-read',request,poll)
    with wave.open(str(wav),'rb') as stream:
        if abs(stream.getnframes()-round(total*16000)) > 1:
            raise RuntimeError('音轨读取失败：解码长度与当前时间轴不一致')
    return wav


def analyze_speech_pauses(project, work, *, mode='smart', minimum_s=1.0, padding_s=.2,
                          audio_track_id='', request=None, progress=lambda *args: None):
    """Project is a detached snapshot; original files and settings are read-only."""
    from .recognition_input import capture_recognition_snapshot
    from .runtime_paths import detect_install_root, resolve_model_dir
    from .runtime_registry import resolve_runtime_python
    from .studio_edit_sequence import projected_cues
    import numpy as np
    started=time.monotonic()
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    snapshot=capture_recognition_snapshot(project)
    if audio_track_id:
        snapshot['audio_graph']['segments']=[s for s in snapshot['audio_graph']['segments'] if s['audio_track_id']==audio_track_id]
    if not snapshot['audio_graph']['segments']:
        raise ValueError('当前范围没有可分析音频；检查目标音轨、静音与独听状态')
    root=detect_install_root()
    if mode=='smart':
        model=resolve_model_dir('FireRedVAD')
        python=resolve_runtime_python('main',register=False)
        worker=root/'firered_vad_worker.py'
        if not (model/'VAD/model.pth.tar').is_file() or not python or not worker.is_file():
            raise RuntimeError('模型未准备好：智能口播需要本地 FireRedVAD 和主运行库；可到模型工坊准备，或手动选择“仅静音”。不会自动启动 MOSS 或云端识别。')
    progress('准备当前时间轴音频',0,snapshot['duration_ms']/1000)
    wav=_render_audio(snapshot,work,root/'tools/ffmpeg/bin/ffmpeg.exe',request,progress)
    _check_cancel(request)
    duration=snapshot['duration_ms']
    coverage=merge_ranges((c.timeline_in_ms,c.timeline_out_ms) for t in project.video_tracks
                          if not video_track_locked(project,t) for c in t.clips)
    if mode=='smart':
        progress_file=work/'vad-progress.json'
        result_file=work/'voice-regions.json'
        def poll():
            if progress_file.exists():
                try:
                    data=json.loads(progress_file.read_text('utf8'))
                    progress('本地人声活动检测',data['processed_seconds'],data['total_seconds'])
                except (OSError,ValueError,KeyError):
                    pass  # Progress is advisory; the final result is mandatory.
        progress('准备本地 FireRedVAD',0,duration/1000)
        _wait_process([python,'-I','-u',str(worker),'--wav',str(wav),'--model-dir',str(model/'VAD'),
            '--output',str(result_file),'--chunk-seconds','30','--speech-padding-frames','0',
            '--progress-file',str(progress_file)],work,'voice-detect',request,poll)
        detected=json.loads(result_file.read_text('utf8'))
        speech=[(round(s['start']*1000),round(s['end']*1000)) for s in detected['regions']]
        # Existing subtitles protect possible missed words; their absence is
        # never used as evidence of a pause or of speaker ownership.
        speech += [(c.start_ms,c.end_ms) for c in projected_cues(project)]
        candidates,stats=pause_candidates(speech,coverage,duration,round(minimum_s*1000),round(padding_s*1000))
        diagnostic=('未获得可靠人声区间，保守保留整段；请检查目标音轨或试听' if not stats['speech_regions'] else
            '停顿均短于阈值或保护后过短' if stats['short_pauses'] or stats['protected_pauses'] else '检测到人声较连续')
    else:
        from .studio_autocut import compute_silence_ranges_ms
        with wave.open(str(wav),'rb') as stream:
            samples=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
        progress('检测低音量区间',duration/1000,duration/1000)
        ranges=compute_silence_ranges_ms(samples,16000,min_silence_s=minimum_s,padding_s=padding_s)
        candidates=[{'start_ms':max(a,lo),'end_ms':min(b,hi),'reason':'仅静音：自适应低能量检测（不等于无口播）',
            'confidence':'低 · 仅按音量'} for a,b in ranges for lo,hi in coverage if min(b,hi)-max(a,lo)>=250]
        stats={};diagnostic='没有检出符合阈值的低音量停顿'
    _check_cancel(request)
    linked_audio={g.audio_track_id for g in project.av_track_groups if g.linked}
    fixed_end=max([c.timeline_out_ms for t in project.video_tracks if video_track_locked(project,t) for c in t.clips]
        + [c.timeline_out_ms for t in project.audio_tracks for c in t.clips
           if t.id not in linked_audio or not c.linked_video_clip_id]+[0])
    editable_end=max((hi for lo,hi in coverage),default=0)
    result={'mode':mode,'candidates':candidates,'stats':stats,'diagnostic':diagnostic if not candidates else '检测完成，尚未应用；请检查或试听候选',
        'duration_ms':duration,'removed_ms':sum(c['end_ms']-c['start_ms'] for c in candidates),
        'fixed_end_ms':fixed_end,'editable_end_ms':editable_end,
        'elapsed_seconds':round(time.monotonic()-started,3),'audio_track_id':audio_track_id,
        'audio_path':str(wav),'work_dir':str(work), 'fingerprint':snapshot['fingerprint']}
    (work/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return result


def make_seam_preview(audio_path, start_ms, end_ms):
    """Save original edges, a 0.6s separator, then the actual proposed join."""
    import numpy as np
    path=Path(audio_path)
    with wave.open(str(path),'rb') as wav:
        rate=wav.getframerate()
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:
            raise ValueError('试听需要单声道 PCM16')
        def read(a,b):
            lo,hi=max(0,round(a*rate/1000)),min(wav.getnframes(),round(b*rate/1000))
            wav.setpos(lo)
            return np.frombuffer(wav.readframes(max(0,hi-lo)),dtype='<i2').copy()
        original=read(start_ms-1200,end_ms+1200)
        joined=np.concatenate((read(start_ms-1200,start_ms),read(end_ms,end_ms+1200)))
        samples=np.concatenate((original,np.zeros(round(.6*rate),dtype='<i2'),joined))
    target=path.with_name(f'seam-{start_ms}-{end_ms}.wav')
    with wave.open(str(target),'wb') as wav:
        wav.setparams((1,2,rate,0,'NONE','not compressed'))
        wav.writeframes(samples.astype('<i2').tobytes())
    return target
