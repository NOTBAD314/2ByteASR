"""Frozen-process production exports for the completed special-path candidate."""
import hashlib
import json
from pathlib import Path
import traceback


def start(window, output):
    import av
    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..exports.studio_render import RenderJob, RenderSettings, run_render_job
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..rendering.ass_compiler import compile_ass
    from ..runtime_paths import detect_install_root
    from ..system.processes import run_hidden_subprocess
    import sys
    result=dict(passed=False,checks=[],frozen=bool(getattr(sys,'frozen',False)),pid=__import__('os').getpid(),executable=sys.executable)
    def write():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name, passed, **detail):
        result['checks'].append(dict(name=name,passed=bool(passed),**detail));write()
        if not passed:raise AssertionError(name)
    def run():
        try:
            ffmpeg=detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe'
            source_name='[10-23-26] cerberVT - FNAF IN VR ＊GONE WRONG＊ ＊COPS WERE CALLED＊ ↜૮^ ＞ω＜^ა 💜🦴 !patreon.mp4'
            for mode in ('native','static','long-static'):
                folder=output/(mode+" O'Brien [字幕];100% 💜🦴");folder.mkdir()
                source=folder/source_name;seconds=12 if mode=='long-static' else 1
                run_hidden_subprocess([ffmpeg,'-v','error','-f','lavfi','-i',f'color=c=0x202020:s=320x180:r=30:d={seconds}',
                    '-f','lavfi','-i',f'sine=frequency=440:duration={seconds}','-c:v','libx264','-threads','2','-c:a','aac',source],
                    check=True,timeout=40,purpose='daily candidate export fixture')
                original=hashlib.sha256(source.read_bytes()).hexdigest();count=1736 if mode=='long-static' else 1
                project=SubtitleProject(StudioMedia(str(source),duration_ms=seconds*1000,width=320,height=180),
                    styles=[SubtitleStyle('g','Caption',font_size=80)],cues=[StudioCue(str(i),round(i*seconds*1000/count),
                    round((i+1)*seconds*1000/count),f'C{i:04}',style_id='g') for i in range(count)])
                if mode!='native':
                    project.style_recipes['g']={'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{
                        'fill':{'type':'linear-gradient','angle':0,'stops':[
                            {'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}}}
                project.validate();ass=folder/"p O'Brien [1].ass";ass.write_text(compile_ass(project),encoding='utf-8-sig')
                destination=folder/"成品 O'Brien [2],100% 💜🦴.mp4"
                job=RenderJob(str(source),str(ass),str(destination),RenderSettings(encoder='libx264',preset='ultrafast',
                    width=320,height=180,fps=30,audio_codec='aac'),start_seconds=.001 if count>1 else 0,
                    duration_seconds=seconds-.001 if count>1 else seconds)
                if mode=='native':run_render_job(ffmpeg,job)
                else:AdvancedRendererBackend().render(project,ffmpeg,job)
                frames=list(av.open(str(destination)).decode(video=0))
                check(mode+' decoded frames',len(frames)==seconds*30,frames=len(frames),cues=count)
                visible=0
                for frame in frames[:-1]:
                    rgb=frame.to_ndarray(format='rgb24').astype(int)
                    visible+=bool(np.count_nonzero(rgb.min(axis=2)>180)>5 if mode=='native' else
                                  np.count_nonzero((rgb[:,:,0]>120)&(rgb[:,:,0]>rgb[:,:,1]+30))>5)
                check(mode+' subtitle pixels',visible==len(frames)-1,visible_frames=visible)
                audio=sum(frame.samples for frame in av.open(str(destination)).decode(audio=0))
                check(mode+' audio',audio>40000*seconds,samples=audio)
                check(mode+' source unchanged',hashlib.sha256(source.read_bytes()).hexdigest()==original)
            result['passed']=True
        except BaseException:result['error']=traceback.format_exc()
        write();window.close();QTimer.singleShot(500,QApplication.instance().quit)
    def shutdown():result['gui_shutdown']=True;write()
    QApplication.instance().aboutToQuit.connect(shutdown)
    write();QTimer.singleShot(250,run)
