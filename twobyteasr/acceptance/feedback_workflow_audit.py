"""Ordinary-window acceptance for the October settings/translation feedback.

Uses a loopback HTTP fixture with actual transports and API usage fields. No
paid API or user project is used. Input-method events are synthetic Qt events.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


def run(output, *, window):
    from PySide6.QtCore import QTimer, QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication, QPushButton, QDialogButtonBox, QMenu, QMessageBox
    from PySide6.QtTest import QTest
    from ..projects.studio_project import load_project, save_project, StudioSpeaker, StudioMedia, SubtitleProject
    from ..projects.studio_runtime_state import state_for
    from ..studio.translation_actions import translate_selected
    from ..studio.speaker_name_controls import add_action
    from ..caption_style.bilingual_layout import project_display_cues
    from ..subtitle_rules.subtitle_translation import records_of, cue_status
    from ..providers import usage_ledger as ledger, llm_adapter, llm_config
    from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from ..timeline.studio_commands import BatchReplaceTextCommand
    from ..exports.studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, verify_subtitle_artifact
    from ..diagnostics.build_identity import load_build_identity
    from .blank_project_audit import _capture

    output=Path(output); fixture=Path(os.environ['TWOBYTEASR_FEEDBACK_FIXTURES'])
    page=window.studio_page
    window.resize(1440,900);window.show()
    result=dict(passed=False,checks=[],screenshots=[],frozen=bool(getattr(sys,'frozen',False)),
                identity=load_build_identity().to_dict(),pid=os.getpid(),entry='normal MainWindow',
                usage_scope='synthetic loopback HTTP responses, not a paid service',
                ime_scope='Qt preedit/commit events, not an installed physical IME')
    def save(): (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,condition,detail=None):
        result['checks'].append(dict(name=name,passed=bool(condition),detail=detail));save()
        if not condition:raise AssertionError(name+': '+str(detail))
    def wait(predicate,label,seconds=30):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError(label)
            QTest.qWait(20)
    def capture(name,widget=None):
        path=output/(name+'.png');_capture(widget or window,path)
        result['screenshots'].append(str(path));save()
    def open_project(path):
        page.video.set_paused(True)
        page.undo_stack.setClean()
        def report_message():
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                result.setdefault('unexpected_messages',[]).append(modal.text());capture('unexpected-project-message',modal)
                modal.reject()
        timer=QTimer(window);timer.timeout.connect(report_message);timer.start(300)
        window.open_studio_project(path,mode='edit',source='feedback_acceptance')
        timer.stop();timer.deleteLater()
        check('project-open-no-error-'+Path(path).stem,not result.get('unexpected_messages'),result.get('unexpected_messages'))
        wait(lambda:page.project is not None and Path(page.session.project_path)==Path(path) and page._readiness.ready,'project ready',60)
        QTest.qWait(400)
    calls=[]; gate=threading.Event();gate.set(); response_mode=['retry_once']
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            payload=json.loads(body['messages'][-1]['content'])
            calls.append(payload)
            gate.wait(15)
            content=('{invalid json' if response_mode[0]=='retry_once' and len(calls)==1 else
                     json.dumps({'items':[{'id':row['id'],'translation':'这是完整的译文 '+row['id']}
                         for row in payload['lines'] if row['translate']]},ensure_ascii=False))
            packet={'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1000,'prompt_cache_hit_tokens':400,'prompt_cache_miss_tokens':600,
                             'completion_tokens':200,'completion_tokens_details':{'reasoning_tokens':150},'total_tokens':1200}}
            data=json.dumps(packet,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    class Provider:
        provider_id='custom';model='acceptance-loopback'
        def complete(self,messages,**kwargs):
            return llm_adapter.post_chat_completion(messages,model=self.model,api_key='fixture-not-a-secret',
                url=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                max_tokens=kwargs.get('max_tokens',2000),provider='custom',stage='subtitle_translation')
    provider=Provider()
    try:
        # Run the actual English grouping entry in this process. The proposed
        # splits are the user's supplied example, not a new paid AI response.
        import subtitle_core as core
        from ..subtitle_rules import grouping
        from ..subtitle_rules.language_rules import language_scope
        from ..subtitle_rules.grouping_contract import validate_grouping_result
        original='I have the idea because flash cards are like bad steam content'
        proposed=['I have the idea','because flash cards are like','bad steam content']
        source=[core.SpeechSegment(1,0,5,original,.9,[],speaker='S00')]
        with language_scope('en'):
            final=grouping.cues_from_resegmented_texts(source,proposed)
            local=grouping.fallback_group(source)
        comparison=dict(source=original,ai_proposed=proposed,
            proposal_source='user supplied example, no paid AI request',
            local=[dict(text=c.text,start=c.start,end=c.end) for c in local],
            final=[dict(text=c.text,start=c.start,end=c.end) for c in final])
        (output/'english-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),'utf8')
        check('english-production-preserves-steam-and-meaning',
              [c.text for c in final]==[proposed[0],'because flash cards are like bad steam content']
              and [c.text for c in local]==[original] and validate_grouping_result(source,final))
        from datetime import datetime,timezone
        price=ledger.price_snapshot('https://api.deepseek.com/chat/completions','deepseek-v4-flash',
                                    datetime(2026,10,20,12,tzinfo=timezone.utc).isoformat())
        cost=ledger.estimate(dict(prompt_tokens=1000,prompt_cache_hit_tokens=400,prompt_cache_miss_tokens=600,
                                 completion_tokens=200,completion_tokens_details=dict(reasoning_tokens=150)),price)
        (output/'cost-example.json').write_text(json.dumps(dict(tariff=price,estimate=cost),ensure_ascii=False,indent=2,default=str),'utf8')
        check('cost-example-cache-and-reasoning-not-double-counted',cost.get('low')=='0.0002112',cost)
        # Open the same production settings entry by a real button click. The
        # timer runs inside its modal loop and presses duplicate entry points.
        for index in range(3):
            checks=[]
            def operate():
                dialog=getattr(window,'_application_settings_dialog',None)
                if dialog is None:
                    checks.append(False);return
                try:
                    checks.append(dialog.isVisible())
                    window._open_application_settings()
                    checks.append(getattr(window,'_application_settings_dialog',None) is dialog)
                    capture('settings-'+str(index),dialog)
                    button=dialog.buttons.button(QDialogButtonBox.StandardButton.Save if index==1 else QDialogButtonBox.StandardButton.Cancel)
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                except Exception:
                    checks.append(traceback.format_exc())
                    dialog.reject()
            QTimer.singleShot(250,operate)
            started=time.perf_counter()
            QTest.mouseClick(window.app_settings_button,Qt.MouseButton.LeftButton)
            check('settings-open-single-instance-'+str(index),checks==[True,True],checks)
            result.setdefault('settings_cycle_ms',[]).append(round((time.perf_counter()-started)*1000))
            QTest.qWait(100)

        project=load_project(fixture/'100.2byteproj')
        project.cues=project.cues[:3]
        for cue,text in zip(project.cues,['I have the idea','because flash cards are like','bad steam content']):
            cue.text=cue.original_text=text
        project.generation_metadata={'language':{'code':'en'}}
        project.speakers=[StudioSpeaker('S00','小明'),StudioSpeaker('S01','另一位很长名字的说话人')]
        path=output/'translation.2byteproj';save_project(project,path);open_project(path)
        page.select_cue('c0')
        page.cue_controller.timeline_selection_changed(['c0','c1','c2'])
        key_missing=llm_config.text_ai_key_missing
        key_ready=lambda:bool(window._ai_main_editor.key.text().strip()) or not key_missing(GLOBAL_PROVIDER_REGISTRY.settings(),'polish')
        registry_type=type(GLOBAL_PROVIDER_REGISTRY)
        with (patch.object(registry_type,'credential',lambda self,selection:(key_ready(),'audit')),
             patch('twobyteasr.providers.llm_config.text_ai_key_missing',lambda *a,**k:not key_ready()),
             patch('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:provider)):
            window._ai_main_editor.key.clear()
            translate_selected(page,merge=True)
            dialog=page._translation_dialog
            wait(lambda:dialog.isVisible(),'translation dialog')
            QTest.qWait(100)
            merged=page.selected_cue_id
            check('merge-all-three-selected',len(page.project.cues)==1 and page.project.cues[0].id==merged)
            check('merge-selection-count-is-one',page.selection_model.selected_count()==1)
            check('missing-key-no-request',not calls and 'Key' in dialog.status.text())
            capture('translation-missing-key',dialog)
            translate_selected(page,merge=True)
            check('double-merge-no-extra-edit',len(page.project.cues)==1 and page._translation_dialog is dialog)
            QTest.mouseClick(dialog.settings_button,Qt.MouseButton.LeftButton)
            settings=window._ai_settings_dialog;QTest.qWait(200)
            check('settings-direct-key-focus',window._ai_main_editor.key.isVisible() and window._ai_main_editor.key.hasFocus())
            capture('translation-key-settings',settings)
            QTest.keyClicks(window._ai_main_editor.key,'fixture-not-a-real-key')
            save_button=window.ai_dialog_save_button
            QTest.mouseClick(save_button,Qt.MouseButton.LeftButton)
            wait(lambda:dialog._thread is not None or bool(calls),'translation resumed')
            dialog._start();dialog._start()
            wait(lambda:dialog._thread is None,'translation finished',40)
            check('invalid-json-retry-two-http-requests',len(calls)==2,len(calls))
            check('only-merged-cue-translated',set(records_of(page.project))=={merged},records_of(page.project))
            check('selection-survives-key-roundtrip',page.selected_cue_id==merged)
            capture('translation-complete',dialog)
            ledger.flush();rows=ledger.read_rows()
            check('all-usage-once-after-retry',len(rows)==2 and sum(r['usage']['total_tokens'] for r in rows)==2400)
            check('relay-fee-unknown',all(not r['cost']['known'] for r in rows))
            dialog._show_usage();QTest.qWait(300);capture('usage-details',dialog._usage_dialog);dialog._usage_dialog.close()
            dialog.close();QTest.qWait(80)

            # Begin a fresh translation with a changed source, then edit and
            # undo while its HTTP response is deliberately delayed.
            page.undo_stack.push(BatchReplaceTextCommand(page.project,{merged:'We should go to the bridge now.'}))
            page._open_translation_dialog(scope='selected')
            dialog=page._translation_dialog;gate.clear();response_mode[0]='normal'
            dialog._start();wait(lambda:len(calls)==3,'delayed request dispatched')
            page.undo_stack.push(BatchReplaceTextCommand(page.project,{merged:'We should stay right here.'}))
            page.undo_stack.undo()
            gate.set();wait(lambda:dialog._thread is None,'stale response finished')
            check('edit-undo-revision-discards-late-result',bool(dialog._result.discarded),dialog._result.summary())
            dialog.close();QTest.qWait(80)

        # Name switch goes through its normal menu action and state delta.
        menu=QMenu(page);action=add_action(page,menu);action.trigger();QTest.qWait(500)
        body=[c.text for c in page.project.cues]
        check('names-view-only',all('小明：' not in text for text in body) and any(c.text.startswith('小明：') for c in project_display_cues(page.project)))
        capture('speaker-name-preview')
        names_path=output/'names.2byteproj';save_project(page.project,names_path);open_project(names_path)
        check('names-save-reopen',page.project.studio_state.get('show_speaker_names') is True and [c.text for c in page.project.cues]==body)
        artifacts=export_subtitle_artifacts(page.project,output/'exports','feedback',SubtitleExportOptions(frozenset({'srt','ass','txt','json'}),'both'))
        check('four-format-independent-readback',bool(artifacts) and all(a.path.is_file() for a in artifacts))
        result['artifacts']=[str(a.path) for a in artifacts]

        # Reuse A's cue count with a genuinely long synthetic video. Its
        # diagnostic fixture has a short source and a long metadata duration.
        long_base=load_project(fixture/'10000.2byteproj')
        long_project=SubtitleProject(media=StudioMedia(os.environ['TWOBYTEASR_FEEDBACK_LONG_MEDIA'],
            duration_ms=20002000,width=640,height=360), cues=long_base.cues,
            asr_evidence=long_base.asr_evidence,styles=long_base.styles,effects=long_base.effects,
            speakers=[StudioSpeaker('S00','甲'),StudioSpeaker('S01','乙')])
        for index,cue in enumerate(long_project.cues):cue.speaker_id='S00' if index%2==0 else 'S01'
        long_path=output/'long.2byteproj';save_project(long_project,long_path);open_project(long_path)
        for label,position,playing in [('middle-paused',10000500,False),('end-paused',19998500,False),
                                      ('middle-playing',9996500,True),('end-playing',19994500,True)]:
            page.select_cue('c1')
            page._seek(position/1000)
            page.video.set_paused(not playing)
            wait(lambda:abs(page.timeline.playhead_ms-position)<1500,'seek to insertion point')
            page.cue_controller.add_subtitle_at_playhead()
            cue_id=page.selected_cue_id
            wait(lambda:page._canvas_editor is not None and page.subtitle_edit_input.isVisible(),'new cue edit')
            row=page.cue_model.row_for_cue_id(cue_id)
            rect=page.cue_table.visualRect(page.cue_model.index(row,3))
            check(label+'-new-row-actually-visible',page.cue_table.viewport().rect().intersects(rect),
                  dict(row=row,y=rect.y(),height=page.cue_table.viewport().height()))
            editor=page.subtitle_edit_input
            QTest.keyClicks(editor,'New subtitle ')
            QCoreApplication.sendEvent(editor,QInputMethodEvent('新',[]))
            QTest.qWait(200)
            check(label+'-preedit-selection',page.selected_cue_id==cue_id)
            commit=QInputMethodEvent();commit.setCommitString('新增');QCoreApplication.sendEvent(editor,commit)
            QTest.qWait(150)
            capture('editing-'+label)
            page._commit_canvas_inline_edit();page.video.set_paused(True)
            check(label+'-selected-text',page.selected_cue_id==cue_id and '新增' in state_for(page.project).cue_by_id[cue_id].text)
            check(label+'-near-insert-position',abs(state_for(page.project).cue_by_id[cue_id].start_ms-position)<1500,
                  dict(wanted_ms=position,insert_ms=state_for(page.project).cue_by_id[cue_id].start_ms))
            page.undo_stack.undo();page.undo_stack.redo();QTest.qWait(100)
            check(label+'-redo-selection',page.selected_cue_id==cue_id)
            rect=page.cue_table.visualRect(page.cue_model.index(page.cue_model.row_for_cue_id(cue_id),3))
            check(label+'-redo-row-actually-visible',page.cue_table.viewport().rect().intersects(rect))
            capture('insert-'+label)
        page.undo_stack.setClean()
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc()
        try:capture('failure')
        except Exception:pass
    finally:
        gate.set();server.shutdown();server.server_close()
        from shiboken6 import isValid
        for name in ('_translation_dialog','_ai_settings_dialog','_application_settings_dialog'):
            owner=page if name=='_translation_dialog' else window
            dialog=getattr(owner,name,None)
            if dialog is not None and isValid(dialog):
                if hasattr(dialog,'_cancel'):dialog._cancel.set()
                dialog.close()
        page.video.set_paused(True);page.undo_stack.setClean();save()
    return 0 if result['passed'] else 1


def start(window,output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        try:code=run(output,window=window)
        except Exception:
            (Path(output)/'result.json').write_text(json.dumps({'passed':False,'error':traceback.format_exc()}),'utf8');code=1
        window.result_exit_code=code
        def stopped():
            path=Path(output)/'result.json';data=json.loads(path.read_text('utf8'));data['gui_shutdown']=True
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(150,execute)
