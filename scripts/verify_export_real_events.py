"""Decode the same real glyphs and audio in old/new outputs; no timestamp-only gate."""
import argparse, copy, json, os, sys
from pathlib import Path
import av
import numpy as np
from scipy.ndimage import binary_dilation
from scipy.signal import correlate, correlation_lags

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    for name in ('project','old','new','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'): raise ValueError('tmp output required')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import load_project
    from twobyteasr.export_timeline import export_project_snapshot
    from twobyteasr.ass_compiler import compile_ass
    from twobyteasr.studio_render import _filter_path
    from twobyteasr.processes import run_hidden_subprocess as run
    project=export_project_snapshot(load_project(args.project))
    ffmpeg=str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe')
    records=[]
    for target in (2.6,180,343):
        cue=min(project.cues,key=lambda c:abs(c.start_ms/1000-target))
        snapshot=copy.deepcopy(project); snapshot.cues=[copy.deepcopy(cue)]
        snapshot.cues[0].start_ms=0; snapshot.cues[0].end_ms=10000
        ass=out/f'template-{target}.ass'; ass.write_text(compile_ass(snapshot,frame_rate=60),encoding='utf-8-sig')
        raw=run([ffmpeg,'-v','error','-f','lavfi','-i','color=black:s=2560x1440:r=60',
            '-vf',f'ass=filename={_filter_path(ass)}:fontsdir={_filter_path(ROOT/"assets/fonts")},scale=1280:720',
            '-frames:v','1','-pix_fmt','gray','-f','rawvideo','pipe:1'],capture_output=True,check=True,timeout=20,
            purpose='render exact cue glyph template').stdout
        template=np.frombuffer(raw,dtype=np.uint8).reshape(720,1280)
        inside=template>210
        # Adjacent black outline distinguishes this exact glyph shape from a bright scene.
        ring=binary_dilation(inside,iterations=2)&(template<25)
        yy,xx=np.where(binary_dilation(inside,iterations=3)); y0,y1,x0,x1=yy.min(),yy.max()+1,xx.min(),xx.max()+1
        inside=inside[y0:y1,x0:x1]; ring=ring[y0:y1,x0:x1]
        item={'text':cue.text,'cue_start':cue.start_ms/1000,'cue_end':cue.end_ms/1000}
        for label,path in [('old',args.old),('new',args.new)]:
            frames=[]
            lo=max(0,cue.start_ms/1000-1.5); hi=cue.end_ms/1000+.3
            with av.open(str(path)) as container:
                stream=container.streams.video[0]
                container.seek(int(lo/stream.time_base),stream=stream,backward=True)
                for frame in container.decode(stream):
                    t=float(frame.pts*frame.time_base)
                    if t<lo:continue
                    if t>hi:break
                    rgb=frame.reformat(width=1280,height=720,format='gray').to_ndarray()[y0:y1,x0:x1]
                    score=float(rgb[inside].mean()-rgb[ring].mean())
                    frames.append((t,score))
            # The template core is white with a black outline; >90 is conservative.
            active=[t for t,s in frames if s>90]
            item[label]={'first':min(active) if active else None,'last':max(active) if active else None,
                         'scores':frames}
            if active:
                item[label]['onset_error_ms']=(min(active)-cue.start_ms/1000)*1000
                item[label]['offset_error_ms']=(max(active)+1/60-cue.end_ms/1000)*1000
        records.append(item)
    audio=[]
    for t in (2,178,341):
        waves=[]
        for path in (args.old,args.new):
            pcm=run([ffmpeg,'-v','error','-ss',str(t),'-i',str(path),'-t','5','-vn','-ac','1','-ar','16000',
                     '-f','f32le','pipe:1'],capture_output=True,check=True,timeout=20,purpose='compare same exported audio').stdout
            waves.append(np.frombuffer(pcm,dtype='<f4'))
        corr=correlate(waves[1],waves[0],method='fft'); lags=correlation_lags(len(waves[1]),len(waves[0]))
        where=abs(lags)<16000; best=np.flatnonzero(where)[np.argmax(corr[where])]
        audio.append({'seconds':t,'new_minus_old_ms':float(lags[best]/16),
                      'correlation':float(corr[best]/np.sqrt(np.dot(waves[0],waves[0])*np.dot(waves[1],waves[1])))})
    def images(path,lo,hi):
        rows=[]
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            container.seek(int(max(0,lo)/stream.time_base),stream=stream,backward=True)
            for frame in container.decode(stream):
                t=float(frame.pts*frame.time_base)
                if t<lo:continue
                if t>hi:break
                pixels=frame.reformat(width=320,height=180,format='rgb24').to_ndarray().astype(np.float32)
                rows.append((t,pixels[:140]))
        return rows
    video=[]
    for t in (2,3,12,180,343):
        reference=images(args.old,t-.001,t+.02)[0]
        compared=sorted((float(np.abs(p-reference[1]).mean()),at) for at,p in images(args.new,t-.06,t+.06))
        video.append({'seconds':t,'best_new_minus_old_ms':(compared[0][1]-reference[0])*1000,
                      'mean_absolute_rgb_error':compared[0][0]})
    first_video={label:next(t for t,p in images(path,0,1.5) if p.mean()>10) for label,path in [('old',args.old),('new',args.new)]}
    report={'events':records,'audio':audio,'video':video,'first_nonblack':first_video,'human_listening':'NOT VERIFIED'}
    (out/'events.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'events':[{k:v for k,v in row.items() if k not in ('old','new')}|{
        label:{k:v for k,v in row[label].items() if k!='scores'} for label in ('old','new')} for row in records],
        'audio':audio,'video':video,'first_nonblack':first_video},ensure_ascii=False))


if __name__=='__main__':main()
