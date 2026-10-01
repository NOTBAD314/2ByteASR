"""Frozen, exact project-frame export, independent of the preview mailbox."""
from pathlib import Path
from fractions import Fraction
import re
import tempfile
import time
import uuid


def safe_frame_name(name, milliseconds):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(name)).strip(' .')[:100] or '封面'
    if name.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:name='_'+name
    ms=int(milliseconds)
    return f'{name}_{ms//3600000:02}-{ms//60000%60:02}-{ms//1000%60:02}-{ms%1000:03}'


def decode_frame(path, seconds):
    import av
    from PySide6.QtGui import QImage
    from .video_decode_worker import display_bgra
    with av.open(str(path)) as container:
        stream=container.streams.video[0]
        stream.thread_type='AUTO';stream.thread_count=4
        origin=Fraction(container.start_time or 0,1000000)
        target=Fraction(seconds)+origin
        # Start from a preceding keyframe, then pick the actual display PTS.
        # Near-start FLV seeks can omit the first GOP: decode from the head.
        if seconds>=10:
            container.seek(int(max(origin,target-2)/stream.time_base),stream=stream,backward=True)
        current=None;future=None
        for frame in container.decode(stream):
            if frame.pts is None:continue
            pts=frame.pts*frame.time_base
            if pts>target:
                future=pts
                if current is None:
                    # Refuse stale/ahead frames rather than silently saving it.
                    raise RuntimeError('媒体索引未定位到目标帧，请在附近重新定位后重试。')
                break
            current=frame
        if current is None:raise RuntimeError('目标时刻没有可解码视频帧。')
        w,h,pixels=display_bgra(current,float(stream.sample_aspect_ratio or 1),(max(current.width,current.height)*16,)*2)
        image=QImage(pixels,w,h,w*4,QImage.Format_ARGB32).copy()
        return image,{'source_seconds':float(seconds),'frame_seconds':float(current.pts*current.time_base-origin),
                      'next_seconds':None if future is None else float(future-origin),'path':str(path)}


def save_project_frame(project, graph, milliseconds, directory, name, *, subtitles=True, extension='png', ffmpeg=None,
                       require_video_frame=False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    from .video_export import paint_layer
    from .clip_time_mapper import project_to_source_exact
    from .advanced_renderer import split_renderer_cues,compile_composition_data
    from .ass_compiler import compile_ass
    from .processes import run_hidden_subprocess
    from .studio_edit_sequence import timeline_duration_ms
    started=time.perf_counter();directory=Path(directory)
    if not directory.is_dir():raise OSError('保存帧目录不存在，请重新选择目录。')
    ms=Fraction(str(milliseconds));duration=timeline_duration_ms(project)
    if ms<0 or ms>=duration:raise ValueError('播放头须位于工程内的有效视频帧，片尾出点不包含。')
    width=int(graph['width'] or 1920);height=int(graph['height'] or 1080)
    image=QImage(width,height,QImage.Format_ARGB32_Premultiplied);image.fill(Qt.black)
    assets={a['asset_id']:a for a in graph['media_pool']};receipts=[]
    painter=QPainter(image);painter.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        for track in sorted(graph['video_tracks'],key=lambda t:(t.get('z_index',0),t['id'])):
            if not track.get('enabled',True):continue
            for clip in track['clips']:
                if not clip.get('enabled',True) or not clip['timeline_in_ms']<=ms<clip['timeline_out_ms']:continue
                asset=assets[clip['asset_id']]
                if asset.get('video_metadata',{}).get('has_video') is False:continue
                layer,receipt=decode_frame(asset['canonical_source'],project_to_source_exact(clip,ms/1000))
                receipt['clip_id']=clip['id'];receipts.append(receipt)
                paint_layer(painter,width,height,layer,clip)
    finally:painter.end()
    if require_video_frame and not receipts:
        raise ValueError('当前时间位于空轨或已停用的视频片段，没有可用视频帧')
    with tempfile.TemporaryDirectory(prefix='2byte-frame-') as temp:
        temp=Path(temp)
        if subtitles:
            native,advanced=split_renderer_cues(project)
            if any(c.start_ms<=ms<c.end_ms for c in native):
                # Production libass evaluates at the frozen project time.
                raw=temp/'video.png';image.save(str(raw))
                ass=temp/'frame.ass';ass.write_text(compile_ass(project,cues=native),encoding='utf-8-sig')
                from .advanced_renderer import _ffmpeg_filter_path
                rendered=temp/'native.png'
                filters=f'settb=1/1000000,setpts=PTS+{float(ms/1000):.9f}/TB,ass=filename={_ffmpeg_filter_path(ass)}:fontsdir={_ffmpeg_filter_path(Path(__file__).resolve().parents[1]/"assets/fonts")}'
                result=run_hidden_subprocess([str(ffmpeg),'-hide_banner','-loglevel','error','-i',str(raw),'-vf',filters,'-frames:v','1','-y',str(rendered)],
                    capture_output=True,timeout=45,purpose='save current frame captions')
                if result.returncode:raise RuntimeError('字幕帧渲染失败：'+result.stderr.decode('utf-8',errors='replace')[-600:])
                image=QImage(str(rendered))
                if image.isNull():raise RuntimeError('字幕帧为空，未保存。')
            active=[c for c in advanced if c.start_ms<=ms<c.end_ms]
            if active:
                from .static_caption_contract import shared_static_cue
                from .advanced_renderer import recipe_payload_for_cue
                from .visual_snapshot import build_visual_cue_snapshot
                from .advanced_live_renderer import render_live_snapshot
                if all(shared_static_cue(project,c) for c in active):
                    painter=QPainter(image)
                    try:
                        for cue in active:painter.drawImage(0,0,render_live_snapshot(build_visual_cue_snapshot(project,cue.id,width=width,height=height),width=width,height=height))
                    finally:painter.end()
                else:
                    from .renderer_service import GLOBAL_RENDERER_SERVICE,RendererJob
                    from .caption_frame_time import project_frame_rate
                    fps=float(project_frame_rate(project) or 30)
                    props=compile_composition_data(project,width=width,height=height,fps=fps,start_seconds=0,duration_seconds=duration/1000)
                    target=temp/'advanced.png'
                    job=RendererJob(str(target),props,int(ms*Fraction(str(fps))/1000),job_id=uuid.uuid4().hex,job_kind='production')
                    GLOBAL_RENDERER_SERVICE.render([job],render_type='still',resolution=(width,height),timeout=90).require_job(job)
                    overlay=QImage(str(target))
                    if overlay.isNull():raise RuntimeError('高级字幕帧不可用，未保存。')
                    painter=QPainter(image);painter.drawImage(0,0,overlay);painter.end()
        suffix='jpg' if extension in ('jpg','jpeg') else 'png'
        stem=safe_frame_name(name,ms)
        for index in range(1,100000):
            output=directory/f'{stem}_{index:03}.{suffix}'
            try:
                handle=output.open('xb');handle.close();break
            except FileExistsError:continue
        else:raise OSError('同一时间码的文件过多，请更换保存目录。')
        try:
            if not image.save(str(output),'JPEG' if suffix=='jpg' else 'PNG',98):raise OSError('无法写入图片，请检查目录权限与剩余空间。')
        except BaseException:
            output.unlink(missing_ok=True);raise
    return dict(path=str(output),project_id=project.project_id,milliseconds=float(ms),width=width,height=height,
                subtitles=subtitles,decode=receipts,elapsed_seconds=time.perf_counter()-started)
