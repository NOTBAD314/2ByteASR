"""Production renderer and encoded-video opacity audit, with isolated assets."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve()
    assert out.is_relative_to(ROOT/'tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ.update(QT_QPA_PLATFORM='offscreen',LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    import numpy as np
    from PIL import Image
    from twobyteasr.studio_project import StudioMedia,StudioCue,SubtitleStyle,SubtitleProject,save_project
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.visual_design_graph import graph_from_style_recipe
    from twobyteasr.advanced_renderer import AdvancedRendererBackend,compile_composition_data
    from twobyteasr.renderer_service import RendererService,RendererJob
    from twobyteasr.studio_render import RenderJob,RenderSettings
    from twobyteasr.processes import run_hidden_subprocess
    from twobyteasr.export_timeline import write_export_ass
    from twobyteasr.video_export import capture_video_graph
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    source=out/'background.mp4'
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=white:s=640x360:r=30:d=4',
        '-c:v','libx264','-preset','ultrafast',str(source)],check=True,capture_output=True,purpose='shadow audit source')
    p=SubtitleProject(media=StudioMedia(str(source),duration_ms=4000,width=640,height=360),
        render_settings={'play_res_x':640,'play_res_y':360},styles=[],cues=[])
    for i,opacity in enumerate((0,.25,.5,1)):
        key=f'shadow-{i}'
        style=SubtitleStyle(key,key,font_family='Source Han Sans SC Medium',font_size=54,
            primary_color='#00FFFFFF',outline_width=0,shadow=0,position_x=320,position_y=220)
        p.styles.append(style)
        recipe=StyleRecipe(key,engine='remotion',typography={'fontFamily':style.font_family,'fontSize':54},
            layout={'positionX':320,'positionY':220},colors={'fill':'#00FFFFFF'},
            outline={'width':0,'shadow':dict(enabled=True,color='#FF000000',opacity=opacity,
                offset_x=18,offset_y=15,blur_radius=6,spread=3,strength=18)})
        recipe.visual_graph=graph_from_style_recipe(recipe).to_dict()
        p.style_recipes[key]=recipe.to_dict()
        p.cues.append(StudioCue(str(i),i*1000,(i+1)*1000,'阴影 Alpha',style_id=key))
    save_project(p,out/'shadow.2byteproj')
    props=compile_composition_data(p,width=640,height=360,fps=30,start_seconds=0,duration_seconds=4)
    jobs=[RendererJob(str(out/f'alpha-{i}.png'),props,15+i*30,job_kind='diagnostic') for i in range(4)]
    service=RendererService(ROOT/'renderer')
    try:
        result=service.submit(jobs,timeout=120).result(130)
        for job in jobs:result.require_job(job)
    finally:service.shutdown()
    alpha=[np.array(Image.open(job.output).convert('RGBA'))[:,:,3] for job in jobs]
    errors=[float(np.abs(a.astype(float)-alpha[3]*ratio).max()) for a,ratio in zip(alpha,(0,.25,.5,1))]
    assert not alpha[0].any(),int(alpha[0].max())
    assert max(errors)<=2,errors
    # The production video retains opaque text, as a real subtitle does.
    # White text on white video does not affect the isolated shadow darkness.
    for style in p.styles:
        if style.id not in p.style_recipes: continue
        style.primary_color='#FFFFFFFF'
        recipe=StyleRecipe.from_dict(p.style_recipes[style.id])
        recipe.colors['fill']='#FFFFFFFF'
        recipe.visual_graph=graph_from_style_recipe(recipe).to_dict()
        p.style_recipes[style.id]=recipe.to_dict()
    save_project(p,out/'encoded-shadow.2byteproj')
    ass=out/'shadow.ass';write_export_ass(p,ass,fps=30)
    job=RenderJob(str(source),str(ass),str(out/'shadow.mp4'),
        RenderSettings(encoder='libx264',quality=12,preset='ultrafast',width=640,height=360,fps=30,audio_codec='none'),
        duration_seconds=4,video_graph=capture_video_graph(p))
    AdvancedRendererBackend().render(p,ffmpeg,job)
    import av
    means=[]
    with av.open(str(out/'shadow.mp4')) as movie:
        frames={15:0,45:1,75:2,105:3}
        mask=alpha[3]>80
        for index,frame in enumerate(movie.decode(video=0)):
            if index in frames:
                array=frame.to_ndarray(format='rgb24')
                Image.fromarray(array).save(out/f'encoded-{frames[index]}.png')
                means.append(float((255-array.astype(float).mean(axis=2))[mask].mean()))
    assert len(means)==4 and all(a<b for a,b in zip(means,means[1:])),means
    ratios=[(v-means[0])/max(1e-6,means[-1]-means[0]) for v in means]
    assert max(abs(a-b) for a,b in zip(ratios,(0,.25,.5,1)))<.05,ratios
    receipt={'passed':True,'renderer_alpha_max_errors':errors,'encoded_darkness':means,
             'encoded_opacity_ratios':ratios,'export_receipt':job.completion_metadata}
    (out/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
