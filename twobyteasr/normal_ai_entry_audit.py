"""Opt-in real design/choose/apply/save UI flow, with externally inspected pixels."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
import traceback

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QFileDialog, QLineEdit, QToolButton, QScrollArea


def start(window, out):
    page = window.studio_page
    phase = os.environ.get('TWOBYTEASR_NORMAL_AI_PHASE', 'generate')
    config = json.loads((out/'run-config.json').read_text('utf8'))
    result = dict(passed=False, phase=phase, real_user_click=False, user_verified=False,
                  checks=[], actual_buttons=[], states=[])
    started = time.monotonic()
    timer_samples=[];last_tick=[started]
    responsiveness=QTimer(window);responsiveness.setInterval(50)
    def sample_tick():
        now=time.monotonic();draft=getattr(page,'_theme_draft_coordinator',None)
        timer_samples.append((getattr(draft,'phase','startup'),(now-last_tick[0])*1000))
        last_tick[0]=now
    responsiveness.timeout.connect(sample_tick);responsiveness.start()
    QApplication.instance().aboutToQuit.connect(lambda:(out/(phase+'-closed.txt')).write_text('closed','utf8'))

    def write(name, value):
        path = out/name
        temporary = path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf8')
        temporary.replace(path)

    def pump(seconds):
        until = time.monotonic()+seconds
        while time.monotonic()<until:
            QApplication.processEvents()
            time.sleep(.005)

    def wait(predicate, timeout, label):
        until = time.monotonic()+timeout
        while not predicate() and time.monotonic()<until:
            pump(.05)
        if not predicate():
            raise AssertionError('Timed out: '+label)

    def check(name, value):
        result['checks'].append(dict(name=name, passed=bool(value)))
        if not value:
            raise AssertionError(name)

    def click(button, name, *, panel=True):
        if panel:
            page._show_context_panel()
            page._scroll_ai_panel_into_view(button)
        pump(.12)
        check(name+' visible and enabled', button.isVisible() and button.isEnabled())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        result['actual_buttons'].append(name)
        pump(.08)

    def theme_in_project():
        cue = next(c for c in page.project.cues if c.id=='audit-ai')
        return page.project.style_recipes.get(cue.style_id, {}).get('webTheme', {})

    def theme_hash(theme):
        if not theme:
            return ''
        from .theme_draft import canonical_theme
        return hashlib.sha256(canonical_theme(theme).encode('utf8')).hexdigest()

    def state(label):
        draft = getattr(page, '_theme_draft_coordinator', None)
        result['states'].append(dict(label=label, elapsed_seconds=round(time.monotonic()-started, 3),
            phase=draft.phase if draft else '', request_id=draft.current.request_id if draft and draft.current else '',
            generation=page._ai_request_generation, project_theme_hash=theme_hash(theme_in_project()),
            draft_theme_hash=draft.current.content_hash if draft and draft.current else ''))
        window.grab().save(str(out/(label+'-qt.png')))
        write(phase+'-result.json', result)

    def native_frame(label):
        composed=out/(label+'-mpv.png')
        page.video.controller.screenshot_to_file(composed,mode='window')
        wait(lambda:composed.is_file() and composed.stat().st_size>0,5,'actual composed playback pixels '+label)
        from .processes import run_hidden_subprocess
        from .runtime_paths import detect_install_root
        run_hidden_subprocess([detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
            f'gfxcapture=hwnd={int(window.winId())}:max_framerate=10:capture_cursor=0','-vf','hwdownload,format=bgra',
            '-frames:v','1','-y',out/(label+'-native.png')],timeout=10,purpose='normal AI actual window pixels')

    def library_themes():
        from .style_presets import StylePresetStore
        return {key: value.get('webTheme', {}) for key, value in StylePresetStore().load_recipes().items()
                if value.get('webTheme')}

    def final_html_frame(label):
        target_stage_ms=min(1750 if config.get('import_theme') else 1500,250+config.get('cue_seconds',3)*500)
        wait(lambda: getattr(page,'_advanced_canvas_source_kind','')=='web_live'
             and getattr(page,'_web_live_published_cue','')=='audit-ai'
             and abs(getattr(page.advanced_cue_overlay,'_web_frame_context',{}).get('web_stage_ms',-1)-target_stage_ms)<80,
             35,'current authored HTML pixels, not temporary LIVE approximation')
        result.setdefault('html_presentations',[]).append(dict(label=label,
            context=dict(page.advanced_cue_overlay._web_frame_context),
            source=page._advanced_canvas_source_kind,cue=page._web_live_published_cue))
        pump(.15);native_frame(label)

    def toolbar_history(redo=False):
        prefix='重做' if redo else '撤销'
        button=next(b for b in page.findChildren(QToolButton) if b.toolTip().startswith(prefix+' ('))
        click(button,('redo' if redo else 'undo')+' ordinary toolbar action',panel=False)

    def edit_and_restore(chosen):
        """Optional actual controls; never synthesize a replacement AI response."""
        replacement=str(config.get('replacement_text') or '')
        cue=next(c for c in page.project.cues if c.id=='audit-ai')
        if replacement:
            original=cue.text
            before_key=getattr(page.advanced_cue_overlay,'_web_frame_context',{}).get('web_content_key')
            page.select_cue(cue.id);page.timeline.setFocus()
            QTest.keyClick(page.timeline,Qt.Key_E)
            wait(lambda:getattr(page,'_canvas_editor',None) is page.subtitle_edit_input,4,'ordinary E subtitle editor')
            editor=page.subtitle_edit_input
            check('editor opens exact adopted cue text',editor.toPlainText()==original)
            editor.selectAll();event=QInputMethodEvent();event.setCommitString(replacement)
            QApplication.sendEvent(editor,event)
            QTest.keyClick(editor,Qt.Key_Return)
            wait(lambda:next(c for c in page.project.cues if c.id=='audit-ai').text==replacement,5,'committed replacement text')
            check('replacement preserves complete theme source',theme_hash(theme_in_project())==theme_hash(chosen))
            wait(lambda:getattr(page.advanced_cue_overlay,'_web_frame_context',{}).get('web_content_key')!=before_key,35,'replacement publishes a new authored content key')
            final_html_frame('edited-text')
            toolbar_history()
            check('text edit undo restores original text',next(c for c in page.project.cues if c.id=='audit-ai').text==original)
            toolbar_history(redo=True)
            check('text edit redo restores replacement text',next(c for c in page.project.cues if c.id=='audit-ai').text==replacement)
            final_html_frame('edited-text-redo')
            result['text_edit']=dict(original=original,replacement=replacement,theme_hash=theme_hash(chosen))
        if config.get('verify_restore'):
            page.select_cue('audit-ai');page._show_context_panel()
            button=page.web_adjust_restore
            tab=next(i for i in range(page.context_drawer.count()) if page.context_drawer.widget(i).isAncestorOf(button))
            page.context_drawer.setCurrentIndex(tab)
            parent=button.parentWidget()
            while parent is not None and not isinstance(parent,QScrollArea):parent=parent.parentWidget()
            if parent is not None:parent.ensureWidgetVisible(button)
            click(button,'restore ordinary subtitle style',panel=False)
            check('restore button removes authored theme from current cue',not theme_in_project())
            expected=next(c for c in page.project.cues if c.id=='audit-ai').text
            def restored_visible():
                try:return page.video.controller.get_property('sub-visibility',False) is True and page.video.controller.get_property('sub-text','')==expected
                except RuntimeError:return False
            wait(restored_visible,12,'restored ordinary caption reaches actual mpv output')
            native_frame('restored-ordinary')
            toolbar_history()
            check('undo restore recovers exact adopted theme',theme_hash(theme_in_project())==theme_hash(chosen))
            page._seek(min(1.75 if config.get('import_theme') else 1.5,.25+config.get('cue_seconds',3)*.5))
            final_html_frame('restored-theme-by-undo')
            page.context_drawer.setCurrentIndex(0)

    def export_short():
        click(page.studio_render_button,'open ordinary export workspace',panel=False)
        wait(lambda: page.export_workspace is not None and page.export_workspace.isVisible(),10,'export workspace')
        ui=page.export_workspace
        target=out/'new-generation-export.mp4'
        ui.directory.setText(str(out));ui.filename.setText(target.stem)
        ui.extension.setCurrentIndex(ui.extension.findData('mp4'))
        ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
        ui.resolution.setCurrentIndex(ui.resolution.findData((1920,1080)))
        ui.fps.setCurrentIndex(ui.fps.findData(30.0))
        ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
        duration_ms=config.get('cue_seconds',3)*1000
        from .project_range import set_range
        set_range(page.project,250,250+duration_ms,page.undo_stack)
        ui._update_range()
        ui._target_changed()
        good=[];errors=[]
        ui.render_succeeded.connect(good.append);ui.render_failed.connect(errors.append)
        ui.preview_scroll.ensureWidgetVisible(ui.export_button);pump(.15)
        click(ui.export_button,'export newly generated theme',panel=False)
        wait(lambda: bool(good or errors),240,'real production export')
        check('production export succeeded '+str(errors),bool(good) and not errors and target.is_file())
        result['export']=dict(path=str(target),bytes=target.stat().st_size,
            receipt=dict(ui._last_job.completion_metadata),start_ms=250,duration_ms=duration_ms)
        from .processes import run_hidden_subprocess
        from .runtime_paths import detect_install_root
        for seconds in (.15,duration_ms/2000,duration_ms/1000-.15):
            run_hidden_subprocess([detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y',
                '-ss',str(seconds),'-i',target,'-frames:v','1',out/f'export-{seconds:g}.png'],
                check=True,timeout=15,purpose='decode real new-generation export')
        native_frame('export-complete')
        page._close_export_workspace()

    def play_current_theme(label):
        if config.get('wait_web_proxy'):
            from .caption_proxy import proxy_store
            def proxy_ready():
                worker=getattr(page,'_web_live_worker',None)
                key=getattr(worker,'_proxy_key',None)
                return bool(key and proxy_store().status(key)=='ready')
            wait(proxy_ready,90,'complete adopted transparent proxy')
            check('transparent proxy ready '+label,proxy_ready())
        native_requests=[]
        original_native=page.video.set_native_subtitle_visible
        def observed_native(visible):
            at=page._caption_sample_ms()
            cue=next((c for c in page.project.cues if c.start_ms<=at<c.end_ms),None)
            payload=page.project.style_recipes.get(cue.style_id,{}) if cue else {}
            native_requests.append(dict(ms=at,visible=bool(visible),authored=bool(payload.get('webTheme'))))
            return original_native(visible)
        page.video.set_native_subtitle_visible=observed_native
        page._seek(.25);pump(.35)
        playback_started=time.monotonic()
        click(page.play_button,'play adopted theme '+label,panel=False)
        samples=[]
        until=time.monotonic()+config.get('cue_seconds',3)+.5
        while time.monotonic()<until:
            samples.append(dict(seconds=page.video.controller.observed_property('time-pos',None),
                wall_since_click=time.monotonic()-playback_started,
                native_visible=bool(page.video._native_subtitle_visible),
                canvas_source=getattr(page,'_advanced_canvas_source_kind',''),
                frame=dict(getattr(page.advanced_cue_overlay,'_web_frame_context',{}))))
            pump(.05)
        page.video.set_paused(True)
        page.video.set_native_subtitle_visible=original_native
        result.setdefault('native_requests',{})[label]=native_requests
        check('authored cue never requests ordinary native placeholder '+label,
              bool(native_requests) and not any(r['visible'] and r['authored'] for r in native_requests))
        check('authored cue excluded from timed ASS events '+label,
              'audit-ai' not in {c.id for c in page._ass_preview_revision().cues})
        positions=[r['seconds'] for r in samples if isinstance(r['seconds'],(int,float))]
        check('adopted theme plays through full cue '+label,bool(positions) and max(positions)>=config.get('cue_seconds',3)+.25)
        def ordinary_visible():
            try:
                return (page.video.controller.get_property('sub-visibility',False) is True
                    and page.video.controller.get_property('sub-text','')=='接下来继续向前走')
            except RuntimeError:
                # Pause may issue an exact seek; mpv temporarily has no sub-text
                # until that seek settles. The actual visibility must still pass.
                return False
        wait(ordinary_visible,5,'ordinary caption after pause seek settles '+label)
        check('following ordinary caption actually visible in mpv '+label,ordinary_visible())
        result.setdefault('actual_playback',{})[label]=samples
        worker=getattr(page,'_web_live_worker',None)
        if worker:result.setdefault('web_worker_metrics',{})[label]=list(worker.metrics)
        native_frame('playback-end-'+label)
        page._seek(min(1.75 if config.get('import_theme') else 1.5,.25+config.get('cue_seconds',3)*.5))
        final_html_frame('playback-return-'+label)

    def run():
        try:
            from .build_identity import load_build_identity
            from .provider_registry import GLOBAL_PROVIDER_REGISTRY
            result['identity'] = load_build_identity().to_dict()
            selection = GLOBAL_PROVIDER_REGISTRY.selection(GLOBAL_PROVIDER_REGISTRY.settings(), stage='polish')
            from urllib.parse import urlsplit
            result['provider'] = dict(service=selection.service, provider=selection.provider, model=selection.model,
                transport=selection.transport, endpoint_host=urlsplit(selection.base_url).hostname)
            wait(lambda: page.project is not None and page.video.controller is not None and page.video.controller.running,
                 20, 'real Studio media readiness')
            wait(lambda: page._readiness.ready or (not page._readiness.active and bool(page._readiness.profile.get('error'))),
                 40,'complete project readiness before audit interaction')
            result['project_readiness']=dict(page._readiness.profile)
            check('project ready without preparation failure',page._readiness.ready)
            window.raise_()
            window.activateWindow()
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            page._set_review_mode(False)
            page.select_cue('audit-ai')
            page._seek(min(1.75 if config.get('import_theme') else 1.5,.25+config.get('cue_seconds',3)*.5))
            pump(.5)
            if phase=='reopen':
                if config.get('verify_usability'):
                    from .theme_usability_audit import verify
                    verify(page,out,phase,check,wait,pump)
                expected = json.loads((out/'expected-theme.json').read_text('utf8'))
                check('new process has exact saved project theme', theme_hash(theme_in_project())==expected['theme_hash'])
                matches = [k for k, t in library_themes().items() if theme_hash(t)==expected['theme_hash']]
                check('new process loads exact saved library theme', matches==expected['library_ids'])
                check('new process keeps nonempty theme name', theme_in_project().get('name')==expected['name'])
                check('new process keeps stable theme id', theme_in_project().get('id')==expected['id'])
                if config.get('replacement_text'):
                    check('new process keeps edited caption text',next(c for c in page.project.cues if c.id=='audit-ai').text==config['replacement_text'])
                final_html_frame('reopened')
                if config.get('import_theme'):
                    page.video.controller.screenshot_to_file(out/'reopened-canvas.png',mode='window')
                state('reopened')
                play_current_theme('reopened')
                export_short()
                result['passed'] = True
                return

            if config.get('import_theme'):
                from .web_theme import import_theme_archive
                archive=Path(config['import_theme'])
                original_bytes=archive.read_bytes()
                chosen=import_theme_archive(archive)
                result['import_provenance']=dict(path=str(archive),archive_sha256=hashlib.sha256(original_bytes).hexdigest(),
                    theme_hash=theme_hash(chosen),model_calls=0)
                QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
                def choose_archive():
                    dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QFileDialog) and w.isVisible())
                    field=dialog.findChild(QLineEdit,'fileNameEdit')
                    field.setText(str(archive));QTest.keyClick(field,Qt.Key_Return)
                page.context_drawer.setCurrentIndex(0)
                drafts=page._theme_drafts()
                if config.get('workbench_ledger'):
                    # Read the isolated saved task; adoption still goes through
                    # the actual dialog signal, source gates and controller.
                    drafts.restore_saved_response(config['workbench_ledger'])
                    wait(lambda:getattr(drafts,'_concept_dialog',None) is not None and drafts._concept_dialog.isVisible(),
                         240,'saved candidate workbench with actual previews')
                    dialog=drafts._concept_dialog
                    expected_count=int(config.get('expected_candidates',3))
                    check('saved workbench has expected candidate count',dialog.candidate_list.count()==expected_count)
                    expected=next(i for i,c in enumerate(dialog.concepts) if theme_hash(c['authored_theme'])==theme_hash(chosen))
                    QTest.mouseClick(dialog.candidate_list.viewport(),Qt.LeftButton,pos=dialog.candidate_list.visualItemRect(dialog.candidate_list.item(expected)).center())
                    dialog.resize(1120,760);pump(.2)
                    positions=[dialog.candidate_list.visualItemRect(dialog.candidate_list.item(i)).y() for i in range(expected_count)]
                    check('candidate cards form one horizontal strip',len(set(positions))==1)
                    check('adopt action stays in the workbench',dialog.rect().contains(dialog.primary.geometry()))
                    check('operational evidence is in details', '本地：' not in dialog.status.text() and '本地：' in dialog.details['生成记录'].toPlainText())
                    check('candidate source is preserved', 'motionSpec' in dialog.details['源码与诊断'].toPlainText())
                    seen=[];dialog.movie.frameChanged.connect(seen.append)
                    from PySide6.QtGui import QMovie
                    if dialog.movie.state()==QMovie.Running:
                        click(dialog.play_button,'pause automatic candidate playback',panel=False)
                    click(dialog.play_button,'play complete candidate',panel=False)
                    wait(lambda:max(seen,default=-1)>=dialog.movie.frameCount()-1,9,'candidate enters reads and exits at normal speed')
                    check('candidate uses real 24fps transparent frames',dialog.movie.frameCount()==144 and dialog.movie.speed()==100)
                    dialog.grab().save(str(out/'frozen-candidate-workbench.png'))
                    click(dialog.primary,'adopt selected saved candidate',panel=False)
                    check('workbench accepted exact selected candidate',dialog.selected_id==dialog.concepts[expected]['id'])
                    result['workbench_provenance']=dict(kind='local_saved_source',model_calls=0,observed_frames=seen)
                else:
                    QTimer.singleShot(300,choose_archive)
                    click(page.ai_import_archive_button,'import existing theme archive')
                wait(lambda:drafts.phase in {'READY','APPLIED','FAILED'},120,'ordinary archive validation')
                check('archive import validated',drafts.is_valid())
                check('archive import preserves complete source',theme_hash(drafts.current.theme)==theme_hash(chosen))
                result['import_validation']=drafts.evidence
                # Adoption/import is now the apply action. A second button
                # here would hide a regression in the actual one-click flow.
                check('adoption automatically applies without second button',drafts.phase=='APPLIED'
                      and theme_hash(theme_in_project())==theme_hash(chosen))
                check('applied archive source unchanged',theme_hash(theme_in_project())==theme_hash(chosen))
                page._seek(min(1.75,.25+config.get('cue_seconds',3)*.5));final_html_frame('applied');state('applied')
                play_current_theme('imported')
                if page.video.controller:
                    page.video.controller.screenshot_to_file(out/'applied-canvas.png',mode='window')
                click(page.ai_save_style_button,'save imported theme to library')
                matches=[k for k,t in library_themes().items() if theme_hash(t)==theme_hash(chosen)]
                check('saved library preserves complete source',len(matches)==1)
                # The draft save gate is bound to its original design target.
                # Save that verified source before editing the adopted cue;
                # project persistence below still audits the replacement text.
                if config.get('verify_usability'):
                    from .theme_usability_audit import verify
                    # Gesture checks include undo of adoption; run them before
                    # text edits when the latest command is the apply action.
                    verify(page,out,phase,check,wait,pump)
                edit_and_restore(chosen)
                click(page.save_button,'save imported theme project',panel=False)
                wait(lambda:page.undo_stack.isClean(),15,'ordinary imported project save')
                from .studio_project import load_project
                saved=load_project(out/'fixture.2byteproj')
                cue=next(c for c in saved.cues if c.id=='audit-ai')
                check('saved project preserves complete source',theme_hash(saved.style_recipes[cue.style_id]['webTheme'])==theme_hash(chosen))
                if config.get('replacement_text'):check('saved project preserves edited caption text',cue.text==config['replacement_text'])
                check('reference archive untouched',archive.read_bytes()==original_bytes)
                write('expected-theme.json',dict(theme_hash=theme_hash(chosen),name=chosen['name'],id=chosen['id'],
                    selected_id='',library_ids=matches,request_id=drafts.current.request_id))
                state('saved-before-close');result['passed']=True
                return

            check('configured model retained by actual provider registry', selection.model==config['model'])
            check('configured service retained by actual provider registry', selection.service==config['service'])
            page._show_context_panel()
            page.context_drawer.setCurrentIndex(0)
            page.ai_prompt.setPlainText(config['prompt'])
            if config.get('retry_saved_candidate'):
                def restore_cards():
                    from .saved_theme_tasks import SavedThemeTasksDialog
                    dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,SavedThemeTasksDialog) and w.isVisible())
                    button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='查看已保存成果')
                    QTest.mouseClick(button,Qt.LeftButton)
                QTimer.singleShot(300,restore_cards)
                click(page.ai_resume_saved_button,'view saved provider directions')
                drafts=page._theme_drafts()
                wait(lambda:getattr(drafts,'_concept_dialog',None) is not None and drafts._concept_dialog.isVisible(),
                     15,'restored direction cards')
                concepts=drafts.design['concepts']
                dialog=drafts._concept_dialog
                index=next(i for i,c in enumerate(concepts) if c['id']==config['retry_saved_candidate'])
                QTest.mouseClick(dialog.candidate_list.viewport(),Qt.LeftButton,pos=dialog.candidate_list.visualItemRect(dialog.candidate_list.item(index)).center())
                check('saved retry target is selected',dialog.current_concept()['id']==config['retry_saved_candidate'])
                clicked=time.monotonic()
                click(dialog.primary,'retry only saved candidate '+config['retry_saved_candidate'],panel=False)
                result['recovery_click_feedback']=dict(wall_seconds=time.monotonic()-clicked,text=dialog.action_feedback.text())
                attempts=[json.loads(p.read_text('utf8')) for p in (drafts.root/'candidate-actions').glob('*.json')]
                check('recovery click has an accepted task receipt',any(a['events'][0]['status']=='accepted' for a in attempts))
            elif config.get('resume_ledger'):
                QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
                def choose_saved():
                    dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QFileDialog) and w.isVisible())
                    field=dialog.findChild(QLineEdit,'fileNameEdit')
                    clipboard=QApplication.clipboard();old=clipboard.text();clipboard.setText(config['resume_ledger'])
                    QTest.mouseClick(field,Qt.LeftButton);QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
                    QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier);clipboard.setText(old);QTest.keyClick(field,Qt.Key_Return)
                def open_saved_file():
                    from .saved_theme_tasks import SavedThemeTasksDialog
                    dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,SavedThemeTasksDialog) and w.isVisible())
                    button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='从其他草稿记录继续…')
                    QTimer.singleShot(200,choose_saved);QTest.mouseClick(button,Qt.LeftButton)
                QTimer.singleShot(300,open_saved_file)
                click(page.ai_resume_saved_button,'continue saved provider response')
            else:click(page.ai_generate, 'generate three directions')
            drafts = page._theme_drafts()
            check('ordinary generation created real provider worker', page._ai_request_active and drafts.phase=='PROVIDER')
            result['request_id'] = drafts.current.request_id
            state('generating')
            wait(lambda: drafts.phase in {'VISUAL_REVIEW', 'CHOOSING', 'FAILED', 'CANCELLED'},
                 config['review_timeout_seconds'], 'real provider and candidate previews')
            result['first_candidate_checkpoint_seconds']=round(time.monotonic()-started,3)
            if drafts.generation_running:
                state('partial-candidates')
                wait(lambda:not drafts.generation_running,config['review_timeout_seconds'],'remaining independent candidates')
            if drafts.phase in {'FAILED', 'CANCELLED'}:
                raise AssertionError('Real provider flow failed: '+drafts.category+' '+drafts.error)
            wait(lambda: not any(t.name=='theme-direction-previews' and t.is_alive()
                                 for t in threading.enumerate()), 15, 'candidate renderer shutdown')
            check('candidate preview worker completed renderer shutdown', True)
            concepts = drafts.design.get('concepts', [])
            expected_count=int(config.get('expected_candidates',3))
            check('authorized number of authored provider candidates', len(concepts)==expected_count and all(c.get('creative_version') for c in concepts))
            check('candidates keep distinct stable ids', len({c.get('id') for c in concepts})==expected_count)
            if config.get('recover_candidate'):
                dialog=drafts._concept_dialog
                dialog.grab().save(str(out/'before-recovery-cards.png'))
                index=next(i for i,c in enumerate(concepts) if c['id']==config['recover_candidate'])
                QTest.mouseClick(dialog.candidate_list.viewport(),Qt.LeftButton,pos=dialog.candidate_list.visualItemRect(dialog.candidate_list.item(index)).center())
                prior_operation=drafts.operation
                click(dialog.primary,'continue failed direction in app',panel=False)
                wait(lambda:drafts.operation!=prior_operation and drafts.phase in {'VISUAL_REVIEW','CHOOSING','FAILED','CANCELLED'},
                     config['review_timeout_seconds'],'explicit recovery preview')
                wait(lambda:not drafts.generation_running,config['review_timeout_seconds'],'explicit recovery complete')
                concepts=drafts.design.get('concepts',[])
                check('explicit app recovery produced previewable candidate',any(c['id']==config['recover_candidate'] and c.get('motion_preview') and c.get('technical_status')!='failed' for c in concepts))
            if config.get('rebuild_preview'):
                dialog=drafts._concept_dialog;menu=dialog.more.menu()
                action=next(a for a in menu.actions() if a.text()=='仅重建预览')
                QTimer.singleShot(150,lambda:QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center()))
                click(dialog.more,'rebuild preview without provider',panel=False)
                wait(lambda:drafts.phase in {'VISUAL_REVIEW','CHOOSING','FAILED','CANCELLED'},config['review_timeout_seconds'],'local preview rebuild')
                concepts=drafts.design.get('concepts',[])
                check('local preview rebuild retained complete source',bool(concepts and concepts[0].get('motion_preview')))
            if config.get('redo_candidate'):
                from PySide6.QtWidgets import QInputDialog,QPlainTextEdit,QDialogButtonBox
                original_ids=[c['id'] for c in concepts]
                index=original_ids.index(config['redo_candidate'])
                dialog=drafts._concept_dialog
                dialog.grab().save(str(out/'before-redo-cards.png'))
                prior_operation=drafts.operation
                def enter_feedback():
                    prompt=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QInputDialog) and w.isVisible())
                    field=prompt.findChild(QPlainTextEdit)
                    check('normal redo feedback editor available',field is not None)
                    old=QApplication.clipboard().text();QApplication.clipboard().setText(config['redo_feedback'])
                    QTest.mouseClick(field,Qt.LeftButton);QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier);QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier)
                    QApplication.clipboard().setText(old)
                    QTest.mouseClick(prompt.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok),Qt.LeftButton)
                QTimer.singleShot(300,enter_feedback)
                QTest.mouseClick(dialog.candidate_list.viewport(),Qt.LeftButton,pos=dialog.candidate_list.visualItemRect(dialog.candidate_list.item(index)).center())
                menu=dialog.more.menu();action=next(a for a in menu.actions() if a.text()=='完整重做该方向…')
                QTimer.singleShot(150,lambda:QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center()))
                click(dialog.more,'redo this art direction',panel=False)
                wait(lambda:drafts.operation!=prior_operation and drafts.phase in {'VISUAL_REVIEW','CHOOSING','FAILED','CANCELLED'},
                     config['review_timeout_seconds'],'new art direction and actual render')
                if drafts.phase in {'FAILED','CANCELLED'}:raise AssertionError('Actual redo failed: '+drafts.error)
                wait(lambda:not any(t.name=='theme-direction-previews' and t.is_alive() for t in threading.enumerate()),15,'redo render shutdown')
                concepts=drafts.design['concepts']
                check('redo retains stable candidate identities',[c['id'] for c in concepts]==original_ids)
                result['full_redo']=dict(candidate_id=config['redo_candidate'],feedback=config['redo_feedback'],operation=drafts.operation)
            from .caption_creative_pipeline import ThemeLedger, digest, canonical
            manifest = dict(request_id=drafts.current.request_id, provider=result['provider'], candidates=[])
            for concept in concepts:
                ledger = ThemeLedger.open(concept['ledger_path'])
                if concept.get('technical_status')=='failed':
                    manifest['candidates'].append(dict(id=concept['id'],name=concept['name'],ledger_path=concept['ledger_path'],
                        technical_status='failed',technical_errors=concept.get('technical_errors',[]),frames=[]))
                    continue
                row = next(c for c in ledger.value['candidates'] if c['id']==concept['id'])
                frames = row.get('rendered_previews', [])
                check('candidate '+concept['id']+' has five real preview files', len(frames)>=5 and all(
                    Path(f['path']).is_file() and digest(Path(f['path']).read_bytes())==f['sha256'] for f in frames))
                check('candidate '+concept['id']+' has nonempty name', bool(concept['name'].strip()))
                original = ledger.value.get('raw_response', {})
                check('candidate '+concept['id']+' has actual provider response provenance',
                      bool(original.get('sha256') and original.get('provider') and Path(original.get('path', '')).is_file()))
                check('candidate '+concept['id']+' response bytes match recorded provenance',
                      digest(Path(original['path']).read_bytes())==original['sha256'])
                check('candidate '+concept['id']+' preserves requested provider and model',
                      original.get('provider')==selection.provider and original.get('model')==selection.model)
                manifest['candidates'].append(dict(id=concept['id'], name=concept['name'], ledger_path=concept['ledger_path'],
                    source_hash=row['generated_source_hash'], preview_hash=row['rendered_preview_hash'], frames=frames,
                    response_provider=original.get('provider'), response_model=original.get('model')))
            manifest['manifest_hash'] = digest(canonical(manifest))
            manifest['review_instructions'] = ('Inspect every candidate image before writing review.json with manifest_hash, selected_id, '
                'and candidates: [{id, pixels_inspected: true, reviewer, notes, accepted, blocking}]. '
                'Record concrete observations. Scores are optional and never an adoption threshold. '
                'Aesthetic concerns do not imply blocking; a rejected design must not be marked accepted.')
            write('review-needed.json', manifest)
            concept_dialog=getattr(drafts,'_concept_dialog',None)
            if concept_dialog is not None:concept_dialog.grab().save(str(out/'direction-cards.png'))
            state('awaiting-actual-visual-review')
            wait(lambda: (out/'review.json').is_file(), config['review_timeout_seconds'], 'actual visual review file')
            review = json.loads((out/'review.json').read_text('utf8'))
            check('review binds this exact preview manifest', review.get('manifest_hash')==manifest['manifest_hash'])
            rows = review.get('candidates', [])
            check('review covers each candidate exactly once', len(rows)==expected_count and {r.get('id') for r in rows}=={c['id'] for c in concepts})
            for evidence in manifest['candidates']:
                inspected = next(r for r in rows if r['id']==evidence['id'])
                if evidence.get('technical_status')=='failed':
                    check('failed technical candidate cannot be accepted '+evidence['id'],inspected.get('accepted') is False)
                    continue
                check('review has named reviewer and observations '+evidence['id'],
                      inspected.get('pixels_inspected') is True and bool(str(inspected.get('reviewer', '')).strip())
                      and bool(str(inspected.get('notes', '')).strip()))
                ledger = ThemeLedger.open(evidence['ledger_path'])
                ledger.record_preview(evidence['id'], [f['path'] for f in evidence['frames']], review=inspected)
            if not review.get('selected_id'):
                result['visual_result'] = 'reject_all'
                result['new_generation_returned'] = True
                result['cache_used'] = bool(config.get('resume_ledger'))
                if drafts.phase=='VISUAL_REVIEW':
                    click(page.ai_retry_render_button, 'check rejected visual review')
                state('visual-rejected')
                raise AssertionError('All actual candidates rejected by visual review; no apply/save/reopen acceptance')
            check('review selects one actual candidate', review.get('selected_id') in {c['id'] for c in concepts})
            if drafts.phase=='VISUAL_REVIEW':
                click(page.ai_retry_render_button, 'check actual visual review')
            wait(lambda: getattr(drafts, '_concept_dialog', None) is not None and drafts._concept_dialog.isVisible(),
                 5, 'ordinary three-direction dialog')
            dialog = drafts._concept_dialog
            dialog.grab().save(str(out/'candidate-subject-dialog.png'))
            state('three-directions')
            chosen_index = next(i for i, c in enumerate(concepts) if c['id']==review['selected_id'])
            QTest.mouseClick(dialog.candidate_list.viewport(),Qt.LeftButton,pos=dialog.candidate_list.visualItemRect(dialog.candidate_list.item(chosen_index)).center())
            if concepts[chosen_index].get('motion_preview'):
                from .theme_concept_dialog import MotionPreviewDialog
                from .theme_concept_dialog import FittedPicture
                subject=dialog.findChild(FittedPicture,'subtitleSubjectPreview')
                check('candidate defaults to subtitle subject pixels',subject is not None and not subject.original.isNull())
                selected_motion=concepts[chosen_index]['motion_preview']
                check('default movie contains only subtitle subject',selected_motion.get('presentation')=='subject' and selected_motion.get('background')=='neutral')
                dialog.enlarge()
                movie=dialog.findChild(MotionPreviewDialog)
                check('optional enlarged motion dialog opened',movie is not None and movie.isVisible())
                seen=[];movie.movie.frameChanged.connect(seen.append)
                movie_started=time.monotonic()
                wait(lambda:max(seen,default=-1)>=movie.movie.frameCount()-1,9,'normal-speed movie reaches final frame')
                check('direction movie advances actual frames',len(set(seen))>2)
                result['complete_preview_playback']=dict(frame_count=movie.movie.frameCount(),observed_frames=seen,
                    normal_speed=movie.movie.speed()==100,wall_seconds=time.monotonic()-movie_started)
                check('complete direction movie reaches its exit',max(seen,default=-1)>=movie.movie.frameCount()-2)
                movie.grab().save(str(out/'subject-motion-dialog.png'))
                switches=[b for b in movie.findChildren(QPushButton) if b.text() in ('查看视频叠加','查看完整画面占比')]
                if switches:
                    click(switches[0],'switch to secondary context preview',panel=False);pump(.8)
                    movie.grab().save(str(out/'context-motion-dialog.png'))
                    click(switches[0],'return to subject preview',panel=False)
                native_frame('direction-motion-playing')
                movie.close();pump(.1)
            choose_buttons = [b for b in dialog.findChildren(QPushButton) if b.text()=='采用这个方向']
            check('workbench has one fixed choose button for selected candidate', len(choose_buttons)==1)
            click(dialog.primary, 'choose reviewed direction', panel=False)
            wait(lambda: drafts.phase in {'READY', 'APPLIED', 'FAILED', 'CANCELLED'},
                 config['review_timeout_seconds'], 'selected source renders via ordinary worker')
            if drafts.phase not in {'READY', 'APPLIED'}:
                raise AssertionError('Selected-theme flow failed: '+drafts.category+' '+drafts.error)
            check('selected theme is actual AI source', drafts.output_source=='ai')
            check('current immutable theme has real render evidence', drafts.is_valid())
            check('selected id survived completion', drafts.design.get('selected_concept_id')==review['selected_id'])
            chosen = drafts.current.theme
            check('completed theme has nonempty name and id', bool(chosen.get('name')) and bool(chosen.get('id')))
            state('ready')
            previous_operation=drafts.operation;previous_generation=drafts.current.generation
            click(page.ai_retry_theme_code_button,'retry theme code from retained chosen candidate')
            wait(lambda: drafts.operation!=previous_operation and drafts.phase in {'READY','FAILED'},
                 100,'ordinary theme-code retry with new runtime evidence')
            check('theme-code retry completes without stale candidate',drafts.phase=='READY'
                and theme_hash(drafts.current.theme)==theme_hash(chosen)
                and drafts.current.generation>previous_generation and drafts.is_valid())
            result['theme_code_retry']=dict(previous_operation=previous_operation,new_operation=drafts.operation,
                previous_generation=previous_generation,new_generation=drafts.current.generation,
                retained_theme_hash=theme_hash(chosen),evidence=drafts.evidence)
            click(page.ai_apply_button, 'apply reviewed theme')
            check('ordinary apply button stores exact validated theme', theme_hash(theme_in_project())==theme_hash(chosen))
            page._seek(1.5)
            final_html_frame('applied')
            state('applied')
            play_current_theme('generated')
            click(page.ai_save_style_button, 'save theme to library')
            matches = [k for k, t in library_themes().items() if theme_hash(t)==theme_hash(chosen)]
            check('ordinary save style button stores exact theme', len(matches)==1)
            edit_and_restore(chosen)
            click(page.save_button, 'save project', panel=False)
            wait(lambda: page.undo_stack.isClean(), 15, 'ordinary project save')
            from .studio_project import load_project
            saved = load_project(out/'fixture.2byteproj')
            cue = next(c for c in saved.cues if c.id=='audit-ai')
            check('saved project bytes contain exact chosen theme', theme_hash(saved.style_recipes[cue.style_id]['webTheme'])==theme_hash(chosen))
            if config.get('replacement_text'):check('saved project preserves edited caption text',cue.text==config['replacement_text'])
            write('expected-theme.json', dict(theme_hash=theme_hash(chosen), name=chosen['name'], id=chosen['id'],
                selected_id=review['selected_id'], library_ids=matches, request_id=drafts.current.request_id))
            state('saved-before-close')
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            draft = getattr(page, '_theme_draft_coordinator', None)
            if draft is not None:
                result['failure'] = dict(category=draft.category, error=draft.error,
                    phase=draft.phase, request_id=draft.current.request_id if draft.current else '')
            try:
                page._scroll_ai_panel_into_view(page.ai_preview)
                pump(.15)
                state('failed')
            except Exception:
                result['failure_capture_error'] = traceback.format_exc()
        finally:
            responsiveness.stop()
            result['gui_timer_ms']={}
            for phase_name in {p for p,_ in timer_samples}:
                values=sorted(v for p,v in timer_samples if p==phase_name)
                result['gui_timer_ms'][phase_name]=dict(samples=len(values),p95=values[int((len(values)-1)*.95)],
                    maximum=max(values),requested_interval=50,includes_audit_capture=True)
            result['completed'] = True
            result['elapsed_seconds'] = round(time.monotonic()-started, 3)
            write(phase+'-result.json', result)
            if page.video.controller:
                page.video.set_paused(True)
            page.undo_stack.setClean()
            # MainWindow's existing close_ready chain owns media, renderer and
            # application shutdown. Never quit QApplication ahead of it.
            QTimer.singleShot(150, window.close)
    QTimer.singleShot(400, run)
