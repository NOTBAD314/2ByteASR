"""Render a three-second production movie from the actual saved drag project."""
import json,os,sys,time
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    run=Path(sys.argv[1]);project_path=Path(json.loads((run/'result.json').read_text('utf8'))['saved_project'])
    out=run/'production-export';out.mkdir(exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.studio_project import load_project
    from twobyteasr.advanced_renderer import AdvancedRendererBackend,compile_composition_data,_overlay_cache_path
    from twobyteasr.studio_render import RenderJob,RenderSettings
    from twobyteasr.video_export import capture_video_graph
    from twobyteasr.web_placement import cue_placement
    from twobyteasr.web_theme import theme_archive_html
    from twobyteasr.renderer_service import RendererService
    from twobyteasr.processes import run_hidden_subprocess
    from PIL import Image
    import numpy as np
    project=load_project(project_path);cue=project.cues[0];placement=cue_placement(project,cue)
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';movie=out/'placement.mp4'
    job=RenderJob(project.media.path,str(out/'native.ass'),str(movie),
        settings=RenderSettings(encoder='libx264',preset='ultrafast',width=960,height=540,fps=30,audio_codec='none'),
        start_seconds=0,duration_seconds=3,overwrite_existing=True,video_graph=capture_video_graph(project))
    def trace(name,value):
        with (out/'trace.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(dict(name=name,value=value),ensure_ascii=False,default=str)+'\n')
    print('EXPORT',out,flush=True);start=time.monotonic()
    AdvancedRendererBackend().render(project,ffmpeg,job,trace=trace)
    props=compile_composition_data(project,width=960,height=540,fps=30,start_seconds=0,duration_seconds=3)
    cached=_overlay_cache_path(props)
    for source,name in ((movie,'movie-frame'),(cached,'overlay-frame')):
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss','1','-i',str(source),'-frames:v','1',str(out/(name+'.png'))],purpose='production movie placement frame evidence',check=True,timeout=20)
    service=RendererService()
    try:
        theme=project.style_recipes[cue.style_id]['webTheme']
        service.live_set(theme_archive_html(theme,sample_text=cue.text,duration_seconds=3,auto_replay=False,placement=placement),width=960,height=540)
        (out/'live-reference.png').write_bytes(service.live_pause(cue_ms=1000,stage_ms=1000))
    finally:service.shutdown()
    def bbox(path):
        alpha=np.array(Image.open(path).convert('RGBA'))[:,:,3];yy,xx=np.nonzero(alpha>25)
        return [int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())]
    expected=bbox(out/'live-reference.png');actual=bbox(out/'overlay-frame.png')
    result=dict(saved_project=str(project_path),placement=placement,seconds=time.monotonic()-start,movie=str(movie),movie_bytes=movie.stat().st_size,
        live_bbox=expected,encoded_overlay_bbox=actual,passed=bool(np.max(np.abs(np.array(expected)-actual))<=2),source='production AdvancedRendererBackend and encoded overlay cache')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(result,flush=True)
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
