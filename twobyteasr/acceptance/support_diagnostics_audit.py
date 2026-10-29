"""Explicit isolated, normal-window support workflow; also a shared before/after probe."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace


def run(window, output):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QDialog
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..studio.studio_bilingual import apply_display, set_manual_translation
    require(os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='support-diagnostics','explicit scenario required')
    from ..diagnostics.support_views import STEP_ROLE as views_role
    theme=os.environ.get('TWOBYTEASR_SUPPORT_THEME','grape')
    from ..design.theme_manager import apply_theme
    apply_theme(theme)
    output=Path(output).resolve()
    require(output==Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve(),'isolated root required')
    bench=os.environ.get('TWOBYTEASR_SUPPORT_BENCH')=='1'
    page=window.studio_page
    result=dict(passed=False,checks=[],timings={},theme=theme,identity=load_build_identity().to_dict(),pid=os.getpid(),
                frozen=bool(getattr(sys,'frozen',False)),platform=QApplication.platformName(),bench=bench,
                method='normal Windows window; QTest application commands; callback completion and queued Qt processing, not hardware input latency')
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));receipt();require(value,name)
    def wait(fn,label,seconds=30):
        end=time.monotonic()+seconds
        while not fn():
            if time.monotonic()>end:raise TimeoutError(label)
            QTest.qWait(20)
    def measure(name,fn):
        start=time.perf_counter();answer=fn();QApplication.processEvents()
        result['timings'].setdefault(name,[]).append(round((time.perf_counter()-start)*1000,3));return answer
    def opened(path):
        prior=page.project
        window.open_studio_project(str(path),mode='edit',source='support_acceptance')
        wait(lambda:page.project is not None and page.project is not prior and page._readiness.ready,'project readiness')
    try:
        window.resize(1440,900);window.show();QTest.qWait(250)
        fixture=output/'fixture.2byteproj'
        measure('open',lambda:opened(fixture))
        check('opened',page.project is not None)
        if os.environ.get('TWOBYTEASR_SUPPORT_TOOLTIPS'):
            # Tooltip-only pass (2026-10-21): with the interface zoom the run preset,
            # show real tooltips on the bar, the Tool Panel and the report window,
            # keep a picture of each and check that its whole text fits.
            from PySide6.QtCore import QCoreApplication, QEvent, QPoint
            from PySide6.QtWidgets import QToolTip, QWidget
            from ..app.ui_zoom import zoom_percent
            from ..diagnostics.support_dialog import open_support_dialog
            result['zoom']=zoom_percent();result['tooltips']=[]
            if page.video.controller is not None:page.video.set_paused(True)
            def tip(name,widget):
                QToolTip.hideText();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);QTest.qWait(80)
                text=widget.toolTip()
                QToolTip.showText(widget.mapToGlobal(QPoint(widget.width()//2,widget.height())),text,widget);QTest.qWait(400)
                tips=[w for w in QApplication.topLevelWidgets() if w.metaObject().className()=='QTipLabel' and w.isVisible()]
                if not tips:
                    result['tooltips'].append(dict(name=name,shown=False,text=text));check(f'tooltip {name}: shown',False,text);return
                label=tips[0];needed=max(label.fontMetrics().horizontalAdvance(line) for line in text.split('\n'))
                inner=label.contentsRect().width();label.grab().save(str(output/f'tip-z{result["zoom"]}-{name}.png'))
                result['tooltips'].append(dict(name=name,shown=True,text=text,size=[label.width(),label.height()],
                                               inner_width=inner,text_width=needed))
                check(f'tooltip {name}: whole text fits',inner>=needed,dict(inner=inner,text=needed))
            report_button=page.findChild(QPushButton,'studioReportProblemButton')
            for name,widget in (('report-flag',report_button),('cue-list',page.cue_list_toggle_button),
                                ('panel-save',page.save_button),('panel-undo',page.studio_undo_button)):
                if widget is not None and widget.isVisible():tip(name,widget)
            _capture(window,output/f'window-z{result["zoom"]}.png')
            open_support_dialog(page,page);dialog=page._support_dialog
            wait(lambda:hasattr(dialog,'_data') and not dialog._loading,'report for tooltips')
            shown=[w for w in dialog.findChildren(QWidget) if w.isVisible() and w.toolTip().strip()][:3]
            check('report window has tooltips to show',bool(shown),len(shown))
            for index,widget in enumerate(shown):tip(f'report-{index}',widget)
            _capture(dialog,output/f'report-z{result["zoom"]}.png')
            QToolTip.hideText();dialog.reject()
            result['passed']=True
            return 0
        if not bench:
            wait(lambda:page.video.controller is not None,'mpv controller')
            QTest.qWait(600)
            # Existing load() requests playback after readiness. Capture the
            # observation; do not mislabel historical autoplay as fixed.
            result['open_autoplay_observed']=not page.video._paused
            page.video.set_paused(True)
            check('explicit_pause_applied',page.video._paused)
            result['player']=dict(type=type(page.video.controller).__name__,paused=page.video._paused)
        first=page.project.cues[0].id;second=page.project.cues[1].id
        for i in range(8 if bench else 2):
            page.select_cue(first)
            measure('edit',lambda:page.cue_controller.set_text(first,'診斷驗收原文秘密'+str(i)))
            cue=page._cue_lookup[first]
            measure('drag_commit',lambda:page.cue_controller.commit_timeline_edit({first:SimpleNamespace(start_ms=cue.start_ms+5,end_ms=cue.end_ms+5,speaker_id=cue.speaker_id)}))
            page.timeline.playhead_ms=page._cue_lookup[first].start_ms+30
            page.timeline.setFocus();page._manual_selection_hold=True
            measure('qw',lambda:page.cue_controller.trim_to_playhead('start'))
            measure('undo',page.undo_stack.undo);measure('redo',page.undo_stack.redo)
        page.project_path=output/'saved.2byteproj'
        measure('save',page.save)
        check('save_completed',page.project_path.is_file() and page.undo_stack.isClean())
        measure('open',lambda:opened(output/'saved.2byteproj'))
        if not bench:
            set_manual_translation(page,first,'診斷驗收譯文秘密一');set_manual_translation(page,second,'診斷驗收譯文秘密二')
            apply_display(page,mode='bilingual')
            page.select_cue(first)
            before=len(page.project.cues)
            page.cue_controller.merge_pair(first,second)
            check('bilingual_merge_committed',len(page.project.cues)==before-1)
            result['merge_translation_count']=len(page.project.generation_metadata.get('translations',{}))
            page.undo_stack.undo();page.undo_stack.redo()
            page.timeline.playhead_ms=7000;page.cue_controller.add_subtitle_at_playhead()
            created=page.selected_cue_id
            check('added_selection_is_new',created not in {first,second})
            wait(lambda:page._canvas_editor is not None,'new subtitle edit card')
            page._canvas_editor.setPlainText('診斷驗收新增秘密')
            QTest.keyClick(page._canvas_editor,Qt.Key.Key_Return)
            wait(lambda:page._canvas_editor is None,'new subtitle commit')
            page.timeline.setFocus();page.timeline.playhead_ms=7150
            QTest.keyClick(page.timeline,Qt.Key.Key_Q);QTest.qWait(80)
            QTest.keyClick(page.timeline,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(page.timeline,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier)
            page.cue_controller.set_text(created,'診斷驗收新增秘密')
            page.save();opened(output/'saved.2byteproj')
            check('reopen_keeps_added',created in page._cue_lookup)
            check('reopen_keeps_confirmed_text',page._cue_lookup[created].text=='診斷驗收新增秘密')
            page.select_cue(created)
            from .grouping_contract_audit import run_offline
            from ..diagnostics.event_log import context,emit,recorder,exception_info
            with context(task_id='task-controlled-ai',project_id=page.project.project_id):
                replay=run_offline()
                emit('ai.fallback',result='completed',decision='rejected_invalid_candidates_used_local_source_boundaries',checks=len(replay['checks']))
            check('actual_ai_validator_failures_and_fallback',replay['passed'])
            # Fault is contained in an owned test thread. Original hook remains installed.
            import threading
            def failed_worker():
                try:raise ValueError('診斷驗收原文秘密 api_key=sk-fake-private-123456')
                except ValueError as exc:raise RuntimeError('controlled worker failure') from exc
            thread=threading.Thread(target=failed_worker,name='support-controlled-failure');thread.start();thread.join()
            from ..system.processes import run_hidden_subprocess
            cmd=[str(Path(sys.executable).parent/'python.exe'),'-c','import sys;sys.stderr.write("PermissionError: api_key=sk-fake-private-123456\\n");sys.exit(7)']
            if getattr(sys,'frozen',False):
                # In frozen mode use the shipped process boundary with a cmd child.
                cmd=[os.environ.get('COMSPEC','cmd.exe'),'/d','/c','exit','7']
            process=run_hidden_subprocess(cmd,purpose='controlled diagnostic failure',capture_output=True)
            check('controlled_child_exit',process.returncode==7)
            emit('privacy.fixture',result='observed',api_key='sk-fake-private-123456',url='https://example.invalid/file?X-Amz-Signature=fake-secret',
                 file_path=r'C:\Users\private-user\private-movie.mp4',text='診斷驗收原文秘密',
                 headers={'X-API-Key':'fixture-azure-secret','X-Custom-Key':'fixture-custom-secret'},
                 request_headers=[{'name':'Proxy-Authorization','value':'Basic fixture-proxy-secret'}],
                 note='Cookie: first=fixture-cookie-first; second=fixture-cookie-second')
            button=page.findChild(QPushButton,'studioReportProblemButton')
            # The main flow runs at 1440 wide: the flag folds before 字幕列表 and
            # comes back into the room the wider commands left (2026-10-21).
            page.studio_toolbar.layout().activate();QApplication.processEvents()
            result.setdefault('toolbar',{})['start']=start_toolbar=dict(
                width=window.width(),needed=page.studio_toolbar.layout().minimumSize().width(),
                collapsed=[w.text() or w.toolTip() for w in getattr(page,'_studio_toolbar_collapsed',())])
            page.studio_toolbar.grab().save(str(output/f'toolbar-{window.width()}.png'))  # Qt grab: no native child
            check('report_button_visible',button is not None and button.isVisible(),start_toolbar)
            # 保存/撤销/重做 and API 用量 left the bar (2026-10-21, user): 字幕列表 and
            # 工具面板 stay on it at 1440.
            check('toolbar_1440_keeps_panel_toggles',page.cue_list_toggle_button.isVisible()
                  and page.context_expand_button.isVisible(),start_toolbar)
            _capture(window,output/'studio.png')
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            dialog=getattr(page,'_support_dialog',None) or getattr(window,'_support_dialog',None)
            wait(lambda:dialog is not None and hasattr(dialog,'_data'),'report preview')
            check('default_content_excluded',not dialog.content.isChecked())
            dialog.description.setText('合併雙語字幕後檢查譯文與時間線；本包含可控 AI／子程序失敗，用來示範定位。')
            dialog._load();wait(lambda:dialog.refresh.isEnabled(),'preview refresh')
            dialog._export_to(output/'example-diagnostics.zip');wait(lambda:dialog._result is not None,'background ZIP',45)
            check('zip_exported',not dialog._result.get('error'),dialog._result)
            _capture(dialog,output/'report.png')
            import zipfile
            with zipfile.ZipFile(output/'example-diagnostics.zip') as z:
                raw=b'\n'.join(z.read(n) for n in z.namelist()).decode('utf8')
                rows=[json.loads(line) for line in z.read('events.jsonl').decode('utf8').splitlines()]
                manifest=json.loads(z.read('manifest.json'))
                check('zip_crc_and_manifest',z.testzip() is None and manifest['event_count']==len(rows))
                check('default_privacy',all(s not in raw for s in ('sk-fake-private','fake-secret','private-user','private-movie','診斷驗收原文秘密','診斷驗收譯文秘密','診斷驗收新增秘密',
                      'fixture-azure-secret','fixture-custom-secret','fixture-proxy-secret','fixture-cookie-first','fixture-cookie-second')))
                required={'problem.marked','data.commit','view.applied','project.saved','project.loaded','player.command','player.state','ai.validation','thread.exception','process.failure'}
                check('required_event_families',required <= {r['event_name'] for r in rows},sorted(required-{r['event_name'] for r in rows}))
                check('mapping_and_scroll_evidence',any(r.get('after',{}).get('mapping') and 'list_scroll' in r['after'] for r in rows if isinstance(r.get('after'),dict)))
                check('translation_before_after',any(r['event_name']=='data.commit' and r.get('before',{}).get('translation_view_count',0)>=2 and r['before']['cue_count']==r['after']['cue_count']+1 for r in rows))
            # 2026-10-21 layout: timeline + the person's steps + three views.
            analysis=dialog._analysis
            check('triage_counts',analysis.counts.get('act',0)>=2 and analysis.counts.get('stall',0)>=1
                  and analysis.counts.get('auto',0)>=1 and analysis.counts.get('check',0)>=1,analysis.counts)
            start_step=analysis.start_step
            check('start_step_selected_and_marked',start_step is not None and dialog._selected_step==start_step.id
                  and dialog.timeline.selected==start_step.id and dialog.detail.start_chip.isVisible(),
                  str(start_step.name) if start_step else None)
            check('merge_translation_check_on_merge_step',any('cue.merge_pair' in s.actions and any(i.kind=='check' for i in s.issues)
                  for s in analysis.steps),[str(s.name) for s in analysis.steps])
            check('timeline_has_marker_and_zoom',dialog.timeline.analysis is analysis and analysis.anchor_is_mark)
            _capture(dialog,output/'report-timeline.png')
            merge=next(s for s in analysis.steps if 'cue.merge_pair' in s.actions)
            item=next(dialog.steps.item(i) for i in range(dialog.steps.count())
                      if (dialog.steps.item(i).data(views_role) or {}).get('id')==merge.id)
            dialog.steps.scrollToItem(item);QTest.qWait(60)
            QTest.mouseClick(dialog.steps.viewport(),Qt.MouseButton.LeftButton,pos=dialog.steps.visualItemRect(item).center())
            QTest.qWait(80)
            check('trail_click_selects_step',dialog._selected_step==merge.id and dialog.timeline.selected==merge.id
                  and dialog.detail.name.text()==str(merge.name))
            _capture(dialog,output/'report-merge-step.png')
            QTest.mouseClick(dialog.detail.only,Qt.MouseButton.LeftButton);QTest.qWait(80)
            check('only_this_step_log',dialog.views.currentIndex()==1 and dialog.step_filter.isVisible() and dialog._filtered
                  and all(analysis.event_steps[i]==merge.id for i in dialog._filtered_index),len(dialog._filtered))
            _capture(dialog,output/'event-details.png')
            QTest.mouseClick(dialog.back_to_step,Qt.MouseButton.LeftButton);QTest.qWait(80)
            check('log_row_returns_to_step',dialog.views.currentIndex()==0 and dialog._selected_step==merge.id)
            dialog.show_view('log');dialog._set_step_filter(None);dialog._set_problem_filter(False)
            dialog.level.setCurrentIndex(dialog.level.findData('ERROR'));QTest.qWait(100)
            check('log_filter_and_page_bound',0<dialog.table.rowCount()<=100 and all(r['level']=='ERROR' for r in dialog._filtered))
            dialog.level.setCurrentIndex(0)
            QTest.mouseClick(dialog._view_buttons['summary'],Qt.MouseButton.LeftButton);QTest.qWait(80)
            lines=dialog.summary.toPlainText().splitlines()
            heads=[next((n for n,l in enumerate(lines) if l.startswith(h)),None) for h in ('【结论】','【从这里开始】','【操作轨迹】')]
            check('summary_conclusion_first',None not in heads and heads==sorted(heads)
                  and '合併雙語字幕' in dialog.summary.toPlainText(),heads)
            _capture(dialog,output/'report-summary.png')
            dialog.show_view('timeline')
            from ..design.ui_theme import hex_luminance
            from ..diagnostics.support_views import active_theme
            dark=not active_theme().is_light
            dialog.scope.showPopup();QTest.qWait(250)
            popup=dialog.scope.view()
            shot=popup.grab();popup_colour=shot.toImage().pixelColor(4,shot.height()//2)
            _capture(popup.window(),output/'scope-popup.png')
            dialog.scope.hidePopup();QTest.qWait(80)
            check('scope_popup_follows_theme',(popup_colour.lightnessF()<0.35)==dark,popup_colour.name())
            menu=dialog.more.menu();menu.popup(dialog.more.mapToGlobal(dialog.more.rect().bottomLeft()));QTest.qWait(250)
            menu_shot=menu.grab();menu_colour=menu_shot.toImage().pixelColor(menu_shot.width()-6,menu_shot.height()//2)
            _capture(menu,output/'more-menu.png')
            check('more_menu_follows_theme_and_holds_detail_toggle',(menu_colour.lightnessF()<0.35)==dark
                  and dialog.details_mode.isVisible(),menu_colour.name())
            menu.hide();QTest.qWait(60)
            for size,name in (((760,680),'report-narrow.png'),((1120,900),'report-wide.png')):
                dialog.resize(*size);QTest.qWait(200)
                _capture(dialog,output/name)
                check('no_horizontal_scroll_'+name.split('.')[0],not dialog.steps.horizontalScrollBar().isVisible()
                      and dialog.timeline.width()<=dialog.width(),dict(size=[dialog.width(),dialog.height()]))
            check('fits_150_percent_laptop',dialog.minimumSizeHint().height()<=720,dialog.minimumSizeHint().height())
            dialog.resize(960,880)
            dialog.content.setChecked(True);check('content_preview_explicit',dialog.content_preview.isVisible())
            dialog._result=None;dialog._export_to(output/'selected-content-diagnostics.zip');wait(lambda:dialog._result is not None,'explicit content ZIP')
            with zipfile.ZipFile(output/'selected-content-diagnostics.zip') as z:
                check('explicit_content_only_when_selected','診斷驗收新增秘密' in z.read('selected-content.json').decode('utf8'))
            from shiboken6 import isValid
            markers=[dialog.identity.text()]
            dialog.close()
            wait(lambda:not isValid(dialog),'closed report disposed')
            for close_method in ('accept','reject'):
                button.click()
                reopened=page._support_dialog
                markers.append(reopened.identity.text())
                wait(lambda:not reopened._loading,'reopened report loaded')
                _capture(reopened,output/'report-reopened.png')
                getattr(reopened,close_method)()
                wait(lambda:not isValid(reopened),'reopened report disposed')
            check('report_reopen_disposes_and_marks',len(set(markers))==3 and
                  not window.findChildren(QDialog,'diagnosticsDialog'))
            # 2026-10-21 (user, later): the flag alone was not recognisable, so
            # 回报问题 shows its words next to the flag, outlined in the warning
            # colour. It still leaves a narrow bar before 字幕列表, and 字幕列表 /
            # 双语 / API 用量 keep their places. Last, so a layout finding cannot
            # hide the report checks above.
            from PySide6.QtWidgets import QToolTip
            from ..i18n import tr
            check('report_button_flag_and_words',button.text()==tr('回报问题')==button.accessibleName()
                  and not button.icon().isNull() and bool(button.toolTip())
                  and button.property('buttonRole')=='secondary' and button.property('emphasis')=='warning',
                  dict(text=button.text(),tooltip=button.toolTip(),accessible=button.accessibleName()))
            QToolTip.showText(button.mapToGlobal(button.rect().center()),button.toolTip(),button);QTest.qWait(400)
            tips=[w for w in QApplication.topLevelWidgets() if w.inherits('QTipLabel') and w.isVisible()]
            tip_colour=None
            if tips:
                tip_shot=tips[0].grab();tip_colour=tip_shot.toImage().pixelColor(3,tip_shot.height()//2)
                tip_shot.save(str(output/'report-tooltip.png'))
            QToolTip.hideText();QTest.qWait(60)
            check('report_tooltip_follows_theme',tip_colour is not None and (tip_colour.lightnessF()<0.35)==dark,
                  tip_colour.name() if tip_colour is not None else None)
            named=lambda widget:widget.text() or widget.toolTip()
            core=(page.cue_list_toggle_button,page.context_expand_button,page.bilingual_toggle_button,button)
            restore=(window.width(),window.height())
            def toolbar_at(width):
                window.resize(width,restore[1]);QTest.qWait(400)
                # A grab right after the resize can show the old positions.
                page.studio_toolbar.layout().activate();QApplication.processEvents();QTest.qWait(400)
                collapsed=list(getattr(page,'_studio_toolbar_collapsed',()))
                state=dict(width=window.width(),needed=page.studio_toolbar.layout().minimumSize().width(),
                           collapsed=[named(w) for w in collapsed],shown={named(w):w.isVisible() for w in core})
                result.setdefault('toolbar',{})[str(width)]=state
                page.studio_toolbar.grab().save(str(output/f'toolbar-{width}.png'))  # Qt grab: no native child
                return state
            state=toolbar_at(1600)
            check('toolbar_1600_keeps_core_entries',all(state['shown'].values()),state)
            # Narrow until the flag really has no room left; then it lives in ⋯.
            for width in (1100,1000,900,800):
                state=toolbar_at(width)
                if not button.isVisible():break
            check('toolbar_narrow_flag_in_overflow',not button.isVisible() and named(button) in state['collapsed'],state)
            from PySide6.QtWidgets import QToolButton
            overflow=next(b for b in page.studio_toolbar.findChildren(QToolButton) if b.property('commandSource')=='更多工作区操作')
            overflow_menu=overflow.menu();overflow_menu.popup(overflow.mapToGlobal(overflow.rect().bottomLeft()));QTest.qWait(300)
            entries=[a for a in overflow_menu.actions() if a.text()==tr('回报问题')]
            overflow_menu.grab().save(str(output/'overflow-menu-narrow.png'))
            overflow_colour=overflow_menu.grab().toImage().pixelColor(overflow_menu.width()-6,overflow_menu.height()//2)
            check('overflow_menu_lists_report_and_follows_theme',len(entries)==1 and not entries[0].icon().isNull()
                  and (overflow_colour.lightnessF()<0.35)==dark,
                  dict(entries=[a.text() for a in overflow_menu.actions()],colour=overflow_colour.name()))
            overflow_menu.hide();QTest.qWait(80)
            entries[0].trigger()
            wait(lambda:getattr(page,'_support_dialog',None) is not None and isValid(page._support_dialog)
                 and hasattr(page._support_dialog,'_data') and not page._support_dialog._loading,'report from overflow')
            from_menu=page._support_dialog
            check('report_opens_from_overflow',from_menu.isVisible(),from_menu.identity.text())
            from_menu.reject();wait(lambda:not isValid(from_menu),'overflow report disposed')
            # API 用量与费用 lives only in ⋯ (2026-10-21, user); same window as before.
            overflow_menu.popup(overflow.mapToGlobal(overflow.rect().bottomLeft()));QTest.qWait(300)
            usage_entries=[a for a in overflow_menu.actions() if a.text()==page.studio_usage_button.text()]
            check('usage_only_in_overflow',len(usage_entries)==1 and not page.studio_usage_button.isVisible()
                  and not page.studio_toolbar.isAncestorOf(page.studio_usage_button),[a.text() for a in overflow_menu.actions()])
            overflow_menu.hide();QTest.qWait(80)
            usage_entries[0].trigger()
            wait(lambda:getattr(page,'_usage_dialog',None) is not None and page._usage_dialog.isVisible()
                 and not page._usage_dialog._loading,'usage window from overflow')
            page._usage_dialog.grab().save(str(output/'usage-from-overflow.png'))
            check('usage_opens_from_overflow',page._usage_dialog.isVisible())
            page._usage_dialog.close();QTest.qWait(100)
            window.resize(*restore);QTest.qWait(300)
            # 保存 / 撤销 / 重做 in the Tool Panel header (2026-10-21, user): a real
            # click on each, then the same three with the keys.
            if not page.context_panel.isVisible():
                QTest.mouseClick(page.context_expand_button,Qt.MouseButton.LeftButton);QTest.qWait(300)
            panel=dict(save=page.save_button,undo=page.studio_undo_button,redo=page.studio_redo_button)
            check('tool_panel_holds_save_undo_redo',all(b.isVisible() and page.context_panel.isAncestorOf(b)
                  and not page.studio_toolbar.isAncestorOf(b) and not b.icon().isNull() for b in panel.values()),
                  {k:[b.isVisible(),b.toolTip()] for k,b in panel.items()})
            page.context_panel.grab().save(str(output/'tool-panel.png'))
            _capture(window,output/'tool-panel-window.png')
            target=page.project.cues[0].id
            text=lambda:page._cue_lookup[target].text
            original=text()
            page.cue_controller.set_text(target,'工具面板撤销验收');QTest.qWait(80)
            QTest.mouseClick(page.studio_undo_button,Qt.MouseButton.LeftButton);QTest.qWait(150)
            undone=text()==original
            QTest.mouseClick(page.studio_redo_button,Qt.MouseButton.LeftButton);QTest.qWait(150)
            redone=text()=='工具面板撤销验收'
            check('panel_undo_redo_click',undone and redone,dict(undone=undone,redone=redone,text=text()))
            QTest.mouseClick(page.save_button,Qt.MouseButton.LeftButton);wait(lambda:page.undo_stack.isClean(),'panel save')
            saved=load_project(page.project_path)
            check('panel_save_click',page.undo_stack.isClean()
                  and next(c.text for c in saved.cues if c.id==target)=='工具面板撤销验收',str(page.project_path.name))
            page.timeline.setFocus()
            page.cue_controller.set_text(target,'快捷键撤销验收');QTest.qWait(80)
            QTest.keyClick(page.timeline,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);QTest.qWait(150)
            key_undo=text()=='工具面板撤销验收'
            QTest.keyClick(page.timeline,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier);QTest.qWait(150)
            key_redo=text()=='快捷键撤销验收'
            QTest.keyClick(page.timeline,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);QTest.qWait(150)
            QTest.keyClick(page.timeline,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
            QTest.qWait(150)
            key_redo_alt=text()=='快捷键撤销验收'
            check('keys_undo_redo',key_undo and key_redo and key_redo_alt,
                  dict(undo=key_undo,redo=key_redo,redo_alt=key_redo_alt,text=text()))
            QTest.keyClick(page.timeline,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
            wait(lambda:page.undo_stack.isClean(),'key save')
            saved=load_project(page.project_path)
            check('key_save',next(c.text for c in saved.cues if c.id==target)=='快捷键撤销验收')
        result['log_bytes']=sum(p.stat().st_size for p in (output/'local/2ByteASR/logs').rglob('*') if p.is_file())
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
        try:_capture(window,output/'failure.png')
        except Exception:pass
    finally:
        page.undo_stack.setClean();receipt()
    return 0 if result['passed'] else 1


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        window.result_exit_code=run(window,output)
        def stopped():
            path=Path(output)/'result.json';result=json.loads(path.read_text(encoding='utf8'));result['gui_shutdown']=True
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100,execute)
