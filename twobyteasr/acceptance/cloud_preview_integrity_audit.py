"""Track first-click and current-raster interaction evidence on a real app window."""
import json
import threading
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..playback.studio_mpv import MpvController
    from ..studio import studio_media_flow
    from ..studio.studio_track_header import button_rect
    result={'passed':False,'checks':[],'timings_ms':{}}
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value:raise AssertionError(name+': '+str(detail))
    def pump(seconds=.02):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:QApplication.processEvents();time.sleep(.002)
    def wait(predicate,seconds=30):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:
            pump()
            if predicate():return True
        return False
    wave_gate=threading.Event();wave_entered=threading.Event();player_entered=threading.Event()
    thumb_gate=threading.Event();thumb_entered=threading.Event()
    from ..studio.video_filmstrip import FilmstripCache
    original_thumb=FilmstripCache._decode_source
    original_start=MpvController.start
    original_wave=studio_media_flow.generate_progressive_waveform_cache
    def delayed_start(self,*args,**kwargs):
        player_entered.set()
        # Test-only controlled startup latency, never a product wait.
        release=threading.Event();threading.Timer(1.2,release.set).start();release.wait(3)
        return original_start(self,*args,**kwargs)
    def delayed_wave(*args,**kwargs):
        wave_entered.set();wave_gate.wait(30)
        return original_wave(*args,**kwargs)
    def delayed_thumb(self,source):
        thumb_entered.set();thumb_gate.wait(30)
        return original_thumb(self,source)
    def run():
        page=window.studio_page
        try:
            window._switch_page(page)
            page.project_controller.create_blank_project()
            check('blank project ready',wait(lambda:page.project is not None and page._project_view_state=='open'))
            t=page.timeline
            # A first import after a not-yet-started player is a supported state.
            if page.video.controller is not None:page.video.controller.close()
            page.video.controller=None;page.video._media_attached=False
            MpvController.start=delayed_start
            studio_media_flow.generate_progressive_waveform_cache=delayed_wave
            FilmstripCache._decode_source=delayed_thumb
            began=time.perf_counter()
            page._begin_media_drop([str(output/'media.mp4')],0)
            check('tracks established during player preparation',wait(lambda:bool(page.project.video_tracks and page.project.video_tracks[0].clips and player_entered.is_set())))
            p=page.project
            result['duration_ms']=p.media.duration_ms
            result['import_to_controls_ms']=round((time.perf_counter()-began)*1000,3)
            def click(kind,track_id,action):
                row=(t._audio_track_rects() if kind=='audio' else t._video_track_rects())[track_id]
                point=button_rect(kind,action,row).center().toPoint()
                begin=time.perf_counter();QTest.mouseClick(t,Qt.LeftButton,pos=point)
                result['timings_ms'].setdefault(kind+'_'+action,[]).append(round((time.perf_counter()-begin)*1000,3));save()
            first=p.video_tracks[0];audio=p.audio_tracks[0]
            check('first controls run before player is ready',page.video._initial_player_request is not None)
            click('audio',audio.id,'muted')
            check('first mute commits immediately',p.audio_tracks[0].muted)
            click('video',first.id,'enabled')
            check('first hide commits immediately',not p.video_tracks[0].enabled)
            for _ in range(2):click('audio',audio.id,'muted');click('video',first.id,'enabled')
            check('rapid toggles keep last intent',p.audio_tracks[0].muted and not p.video_tracks[0].enabled)
            check('waveform still pending',wait(wave_entered.is_set) and not wave_gate.is_set())
            check('player startup completes',wait(lambda:page.video._initial_player_request is None and page.video.controller is not None))
            check('startup does not reset mute/hidden',p.audio_tracks[0].muted and not p.video_tracks[0].enabled)
            page._begin_media_drop([str(output/'media.mp4')],0,'new')
            check('second video/audio pair imported',wait(lambda:len(p.video_tracks)==2 and len(p.audio_tracks)>=2))
            second=p.video_tracks[1];audio2=next(a for a in p.audio_tracks if a.linked_video_track_id==second.id)
            click('audio',audio2.id,'muted');click('video',second.id,'enabled')
            check('second pair changes without touching first',all(a.muted for a in p.audio_tracks) and not any(v.enabled for v in p.video_tracks))
            check('thumbnail decoding is still pending',wait(thumb_entered.is_set,3) and not thumb_gate.is_set())
            wave_gate.set();thumb_gate.set()
            check('background analysis completes',wait(lambda:t.waveform_state=='READY' and getattr(page,'_completed_waveform_progress',None)==(page._waveform_generation,page._waveform_last_ready_media),40))
            check('analysis completion does not reset tracks',all(a.muted for a in p.audio_tracks) and not any(v.enabled for v in p.video_tracks))
            click('video',first.id,'enabled')
            check('visible video restored',p.video_tracks[0].enabled)
            from ..timeline.studio_edit_sequence import sequence_of
            check('first imported primary keeps its sequence',bool(sequence_of(p).segments))
            # Add through the production command/undo route.
            from ..projects.studio_project import StudioCue, StudioSpeaker
            from ..timeline.studio_commands import add_cue_command
            if not p.speakers:p.speakers=[StudioSpeaker('S00','测试主播')]
            cue=StudioCue('canvas-test',0,5000,'画布可见字幕',speaker_id=p.speakers[0].id)
            page.undo_stack.push(add_cue_command(p,cue))
            page.cue_controller.model_changed()
            page._seek(.5);page.video.set_paused(True);page.select_cue(cue.id)
            page.position_edit_button.setChecked(True)
            page.ensure_active_subtitle_renderer(reason='acceptance_canvas')
            check('visible caption has real measured bounds',wait(lambda:not page.position_overlay._subtitle_rect().isEmpty(),40))
            overlay=page.position_overlay;old=overlay._subtitle_rect().center().toPoint()
            page.video.controller.screenshot_to_file(output/'visible-native.png',mode='window')
            check('visible native frame captured',wait(lambda:(output/'visible-native.png').exists(),10))
            page._subtitle_visibility_changed(cue.speaker_id,False)
            check('hidden caption clears bounds immediately',overlay._subtitle_rect().isEmpty() and not overlay._dragging)
            QTest.mouseClick(overlay,Qt.LeftButton,pos=old);QTest.mouseDClick(overlay,Qt.LeftButton,pos=old)
            check('old point cannot start hidden gesture',not overlay._dragging and not overlay.isVisible())
            check('timeline/list selection retained',page.selected_cue_id==cue.id and page.cue_model.row_for_cue_id(cue.id)>=0)
            page._subtitle_visibility_changed(cue.speaker_id,True)
            restored = wait(lambda:not overlay._subtitle_rect().isEmpty(),30)
            check('restored caption hit region returns',restored, dict(overlay_visible=overlay.isVisible(),
                position_checked=page.position_edit_button.isChecked(),selected=page.selected_cue_id,
                scene=page._caption_scene.trace(),hidden=list(t.hidden_speakers),page_visibility=page._subtitle_track_visibility))
            QTest.mousePress(overlay,Qt.LeftButton,pos=overlay._subtitle_rect().center().toPoint())
            check('restored caption can be dragged',overlay._dragging)
            QTest.keyClick(overlay,Qt.Key_Escape)
            QTest.mouseRelease(overlay,Qt.LeftButton,pos=old)
            page.video.controller.screenshot_to_file(output/'restored-native.png',mode='window')
            from .blank_project_audit import _capture
            _capture(window,output/'window.png')
            check('undo redo track state',page.undo_stack.canUndo())
            page.undo_stack.undo();page.undo_stack.redo()
            check('caption survives undo redo',any(c.id==cue.id for c in p.cues))
            from ..timeline.studio_commands import SetCueTranslationCommand, ReplaceCuesCommand
            from ..studio.studio_bilingual import apply_display
            from ..studio.canvas_visibility import visible_object_at
            page.undo_stack.push(SetCueTranslationCommand(p,cue.id,'Visible translation'))
            apply_display(page,mode='translation')
            panel=page.caption_transform_panel
            panel.language.setCurrentIndex(panel.language.findData('original'))
            page.ensure_active_subtitle_renderer(reason='translation_only')
            check('hidden original has no canvas handles',overlay._subtitle_rect().isEmpty() and not overlay.isVisible())
            panel.language.setCurrentIndex(panel.language.findData('translation'))
            check('shown translation has measured bounds',wait(lambda:not overlay._subtitle_rect().isEmpty(),30))
            hit=visible_object_at(page,overlay._subtitle_rect().center())
            check('translation only hits actual translation',hit==(cue.id,'translation'),hit)
            apply_display(page,mode='original')
            panel.language.setCurrentIndex(panel.language.findData('original'))
            from ..projects.studio_runtime_state import state_for, DirtyDomain
            def ink(fill,outline):
                from ..caption_style.style_field_patch import style_fields_command
                command=style_fields_command(p,[cue.id],dict(primary_color=fill,outline_width=outline,
                    outline2_width=0,shadow=0,border_style=1))
                page.undo_stack.push(command)
                page._refresh_ass_preview();page.ensure_active_subtitle_renderer(reason='acceptance_ink')
            ink('#00FFFFFF',3)
            check('transparent fill with stroke stays interactive',wait(lambda:not overlay._subtitle_rect().isEmpty(),30))
            ink('#00FFFFFF',0)
            check('zero alpha caption clears hit region',wait(lambda:overlay._subtitle_rect().isEmpty(),30))
            check('zero alpha does not hit old position',visible_object_at(page,old) is None)
            ink('#FFFFFFFF',3)
            check('restored ink becomes interactive',wait(lambda:not overlay._subtitle_rect().isEmpty(),30))
            single_point=overlay._subtitle_rect().center()
            begin=time.perf_counter()
            for _ in range(1000):visible_object_at(page,single_point)
            result['timings_ms']['1000_canvas_hits_1_cue']=round((time.perf_counter()-begin)*1000,3)
            # Long project, one current raster. Use the normal undoable replacement.
            extra=[StudioCue(f'long-{i:04d}',10000+i*2500,11800+i*2500,'长工程字幕',speaker_id=cue.speaker_id) for i in range(4000)]
            page.undo_stack.push(ReplaceCuesCommand(p,[*p.cues,*extra],'acceptance long project'))
            page.select_cue(cue.id);page._seek(.5);page.video.set_paused(True)
            check('4001 cue project keeps current canvas',wait(lambda:not overlay._subtitle_rect().isEmpty(),30))
            point=overlay._subtitle_rect().center()
            begin=time.perf_counter()
            hits=[visible_object_at(page,point) for _ in range(1000)]
            elapsed=(time.perf_counter()-begin)*1000
            result['timings_ms']['1000_canvas_hits_4001_cues']=round(elapsed,3)
            check('long project hits only current object',all(h==(cue.id,'original') for h in hits),elapsed)
            check('long project hit lookup remains bounded',elapsed<500,elapsed)
            page.undo_stack.undo();check('long project undo retains current cue',len(p.cues)==1 and p.cues[0].id==cue.id)
            page.undo_stack.redo();check('long project redo restores all cues',len(p.cues)==4001)
            from ..projects.studio_project import save_project
            check('caption undo redo retains primary sequence',bool(sequence_of(p).segments) and p.video_tracks[0].enabled)
            page._sync_multitrack_preview_at(500);page._seek(.5);pump(.15)
            save_project(p,output/'saved-result.2byteproj')
            page.video.controller.screenshot_to_file(output/'final-native.png',mode='window')
            _capture(window,output/'final-window.png')
            from ..providers.endpoint_editor_ui import EndpointEditor
            from ..providers.subtitle_request_policy import settings_policy
            from ..storage.settings import DEFAULT_SETTINGS,save_runtime_settings,load_runtime_settings
            from ..providers.llm_config import activate_ai_service
            from ..app.ui import persist_ai_configuration
            from PySide6.QtWidgets import QDialog,QVBoxLayout
            from types import SimpleNamespace
            import copy
            settings=copy.deepcopy(DEFAULT_SETTINGS)
            settings['models']['provider_profiles']={'custom':{'model':'local-relay','base_url':'http://127.0.0.1:1/v1'}}
            activate_ai_service(settings,'custom',stage='group',unified=True)
            dialog=QDialog(window);layout=QVBoxLayout(dialog)
            editor=EndpointEditor('字幕 AI','#3867c8','group',settings)
            layout.addWidget(editor);editor.advanced_toggle.setChecked(True)
            dialog.resize(760,820);dialog.show();pump(.15)
            check('settings show 10000 and thinking off',editor.max_output_tokens.value()==10000 and not editor.enable_thinking.isChecked())
            editor.max_output_tokens.setValue(12345);editor.enable_thinking.setChecked(True)
            editor.thinking_protocol.setCurrentIndex(editor.thinking_protocol.findData('deepseek'))
            values=editor.values()
            persisted=persist_ai_configuration(SimpleNamespace(RUNTIME_SETTINGS=settings),values,values,
                unified=True,share_key=False,require_ready=False,dry_run=True)
            settings['models'].update(persisted['models']);settings['switches']['unified_glm_processing']=True
            save_runtime_settings(settings,output/'settings-profile')
            loaded=load_runtime_settings(output/'settings-profile')[0]
            policy=settings_policy(loaded)
            check('custom settings survive normal persistence',policy==dict(max_output_tokens=12345,enable_thinking=True,thinking_protocol='deepseek'),policy)
            check('new settings controls fit visible dialog',editor.max_output_tokens.isVisible() and editor.thinking_protocol.isVisible())
            dialog.grab().save(str(output/'request-settings.png'));dialog.close()
            result['passed']=True;save()
        except Exception:
            result['error']=traceback.format_exc();save()
        finally:
            wave_gate.set();thumb_gate.set();MpvController.start=original_start
            FilmstripCache._decode_source=original_thumb
            studio_media_flow.generate_progressive_waveform_cache=original_wave
            if page.project is not None:page.project_controller._mark_saved() if hasattr(page.project_controller,'_mark_saved') else None
            if page.project:
                page.undo_stack.setClean();page.project_dirty=False
            window.close();result['gui_shutdown']=True;save()
            QTimer.singleShot(300,QApplication.instance().quit)
    QTimer.singleShot(1200,run)
