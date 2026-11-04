"""Same-machine production export benchmark; lossless stage evidence in JSON."""
import argparse
import cProfile
import copy
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--encoder',default='libx264')
    parser.add_argument('--repeat',type=int,default=3)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out);os.environ['QT_QPA_PLATFORM']='offscreen'
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,hydrate_media_contract
    from twobyteasr.studio.studio_helpers import probe_media_identity
    from twobyteasr.exports.studio_render import RenderSettings,RenderJob,run_render_job,probe_encoder_detail
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.caption_style.motion_application import motion_command
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';media=root/'tmp/workbench-perf/壓制 基準.mp4'
    if not media.exists():
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=30',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','6',
            '-c:v','libx264','-preset','medium','-crf','20','-c:a','aac',str(media)],
            check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    identity=probe_media_identity(str(media))
    result={'media':str(media),'ffmpeg':str(ffmpeg),'encoder':args.encoder,'runs':[],
            'note':'Decode, filters, burn-in, encode and mux overlap inside one FFmpeg process; not added as separate wall times.'}
    import psutil
    current=psutil.Process()
    result['host']={'cpu_count':os.cpu_count(),'ram_bytes':psutil.virtual_memory().total}
    for case in ('video','subtitle','bilingual','motion'):
        for run in range(args.repeat):
            p=SubtitleProject(media=StudioMedia(str(media),duration_ms=6000,width=1280,height=720),
                cues=[] if case=='video' else [StudioCue('a',0,3000,'字幕與音訊壓制效能測試'),StudioCue('b',3000,6000,'相同解析度與畫質設定')])
            if case in ('bilingual','motion'):
                p.generation_metadata['translations']={'a':'Subtitle and audio export','b':'Identical resolution and quality'}
                p.studio_state['bilingual']={'mode':'bilingual'}
            hydrate_media_contract(p,identity);p.validate();p.render_settings.update(play_res_x=1280,play_res_y=720,_cue_domain='timeline')
            if case=='motion':
                motion_command(p,[c.id for c in p.cues],motion={'entry':{'type':'float_up','duration':400}},language='linked').redo()
            profile=cProfile.Profile();events=[];progress=[];samples=[];stop=threading.Event()
            def sample():
                while not stop.wait(.1):
                    try:
                        children=current.children(recursive=True)
                        samples.append({'at':time.perf_counter(),'rss':sum(x.memory_info().rss for x in [current,*children]),
                            'cpu_seconds':sum(x.cpu_times().user+x.cpu_times().system for x in children)})
                    except psutil.Error:pass
            sampler=threading.Thread(target=sample,daemon=True);sampler.start()
            started=time.perf_counter();profile.enable()
            ass=out/f'{case}-{run}.ass';write_export_ass(p,ass,fps=30)
            prepared=time.perf_counter()
            settings=RenderSettings(encoder=args.encoder,preset='medium' if args.encoder=='libx264' else 'p4',
                quality_mode='crf' if args.encoder=='libx264' else 'cq',quality=20,width=1280,height=720,fps=30,audio_codec='aac')
            job=RenderJob(str(media),str(ass),str(out/f'{case}-{run}.mp4'),settings,
                start_seconds=0,duration_seconds=6,video_graph=capture_video_graph(p))
            run_render_job(ffmpeg,job,progress=lambda row:progress.append({'at':time.perf_counter()-started,**row}),
                trace=lambda event,value=None,**fields:events.append({'at':time.perf_counter()-started,'event':event,'value':value,**fields}))
            end=time.perf_counter();profile.disable();stop.set();sampler.join(1)
            profile.dump_stats(str(out/f'{case}-{run}.prof'))
            row={'case':case,'run':run,'wall_seconds':end-started,'prepare_subtitles_seconds':prepared-started,
                'speed_x':6/(end-started),'processed_fps':180/(end-started),'events':events,'progress':progress,
                'peak_rss_bytes':max((s['rss'] for s in samples),default=None),
                'max_sampled_child_cpu_seconds':max((s['cpu_seconds'] for s in samples),default=None),
                'receipt':job.completion_metadata}
            result['runs'].append(row)
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
            print(case,run,round(row['wall_seconds'],3),flush=True)
    print(json.dumps({case:statistics.median(r['wall_seconds'] for r in result['runs'] if r['case']==case)
          for case in ('video','subtitle','bilingual','motion')}))


if __name__=='__main__':main()
