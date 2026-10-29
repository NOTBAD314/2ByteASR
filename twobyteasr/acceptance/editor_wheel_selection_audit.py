"""Owned normal-app verification for wheel axes, selection and field-only edits."""
from __future__ import annotations
import copy
import ctypes
from dataclasses import asdict
import json
import os
import sys
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
    from PySide6.QtGui import QColor, QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu, QScrollArea
    from ..caption_style.style_resolution import resolve_cue_visual
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..projects.studio_project import load_project, save_project
    app = QApplication.instance()
    output = Path(output)

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            from ..diagnostics.build_identity import load_build_identity
            self.result = {'passed':False, 'pid':os.getpid(), 'checks':[], 'wheel_events':[], 'screenshots':[],
                           'executable':sys.executable, 'frozen':bool(getattr(sys,'frozen',False)),
                           'build_identity':load_build_identity().to_dict()}
            self.wait_until = 0
            self.steps = self.run()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(20)

        def check(self, name, passed, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Wheel:
                self.result['wheel_events'].append(dict(angle=[event.angleDelta().x(),event.angleDelta().y()],
                                                        modifiers=event.modifiers().value))
            return False

        def shot(self, widget, name):
            filename = output/(name+'.png')
            if widget is window:
                from .blank_project_audit import _capture
                _capture(window, filename)
            else:
                widget.grab().save(str(filename))
            self.result['screenshots'].append(str(filename))

        def tick(self):
            if time.monotonic() < self.wait_until:
                return
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        @staticmethod
        def styles(page):
            return {cue.id:asdict(resolve_cue_visual(page.project,cue).style) for cue in page.project.cues}

        def show_control(self, control):
            parent = control.parentWidget()
            while parent is not None and not isinstance(parent,QScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                parent.ensureWidgetVisible(control, 0, 30)

        def input_number(self, control, value):
            self.show_control(control)
            editor = control.lineEdit()
            QTest.mouseClick(editor, Qt.LeftButton)
            QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(editor, str(value))
            QTest.keyClick(editor, Qt.Key_Tab)

        def wait_preview(self, page, name):
            cue_id=page.session.selected_cue_id
            width,height=page._advanced_preview_size()
            expected=build_visual_cue_snapshot(page.project,cue_id,width=width,height=height)
            fields=('font_family','font_size','font_weight','italic','letter_spacing','fill',
                    'strokes','shadow','glow','position_x','position_y','alignment')
            expected_values={key:getattr(expected,key) for key in fields}
            deadline=time.monotonic()+6
            rows=[]
            actual_values={}
            while time.monotonic()<deadline:
                trace=page.subtitle_visibility_trace(reason='field_edit_preview')
                rows=trace.get('cue_pixels',[])
                prepared=page._prepared_caption(cue_id)
                if prepared is not None and hasattr(prepared,'snapshot'):
                    actual_values={key:getattr(prepared.snapshot,key) for key in fields}
                if (actual_values==expected_values and any(row.get('cue_id')==cue_id
                        and row.get('snapshot_hash')==prepared.snapshot_hash
                        and row.get('alpha_nonzero',0)>0 for row in rows)):
                    self.check(name,True)
                    return
                yield .15
            self.check(name,False,{'expected':expected_values,'actual':actual_values,'rows':rows})

        def native_wheel(self, page, delta, alt=False, ctrl=False, shift=False):
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.SendMessageW.argtypes = [ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
            saved = (ctypes.c_ubyte*256)()
            user.GetKeyboardState(saved)
            keys = (ctypes.c_ubyte*256)()
            for enabled,key,left in [(alt,0x12,0xa4),(ctrl,0x11,0xa2),(shift,0x10,0xa0)]:
                if enabled:
                    keys[key] = keys[left] = 0x80
            point = page.timeline.mapToGlobal(QPoint(page.timeline.width()//2,30))
            packed = (point.x()&0xffff)|((point.y()&0xffff)<<16)
            try:
                if not user.SetKeyboardState(keys):
                    raise ctypes.WinError(ctypes.get_last_error())
                user.SendMessageW(int(page.timeline.winId()),0x020A,((delta&0xffff)<<16)|(8 if ctrl else 0)|(4 if shift else 0),packed)
                app.processEvents()
            finally:
                user.SetKeyboardState(saved)

        def run(self):
            yield 1
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('TWOBYTEASR_STYLE_AUDIT_THEME','warm'))
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            deadline = time.monotonic()+50
            page = None
            while time.monotonic()<deadline:
                page = window.built_page('studio')
                if page and page.project and getattr(page.video,'_startup_state','')=='READY':
                    break
                yield .2
            self.check('normal_studio_ready',bool(page and page.project and page.video._startup_state=='READY'))
            if page is None or page.project is None:
                return
            window.showMaximized()
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            page._sync_play_button(True)
            page.select_cue('a')
            page.context_drawer.setCurrentIndex(1)
            yield 1
            page.timeline.installEventFilter(self)
            for modifiers in ({'alt':True},{},{'shift':True}):
                page.timeline.set_visible_window(40_000,10_000)
                positions = [page.timeline.visible_start_ms]
                for delta in (120,120,-120,-120):
                    self.native_wheel(page,delta,**modifiers)
                    yield .1
                    positions.append(page.timeline.visible_start_ms)
                self.check('native_pan_'+str(modifiers),positions==[40000,38800,37600,38800,40000],positions)
            for start,outward,returned in ((0,120,1200),(110000,-120,108800)):
                page.timeline.set_visible_window(start,10_000)
                self.native_wheel(page,outward,alt=True)
                yield .1
                self.check('boundary_clamp_'+str(start),page.timeline.visible_start_ms==start)
                self.native_wheel(page,-outward,alt=True)
                yield .1
                self.check('boundary_return_'+str(start),page.timeline.visible_start_ms==returned)
            page.timeline.set_visible_window(40_000,10_000)
            for delta,duration in ((120,8000),(-120,10000)):
                self.native_wheel(page,delta,ctrl=True)
                yield .1
                self.check('native_ctrl_zoom_'+str(delta),page.timeline.visible_duration_ms==duration)
            events = self.result['wheel_events']
            self.check('one_native_event_per_notch',len(events)==18,len(events))
            self.check('alt_signed_horizontal_axis', [event['angle'] for event in events[:4]]==[[120,0],[120,0],[-120,0],[-120,0]],events[:4])
            self.check('wheel_does_not_seek',page.timeline.playhead_ms<1800,page.timeline.playhead_ms)
            page.timeline.set_visible_window(0,10000)
            self.shot(window,'01-wheel-and-editor')
            # Real list clicks, Ctrl+A and a collapsed-group context menu.
            for kind,targets in [('single',{'a'}),('multi',{'a','b'}),('all',{'a','b','c','d'}),('group',{'b','c'})]:
                page.cue_table.setFocus()
                index=page.cue_model.index(page.cue_model.row_for_cue_id('a'),3)
                QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,Qt.NoModifier,
                                 page.cue_table.visualRect(index).center())
                if kind=='multi':
                    index=page.cue_model.index(page.cue_model.row_for_cue_id('b'),3)
                    QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,Qt.ControlModifier,
                                     page.cue_table.visualRect(index).center())
                elif kind=='all':
                    QTest.keyClick(page.cue_table,Qt.Key_A,Qt.ControlModifier)
                elif kind=='group':
                    rect=page.timeline._track_layout()[0]['S02']
                    point=QPoint(50,round(rect.center().y()))
                    def choose_group():
                        menu=QApplication.activePopupWidget()
                        if not isinstance(menu,QMenu):
                            raise AssertionError('Group context menu did not open')
                        action=next(action for action in menu.actions() if '选择次要角色组的全部字幕' in action.text())
                        self.shot(menu,'02-collapsed-group-menu')
                        QTest.mouseClick(menu,Qt.LeftButton,Qt.NoModifier,menu.actionGeometry(action).center())
                    QTimer.singleShot(80,choose_group)
                    app.sendEvent(page.timeline,QContextMenuEvent(QContextMenuEvent.Mouse,point,page.timeline.mapToGlobal(point)))
                yield .3
                self.check(kind+'_targets',set(page._style_target_ids())==targets,page._style_target_ids())
                if kind=='group':
                    page._seek((page.session._cue_lookup['b'].start_ms+500)/1000)
                    yield .4
                before=self.styles(page)
                before_count=page.undo_stack.count()
                self.input_number(page.style_font_size,84+len(targets))
                yield .5
                after=self.styles(page)
                yield from self.wait_preview(page,kind+'_size_preview_current')
                self.check(kind+'_font_size',all(style['font_size']==84+len(targets) if cue_id in targets else style==before[cue_id]
                                               for cue_id,style in after.items()),after)
                self.check(kind+'_unmodified_fields',all(all(style[key]==before[cue_id][key] for key in ('font_family','primary_color','outline_color','outline_width','alignment'))
                                                       for cue_id,style in after.items()))
                self.check(kind+'_one_undo',page.undo_stack.count()==before_count+1)
                page.undo_stack.undo()
                self.check(kind+'_undo_restores_each',self.styles(page)==before)
                page.undo_stack.redo()
                self.check(kind+'_redo_restores_each',self.styles(page)==after)
                before=after
                selected=set(page._style_target_ids())
                def accept_color():
                    dialog=QApplication.activeModalWidget()
                    if dialog is None:
                        raise AssertionError('Color picker did not open')
                    self.check(kind+'_dialog_keeps_targets',set(page._style_target_ids())==selected)
                    self.shot(dialog,'03-'+kind+'-color-dialog')
                    dialog.picker.set_color(QColor('#FF245678'))
                    button=dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
                    QTest.mouseClick(button,Qt.LeftButton)
                self.show_control(page.style_outline_button)
                QTimer.singleShot(100,accept_color)
                QTest.mouseClick(page.style_outline_button,Qt.LeftButton)
                yield .5
                after=self.styles(page)
                yield from self.wait_preview(page,kind+'_color_preview_current')
                self.check(kind+'_color_targets',all(style['outline_color'].upper()=='#FF245678' if cue_id in targets else style==before[cue_id]
                                                   for cue_id,style in after.items()))
                self.check(kind+'_color_preserves_font',all(style['font_family']==before[cue_id]['font_family'] and style['font_size']==before[cue_id]['font_size']
                                                          for cue_id,style in after.items()))
                self.check(kind+'_selection_retained',set(page._style_target_ids())==targets)
                native=output/('07-'+kind+'-color-preview.png')
                page.video.controller.screenshot_to_file(native)
                yield .2
                self.result['screenshots'].append(str(native))
                self.shot(window,'04-'+kind+'-after-style')
            destination=output/'saved-result.2byteproj'
            save_project(page.project,destination)
            expected=self.styles(page)
            self.result['saved_styles']=expected
            self.check('save_load_data',all(asdict(resolve_cue_visual(load_project(destination),cue).style)==expected[cue.id]
                                          for cue in load_project(destination).cues))
            page.undo_stack.setClean()
            previous=page.project
            page.open_project(destination)
            deadline=time.monotonic()+35
            while time.monotonic()<deadline and (page.project is previous or page.project_path!=destination):
                yield .2
            yield 1
            self.check('reopened_editor_data',page.project is not previous and self.styles(page)==expected)
            for cue_id in ('b','c'):
                page.select_cue(cue_id)
                page._seek((page.session._cue_lookup[cue_id].start_ms+500)/1000)
                yield 1
                snapshot=build_visual_cue_snapshot(page.project,cue_id)
                self.check('reopened_preview_'+cue_id,snapshot.font_size==86 and page.style_font_size.value()==86,
                           {'snapshot_size':snapshot.font_size,'inspector_size':page.style_font_size.value()})
                self.shot(window,'05-reopened-'+cue_id)
                native=output/('06-mpv-'+cue_id+'.png')
                page.video.controller.screenshot_to_file(native)
                yield .4
                self.check('mpv_composed_frame_'+cue_id,native.is_file() and native.stat().st_size>1000)
                self.result['screenshots'].append(str(native))
            self.result['subtitle_visibility']=page.subtitle_visibility_trace(reason='editor_wheel_selection_audit')

        def finish(self):
            self.timer.stop()
            self.result['passed']=bool(self.result['checks']) and all(row['passed'] for row in self.result['checks']) and 'error' not in self.result
            receipt=output/'result.json'
            receipt.write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            def closed():
                self.result['gui_shutdown']=True
                receipt.write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            app.aboutToQuit.connect(closed)
            page=window.built_page('studio')
            if page is not None:
                page.undo_stack.setClean()
            window.close()

    window._editor_wheel_selection_audit=Audit()
