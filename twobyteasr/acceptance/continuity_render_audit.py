"""Native video, isolated speaker masks and every-frame handoff evidence."""
from pathlib import Path
from fractions import Fraction
import json
import subprocess


def run(project_path, output, product_root, *, masks=True):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.caption_style.collision_layout import project_layout_schedule
    from twobyteasr.exports.studio_render import RenderSettings, RenderJob, run_render_job
    from twobyteasr.app.ui import _register_bundled_fonts
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    project = load_project(project_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = Path(product_root)/'tools/ffmpeg/bin/ffmpeg.exe'
    result = dict(project=str(project_path), frames=[], clips=[], checks={})
    plan = project_layout_schedule(project)
    yes = next(c for c in project.cues if c.text=='是的' and 86000<c.start_ms<87500)
    following = next(c for c in project.cues if c.text=='八连击的月光合奏')
    good = next(c for c in project.cues if c.text=='好' and 87000<c.start_ms<87500)
    result['core_offsets'] = {c.id:plan[c.id][0][2] for c in (yes,good,following)}
    ass=output/'captions.ass'
    ass.write_text(compile_ass(project),encoding='utf-8-sig')
    settings=RenderSettings(encoder='libx264',preset='ultrafast',width=960,height=540,fps=60,
        audio_codec='aac',font_directory=str(Path(product_root)/'assets/fonts'))
    for name,start,duration in [('handoff-14',14.1,1.2),('alternating-45',45,8.5),('core-87',86.4,3.1)]:
        video=run_render_job(ffmpeg,RenderJob(project.media.path,str(ass),str(output/(name+'.mp4')),
            settings=settings,start_seconds=start,duration_seconds=duration))
        result['clips'].append(dict(name=name,path=str(video),start=start,duration=duration))
    if masks:
        black=output/'black.mp4'
        subprocess.run([str(ffmpeg),'-n','-v','error','-f','lavfi','-i',
            'color=c=black:s=960x540:r=60:d=100','-c:v','libx264','-preset','ultrafast','-threads','2',str(black)],check=True)
        from PIL import Image,ImageChops
        from dataclasses import replace
        for fps in [Fraction(24_000,1001),Fraction(30_000,1001),Fraction(60_000,1001),Fraction(60)]:
            tag=str(fps.numerator)+'-'+str(fps.denominator)
            lane_ass=output/('lane-'+tag+'.ass')
            lane_ass.write_text(compile_ass(project,frame_rate=fps,cues=[c for c in project.cues if c.speaker_id==yes.speaker_id]),encoding='utf-8-sig')
            video=run_render_job(ffmpeg,RenderJob(str(black),str(lane_ass),str(output/('lane-'+tag+'.mp4')),
                settings=replace(settings,fps=float(fps),audio_codec='none'),start_seconds=86.8,duration_seconds=1.8))
            folder=output/('frames-'+tag);folder.mkdir()
            subprocess.run([str(ffmpeg),'-v','error','-i',str(video),'-threads','2',str(folder/'%04d.png')],check=True)
            frames=[]
            for index,path in enumerate(sorted(folder.glob('*.png'))):
                image=Image.open(path).convert('RGB')
                difference=ImageChops.difference(image,Image.new('RGB',image.size)).convert('L')
                box=difference.point(lambda x:255 if x>40 else 0).getbbox()
                frames.append(dict(index=index,global_ms=86800+index*1000/float(fps),bounds=box))
            core=[frame for frame in frames if 87000<=frame['global_ms']<=87500]
            gap=[frame for frame in core if 87140<=frame['global_ms']<=87220 and frame['bounds'] is None]
            before=[frame['bounds'][3] for frame in core if frame['global_ms']<87100 and frame['bounds']]
            after=[frame['bounds'][3] for frame in core if 87300<frame['global_ms']<87400 and frame['bounds']]
            result['checks']['no_blank_'+tag]=not gap
            result['checks']['same_lane_bottom_'+tag]=bool(before and after) and abs(sum(before)/len(before)-sum(after)/len(after))<=6
            result['frames'].append(dict(fps=str(fps),samples=frames,blank_frames_in_core_gap=len(gap)))
    result['passed']=all(result['checks'].values())
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
