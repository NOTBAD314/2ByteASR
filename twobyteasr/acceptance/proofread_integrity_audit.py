"""Owned-window proofread checks; synthetic text is labelled, no provider call."""
import json,os,time,traceback


def start(window,out):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500,lambda:run(window,out))


def run(window,out):
    from PySide6.QtCore import Qt,QPoint,QTimer
    from PySide6.QtWidgets import QApplication,QScrollArea
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,load_project,save_project
    from ..subtitle_rules.subtitle_translation import set_manual,records_of
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    app=QApplication.instance();checks=[];timings=[];error=None;review=None
    identity=load_build_identity().to_dict()
    def pump(seconds=.05):
        until=time.perf_counter()+seconds
        while time.perf_counter()<until:app.processEvents();time.sleep(.003)
    def wait(predicate,timeout=60):
        until=time.perf_counter()+timeout
        while not predicate() and time.perf_counter()<until:pump(.02)
        if not predicate():raise TimeoutError(str(predicate))
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail))
        if not value:raise AssertionError(name+': '+str(detail))
    def show(project,path):
        nonlocal review
        window._show_glossary_proofread(str(path),project)
        review=window.glossary_proofread_page
        wait(lambda:not review.checks_running())
        review.text_targets.mode.setCurrentIndex(review.text_targets.mode.findData('both'))
        wait(lambda:not review.checks_running());pump(.15)
        return review
    def shot(name):
        from .blank_project_audit import _capture
        _capture(window,out/(name+'.png'))
        window.grab().save(str(out/(name+'-qt.png')))
    def fixture(count):
        p=SubtitleProject(StudioMedia('',duration_ms=count*3000+2000),
            speakers=[StudioSpeaker('A','甲'),StudioSpeaker('B','乙')],
            cues=[StudioCue(f'fixture-{i:05d}',(i//2)*3000,(i//2)*3000+2500,
                f'共通 あーギリギリセーフ {i}','AB'[i%2]) for i in range(count)],
            generation_metadata={'language':{'code':'ja'}})
        p.validate()
        for cue in p.cues[:-1]:set_manual(p,cue.id,f'共通 啊——勉强赶上了 {cue.id}',target='zh-Hans')
        return p
    try:
        actual=load_project(out/'real.2byteproj');show(actual,out/'real.2byteproj')
        window.showNormal();pump(.2)
        owner=actual.cues[0].id
        translated=next((r['cue_id'] for r in review._rows if r['target'].storage=='translation'
                        and r['target'].cue_id==owner),owner)
        review._play(translated);wait(lambda:review._player.state=='playing',20)
        check('actual output binds translation to the same original audio',review._player.last_plan.cue_id==owner
            and review._player._expected_ms==actual.cues[0].end_ms-actual.cues[0].start_ms)
        review._play(owner);check('shared original button pauses same request',review._player.state=='paused')
        review._play(translated);wait(lambda:not review._player.cue_id,20)
        check('actual finite original audio finishes after resume',review._player.state=='')
        check('current real project count uses stable subtitles',review._filter_counts['all']==len(actual.cues),
              dict(current_cues=len(actual.cues),groups=len(review._group_indices),fields=len(review._rows),screenshot_cues=282))
        for theme in ('warm','grape'):
            apply_theme(theme,app);window.refresh_theme_palette();pump(.15)
            # At forced Qt 1x on this physical 175% monitor, Windows' native
            # 640-DIP minimum is 1120px. Keep that simulation legal; exercise
            # 1024 logical pixels separately with matching native Qt DPI.
            sizes = ((1600,1000),(1180,800),(1024,720)) if os.environ.get('TWOBYTEASR_ACCEPTANCE_NATIVE_DPI') else ((1600,1000),(1280,800),(1180,720))
            for width,height in sizes:
                window.resize(width,height);pump(.18);review.list.repaint();pump(.03)
                window.resize(width,height);pump(.05)  # responsive sidebar releases its former minimum
                from ..app.window_constraints import native_frame
                native=native_frame(window)
                client=native['client'] if native else None
                expected=(round(window.width()*window.devicePixelRatioF()),round(window.height()*window.devicePixelRatioF()))
                check(f'{theme} {width} native client agrees with Qt',bool(client) and
                    abs(client[2]-client[0]-expected[0])<=2 and abs(client[3]-client[1]-expected[1])<=2,
                    dict(native=native,qt=[window.width(),window.height()],dpr=window.devicePixelRatioF()))
                check(f'{theme} {width} requested height fits',window.height()<=height,
                    dict(requested=height,actual=window.height()))
                check(f'{theme} {width} requested width fits',window.width()<=width,
                    dict(requested=width,actual=window.width()))
                check(f'{theme} {width} main list reachable',review.list.isVisible() and review.list.height()>=100,
                    dict(window=[window.width(),window.height()],list=review.list.geometry().getRect()))
                for widget in (review.search,review.ai_button,review.undo_button,review.batch_all,review.select_all):
                    review.page_scroll.ensureWidgetVisible(widget,8,8);pump(.02)
                    check(f'{theme} {width} reachable '+widget.objectName(),widget.isVisible() and review.rect().contains(widget.mapTo(review,QPoint(0,0)))
                        and review.rect().contains(widget.mapTo(review,QPoint(widget.width()-1,widget.height()-1))),
                        dict(name=widget.objectName(),size=[widget.width(),widget.height()]))
                review.page_scroll.verticalScrollBar().setValue(0);pump(.03)
                shot(f'{theme}-{width}')
                if review.sidebar_button.isVisible():
                    sidebar=[]
                    def inspect_sidebar():
                        dialog=app.activeModalWidget()
                        try:
                            sidebar.append(bool(dialog and review.left_panel.isVisible() and review._sidebar_open))
                            scroll=review.left_panel.findChild(QScrollArea,'proofreadLeftScroll')
                            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                            pump(.02);dialog.grab().save(str(out/f'{theme}-{width}-sidebar.png'))
                        finally:
                            if dialog is not None:dialog.reject()
                    QTimer.singleShot(100,inspect_sidebar)
                    QTest.mouseClick(review.sidebar_button,Qt.LeftButton);pump(.04)
                    check(f'{theme} {width} sidebar remains accessible',sidebar==[True] and not review._sidebar_open)
        p=fixture(282);path=out/'fixture282.2byteproj';save_project(p,path);show(p,path)
        check('282 bilingual subtitles remain 282 groups',review._filter_counts['all']==282 and len(review._group_indices)==282)
        check('missing translation is a state not generated text',len(review._rows)==563 and review._by_id[p.cues[-1].id]['translation_missing'])
        check('same-time different speakers keep separate owners',all(
            all(review._rows[i]['target'].cue_id==owner for i in indices) for owner,indices in review._group_indices.items()))
        window.resize(1600,1000);pump(.2);review.list.repaint();pump(.04)
        play=[hit for hit in review.list._hit_boxes if hit[1]=='play']
        boxes=[hit for hit in review.list._hit_boxes if hit[1]=='rowcheck']
        check('one play and selection per visible group',len(play)==len(boxes) and len(play)>0 and
            len({review._by_id[hit[2]]['group_id'] for hit in play})==len(play))
        review.search.setText('共通');pump(.25);review._apply_filter()
        check('both fields contribute separate search matches',len(review._hits)==563)
        keys=[]
        for _ in range(4):review._step_hit(1);keys.append(review.list.find['current'][0])
        check('next match visits both fields within one group',len(set(keys))==4 and
            review._by_id[keys[0]]['group_id']==review._by_id[keys[1]]['group_id'])
        key=keys[1];row=review._by_id[key];owner=row['target'].cue_id;before=records_of(p)[owner]['text']
        source=next(c.text for c in p.cues if c.id==owner)
        review._edit(key);review.list.editor.setText(before+' 確認');QTest.keyClick(review.list.editor,Qt.Key_Return);pump(.15)
        check('translation editor commits to translation only',records_of(p)[owner]['text']==before+' 確認' and next(c.text for c in p.cues if c.id==owner)==source)
        review._undo();pump(.1);check('undo restores exact translation',records_of(p)[owner]['text']==before)
        review._redo();pump(.1);check('redo stays on same language field',records_of(p)[owner]['text']==before+' 確認')
        review._undo();review.search.setText('勉强');pump(.25);review.replace_input.setText('成功');pump(.15)
        review._replace_enter();pump(.2)
        check('scoped replacement changes translations only',all('成功' in records_of(p)[c.id]['text'] for c in p.cues[:-1])
            and all('ギリギリ' in c.text for c in p.cues))
        review._undo();pump(.15);check('batch replacement undo retains source identities',len(p.cues)==282 and all('勉强' in records_of(p)[c.id]['text'] for c in p.cues[:-1]))
        review.search.clear();review.replace_input.clear();pump(.25);shot('paired-282')
        # Synthetic provider result, through the real QThread/page callback.
        # This checks field ownership and counts, not model/content quality.
        def stand_in(view,wanted,snapshot,settings,**kwargs):
            from types import SimpleNamespace
            from ..glossary.studio_glossary_service import GlossaryReviewPreview
            from ..glossary.studio_glossary_review import diff_occurrences
            from ..studio.subtitle_text_targets import bind_occurrence
            hits=[]
            for entry in view._review_text_entries.values():
                if entry.target.cue_id!='fixture-00000':continue
                replacement=entry.text.replace('共通','共用' if entry.target.layer=='original' else '共有',1)
                if entry.target.layer=='translation':replacement=replacement.replace('勉强','成功',1)
                cue=SimpleNamespace(id=entry.key,text=entry.text,start_ms=entry.start_ms)
                hits.extend(bind_occurrence(hit,entry) for hit in diff_occurrences(cue,replacement,
                    reason='合成候选，仅验证操作身份',source='translation_ai',selected=False))
            return GlossaryReviewPreview(tuple(hits),dict(successful_cues=len(wanted),checked_cues=len(wanted),fallback_cues=0,
                pending_rows=[],request_errors=[],failed_cues=[],segments=[],run_state='completed'))
        review.ai_stand_in=stand_in
        QTest.mouseClick(review.ai_button,Qt.LeftButton);wait(lambda:not review.checks_running());pump(.15)
        check('one subtitle with three synthetic suggestions counts once',review._filter_counts['suggested']==1
            and review.proposal_counts()['proposals']==3)
        check('completion uses text units', '段文本' in review.status_label.text())
        shot('paired-suggestions')
        QTest.mouseClick(review.batch_all,Qt.LeftButton);QTest.mouseClick(review.batch_adopt,Qt.LeftButton);pump(.1)
        check('batch adoption writes both addressed fields once','共用' in p.cues[0].text and '共有' in records_of(p)['fixture-00000']['text']
            and '成功' in records_of(p)['fixture-00000']['text'] and review.proposal_counts()['changed']==1)
        review._undo();pump(.1)
        check('one undo restores both fields','共通' in p.cues[0].text and '勉强' in records_of(p)['fixture-00000']['text'])
        QTest.mouseClick(review.batch_all,Qt.LeftButton);QTest.mouseClick(review.batch_ignore,Qt.LeftButton);pump(.1)
        check('ignore updates group count without editing texts',review._filter_counts['pending']==0 and '共通' in p.cues[0].text)
        review._undo();pump(.1);check('ignore undo restores three proposals',review.proposal_counts()['remaining']==3)
        def fail(*_args,**_kwargs):raise RuntimeError('离线失败注入，仅验证状态')
        review.ai_stand_in=fail;QTest.mouseClick(review.ai_button,Qt.LeftButton)
        wait(lambda:not review.checks_running());pump(.1)
        check('failed request preserves valid proposals and releases controls',review.proposal_counts()['remaining']==3
            and review.ai_button.isEnabled() and not review.cancel_button.isVisible())
        review.ai_stand_in=None
        large=fixture(2000);largepath=out/'fixture2000.2byteproj';save_project(large,largepath)
        started=time.perf_counter();show(large,largepath);timings.append(dict(action='open2000',ms=(time.perf_counter()-started)*1000))
        resets=[];full_layouts=[];original_set_rows=review.list.set_rows
        def counted(*args,**kwargs):resets.append(1);return original_set_rows(*args,**kwargs)
        review.list.set_rows=counted
        original_layout=review.list._layout_rows
        def counted_layout(*args,**kwargs):full_layouts.append(1);return original_layout(*args,**kwargs)
        review.list._layout_rows=counted_layout
        for n in range(20):
            started=time.perf_counter();review.list.bar.setValue(round(review.list.bar.maximum()*((n*7)%20)/19));pump(.025)
            timings.append(dict(action='scroll2000',ms=(time.perf_counter()-started)*1000))
        check('2000 group scrolling reuses virtual list',not resets and len(review.list._layout_cache)<=1024,
              dict(shapes=len(review.list._layout_cache),groups=len(review._group_indices)))
        row=review._by_id['fixture-00008'];review._edit_committed(row['cue_id'],row['base']+' 確認');pump(.1)
        check('single edit does not rebuild full rows',not resets and not full_layouts,
              dict(resets=len(resets),full_layouts=len(full_layouts)))
        review._undo();pump(.1);shot('paired-2000')
    except Exception:
        error=traceback.format_exc();(out/'error.txt').write_text(error,'utf8');shot('failure')
    finally:
        if review is not None:review.shutdown()
        result=dict(passed=bool(checks) and not error and all(c['passed'] for c in checks),checks=checks,timings=timings,
            error=error,identity=identity,pid=os.getpid(),dpr=window.devicePixelRatioF())
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
        window._allow_exit_without_prompt=True;window.close();app.quit()
