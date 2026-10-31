"""Opt-in actual-window evidence; all edits and failure injection use a copy."""
import json,time,traceback,hashlib,os

def start(window,out):
    from PySide6.QtCore import QTimer,QPoint,QPointF,Qt
    from PySide6.QtGui import QWheelEvent,QTextCursor,QImage
    from PySide6.QtWidgets import QApplication
    if window.built_page('studio') is None:
        QTimer.singleShot(100,lambda:start(window,out));return
    page=window.studio_page;t=page.timeline
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..projects.studio_project import load_project
    spec=json.loads((out/'input.json').read_text('utf8'))
    r=dict(passed=False,checks=[],edits=[],views=[],baseline=spec['baseline'],pid=os.getpid())
    for name in ('set_visible_window','_follow_scroll'):
        original=getattr(t,name)
        def observed(*args,_name=name,_original=original,**kwargs):
            before=(t.visible_start_ms,t.visible_duration_ms)
            result=_original(*args,**kwargs)
            after=(t.visible_start_ms,t.visible_duration_ms)
            if before!=after:
                r.setdefault('writers',[]).append(dict(time=time.perf_counter(),writer=_name,before=before,after=after,
                    callers=[frame.name for frame in traceback.extract_stack(limit=6)[:-1]]))
            return result
        setattr(t,name,observed)
    def check(name,ok,**detail):r['checks'].append(dict(name=name,passed=bool(ok),**detail))
    def capture(name):_capture(window,out/(name+'.png'));t.grab().save(str(out/(name+'-timeline.png')))
    def view(source):
        r['views'].append(dict(time=time.perf_counter(),source=source,start=t.visible_start_ms,
            visible=t.visible_duration_ms,end=t._duration_ms(),width=t._content_right()-t.TRACK_HEADER_WIDTH,
            padding=t._tail_padding_ms(),scroll=t.horizontal_scrollbar.value(),maximum=t.horizontal_scrollbar.maximum(),
            viewport_end=t.visible_start_ms+t.visible_duration_ms,
            pixels_per_second=(t._content_right()-t.TRACK_HEADER_WIDTH)*1000/t.visible_duration_ms,
            follow_hold=getattr(t,'_manual_view_hold',False),mode=getattr(t,'_view_mode',''),
            media_end=max((c.timeline_out_ms for track in page.project.video_tracks for c in track.clips),default=0)))
    def wheel(delta,ctrl=False):
        p=QPointF(t.TRACK_HEADER_WIDTH+600,t.RULER_HEIGHT+20)
        e=QWheelEvent(p,QPointF(t.mapToGlobal(p.toPoint())),QPoint(),QPoint(-delta,0),Qt.NoButton,
            Qt.ControlModifier if ctrl else Qt.NoModifier,Qt.ScrollUpdate,False)
        QApplication.sendEvent(t,e);view('ctrl_wheel' if ctrl else 'pan_wheel')
    def prepared_current():
        scene=getattr(page,'_caption_scene',None)
        return bool(scene and scene.published and scene.metrics and scene.last_result_token==scene.token
            and scene.token[2]==page._revision_store.render.visual_revision
            and any(x.get('cue_id')==page.selected_cue_id and x.get('snapshot_hash')==getattr(page._prepared_caption(page.selected_cue_id),'snapshot_hash',None)
                    for x in scene.metrics[-1].get('cue_pixels',())))
    def pixel_match(path):
        import numpy as np
        image=QImage(str(path));scene=page._caption_scene
        if image.isNull() or scene.published is None:return False
        def pixels(img):
            img=img.convertToFormat(QImage.Format_RGBA8888)
            return np.frombuffer(img.constBits(),np.uint8).reshape(img.height(),img.bytesPerLine())[:,:img.width()*4].reshape(img.height(),img.width(),4).copy()
        expected=pixels(scene.published.image);actual=pixels(image)
        yy,xx=np.where((expected[:,:,3]>250)&(expected[:,:,:3].max(axis=2)>80))
        if len(xx)<10:return False
        step=max(1,len(xx)//1500);xx,yy=xx[::step],yy[::step]
        x,y,w,h=scene.last_result_token[-4:]
        ax=((x+(xx+.5)*w/expected.shape[1])*image.width()/page.video.width()).astype(int)
        ay=((y+(yy+.5)*h/expected.shape[0])*image.height()/page.video.height()).astype(int)
        good=(ax>=0)&(ax<image.width())&(ay>=0)&(ay<image.height())
        if not good.any():return False
        difference=np.abs(actual[ay[good],ax[good],:3].astype(int)-expected[yy[good],xx[good],:3].astype(int)).max(axis=1)
        return float((difference<60).mean())>.72
    def steps():
        yield lambda:page.project is not None and page._readiness.ready and not page._readiness.active
        apply_theme(spec['theme']);page._set_volume(0);yield .3
        p=page.project;r['project_id']=p.project_id;r['cue_count']=len(p.cues);r['dpr']=t.devicePixelRatioF()
        key=p.studio_state.get('last_selected_cue');cue=next((c for c in p.cues if c.id==key),p.cues[-1])
        page.select_cue(cue.id);page._seek((cue.start_ms+cue.end_ms)/2000);yield 1
        yield prepared_current
        capture('before-edit')
        original=cue.text;final=original[:max(1,len(original)//2)]+'改'+original[max(1,len(original)//2)+1:]
        for label in ('partial','clear','all'):
            page.select_cue(cue.id);page._open_caption_editor(cue.id,'original');yield .08
            editor=page.subtitle_edit_input
            if label=='partial':
                c=editor.textCursor();at=max(1,len(original)//2);c.setPosition(at);c.setPosition(at+1,QTextCursor.KeepAnchor);c.insertText('改')
            else:
                editor.selectAll()
                if label=='clear':editor.insertPlainText('');yield .05
                editor.insertPlainText(final)
            sent=time.perf_counter();applied=page._end_caption_editor(keep_open=False)
            check(label+'_memory',applied and next(c for c in p.cues if c.id==cue.id).text==final)
            yield prepared_current
            png=out/(label+'-video.png');page.video.controller.screenshot_to_file(png,mode='window')
            yield lambda:png.exists() and png.stat().st_size>0
            matches=pixel_match(png)
            r['edits'].append(dict(path=label,submit_to_video_pixel_check_ms=(time.perf_counter()-sent)*1000,
                actual_video_pixels=matches,revision=page._revision_store.render.visual_revision))
            check(label+'_pixels',matches)
            errors=[];page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
            saved=load_project(page.project_path)
            check(label+'_disk',not errors and next(c for c in saved.cues if c.id==cue.id).text==final,errors=errors)
            page.undo_stack.undo();yield .15
            original=next(c for c in p.cues if c.id==cue.id).text
        capture('after-edit')
        # Other actual edit entries use the same target and final text.
        t._open_inline_editor(cue,False,cue.text);yield .08
        if t._inline_editor is not None:
            t._inline_editor.selectAll();t._inline_editor.insertPlainText(final);t._commit_inline_edit()
            check('timeline_entry',next(c for c in p.cues if c.id==cue.id).text==final and t._inline_editor is None)
            page.undo_stack.undo();yield .1
        else:check('timeline_entry',False)
        target=page._resolve_caption_edit_target(cue.id,'original')
        text=target.read(p)
        check('review_entry',page._commit_target_text_patch(target,0,len(text),final)
            and target.read(p)==final)
        page.undo_stack.undo();yield .1
        from ..studio.caption_editor import qt_position
        paths=[]
        for c in tuple(p.cues):
            for kind in ('partial','clear'):
                old=c.text;at=max(0,len(old)-1);wanted=old[:at]+'改'+old[at+1:]
                page.select_cue(c.id);page._open_caption_editor(c.id,'original')
                e=page.subtitle_edit_input
                if kind=='partial':
                    cursor=e.textCursor();cursor.setPosition(qt_position(old,at));cursor.setPosition(qt_position(old,min(len(old),at+1)),QTextCursor.KeepAnchor);cursor.insertText('改')
                else:e.selectAll();e.insertPlainText('');e.insertPlainText(wanted)
                ok=page._end_caption_editor(keep_open=False) and next(x for x in p.cues if x.id==c.id).text==wanted
                paths.append(dict(cue_id=c.id,path=kind,passed=ok))
                if not ok:raise AssertionError('Actual caption matrix retained draft '+c.id)
                page.undo_stack.undo()
                yield .01
        r['all_cue_matrix']=paths;check('all_cues_both_edit_paths',all(x['passed'] for x in paths),cases=len(paths))
        page.select_cue(cue.id);page._seek((cue.start_ms+cue.end_ms)/2000);yield .4
        for i in range(6):
            page._open_caption_editor(cue.id,'original');page.subtitle_edit_input.setPlainText(final+str(i));page._end_caption_editor(keep_open=False)
        yield prepared_current
        check('rapid_latest_text',next(c for c in p.cues if c.id==cue.id).text==final+'5')
        capture('rapid-latest')
        for i in range(6):page.undo_stack.undo()
        yield .2
        page._seek(.5);yield .6
        duration=t._duration_ms();t.set_visible_window(max(0,duration-90000+round(t._tail_padding_ms(90000)*.6)),90000);yield .3
        capture('tail');view('initial_tail')
        def media_digest():
            payload=p.to_dict()
            return hashlib.sha256(json.dumps({k:payload[k] for k in ('media','media_pool','video_tracks','audio_tracks','av_track_groups','cues','edit_sequence','render_settings')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        identity=media_digest()
        undo_index=page.undo_stack.index()
        for direction in (1,-1,1):
            for i in range(32):wheel(direction);yield .015
            yield .15
        view('before_idle');before=(t.visible_start_ms,t.visible_duration_ms)
        yield 2.5
        # Same paused decoder observation after the gesture timeout.
        page._apply_project_playhead(int(t.playhead_ms));yield .15
        view('after_idle');check('paused_view_stable',before==(t.visible_start_ms,t.visible_duration_ms))
        for direction in (1,-1):
            for i in range(18):wheel(direction,True);yield .015
        check('pure_view_no_undo',page.undo_stack.index()==undo_index)
        check('pure_view_no_media_change',media_digest()==identity)
        capture('tail-after-input')
        # Paint-only fixtures derived from this same real media graph. They
        # never replace the page project, save user data, or alter export data.
        import copy
        from dataclasses import replace
        from ..projects.studio_project import AudioClip,AudioTrack
        from ..timeline.studio_edit_sequence import sequence_of,replace_runtime_sequence
        from ..timeline.studio_media_pool import sync_primary_video_track_from_sequence,validate_media_graph
        waveform_cache=t.cache;waveform_sources=dict(t.waveform_caches)
        def paint_project(project):
            t.set_project(project)
            # Every fixture retains these exact asset IDs, canonical sources
            # and streams. Reuse the verified real-media waveform, not an
            # empty cache created by the paint-only project switch.
            t.set_cache(waveform_cache);t.waveform_caches.update(waveform_sources)
        t.set_visible_window(60000,10000);yield .2;capture('middle-no-false-tail')
        middle=dict(start=t.visible_start_ms,visible=t.visible_duration_ms,end=t._duration_ms())
        check('middle_true_end_offscreen',t._time_to_x(duration)>t._content_right()+8,**middle)
        gap=copy.deepcopy(p);seq=copy.deepcopy(sequence_of(gap));seg=seq.segments[-1]
        gap_left=seg.timeline_in_ms+60000;gap_right=seg.timeline_in_ms+80000
        seq.segments=[*seq.segments[:-1],replace(seg,id='fixture-left',source_out_ms=seg.source_in_ms+60000,timeline_out_ms=gap_left),
                      replace(seg,id='fixture-right',source_in_ms=seg.source_in_ms+80000,timeline_in_ms=gap_right)]
        replace_runtime_sequence(gap,seq);sync_primary_video_track_from_sequence(gap,seq);validate_media_graph(gap)
        paint_project(gap);t.set_visible_window(gap_left-15000,55000);yield .3;capture('real-media-gap')
        check('gap_intervals',[(c.timeline_in_ms,c.timeline_out_ms) for c in gap.video_tracks[0].clips][-2:]==[(seg.timeline_in_ms,gap_left),(gap_right,duration)])
        longer=copy.deepcopy(p);asset=longer.video_tracks[0].clips[0].asset_id
        longer.audio_tracks.append(AudioTrack('A-fixture-independent','独立音频',clips=[AudioClip('independent-tail',asset,
            source_in_ms=10000,source_out_ms=40000,timeline_in_ms=duration-5000,timeline_out_ms=duration+25000)]))
        validate_media_graph(longer);paint_project(longer);t.set_visible_window(duration-40000,85000)
        yield .3;capture('independent-audio-longer')
        check('independent_audio_own_end',longer.audio_tracks[-1].clips[0].timeline_out_ms==duration+25000
            and max(c.timeline_out_ms for track in longer.video_tracks for c in track.clips)==duration)
        short=copy.deepcopy(p);seq=copy.deepcopy(sequence_of(short));seg=seq.segments[0]
        seq.segments=[replace(seg,source_out_ms=seg.source_in_ms+100,timeline_out_ms=100)]
        replace_runtime_sequence(short,seq);sync_primary_video_track_from_sequence(short,seq)
        paint_project(short);t.set_visible_window(0,30000);yield .3;capture('very-short-clip')
        paint_project(p);t.set_visible_window(duration-90000+round(t._tail_padding_ms(90000)*.6),90000)
        check('original_document_preserved_after_variants',media_digest()==identity)
        r['passed']=all(x['passed'] for x in r['checks'])
    iterator=iter(steps());waiting=dict(condition=None,deadline=0,until=0);state=dict(busy=False)
    timer=QTimer(window);timer.setInterval(10)
    def save():
        (out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str),'utf8')
        (out/'continuous-views.jsonl').write_text('\n'.join(json.dumps(x) for x in r['views']),'utf8')
    def finish():
        timer.stop();save();page.undo_stack.setClean();window.close();QTimer.singleShot(600,QApplication.instance().quit)
    def tick():
        now=time.perf_counter()
        if state['busy']:return
        state['busy']=True
        try:
            if waiting['condition']:
                if waiting['condition']():waiting['condition']=None
                elif now>waiting['deadline']:raise TimeoutError('Actual-window condition timed out')
                else:return
            if now<waiting['until']:return
            item=next(iterator)
            if callable(item):waiting.update(condition=item,deadline=now+45)
            else:waiting['until']=now+float(item or 0)
        except StopIteration:finish()
        except BaseException:
            r['error']=traceback.format_exc()
            try:capture('failure')
            except Exception:pass
            finish()
        finally:state['busy']=False
    def shutdown():r['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown);timer.timeout.connect(tick);timer.start()
