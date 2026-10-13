# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in normal MainWindow audit; invoked only by the guarded acceptance hook.

The input project, added MOV, saves and exports belong to the isolated output.
No synthetic frames/inference or alternate renderer stand in for native GUI.
"""
from __future__ import annotations
import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback


def _sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def classify_export_invocation(argv):
    """Classify launched tools/package paths, never arbitrary output names."""
    argv=[str(arg) for arg in (argv or [])]
    executable=(argv[0] if argv else '').replace('\\','/').rstrip('/').rsplit('/',1)[-1].casefold()
    normalized=[arg.replace('\\','/').casefold() for arg in argv]
    runtime=executable in {'node','node.exe','bun','bun.exe','deno','deno.exe'}
    helper=executable in {'compositor','compositor.exe','remotion','remotion.exe'}
    package=any('/node_modules/@remotion/' in arg or '/node_modules/remotion/' in arg for arg in normalized)
    return dict(executable=executable,runtime=runtime,remotion_helper=helper,remotion_package=package,
        accepted=bool(argv) and executable in {'ffmpeg','ffmpeg.exe','ffprobe','ffprobe.exe'} and not package,
        naive_remotion_substring=any('remotion' in arg for arg in normalized))


def start(window, output):
    from PySide6.QtCore import QObject,QPoint,QRect,QTimer,Qt
    from PySide6.QtGui import QImage,QInputMethodEvent,QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QScrollArea,QPushButton,QToolButton,QColorDialog,QDialogButtonBox
    from . import blank_project_audit
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_project import load_project
    from .studio_media_pool import asset_by_id
    from .export_target_audit import active_main_encoding
    output=Path(output).resolve()
    inputs=json.loads((output/'input.json').read_text('utf8'))
    project_path=Path(inputs['project']).resolve()
    overlay=Path(inputs['overlay_mov']).resolve() if inputs.get('overlay_mov') else None
    if not project_path.is_relative_to(output) or not project_path.is_file():
        raise ValueError('Audit project must be its isolated copy')
    if inputs.get('mode','studio')=='studio' and (overlay is None or not overlay.is_relative_to(output) or not overlay.is_file()):
        raise ValueError('Transparent MOV must be copied into isolated output')

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page;self.ui=None
            self.started=time.monotonic();self.waiting=0.;self.deadline=self.started+120
            self.last_readiness_diagnostic=0.
            self.busy=False;self.result=dict(passed=False,checks=[],screenshots=[],exports=[],
                identity=load_build_identity().to_dict(),executable=sys.executable,pid=os.getpid(),
                entry='frozen' if getattr(sys,'frozen',False) else 'quick_start.main',
                actual_main_window=True,dpr=window.devicePixelRatioF(),inputs=inputs,
                scope='Actual normal UI media pool import/track/transform/save/reopen/export; retained completion replay separately identified',
                pixel_source='Native whole-window PrintWindow, not offscreen')
            self.input_hashes={str(project_path):_sha(project_path)}
            if overlay:self.input_hashes[str(overlay)]=_sha(overlay)
            self.steps=self.run();self.timer=QTimer(self);self.timer.timeout.connect(self.tick)
            self.write();self.timer.start(30)

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail));self.write()
            if not value:raise AssertionError(name+': '+str(detail))

        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    handler=getattr(self,'expected_modal_handler',None)
                    if handler is None or not handler(modal):
                        raise RuntimeError('Unexpected modal: '+modal.text()+' '+modal.informativeText())
                now=time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now>self.deadline:
                            self.readiness_diagnostic(force=True)
                            try:self.shot('timeout-normal-window')
                            except Exception as exc:self.result['timeout_capture_error']=str(exc)
                            raise TimeoutError('Unified normal GUI step timed out; see actual readiness_diagnostics and timeout-normal-window')
                        return
                elif now<self.waiting:return
                step=next(self.steps)
                wait,timeout=step if isinstance(step,tuple) else (step,120)
                self.waiting=wait if callable(wait) else time.monotonic()+float(wait)
                self.deadline=time.monotonic()+timeout
            except StopIteration:
                self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc();self.finish()
            finally:self.busy=False

        def ready(self):
            p=self.page
            value=bool(p.project and p._readiness.ready and not p._readiness.active and p._project_view_state=='open')
            if not value:
                self.readiness_diagnostic()
                error=(getattr(p._readiness,'profile',{}) or {}).get('error')
                if error:raise RuntimeError('Actual Studio readiness failed: '+str(error))
            return value

        def readiness_diagnostic(self,force=False):
            now=time.monotonic()
            if not force and now-self.last_readiness_diagnostic<5:return
            self.last_readiness_diagnostic=now
            p=self.page;r=getattr(p,'_readiness',None);video=getattr(p,'video',None)
            controller=getattr(video,'controller',None);audio=getattr(p,'audio_engine',None)
            try:audio_state=audio.telemetry_snapshot() if audio else None
            except Exception as exc:audio_state={'diagnostic_error':str(exc)}
            def visible(widget):return bool(widget and widget.isVisible())
            modal=QApplication.activeModalWidget()
            snapshot=dict(elapsed_seconds=round(now-self.started,3),
                project_present=p.project is not None,project_path=str(getattr(p,'project_path','') or ''),
                project_view_state=getattr(p,'_project_view_state',None),
                media_path=str(p.project.media.path) if p.project else None,
                media_exists=Path(p.project.media.path).is_file() if p.project and p.project.media.path else None,
                current_page_index=window.pages.currentIndex(),studio_is_current=window.pages.currentWidget() is p,
                window_visible=window.isVisible(),studio_visible=p.isVisible(),hub_visible=visible(getattr(p,'studio_empty',None)),
                readiness=dict(path=getattr(r,'path',None),active=getattr(r,'active',None),ready=getattr(r,'ready',None),
                    completed=sorted(getattr(r,'completed',set())),pending=[name for name in getattr(r,'TASKS',()) if name not in getattr(r,'completed',set())],
                    profile=copy.deepcopy(getattr(r,'profile',{})),hydrated=getattr(r,'hydrated',None),painted=getattr(r,'painted',None),
                    player_ready=getattr(r,'player_ready',None),label=r.label.text() if r else None,
                    overlay_visible=visible(getattr(r,'overlay',None)),retry_visible=visible(getattr(r,'retry',None))),
                player=dict(startup_state=getattr(video,'_startup_state',None),controller_present=controller is not None,
                    controller_running=getattr(controller,'running',None),preview_path=str(getattr(p,'_preview_path',None)),
                    video_visible=visible(video)),audio=audio_state,
                modal_type=type(modal).__name__ if modal else None)
            self.result.setdefault('readiness_diagnostics',[]).append(snapshot);self.write()

        def shot(self,name,widget=None):
            path=output/(name+'.png');_capture(widget or window,path);self.result['screenshots'].append(str(path));self.write()

        def visible(self,widget):
            ancestor=widget.parentWidget()
            while ancestor:
                if isinstance(ancestor,QScrollArea):ancestor.ensureWidgetVisible(widget,6,16)
                ancestor=ancestor.parentWidget()
            QApplication.processEvents()
            self.check('visible enabled control '+widget.objectName(),widget.isVisible() and widget.isEnabled())

        def click(self,widget):
            self.visible(widget);QTest.mouseClick(widget,Qt.MouseButton.LeftButton)

        def field(self,widget,text):
            self.visible(widget);widget.setFocus();QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(widget,str(text));QTest.keyClick(widget,Qt.Key_Tab)

        def combo(self,widget,value):
            self.visible(widget);index=widget.findData(value)
            self.check('actual combo data exists',index>=0,dict(control=widget.objectName(),value=value))
            widget.setFocus();QTest.keyClick(widget,Qt.Key_F4);QApplication.processEvents()
            view=widget.view();view.setFocus();QTest.keyClick(view,Qt.Key_Home)
            for _ in range(index):QTest.keyClick(view,Qt.Key_Down)
            QTest.keyClick(view,Qt.Key_Return);QApplication.processEvents()
            self.check('actual popup keyboard selects request',widget.currentData()==value,dict(request=value,actual=widget.currentData()))

        def caption_contract(self,project):
            return dict(cues=[asdict(c) for c in project.cues],speakers=[asdict(s) for s in project.speakers],
                styles=[asdict(s) for s in project.styles],recipes=copy.deepcopy(project.style_recipes),
                asr_evidence_sha256=hashlib.sha256(json.dumps(project.asr_evidence,ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest(),
                manual=copy.deepcopy(project.studio_state.get('manual_caption_text',{})))

        def overlay_clip(self,project=None):
            project=project or self.page.project
            for track in project.video_tracks:
                for clip in track.clips:
                    asset=asset_by_id(project,clip.asset_id)
                    if Path(asset.canonical_source).resolve()==overlay:return track,clip
            return None

        def decoder_ready(self):
            row=self.overlay_clip()
            if not row:return False
            player=self.page.video_compositor._players.get(row[1].id)
            return bool(player and getattr(player,'image',None) is not None and not player.image.isNull()
                and abs(int(getattr(player,'pts_ms',-9999))-1000)<=50)

        def seek(self,ms):
            # The normal timecode control commits only on ReturnPressed.
            widget=self.page.timecode_input;self.visible(widget);widget.setFocus()
            QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(widget,f'00:00:{ms//1000:02}.{ms%1000:03}')
            QTest.keyClick(widget,Qt.Key_Return)

        def save_reopen(self):
            self.click(self.page.save_button);yield .4
            saved=Path(self.page.project_path).resolve()
            self.check('saved project inside owned profile',saved.is_relative_to(output))
            loaded=load_project(saved);self.check('native text/speaker/manual style preserved on save',self.caption_contract(loaded)==self.original_caption)
            row=self.overlay_clip(loaded);self.check('actual added MOV and transform persisted',row is not None and abs(row[1].transform.scale_x-1.25)<.001 and abs(row[1].transform.scale_y-1.25)<.001)
            self.result['saved_project']=str(saved);self.result['saved_sha256']=_sha(saved)
            self.click(self.page.studio_back_button);yield .2
            self.check('normal hub opened',self.page.studio_empty.isVisible())
            original=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(str(saved),'2ByteASR project')
            try:self.click(self.page.project_import_button)
            finally:QFileDialog.getOpenFileName=original
            yield self.ready;yield .3
            self.check('reopened same saved MOV graph',self.overlay_clip() is not None and abs(self.overlay_clip()[1].transform.scale_x-1.25)<.001)
            self.check('caption/manual contract survived normal reopening',self.caption_contract(self.page.project)==self.original_caption)
            self.shot('studio-reopened')

        def manual_edit(self):
            from .studio_speaker_manager import SpeakerManagerDialog
            from .studio_edit_sequence import source_cue_id_of
            p=self.page;before=self.caption_contract(p.project)
            editable_speakers={speaker.id for speaker in p.project.speakers}
            row=next((i for i in range(p.cue_model.rowCount()) if p.cue_model.cue_at(i).text.strip()
                and p.cue_model.cue_at(i).speaker_id in editable_speakers
                and p.cue_model.cue_at(i).speaker_id!='SPEAKER_UNCONFIRMED'),None)
            self.check('actual project contains editable nonempty cue',row is not None)
            cue=p.cue_model.cue_at(row);view_cue_id=cue.id;cue_id=source_cue_id_of(cue.id);speaker_id=cue.speaker_id
            index=p.cue_model.index(row,0);p.cue_table.scrollTo(index);yield .2
            QTest.mouseClick(p.cue_table.viewport(),Qt.LeftButton,pos=p.cue_table.visualRect(index).center());yield .2
            self.check('normal cue table mouse selected requested cue',source_cue_id_of(p.selected_cue_id)==cue_id)
            # Import/clip transforms leave the tool drawer on its video tab.
            # Locate the production editor's actual ancestor page, then expose
            # its existing disclosure through visible normal controls.
            if not p.context_drawer.isVisible():self.click(p.context_expand_button);yield .15
            editor_tab=next((i for i in range(p.context_drawer.count()) if p.context_drawer.widget(i).isAncestorOf(p.cue_text)),None)
            self.check('real cue text belongs to an existing context page',editor_tab is not None)
            tabs=p.context_drawer.tabBar();self.visible(tabs)
            QTest.mouseClick(tabs,Qt.LeftButton,pos=tabs.tabRect(editor_tab).center());yield .2
            if not p.current_cue_section_button.isChecked():self.click(p.current_cue_section_button);yield .15
            edited=cue.text+' [本轮人工校验]';self.visible(p.cue_text);p.cue_text.setFocus()
            QTest.keyClick(p.cue_text,Qt.Key_A,Qt.ControlModifier)
            ime=QInputMethodEvent('',[]);ime.setCommitString(edited);QApplication.sendEvent(p.cue_text,ime)
            p.context_drawer.tabBar().setFocus();yield .3
            source_cue=next(c for c in p.project.cues if c.id==cue_id)
            self.check('normal Chinese IME edit committed and protected',source_cue.text==edited and p.project.studio_state.get('manual_caption_text',{}).get(cue_id)==edited,
                dict(expected=edited,actual=source_cue.text,editor=p.cue_text.toPlainText(),manual=p.project.studio_state.get('manual_caption_text',{}).get(cue_id),source_cue_id=cue_id,selected=p.selected_cue_id))
            self.shot('actual-manual-Chinese-text')
            if p.speaker_manager_button.isVisible():
                QTimer.singleShot(0,lambda:self.click(p.speaker_manager_button))
            else:
                overflow=next(b for b in p.findChildren(QToolButton) if b.isVisible() and b.menu() and b.toolTip()=='更多工作区操作')
                QTimer.singleShot(0,lambda:QTest.mouseClick(overflow,Qt.LeftButton));yield lambda:overflow.menu().isVisible()
                menu=overflow.menu();action=next(a for a in menu.actions() if a.text()==p.speaker_manager_button.text())
                QTimer.singleShot(0,lambda:QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center()))
            yield lambda:isinstance(QApplication.activeModalWidget(),SpeakerManagerDialog)
            manager=QApplication.activeModalWidget();yield .15
            manager_tab=next((i for i in range(manager.tabs.count()) if manager.tabs.widget(i).isAncestorOf(manager.name_edit)),None)
            self.check('speaker editor belongs to an actual manager tab',manager_tab is not None)
            QTest.mouseClick(manager.tabs.tabBar(),Qt.LeftButton,pos=manager.tabs.tabBar().tabRect(manager_tab).center());yield .15
            target=next(i for i in range(manager.table.rowCount()) if manager.table.item(i,1).data(Qt.UserRole)==speaker_id)
            item=manager.table.item(target,2);manager.table.scrollToItem(item);yield .1
            QTest.mouseClick(manager.table.viewport(),Qt.LeftButton,pos=manager.table.visualItemRect(item).center());yield .15
            self.field(manager.name_edit,'QA Display Label');QTest.keyClick(manager.name_edit,Qt.Key_Return);yield .15
            self.check('manual name updates stable ID, without acoustic identity claim',next(s for s in p.project.speakers if s.id==speaker_id).name=='QA Display Label')
            QTimer.singleShot(0,lambda:self.click(manager.color_button));yield lambda:isinstance(QApplication.activeModalWidget(),QColorDialog)
            picker=QApplication.activeModalWidget();picker.setCurrentColor(QColor('#e84055'));yield .1
            box=picker.findChild(QDialogButtonBox);self.check('normal color picker has real OK control',box is not None)
            self.shot('actual-speaker-color-picker',picker);self.click(box.button(QDialogButtonBox.Ok));yield .15
            self.click(manager.apply_button);yield .15
            self.check('real Apply committed speaker color',next(s for s in p.project.speakers if s.id==speaker_id).color=='#e84055')
            self.shot('actual-speaker-name-color',manager)
            close=next(b for b in manager.findChildren(QPushButton) if b.text()=='完成');self.click(close);yield .3
            # Select the cue again because a native speaker refresh rebuilds table rows.
            row=p.cue_model.row_for_cue_id(view_cue_id);self.check('edited cue survives real table refresh',row>=0)
            index=p.cue_model.index(row,0);p.cue_table.scrollTo(index);yield .1
            QTest.mouseClick(p.cue_table.viewport(),Qt.LeftButton,pos=p.cue_table.visualRect(index).center());yield .2
            self.seek(source_cue.start_ms+min(100,max(0,(source_cue.end_ms-source_cue.start_ms)//2)));yield .3
            if not p.context_drawer.isVisible():self.click(p.context_expand_button);yield .15
            bar=p.context_drawer.tabBar();self.visible(bar);QTest.mouseClick(bar,Qt.LeftButton,pos=bar.tabRect(1).center());yield .2
            section=p.position_edit_button.parentWidget()
            while section and section.objectName()!='styleSection':section=section.parentWidget()
            self.check('position control belongs to actual style section',section is not None)
            if not p.position_edit_button.isVisible():
                header=next(b for b in section.findChildren(QToolButton) if b.objectName()=='styleSectionHeader')
                self.click(header);yield .15
            self.visible(p.position_edit_button)
            if not p.position_edit_button.isChecked():self.click(p.position_edit_button)
            yield lambda:p.position_overlay.isVisible();yield .3
            edit_overlay=p.position_overlay;rect=edit_overlay._subtitle_rect();start_point=rect.center().toPoint();end_point=start_point+QPoint(20,-12)
            self.check('actual subtitle drag target lies in visible canvas',edit_overlay.rect().contains(start_point) and edit_overlay.rect().contains(end_point),dict(rect=[rect.x(),rect.y(),rect.width(),rect.height()],canvas=[edit_overlay.width(),edit_overlay.height()]))
            old_transform=copy.deepcopy(source_cue.transform)
            QTest.mousePress(edit_overlay,Qt.LeftButton,pos=start_point);QTest.mouseMove(edit_overlay,end_point,100);QTest.mouseRelease(edit_overlay,Qt.LeftButton,pos=end_point);yield .3
            source_cue=next(c for c in p.project.cues if c.id==cue_id)
            self.check('actual canvas drag committed changed subtitle location',source_cue.transform!=old_transform and all(key in source_cue.transform for key in ('position_x','position_y')),dict(before=old_transform,after=source_cue.transform))
            self.shot('actual-manual-subtitle-location')
            after=self.caption_contract(p.project);expected=copy.deepcopy(before)
            expected_cue=next(c for c in expected['cues'] if c['id']==cue_id);expected_cue['text']=edited
            for key in ('position_x','position_y'):expected_cue['transform'][key]=source_cue.transform[key]
            expected_speaker=next(s for s in expected['speakers'] if s['id']==speaker_id)
            expected_speaker.update(name='QA Display Label',color='#e84055');expected['manual'][cue_id]=edited
            self.check('manual actions changed only intended text/name/color/position fields',after==expected,dict(cue_id=cue_id,speaker_id=speaker_id,before=before,after=after,expected=expected))
            self.result['manual_edit']=dict(cue_id=cue_id,speaker_id=speaker_id,display_label_only=True,before=before,after=after,original_text_and_timing_and_evidence_preserved=True)
            self.original_caption=expected
            if p.position_edit_button.isChecked():self.click(p.position_edit_button)
            yield from self.save_reopen()

        def subtitle_exports(self):
            from .studio_subtitle_export import verify_subtitle_artifact,_export_view_cues
            ui=self.ui;destination=output/'subtitle-exports';destination.mkdir(exist_ok=True)
            self.field(ui.filename,'unified-manual-speech');self.field(ui.filename_prefix.lineEdit(),'');self.field(ui.filename_suffix.lineEdit(),'')
            for name,control in ui.subtitle_format_checks.items():
                if control.isChecked()!=(name in {'srt','json'}):self.click(control)
            self.click(ui.subtitle_speaker_modes['both']);self.click(ui.subtitle_destination_modes['custom'])
            old=QFileDialog.getExistingDirectory;QFileDialog.getExistingDirectory=lambda *a,**k:str(destination)
            try:self.click(ui.subtitle_custom_choose)
            finally:QFileDialog.getExistingDirectory=old
            self.click(ui.subtitle_export_button);yield .2
            artifacts=ui._last_subtitle_artifacts
            visible=self.page.project.visible_cues();ids=set(c.speaker_id for c in visible)
            self.check('normal export writes combined and each actual speaker in SRT/JSON',set((a.speaker_id,a.format) for a in artifacts)=={(s,f) for s in ids|{''} for f in {'srt','json'}},dict(actual=[asdict(a) for a in artifacts],status=ui.subtitle_export_status.text()))
            rows=[]
            for artifact in artifacts:
                self.check('subtitle artifact published only under owned output',artifact.path.resolve().is_relative_to(destination))
                scoped=copy.deepcopy(self.page.project);scoped.cues=copy.deepcopy([c for c in visible if not artifact.speaker_id or c.speaker_id==artifact.speaker_id])
                scoped.cues=copy.deepcopy(_export_view_cues(scoped))
                verification=verify_subtitle_artifact(artifact,scoped)
                self.check('actual parser readback preserves text/timing/identity '+artifact.path.name,verification.valid,asdict(verification))
                content=artifact.path.read_text('utf8');rows.append(dict(artifact=asdict(artifact),sha256=_sha(artifact.path),verification=asdict(verification),content=content))
            self.result['subtitle_exports']=dict(artifacts=rows,actual_visible_speaker_ids=sorted(ids),acoustic_identity_verified=False)
            self.check('subtitle export leaves manual project contract intact',self.caption_contract(self.page.project)==self.original_caption)
            self.shot('actual-per-speaker-SRT-JSON-export');self.write()

        def export_settings(self,name,milliseconds):
            ui=self.ui;self.field(ui.directory,str(output/'exports'));self.field(ui.filename,name)
            self.field(ui.filename_prefix.lineEdit(),'');self.field(ui.filename_suffix.lineEdit(),'')
            self.combo(ui.codec,'h264')
            if not ui.advanced_button.isChecked():self.click(ui.advanced_button)
            self.combo(ui.encoder,'libx264');self.combo(ui.fps,60.)
            # QVariant converts this production tuple to a list in PySide6.
            # Select its actual itemData while preserving exact dimensions.
            resolutions=[dict(text=ui.resolution.itemText(i),data=ui.resolution.itemData(i),
                type=type(ui.resolution.itemData(i)).__name__) for i in range(ui.resolution.count())]
            match=next((row['data'] for row in resolutions if isinstance(row['data'],(list,tuple)) and tuple(row['data'])==(1920,1080)),None)
            self.check('actual production full-HD resolution option exists',match is not None,resolutions)
            self.combo(ui.resolution,match)
            self.check('actual selected dimensions remain 1920x1080',tuple(ui.resolution.currentData())==(1920,1080))
            self.combo(ui.audio,'none')
            self.combo(ui.rate_control,'crf')
            for field,ms in zip(ui.project_range_bar.fields,(0,milliseconds)):
                hours,remain=divmod(ms,3600000);minutes,remain=divmod(remain,60000);seconds,remain=divmod(remain,1000)
                self.field(field,f'{hours:02}:{minutes:02}:{seconds:02}.{remain:03}')
            self.combo(ui.export_range,'in_out')
            self.check('native frozen range reflects requested video portion',abs(ui._range_seconds()[2]-milliseconds/1000)<.001)

        def process_records(self,job):
            directory=Path(job.export_context.get('diagnostics_path') or '')
            path=directory/'processes.jsonl'
            if not path.is_file():raise RuntimeError('Actual export process diagnostics missing')
            records=[json.loads(line) for line in path.read_text('utf8').splitlines() if line]
            started=[r.get('payload',{}) for r in records if r.get('event')=='process_started']
            classified=[dict(payload=r,classification=classify_export_invocation(r.get('argv'))) for r in started]
            self.check('transparent MOV export launches only independently audited FFmpeg/FFprobe tools',bool(started) and all(r['classification']['accepted'] for r in classified),classified)
            return dict(directory=str(directory),records=records,invocation_classification=classified,
                legacy_naive_false_positive=any(r['classification']['accepted'] and r['classification']['naive_remotion_substring'] for r in classified))

        def export(self):
            self.click(self.page.studio_render_button);yield lambda:self.page.export_workspace is not None
            self.ui=self.page.export_workspace;yield .4
            yield from self.subtitle_exports()
            ms=int(inputs.get('export_ms',2117));self.export_settings('non-remotion-studio-composed',ms)
            self.shot('actual-export-settings');self.click(self.ui.export_button);yield .05
            self.check('actual production export worker began',self.ui._last_job is not None)
            job=self.ui._last_job;yield (lambda:not self.ui._running,int(inputs.get('job_timeout',600)));yield .3
            self.check('real export completed through success page',self.ui.pages.currentWidget()==self.ui.success_page,self.ui.failure_reason.text())
            target=Path(job.output_path);self.check('actual video file published',target.is_file() and target.stat().st_size>0,str(target))
            receipt=copy.deepcopy(job.completion_metadata);stream=next((s for s in receipt.get('streams',[]) if s.get('codec_type')=='video'),{})
            self.check('actual composed export dimensions/rate/frame count',stream.get('width')==1920 and stream.get('height')==1080 and stream.get('avg_frame_rate')=='60/1' and int(stream.get('nb_frames',0))==math.ceil(ms/1000*60-1e-8),stream)
            self.result['exports'].append(dict(path=str(target),sha256=_sha(target),receipt=receipt,actual_processes=self.process_records(job)))
            self.shot('actual-export-success');self.ui._return_to_settings();yield .2
            if inputs.get('cancel',True):
                self.export_settings('non-remotion-cancelled',int(inputs.get('cancel_ms',12000)))
                self.click(self.ui.export_button);yield .01
                def encoding():
                    current=self.ui._last_job
                    return bool(self.ui._running and current and active_main_encoding(current.export_context.get('diagnostics_path')))
                yield (encoding,int(inputs.get('job_timeout',600)))
                job=self.ui._last_job;active=active_main_encoding(job.export_context.get('diagnostics_path'))
                self.check('cancellation observes new active final encode',active is not None,active)
                self.result['cancellation']=dict(actual_started_process=active,context=copy.deepcopy(job.export_context))
                cancel=next((b for b in self.ui.exporting_page.findChildren(QPushButton) if '取消' in b.text()),None)
                self.check('actual cancel button exists',cancel is not None)
                self.shot('actual-running-encode-before-cancel');self.click(cancel)
                yield (lambda:not self.ui._running,120);yield .2
                self.check('cancelled actual composition not published',not Path(job.output_path).exists(),job.output_path)
                self.result['cancellation']['actual_processes']=self.process_records(job)
                self.shot('actual-cancel-result')
            self.check('export preserved original caption/manual fields',self.caption_contract(self.page.project)==self.original_caption)

        def completion(self):
            from .service import MediaResult,QueueResult
            report_path=Path(inputs['completion_report']).resolve()
            if not report_path.is_relative_to(output):raise ValueError('Retained completion report must be its isolated copy')
            report=json.loads(report_path.read_text('utf8'))
            item=MediaResult(media_path=report['media']['path'],status=report['status'],project_path=str(project_path),report_json_path=str(report_path),elapsed_seconds=float(report['result'].get('elapsed_seconds',0)))
            window._handle_result(QueueResult((item,),item.elapsed_seconds))
            dialog=getattr(window,'_completion_dialog',None)
            if dialog and dialog.isVisible():self.click(dialog.confirm_button)
            yield .4
            viewport=window.pages.widget(2).viewport();content=window.result_content
            def box(widget):
                point=widget.mapTo(viewport,QPoint());return QRect(point.x(),point.y(),widget.width(),widget.height())
            rows=[]
            from .completion_real_audit import completion_panel_geometry
            from .completion_widgets import CompletionInfoPanel
            for header in (window.result_files_toggle,window.result_log_toggle):
                window.pages.widget(2).ensureWidgetVisible(header);yield .15
                header_rect=box(header);content_rect=box(content);title,arrow=(r.toRect() for r in header.content_rects())
                text=header.fontMetrics().boundingRect(title,int(Qt.AlignLeft|Qt.AlignVCenter|Qt.TextSingleLine),header.text())
                row=dict(text=header.text(),header=[header_rect.x(),header_rect.y(),header_rect.width(),header_rect.height()],content=[content_rect.x(),content_rect.y(),content_rect.width(),content_rect.height()],legacy_full_row_contract=abs(header_rect.x()-content_rect.x())<=1 and abs(header_rect.width()-content_rect.width())<=1,visible=header.isVisible(),enabled=header.isEnabled(),title_fits=text.width()<=title.width() and text.height()<=title.height(),arrow_inside=header.rect().contains(arrow))
                panel=window.result_files_panel if header is window.result_files_toggle else window.result_log_panel
                panel_rect=box(panel);margins=panel.layout_box.contentsMargins()
                row.update(completion_panel_geometry([panel_rect.x(),panel_rect.y(),panel_rect.width(),panel_rect.height()],
                    row['header'],row['content'],[margins.left(),margins.top(),margins.right(),margins.bottom()]))
                row['production_panel_owns_header']=isinstance(panel,CompletionInfoPanel) and header.parentWidget() is panel
                row['header_height_contract']=46<=header.height()<=54
                rows.append(row);self.check('completion native header visible/text fits/arrow inside',row['visible'] and row['enabled'] and row['title_fits'] and row['arrow_inside'],row)
                self.click(header);yield .2
                body=window.result_files if header is window.result_files_toggle else window.result_console
                self.check('completion disclosure actually expands corresponding body',body.isVisible());self.shot('completion-expanded-'+str(len(rows)));self.click(header);yield .15
            self.result['completion_geometry']=dict(retained_actual_report=True,new_inference=False,headers=rows,
                legacy_full_row_contract=all(r['legacy_full_row_contract'] for r in rows),
                designed_panel_contract=all(r['designed_panel_contract'] and r['production_panel_owns_header'] and r['header_height_contract'] for r in rows),
                classification='Existing CompletionInfoPanel owns the full row; fixed layout margins and header top/left/right inset are exactly 1 logical pixel. Legacy header-to-content mismatch remains recorded; no tolerance or before-source waiver.')
            self.shot('completion-native-recheck')
            self.result['completion_functional_passed']=True;self.write()
            self.check('completion full-row outer panel and exact 1px inner header border contract',
                self.result['completion_geometry']['designed_panel_contract'],rows)

        def run(self):
            window.showNormal();window.resize(1320,860);yield .4
            self.readiness_diagnostic(force=True);self.shot('normal-entry-before-ready')
            if inputs.get('mode')=='removed-models':
                from .removed_models_audit import steps
                yield from steps(self,window,output,inputs)
            elif inputs.get('mode','studio') in {'daily-workshop','workshop'}:
                raise RuntimeError('可选模型旧验收已退役，请使用当前 removed-models 验收。')
            elif inputs.get('mode','studio')=='completion':
                yield from self.completion()
            else:
                # The launcher deliberately leaves the normal Home in place.
                # Import through its real Studio library button, like existing
                # export_target_audit; merely having STARTUP_PROJECT is no open.
                self.check('normal initial Home has no automatically opened project',self.page.project is None)
                self.click(window.subtitle_studio_button);yield .2
                self.check('normal Home to Studio library route',window.pages.currentWidget() is self.page and self.page.studio_empty.isVisible())
                self.shot('normal-studio-library-before-import')
                picker=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(str(project_path),'2ByteASR project')
                try:self.click(self.page.project_import_button)
                finally:QFileDialog.getOpenFileName=picker
                yield .05;self.readiness_diagnostic(force=True);self.shot('normal-project-import-before-ready')
                yield self.ready;self.page._set_volume(0);self.page.video.set_paused(True)
                self.original_caption=self.caption_contract(self.page.project)
                self.check('normal startup loaded copied project',Path(self.page.project_path).resolve()==project_path)
                self.shot('studio-before-transparent-import')
                self.seek(0);yield .3;self.click(self.page.media_pool_button);yield .2
                panel=self.page.media_pool_panel
                original=QFileDialog.getOpenFileName;QFileDialog.getOpenFileName=lambda *a,**k:(str(overlay),'media')
                try:self.click(panel.add_asset_button)
                finally:QFileDialog.getOpenFileName=original
                yield lambda:any(Path(a.canonical_source).resolve()==overlay for a in self.page.project.media_pool)
                yield .3;self.click(panel.add_track_button);yield .2
                asset=next(a for a in self.page.project.media_pool if Path(a.canonical_source).resolve()==overlay)
                tree=panel.assets
                item=next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0,Qt.UserRole)==asset.asset_id)
                tree.scrollToItem(item);QApplication.processEvents();QTest.mouseClick(tree.viewport(),Qt.LeftButton,pos=tree.visualItemRect(item).center())
                self.check('actual media pool row selected',panel.selected_asset_id()==asset.asset_id)
                self.click(panel.add_to_track_button);yield lambda:self.overlay_clip() is not None
                self.check('actual MOV imported as a video track clip at playhead0',self.overlay_clip()[1].timeline_in_ms==0,asdict(self.overlay_clip()[1]))
                self.seek(1000);yield .4
                row=self.overlay_clip();timeline=self.page.timeline
                timeline.set_visible_window(0,max(3000,int(inputs.get('timeline_window_ms',12000))))
                rect=timeline._video_track_rect(row[0].id);point=QPoint(round(timeline._time_to_x(1000)),round(rect.center().y()))
                self.check('actual imported clip mouse target lies inside timeline',timeline.rect().contains(point),[point.x(),point.y()])
                QTest.mouseClick(timeline,Qt.LeftButton,pos=point);yield .3
                self.check('actual timeline mouse selects imported clip',timeline.selected_video_clip_id==row[1].id)
                for scale in (1.,.7,1.25):
                    self.field(self.page.video_scale_x.lineEdit(),round(scale*100));yield .2
                    current=self.overlay_clip()[1]
                    self.check('actual scale controls committed X/Y '+str(scale),abs(current.transform.scale_x-scale)<.001 and abs(current.transform.scale_y-scale)<.001,asdict(current.transform))
                    self.seek(1000);yield (self.decoder_ready,60);yield .3
                    scene=self.page.video_compositor;player=scene._players[current.id]
                    image=player.image.convertToFormat(QImage.Format.Format_ARGB32)
                    import numpy as np
                    pixels=np.frombuffer(image.constBits(),dtype=np.uint8,count=image.sizeInBytes()).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width()]
                    self.check('actual decoder retained nontrivial alpha for transparent MOV',int(pixels[:,:,3].min())==0 and int(pixels[:,:,3].max())==255,dict(min=int(pixels[:,:,3].min()),max=int(pixels[:,:,3].max()),size=[image.width(),image.height()]))
                    telemetry=scene.telemetry();async_samples=list(scene._async_compositor.samples) if scene._async_compositor else []
                    self.result.setdefault('compositions',[]).append(dict(scale=scale,actual_decoder_pts_ms=player.pts_ms,decoder_path=str(getattr(player,'path','')),transform=asdict(current.transform),scene_visible=scene.isVisible(),telemetry=telemetry,async_samples=async_samples[-6:]))
                    self.check('actual normal Studio composition has decoded layer',scene.has_video_overlays and (bool(telemetry) or any(any(l.get('clip_id')==current.id for l in s.get('layers',[])) for s in async_samples)))
                    self.shot('studio-real-transparent-scale-'+str(scale));self.write()
                yield from self.save_reopen()
                if inputs.get('manual_edit',True):yield from self.manual_edit()
                if inputs.get('export',True):yield from self.export()
            self.check('no background provider request',blank_project_audit._provider_calls==0)
            if overlay:self.check('input transparent MOV original bytes retained',_sha(overlay)==self.input_hashes[str(overlay)])

        def finish(self):
            self.timer.stop();self.result['elapsed_seconds']=time.monotonic()-self.started
            self.result['provider_calls']=blank_project_audit._provider_calls
            try:self.shot('final-normal-window')
            except Exception:pass
            if self.ui and self.ui._running:self.ui._cancel_export()
            self.write()
            def close_when_idle():
                if self.ui and self.ui._running:QTimer.singleShot(100,close_when_idle);return
                self.page.undo_stack.setClean();window.result_exit_code=0 if self.result['passed'] else 1;window.close()
            def stopped():self.result['gui_shutdown']=True;self.write()
            QApplication.instance().aboutToQuit.connect(stopped);close_when_idle()
    window._unified_studio_audit=Audit()
