"""Original-media audio clocks: streams, offsets, rates and six-hour seek."""
import argparse,json,os,subprocess,sys,time,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('fresh source/tmp required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    import numpy as np,psutil
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    from twobyteasr.studio.studio_video_track import ffmpeg_executable
    from twobyteasr.playback.cue_audio_preview import plan_cue_preview,preview_command,preview_cache_key
    ffmpeg=str(ffmpeg_executable());rows=[]
    def run(command):subprocess.run(command,check=True,capture_output=True)
    multi=out/'two-streams.mkv'
    run([ffmpeg,'-v','error','-f','lavfi','-i','sine=frequency=700:sample_rate=48000:duration=8',
        '-f','lavfi','-i','sine=frequency=1300:sample_rate=48000:duration=8',
        '-map','0:a','-map','1:a','-c:a','pcm_s16le',str(multi)])
    def project(path,duration,start,end):
        p=SubtitleProject(StudioMedia(str(path),duration_ms=duration),cues=[StudioCue('stable',start,end,'時間試験')])
        p.validate();p.render_settings['_cue_domain']='timeline';return p
    def decode(p,label):
        plan=plan_cue_preview(p,'stable');key=preview_cache_key(plan);command,_=preview_command(plan,ffmpeg)
        initial=psutil.Process().memory_info().rss;peak=[initial];done=threading.Event()
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
        child=psutil.Process(proc.pid);child_peak=[0]
        def watch():
            while not done.wait(.01):
                peak[0]=max(peak[0],psutil.Process().memory_info().rss)
                try:child_peak[0]=max(child_peak[0],child.memory_info().rss)
                except psutil.Error:pass
        watcher=threading.Thread(target=watch);watcher.start();began=time.perf_counter()
        try:payload,errors=proc.communicate(timeout=30)
        finally:done.set();watcher.join()
        if proc.returncode:raise RuntimeError(errors.decode('utf8','replace'))
        pcm=np.frombuffer(payload,dtype='<i2').reshape(-1,2)
        spectrum=np.abs(np.fft.rfft(pcm[:,0].astype(float)))
        hz=float(np.argmax(spectrum)*48000/len(pcm))
        result=dict(label=label,plan=plan.diagnostic(),cache_key=key,frames=len(pcm),
            expected_frames=(plan.play_range_ms[1]-plan.play_range_ms[0])*48,peak_hz=hz,
            head_rms=float(np.sqrt(np.mean(pcm[:960].astype(float)**2))),
            tail_rms=float(np.sqrt(np.mean(pcm[-960:].astype(float)**2))),
            elapsed_ms=(time.perf_counter()-began)*1000,parent_rss_delta=peak[0]-initial,decoder_peak_rss=child_peak[0])
        rows.append(result);return result
    p=project(multi,8000,1000,2000)
    keys=set()
    for stream in (0,1):
        for rate in (.5,1.,1.5,2.):
            for clip in (p.video_tracks[0].clips[0],p.audio_tracks[0].clips[0]):
                clip.source_in_ms=2000;clip.source_out_ms=8000;clip.timeline_in_ms=0
                clip.timeline_out_ms=round(6000/rate);clip.playback_rate=rate
            p.audio_tracks[0].clips[0].stream_index=stream
            row=decode(p,f'stream-{stream}-rate-{rate}')
            assert abs(row['peak_hz']-(700 if stream==0 else 1300))<=2
            assert row['frames']==row['expected_frames'] and row['tail_rms']>500
            assert row['cache_key'] not in keys;keys.add(row['cache_key'])
    shifted=out/'nonzero-start.mkv'
    run([ffmpeg,'-v','error','-i',str(multi),'-map','0:a:1','-c:a','copy','-output_ts_offset','5.5',str(shifted)])
    row=decode(project(shifted,8000,1000,2000),'nonzero media PTS 5.5s')
    assert abs(row['peak_hz']-1300)<=2 and row['head_rms']>500 and row['tail_rms']>500
    longfile=out/'six-hour-synthetic.flac'
    run([ffmpeg,'-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono:d=21600',
        '-f','lavfi','-i','sine=frequency=913:sample_rate=16000:duration=2',
        '-filter_complex','[0:a][1:a]concat=n=2:v=0:a=1[out]','-map','[out]','-c:a','flac','-compression_level','0',str(longfile)])
    row=decode(project(longfile,21602000,21600000,21602000),'six-hour synthetic tail')
    assert row['frames']==96000 and abs(row['peak_hz']-913)<=1 and row['head_rms']>500 and row['tail_rms']>500
    assert row['elapsed_ms']<10000 and row['parent_rss_delta']<64*1024*1024 and row['decoder_peak_rss']<256*1024*1024
    result=dict(passed=True,rows=rows,long_file_bytes=longfile.stat().st_size,
        limits='Synthetic FLAC clock/performance only; not real long-GOP media or listening judgement.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=True,checks=len(rows),long_tail=row,output=str(out)),ensure_ascii=False))


if __name__=='__main__':main()
