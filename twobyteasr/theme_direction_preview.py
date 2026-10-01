"""One transparent render, stable subject crop and optional video comparison."""
from pathlib import Path
from io import BytesIO
import json
import math

def render_motion_preview(service,html,folder,candidate_id,*,cancel_check=lambda:False,progress=lambda value:None,background_path=None,duration_ms=6000):
    from PIL import Image
    folder=Path(folder);frames=folder/(candidate_id+'-frames');frames.mkdir(exist_ok=True)
    service.live_set(html,width=960,height=540)
    if isinstance(duration_ms,bool) or not isinstance(duration_ms,(int,float)) or not math.isfinite(duration_ms) or not 100<=duration_ms<=10000:
        raise ValueError('Motion review requires a finite 100–10000ms cue')
    samples=[];fps=24;visible_frames=0;bounds=None
    frame_count=math.ceil(duration_ms*fps/1000)
    background=Image.open(background_path).convert('RGBA').resize((960,540)) if background_path else Image.new('RGBA',(960,540),'#20262e')
    transparent=folder/(candidate_id+'-transparent');transparent.mkdir(exist_ok=True)
    for index in range(frame_count):
        if cancel_check():raise InterruptedError('方向动画已取消')
        if index%12==0:progress(f'方向 {candidate_id} · 完整动画 {index}/{frame_count} 帧')
        ms=index*1000/fps
        png=service.live_pause(cue_ms=ms,stage_ms=ms)
        im=Image.open(BytesIO(png)).convert('RGBA')
        box=im.getchannel('A').point(lambda a:255 if a>8 else 0).getbbox()
        if box:
            visible_frames+=1
            bounds=box if bounds is None else (min(bounds[0],box[0]),min(bounds[1],box[1]),max(bounds[2],box[2]),max(bounds[3],box[3]))
        im.save(transparent/f'{index:04}.png')
        samples.append(dict(frame=index,time_ms=ms))
    if visible_frames==0:
        raise ValueError(f'完整动画{frame_count}帧均为空白；请检查主体尺寸、单位、位置和父层可见性')
    # One envelope for the entire motion: never resize/recenter each frame.
    bounds=(max(0,(bounds[0]-20)//2*2),max(0,(bounds[1]-20)//2*2),
            min(960,(bounds[2]+21)//2*2),min(540,(bounds[3]+21)//2*2))
    from .processes import run_hidden_subprocess
    from .audio_engine import studio_ffmpeg_path
    ffmpeg=studio_ffmpeg_path()
    def encode(mode):
        movie=[]
        target=frames if mode=='subject' else folder/(candidate_id+'-context-frames');target.mkdir(exist_ok=True)
        for index in range(frame_count):
            if cancel_check():raise InterruptedError('方向动画已取消')
            with Image.open(transparent/f'{index:04}.png') as source:
                im=source.convert('RGBA')
            if mode=='subject':
                im=im.crop(bounds);canvas=Image.new('RGBA',im.size,'#20262e')
            else:canvas=background
            composite=Image.alpha_composite(canvas,im).convert('RGB')
            composite.save(target/f'{index:04}.png')
            if index%2==0:movie.append(composite)
        stem=candidate_id+('-motion' if mode=='subject' else '-context-motion')
        gif=folder/(stem+'.gif');video=folder/(stem+'.mp4')
        movie[0].save(gif,save_all=True,append_images=movie[1:],duration=([80,80,90]*((len(movie)+2)//3))[:len(movie)],loop=0,disposal=2)
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-framerate',str(fps),'-i',str(target/'%04d.png'),
            '-c:v','libx264','-crf','17','-pix_fmt','yuv420p',str(video)],check=True,capture_output=True,timeout=45,purpose='finite subtitle design preview')
        return dict(status='motion_ready',duration_ms=duration_ms,fps=fps,frame_count=len(samples),
            viewport=[bounds[2]-bounds[0],bounds[3]-bounds[1]] if mode=='subject' else [960,540],
            presentation=mode,full_frame=mode!='subject',background='current-media' if mode!='subject' and background_path else 'neutral',
            visible_frames=visible_frames,gif=str(gif),video=str(video),frames=str(target),samples=samples)
    data=encode('subject');data['subject_bbox']=list(bounds)
    try:
        data['context']=encode('context')
    except Exception as exc:
        if cancel_check():raise InterruptedError('方向动画已取消') from exc
        data['context_error']=str(exc)[:500]
        progress('字幕本体动画已就绪；辅助叠加预览暂未完成')
    data['transparent_frames']=str(transparent)
    (folder/(candidate_id+'-motion.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
    return data
