"""Reject invisible HTML layers before the full production frame sequence."""
from copy import deepcopy
import math
from pathlib import Path
import time
from PIL import Image


def preflight_web_captions(props, renderer_root, temp, *, cancelled=None, trace=None):
    from .renderer_service import RendererJob, RendererService
    cues=[cue for cue in props['cues'] if (cue.get('visual') or props['recipes'].get(cue['styleId'],{})).get('webTheme')]
    if not cues:return
    # First and longest text exercise startup and the tightest authored well.
    selected={cues[0]['id']:cues[0]}
    longest=max(cues,key=lambda c:len(c['text']));selected[longest['id']]=longest
    jobs=[];started=time.perf_counter();service=RendererService(renderer_root)
    try:
        for i,cue in enumerate(selected.values()):
            local=deepcopy(props);local['cues']=[cue]
            frame=math.floor((cue['startMs']+cue['endMs'])/2000*props['fps'])
            frame=min(props['durationInFrames']-1,max(0,frame))
            jobs.append(RendererJob(str(Path(temp)/f'html-preflight-{i}.png'),local,frame,
                cue_id=cue['id'],job_kind='production'))
        handle=service.submit(jobs,timeout=90)
        while not handle._event.wait(.05):
            if cancelled and cancelled():handle.cancel();raise InterruptedError('render cancelled')
        result=handle.result(1)
        for job in jobs:
            result.require_job(job)
            with Image.open(job.output) as image:bounds=image.getchannel('A').getbbox()
            receipt={'cue':job.cue_id,'frame':job.frame,'alpha_bbox':bounds}
            if trace:trace('html_pixel_preflight',receipt)
            if bounds is None:
                raise RuntimeError(f'HTML_EMPTY_LAYER：字幕 {job.cue_id} 在帧 {job.frame} 的渲染层完全透明；请查看 HTML 舞台/字体/动效诊断')
    finally:
        service.shutdown()
        if trace:trace('html_pixel_preflight_seconds',time.perf_counter()-started)
