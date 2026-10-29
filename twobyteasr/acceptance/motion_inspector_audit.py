"""Isolated real-window and export checks for the motion tool page."""
from pathlib import Path
import copy


def make_project(media, duration=6000):
    from .letter_motion_audit import make_project as make_six
    from ..caption_style.motion_application import motion_command
    project = make_six(media, duration=duration)
    project.cues = project.cues[:4]
    for cue in project.cues:
        cue.effect_id = 'none'
    # A deliberate gap makes false uniform karaoke visibly wrong.
    motion_command(project, [c.id for c in project.cues], words={'type':'karaoke_wipe'}).redo()
    project.cues[-1].evidence_refs = []
    project.asr_evidence.pop(project.cues[-1].id, None)
    return project


def run_window(output, theme='grape', *, embedded=False):
    import time, json, traceback
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from ..studio.studio_ui import SubtitleStudioPage
    from ..design.theme_manager import apply_application_theme
    from ..projects.studio_project import save_project, load_project
    from ..caption_style.word_animation import build_word_animation
    from .blank_project_audit import _capture
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, theme)
    page = SubtitleStudioPage(); page.resize(1480, 940); page.show()
    project = make_project(output/'source.mp4')
    for cue in project.cues: cue.effect_id = 'none'
    source = save_project(project, output/'input.2byteproj')
    result = {'checks': [], 'passed': False}
    def check(name, condition): result['checks'].append({'name':name, 'passed':bool(condition)})
    def steps():
        page.open_project(source, skip_dirty_guard=True)
        yield lambda: page.project is not None and page._readiness.ready and not page._readiness.active
        yield .5
        page.video.set_paused(True); page.select_cue('0')
        page.context_drawer.setCurrentIndex(page.motion_tab_index)
        inspector = page.motion_inspector
        yield .4
        check('dedicated motion page', page.motion_sample.isVisible())
        check('motion absent from style', not page.context_drawer.widget(1).isAncestorOf(page.motion_sample))
        before = copy.deepcopy(page.project.to_dict())
        for stage_index, key, seconds, filename in [
                (0, 'soft_pop', .65, 'entry'), (1, 'soft_fade', .55, 'exit'),
                (2, 'loop_float', 1.4, 'loop'), (3, 'karaoke_wipe', None, 'words')]:
            inspector.tabs.setCurrentIndex(stage_index)
            stage = inspector.stages[stage_index]
            tile = inspector.cards[stage, key]
            QTest.mouseClick(tile, Qt.LeftButton)
            if seconds is not None: inspector.seconds.setValue(seconds)
            yield .4
            check(stage+' card selected', tile.isChecked())
            from ..caption_style.motion_inspector_ui import TILE_HEIGHT, PREVIEW_HEIGHT
            check(stage+' card not squeezed by app theme', tile.height() >= TILE_HEIGHT-2 and tile.preview.height() == PREVIEW_HEIGHT)
            check(stage+' real preview animating', tile.preview.timer.isActive() and tile.preview.snapshot is not None)
            if seconds is not None:
                check(stage+' duration editable', inspector.seconds.isVisible() and inspector.duration_control().value() == round(seconds*1000))
            _capture(page, output/(filename+'.png'))
        check('draft does not change project', page.project.to_dict() == before)
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('all'))
        QTest.mouseClick(page.motion_apply, Qt.LeftButton)
        yield .5
        effects = [page.project.effects[c.effect_id] for c in page.project.cues]
        check('all captions get blue white karaoke', all(e['word_highlight']['type']=='karaoke_wipe' for e in effects))
        check('independent entry exit and period', all(e['entry']['duration']==650 and e['exit']['duration']==550 and e['loop']['duration']==1400 for e in effects))
        check('appearance unchanged', page.project.to_dict()['styles'] == before['styles'])
        saved = [c.effect_id for c in page.project.cues]
        page.undo_stack.undo()
        check('one undo restores all', all(c.effect_id=='none' for c in page.project.cues))
        page.undo_stack.redo()
        check('one redo restores all', [c.effect_id for c in page.project.cues] == saved)
        loaded = load_project(save_project(page.project, output/'saved.2byteproj'))
        check('saved effects exact', all(loaded.effects[c.effect_id]==effects[i] for i,c in enumerate(loaded.cues)))
        check('missing timing stays unmeasured', not build_word_animation(page.project, page.project.cues[-1])['spans'])
        for index in (0, 1, 2, 3):
            inspector.tabs.setCurrentIndex(index)
            yield .2
            check('category survives reload '+str(index), inspector.selected(inspector.stages[index]) == ['soft_pop','soft_fade','loop_float','karaoke_wipe'][index])
        page._seek(.05); page.video.set_paused(False)
        yield 2.
        page.video.set_paused(True); _capture(page, output/'playback.png')
        from ..caption_style.letter_motion import PRESETS, sample
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('current'))
        inspector.tabs.setCurrentIndex(3)
        for mode in ('karaoke_wipe', *PRESETS):
            QTest.mouseClick(inspector.cards['words', mode], Qt.LeftButton)
            QTest.mouseClick(page.motion_apply, Qt.LeftButton)
            yield .1
            plan = build_word_animation(page.project, page.project.cues[0])
            check('applied continuous '+mode, plan['mode']==mode and len(plan['units'])==8)
            page._seek(.1); page.video.set_paused(False)
            yield .9
            page.video.set_paused(True)
            _capture(page, output/('continuous-'+mode+'.png'))
            check('preview precise clock '+mode, page.motion_sample.timer.interval()==16)
        # Curated catalog: category chips, per-glyph entry, direction, strength.
        from ..caption_style.motion_inspector_ui import CATEGORY, TILE_HEIGHT
        page.select_cue('1')
        yield .4
        for stage_index, stage, category, key in [(0, 'entry', 'char', 'char_rise'), (0, 'entry', 'cinema', 'push_in'),
                (1, 'exit', 'cinema', 'zoom_blur_out'), (2, 'loop', 'light', 'loop_shine'),
                (3, 'words', 'beat', 'word_current_pop')]:
            inspector.tabs.setCurrentIndex(stage_index)
            yield .2
            QTest.mouseClick(inspector.chips[stage][category], Qt.LeftButton)
            yield .3
            shown = [k for (s, k), tile in inspector.cards.items() if s == stage and tile.isVisible()]
            check(stage+' filter '+category, shown and all(CATEGORY[stage, k] == category for k in shown))
            check(stage+' stage bar names choice', bool(inspector.tabs.buttons[stage_index].value_text))
            QTest.mouseClick(inspector.cards[stage, key], Qt.LeftButton)
            yield .5
            check(stage+' picked '+key, inspector.selected(stage) == key and inspector.cards[stage, key].isChecked())
            check(stage+' card renders '+key, inspector.cards[stage, key].preview.pixmap() is not None
                  and not inspector.cards[stage, key].preview.pixmap().isNull())
            if key == 'push_in':
                check('direction offered', inspector.direction_buttons['left'].isVisible())
                QTest.mouseClick(inspector.direction_buttons['right'], Qt.LeftButton)
                QTest.mouseClick(inspector.strength_buttons['high'], Qt.LeftButton)
                yield .3
                check('direction chosen', inspector.direction('entry') == 'right')
                _capture(page, output/'curated-entry-direction.png')
            _capture(page, output/f'curated-{stage}-{key}.png')
            QTest.mouseClick(inspector.chips[stage]['all'], Qt.LeftButton)
        page.motion_scope.setCurrentIndex(page.motion_scope.findData('current'))
        QTest.mouseClick(page.motion_apply, Qt.LeftButton)
        yield .5
        effect = page.project.effects[page.project.cues[1].effect_id]
        check('curated applied', (effect['entry']['type'], effect['entry'].get('direction'), effect['entry']['strength'],
               effect['exit']['type'], effect['loop']['type'], effect['word_highlight']['type'])
              == ('push_in', 'right', 'high', 'zoom_blur_out', 'loop_shine', 'word_current_pop'))
        check('curated plan has units', bool(build_word_animation(page.project, page.project.cues[1]).get('units')))
        page._seek(1*6+.05); page.video.set_paused(False)
        yield .35
        page.video.set_paused(True); _capture(page, output/'curated-playback.png')
        reloaded = load_project(save_project(page.project, output/'curated.2byteproj'))
        check('curated saved exact', reloaded.effects[reloaded.cues[1].effect_id] == effect)
        applied_id = page.project.cues[1].effect_id
        page.undo_stack.undo()
        yield .3
        check('curated undo', page.project.cues[1].effect_id != applied_id)
        page.undo_stack.redo()
        page.resize(1100, 740)
        yield .4
        check('narrow cards contained', inspector.stack.width() >= inspector.stack.currentWidget().minimumSizeHint().width())
        check('short panel shows a full card row', inspector.cards_scroll.viewport().height() >= TILE_HEIGHT)
        check('motion tab readable', page.context_drawer.tabText(page.motion_tab_index) == '动效')
        _capture(page, output/'small-window.png')
        page.context_drawer.setCurrentIndex(1)
        yield .3
        check('style hides motion editor', not page.motion_sample.isVisible())
        _capture(page, output/'style-only.png')

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
            if time.monotonic()-started>170:raise TimeoutError('Window acceptance timeout')
            if callable(pending):
                if not pending():return
            elif time.monotonic()<deadline:return
            value=next(sequence)
            pending=value if callable(value) else None
            deadline=time.monotonic()+(float(value) if not callable(value) else 0)
        except StopIteration:finish()
        except Exception:finish(traceback.format_exc())
        finally:busy=False
    timer=QTimer(page);timer.setInterval(40);timer.timeout.connect(tick);timer.start()
    if embedded:
        # Keep the isolated test page alive inside the normal EXE event loop.
        app._motion_acceptance_page = page
        def shutdown():
            result['gui_shutdown'] = True
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        app.aboutToQuit.connect(shutdown)
        return
    app.exec()
    result['gui_shutdown']=True
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1


def render_outputs(output):
    import subprocess
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QColor, QPainter
    from ..caption_style.style_recipe import StyleRecipe
    from ..caption_style.motion_application import motion_command
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.caption_scene import SceneRasterizer
    from ..rendering.ass_compiler import compile_ass
    from ..rendering.advanced_renderer import AdvancedRendererBackend
    from ..exports.studio_render import RenderJob, RenderSettings
    from ..projects.studio_project import save_project
    app = QApplication.instance() or QApplication([])
    ffmpeg = Path(__file__).resolve().parents[2]/'tools/ffmpeg/bin/ffmpeg.exe'
    media = output/'source.mp4'
    if not media.exists():
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'color=c=0x203344:s=960x540:r=30:d=24', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(media)], check=True)
    p = make_project(media)
    motion_command(p, ['1'], motion={'entry':{'type':'soft_fade','duration':650},
        'exit':{'type':'soft_fade','duration':550}, 'loop':{'type':'loop_float','duration':1400}}).redo()
    motion_command(p, ['2'], motion={'entry':{'type':'soft_pop','duration':450},
        'exit':{'type':'scale','duration':500,'scale_from':65}, 'loop':{'type':'loop_breathe','duration':1200}},
        words={'type':'word_reveal'}).redo()
    native_ass = output/'native.ass'; native_ass.write_text(compile_ass(p), encoding='utf-8-sig')
    subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-i', str(media.resolve()),
        '-vf', 'ass=native.ass', '-t', '24', '-an', '-c:v', 'libx264', '-crf', '19',
        '-pix_fmt', 'yuv420p', 'native.mp4'], cwd=output, check=True)
    raster = SceneRasterizer()
    for cue_id in ('0', '1', '2', '3'):
        snap = build_visual_cue_snapshot(p, cue_id)
        for t in (0, 300, 650, 1500, 2800, 4200, 5600):
            layer = raster.native_frame(SimpleNamespace(snapshot=snap, snapshot_hash=snap.stable_hash()), t, 960, 540)
            image = QImage(960, 540, QImage.Format_ARGB32_Premultiplied); image.fill(QColor('#203344'))
            painter = QPainter(image); painter.drawImage(0, 0, layer); painter.end()
            image.save(str(output/f'live-{cue_id}-{t}.png'))
    style = copy.deepcopy(p.styles[0]); style.id = 'advanced'; p.styles.append(style); p.cues[1].style_id = style.id
    p.style_recipes[style.id] = StyleRecipe(name='渐变外观下的卡拉 OK', engine='remotion', colors={
        'fill':{'type':'linear-gradient', 'angle':0, 'stops':[{'position':0,'color':'#FFFF3355'},
                                                         {'position':1,'color':'#FFFFD166'}]}}).to_dict()
    save_project(p, output/'render-project.2byteproj')
    ass = output/'mixed.ass'; ass.write_text(compile_ass(p), encoding='utf-8-sig')
    settings = RenderSettings(encoder='libx264', width=960, height=540, fps=30, audio_codec='none')
    for name, start, duration in [('mixed',0,12), ('excerpt',7.2,1.2)]:
        job = RenderJob(str(media), str(ass), str(output/(name+'.mp4')), settings=settings,
                        start_seconds=start, duration_seconds=duration)
        print(AdvancedRendererBackend().render(p, ffmpeg, job), flush=True)
    return 0
