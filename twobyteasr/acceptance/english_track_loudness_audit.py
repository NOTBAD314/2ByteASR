"""Real-window mouse/undo/persistence and shared-bus export evidence."""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500,lambda:run(window,output))


def run(window,output):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from unittest.mock import patch
    from types import SimpleNamespace
    from ..timeline.studio_track_gain import track_gain_db,show_track_gain
    from ..studio.timeline_track_gain import geometry
    from ..studio.project_loudness_panel import show_project_loudness
    from ..playback.project_loudness import baseline_identity,project_gain_db,match_gain
    from ..projects.studio_project import save_project,load_project
    app=QApplication.instance();checks=[];error=None;metrics={};completed=False
    import faulthandler
    fault_file=(output/'native-fault.txt').open('w',encoding='utf8')
    faulthandler.enable(file=fault_file,all_threads=True)
    def persist():
        (output/'result.json').write_text(json.dumps(dict(passed=completed and error is None and bool(checks) and all(c['passed'] for c in checks),checks=checks,error=error,metrics=metrics),ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,passed,detail=None):
        checks.append(dict(name=name,passed=bool(passed),detail=detail));persist()
        if not passed:raise AssertionError(name+': '+str(detail))
    def settle(seconds=.1):
        until=time.monotonic()+seconds
        while time.monotonic()<until:app.processEvents();time.sleep(.004)
    def wait(predicate,timeout=40):
        until=time.monotonic()+timeout
        while not predicate() and time.monotonic()<until:settle(.02)
        if not predicate():raise TimeoutError(str(predicate))
    def drag(widget,a,b):
        QTest.mousePress(widget,Qt.LeftButton,Qt.NoModifier,a)
        for fraction in (.25,.5,.75,1.):
            QTest.mouseMove(widget,a+(b-a)*fraction);settle(.04)
        QTest.mouseRelease(widget,Qt.LeftButton,Qt.NoModifier,b);settle(.15)
    page=None
    try:
        import os
        from ..design.theme_manager import apply_theme,save_theme_key
        theme=os.environ.get('TWOBYTEASR_VOLUME_THEME','sand')
        save_theme_key(theme);apply_theme(theme,app)
        window.resize(1560,980);window.open_studio_project(str(output/'fixture.2byteproj'))
        wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
        page=window.built_page('studio')
        wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
        wait(lambda:getattr(page.video,'_startup_state','')=='READY')
        page.video.set_paused(True);settle(.5)
        # Offline provider replay invokes the actual menu worker and writeback.
        calls=[]
        def complete(messages,**kwargs):
            payload=json.loads(messages[-1]['content']);calls.append(payload)
            return json.dumps({'results':[dict(cue_id=row['cue_id'],action='keep') for row in payload['cues']]})
        with patch('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete)),patch('twobyteasr.providers.llm_config.text_ai_key_missing',lambda *a,**k:False):
            page.select_cue('c132');page.run_sentence_refine(whole_project=True)
            wait(lambda:page._refine_task.ended is not None)
        project=page.project
        check('77-char source actually split',len(project.cues)>1,[(c.text,c.start_ms,c.end_ms) for c in project.cues])
        check('one targeted retry',len(calls)==2)
        check('source exact', ''.join(c.text for c in project.cues).replace('\n','')=="And uh but I just also say you what I'm going to do here does require studio.")
        page.timeline.grab().save(str(output/'01-english-timeline.png'))
        page.undo_stack.undo();check('split undo restores one source',len(project.cues)==1)
        page.undo_stack.redo();check('split redo',len(project.cues)>1)
        page._seek(2.);settle(.6)
        # Track popup: real editor scrub, horizontal slider and cancel/apply.
        count=page.undo_stack.count();show_track_gain(page,'A2');settle(.3)
        dialog=page._track_gain_dialog;spin=dialog.findChild(__import__('PySide6.QtWidgets',fromlist=['QDoubleSpinBox']).QDoubleSpinBox,'trackGainDb')
        QTest.mouseClick(dialog.listen,Qt.LeftButton)
        wait(lambda:not page.video._paused and any(s.meter.level()>0 for s in dialog.strips.values()),35)
        metrics['live_levels']={k:s.meter.level() for k,s in dialog.strips.items()}
        check('real decoder telemetry moves live strip meters',any(v>0 for v in metrics['live_levels'].values()),metrics['live_levels'])
        dialog.grab().save(str(output/'02a-live-meters.png'))
        QTest.mouseClick(dialog.listen,Qt.LeftButton);wait(lambda:page.video._paused)
        page._seek(2.);settle(.4)
        check('signed numeric text present','0.0' in spin.text() and spin.lineEdit().width()>70,(spin.text(),spin.lineEdit().width()))
        editor=spin.lineEdit();a=editor.rect().center();drag(editor,a,a+QPoint(48,0))
        check('number scrub previews positive gain',page._gain_preview_values.get('A2',0)>0,page._gain_preview_values)
        check('scrub does not commit',page.undo_stack.count()==count and track_gain_db(project,'A2')==0)
        # 2026-11-14: the window is a mixer; each track has a vertical fader.
        fader=dialog.strips['A2'].fader
        before=fader.value();y=round(fader.pixel_of(before))
        drag(fader,QPoint(fader.width()//2,y),QPoint(fader.width()//2,y+20))
        check('fader down lowers preview',fader.value()<before and page._gain_preview_values.get('A2')==fader.value()
              and page.undo_stack.count()==count,(before,fader.value(),page._gain_preview_values))
        dialog.grab().save(str(output/'02-track-volume.png'))
        dialog.reject();wait(lambda:getattr(page,'_track_gain_dialog',None) is None)
        check('cancel restores track',track_gain_db(project,'A2')==0 and not page._gain_preview_values)
        # Multiple real strips share one preview bus and one history command.
        show_track_gain(page,'A2');settle(.2);dialog=page._track_gain_dialog
        def fader_drag(key,offset):
            f=dialog.strips[key].fader;y=round(f.pixel_of(f.value()))
            drag(f,QPoint(f.width()//2,y),QPoint(f.width()//2,y+offset))
        fader_drag('A1',20);fader_drag('A2',-20)
        values=dict(page._gain_preview_values)
        check('multiple strips preview together',values.get('A1',0)<0 and values.get('A2',0)>0 and page.undo_stack.count()==count,values)
        f=dialog.strips['A2'].fader;start=f.value();a=QPoint(f.width()//2,round(f.pixel_of(start)))
        QTest.mousePress(f,Qt.LeftButton,Qt.NoModifier,a);QTest.mouseMove(f,a+QPoint(0,-20));settle(.1)
        QTest.keyClick(f,Qt.Key_Escape);QTest.mouseRelease(f,Qt.LeftButton,Qt.NoModifier,a+QPoint(0,-20));settle(.1)
        check('fader Esc restores pending value',f.value()==start and page._gain_preview_values==values)
        dialog.grab().save(str(output/'02b-multi-track-volume.png'))
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Ok),Qt.LeftButton)
        wait(lambda:getattr(page,'_track_gain_dialog',None) is None)
        check('multi-track apply is one undo',page.undo_stack.count()==count+1 and all(track_gain_db(project,k)==v for k,v in values.items()))
        page.undo_stack.undo();check('multi-track undo restores both',track_gain_db(project,'A1')==0 and track_gain_db(project,'A2')==0)
        page.undo_stack.redo();check('multi-track redo restores both',all(track_gain_db(project,k)==v for k,v in values.items()))
        page.undo_stack.undo()
        # Discard this acceptance-only history branch before the original scenario.
        count=page.undo_stack.index()
        show_track_gain(page,'A2');settle(.2);dialog=page._track_gain_dialog
        spin=dialog.findChild(__import__('PySide6.QtWidgets',fromlist=['QDoubleSpinBox']).QDoubleSpinBox,'trackGainDb')
        editor=spin.lineEdit();editor.setFocus();spin.selectAll()
        QTest.keyClicks(editor,'3.5');QTest.keyClick(editor,Qt.Key_Tab);settle(.1)
        QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok),Qt.LeftButton)
        wait(lambda:getattr(page,'_track_gain_dialog',None) is None)
        check('apply once',track_gain_db(project,'A2')==3.5 and page.undo_stack.count()==count+1)
        check('other lane untouched',track_gain_db(project,'A1')==0)
        # Whole-track vertical line; other clip positions and playhead stay fixed.
        timeline=page.timeline;row=timeline._audio_track_rects()['A2'];hit=geometry(timeline,'A2',row).center().toPoint()
        before=[(c.id,c.timeline_in_ms,c.timeline_out_ms) for t in project.audio_tracks for c in t.clips];playhead=timeline.playhead_ms
        count=page.undo_stack.count();drag(timeline,hit,hit+QPoint(0,-12))
        check('vertical up increases only selected track',track_gain_db(project,'A2')>3.5 and track_gain_db(project,'A1')==0,
              dict(value=track_gain_db(project,'A2'),hit=(hit.x(),hit.y()),row=str(row)))
        check('line drag single undo',page.undo_stack.count()==count+1)
        check('line leaves clips/playhead unchanged',before==[(c.id,c.timeline_in_ms,c.timeline_out_ms) for t in project.audio_tracks for c in t.clips] and timeline.playhead_ms==playhead)
        timeline.grab().save(str(output/'03-track-gain-line.png'))
        page.undo_stack.undo();check('line undo',track_gain_db(project,'A2')==3.5)
        row=timeline._audio_track_rects()['A2'];hit=geometry(timeline,'A2',row).center().toPoint()
        QTest.mousePress(timeline,Qt.LeftButton,Qt.NoModifier,hit);QTest.mouseMove(timeline,hit+QPoint(0,12));QTest.keyClick(timeline,Qt.Key_Escape)
        QTest.mouseRelease(timeline,Qt.LeftButton,Qt.NoModifier,hit+QPoint(0,12));settle(.2)
        check('Esc restores preview without history',track_gain_db(project,'A2')==3.5 and not page._gain_preview_values)
        show_project_loudness(page);settle(.2);panel=page._project_loudness_panel
        wait(lambda:panel.worker is None,90)
        check('real full-mix measurement',bool(panel.result),panel.status.text())
        metrics['analysis']=panel.result
        identity=baseline_identity(project);count=page.undo_stack.count()
        podcast=next(card for card in panel.destinations if card.key=='podcast')
        QTest.mouseClick(podcast,Qt.LeftButton);settle(.1)
        check('destination selects and persists target',panel.target.value()==-16 and project.studio_state.get('loudness_target')==-16 and baseline_identity(project)==identity)
        QTest.mouseClick(next(card for card in panel.destinations if card.key=='short'),Qt.LeftButton);settle(.1)
        for _ in range(10):QTest.mouseClick(panel.match,Qt.LeftButton);settle(.02)
        gain=project_gain_db(project)
        check('matching absolute repeated ten times',page.undo_stack.count()<=count+1 and gain!=0,(gain,page.undo_stack.count(),count))
        panel.monitor.setValue(18);settle(.1)
        check('monitor excluded from baseline',baseline_identity(project)==identity and project_gain_db(project)==gain)
        panel.grab().save(str(output/'04-loudness-panel.png'))
        saved=output/'saved.2byteproj';save_project(project,saved);reopened=load_project(saved)
        check('save/reopen all gain scopes',project_gain_db(reopened)==gain and track_gain_db(reopened,'A2')==3.5)
        panel.accept();settle(.2)
        page.project_loudness_button.refresh();page.secondary_group_button.refresh()
        check('toolbar shows measured loudness and group icon',page.project_loudness_button.readout is not None and page.secondary_group_button.menu() is not None)
        window.grab().save(str(output/'05-volume-toolbar.png'))
        check('peak-limited calculation',match_gain(-20,-3)['gain_db']==2 and match_gain(-20,-9)['gain_db']==6)
        # Real output files, decoded and metered again. Blocking native work
        # stays off the GUI thread even in this acceptance scenario.
        import threading
        from ..system.platform_media import ffmpeg_tool
        from ..exports.studio_render import RenderJob,RenderSettings,run_render_job
        from ..exports.video_export import capture_video_graph
        from ..playback.audio_graph import capture_audio_graph
        from ..rendering.ass_compiler import compile_ass
        from ..playback.project_loudness import freeze_baseline,analyze_baseline
        from ..projects.studio_project import SubtitleProject,StudioMedia
        ass=output/'captions.ass';ass.write_text(compile_ass(project),encoding='utf-8-sig')
        frozen=__import__('copy').deepcopy(project)
        files={};export_errors=[]
        def export():
            try:
                for kind,suffix in [('audio','wav'),('video','mp4')]:
                    path=output/('matched.'+suffix)
                    settings=RenderSettings(output_kind=kind,container=suffix,width=960,height=540,fps=12,encoder='libx264',preset='ultrafast')
                    job=RenderJob(frozen.media.path,str(ass),str(path),settings=settings,start_seconds=0.,duration_seconds=327.,
                        audio_graph=capture_audio_graph(frozen),video_graph=capture_video_graph(frozen))
                    run_render_job(ffmpeg_tool(),job)
                    rendered=SubtitleProject(media=StudioMedia(str(path),duration_ms=327000));rendered.validate()
                    for asset in rendered.media_pool:asset.offline=False
                    _,bus=freeze_baseline(rendered,ffmpeg_tool())
                    files[kind]=analyze_baseline(ffmpeg_tool(),bus)
            except Exception:export_errors.append(traceback.format_exc())
        thread=threading.Thread(target=export);thread.start()
        heartbeats=0
        until=time.monotonic()+150
        while thread.is_alive() and time.monotonic()<until:settle(.04);heartbeats+=1
        check('actual audio and video export complete',not thread.is_alive() and not export_errors,export_errors)
        metrics['exports']=files;metrics['gui_heartbeats_during_export']=heartbeats
        check('WAV within target 0.5 LU',abs(files['audio']['integrated']+14)<=.5,files['audio'])
        check('AAC within target 0.5 LU',abs(files['video']['integrated']+14)<=.5,files['video'])
        check('actual output truepeak safe',all(value['true_peak']<=-1 for value in files.values()),files)
        # Same source/translation ownership, explicitly selecting English
        # translation of Japanese source. No translation-to-original timing.
        from ..subtitle_rules.subtitle_translation import set_manual
        from ..projects.studio_project import StudioCue
        jp=SubtitleProject(media=StudioMedia(project.media.path,duration_ms=327000),cues=[StudioCue('ja',5000,10681,'このゲームはとても面白いです')])
        jp.generation_metadata['language']={'code':'ja','requested':'ja'};jp.validate()
        sample="And uh but I just also say you what I'm going to do here does require studio."
        from ..subtitle_rules.subtitle_translation import _empty_container,normalize_target
        jp.generation_metadata['translation_records']=_empty_container(normalize_target('en'))
        set_manual(jp,'ja',sample,target='en')
        translated=output/'translation.2byteproj';save_project(jp,translated)
        page.undo_stack.setClean();window.open_studio_project(str(translated))
        wait(lambda:page.project is not project and page.project is not None and page.project.cues[0].id=='ja')
        wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
        wait(lambda:getattr(page.video,'_startup_state','')=='READY');settle(.6)
        page.timeline.set_subtitle_layer('translation')
        with patch('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete)),patch('twobyteasr.providers.llm_config.text_ai_key_missing',lambda *a,**k:False):
            page.run_sentence_refine(whole_project=True);wait(lambda:page._refine_task.ended is not None)
        view=page.project.generation_metadata['translations']['ja']
        check('selected English translation wraps independently', '\n' in view and ' '.join(view.split())==sample,view)
        check('Japanese source and time retained',page.project.cues[0].text=='このゲームはとても面白いです' and page.project.cues[0].start_ms==5000)
        page.undo_stack.undo();check('translation layout undo',page.project.generation_metadata['translations']['ja']==sample)
        # Persist evidence before orderly application exit.
        page.undo_stack.setClean();page._cancel_autosave() if hasattr(page,'_cancel_autosave') else None
        completed=True
    except Exception:
        error=traceback.format_exc()
    finally:
        persist()
        if page:
            try:page.undo_stack.setClean()
            except RuntimeError:pass
        window.close();app.processEvents();app.exit(0 if error is None else 1)
