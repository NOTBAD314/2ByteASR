"""Opt-in real-media timeline interactions and input-to-painted-marker receipts."""
import copy
import hashlib
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit
    if window.built_page('studio') is None:
        QTimer.singleShot(100, lambda:start(window, output))
        return
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..projects.project_range import set_range, range_points, validated_range
    from ..projects.studio_project import save_project, load_project
    from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
    from ..diagnostics.build_identity import load_build_identity
    from ..runtime_paths import get_runtime_paths

    spec = json.loads((output/'input.json').read_text('utf-8'))
    baseline = spec['baseline']; page = window.studio_page
    result = dict(passed=False, checks=[], samples={}, screenshots=[], baseline=baseline,
                  identity=load_build_identity().to_dict(), runtime_paths=get_runtime_paths().to_dict())
    log = (output/'operations.jsonl').open('w',encoding='utf-8')
    state = dict(phase='', pending=None, gap_time=time.perf_counter(), busy=False)
    gaps = {}; samples = result['samples']

    def event(kind, **data):
        log.write(json.dumps(dict(t=time.perf_counter(),kind=kind,**data),ensure_ascii=False,default=str)+'\n'); log.flush()

    def check(name, passed, detail=None):
        row = dict(name=name,passed=bool(passed),detail=detail)
        result['checks'].append(row); event('check',**row)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def capture(name):
        state['phase']=''
        _capture(window, output/(name+'.png'))
        page.timeline.grab().save(str(output/(name+'-timeline.png')))
        result['screenshots'].append(name); event('capture',name=name)

    def phase(name):
        state.update(phase=name, gap_time=time.perf_counter())

    def color_column(t, value, row, color):
        image=t.grab().toImage();dpr=image.devicePixelRatio()
        x=round(t._time_to_x(value)*dpr)
        count=0
        for y in range(max(0,round((row.top()+5)*dpr)),min(image.height(),round((row.bottom()-5)*dpr))):
            if any(max(abs(image.pixelColor(xx,y).red()-color.red()),abs(image.pixelColor(xx,y).green()-color.green()),
                       abs(image.pixelColor(xx,y).blue()-color.blue()))<32
                   for xx in range(max(0,x-2),min(image.width(),x+3))):
                count+=1
        return count

    def geometry(project):
        return {kind:[(track.id,[(c.id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms,c.playback_rate)
                     for c in track.clips]) for track in tracks]
                for kind,tracks in [('video',project.video_tracks),('audio',project.audio_tracks)]}

    def point(t, value, lane='V1', audio=False):
        rows = t._audio_track_rects() if audio else t._video_track_rects()
        return QPoint(round(t._time_to_x(value)),round(rows[lane].center().y()))

    def move(t, pos):
        top=t.window(); QTest.mouseMove(top.windowHandle(),t.mapTo(top,pos))

    def button(t,pos,release=False):
        top=t.window()
        (QTest.mouseRelease if release else QTest.mousePress)(top.windowHandle(),Qt.LeftButton,Qt.NoModifier,t.mapTo(top,pos))

    def instrument(t):
        cls=type(t); old_move,old_paint=cls.mouseMoveEvent,cls.paintEvent
        def moving(self,event_):
            before=time.perf_counter(); old_move(self,event_)
            if self is t and state['phase']:
                samples.setdefault(state['phase']+'_handler_ms',[]).append((time.perf_counter()-before)*1000)
        def painting(self,event_):
            before=time.perf_counter(); old_paint(self,event_)
            if self is t and state['pending']:
                pending=state['pending']; phase=pending['phase']
                if phase=='razor' and not getattr(self,'_media_cut',None):return
                if phase=='range' and not getattr(self,'_range_drag',None):return
                samples.setdefault(phase+'_paint_latency_ms',[]).append((time.perf_counter()-pending['sent'])*1000)
                samples.setdefault(phase+'_paint_work_ms',[]).append((time.perf_counter()-before)*1000)
                samples.setdefault(phase+'_static_cache_hit',[]).append(bool(getattr(self,'_last_paint_stats',{}).get('static_cache_hit')))
                state['pending']=None
        cls.mouseMoveEvent,cls.paintEvent=moving,painting
        old_view=cls.set_visible_window
        def viewing(self,start,duration):
            before=(self.visible_start_ms,self.visible_duration_ms,self.width())
            old_view(self,start,duration)
            after=(self.visible_start_ms,self.visible_duration_ms,self.width())
            if self is t and before!=after and not state['phase']:
                event('viewport',before=before,after=after,requested=(start,duration),
                      caller=[f'{f.name}:{f.lineno}' for f in traceback.extract_stack(limit=5)[:-1]])
        cls.set_visible_window=viewing

    def steps():
        apply_theme(spec['theme'])
        window.resize(1840,1050); window.show()
        window.open_studio_project(spec['project'],mode='edit',source='timeline_operations_audit')
        yield ready
        t=page.timeline; p=page.project
        t.setMinimumHeight(430)
        t.set_track_heights({'subtitle':72,'video':66,'audio':84})
        yield lambda:t.waveform_state in ('READY','ERROR')
        check('real waveform available',t.waveform_state=='READY',t.waveform_state)
        check('all write roots isolated',all(str(output).casefold() in str(value).casefold()
              for key,value in result['runtime_paths'].items() if key in ('user_data_root','project_root','config_root','cache_root','log_root','temp_root')))
        result.update(cues=len(p.cues),dpr=t.devicePixelRatioF(),media=p.media.path,
                      project_duration_ms=timeline_duration_ms(p),original_geometry=geometry(p))
        instrument(t)
        t.set_visible_window(232000,18000); t.set_playhead(239033)
        page._timeline_scrub.request(239.033)
        if not baseline:
            page._clear_range();t.setFocus();t.set_playhead(237000)
            QTest.keyClick(t,Qt.Key_I);yield .12
            check('I shortcut sets single endpoint',range_points(p)==(237000,None),range_points(p))
            capture('single-I')
            t.set_playhead(243000);QTest.keyClick(t,Qt.Key_O);yield .12
            check('O shortcut sets range',range_points(p)==(237000,243000),range_points(p))
            page.cue_search.setFocus();QTest.keyClicks(page.cue_search,'ioIO');yield .08
            check('text input keeps I/O letters',page.cue_search.text()=='ioIO' and range_points(p)==(237000,243000))
            page.cue_search.clear();t.setFocus()
            page._clear_range();yield .08
            check('clear removes both endpoint visuals',range_points(p)==(None,None) and not t._range_handles())
        set_range(p,237000,243000)
        t.set_playhead(239033)
        yield 2
        t.set_tool_mode('razor')
        target=point(t,239610); move(t,target)
        yield .3
        capture('01-razor-preview')
        cut=getattr(t,'_media_cut',None)
        check('video hover preview available',bool(cut) or baseline,dict(supported=bool(cut),cut=str(cut)))
        if cut:
            from ..studio.timeline_razor import razor_colors
            color=razor_colors(t._timeline_palette())['cut']
            counts={name:color_column(t,cut.split_ms,row,color) for name,row in
                    [('video',t._video_track_rect('V1')),('audio',next(iter(t._audio_track_rects().values())))]}
            check('actual cut-color pixels traverse video and waveform',all(n>=6 for n in counts.values()),counts)
        original=geometry(p); count=page.undo_stack.index()
        phase('razor')
        for i in range(48):
            pos=point(t,235500+i*133)
            state['pending']=dict(phase='razor',sent=time.perf_counter())
            move(t,pos)
            yield .024
        state['phase']='';state['pending']=None
        check('hover edits nothing',geometry(p)==original and page.undo_stack.index()==count)
        move(t,target);yield .12
        cut=getattr(t,'_media_cut',None)
        result['cut_before_commit']=str(cut)
        button(t,target);button(t,target,True)
        yield .6
        split_geometry=geometry(p)
        values=[c.timeline_in_ms for track in p.video_tracks if track.id=='V1' for c in track.clips]
        if cut:
            check('actual cut equals painted preview',cut.split_ms in values,dict(cut=cut.split_ms,starts=values))
            check('cut is not replaced by playhead',cut.split_ms!=0)
            linked=[a for track in p.audio_tracks for a in track.clips if a.timeline_in_ms==cut.split_ms]
            check('linked audio splits at same time',bool(linked),[(a.source_in_ms,a.timeline_in_ms) for a in linked])
        check('ordinary split preserves total duration',timeline_duration_ms(p)==result['project_duration_ms'])
        capture('02-actual-cut')
        page.undo_stack.undo();yield .25
        check('undo restores AV geometry',geometry(p)==original)
        page.undo_stack.redo();yield .25
        check('redo restores both split children',geometry(p)==split_geometry)
        # Same version, same source project: finite manual zoom and viewport tail.
        t.set_tool_mode('selection')
        t.set_visible_window(233000,16000); anchor=t._time_to_x(239000)
        for duration in (12000,24000,6000,18000):
            t.set_visible_window(239000-duration//2,duration)
            yield .08
            check('shared one-second scale '+str(duration),abs(t._time_to_x(240000)-t._time_to_x(239000)
                   -(t._content_right()-t.TRACK_HEADER_WIDTH)*1000/t.visible_duration_ms)<.001)
        selected_window=(t.visible_start_ms,t.visible_duration_ms)
        t.set_selected(p.cues[178].id); t.refresh_media_graph()
        yield .2
        check('selection and refresh preserve manual zoom',(t.visible_start_ms,t.visible_duration_ms)==selected_window)
        capture('03-manual-zoom')
        # Markers remain true when offscreen, never moved to the viewport edge.
        t.set_visible_window(300000,18000); yield .2;capture('04-range-offscreen')
        check('offscreen I/O retains exact time',range_points(p)==(237000,243000))
        t.set_visible_window(232000,18000);yield .15
        if not baseline:
            index=page.undo_stack.index()
            handle=next(h for h in t._range_handles() if h[0]==0)
            pos=handle[3].center().toPoint();button(t,pos)
            phase('range')
            for i in range(24):
                value=237000+i*45
                state['pending']=dict(phase='range',sent=time.perf_counter())
                move(t,QPoint(round(t._time_to_x(value)),7));yield .024
            state['phase']='';state['pending']=None
            check('I/O preview does not write document',range_points(p)==(237000,243000))
            button(t,QPoint(round(t._time_to_x(value)),7),True);yield .25
            check('I/O release commits once',page.undo_stack.index()==index+1)
            after=range_points(p);page.undo_stack.undo();yield .15
            check('I/O undo restores endpoints',range_points(p)==(237000,243000))
            page.undo_stack.redo();yield .15
            check('I/O redo restores endpoints',range_points(p)==after)
        capture('05-range-handles')
        if not baseline:
            saved=range_points(p);set_range(p,238000,238020);yield .08
            handles=t._range_handles()
            check('near endpoints keep distinct handles',len(handles)==2 and not handles[0][3].intersects(handles[1][3]))
            capture('range-near-endpoints');set_range(p,*saved)
        # Existing seam near the actual tail: true edges + outboard hit target.
        total=timeline_duration_ms(p); t.set_visible_window(total-15000,20000);yield .4
        tail=max((c for track in p.video_tracks for c in track.clips),key=lambda c:c.timeline_out_ms)
        edge=point(t,tail.timeline_out_ms)
        margin=t._content_right()-t._time_to_x(total)
        result['tail_margin_px']=margin
        check('tail has operation space',margin>=30 or baseline,margin)
        capture('06-tail-before-trim')
        # Baseline gets its existing inner target; revised checks 9px outside.
        edge.setX(edge.x()+(-2 if baseline else 9))
        move(t,edge);yield .1;button(t,edge);yield .1
        drag=t._clip_drag
        check('true right edge is easy to hit',bool(drag and drag['mode']=='trim_right'))
        trim_original=geometry(p)
        trim_window=(t.visible_start_ms,t.visible_duration_ms)
        if drag:
            phase('trim')
            for i in range(24):
                pos=QPoint(edge.x()-12-i*2,edge.y())
                state['pending']=dict(phase='trim',sent=time.perf_counter())
                move(t,pos);yield .024
            state['phase']='';state['pending']=None
            check('trim hover leaves document intact',geometry(p)==trim_original)
            capture('07-tail-trim-preview')
            button(t,pos,True);yield .4
            check('trim keeps requested playback rate',all(c.playback_rate==1 for track in p.video_tracks for c in track.clips))
            page.undo_stack.undo();yield .2
            check('trim undo restores exact AV map',geometry(p)==trim_original)
            if not baseline:
                check('trim commit and undo keep viewport',(t.visible_start_ms,t.visible_duration_ms)==trim_window,
                      dict(before=trim_window,after=(t.visible_start_ms,t.visible_duration_ms)))
                t.set_visible_window(total-15000,20000);yield .1
                # Restore real remaining source material outward, then undo.
                edge=point(t,total);edge.setX(edge.x()+6)
                move(t,QPoint(t.TRACK_HEADER_WIDTH+10,2));yield .04
                move(t,edge);yield .08;button(t,edge);yield .06
                pos=QPoint(edge.x()+32,edge.y());move(t,pos);yield .1
                preview=t._clip_drag
                check('outward trim previews available source',bool(preview and preview['preview_out']>total),str(preview and preview.get('invalid')))
                button(t,pos,True);yield .3
                check('outward trim extends time without changing speed',timeline_duration_ms(p)>total
                      and all(c.playback_rate==1 for track in p.video_tracks for c in track.clips))
                page.undo_stack.undo();yield .2
                check('outward trim undo restores exact source limits',geometry(p)==trim_original)
        # Normal application save, then a real parse and normal reopen.
        saved_geometry=geometry(p);saved_range=range_points(p)
        saved_window=(t.visible_start_ms,t.visible_duration_ms)
        page.save();yield .8
        loaded=load_project(spec['project'])
        check('saved geometry and I/O round trip',geometry(loaded)==saved_geometry and range_points(loaded)==saved_range)
        check('export range remains document I/O',validated_range(loaded)==validated_range(p))
        result['final_geometry']=saved_geometry;result['export_range_ms']=validated_range(p)
        window.open_studio_project(spec['project'],mode='edit',source='timeline_operations_reopen');yield ready;yield .6
        check('normal reopen keeps AV map and range',geometry(page.project)==saved_geometry and range_points(page.project)==saved_range)
        if not baseline:
            check('save/reopen keeps explicit manual view',(t.visible_start_ms,t.visible_duration_ms)==saved_window,
                  dict(before=saved_window,after=(t.visible_start_ms,t.visible_duration_ms)))
        capture('08-reopened')
        if not baseline:
            # All existing themes, on the same project and actual widget.
            from ..design.theme_manager import available_themes
            for theme in available_themes():
                apply_theme(theme.key);t.refresh_theme_palette()
                t.set_visible_window(232000,18000);t.set_tool_mode('razor');move(t,point(t,240500));yield .12
                cut=t._media_cut
                from ..studio.timeline_razor import razor_colors
                color=razor_colors(t._timeline_palette())['cut']
                count=color_column(t,cut.split_ms,next(iter(t._audio_track_rects().values())),color) if cut else 0
                check('razor visible in theme '+theme.key,count>=6,count)
                capture('theme-'+theme.key)
            apply_theme(spec['theme']);t.refresh_theme_palette()
            # Fixture variants retain the real 573 captions, source media and
            # source offset. Only link/lock/target conditions change here.
            from ..timeline.studio_media_pool import create_video_track, add_video_clip
            for variant in ('unlinked','audio-locked','video-locked','target-V2','audio-only','source-limit','short-fast'):
                v=load_project(spec['project'])
                group=next(g for g in v.av_track_groups if g.video_track_id=='V1')
                audio=next(a for a in v.audio_tracks if a.id==group.audio_track_id)
                lane='V1';at=238500
                if variant in ('unlinked','audio-only'):group.linked=False
                if variant=='audio-locked':audio.locked=True
                if variant=='video-locked':v.video_tracks[0].locked=True;sequence_of(v).video_track_locked=True
                if variant in ('target-V2','source-limit','short-fast'):
                    lane=create_video_track(v,'V2').id
                    base=v.video_tracks[0].clips[0]
                    if variant=='source-limit':
                        asset=next(a for a in v.media_pool if a.asset_id==base.asset_id)
                        add_video_clip(v,lane,base.asset_id,timeline_in_ms=235000,
                                       source_in_ms=asset.duration_ms-5000,source_out_ms=asset.duration_ms)
                    elif variant=='short-fast':
                        child=add_video_clip(v,lane,base.asset_id,timeline_in_ms=235000,
                                       source_in_ms=base.source_in_ms+235000,source_out_ms=base.source_in_ms+235333)
                        child.playback_rate=2.;child.timeline_out_ms=235167
                        from ..projects.studio_project import sync_linked_av_contract
                        sync_linked_av_contract(v)
                        at=235083
                    else:
                        add_video_clip(v,lane,base.asset_id,timeline_in_ms=235000,
                                       source_in_ms=base.source_in_ms+235000,source_out_ms=base.source_in_ms+245000)
                file=output/(variant+'.2byteproj');save_project(v,file)
                window.open_studio_project(str(file),mode='edit',source='timeline_operations_matrix')
                yield ready;yield .2
                v=page.project;t=page.timeline;t.set_visible_window(232000,18000);t.set_tool_mode('razor')
                if variant=='short-fast':t.set_visible_window(234800,1000)
                if variant=='source-limit':
                    t.set_tool_mode('selection');t.set_visible_window(234000,8000)
                    pos=point(t,240000,lane);pos.setX(pos.x()+5);move(t,pos);yield .1
                    before=geometry(v);button(t,pos);yield .1
                    dest=QPoint(pos.x()+65,pos.y());move(t,dest);yield .1
                    drag=t._clip_drag
                    check('source end reports limit without fake extension',bool(drag and drag.get('limit')
                          and drag['preview_out']==240000),str(drag and drag.get('limit')))
                    capture('matrix-source-limit')
                    button(t,dest,True);yield .15
                    check('source limit leaves document unchanged',geometry(v)==before)
                    page.save();yield .1
                    continue
                if variant=='audio-only':
                    pos=point(t,at,audio.id,True)
                else:pos=point(t,at,lane)
                move(t,QPoint(t.TRACK_HEADER_WIDTH+10,2));yield .04
                move(t,pos);yield .12
                cut=t._media_cut;before=geometry(v);index=page.undo_stack.index()
                check(variant+' preview resolves target',cut is not None,str(cut))
                capture('matrix-'+variant+'-preview')
                button(t,pos);button(t,pos,True);yield .25
                after=geometry(v)
                if 'locked' in variant:
                    check(variant+' rejects entire linked edit',after==before and page.undo_stack.index()==index)
                elif variant=='audio-only':
                    check('independent audio cut leaves picture intact',after['video']==before['video'] and after['audio']!=before['audio'])
                elif variant=='unlinked':
                    check('unlinked video cut leaves audio intact',after['audio']==before['audio'] and after['video']!=before['video'])
                else:
                    check('V2 cut leaves V1 intact',after['video'][0]==before['video'][0]
                          and after['video'][1]!=before['video'][1])
                capture('matrix-'+variant+'-after')
                if 'locked' not in variant:
                    page.undo_stack.undo();yield .12
                    check(variant+' undo restores source map',geometry(v)==before)
                page.save();yield .15
            window.open_studio_project(spec['project'],mode='edit',source='timeline_operations_return')
            yield ready;yield .2
        result['passed']=all(c['passed'] for c in result['checks'])

    iterator=steps(); wait=dict(condition=None,until=0.,deadline=0.)
    timer=QTimer(window);timer.setInterval(5)
    def save():
        result['timings']={}
        for name,values in samples.items():
            if values and not name.endswith('static_cache_hit'):
                ordered=sorted(values)
                result['timings'][name]=dict(n=len(values),median=ordered[len(values)//2],p95=ordered[min(len(values)-1,int(len(values)*.95))],maximum=max(values))
        result['gui_gap_ms']={k:dict(maximum=max(v),samples=v) for k,v in gaps.items() if v}
        result['failures']=[r for r in result['checks'] if not r['passed']]
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def finish():
        timer.stop();state['phase']='';save();log.close()
        if page.project is not None:page.save()
        page.undo_stack.setClean();window.close()
        QTimer.singleShot(500,QApplication.instance().quit)
    def tick():
        now=time.perf_counter()
        if state['phase']:gaps.setdefault(state['phase'],[]).append((now-state['gap_time'])*1000)
        state['gap_time']=now
        if state['busy']:return
        state['busy']=True
        try:
            if wait['condition']:
                if wait['condition']():wait['condition']=None
                elif now>wait['deadline']:raise TimeoutError('UI condition timed out')
                else:return
            if now<wait['until']:return
            value=next(iterator)
            if callable(value):wait.update(condition=value,deadline=now+180)
            else:wait['until']=now+float(value or 0)
        except StopIteration:finish()
        except BaseException:
            result['error']=traceback.format_exc()
            try:capture('failure')
            except Exception:pass
            finish()
        finally:state['busy']=False
    def shutdown():
        result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick);timer.start()
