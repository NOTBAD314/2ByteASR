"""Opt-in actual Studio caption transitions and Enter latency evidence."""
from __future__ import annotations
import json
import os
import time
import traceback
from dataclasses import asdict
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def start(window, out):
    if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE') == 'boundary-tail':
        from .playback_tail_audit import start as start_tail
        return start_tail(window, out)
    if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE') in {'boundary-light','seek-pointer'}:
        from .playback_performance_audit import start as start_performance
        return start_performance(window,out)
    if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE') == 'preset-export':
        from .preset_export_audit import start as start_preset_export
        return start_preset_export(window, out)
    if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE') == 'balatro':
        from .balatro_runtime_audit import start as start_balatro
        return start_balatro(window,out)
    if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE') == 'boundary':
        from .cue_boundary_audit import start as start_boundary
        return start_boundary(window, out)
    page = window.studio_page
    result = {'passed': False, 'states': [], 'enter': [], 'playback_seconds': [], 'checks': []}
    def pump(seconds):
        end = time.perf_counter()+seconds
        while time.perf_counter()<end:
            QApplication.processEvents()
            time.sleep(.003)
    def wait(predicate, seconds=8):
        end = time.perf_counter()+seconds
        while not predicate() and time.perf_counter()<end:
            pump(.015)
        if not predicate(): raise AssertionError('condition timeout')
    def state(name):
        from .visual_snapshot import build_visual_cue_snapshot
        from .style_resolution import resolve_cue_visual
        cue = page._cue_lookup['long']
        visual = build_visual_cue_snapshot(page.project, cue.id)
        value = dict(name=name, cue_id=cue.id, preset_id=cue.base_preset_id, style_id=cue.style_id,
            style_revision=cue.appearance_generation, resolved_style=asdict(resolve_cue_visual(page.project,cue).style),
            style_hash=visual.glyph_hash(), snapshot=visual.to_dict(), renderer=page.render_truth_probe(force=True),
            playhead_ms=page.timeline.playhead_ms)
        if visual.resolved_caption:value['resolved_caption']=visual.resolved_caption.to_dict()
        result['states'].append(value)
        page.video.controller.screenshot_to_file(out/(name+'.png'))
        from .ass_compiler import compile_ass
        (out/(name+'.ass')).write_text(compile_ass(page.project), encoding='utf8')
        canvas=page.advanced_cue_overlay
        if getattr(canvas,'_snapshot',None) is not None:
            value['canvas_snapshot_hash']=canvas._snapshot.glyph_hash()
            value['canvas_bbox']=[canvas._base_rect.x(),canvas._base_rect.y(),canvas._base_rect.width(),canvas._base_rect.height()]
            pixmap=getattr(canvas,'_source',None)
            if pixmap is not None and not pixmap.isNull():
                alpha_path=out/(name+'-foreground.png');pixmap.save(str(alpha_path))
                from PIL import Image
                im=Image.open(alpha_path).convert('RGBA');bbox=im.getchannel('A').getbbox()
                value['foreground_alpha_bbox']=bbox
                value['foreground_size']=im.size
                fitted_height=visual.font_size*im.height/visual.playres_y
                value['measured_single_line']=bool(bbox and (bbox[3]-bbox[1])<=fitted_height*1.7)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    def run():
        try:
            wait(lambda: page.project is not None and page.video.controller is not None and page.video.controller.running)
            page.volume_slider.setValue(0)
            page.video.controller.set_volume(0)
            page.video.set_paused(True)
            window.raise_(); window.activateWindow()
            mode=os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE','all')
            if mode in {'all','review','review-edit'}:
                from .studio_review import ReviewSession, ReviewScopeSnapshot
                ids=tuple(f'review-{i:02d}' for i in range(31))
                page._set_review_mode(True)
                page.cue_model.set_filter('all')
                page._review_session=ReviewSession(ReviewScopeSnapshot('all','','','',ids))
                page.continuous_review_toggle.setChecked(False)
                page.select_cue(ids[0]); pump(.25)
                for i in range(30):
                    page.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    target=page.timeline
                    if mode=='review-edit':
                        page._begin_canvas_inline_edit()
                        target=page._canvas_editor
                        target.setPlainText(page._cue_lookup[ids[i]].text+' 已校对')
                        target.setFocus()
                    counts={'list_reset':0,'ass':0}
                    def reset():counts['list_reset']+=1
                    page.cue_model.modelReset.connect(reset)
                    before_ass=page._ass_generation
                    started=time.perf_counter()
                    QTest.keyClick(target,Qt.Key.Key_Return)
                    selected_at=time.perf_counter()
                    row={'from':ids[i],'expected':ids[i+1],'actual':page.selected_cue_id,
                        'ms':(selected_at-started)*1000, 'list_resets':counts['list_reset'],
                        'ass_rebuilds':page._ass_generation-before_ass}
                    page.cue_model.modelReset.disconnect(reset)
                    result['enter'].append(row)
                    # Review editing normally requests a short contextual play;
                    # this latency audit only tests selection and seek.
                    page.video.set_paused(True)
                    pump(.12)
                    page.video.set_paused(True)
                values=sorted(r['ms'] for r in result['enter'])
                result['enter_summary']={'median_ms':(values[14]+values[15])/2,'p95_ms':values[28],
                    'correct':all(r['actual']==r['expected'] for r in result['enter'])}
                page._set_review_mode(False)
            if mode in {'all','style'}:
                for number,preset in enumerate(('game','livestream','dialogue-b','clean-white','default')):
                    page.select_cue('long')
                    page._seek(1.1); pump(.25)
                    page._apply_style_library_preset(preset); pump(.3)
                    # Real inspector edits reproduce a large single-line preset with rich shadow.
                    page.style_font_size.setValue(180)
                    page._apply_style(); pump(.45)
                    state(f'{number}-{preset}-paused')
                    started=time.perf_counter(); page.video.set_paused(False)
                    pump(.09); state(f'{number}-{preset}-first')
                    pump(.85); state(f'{number}-{preset}-1s')
                    pump(1.8); state(f'{number}-{preset}-3s')
                    pump(max(0,5.02-(time.perf_counter()-started))); page.video.set_paused(True)
                    result['playback_seconds'].append(time.perf_counter()-started)
                    page._seek(8.2); pump(.12); page._seek(1.1); pump(.25)
                    state(f'{number}-{preset}-seek')
                    page.video.set_paused(False); pump(.15); page.video.set_paused(True)
                    state(f'{number}-{preset}-replay')
                from .studio_project import save_project, load_project
                save_project(page.project,out/'saved.2byteproj')
                reopened=load_project(out/'saved.2byteproj')
                from .visual_snapshot import build_visual_cue_snapshot
                result['saved_reopened_hash']=build_visual_cue_snapshot(reopened,'long').glyph_hash()
                old=page.project
                page.undo_stack.setClean()
                from PySide6.QtCore import QMimeData,QUrl,QPoint,QPointF
                from PySide6.QtGui import QDragEnterEvent,QDropEvent
                mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(out/'saved.2byteproj'))])
                QApplication.sendEvent(page,QDragEnterEvent(QPoint(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
                QApplication.sendEvent(page,QDropEvent(QPointF(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
                wait(lambda:page.project is not old and not page._readiness.active,12)
                page.select_cue('long');page._seek(1.1);pump(.5)
                state('reopened-studio')
            result['passed']=all(r['actual']==r['expected'] for r in result['enter']) and all(
                r.get('measured_single_line',True) for r in result['states'])
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            if page.video.controller:page.video.set_paused(True)
            page.undo_stack.setClean()
            result['enter_profile']=getattr(page,'_review_enter_profile',[])
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            QTimer.singleShot(200,window.close)
    QTimer.singleShot(300,run)
