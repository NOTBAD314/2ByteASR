"""Real production ASS and static-raster exports of marked bilingual captions."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='offscreen')
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings,run_render_job
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
    from twobyteasr.caption_style.bilingual_layout import materialize_display_project
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
    from PySide6.QtGui import QImage,QPainter
    import av
    import numpy as np
    app=QApplication.instance() or QApplication([])
    from twobyteasr.app.ui import _register_bundled_fonts
    _register_bundled_fonts()
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe';source=out/'source.mp4'
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x203040:s=640x360:r=30:d=3',
        '-c:v','libx264','-preset','ultrafast',str(source)],purpose='marked caption export fixture',check=True,timeout=20)
    p=SubtitleProject(media=StudioMedia(str(source),duration_ms=3000,width=640,height=360),
        speakers=[StudioSpeaker('S01','隊長')],cues=[StudioCue('a',500,2500,'今天通過最後一關',speaker_id='S01')])
    p.cues[0].appearance_override={'text_marks':[{'start':4,'end':8,'bold':True,'color':'#FF3B30'}],
        'translation':{'style':{'font_size':44,'primary_color':'#FFFFFF'},
                       'text_marks':[{'start':0,'end':7,'italic':True,'color':'#FFD166'}]}}
    p.generation_metadata['translations']={'a':'Victory at last'}
    p.studio_state['bilingual']={'mode':'bilingual','original_scale':1,'translation_scale':.8}
    p.validate();save_project(p,out/'marked-bilingual.2byteproj')
    result={'cases':[],'source':'production FFmpeg/ASS and AdvancedRendererBackend; generated fixture'}
    for route in ('native','static'):
        if route=='static':p.style_recipes['default']={'name':'靜態字面','engine':'remotion','motion':{'mode':'none'},
            'colors':{'fill':{'type':'linear-gradient','angle':0,'stops':[{'position':0,'color':'#FFFFFF'},{'position':1,'color':'#FFF0D0'}]}}}
        ass=out/f'{route}.ass';snapshot=write_export_ass(p,ass,fps=30)
        job=RenderJob(str(source),str(ass),str(out/f'{route}.mp4'),
            RenderSettings(encoder='libx264',preset='ultrafast',quality=12,width=640,height=360,fps=30),
            duration_seconds=3,video_graph=capture_video_graph(p))
        if route=='static':AdvancedRendererBackend().render(snapshot,ffmpeg,job)
        else:run_render_job(ffmpeg,job)
        counts=[]
        with av.open(job.output_path) as container:
            for frame in container.decode(video=0):
                rgb=frame.to_ndarray(format='rgb24');at=float(frame.pts*frame.time_base)
                red=int(np.count_nonzero((rgb[:,:,0]>160)&(rgb[:,:,1]<110)&(rgb[:,:,2]<110)))
                yellow=int(np.count_nonzero((rgb[:,:,0]>150)&(rgb[:,:,1]>120)&(rgb[:,:,2]<130)))
                counts.append((at,red,yellow))
                if abs(at-1)<.001:frame.to_image().save(out/f'{route}-export.png')
        active=[v for v in counts if .6<v[0]<2.4];outside=[v for v in counts if v[0]<.4 or v[0]>2.6]
        result['cases'].append({'route':route,'frames':len(counts),'active_min_red':min(v[1] for v in active),
            'active_min_yellow':min(v[2] for v in active),'outside_max_red':max(v[1] for v in outside),
            'passed':all(v[1]>30 and v[2]>20 for v in active) and all(v[1]==0 for v in outside)})
        display=materialize_display_project(p)
        image=QImage(640,360,QImage.Format_ARGB32_Premultiplied);image.fill(0xff203040)
        painter=QPainter(image)
        for cue in display.cues:
            snap=build_visual_cue_snapshot(display,cue.id,width=640,height=360)
            painter.drawImage(0,0,render_live_snapshot(snap,width=640,height=360))
        painter.end();image.save(str(out/f'{route}-preview.png'))
    result['passed']=all(row['passed'] for row in result['cases'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
