"""Real Studio style picks, live bilingual rasters and controlled playback."""
import copy,json,os,platform,statistics,time,traceback
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QPoint,QTimer,Qt,QSignalBlocker
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..caption_style.style_presets import StylePresetStore
    from ..caption_style.scoped_preset import preset_command
    from ..caption_style.scoped_style import style_patch_command
    from ..caption_style.motion_application import motion_command
    from ..caption_style.bilingual_layout import project_display_cues,ink_block
    from ..caption_style.resolved_caption_style import resolve_caption_style
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.caption_scene import SceneRasterizer,CaptionScene
    from ..projects.studio_project import save_project,load_project
    import psutil
    try:page=window.studio_page
    except RuntimeError:
        QTimer.singleShot(100,lambda:start(window,output));return
    output=Path(output);clock=time.perf_counter
    baseline=bool(os.environ.get('STYLE_MOTION_BASELINE'))
    result=dict(passed=False,baseline=baseline,checks=[],performance=[],states=[],pid=os.getpid())
    active={'phase':''};frames=[];posts=[];gaps=[];last=[clock()]
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));receipt()
    def wait(predicate,seconds=90):
        until=clock()+seconds
        while clock()<until and not predicate():QTest.qWait(20)
        if not predicate():raise RuntimeError('Wait timed out')
    def pause():
        if not page.video._paused:page._toggle_playback()
        QTest.qWait(150)
    def shot(name):
        QTest.qWait(500);_capture(window,output/(name+'.png'))
        scene=getattr(page,'_caption_scene',None)
        if scene is not None and scene.published is not None:scene.published.image.save(str(output/(name+'-overlay.png')))
        page.style_preset.parentWidget().grab().save(str(output/(name+'-preset-row.png')))
    def ready():
        wait(lambda:page.project is not None and page._readiness.ready and not page._readiness.active,150)
        wait(lambda:not getattr(page,'_style_application_busy',False),120);QTest.qWait(300)
    def choose(key):
        combo=page.style_preset;index=combo.findData(key)
        if index<0:raise RuntimeError('Preset absent: '+key)
        block=QSignalBlocker(combo);combo.setCurrentIndex(index);del block
        combo.showPopup();QTest.qWait(80);item=combo.model().index(index,0)
        combo.view().scrollTo(item);QTest.qWait(50)
        QTest.mouseClick(combo.view().viewport(),Qt.MouseButton.LeftButton,pos=combo.view().visualRect(item).center())
        ready()
    def state(name,cue):
        p=page.project;rows=[]
        for shown in project_display_cues(p,[cue]):
            r=resolve_caption_style(p.styles,p.speakers,shown,p.style_recipes,1920,1080);s=r.style
            h,_,o,shadow=ink_block(r);f=(1.,.5,0.)[(s.alignment-1)//3]
            y=s.position_y if s.position_y is not None else 1080-s.margin_v
            snap=build_visual_cue_snapshot(p,shown.id,width=1280,height=720,resolved_cue=shown)
            rows.append(dict(id=shown.id,font_size=s.font_size,fill=s.primary_color,recipe_fill=r.recipe.colors.get('fill'),
                strokes=snap.strokes,shadow=snap.shadow,render_fill=snap.fill,position=[s.position_x,y],
                bounds=[y-f*h-o,y+(1-f)*h+o+shadow],lines=r.line_count))
        panel=dict(layer=page.style_layer.currentData(),font_size=page.style_font_size.value(),
            fill=page.style_fill_color.text(),fill_spec=page._fill_spec.to_dict(),outline=page.style_outline_color.text(),
            outline_width=page.style_outline_width.value(),summary=page.style_scope_summary.text())
        overlap=len(rows)>1 and min(r['bounds'][1]for r in rows)>max(r['bounds'][0]for r in rows)
        result['states'].append(dict(step=name,rows=rows,panel=panel,overlap=overlap));receipt();return rows
    original_frame=SceneRasterizer.frame;original_accept=CaptionScene.accept
    def frame(self,*args,**kwargs):
        t=clock();value=original_frame(self,*args,**kwargs)
        if active['phase']:frames.append(dict(phase=active['phase'],ms=(clock()-t)*1000,cues=len(args[0]),entries=len(self.rasters)))
        return value
    def accept(self,token,pixels,trace):
        previous=self.published;original_accept(self,token,pixels,trace)
        if active['phase'] and self.published is pixels and self.published is not previous:
            posts.append(dict(phase=active['phase'],wall=clock(),media_ms=trace.get('sample_ms'),cues=list(token[4]),
                duration_ms=trace.get('duration_ms'),drawn=[x['cue_id']for x in trace.get('cue_pixels',[])]))
    SceneRasterizer.frame=frame;CaptionScene.accept=accept
    pulse=QTimer(window);pulse.setInterval(16);pulse.setTimerType(Qt.TimerType.PreciseTimer)
    def tick():
        now=clock()
        if active['phase']:gaps.append((active['phase'],(now-last[0])*1000))
        last[0]=now
    pulse.timeout.connect(tick)
    def summary(values):
        values=sorted(values)
        return dict(count=len(values),p50=statistics.median(values) if values else None,
                    p95=values[min(len(values)-1,int(len(values)*.95))] if values else None,
                    maximum=max(values,default=0),over_33ms=sum(x>33.333 for x in values),over_100ms=sum(x>100 for x in values))
    def video_stats():
        result={}
        for key in ('container-fps','estimated-vf-fps','display-fps','frame-drop-count',
                    'decoder-frame-drop-count','mistimed-frame-count','hwdec-current'):
            try:result[key]=page.video.controller.get_property(key,None)
            except Exception as exc:result[key]=dict(unavailable=type(exc).__name__)
        return result
    def execute():
        try:
            ready()
            for font in (Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts').glob('*'):
                if font.suffix in {'.ttf','.otf'}:QFontDatabase.addApplicationFont(str(font))
            from ..caption_style.font_metadata import resolve_local_face
            result['font_face']=str(resolve_local_face('猫啃什锦黑')[0])
            # Startup already applies the user's chosen density and scale.
            pause();page.volume_slider.setValue(0);p=page.project
            result['project']=dict(cues=len(p.cues),translations=len(p.generation_metadata.get('translations',{})),media=p.media.path)
            cue=next(c for c in p.cues if c.id=='137');speaker=[c.id for c in p.cues if c.speaker_id==cue.speaker_id]
            result['project']['speaker_cues']=len(speaker)
            result['device']=dict(platform=platform.platform(),processor=platform.processor(),logical_cpus=psutil.cpu_count(),
                window=[window.width(),window.height()],dpr=window.devicePixelRatioF(),video=video_stats(),rate=1.)
            page.select_cue(cue.id);page._seek((cue.start_ms+1200)/1000);QTest.qWait(1200)
            scope=page.style_scope.findData('current');page.style_scope.setCurrentIndex(scope)
            page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
            page.style_apply_geometry.setChecked(False);ready()
            state('input',cue);shot('01-before-preset')
            if os.environ.get('STYLE_MOTION_RECOVER_LEGACY')=='1':
                from PySide6.QtWidgets import QToolButton
                faces=copy.deepcopy([(c.text,c.style_id,c.effect_id,c.appearance_override)for c in p.cues])
                action=next(a for b in page.findChildren(QToolButton) if b.menu() is not None
                            for a in b.menu().actions() if a.text()=='恢复双语自动排列')
                action.trigger();ready();state('restored-automatic-layout',cue);shot('01b-restored-automatic-layout')
                check('legacy_saved_pair_reflows',not result['states'][-1]['overlap'])
                check('legacy_recovery_preserves_all_faces_and_text',faces==[(c.text,c.style_id,c.effect_id,c.appearance_override)for c in p.cues])
            choose('user-ca40c9cf62d9');before=state('preset',cue);shot('02-preset')
            page.style_font_size.lineEdit().setFocus();page.style_font_size.lineEdit().selectAll()
            QTest.keyClicks(page.style_font_size.lineEdit(),'61');QTest.keyClick(page.style_font_size.lineEdit(),Qt.Key.Key_Tab)
            QTest.qWait(400);ready();after=state('font-61',cue);shot('03-font-61')
            check('automatic_pair_no_overlap',not result['states'][-1]['overlap'])
            check('font_edit_preserves_fill_stroke_shadow',[(x['render_fill'],x['strokes'],x['shadow'])for x in before]==
                [(x['render_fill'],x['strokes'],x['shadow'])for x in after])
            if not baseline:check('modified_label_names_the_field','字号' in page.style_preset.toolTip(),page.style_preset.toolTip())
            check('panel_fill_matches_render',page._fill_spec.to_dict()==after[0]['render_fill'],
                  dict(panel=page._fill_spec.to_dict(),render=after[0]['render_fill']))
            check('language_picker_next_to_preset',page.style_layer.parentWidget() is page.style_preset.parentWidget(),
                  dict(preset=page.style_preset.geometry().getRect(),layer=page.style_layer.geometry().getRect()))
            check('independent_library_removed',not hasattr(page,'style_library_button'))
            saved=save_project(p,output/'saved.2byteproj');restored=load_project(saved)
            check('saved_styles_and_geometry_roundtrip',[(c.style_id,c.appearance_override,c.transform)for c in restored.cues]==
                [(c.style_id,c.appearance_override,c.transform)for c in p.cues])
            if os.environ.get('STYLE_MOTION_UI_ONLY')!='1':
                loop={'entry':{'type':'fade','duration':180},'exit':{'type':'fade','duration':140},
                      'loop':{'type':'loop_breathe','duration':1200,'strength':'medium'}}
                store=StylePresetStore();proc=psutil.Process();pulse.start()
                for name,styled,animated,whole in [('A',False,False,True),('B',True,False,True),
                    ('C',False,True,True),('D',True,True,True),('D-current',True,True,False),('D-speaker',True,True,True)]:
                    pause();page.style_controller._application=None
                    for ids,motion in [(speaker,{'entry':{'type':'none'},'exit':{'type':'none'}}),
                        (speaker if whole else [cue.id],loop if animated else {'entry':{'type':'none'},'exit':{'type':'none'}})]:
                        cmd=motion_command(p,ids,motion=motion,language='linked')
                        if cmd:page.undo_stack.push(cmd)
                    cmd=preset_command(p,speaker,store.load_patch('user-ca40c9cf62d9' if styled else 'default'),
                        layer='group',apply_geometry=False,changed=page._changed)
                    if cmd:page.undo_stack.push(cmd)
                    start_ms=cue.start_ms+(700 if name.startswith('D-') else -3000)
                    span=4.5 if name.startswith('D-') else float(os.environ.get('STYLE_MOTION_SECONDS','18'))
                    page._seek(start_ms/1000);QTest.qWait(1800);page._set_speed(1.)
                    cpu0=proc.cpu_times();rss0=proc.memory_info().rss;stats0=video_stats()
                    active['phase']=name;last[0]=clock();beg=clock();page._toggle_playback()
                    QTest.qWait(round(span*1000));pause();active['phase']=''
                    cpu1=proc.cpu_times();stats1=video_stats();rss1=proc.memory_info().rss
                    stamps=[r['wall']for r in posts if r['phase']==name]
                    result['performance'].append(dict(scenario=name,wall_seconds=clock()-beg,
                        render_ms=summary([r['ms']for r in frames if r['phase']==name]),
                        gui_interval_ms=summary([v for phase,v in gaps if phase==name]),
                        caption_post_interval_ms=summary([(b-a)*1000 for a,b in zip(stamps,stamps[1:])]),
                        frame_count=len(stamps),maximum_active_cues=max((r['cues']for r in frames if r['phase']==name),default=0),
                        maximum_raster_entries=max((r['entries']for r in frames if r['phase']==name),default=0),
                        rss_mb=[rss0/1048576,rss1/1048576],cpu_seconds=cpu1.user+cpu1.system-cpu0.user-cpu0.system,
                        video_before=stats0,video_after=stats1));receipt()
                pulse.stop()
                (output/'frames.json').write_text(json.dumps(frames),'utf8')
                (output/'posts.json').write_text(json.dumps(posts),'utf8')
                check('visible_scene_never_visits_hidden_speaker_cues',all(r['cues']<=4 for r in frames))
                scene=page._caption_scene;seen=len(posts);QTest.qWait(800)
                check('pause_stops_caption_posts',len(posts)==seen)
                page._seek((cue.start_ms+2000)/1000);QTest.qWait(800)
                check('seek_preserves_bilingual_scene',scene.token is not None and cue.id in scene.token[4])
            check('project_has_full_counts',len(p.cues)==1392 and len(p.generation_metadata.get('translations',{}))==1388)
            if os.environ.get('STYLE_MOTION_UI_ONLY')=='1':
                from PySide6.QtTest import QSignalSpy
                from ..studio.presentation_scope import capture_scope
                from ..caption_style.scoped_style import effective_layer_style
                presentations=copy.deepcopy([(c.style_id,c.appearance_override,c.transform)for c in p.cues])
                undo_index=page.undo_stack.index()
                button=page.style_scope._buttons[page.style_scope.findData('speaker')]
                QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=QPoint(button.width()-3,button.height()//2));ready()
                resolved_scope=capture_scope(page)
                check('actual_speaker_scope_is_278',len(resolved_scope.cue_ids)==278 and set(resolved_scope.cue_ids)==set(speaker))
                check('speaker_batch_one_undo',page.undo_stack.index()==undo_index+1)
                check('speaker_batch_font_and_layer',all(effective_layer_style(p,c,l).font_size==61
                    for c in p.cues if c.id in speaker for l in ('original','translation')))
                page.undo_stack.undo();QTest.qWait(200)
                check('speaker_undo_restores_all_presentations',presentations==[(c.style_id,c.appearance_override,c.transform)for c in p.cues])
                page.style_controller.cancel_pending_application()
                page.style_scope.setCurrentIndex(page.style_scope.findData('current'));page._load_style_inspector()
                before_layers=copy.deepcopy([(c.appearance_override,c.transform)for c in p.cues])
                for pixels in (13,18):
                    page.upper_splitter.setSizes([320,1100,330])
                    for control in (page.style_layer,page.style_preset):control.setStyleSheet(f'font-size:{pixels}px;')
                    QTest.qWait(200)
                    check(f'preset_main_width_font_{pixels}',page.style_preset.width()>page.style_layer.width()*1.5,
                        dict(preset=page.style_preset.geometry().getRect(),layer=page.style_layer.geometry().getRect()))
                    for language in ('original','translation','group'):
                        combo=page.style_layer;spy=QSignalSpy(combo.activated)
                        QTest.mouseClick(combo,Qt.MouseButton.LeftButton,pos=QPoint(4,combo.height()//2));QTest.qWait(80)
                        check(f'full_picker_hit_{pixels}_{language}',combo.view().isVisible())
                        index=combo.findData(language);item=combo.model().index(index,0)
                        # QTest viewport releases do not move the native
                        # pointer on a private desktop. Exercise the whole
                        # control hit and then the real popup keyboard route.
                        QTest.keyClick(combo.view(),Qt.Key.Key_Home)
                        for _ in range(index):QTest.keyClick(combo.view(),Qt.Key.Key_Down)
                        QTest.keyClick(combo.view(),Qt.Key.Key_Return)
                        QTest.qWait(100)
                        check(f'picker_bound_once_{pixels}_{language}',spy.count()==1 and combo.currentData()==language,
                            dict(method='popup-keyboard-after-body-click',activated=spy.count(),current=combo.currentData(),target=language,
                                 rect=combo.view().visualRect(item).getRect()))
                    page.context_panel.grab().save(str(output/f'compact-font-{pixels}.png'))
                check('layer_picks_do_not_write_style',before_layers==[(c.appearance_override,c.transform)for c in p.cues])
                from ..caption_style.motion_controls_ui import MotionSample
                page.context_drawer.setCurrentIndex(page.motion_tab_index);QTest.qWait(400)
                page.context_drawer.setCurrentIndex(1);QTest.qWait(300)
                samples=page.findChildren(MotionSample)
                check('hidden_motion_samples_stop',all(not sample.timer.isActive()for sample in samples if not sample.isVisible()))
                scene=page._caption_scene
                page._close_project_session('style-motion-lifecycle');QTest.qWait(800)
                check('close_retires_caption_scene',scene.closed and page.project is None and not scene.thread.is_alive())
            if baseline:result['passed']=True
            else:result['passed']=all(c['passed']for c in result['checks'])
        except BaseException:result['error']=traceback.format_exc()
        finally:
            pulse.stop();SceneRasterizer.frame=original_frame;CaptionScene.accept=original_accept;receipt()
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.undo_stack.setClean();window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(250,execute)
