"""Synthetic real-window and production-render acceptance for word captions."""
from pathlib import Path
import json
import time
import traceback


def make_project(media):
    from .studio_project import SubtitleProject, StudioCue, StudioMedia, SubtitleStyle, StudioSpeaker
    text = ['跟着声音，逐词出现', 'Words follow the voice.', '高亮正在说的字词', '没有时间也保留完整字幕', '渐变字幕也能逐词出现']
    pieces = [['跟','着','声','音','逐','词','出','现'], ['Words', 'follow', 'the', 'voice'],
              ['高','亮','正','在','说','的','字','词'], [], ['渐','变','字','幕','也','能','逐','词','出','现']]
    cues = [StudioCue(str(i), i*3000+200, i*3000+2800, t, speaker_id='S01' if i%2==0 else 'S02', evidence_refs=[str(i)]) for i,t in enumerate(text)]
    evidence = {}
    for cue, units in zip(cues,pieces):
        # Deliberately nonuniform intervals with real pauses in a synthetic fixture.
        intervals = [100, 270, 620, 900, 1230, 1570, 1880, 2170, 2300, 2420]
        if len(units)==4:
            intervals = [120, 750, 1250, 1860]
        evidence[cue.id] = {'words':[dict(text=t, start_ms=cue.start_ms+intervals[k],
                                        end_ms=cue.start_ms+min(2550,intervals[k]+140)) for k,t in enumerate(units)]}
    return SubtitleProject(media=StudioMedia(str(media), duration_ms=15000, width=640, height=360),
        styles=[SubtitleStyle('default','Default',font_family='Microsoft YaHei',font_size=90,shadow=0)],
        speakers=[StudioSpeaker('S01','旁白'),StudioSpeaker('S02','解说')], cues=cues, asr_evidence=evidence)


def run_window(output, theme='grape'):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from .studio_ui import SubtitleStudioPage
    from .theme_manager import apply_application_theme
    from .studio_project import save_project, load_project
    from .word_animation import build_word_animation
    from .studio_motion_browser import MotionBrowserDialog
    from .blank_project_audit import _capture
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, theme)
    page = SubtitleStudioPage()
    page.resize(1500, 900)
    page.show()
    project_path = save_project(make_project(output/'synthetic.mp4'), output/'input.2byteproj')
    result = {'checks':[], 'passed':False}
    def check(name, value):
        result['checks'].append({'name':name, 'passed':bool(value)})
    def capture(name):
        _capture(page, output/(name+'.png'))
        scene = getattr(page, '_caption_scene', None)
        if scene and scene.published:
            scene.published.image.save(str(output/(name+'-overlay.png')))
    def steps():
        page.open_project(project_path, skip_dirty_guard=True)
        yield lambda: page.project is not None and page._readiness.ready and not page._readiness.active
        yield 1.0
        page.video.set_paused(True)
        page.context_drawer.setCurrentIndex(1)
        page.select_cue('0')
        page.motion_jump_button.click()
        yield .6
        capture('01-motion-panel')
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('all'))
        page.motion_word_mode.setCurrentIndex(page.motion_word_mode.findData('word_reveal'))
        page.effect_preset.setCurrentIndex(page.effect_preset.findData('soft_pop'))
        yield .6
        check('draft leaves captions untouched',all(c.effect_id=='none' for c in page.project.cues))
        QTest.mouseClick(page.motion_apply,Qt.LeftButton)
        yield .6
        check('all five captions get one undoable effect',len({c.effect_id for c in page.project.cues})==1 and page.project.cues[0].effect_id!='none')
        check('missing timing retains full line',not build_word_animation(page.project,page.project.cues[3])['spans'])
        for local in (50, 800, 2350):
            page._seek((200+local)/1000)
            yield 1.0
            capture('02-reveal-'+str(local))
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('current'))
        page.motion_word_mode.setCurrentIndex(page.motion_word_mode.findData('karaoke_highlight'))
        page.motion_apply.click()
        yield .5
        for local in (50, 800, 2350):
            page._seek((200+local)/1000)
            yield .8
            capture('03-karaoke-'+str(local))
        before = [c.effect_id for c in page.project.cues]
        page.undo_stack.undo()
        check('undo restores preceding word mode',build_word_animation(page.project,page.project.cues[0])['mode']=='word_reveal')
        page.undo_stack.redo()
        check('redo restores exact effect ids',[c.effect_id for c in page.project.cues]==before)
        def library():
            dialog=app.activeModalWidget()
            check('real button opens motion library',isinstance(dialog,MotionBrowserDialog))
            if isinstance(dialog,MotionBrowserDialog):
                _capture(dialog,output/'04-library.png')
                dialog._select('word_current')
                check('library choice is not applied before action',[c.effect_id for c in page.project.cues]==before)
                dialog.apply_button.click()
            elif dialog:
                dialog.reject()
        QTimer.singleShot(800,library)
        page.motion_library_button.click()
        yield .8
        check('library applied only current caption',build_word_animation(page.project,page.project.cues[0])['mode']=='word_current' and page.project.cues[1].effect_id==before[1])
        saved=save_project(page.project,output/'saved.2byteproj')
        restored=load_project(saved)
        check('save reopen retains measured word mode',build_word_animation(restored,restored.cues[0])['mode']=='word_current')
        page.resize(1100,720)
        page.motion_jump_button.click()
        yield .8
        capture('05-small-window')
        check('motion controls fit panel width',page.motion_apply.width()>100 and page.motion_scope.width()>100)
        page._replay_motion()
        yield 1.0
        capture('06-playing')
        check('real playback advances',not page.video._paused)
        page.video.set_paused(True)
        result['passed']=all(c['passed'] for c in result['checks'])
    iterator=steps()
    state={'wait':None,'until':0.,'deadline':0.,'busy':False}
    timer=QTimer(page);timer.setInterval(50)
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    def finish():
        timer.stop();save()
        page.undo_stack.setClean()
        page.close_page();page.close()
        QTimer.singleShot(400,app.quit)
    def tick():
        if state['busy']:return
        state['busy']=True
        try:
            if state['wait']:
                if state['wait']():state['wait']=None
                elif time.monotonic()>state['deadline']:raise TimeoutError('Window did not become ready')
                else:return
            if time.monotonic()<state['until']:return
            value=next(iterator)
            if callable(value):state.update(wait=value,deadline=time.monotonic()+90)
            else:state['until']=time.monotonic()+float(value or 0)
        except StopIteration:finish()
        except Exception:
            result['error']=traceback.format_exc();capture('failure');finish()
        finally:state['busy']=False
    timer.timeout.connect(tick);timer.start()
    app.exec()
    result['gui_shutdown']=True;save()
    return 0 if result['passed'] else 1


def render_outputs(output):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from .motion_application import motion_command
    from .style_recipe import StyleRecipe
    from .effect_dsl import builtin_effects
    from .ass_compiler import compile_ass
    from .advanced_renderer import AdvancedRendererBackend
    from .studio_render import RenderJob,RenderSettings
    from .studio_project import save_project
    project=make_project(output/'synthetic.mp4')
    for cue,mode in zip(project.cues,['word_reveal','karaoke_highlight','word_current','word_reveal','word_reveal']):
        motion_command(project,[cue.id],words={'type':mode,'color':'#FFD166'}).redo()
    for index in (2,4):
        import copy
        style=copy.deepcopy(project.styles[0]);style.id='gradient'+str(index)
        project.styles.append(style);project.cues[index].style_id=style.id
        project.style_recipes[style.id]=StyleRecipe(name='Gradient',engine='remotion',
            colors={'fill':{'type':'linear-gradient','angle':0,'stops':[{'position':0,'color':'#FF7DD3FC'},{'position':1,'color':'#FFFDA4AF'}]}}).to_dict()
    motion_command(project,['2'],motion=builtin_effects()['float_up']).redo()
    save_project(project,output/'export-project.2byteproj')
    ass=output/'captions.ass';ass.write_text(compile_ass(project),'utf-8-sig')
    ffmpeg=Path(__file__).resolve().parents[2]/'tools/ffmpeg/bin/ffmpeg.exe'
    job=RenderJob(str(output/'synthetic.mp4'),str(ass),str(output/'word-motion.mp4'),
        settings=RenderSettings(encoder='libx264',width=640,height=360,fps=30,audio_codec='none'))
    from dataclasses import replace
    for name, start, duration in [('word-motion',None,None), ('excerpt-mixed',1.0,7.5), ('excerpt-gradient',13.5,1.2)]:
        result=AdvancedRendererBackend().render(project,ffmpeg,
            replace(job,output_path=str(output/(name+'.mp4')),start_seconds=start,duration_seconds=duration))
        print(result,flush=True)
    return 0
