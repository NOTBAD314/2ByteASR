"""Isolated visual fixtures for the curated kinetic subtitle collection."""
from pathlib import Path
from types import SimpleNamespace


def make_project(media, *, duration=6000):
    from ..projects.studio_project import SubtitleProject,StudioCue,StudioMedia,SubtitleStyle
    from ..caption_style.letter_motion import PRESETS
    text='让每一句，都有余韵'
    cues=[]; evidence={}
    for i,mode in enumerate(PRESETS):
        start=i*duration
        cues.append(StudioCue(str(i),start,start+duration,text,effect_id=mode,evidence_refs=[str(i)]))
        evidence[str(i)]={'words':[{'text':t,'start_ms':round(start+duration*(.035+k*.085)),
                                  'end_ms':round(start+duration*(.075+k*.085))} for k,t in enumerate(text.replace('，',''))]}
    return SubtitleProject(media=StudioMedia(str(media),duration_ms=6*duration,width=960,height=540),cues=cues,
        styles=[SubtitleStyle('default','精选字效',font_family='Microsoft YaHei',font_size=92,
                              outline_width=1.4,outline_color='#303747',shadow=0)],asr_evidence=evidence)


def gallery(output, duration=6000, *, anonymous=False):
    import subprocess,json
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage,QPainter,QColor,QFont
    from PySide6.QtCore import Qt,QPointF
    from ..caption_style.letter_motion import PRESETS
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.caption_scene import SceneRasterizer
    from ..rendering.ass_compiler import compile_ass
    from ..projects.studio_project import save_project
    app=QApplication.instance() or QApplication([])
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    project=make_project(output/'source.mp4',duration=duration)
    save_project(project,output/'gallery.2byteproj')
    (output/'captions.ass').write_text(compile_ass(project),encoding='utf-8-sig')
    snapshots=[build_visual_cue_snapshot(project,c.id) for c in project.cues]
    from dataclasses import replace
    snapshots=[replace(s,position_y=540,position_x=960,anchor_y=.5,alignment=5,font_size=132) for s in snapshots]
    if anonymous:
        snapshots=[replace(s,word_animation={**s.word_animation,'color':'#FFFFFF'}) for s in snapshots]
    rasters=[SceneRasterizer() for _ in snapshots]
    size=(1440,720)
    ffmpeg=Path(__file__).resolve().parents[2]/'tools/ffmpeg/bin/ffmpeg.exe'
    proc=subprocess.Popen([str(ffmpeg),'-y','-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgba',
        '-video_size','1440x720','-framerate','24','-i','-','-c:v','libx264','-crf','19','-pix_fmt','yuv420p',str(output/'gallery.mp4')],stdin=subprocess.PIPE)
    for frame in range(round(duration/1000*24)+12):
        t=min(duration,frame/24*1000)
        image=QImage(*size,QImage.Format_RGBA8888);image.fill(QColor('#101722'))
        painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
        for i,(snap,raster,(mode,(name,description,color))) in enumerate(zip(snapshots,rasters,PRESETS.items())):
            x=(i%3)*480;y=(i//3)*360
            painter.fillRect(x+10,y+10,460,340,QColor('#192434'))
            painter.setPen(QColor('#FFFFFF' if anonymous else color));font=QFont('Microsoft YaHei');font.setPixelSize(19);painter.setFont(font)
            painter.drawText(x+28,y+48,str(i+1) if anonymous else name)
            if not anonymous:
                painter.setPen(QColor('#91A1B6'));font.setPixelSize(13);painter.setFont(font)
                painter.drawText(x+28,y+76,description)
            image0=raster.native_frame(SimpleNamespace(snapshot=snap,snapshot_hash=snap.stable_hash()),t,460,259)
            painter.drawImage(QPointF(x+10,y+80),image0)
        painter.setPen(QColor('#91A1B6'));painter.drawText(20,710,f'{t/1000:.2f} / {duration/1000:.1f} s · 实际 LIVE 渲染')
        painter.end()
        if frame%3==0 or frame==5:
            image.save(str(output/f'frame-{frame:03}.png'))
        proc.stdin.write(bytes(image.constBits()))
    proc.stdin.close();code=proc.wait()
    if code:raise RuntimeError('Gallery encoding failed')
    return 0


def run_window(output,theme='grape'):
    import time,json,traceback
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from ..studio.studio_ui import SubtitleStudioPage
    from ..design.theme_manager import apply_application_theme
    from ..projects.studio_project import save_project,load_project
    from ..caption_style.studio_motion_browser import MotionBrowserDialog,MotionCard
    from ..caption_style.word_animation import build_word_animation
    from ..caption_style.letter_motion import PRESETS
    from .blank_project_audit import _capture
    app=QApplication.instance() or QApplication([])
    apply_application_theme(app,theme)
    page=SubtitleStudioPage();page.resize(1480,900);page.show()
    project=make_project(output/'source.mp4')
    for cue in project.cues:cue.effect_id='none'
    source=save_project(project,output/'input.2byteproj')
    result={'checks':[],'passed':False}
    def check(name,condition):result['checks'].append({'name':name,'passed':bool(condition)})
    def steps():
        page.open_project(source,skip_dirty_guard=True)
        yield lambda:page.project is not None and page._readiness.ready and not page._readiness.active
        yield .6
        page.video.set_paused(True);page.context_drawer.setCurrentIndex(1)
        page.select_cue('0');page.motion_jump_button.click()
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('all'))
        for i,mode in enumerate(PRESETS):
            page.select_cue(str(i))
            if i:page.motion_scope.setCurrentIndex(page.motion_scope.findData('current'))
            before=[c.effect_id for c in page.project.cues]
            def library(mode=mode,i=i):
                dialog=app.activeModalWidget()
                check('library opens '+mode,isinstance(dialog,MotionBrowserDialog))
                if not isinstance(dialog,MotionBrowserDialog):return
                cards=dialog.host.findChildren(MotionCard)
                check('six featured cards '+mode,{c.preset.id for c in cards}==set(PRESETS))
                card=next(c for c in cards if c.preset.id==mode)
                QTest.mouseClick(card,Qt.LeftButton)
                card.start_preview()
                QTest.qWait(240)
                check('real preview clock '+mode,card.preview.timer.isActive())
                if i==0:_capture(dialog,output/'library.png')
                check('draft leaves project untouched '+mode,[c.effect_id for c in page.project.cues]==before)
                QTest.mouseClick(dialog.apply_button,Qt.LeftButton)
            QTimer.singleShot(500,library)
            page.motion_library_button.click()
            yield .35
            check('applied '+mode,build_word_animation(page.project,page.project.cues[i])['mode']==mode)
            if i==0:
                check('batch applies six',all(build_word_animation(page.project,c)['mode']==mode for c in page.project.cues))
            page._seek((i*6000+360)/1000)
            yield .3
            _capture(page,output/(mode+'.png'))
        saved=[c.effect_id for c in page.project.cues]
        page.undo_stack.undo();page.undo_stack.redo()
        check('undo redo exact effects',[c.effect_id for c in page.project.cues]==saved)
        path=save_project(page.project,output/'saved.2byteproj')
        loaded=load_project(path)
        check('save load all modes',[build_word_animation(loaded,c)['mode'] for c in loaded.cues]==list(PRESETS))
        page.resize(1100,720);page.select_cue('0')
        yield .4
        _capture(page,output/'small-window.png')
        page._seek(.05);page.video.set_paused(False)
        yield 2.0
        page.video.set_paused(True)
        _capture(page,output/'normal-playback.png')
    sequence=steps();pending=None;deadline=0;started=time.monotonic();busy=False
    def finish(error=None):
        if error:result['error']=error
        result['passed']=not error and all(c['passed'] for c in result['checks'])
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        timer.stop();page.undo_stack.setClean();page.close_page();page.close();QTimer.singleShot(400,app.quit)
    def tick():
        nonlocal pending,deadline,busy
        if busy:return
        busy=True
        try:
            if time.monotonic()-started>120:raise TimeoutError('Window acceptance timeout')
            if callable(pending):
                if not pending():return
            elif time.monotonic()<deadline:return
            value=next(sequence)
            pending=value if callable(value) else None
            deadline=time.monotonic()+(float(value) if not callable(value) else 0)
        except StopIteration:finish()
        except Exception:finish(traceback.format_exc())
        finally:busy=False
    timer=QTimer();timer.setInterval(40);timer.timeout.connect(tick);timer.start();app.exec()
    result['gui_shutdown']=True
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1


def render_outputs(output):
    from PySide6.QtWidgets import QApplication
    from ..caption_style.style_recipe import StyleRecipe
    from ..rendering.ass_compiler import compile_ass
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..exports.studio_render import RenderJob,RenderSettings
    from ..projects.studio_project import save_project
    from ..caption_design.visual_design_graph import graph_from_style_recipe
    import copy
    app=QApplication.instance() or QApplication([])
    p=make_project(output/'source.mp4',duration=1500)
    for i in (1,2,3,5):
        style=copy.deepcopy(p.styles[0]);style.id='advanced'+str(i);p.styles.append(style);p.cues[i].style_id=style.id
        recipe=StyleRecipe(name='渐变字效',engine='remotion',colors={'fill':{'type':'linear-gradient','angle':0,
            'stops':[{'position':0,'color':'#FFB9DDF6'},{'position':1,'color':'#FFF2C4CD'}]}})
        if i in (2,5):recipe.visual_graph=graph_from_style_recipe(recipe).to_dict()
        p.style_recipes[style.id]=recipe.to_dict()
    save_project(p,output/'render-project.2byteproj')
    ass=output/'render.ass';ass.write_text(compile_ass(p),encoding='utf-8-sig')
    ffmpeg=Path(__file__).resolve().parents[2]/'tools/ffmpeg/bin/ffmpeg.exe'
    settings=RenderSettings(encoder='libx264',width=960,height=540,fps=30,audio_codec='none')
    for name,start,duration in [('mixed',0,9),('excerpt',1.85,.9)]:
        job=RenderJob(str(output/'source.mp4'),str(ass),str(output/(name+'.mp4')),settings=settings,
                      start_seconds=start,duration_seconds=duration)
        print(AdvancedRendererBackend().render(p,ffmpeg,job),flush=True)
    return 0
