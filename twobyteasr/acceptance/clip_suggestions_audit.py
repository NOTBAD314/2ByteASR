"""Real-window and original FLV/XML/SRT clip suggestions acceptance."""
from __future__ import annotations
import copy,json,os,time,traceback
from pathlib import Path

def start(window,output):
    from PySide6.QtWidgets import QApplication,QPushButton,QLabel,QFrame,QVBoxLayout
    from PySide6.QtCore import QTimer,Qt,QEvent
    from PySide6.QtTest import QTest
    from ..timeline.studio_edit_sequence import sequence_of
    from ..studio.studio_highlight_analyzer import analyze_highlights
    from ..studio.highlight_workflow import apply_range,timeline_range
    from ..projects.studio_project import load_project
    from ..media.danmaku_binding import effective_path
    app=QApplication.instance();page=window.studio_page;output=Path(output)
    result=dict(checks=[],errors=[],passed=False,gui_shutdown=False)
    def record():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));record()
        if not ok:raise AssertionError(name)
    def settle(ms=300):
        until=time.monotonic()+ms/1000
        while time.monotonic()<until:
            app.processEvents()
            app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            time.sleep(.01)
    def wait(fn,name,seconds=50):
        until=time.monotonic()+seconds
        while not fn():
            if time.monotonic()>until:raise TimeoutError(name)
            settle(40)
    def click(button):
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);settle(250)
    def grab(widget,name):
        widget.grab().save(str(output/(name+'.png')))
    def run():
        try:
            from ..design.theme_manager import apply_theme
            window.showNormal();window.resize(1540,940)
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'],mode='edit',source='clip_suggestions_audit')
            wait(lambda:page.project is not None and page._readiness.ready,'project ready',90)
            settle(700)
            page._open_clip_assistant();settle(300)
            panel=page.highlight_panel
            apply_theme('sand',app);settle(300)
            language=os.environ.get('TWOBYTEASR_CLIP_AUDIT_LANG','zh')
            index=window.language_combo.findData(language)
            if index>=0:window.language_combo.setCurrentIndex(index);settle(300)
            check('open waits for user playback',page.video._paused)
            project=page.project
            original_asset=copy.deepcopy(project.media_pool[0])
            # Only XML: same real recording, no imagined scene or actionable cut.
            panel.mode.setCurrentIndex(panel.mode.findData('xml'))
            click(panel.analyze_button)
            wait(lambda:not getattr(panel,'_analyzing',False),'XML analysis')
            settle(300)
            pending=sequence_of(project).clip_candidates
            check('real XML returns audience leads',bool(pending),len(pending))
            check('XML never asserts a cut or a verified event',all(c.clip_range is None for c in pending))
            check('analysis completion stays paused',page.video._paused)
            grab(page.context_panel,'01-xml-default')
            first=panel.results.itemWidget(panel.results.item(0))
            first.toggle_details();settle(300);grab(page.context_panel,'02-xml-evidence')
            panel.results.verticalScrollBar().setValue(220);settle(250)
            grab(page.context_panel,'02b-xml-evidence-scrolled')
            check('evidence contains timestamped original comments',any('[' in lab.text() and ']' in lab.text()
                    for lab in first.details_body.findChildren(QLabel)))
            first.toggle_details()
            # Caption + XML: use the existing SRT as input; no whole-file ASR.
            panel.mode.setCurrentIndex(panel.mode.findData('subtitles_xml'))
            click(panel.analyze_button)
            wait(lambda:not getattr(panel,'_analyzing',False),'caption analysis')
            settle(300)
            candidates=sequence_of(project).clip_candidates
            ready=[c for c in candidates if c.clip_range]
            if ready:
                check('captions plus XML yield cited boundary proposal',True,[(c.title,c.clip_range) for c in ready])
                candidate=min(ready,key=lambda c:c.source_out_ms-c.source_in_ms)
            else:
                grounded=[c for c in candidates if 'subtitle' in c.evidence_kinds]
                check('partial real transcript keeps uncertain cut pending',bool(grounded) and all(c.clip_range is None for c in grounded))
                candidate=grounded[0]
            # Reveal chosen row without triggering playback on expansion.
            panel._show_all=True;panel.reload_candidates(candidates);settle(200)
            item=next(panel.results.item(i) for i in range(panel.results.count()) if panel.results.item(i).data(Qt.ItemDataRole.UserRole)==candidate.id)
            panel.results.scrollToItem(item);panel.results.setCurrentItem(item);settle(250)
            card=panel.results.itemWidget(item)
            grab(page.context_panel,'03-caption-default');grab(window,'04-workspace')
            result['candidate_before']=candidate.to_dict()
            before=candidate.clip_range or candidate.view_range
            before_clip=candidate.clip_range
            mapped=timeline_range(project,candidate.source_path,*before)
            check('card cut maps to current timeline',mapped is not None,mapped)
            page.audio_engine.capture_pcm('real-preview',True)
            wait(lambda:(output/'real-preview.started').exists(),'PCM capture ready')
            click(card.preview_button)
            wait(lambda:not page.video._paused,'preview playing')
            settle(500)
            page.video.controller.screenshot_to_file(output/'04b-native-preview.png')
            check('preview starts within range',mapped[0]-150<=page.timeline.playhead_ms<=mapped[1],page.timeline.playhead_ms)
            wait(lambda:page.video._paused,'automatic preview end',max(20,(mapped[1]-mapped[0])/1000+15))
            check('preview stops at exact requested endpoint',abs(page.timeline.playhead_ms-mapped[1])<=100,page.timeline.playhead_ms)
            check('range visibly marked on timeline',page.timeline._highlight_preview_range==mapped)
            page.audio_engine.capture_pcm('real-preview',False)
            wait(lambda:(output/'real-preview.json').exists(),'PCM capture written')
            import numpy as np
            pcm=np.fromfile(output/'real-preview.tracks.f32',dtype='<f4')
            result['audio_preview']=page.audio_engine.telemetry_snapshot()
            check('real FLV preview submits non-silent PCM',len(pcm)>1000 and float(np.sqrt(np.mean(pcm**2)))>0.0001,
                  dict(samples=len(pcm),rms=float(np.sqrt(np.mean(pcm**2))) if len(pcm) else 0,
                       submitted_bytes=(output/'real-preview.pcm').stat().st_size))
            # The real modeless editor uses source times, then the existing undo stack.
            page._edit_highlight_range(candidate.id);settle(300)
            editor=page._highlight_range_editor
            from ..projects.project_range import clock_text
            new=(max(0,before[0]-500),min(candidate.source_duration_ms,before[1]+700))
            if before_clip is None:
                raw=json.loads((Path(os.environ['TWOBYTEASR_INVOKER_CWD'])/'tmp/clip-suggestions/real-transcript/raw.json').read_text('utf-8'))
                tokens=raw['results'][0]['text'].split();words=''.join(tokens);stamps=raw['results'][0]['timestamp']
                a=words.index('都是我们刚到一个地方')
                b=words.index('都是引路人呢')+len('都是引路人呢')
                new=(raw['source_start_ms']+stamps[a][0],raw['source_start_ms']+stamps[b-1][1])
            editor.range_fields[0].setText(clock_text(new[0]));editor.range_fields[1].setText(clock_text(new[1]))
            grab(editor,'05-adjust-range')
            click(next(b for b in editor.findChildren(QPushButton) if b.objectName()=='studioPrimary'))
            wait(lambda:page._highlight_range_editor is None,'editor close')
            current=next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id)
            check('card and preview range update together',current.clip_range==new,current.to_dict())
            page.undo_stack.undo();settle(250)
            check('range adjustment undo',next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id).clip_range==before_clip)
            page.undo_stack.redo();settle(250)
            page._set_candidate_status(candidate.id,'accepted');settle(300)
            check('selected range is visible in generation list',panel.bin.count()==1 and panel.generate_button.isVisible())
            undo_index=page.undo_stack.index();page._set_candidate_status(candidate.id,'accepted')
            check('repeat add has no duplicate or extra undo',panel.bin.count()==1 and page.undo_stack.index()==undo_index)
            grab(page.context_panel,'06-added-to-list')
            if project.video_tracks[0].locked or sequence_of(project).video_track_locked:
                page._toggle_video_lock();settle(250)
            click(panel.generate_button)
            result['generation_status']=panel.edit_result.text()
            result['generation_locks']=[(t.id,t.locked) for t in project.video_tracks]
            actual=sequence_of(project).segments
            check('generated clip equals adjusted preview range',len(actual)==1 and
                  (actual[0].source_in_ms,actual[0].source_out_ms)==new, [s.to_dict() for s in actual])
            grab(window,'07-generated-timeline')
            wait(lambda:not page.video._playback_clock.exact_seek_pending,'generated seek settled')
            settle(500)
            page.video.controller.screenshot_to_file(output/'07a-generated-native.png')
            # Source context outside the edited timeline opens read-only; it
            # must leave the canonical cut untouched and use audible source video.
            page._highlight_context(candidate.id);settle(500)
            source_view=getattr(page,'_highlight_source_view',None)
            check('removed context opens original-source viewer',source_view is not None)
            wait(lambda:source_view.canvas.controller is not None and not source_view.canvas._paused,'source context playback')
            settle(1500)
            source_view.canvas.controller.screenshot_to_file(output/'07b-source-native.png')
            check('source viewer owns its audio independently',source_view.canvas.controller.get_property('aid') not in (None,False,'no'))
            check('context viewing preserves selected cut',next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id).clip_range==new)
            grab(source_view,'07c-source-context')
            source_view.close();settle(300)
            # Clicking footage while working in Clips keeps the tool page.
            track=project.video_tracks[0];page._video_clip_selected(track.id,track.clips[0].id);settle(250)
            check('video selection keeps clipping workspace',page.context_drawer.currentIndex()==page.highlight_tab_index)
            # Every current tab can be saved, including former index 5 crash.
            for tab in range(page.context_drawer.count()):
                page.context_drawer.setCurrentIndex(tab);page._capture_studio_state()
            page.save();settle(350)
            saved=load_project(page.session.project_path)
            restored=next(c for c in sequence_of(saved).clip_candidates if c.id==candidate.id)
            check('saved/reopened exact manual range and state',restored.clip_range==new and restored.user_adjusted and restored.status=='accepted')
            result['candidate_after']=restored.to_dict()
            check('all six tool tabs save without tuple error',saved.studio_state['layout']['context_tab_id']=='media')
            page.context_drawer.setCurrentIndex(page.highlight_tab_index)
            page._set_candidate_status(candidate.id,'ignored');settle(200)
            check('ignore takes effect',next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id).status=='ignored')
            page.undo_stack.undo();settle(200)
            check('ignore undo restores accepted state',next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id).status=='accepted')
            panel.mode.setCurrentIndex(panel.mode.findData('subtitles_xml'))
            click(panel.analyze_button)
            wait(lambda:not getattr(panel,'_analyzing',False),'reanalysis after edit')
            kept=next(c for c in sequence_of(project).clip_candidates if c.id==candidate.id)
            check('reanalysis preserves user range and accepted state',kept.clip_range==new and kept.status=='accepted')
            # Rendering details and a narrow panel neither analyzes nor plays.
            apply_theme('grape',app);window.resize(1160,780);settle(350)
            grab(page.context_panel,'08-narrow-grape')
            check('narrow panel keeps actions usable',panel.width()>=280)
            # A truly narrow standalone instance of the same production panel,
            # using the actual candidates, checks 300 logical pixels explicitly.
            from ..studio.studio_highlight_ui import HighlightAssistantPanel
            narrow_host=QFrame();narrow_host.setObjectName('contextPanel')
            narrow_host.setStyleSheet(page.styleSheet())
            narrow_host.setWindowTitle('Clip panel acceptance')
            narrow_layout=QVBoxLayout(narrow_host);narrow_layout.setContentsMargins(0,0,0,0)
            narrow=HighlightAssistantPanel();narrow_layout.addWidget(narrow)
            narrow_host.resize(300,820);narrow.set_project_status(project,effective_path(project));narrow_host.show();settle(400)
            narrow.bin_toggle.setChecked(False);settle(100)
            grab(narrow,'08b-narrow-300')
            buttons=[]
            for row in range(narrow.results.count()):
                c=narrow.results.itemWidget(narrow.results.item(row))
                buttons.extend([(b.text(),b.width(),b.sizeHint().width()) for b in c._action_buttons])
            check('300px card buttons fit their labels',all(w+3>=hint for _,w,hint in buttons),buttons)
            narrow_host.close();narrow_host.deleteLater();settle(100)
            check('details and resizing do not play',page.video._paused)
            # Open the real save-error project copy and sample its retained late
            # FLV section, where source time is ~54 minutes and project time 0.
            error_copy=output/'projects'/'save-error-copy.2byteproj'
            if error_copy.is_file():
                page.undo_stack.setClean()
                window.open_studio_project(str(error_copy),mode='edit',source='clip_suggestions_audit')
                wait(lambda:page.session.project_path==error_copy and page._readiness.ready,'error copy ready',90)
                page._seek(0);settle(600)
                page.audio_engine.capture_pcm('user-flv-tail',True)
                wait(lambda:(output/'user-flv-tail.started').exists(),'tail capture ready')
                page.video.set_paused(False)
                settle(5000)
                result['user_flv_audio']=page.audio_engine.telemetry_snapshot()
                page.video.set_paused(True)
                page.audio_engine.capture_pcm('user-flv-tail',False)
                wait(lambda:(output/'user-flv-tail.json').exists(),'tail capture saved')
                raw=np.fromfile(output/'user-flv-tail.tracks.f32',dtype='<f4')
                check('user retained FLV tail produces real audio',len(raw)>1000 and float(np.sqrt(np.mean(raw**2)))>0.0001,
                      dict(samples=len(raw),rms=float(np.sqrt(np.mean(raw**2))) if len(raw) else 0))
                page.context_drawer.setCurrentIndex(page.media_pool_tab_index)
                saved_before=error_copy.stat().st_mtime_ns
                page.save();settle(200)
                written=load_project(error_copy)
                check('user save-error copy saves on last tool tab',
                      error_copy.stat().st_mtime_ns>saved_before and written.studio_state['layout']['context_tab_id']=='media',
                      dict(last_page=written.studio_state['layout']['context_tab_id'],status=page.save_state.text()))
                from ..timeline.studio_media_commands import media_graph_command
                from ..timeline.studio_media_pool import add_media_asset,add_video_clip,remove_video_clip,create_video_track,primary_video_track_id
                from ..media.danmaku_binding import primary_source,binding_matches_source
                legacy_source=page.project.media.path
                def replace_retained(working):
                    track=working.video_tracks[0];track.locked=False
                    asset=add_media_asset(working,original_asset.canonical_source,
                        duration_ms=original_asset.duration_ms,video_metadata=original_asset.video_metadata,
                        audio_metadata=original_asset.audio_metadata)
                    for c in list(track.clips):remove_video_clip(working,track.id,c.id)
                    retained=create_video_track(working)
                    add_video_clip(working,retained.id,asset.asset_id,timeline_in_ms=0)
                page.undo_stack.push(media_graph_command(page.project,'保留最后导入的录播',replace_retained))
                wait(lambda:binding_matches_source(page.project),'new source XML discovery',30)
                page._open_clip_assistant();settle(250)
                check('retained source replaces stale initial recording in analysis',
                    primary_source(page.project)==original_asset.canonical_source
                    and page.project.media.path==legacy_source
                    and panel.source_combo.currentData()==original_asset.canonical_source)
                panel.mode.setCurrentIndex(panel.mode.findData('xml'));click(panel.analyze_button)
                wait(lambda:not getattr(panel,'_analyzing',False),'retained-source analysis')
                current_rows=sequence_of(page.project).clip_candidates
                check('new analysis names only retained recording',bool(current_rows) and all(
                    c.source_path==original_asset.canonical_source for c in current_rows if c.status=='suggested'))
                grab(page.context_panel,'09-retained-recording')
                retained=next(t for t in page.project.video_tracks if t.clips)
                old_primary=primary_video_track_id(page.project)
                check('actual retained recording is on secondary video track',retained.id!=old_primary)
                target=current_rows[0]
                apply_range(page,target.id,*new);settle(200)
                page._set_candidate_status(target.id,'accepted');settle(200)
                active=next(c for c in sequence_of(page.project).clip_candidates if c.id==target.id)
                from ..studio.highlight_workflow import preview
                preview(page,active.id)
                wait(lambda:not page.video._paused,'secondary preview playing',30)
                wait(lambda:page.video._paused and getattr(page,'_highlight_preview',None) is None,'secondary preview endpoint',30)
                check('secondary-track preview uses adjusted source range',abs(page.timeline.playhead_ms-new[1])<=100,page.timeline.playhead_ms)
                click(panel.generate_button)
                check('generation trims retained track without duplicating recording',
                    primary_video_track_id(page.project)==retained.id and not page.project.video_tracks[0].clips
                    and len(sequence_of(page.project).segments)==1
                    and (sequence_of(page.project).segments[0].source_in_ms,sequence_of(page.project).segments[0].source_out_ms)==new,
                    [(t.id,[(c.source_in_ms,c.source_out_ms) for c in t.clips]) for t in page.project.video_tracks])
                linked=[c for t in page.project.audio_tracks if t.linked_video_track_id==retained.id for c in t.clips]
                check('retained track linked audio uses same cut',bool(linked) and all((c.source_in_ms,c.source_out_ms)==new for c in linked))
                page.undo_stack.undo();settle(250)
                check('retained track generation undo restores full recording',primary_video_track_id(page.project)==old_primary
                    and next(t for t in page.project.video_tracks if t.id==retained.id).clips[0].source_out_ms==original_asset.duration_ms)
                page.undo_stack.redo();settle(250)
                page.save();settle(200)
                reopened=load_project(error_copy)
                check('retained track generation persists after redo and reopen',primary_video_track_id(reopened)==retained.id
                    and (sequence_of(reopened).segments[0].source_in_ms,sequence_of(reopened).segments[0].source_out_ms)==new)
                grab(window,'10-secondary-generated')
            page.undo_stack.setClean()
            result['passed']=all(c['passed'] for c in result['checks'])
        except Exception:result['errors'].append(traceback.format_exc())
        record()
        if page.project:page.undo_stack.setClean()
        window.close();QTimer.singleShot(400,app.quit)
    def shutdown():
        result['gui_shutdown']=True;record()
    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2200,run)
