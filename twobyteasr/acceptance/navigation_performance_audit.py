"""Real-window navigation benchmark. Never imported in normal operation.

End-of-paint callbacks verify target content, then an actual queued input
probes a useful control. These are Qt presentation times, not monitor scanout.
First operations and repeated operations are reported separately. cProfile is
optional and its measurements must not be mixed into the performance table.
"""
from __future__ import annotations
import cProfile
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time
import traceback


def distribution(values):
    values=sorted(v for v in values if v is not None)
    if not values: return {'n':0}
    return dict(n=len(values),median=round(statistics.median(values),2),
        p95=round(values[max(0,math.ceil(len(values)*.95)-1)],2),max=round(values[-1],2))


def start(window,out):
    import psutil
    import PySide6
    from PySide6.QtCore import QCoreApplication,QEvent,QEventLoop,QObject,Qt,QTimer,qVersion
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication,QDialog,QLabel,QLineEdit,QWidget
    from ..diagnostics import navigation_timing,gui_stall_watchdog
    from ..projects.studio_project import load_project
    from .blank_project_audit import _capture
    from .perf_pages_audit import _gui_objects

    app=QApplication.instance()
    process=psutil.Process()
    fixture=out/'project.2byteproj'
    cycles=int(os.environ.get('TWOBYTEASR_NAVIGATION_CYCLES','30'))
    profiling=os.environ.get('TWOBYTEASR_NAVIGATION_PROFILE')=='1'
    regressions=os.environ.get('TWOBYTEASR_NAVIGATION_REGRESSIONS')=='1'
    categories=os.environ.get('TWOBYTEASR_NAVIGATION_CATEGORIES')=='1'
    # Read metadata off the GUI thread, before measurements; do not warm any
    # project parser, caption cache, media controller or application page.
    raw=json.loads(fixture.read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result=dict(entries=[],resources=[],errors=[],checks=[],cycles=cycles,
                pid=os.getpid(),frozen=bool(getattr(sys,'frozen',False)),profiling=profiling,
                protocol='navigation-v2-confirmed-transport',
                measurement='Qt target paint completed -> queued key handled; not monitor scanout',
                environment=dict(python=sys.version,executable=sys.executable,PySide6=PySide6.__version__,
                    Qt=qVersion(),platform=platform.platform(),cpu=platform.processor(),logical_cpus=os.cpu_count(),
                    ram_gb=round(psutil.virtual_memory().total/1024**3,1),
                    screens=[dict(name=s.name(),size=[s.size().width(),s.size().height()],dpr=s.devicePixelRatio(),
                        dpi=s.logicalDotsPerInch(),refresh=s.refreshRate()) for s in app.screens()]),
                fixture=dict(cues=len(raw.get('cues',[])),duration_ms=raw.get('media',{}).get('duration_ms'),
                    bytes=fixture.stat().st_size,media_exists=Path(raw.get('media',{}).get('path','')).is_file()))
            self.started=time.perf_counter(); self.last_beat=self.started
            self.gaps=[]; self.seen=set(); self.cur=None; self.pending=0.;self.cycle=-1
            self.sequence=self.run();self.finished=False;self.profile=None
            self.heartbeat=QTimer(self);self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.timeout.connect(self.beat);self.heartbeat.start(16)
            self.driver=QTimer(self);self.driver.setTimerType(Qt.TimerType.PreciseTimer)
            self.driver.timeout.connect(self.tick);self.driver.start(5)
            app.installEventFilter(self)
            app.aboutToQuit.connect(self.closed)
            self.save()

        def beat(self):
            now=time.perf_counter();self.gaps.append((now,(now-self.last_beat)*1000));self.last_beat=now

        def tick(self):
            if self.finished:return
            try:
                if time.perf_counter()-self.started>780:raise TimeoutError('navigation audit deadline')
                page=self.studio()
                readiness=getattr(page,'_readiness',None)
                if readiness is not None and readiness.profile.get('error'):
                    scene=getattr(page,'_caption_scene',None)
                    self.result['failed_readiness']=dict(profile=readiness.profile,
                        preview_path=str(getattr(page,'_preview_path',None)),
                        ass_profile=list(getattr(page,'_ass_profile',()))[-5:],
                        publish_timer_active=page._advanced_preview_publish_timer.isActive(),
                        scene=scene.trace() if scene is not None else None)
                    raise RuntimeError('Studio readiness failed: '+str(readiness.profile['error']))
                status=window.__dict__.get('_studio_entry_status')
                if self.cur is not None and self.cur['kind']=='studio' and status is not None and '创建失败' in status.text():
                    raise RuntimeError(status.text())
                if callable(self.pending):
                    if not self.pending():return
                elif time.perf_counter()<self.pending:return
                value=next(self.sequence)
                self.pending=value if callable(value) else time.perf_counter()+value
            except StopIteration:self.finish()
            except Exception:
                self.result['errors'].append(traceback.format_exc());self.finish()

        def dialog(self):
            return next((w for w in app.topLevelWidgets() if w.objectName()=='applicationSettings' and w.isVisible()),None)

        def studio(self):return window.built_page('studio')

        def target(self,kind):
            if kind=='settings':return self.dialog()
            if self.dialog() is not None:return None
            if kind=='home':return window.settings_scroll if window.settings_scroll.isVisible() else None
            loading=window.__dict__.get('_studio_entry_loading')
            if loading is not None and loading.isVisible():return loading
            page=self.studio()
            return page if page is not None and page.isVisible() else None

        def useful(self,kind):
            target=self.target(kind)
            if target is None:return False
            if kind=='settings':
                category=(self.cur or {}).get('category')
                if category is not None:
                    return (target.pages.currentIndex()==category and target.pages.currentWidget().isVisible())
                return target.root_edit.isEnabled() and target.navigation.count()>1
            if kind=='home':return window.app_settings_button.isEnabled() and not window._recognition_page_deferred
            if target is not self.studio():return False
            return (target.project is not None and target._readiness.ready and
                target.cue_table.model().rowCount()>0 and target.timeline.isEnabled())

        def complete(self,kind):
            if not self.useful(kind):return False
            if kind=='settings':
                # __dict__: reading the attribute would build the category (2026-10-25).
                dialog=self.dialog();panel=dialog.__dict__.get('shortcut_panel')
                if panel is not None and dialog.pages.currentWidget().isAncestorOf(panel):
                    return bool(getattr(panel,'construction_complete',True))
            if kind!='studio':return True
            page=self.studio()
            return (not page._waveform_inflight and not page._waveform_pending_media
                    and bool(page._waveform_last_ready_media))

        def eventFilter(self,obj,event):
            cur=self.cur
            if cur is None or event.type()!=QEvent.Type.Paint:return False
            target=self.target(cur['kind'])
            if target is None:return False
            try:relevant=obj is target or (isinstance(obj,QWidget) and target.isAncestorOf(obj))
            except RuntimeError:return False
            if not relevant:return False
            useful=self.useful(cur['kind']);complete=self.complete(cur['kind'])
            def painted():
                if self.cur is not cur:return
                now=time.perf_counter()
                if cur.get('feedback') is None:cur['feedback']=now
                if useful and cur.get('content') is None:cur['content']=now
                if complete and cur.get('complete_paint') is None:cur['complete_paint']=now
            QTimer.singleShot(0,painted)
            return False

        def resource(self,label):
            page=self.studio();children=process.children(recursive=True)
            row=dict(label=label,at_s=round(time.perf_counter()-self.started,2),
                rss_mb=round(process.memory_info().rss/1024**2,2),threads=process.num_threads(),
                python_threads=threading.active_count(),handles=process.num_handles(),widgets=len(app.allWidgets()),
                timers=len(window.findChildren(QTimer)),active_timers=sum(t.isActive() for t in window.findChildren(QTimer)),
                objects=len(window.findChildren(QObject)),event_loops=len(window.findChildren(QEventLoop)),
                children=len(children),mpv=sum(p.name().lower()=='mpv.exe' for p in children if p.is_running()),
                **_gui_objects())
            if page is not None:
                row['waveform_workers']=len(page._waveform_threads)
            self.result['resources'].append(row)

        def save(self):
            summary={}
            for row in self.result['entries']:
                key=row['label']+(':first' if row['first'] else ':hot')
                group=summary.setdefault(key,{k:[] for k in ('feedback_ms','usable_ms','complete_ms','max_gap_ms','max_lag_ms','over_100','over_250')})
                for k in group:group[k].append(row.get(k))
            self.result['summary']={key:{k:distribution(v) for k,v in cols.items()} for key,cols in summary.items()}
            self.result['elapsed_s']=round(time.perf_counter()-self.started,2)
            (out/'navigation.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
            navigation_timing.flush(out/'phases.json')

        def check(self,name,value):
            self.result['checks'].append(dict(name=name,passed=bool(value)))
            if not value:self.result['errors'].append(name)

        def measure(self,label,kind,action,timeout=300,category=None):
            first=self.cycle < 0;self.seen.add(label)
            cur=dict(label=label,kind=kind,t0=time.perf_counter(),category=category);self.cur=cur
            def dispatch():
                cur['t0']=time.perf_counter()
                page=self.studio()
                if page is not None and page.project is not None:
                    cur['transport_at_start']=dict(paused=page.video._paused,position_ms=page.timeline.playhead_ms,
                        audio_paused=page.audio_engine.telemetry_snapshot().get('paused'))
                if profiling and first:
                    self.profile=cProfile.Profile();self.profile.enable()
                try:action()
                except Exception:cur['error']=traceback.format_exc()
                finally:cur['returned']=time.perf_counter()
            QTimer.singleShot(0,dispatch)
            deadline=time.perf_counter()+timeout
            yield lambda: cur.get('content') is not None or cur.get('error') or time.perf_counter()>deadline
            if cur.get('content') is None:
                page=self.studio()
                raise RuntimeError(f'{label}: content timeout: {cur.get("error")}; readiness {getattr(getattr(page,"_readiness",None),"profile",None)}')
            if label == 'studio.enter':
                # Normalize the requested paused-entry scenario once transport
                # is operable. Older code auto-played and its resource governor
                # postponed fine waveform generation until the 1 h video ended.
                cur['auto_played_on_entry'] = not self.studio().video._paused
                self.studio().video.set_paused(True)
            # A real queued key in an existing control, beyond a responsive
            # heartbeat. No model or video state is changed by this probe.
            if kind=='settings':
                editor=self.dialog().root_edit
                if category is not None:
                    editor=next((w for w in self.dialog().pages.currentWidget().findChildren(QLineEdit)
                                 if w.isVisible() and w.isEnabled() and not w.isReadOnly()),self.dialog().navigation)
            elif kind=='studio':
                editor=self.studio().cue_table
            else:editor=window.app_settings_button
            acknowledged=[]
            if isinstance(editor,QLineEdit):
                editor.setCursorPosition(len(editor.text()))
                key=Qt.Key.Key_Home
            else:key=Qt.Key.Key_Tab
            editor.setFocus()
            QCoreApplication.postEvent(editor,QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.NoModifier))
            QCoreApplication.postEvent(editor,QKeyEvent(QEvent.Type.KeyRelease,key,Qt.KeyboardModifier.NoModifier))
            QTimer.singleShot(0,lambda:acknowledged.append(time.perf_counter()))
            yield lambda:bool(acknowledged)
            usable=acknowledged[0]
            if isinstance(editor,QLineEdit):self.check(label+':queued input',editor.cursorPosition()==0)
            yield lambda:self.complete(kind) or time.perf_counter()>deadline
            if not self.complete(kind):raise TimeoutError(label+': full content (including waveform) not ready')
            if cur.get('complete_paint') is None:
                target=self.target(kind);target.update()
                yield lambda:cur.get('complete_paint') is not None or time.perf_counter()>deadline
            complete=max(cur.get('complete_paint') or time.perf_counter(),usable)
            # Flush the heartbeat spanning the operation before attributing it.
            yield .025
            end=time.perf_counter();self.cur=None
            if self.profile is not None:
                self.profile.disable();self.profile.dump_stats(str(out/(label.replace('.','-')+'.pstats')));self.profile=None
            ms=lambda v:round((v-cur['t0'])*1000,2) if v is not None else None
            gaps=[gap for at,gap in self.gaps if cur['t0']<=at<=end]
            row=dict(label=label,first=first,cycle=self.cycle,feedback_ms=ms(cur.get('feedback')),
                usable_ms=ms(usable),complete_ms=ms(complete),handler_ms=ms(cur.get('returned')),
                max_gap_ms=round(max(gaps,default=0),2),max_lag_ms=round(max(0,max(gaps,default=0)-16),2),
                over_100=sum(g>=100 for g in gaps),over_250=sum(g>=250 for g in gaps),
                phases=navigation_timing.snapshot(cur['t0']))
            if kind=='studio':
                row['readiness']=dict(self.studio()._readiness.profile)
                if first:row['construction_stages']=getattr(self.studio(),'_workspace_build_profile',[])
            if 'auto_played_on_entry' in cur:row['auto_played_on_entry']=cur['auto_played_on_entry']
            if 'transport_at_start' in cur:row['transport_at_start']=cur['transport_at_start']
            self.result['entries'].append(row)
            print('NAVIGATION',label,'first' if first else 'hot',row['feedback_ms'],row['usable_ms'],row['complete_ms'],row['max_gap_ms'],flush=True)
            self.save()

        def settings(self,context):
            yield from self.measure('settings.'+context,'settings',window._open_application_settings)
            dialog=self.dialog()
            # 2026-10-25: an unchanged window is shown again instead of rebuilt.
            self.result.setdefault('settings_windows',[]).append([context,self.cycle,id(dialog)])
            if regressions:
                window._open_application_settings()
                self.check('settings.double-entry-single-instance', self.dialog() is dialog)
            # Category changes must expose the matching page and remain usable.
            for index in (1,2,3,0):
                start=time.perf_counter();dialog.navigation.setCurrentRow(index)
                yield .02
                self.check('settings.category.'+str(index),dialog.pages.currentIndex()==index)
                self.result.setdefault('category_samples',[]).append((time.perf_counter()-start)*1000)
            if self.cycle==-1:
                _capture(dialog,out/('settings-'+context+'.png'))
            yield from self.measure('settings.close.'+context,'home' if context=='home' else 'studio',dialog.reject)

        def go_home(self):
            page=self.studio()
            # The actual Studio menu action, same route as its home command.
            page._request_return_home()

        def run(self):
            window.resize(1440,900);window.show()
            yield 3.0
            if categories:
                yield from self.measure('settings.home','settings',window._open_application_settings)
                dialog=self.dialog()
                for cycle in range(-1,cycles):
                    self.cycle=cycle
                    for index in list(range(1,dialog.navigation.count()))+[0]:
                        yield from self.measure('category.'+str(index),'settings',
                            lambda index=index:dialog.navigation.setCurrentRow(index),category=index)
                        if cycle==-1:
                            # First visit builds the category (2026-10-25): what it looks like, its
                            # zoom pass, and visible words left in Chinese (another language run).
                            yield .3
                            _capture(dialog,out/f'category-{index}.png')
                            page=dialog.pages.widget(index)
                            self.result.setdefault('category_pages',[]).append(dict(index=index,
                                label=dialog.navigation.item(index).text(),
                                zoom=page.property('_uiZoomApplied') or dialog.property('_uiZoomApplied'),
                                chinese=[w.text() for w in page.findChildren(QLabel)
                                         if w.isVisible() and not w.property('i18nUserText')
                                         and any('一'<=c<='鿿' for c in w.text())][:30]))
                yield from self.invoke(dialog.reject)
                self.resource('categories-end')
                return
            if regressions:
                yield from self.construction_regression()
            self.resource('start')
            yield from self.settings('home')
            yield from self.measure('studio.enter','studio',lambda:window.open_studio_project(fixture,source='navigation-audit'))
            self.studio().video.set_paused(True)
            yield .3
            _capture(window,out/'studio-ready.png')
            yield from self.settings('paused')
            yield from self.measure('home.return','home',self.go_home)
            self.resource('first-complete')
            for cycle in range(cycles):
                self.cycle=cycle
                yield from self.settings('home')
                yield from self.measure('studio.enter','studio',lambda:window.open_studio_project(fixture,source='navigation-audit'))
                page=self.studio();paused=cycle%2==0
                origin=page.video.visual_position()
                page.video.set_paused(paused)
                deadline=time.perf_counter()+12
                def transport_ready():
                    return (page.video._paused==paused and
                        (paused or page.video.visual_position()>origin+.03))
                yield lambda:transport_ready() or time.perf_counter()>deadline
                if not transport_ready():raise TimeoutError('Requested playback state did not become real')
                context='paused' if paused else 'playing'
                yield from self.settings(context)
                yield from self.measure('home.return.'+context,'home',self.go_home)
                self.resource('cycle-'+str(cycle))
                yield .12
            self.resource('end')
            for cycle in range(int(os.environ.get('TWOBYTEASR_NAVIGATION_SOAK','0'))):
                self.cycle=cycle
                yield from self.measure('soak.settings','settings',window._open_application_settings)
                yield from self.invoke(self.dialog().reject)
                yield from self.measure('soak.enter','studio',lambda:window.open_studio_project(fixture))
                yield from self.measure('soak.home','home',self.go_home)
                yield .12
                self.resource('soak-'+str(cycle))
            if regressions:
                yield from self.regression_interactions()
                yield from self.category_roundtrip()

        def category_roundtrip(self):
            """Every category: change one setting, save, reopen and read it back (2026-10-25)."""
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QDialogButtonBox
            from ..app.application_settings import read_studio_preferences
            from ..design.theme_manager import theme_key
            from ..local_mcp import mcp_common
            from ..storage.storage_service import StorageService
            from ..studio import shortcut_registry
            yield from self.measure('roundtrip.open','settings',window._open_application_settings)
            dialog=self.dialog()
            for index in range(dialog.navigation.count()):   # each category built by its click
                yield from self.invoke(lambda index=index:dialog.navigation.setCurrentRow(index))
                yield .05
                self.check('roundtrip.category.'+str(index),dialog.pages.currentIndex()==index
                           and dialog.pages.currentWidget().isVisible())
            self.check('roundtrip.browsing-is-not-a-change',dialog._values()==dialog._saved_values)
            pick=lambda combo:next(i for i in range(combo.count()) if i!=combo.currentIndex())
            want={}
            def change(perform):
                yield from self.invoke(perform)
            yield from change(lambda:dialog.auto_save.setChecked(True))
            yield from change(lambda:dialog.interval.setCurrentIndex(pick(dialog.interval)))
            yield from change(lambda:dialog.recovery_policy.setCurrentIndex(pick(dialog.recovery_policy)))
            yield from change(lambda:dialog.startup_page.setCurrentIndex(pick(dialog.startup_page)))
            yield from change(lambda:dialog.frame_directory.setText(str(out/'frames')))
            want.update(interval=dialog.interval.currentData(),recovery=dialog.recovery_policy.currentData(),
                        startup=dialog.startup_page.currentData(),frames=str(out/'frames'),
                        cover=not dialog.cover.isChecked(),restore=not dialog.restore_layout_box.isChecked())
            yield from change(lambda:dialog.cover.setChecked(want['cover']))
            yield from change(lambda:dialog.restore_layout_box.setChecked(want['restore']))
            yield from change(lambda:dialog.speaker_tracks.setCurrentIndex(pick(dialog.speaker_tracks)))
            want['tracks']=dialog.speaker_tracks.currentData()
            spin=dialog.storage_panel.policy_controls['retention_days'][0];want['days']=spin.value()+1
            yield from change(lambda:spin.setValue(want['days']))
            want['motion']=not dialog.reduce_motion_box.isChecked()
            yield from change(lambda:dialog.reduce_motion_box.setChecked(want['motion']))
            gallery=dialog.theme_gallery
            want['theme']=next(gallery.itemData(i) for i in range(gallery.count()) if gallery.itemData(i)!=gallery.currentData())
            yield from change(lambda:gallery.card(want['theme']).click())   # previews the whole app
            yield .3
            review=dialog.advanced_controls.get('review_track')
            if review is not None and review.isEnabled():
                want['review']=not review.isChecked()
                yield from change(lambda:review.setChecked(want['review']))
            panel=dialog.shortcut_panel;action=panel._actions[-1].id;want['key']='Ctrl+Alt+Shift+F11'
            yield from change(lambda:panel._apply_bindings({action:want['key']}))
            want['scope']='library' if dialog.mcp_scope.currentData()!='library' else 'current'
            yield from change(lambda:dialog.mcp_scope.setCurrentIndex(dialog.mcp_scope.findData(want['scope'])))
            want['export']=not dialog.mcp_allow_export.isChecked()
            yield from change(lambda:dialog.mcp_allow_export.setChecked(want['export']))
            want['reminder']=not dialog.update_reminder_box.isChecked()
            yield from change(lambda:dialog.update_reminder_box.setChecked(want['reminder']))
            self.check('roundtrip.changes-detected',bool(dialog._values()))
            yield from self.invoke(dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click)
            yield .4
            self.check('roundtrip.closed-by-save',self.dialog() is None)
            prefs=read_studio_preferences();mcp=mcp_common.read_settings()
            stored=dict(interval=prefs.get('autosave_interval_seconds'),recovery=prefs.get('recovery_policy'),
                startup=prefs.get('startup_page'),cover=prefs.get('auto_cover'),restore=prefs.get('restore_layout'),
                tracks=prefs.get('speaker_main_tracks'),motion=prefs.get('reduce_motion'),
                reminder=prefs.get('update_reminder'),theme=theme_key(),
                frames=str(QSettings('2ByteASR','2ByteASR').value('frame_export/directory','')),
                days=StorageService().policy()['retention_days'],
                key=shortcut_registry.current_values().get(action),scope=mcp.get('scope'),export=mcp.get('allow_export'))
            if 'review' in want:
                stored['review']=window.legacy.RUNTIME_SETTINGS.get('switches',{}).get('output_review_track')
            for name,value in want.items():
                self.check('roundtrip.saved.'+name,stored.get(name)==value)
            self.result['roundtrip']=dict(wanted=want,stored=stored)
            yield from self.measure('roundtrip.reopen','settings',window._open_application_settings)
            again=self.dialog()
            self.check('roundtrip.saved-window-rebuilt',again is not dialog)
            for index in range(again.navigation.count()):
                yield from self.invoke(lambda index=index:again.navigation.setCurrentRow(index))
                yield .05
            shown=dict(interval=again.interval.currentData(),recovery=again.recovery_policy.currentData(),
                startup=again.startup_page.currentData(),frames=again.frame_directory.text(),
                cover=again.cover.isChecked(),restore=again.restore_layout_box.isChecked(),
                tracks=again.speaker_tracks.currentData(),days=again.storage_panel.policy_controls['retention_days'][0].value(),
                motion=again.reduce_motion_box.isChecked(),theme=again.theme_gallery.currentData(),
                key=again.shortcut_panel.values().get(action),scope=again.mcp_scope.currentData(),
                export=again.mcp_allow_export.isChecked(),reminder=again.update_reminder_box.isChecked())
            if 'review' in want:
                shown['review']=again.advanced_controls['review_track'].isChecked()
            for name,value in want.items():
                self.check('roundtrip.reopened.'+name,shown.get(name)==value)
            self.result['roundtrip']['shown']=shown
            self.check('roundtrip.reopened-not-dirty',again._values()==again._saved_values)
            _capture(again,out/'settings-roundtrip.png')
            yield from self.invoke(again.reject)
            yield .2
            self.check('roundtrip.cancel-without-question',self.dialog() is None)
            yield from self.measure('roundtrip.reuse','settings',window._open_application_settings)
            self.check('roundtrip.unchanged-window-reused',self.dialog() is again)
            self.check('roundtrip.reused-shows-first-category',again.pages.currentIndex()==0)
            yield from self.invoke(again.reject)
            yield .2

        def invoke(self,action):
            done=[];errors=[]
            def perform():
                try:action()
                except Exception:errors.append(traceback.format_exc())
                finally:done.append(True)
            QTimer.singleShot(0,perform)
            yield lambda:bool(done)
            if errors:raise RuntimeError(errors[0])

        def construction_regression(self):
            if not hasattr(window,'_queue_studio_construction'):
                return
            called=[]
            window.subtitle_studio_button.click()
            self.check('header.uses-loading-shell',window.__dict__.get('_studio_entry_loading') is not None)
            window.open_studio_project(fixture,on_ready=lambda page:called.append('obsolete'))
            yield lambda: window.__dict__.get('_studio_page_building') is not None
            partial=window._studio_page_building
            yield lambda:hasattr(partial,'audio_engine') or window.built_page('studio') is not None
            window._cancel_studio_construction()
            yield .1
            self.check('construction.cancel-home',window.pages.currentWidget() is window.settings_scroll)
            self.check('construction.cancel-stops-timer',not partial._workspace_build_timer.isActive())
            self.check('construction.no-obsolete-ready',not called)
            window.open_studio_project(fixture,on_ready=lambda page:called.append('latest'))
            yield lambda: self.studio() is not None and getattr(self.studio(),'_readiness',None) is not None and self.studio()._readiness.ready
            self.check('construction.latest-request-only',called==['latest'])
            yield from self.invoke(self.go_home)

        def regression_interactions(self):
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QDialogButtonBox
            from ..app.application_settings import read_studio_preferences
            yield from self.measure('regression.settings','settings',window._open_application_settings)
            dialog=self.dialog();before=dialog.auto_save.isChecked()
            for index in range(dialog.navigation.count()):
                yield from self.invoke(lambda index=index:dialog.navigation.setCurrentRow(index))
                yield .03
                self.check('category-full.'+str(index),dialog.pages.currentIndex()==index)
                panel=dialog.__dict__.get('shortcut_panel')
                if panel is not None and dialog.pages.currentWidget().isAncestorOf(panel):
                    if hasattr(panel,'_pending_rows') and panel._pending_rows:
                        dialog.navigation.setCurrentRow(0)
                        pending=len(panel._pending_rows)
                        yield .08
                        self.check('shortcuts.hidden-stops-construction',len(panel._pending_rows)==pending)
                        dialog.navigation.setCurrentRow(index)
                    yield lambda:bool(getattr(panel,'construction_complete',True))
                    _capture(dialog,out/'shortcuts-ready.png')
            self.check('category-no-false-dirty',dialog._values()==dialog._saved_values)
            dialog.navigation.setCurrentRow(0)
            dialog.auto_save.click()
            yield from self.invoke(dialog.buttons.button(QDialogButtonBox.Save).click)
            yield .1
            self.check('settings.persisted',read_studio_preferences().get('autosave_enabled')== (not before))
            yield from self.measure('regression.settings.reopen','settings',window._open_application_settings)
            dialog=self.dialog();self.check('settings.reopened-value',dialog.auto_save.isChecked()==(not before))
            yield from self.invoke(dialog.reject)
            yield from self.measure('regression.open','studio',lambda:window.open_studio_project(fixture))
            page=self.studio();page.video.set_paused(True)
            cue=page.project.cues[0];cue_id=cue.id;text=cue.text
            speakers=[(c.id,c.speaker_id,c.start_ms,c.end_ms) for c in page.project.cues]
            page.select_cue(cue_id);page._begin_canvas_inline_edit()
            yield lambda:page._canvas_editor is not None
            editor=page._canvas_editor
            editor.setPlainText(text+' nav-proof')
            yield from self.invoke(lambda:QTest.keyClick(editor,Qt.Key.Key_Return))
            yield .1
            self.check('edit.committed',page._cue_lookup[cue_id].text==text+' nav-proof')
            yield from self.invoke(page._undo_interactive)
            self.check('edit.undo',page._cue_lookup[cue_id].text==text)
            yield from self.invoke(page._redo_interactive)
            self.check('edit.redo',page._cue_lookup[cue_id].text==text+' nav-proof')
            yield from self.invoke(page.save)
            self.check('save.clean',page.undo_stack.isClean())
            translations=copy.deepcopy(page.project.generation_metadata.get('translations'))
            evidence_hash=lambda project:hashlib.sha256(json.dumps(project.asr_evidence,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            evidence=evidence_hash(page.project)
            project=page.project;index=page.undo_stack.index();selected=page.selected_cue_id
            position=page.timeline.playhead_ms
            yield from self.invoke(self.go_home)
            yield .15
            self.check('home.retains-session',page.project is project)
            self.check('home.paused',page.video._paused)
            self.check('home.presentation-timers-stopped',not page.video._timer.isActive() and not page.video._sync_timer.isActive())
            # State retention is checked before the benchmark's deliberate Tab
            # probe, which itself advances a QTableView's current selection.
            yield from self.invoke(lambda:window.open_studio_project(fixture))
            yield lambda:page._readiness.ready
            yield .02
            self.check('resume.same-project-after-save',page.project is project)
            self.check('resume.undo-history',page.undo_stack.index()==index)
            self.check('resume.selection',page.selected_cue_id==selected)
            self.check('resume.position',abs(page.timeline.playhead_ms-position)<80)
            self.check('resume.speakers-timing',speakers==[(c.id,c.speaker_id,c.start_ms,c.end_ms) for c in page.project.cues])
            self.check('resume.translations',translations==page.project.generation_metadata.get('translations'))
            self.check('resume.word-evidence',evidence==evidence_hash(page.project))
            other=out/'other.2byteproj';other.write_bytes(fixture.read_bytes())
            completed=[]
            window.open_studio_project(other,on_ready=lambda p:completed.append('obsolete'))
            page._request_return_home()
            yield .5
            self.check('load.cancel-late-result',not completed and window.pages.currentWidget() is window.settings_scroll)
            yield from self.measure('regression.reload','studio',lambda:window.open_studio_project(fixture))
            yield from self.invoke(page._request_return_library)
            self.check('library.closes-session',page.project is None)
            yield from self.measure('regression.library-open','studio',lambda:window.open_studio_project(fixture))
            self.check('save.reopen-content',page._cue_lookup[cue_id].text==text+' nav-proof')
            self.check('save.reopen-metadata',speakers==[(c.id,c.speaker_id,c.start_ms,c.end_ms) for c in page.project.cues])
            self.check('save.reopen-translations',translations==page.project.generation_metadata.get('translations'))
            self.check('save.reopen-word-evidence',evidence==evidence_hash(page.project))
            origin=page.video.visual_position();page.video.set_paused(False)
            deadline=time.perf_counter()+12
            def audible_transport():
                return (not page.video._paused and page.video.visual_position()>origin+.25
                        and page.audio_engine.telemetry_snapshot().get('paused') is False)
            yield lambda:audible_transport() or time.perf_counter()>deadline
            self.check('playback.audio-video-running',audible_transport())
            before=page.video.visual_position()
            yield from self.measure('regression.settings.steady-playing','settings',window._open_application_settings)
            yield .4
            self.check('playback.continues-through-settings',not page.video._paused and page.video.visual_position()>before+.2)
            self.result['playback_telemetry']=page.audio_engine.telemetry_snapshot()
            yield from self.invoke(self.dialog().reject)
            yield from self.invoke(self.go_home)
            deadline=time.perf_counter()+5
            yield lambda:page.audio_engine.telemetry_snapshot().get('paused') is True or time.perf_counter()>deadline
            self.check('home.audio-endpoint-paused',page.video._paused and page.audio_engine.telemetry_snapshot().get('paused') is True)
            self.resource('regressions-end')

        def finish(self):
            if self.finished:return
            self.finished=True;self.driver.stop();self.heartbeat.stop();app.removeEventFilter(self)
            if self.profile is not None:self.profile.disable()
            if self.cur is not None:
                cur=self.cur
                ms=lambda value:round((value-cur['t0'])*1000,2) if value else None
                self.result['incomplete_operation']=dict(label=cur['label'],
                    feedback_ms=ms(cur.get('feedback')),content_ms=ms(cur.get('content')),
                    elapsed_ms=ms(time.perf_counter()),phases=navigation_timing.snapshot(cur['t0']))
            watchdog=gui_stall_watchdog.instance()
            self.result['watchdog']=list(watchdog.recent) if watchdog else []
            self.result['finished']=True;self.save()
            for widget in app.topLevelWidgets():
                if isinstance(widget,QDialog) and widget.isVisible():widget.reject()
            page=self.studio()
            if page is not None:
                page.video.set_paused(True)
            window.close()

        def closed(self):
            self.result['gui_shutdown']=True
            page=self.studio()
            if page is not None:
                self.result['close_profile']=dict(getattr(page,'last_close_profile',{}))
            audit_path=out/'top-level-windows.jsonl'
            if audit_path.exists():
                accidental=[]
                for line in audit_path.read_text('utf8').splitlines():
                    try:entry=json.loads(line)
                    except ValueError:continue
                    if (entry.get('event')=='Show' and not entry.get('parentClass')
                            and entry.get('class') in {'QPushButton','QComboBox','QWidget','QFrame'}):
                        accidental.append({key:entry.get(key) for key in ('class','objectName','geometry')})
                self.result['accidental_windows']=accidental
                self.check('no-parentless-control-windows',not accidental)
            self.save()

    audit=Audit();window._navigation_audit=audit

