"""Normal-window acceptance for the VM2 interface delivery, with offline data."""
from pathlib import Path
import hashlib,json,os,sys,time,traceback

def start(window,output):
    from PySide6.QtCore import QPoint,Qt,QTimer
    from PySide6.QtTest import QTest,QSignalSpy
    from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QScrollArea
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..design.theme_manager import apply_theme
    from ..i18n import apply_ui_language
    app=QApplication.instance();output=Path(output)
    inputs=json.loads((output/'input.json').read_text('utf8'))
    result=dict(passed=False,checks=[],screenshots=[],geometry=[],executable=sys.executable,
        frozen=bool(getattr(sys,'frozen',False)),identity=load_build_identity().to_dict(),pid=os.getpid(),
        dpr=window.devicePixelRatioF(),inputs=inputs)

    def save(): (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value:raise AssertionError(name+': '+str(detail))
    def settle(seconds=.2):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.005)
    def wait(predicate,seconds=40):
        end=time.monotonic()+seconds
        while time.monotonic()<end and not predicate():settle(.03)
        check('bounded UI readiness',predicate())
    def shot(name,widget=None):
        target=output/(name+'.png');_capture(widget or window,target)
        check('native window screenshot '+name,target.is_file() and target.stat().st_size>1000)
        result['screenshots'].append(str(target));save()
    def rect(widget,target):
        p=widget.mapTo(target,QPoint());return [p.x(),p.y(),widget.width(),widget.height()]

    def updates(theme):
        from types import SimpleNamespace
        from ..app.updater import ComponentAction,UpdatePlan
        from ..app.update_dialog import UpdateOfferDialog
        plan=UpdatePlan('components',(ComponentAction('app','changed',23*1024*1024,23*1024*1024,48_000_000),
            ComponentAction('renderer','reuse',0,0,587_000_000)),23*1024*1024,1_000_000_000,'',(),())
        for count in [1,2,3,4,6,0]:
            notes='\n'.join(f'第{i+1}项，保留已有功能并改善操作' for i in range(count)) if count else '完整说明'+('较长的更新内容。'*15)
            offer=SimpleNamespace(plan=plan,latest_version='0.9.8',current_version='0.9.7',manifest=SimpleNamespace(note_for=lambda lang:notes))
            dialog=UpdateOfferDialog(offer,window);dialog.show();settle(.15)
            check(theme+f' update {count} custom window',bool(dialog.windowFlags()&Qt.WindowType.FramelessWindowHint))
            labels='\n'.join(x.text() for x in dialog.findChildren(QLabel))
            check(theme+f' update {count} retains size and versions','23.0 MB' in labels and '0.9.8' in labels and '0.9.7' in labels)
            check(theme+f' update {count} correct highlight count',len(dialog.highlight_cards)==min(count,4))
            check(theme+f' update {count} primary action visible',any(b.isVisible() and b.text()=='下载并准备更新' for b in dialog.findChildren(QPushButton)))
            check(theme+f' update {count} preserves rounded window',dialog.RADIUS==24 and dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
            check(theme+f' update {count} primary action fits window',dialog.primary_button.geometry().bottom()<dialog.height())
            shot(f'{theme}-update-{count}',dialog)
            if count>4:
                check(theme+' extra release notes visible',dialog.more_line is not None and '查看完整说明' in dialog.more_line.text())
                dialog.more_line.linkActivated.emit('page')
                check(theme+' full release notes retains action',dialog.choice=='page')
            dialog.reject();dialog.deleteLater();settle(.05)

    def history(theme):
        from ..recognition.recognition_history import RecognitionHistoryPage,HistoryGroup,RecognitionHistoryDetail,parse_recognition_report
        from ..recognition.history_diagnosis import ai_view
        reports=output/'history';reports.mkdir(exist_ok=True)
        for index in range(3):
            payload=dict(schema_version=1,status='failed',task_id=f'audit-{index}',started_at=f'2026-11-11T10:0{index}:00+08:00',
                finished_at=f'2026-11-11T10:0{index}:10+08:00',media=dict(name='同一素材.mp4',path=str(output/'same.mp4')),
                settings={},stages=[],events=[],review_items=[],result=dict(cue_count=0,elapsed_seconds=10,error='MOSS Pro 云端任务未启动',outputs={}),
                task=dict(current_stage='等待启动',last_error='MOSS Pro 云端任务未启动',remote_total=0,remote_requests={}))
            (reports/f'failed-{index}_字幕任务报告.json').write_text(json.dumps(payload,ensure_ascii=False),'utf8')
        page=RecognitionHistoryPage(reports,window,index_path=output/'history-index.json');page._roots=lambda:[reports]
        page.refresh();window.pages.addWidget(page);window._switch_page(page);wait(lambda:len(page.records)==3);settle(.2)
        groups=[g for g in page.findChildren(HistoryGroup) if not g.isHidden()]
        check(theme+' history groups repeated material',len(groups)==1 and len(groups[0].records)==3)
        check(theme+' history latest attempt first',[c.number.text() for c in page._cards]==['3','2','1'])
        check(theme+' history failure total',page.overview.failed_tile.value.text()=='3')
        shot(theme+'-history-media')
        QTest.mouseClick(page.view_buttons['time'],Qt.MouseButton.LeftButton);settle(.15)
        time_groups=[g for g in page.findChildren(HistoryGroup) if not g.isHidden()]
        check(theme+' time view hides group heading',len(time_groups)==1 and time_groups[0].header.isHidden());shot(theme+'-history-time')
        record=parse_recognition_report(reports/'failed-2_字幕任务报告.json')
        detail=RecognitionHistoryDetail(record,window,settings={});window.pages.addWidget(detail);window._switch_page(detail);settle(.25)
        check(theme+' failed detail leads with local diagnosis',detail.diagnosis_panel is not None and detail.diagnosis_panel.isVisible())
        check(theme+' AI structured diagnosis discards unlisted action',ai_view(json.dumps(dict(conclusion='检查账号',steps=[dict(title='重试',action='retry'),dict(title='未知',action='delete-all')]),ensure_ascii=False)).steps[-1].action=='')
        shot(theme+'-history-diagnosis');detail.shutdown() if hasattr(detail,'shutdown') else None
        window._return_to_settings();window.pages.removeWidget(detail);detail.deleteLater();window.pages.removeWidget(page);page.deleteLater();settle(.1)

    def completion(theme):
        from ..recognition.service import MediaResult,QueueResult
        report=json.loads(Path(inputs['report']).read_text('utf-8-sig'));data=report.get('result',{})
        item=MediaResult(media_path=report['media']['path'],status=report['status'],project_path=inputs['project'],
            report_json_path=inputs['report'],elapsed_seconds=float(data.get('elapsed_seconds',0)))
        window._last_run_options=None;window._handle_result(QueueResult((item,),item.elapsed_seconds));settle(.7)
        notification=getattr(window,'_completion_dialog',None)
        if notification and notification.isVisible():QTest.mouseClick(notification.confirm_button,Qt.MouseButton.LeftButton);settle(.15)
        for width in [1440,1100,760]:
            window.resize(width,900);settle(.25)
            scroll=window.pages.widget(2);cards=window.result_action_grid.cards
            check(theme+f' {width} completion has four actions',len(cards)==4 and cards[0] is window.result_ai_card)
            check(theme+f' {width} completion equal card height',len({c.height() for c in cards})==1)
            check(theme+f' {width} completion no horizontal scrolling',scroll.horizontalScrollBar().maximum()==0)
            check(theme+f' {width} followups below cards',window.result_todo.geometry().top()>window.result_action_grid.geometry().bottom())
            check(theme+f' {width} AI proxy follows original availability',window.result_ai_card.isEnabled()==window.repolish_current_glossary_button.isEnabled())
            check(theme+f' {width} summary keeps filename without repeated correction line',window.result_summary_meta.isHidden())
            check(theme+f' {width} result badge has real pixels',not window.result_icon.pixmap().isNull())
            result['geometry'].append(dict(theme=theme,width=width,cards=[rect(c,window.result_content) for c in cards],dpr=window.devicePixelRatioF()))
            shot(f'{theme}-completion-{width}')
        apply_ui_language(window,'en');settle(.25);shot(theme+'-completion-english');apply_ui_language(window,'zh')
        panel=window.result_files_panel;QTest.mouseClick(panel.detail_button,Qt.MouseButton.LeftButton);settle(.15)
        check(theme+' output details expand',panel.mode=='full');QTest.mouseClick(panel.header,Qt.MouseButton.LeftButton);settle(.15)
        check(theme+' output details collapse',panel.mode=='collapsed')
        window._return_to_settings();window.resize(1440,900)

    def workshop(theme):
        from ..local_models.model_workshop import ModelCard
        window._open_model_workshop();settle(.8);page=window.workshop_page
        cards=[c for c in page.findChildren(ModelCard) if c.isVisible()]
        check(theme+' normal model workshop shows table rows',bool(cards) and all(hasattr(c,'info_host') for c in cards))
        check(theme+' workshop model titles wrap',all(c.title_label.wordWrap() for c in cards))
        check(theme+' cloud recommendation retained',any(c.model.key=='mosi_moss_pro' for c in cards))
        check(theme+' model names have readable width',all(c.title_label.width()>=100 for c in cards),
              [(c.model.key,c.title_label.width()) for c in cards])
        shot(theme+'-workshop');window._return_to_settings()

    def studio(theme):
        from ..projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
        p=output/'controls.2byteproj'
        if not p.exists():save_project(SubtitleProject(media=StudioMedia(path=''),cues=[StudioCue('a',0,1000,'第一条'),StudioCue('b',1200,2200,'第二条')]),p)
        window.open_studio_project(str(p));wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
        wait(lambda:window.__dict__.get('_studio_loading_session') is None or not window._studio_loading_session.active)
        page=window.built_page('studio');settle(.3);page.select_cue('a')
        check(theme+' filters share segmented control',sum(b.parentWidget() is page.cue_filter_track for b in page.cue_filter_buttons.values())==3)
        QTest.mouseClick(page.cue_step_next,Qt.MouseButton.LeftButton);settle(.1)
        check(theme+' next cue navigation works',page.selected_cue_id=='b')
        QTest.mouseClick(page.cue_step_previous,Qt.MouseButton.LeftButton);settle(.1)
        check(theme+' previous cue navigation works',page.selected_cue_id=='a')
        page.jump_spin.setValue(2);QTest.keyClick(page.jump_spin,Qt.Key.Key_Return);settle(.1)
        check(theme+' typed stepper jumps to requested cue',page.selected_cue_id=='b')
        page.select_cue('a')
        check(theme+' reading list has no outer frame',page.cue_table.frameShape()==page.cue_table.Shape.NoFrame)
        check(theme+' review button shares search row',abs(page.review_entry_button.mapTo(page,QPoint()).y()-page.cue_search.mapTo(page,QPoint()).y())<8)
        from ..subtitle_rules.studio_qc import QCResult,QCIssue,QCSeverity,QCCategory
        from ..subtitle_rules.current_issues import invalidate
        page.project._qc_result=QCResult({'a':(QCIssue('test_current_check',QCSeverity.WARNING,
            QCCategory.TEXT,'a','检查当前字幕','人工保留当前字幕'),)})
        invalidate(page.project);page._refresh_cue_list_summary();settle(.05)
        check(theme+' pending review strip appears',not page.confirm_all_reviews_strip.isHidden())
        check(theme+' pending count belongs to note',page.confirm_all_reviews_button.property('pendingCount')==1 and '1' in page.confirm_all_reviews_note.text())
        original=[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]
        steps=page.undo_stack.count()
        QTest.mouseClick(page.confirm_all_reviews_button,Qt.MouseButton.LeftButton);settle(.05)
        check(theme+' empty review strip hides',page.confirm_all_reviews_strip.isHidden())
        check(theme+' whole-project confirmation is one undo and preserves content',page.undo_stack.count()==steps+1
            and original==[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues])
        page.undo_stack.undo();settle(.05)
        check(theme+' undo restores pending review strip',not page.confirm_all_reviews_strip.isHidden())
        page.context_drawer.setCurrentIndex(1);settle(.15)
        check(theme+' selection summary is shown on style tab',page.style_scope_summary.isVisible())
        check(theme+' shadow uses opacity without visible switch',page.style_shadow_switch.isHidden())
        from ..design.theme_manager import theme_key
        from ..design.themed_icons import colored_icon
        from ..design.ui_theme import theme_definition
        expected_icon=colored_icon('fa5s.sliders-h',theme_definition(theme_key()).accent_text).pixmap(15,15).toImage()
        check(theme+' appearance icons follow current theme',all(row.chevron.pixmap().toImage()==expected_icon for row in page._appearance_rows.values()))
        for width in [351,420]:
            page.context_panel.setFixedWidth(width);settle(.2)
            scope=page.style_scope
            check(theme+f' {width} scope remains one readable row',len({b.y() for b in scope._buttons})==1,
                  [(b.text(),b.x(),b.y(),b.width()) for b in scope._buttons])
            rows=page._appearance_rows
            ends=[]
            for row in rows.values():
                last=row.trailing if not row.trailing.isHidden() else row.chevron
                ends.append(last.mapTo(page.context_panel,last.rect().topRight()).x())
            check(theme+f' {width} appearance trailing controls align',max(ends)-min(ends)<=1,ends)
            check(theme+f' {width} shadow color is a wide well',page.style_shadow_swatch.width()>=2*page.style_shadow_swatch.height())
            shot(f'{theme}-style-{width}')
            scroll=rows['shadow'].parentWidget()
            while scroll is not None and not isinstance(scroll,QScrollArea):scroll=scroll.parentWidget()
            check(theme+' appearance belongs to scrollable style panel',scroll is not None)
            scroll.ensureWidgetVisible(rows['shadow']);settle(.15)
            shot(f'{theme}-appearance-{width}')
            scroll.verticalScrollBar().setValue(0);settle(.1)
        page.context_panel.setMinimumWidth(0);page.context_panel.setMaximumWidth(16777215)
        QTest.mouseClick(page.style_apply_geometry,Qt.MouseButton.LeftButton)
        check(theme+' geometry apply option mutually exclusive',page.style_apply_geometry.isChecked() and not page.style_apply_style_only.isChecked())
        QTest.mouseClick(page.style_apply_style_only,Qt.MouseButton.LeftButton)
        check(theme+' style-only option mutually exclusive',page.style_apply_style_only.isChecked() and not page.style_apply_geometry.isChecked())
        shot(theme+'-studio-controls');page.undo_stack.setClean();page.show_project_hub();window._return_to_settings();settle(.3)

    def execute():
        try:
            window.resize(1440,900)
            for theme in ['grape','warm']:
                apply_theme(theme,app);settle(.25);updates(theme);workshop(theme);history(theme);completion(theme);studio(theme)
            from . import blank_project_audit
            check('no external provider call',blank_project_audit._provider_calls==0)
            for path,digest in inputs['protected'].items():check('original input preserved',hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest)
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
            try:shot('failure')
            except Exception:result['capture_error']=traceback.format_exc()
        result['checks_passed']=sum(r['passed'] for r in result['checks']);save()
        window.close();settle(1);app.exit(0 if result['passed'] else 1)
    QTimer.singleShot(800,execute)
