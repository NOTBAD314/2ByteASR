"""Normal-entry, real-project caption readiness and late-result ownership audit."""
from __future__ import annotations
import json, os, time, traceback
import sys,hashlib
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import QObject,QEvent,QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..studio.studio_readiness import StudioReadiness
    from .blank_project_audit import _capture
    app=QApplication.instance();out=Path(out)
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result={'pid':os.getpid(),'rounds':[],'checks':{},'errors':[],
                         'measurement':'Qt paint/input and published glyph image; not physical scanout'}
            self.result['frozen']=bool(getattr(sys,'frozen',False))
            self.result['gui_sha256']=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
            self.result['module_origins']={name:getattr(module,'__file__','') for name,module in sys.modules.items()
                if name in ('twobyteasr.app.ui','twobyteasr.studio.studio_readiness','twobyteasr.rendering.caption_playback_cache')}
            if os.environ.get('CAPTION_FIRST_EXPECT_FROZEN')=='1':
                self.check('frozen_executable',self.result['frozen'])
                self.check('frozen_gui_hash',self.result['gui_sha256']==os.environ['CAPTION_FIRST_EXPECT_GUI_SHA256'])
                self.check('frozen_module_origins',all(str(getattr(sys,'_MEIPASS','')) in path for path in self.result['module_origins'].values()))
            self.current=None;self.phase='';self.pending=0;self.last=time.perf_counter();self.gaps=[];self.advancing=False
            self.paint_pending=set()
            self.watched_loading=None
            self.sequence=self.run();self.timer=QTimer(self);self.timer.setInterval(4)
            self.timer.timeout.connect(self.tick);self.timer.start();window.installEventFilter(self)
            self.watched_page=None
            app.aboutToQuit.connect(self.shutdown)
            self.save()
        def page(self):return window.built_page('studio')
        def mark(self,name):
            if self.current and name not in self.current:
                self.current[name]=round((time.perf_counter()-self.current['_started'])*1000,3)
        def check(self,name,value,detail=None):self.result['checks'][name]={'passed':bool(value),'detail':detail}
        def eventFilter(self,obj,event):
            if self.current and event.type()==QEvent.Paint and id(obj) not in self.paint_pending:
                self.paint_pending.add(id(obj));current=self.current
                QTimer.singleShot(0,lambda obj=obj,current=current:self.after_paint(obj,current))
            return False
        def after_paint(self,obj,current):
            self.paint_pending.discard(id(obj))
            if self.current is not current:return
            try:
                self.mark('window_first_paint_ms')
                page=self.page()
                gate=getattr(page,'_readiness',None)
                if page and page.project and page.isVisible() and gate and gate.ready and not gate.loading.active:
                    if obj is page.cue_table.viewport() and page.cue_model.rowCount():
                        self.mark('list_first_paint_ms')
                    if obj is page.timeline:
                        self.mark('timeline_first_paint_ms')
            except RuntimeError:pass
        def tick(self):
            if self.advancing:return
            now=time.perf_counter();self.gaps.append((now-self.last)*1000);self.last=now
            page=self.page()
            loading=window.__dict__.get('_studio_entry_loading')
            if loading is not None and self.watched_loading is not loading:
                loading.installEventFilter(self);self.watched_loading=loading
            if self.current and page:
                gate=getattr(page,'_readiness',None)
                if gate and '读取工程' in gate.completed:self.mark('data_prepared_ms')
                if page.project and self.watched_page is not page:
                    page.cue_table.viewport().installEventFilter(self);page.timeline.installEventFilter(self)
                    self.watched_page=page
            if self.current and page and page.project:
                scene=getattr(page,'_caption_scene',None)
                published=getattr(scene,'published',None)
                if page.isVisible() and published is not None and getattr(published,'image',None) is not None:
                    if not published.image.isNull():
                        self.mark('preview_pixels_prepared_ms')
                        gate=getattr(page,'_readiness',None)
                        if gate and gate.ready and not gate.loading.active:self.mark('preview_visible_ms')
            if now<self.pending:return
            try:
                self.advancing=True
                self.pending=now+next(self.sequence)
            except StopIteration:self.finish()
            except Exception:self.result['errors'].append(traceback.format_exc());self.finish()
            finally:self.advancing=False
        def run(self):
            yield .4
            for name in ('first','reenter'):
                self.current={'name':name,'_started':time.perf_counter()};self.gaps=[]
                self.result['rounds'].append(self.current)
                self.save()
                profiler=None;stop_samples=None
                if name=='first' and os.environ.get('CAPTION_FIRST_PROFILE')=='1':
                    import cProfile,threading,sys,collections
                    profiler=cProfile.Profile();profiler.enable();stop_samples=threading.Event();samples=collections.Counter()
                    def sample():
                        while not stop_samples.wait(.1):
                            names={t.ident:t.name for t in threading.enumerate()}
                            for ident,frame in sys._current_frames().items():
                                chain=[]
                                while frame and len(chain)<14:
                                    chain.append(f'{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}')
                                    frame=frame.f_back
                                samples[(names.get(ident,str(ident)),' <- '.join(chain))]+=1
                    threading.Thread(target=sample,daemon=True).start()
                window.open_studio_project(out/'project.2byteproj')
                deadline=time.perf_counter()+55
                while time.perf_counter()<deadline:
                    page=self.page();gate=getattr(page,'_readiness',None)
                    if page and gate and gate.profile.get('error'):raise RuntimeError(str(gate.profile))
                    if page and page.project and page.isVisible() and gate and gate.ready:
                        if all(k in self.current for k in ('list_first_paint_ms','timeline_first_paint_ms','preview_visible_ms')):break
                    yield .01
                page=self.page()
                self.check(name+'.ready',bool(page and page.project and page._readiness.ready),getattr(getattr(page,'_readiness',None),'profile',{}))
                if not self.result['checks'][name+'.ready']['passed']:raise TimeoutError('caption readiness timeout')
                row=page.cue_model.row_for_cue_id('6');index=page.cue_model.index(row,3)
                page.cue_table.scrollTo(index);QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,Qt.NoModifier,page.cue_table.visualRect(index).center())
                yield .005
                self.mark('selectable_ms');self.check(name+'.selection',str(page.selected_cue_id)=='6')
                if profiler is not None:
                    import pstats,io
                    profiler.disable();stop_samples.set();stream=io.StringIO()
                    pstats.Stats(profiler,stream=stream).sort_stats('cumtime').print_stats(60)
                    (out/'profile-main.txt').write_text(stream.getvalue(),'utf8')
                    (out/'profile-thread-samples.json').write_text(json.dumps([
                        {'thread':key[0],'stack':key[1],'samples':count} for key,count in samples.most_common()],indent=2),'utf8')
                self.current['readiness']=dict(page._readiness.profile)
                self.current['open_profile']=getattr(page,'last_open_profile',{})
                self.current['gui_max_gap_ms']=round(max(self.gaps,default=0),3)
                self.check(name+'.cue_count',len(page.project.cues)==int(os.environ.get('CAPTION_FIRST_CUE_COUNT','1392')),len(page.project.cues))
                self.current['preview_text']=page.project.cues[5].text
                self.current['preview_translation']=page.project.generation_metadata.get('translations',{}).get('6','')
                self.check(name+'.translation_present',bool(self.current['preview_translation']))
                _capture(window,out/(name+'.png'))
                native=out/(name+'-video.png')
                page.video.controller.screenshot_to_file(native)
                # A real edit through the table's undoable model boundary.
                text=page.project.cues[5].text
                changed=page.cue_model.setData(index,text+' [audit]',Qt.EditRole)
                self.check(name+'.edit',changed and page.project.cues[5].text==text+' [audit]')
                if changed:page.undo_stack.undo()
                self.check(name+'.undo',page.project.cues[5].text==text)
                self.current.pop('_started',None);self.current=None
                window._return_to_main_menu();yield .3
            # Cancelled read A must not deliver after reopening B.
            window.open_studio_project(out/'alternate.2byteproj')
            yield .01
            window._return_to_main_menu();yield .05
            window.open_studio_project(out/'project.2byteproj');yield .2
            deadline=time.perf_counter()+45
            while time.perf_counter()<deadline and not (self.page() and self.page()._readiness.ready):yield .02
            self.check('rapid_reentry_ownership',self.page().project_path.resolve()==(out/'project.2byteproj').resolve())
            self.result['completed']=True
        def save(self):
            data=json.loads(json.dumps(self.result,default=str));
            for row in data['rounds']:row.pop('_started',None)
            (out/'caption-first-display.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),'utf8')
        def finish(self):
            self.timer.stop();window.removeEventFilter(self)
            self.result['passed']=bool(self.result.get('completed') and not self.result['errors'] and all(x['passed'] for x in self.result['checks'].values()))
            self.save();window.close()
        def shutdown(self):self.result['normal_shutdown']=True;self.save()
    window._caption_first_display_audit=Audit()
