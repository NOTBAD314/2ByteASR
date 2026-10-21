"""Real media, normal application entry and actual widgets; no external AI."""
import copy, json, os, sys, time, traceback
from pathlib import Path

def run(window,out):
    from PySide6.QtCore import QTimer, Qt, QPoint
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QComboBox
    from ..projects.studio_project import load_project,save_project
    from ..diagnostics.build_identity import load_build_identity
    from ..subtitle_rules import subtitle_translation as st
    from .blank_project_audit import _capture
    out=Path(out); route=os.environ['TWOBYTEASR_FOLLOWUP_ROUTE']
    path=Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
    result=dict(passed=False,checks=[],screenshots=[],pid=os.getpid(),frozen=bool(getattr(sys,'frozen',False)),
                identity=load_build_identity().to_dict(),route=route,scope='original media copy; no paid API')
    def save(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,condition,detail=None):
        result['checks'].append(dict(name=name,passed=bool(condition),detail=detail));save()
        if not condition:raise AssertionError(name+': '+str(detail))
    def wait(predicate,label,seconds=70):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:
                if page is not None:
                    scene=getattr(page,'_caption_scene',None)
                    cache=getattr(page,'_caption_playback_cache',None)
                    result['timeout_state']=dict(label=label,preview=str(page._preview_path),
                        scene=scene.trace() if scene else None,
                        scene_work={k:repr(getattr(scene,k,None)) for k in ('token','last_request','last_result_token','pending','closed','active')},
                        cache_work={k:repr(getattr(cache,k,None)) for k in ('_materialized_key','_pending','_running','_closed','prepared_count')},
                        cache_keys=list(getattr(cache,'_frames',{})),
                        geometry=page._advanced_preview_size(),tick_geometry=getattr(page,'_caption_tick_geometry',None),
                        clock=page.video.playback_position_snapshot(),revision=page._revision_store.render)
                    save()
                raise TimeoutError(label)
            QTest.qWait(25)
    def capture(name,widget=None):
        dest=out/(name+'.png');_capture(widget or window,dest);result['screenshots'].append(str(dest));save()
    page=None
    try:
        window.resize(1600,1000);window.show()
        # Confirm the original autosave via its actual recovery dialog when
        # this cold run specifically exercises recovery inspection.
        recovery_timer=QTimer(window)
        def recover():
            from PySide6.QtWidgets import QMessageBox
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                buttons=modal.buttons()
                chosen=next((b for b in buttons if '正式' in b.text()),None)
                if chosen is not None:QTest.mouseClick(chosen,Qt.MouseButton.LeftButton)
        if os.environ.get('TWOBYTEASR_FOLLOWUP_RECOVERY')=='1':
            recovery_timer.timeout.connect(recover);recovery_timer.start(150)
        if route=='recent':
            from ..app.home_studio_entry import RecentProjectHero
            hero=window.findChild(RecentProjectHero,'homeRecentHero')
            check('recent-hero-present',hero is not None)
            hero.set_entry(dict(path=str(path),name='日常・原问题工程副本',count=74))
            QTest.mouseClick(hero,Qt.MouseButton.LeftButton)
        elif route!='direct':
            window.open_studio_project(path,source='home_open_project')
        page=window.studio_page
        wait(lambda:page.project is not None and page._readiness.ready,'initial project readiness')
        recovery_timer.stop()
        check('original-project-opened',len(page.project.cues)==len(load_project(path).cues) and Path(page.project.media.path).is_file())
        samples=[]
        def sample_pause(label):
            before=page.video.visual_position(); audio_before=page.audio_engine.telemetry_snapshot(); QTest.qWait(1300)
            observed=page.video.controller.observed_properties()
            audio=page.audio_engine.telemetry_snapshot()
            sample=dict(label=label,before=before,after=page.video.visual_position(),paused=page.video._paused,
                mpv_pause=observed.get('pause'),audio=audio,readiness=page._readiness.profile)
            samples.append(sample);result['playback_samples']=samples
            check(label+'-paused-and-stationary',page.video._paused and observed.get('pause') is True
                and abs(sample['after']-before)<.08 and audio.get('state')!='PLAYING'
                and audio.get('sink_consumed_bytes',0)==audio_before.get('sink_consumed_bytes',0),sample)
        sample_pause('cold-open-nonzero')
        check('cold-open-device-submitted-no-audio',samples[-1]['audio'].get('sink_consumed_bytes',0)==0)
        capture('01-open-paused')
        # An explicit user click is the only action starting transport.
        before=page.video.visual_position();page.video.set_paused(False)
        wait(lambda:not page.video._paused and page.video.visual_position()>before+.45
             and page.audio_engine.telemetry_snapshot().get('state')=='PLAYING'
             and abs(page.timeline.playhead_ms-page.video.visual_position()*1000)<200,
             'explicit playback advances after the audio seek gate',35)
        check('explicit-play-audio-and-timeline',not page.video._paused and
              abs(page.timeline.playhead_ms-page.video.visual_position()*1000)<200,
              page.audio_engine.telemetry_snapshot())
        page.video.set_paused(True)
        for switch_index in range(int(os.environ.get('TWOBYTEASR_FOLLOWUP_SWITCH_COUNT','1')) if route=='switch' else 0):
            second=out/f'second-copy-{switch_index}.2byteproj';p=load_project(path);p.studio_state['playhead_ms']=67566
            save_project(p,second);page.undo_stack.setClean();page.video.set_paused(False)
            window.open_studio_project(second,source='switch_project')
            wait(lambda:page._readiness.ready and Path(page.session.project_path)==second,'switch ready')
            sample_pause('switch-from-playing')
        if os.environ.get('TWOBYTEASR_FOLLOWUP_FULL')=='1':
            p=page.project
            page.select_cue('24');page.cue_controller.timeline_selection_changed(['24','25'])
            from ..timeline.studio_commands import merge_cues_command
            before=st.snapshot(p)
            page.undo_stack.push(merge_cues_command(p,['24','25'],page.cue_controller.model_changed))
            combined=st.records_of(p)['24']['text']
            check('original-local-merge-complete',combined=='好可怕 好可怕 虚拟世代好可怕',combined)
            page.undo_stack.undo();check('merge-undo-exact',st.snapshot(p)==before)
            page.undo_stack.redo();page.select_cue('24');page._seek(67.566);QTest.qWait(700)
            capture('02-merged-translation')
            # QPushButton menus are modal: drive the real menu from its nested event loop.
            def bilingual_menu():
                menu=page.bilingual_toggle_button.menu();capture('03-bilingual-entry',menu)
                check('selected-translation-enabled',menu.actions()[0].isEnabled())
                check('usage-removed-from-bilingual',not any('API' in a.text() for a in menu.actions()))
                menu.close()
            QTimer.singleShot(250,bilingual_menu)
            QTest.mouseClick(page.bilingual_toggle_button,Qt.MouseButton.LeftButton)
            # 2026-10-21 (user): API 用量与费用 lives only in ⋯ now; open it from that menu.
            from PySide6.QtWidgets import QToolButton
            overflow=next(b for b in page.studio_toolbar.findChildren(QToolButton) if b.property('commandSource')=='更多工作区操作')
            overflow_menu=overflow.menu();overflow_menu.popup(overflow.mapToGlobal(overflow.rect().bottomLeft()));QTest.qWait(250)
            usage_entries=[a for a in overflow_menu.actions() if a.text()==page.studio_usage_button.text()]
            capture('03b-overflow-usage',overflow_menu)
            check('bilingual-on-bar-usage-in-overflow',page.bilingual_toggle_button.isVisible() and not page.studio_usage_button.isVisible()
                  and len(usage_entries)==1,[a.text() for a in overflow_menu.actions()])
            overflow_menu.hide();usage_entries[0].trigger();QTest.qWait(200)
            usage=page._usage_dialog;wait(lambda:not usage._loading and hasattr(usage,'visible_rows'),'usage rows');capture('04-api-usage',usage)
            result['usage_rows']=len(usage.visible_rows);usage.close()
            page._open_translation_dialog(scope='all')
            translation=page._translation_dialog
            check('translate-whole-project-scope',translation.scope_buttons['all'].isChecked())
            QTest.mouseClick(translation.start_button,Qt.MouseButton.LeftButton)
            check('missing-key-explained','没有运行' in translation.status.text() and translation.settings_button.isVisible(),translation.status.text())
            QTest.mouseClick(translation.settings_button,Qt.MouseButton.LeftButton)
            settings=window._ai_settings_dialog
            check('translation-settings-open',settings.isVisible())
            settings.reject();wait(lambda:translation.isVisible(),'return from settings',10)
            check('translation-settings-return',translation.isVisible() and translation.scope_buttons['all'].isChecked())
            translation.close()
            def speaker():
                dialog=QApplication.activeModalWidget()
                try:
                    check('speaker-name-switch-visible',dialog.show_names.isVisible())
                    QTest.mouseClick(dialog.show_names,Qt.MouseButton.LeftButton,pos=QPoint(12,dialog.show_names.height()//2));QTest.qWait(100)
                    card=dialog.cards[p.cues[0].speaker_id];card.name_edit.setText('优子')
                    QTest.keyClick(card.name_edit,Qt.Key.Key_Return)
                    check('speaker-name-preview-live','优子：' in dialog.name_preview.text(),dialog.name_preview.text())
                    capture('05-speaker-names',dialog)
                finally:dialog.accept()
            QTimer.singleShot(350,speaker);QTest.mouseClick(page.speaker_manager_button,Qt.MouseButton.LeftButton)
            from ..studio.studio_chinese_script import open_convert_dialog,TRADITIONAL
            def convert():
                dialog=QApplication.activeModalWidget()
                try:
                    layer=dialog.findChild(QComboBox,'chineseScriptLayer')
                    scope=dialog.findChild(QComboBox,'chineseScriptScope')
                    check('japanese-converts-only-chinese-translation',layer.count()==1 and layer.currentData()=='translation')
                    scope.setCurrentIndex(scope.findData('all'));QTest.qWait(100);capture('06-subtitle-script',dialog)
                    QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok),Qt.MouseButton.LeftButton)
                except Exception:dialog.reject();raise
            japanese=[c.text for c in p.cues]
            QTimer.singleShot(300,convert);open_convert_dialog(page,TRADITIONAL)
            check('script-keeps-japanese-and-converts-translation',[c.text for c in p.cues]==japanese
                and '虛擬世代' in p.generation_metadata['translations']['24'])
            # Original evidence and separately measured CTC agree on this one cut.
            from ..recognition.ctc_alignment import propose
            from ..studio.studio_ctc_refine import _alternate_start,RefineStartsCommand
            from ..studio.studio_cut_refine import _measured
            from types import SimpleNamespace
            rows=[SimpleNamespace(id=c.id,start_ms=c.start_ms,end_ms=c.end_ms,speaker=c.speaker_id,cue=c) for c in p.cues]
            changes=propose(rows,{'2':12864},lambda r:_measured(p,r.cue,'start'),alternate_start=lambda r:_alternate_start(p,r.cue))
            check('original-disputed-cut-accepted',len(changes)==1,[c.receipt() for c in changes])
            page.undo_stack.push(RefineStartsCommand(p,changes));page.select_cue('2');page._seek(12.909);QTest.qWait(500)
            capture('07-corrected-boundary')
            corrected=out/'review-copy.2byteproj';save_project(p,corrected);loaded=load_project(corrected)
            check('save-reopen-data-identical',st.snapshot(loaded)==st.snapshot(p) and loaded.cues==p.cues
                and loaded.studio_state['show_speaker_names'])
            from ..exports.studio_subtitle_export import SubtitleExportOptions,export_subtitle_artifacts
            artifacts=export_subtitle_artifacts(loaded,out/'exports','review',SubtitleExportOptions(frozenset({'srt','ass','txt','json'}),'both'))
            result['exports']=[str(a.path) for a in artifacts]
            combined_srt=(out/'exports/review.srt').read_text('utf8')
            check('export-merged-name-translation',all(text in combined_srt for text in ['优子：','虛擬世代','好可怕 好可怕']))
            check('export-corrected-time','00:00:12,864' in combined_srt)
            from ..exports.studio_render import _filter_path
            from ..system.platform_media import ffmpeg_tool
            from ..system.processes import run_hidden_subprocess
            ass=out/'exports/review.ass'
            for name,begin in [('boundary',11.0),('merged',65.5)]:
                destination=out/(name+'-burn-in.mp4')
                command=[ffmpeg_tool(),'-v','error','-y','-ss',str(begin),'-copyts','-i',p.media.path,
                    '-vf',f'ass=filename={_filter_path(ass)},setpts=PTS-STARTPTS,scale=960:540',
                    '-af','asetpts=PTS-STARTPTS','-t','6','-c:v','libx264','-preset','ultrafast','-crf','20',
                    '-c:a','aac',str(destination)]
                run_hidden_subprocess(command,purpose='Original-media subtitle burn-in acceptance',check=True,timeout=90)
                frame=out/(name+'-burn-in.png')
                run_hidden_subprocess([ffmpeg_tool(),'-v','error','-y','-ss','2','-i',str(destination),
                    '-frames:v','1',str(frame)],purpose='Inspect real burned-in subtitle frame',check=True,timeout=30)
                check(name+'-burn-in-created',destination.stat().st_size>10000 and frame.is_file())
            # Failure during read must preserve the currently usable project.
            invalid=out/'invalid.2byteproj';invalid.write_text('{invalid','utf8');page.undo_stack.setClean()
            def dismiss_error():
                modal=QApplication.activeModalWidget()
                if modal is not None:
                    capture('08a-load-error-detail',modal);modal.reject()
            QTimer.singleShot(700,dismiss_error)
            window.open_studio_project(invalid,source='invalid_open')
            wait(lambda:not page._readiness.active,'invalid read finishes')
            check('failed-open-preserves-current',page.project is p and page._readiness.copy_error.isVisible())
            capture('08-recoverable-error');page._readiness.cancel()
            # Cancel a real in-flight file read, then let its late result arrive.
            page._readiness.begin(path,skip_dirty_guard=True);page._readiness.cancel();QTest.qWait(1500)
            check('cancelled-load-rejects-old-callback',page.project is p and page.video._paused)
        page.undo_stack.setClean();result['passed']=all(c['passed'] for c in result['checks'])
    except Exception:
        result['error']=traceback.format_exc()
        try:capture('failure')
        except Exception:pass
    finally:
        if page is not None:
            page.video.set_paused(True);page.undo_stack.setClean()
        save()
    return 0 if result['passed'] else 1

def start(window,out):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        code=run(window,out);window.result_exit_code=code
        def stopped():
            path=Path(out)/'result.json';data=json.loads(path.read_text('utf8'));data['gui_shutdown']=True
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(150,execute)
