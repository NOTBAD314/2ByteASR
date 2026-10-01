"""Three-second native production export, style receipt and decoded frames."""
import argparse,json,os,sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('tmp output required')
    out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from twobyteasr.studio_project import load_project
    from twobyteasr.ass_compiler import compile_ass
    from twobyteasr.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.studio_render import RenderJob,RenderSettings,run_render_job
    from twobyteasr.processes import run_hidden_subprocess
    project=load_project(a.project);cue=project.cues[0]
    ass=out/'captions.ass';ass.write_text(compile_ass(project),encoding='utf8')
    movie=out/'caption-proof.mp4';ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    job=RenderJob(project.media.path,str(ass),str(movie),settings=RenderSettings(encoder='libx264',preset='ultrafast',
        width=1920,height=1080,fps=30,audio_codec='none'),start_seconds=1.1,duration_seconds=3,overwrite_existing=True)
    from twobyteasr.advanced_renderer import split_renderer_cues,AdvancedRendererBackend,compile_composition_data
    if split_renderer_cues(project)[1]:
        AdvancedRendererBackend().render(project,ffmpeg,job)
        (out/'composition.json').write_text(json.dumps(compile_composition_data(project,width=1920,height=1080,
            fps=30,start_seconds=1.1,duration_seconds=3),ensure_ascii=False,indent=2),encoding='utf8')
    else:run_render_job(ffmpeg,job)
    for timepoint in (0,1,2.9):
        run_hidden_subprocess([ffmpeg,'-v','error','-y','-ss',str(timepoint),'-i',movie,'-frames:v','1',out/f'export-{timepoint:g}.png'],
            check=True,timeout=20,purpose='decode native production caption proof')
    caption=build_visual_cue_snapshot(project,cue.id).resolved_caption
    result={'style_hash':caption.style_hash,'line_count':caption.line_count,'font_loaded':caption.font_loaded,
        'measured_width':caption.measured_width,'max_width':caption.max_width,'movie':str(movie),'bytes':movie.stat().st_size,
        'production_entry':'studio_render.run_render_job','duration_seconds':3,'audio':'none'}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
