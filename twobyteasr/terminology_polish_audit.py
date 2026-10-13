"""Guarded normal-UI ASR-fixture replay; all search/polish CLI calls are real."""
from __future__ import annotations
import json
import os
import time
import traceback
from pathlib import Path
from types import SimpleNamespace


def start(window,out):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from . import ui,reporting
    from .studio_project import load_project,save_project
    from .pipeline_runtime import complete_media_run
    from .build_identity import load_build_identity
    from .asr_provider_snapshot import digest
    from .provider_input_budget import measure
    from . import domain_terms,polishing
    core=window.legacy
    phase=os.environ.get('TWOBYTEASR_TERMINOLOGY_PHASE','run')
    result=dict(phase=phase,synthetic_asr_input=True,recognition_models_executed=False,
        checks={},build=vars(load_build_identity()),buttons=[],started=time.time())
    def write(name,value):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),'utf8')
    def pump(seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            QApplication.processEvents();time.sleep(.01)
    def wait(predicate,seconds,label):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            pump(.05)
        check(label,predicate())
    def check(name,value):
        result['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def click(button,name):
        check(name+' visible',button.isVisible() and button.isEnabled())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        result['buttons'].append(name);pump(.15)
    def cue_rows(project):
        return [(c.id,c.text,c.speaker_id,c.start_ms,c.end_ms) for c in project.cues]
    try:
        if phase=='reopen':
            expected=json.loads((out/'saved-state.json').read_text('utf8'))
            project=load_project(out/'polished.2byteproj')
            window.open_studio_project(str(out/'polished.2byteproj'),mode='edit',source='startup_audit')
            wait(lambda:window.studio_page.project is not None,30,'new process project opened')
            check('text speaker time IDs persisted',digest(cue_rows(window.studio_page.project))==expected['cues_hash'])
            check('task states persisted',window.studio_page.project.generation_metadata.get('polishing_summary')==expected['polishing_summary'])
            window.grab().save(str(out/'reopened-qt.png'))
        else:
            original_rows=json.loads((out/'synthetic-asr.json').read_text('utf8'))
            source=out/'synthetic.mp4'
            reports=out/'reports';reports.mkdir(exist_ok=True)
            reporting.REPORT_ROOT=reports
            # Inject only upstream evidence. This audit deliberately does not
            # install or run recognition models; worker/service/cloud/output
            # paths and the user's existing CLI account are production code.
            ui.missing_selected_local_models=lambda *_:[]
            window._save_asr_configuration=lambda **_:True
            index=window.primary_asr_backend.findData('moss')
            if index<0:
                window.primary_asr_backend.addItem('MOSS · 合成证据夹具','moss')
                index=window.primary_asr_backend.findData('moss')
            window.primary_asr_backend.setCurrentIndex(index)
            queue=ui.run_media_queue
            def fixture_queue(*args,**kwargs):
                return queue(*args,**kwargs,_skip_environment_preflight=True)
            ui.run_media_queue=fixture_queue
            core.cleanup_old_cache=lambda:None
            def process_media(media_path,file_index,file_total,legacy,runtime_context=None):
                started=time.perf_counter();ctx=runtime_context
                ctx.reset_for_media()
                rows=legacy.deserialize_segments(original_rows)
                cache_dir=out/'cache';cache_dir.mkdir(exist_ok=True)
                cache={'cache_dir':str(cache_dir),'identity':{'synthetic_sha256':digest(original_rows)}}
                legacy.begin_media_report(media_path,cache)
                candidates=domain_terms.collect_stable_moss_term_candidates(rows,legacy.load_glossary())
                verified=legacy.load_verified_game_terms()
                disputes=domain_terms.collect_global_term_disputes(rows,candidates)
                global_messages=domain_terms._discover_term_batch(rows,'原神合成前瞻讨论',legacy.load_glossary(),verified,candidates,
                    _disputes=disputes,_messages_only=True)
                # Match production outer work units; dynamic final-message
                # packing occurs inside each of these batches.
                batches=[rows[i:i+16] for i in range(0,len(rows),16)]
                sizes=[]
                for batch in batches:
                    msgs=polishing.call_correction_api(batch,legacy.load_glossary(),'只读前文','只读后文','原神合成验收',
                        '原神合成前瞻讨论',candidates,[],verified,_messages_only=True)
                    sizes.append(measure(msgs,None,4096,'polish',[]))
                write('input-scope.json',dict(candidate_count=len(candidates),verified_terms=verified,
                    outer_batches=len(batches),cue_count=len(rows),global_budget=measure(global_messages,None,4096,'domain_terms',[]),
                    polish_budgets=sizes,upstream='synthetic SpeechSegment fixture, no audio sent'))
                polished=legacy.run_cached_stage('polished',cache,
                    lambda:legacy.polish_subtitles(rows,'原神合成验收',cache),
                    encoder=legacy.serialize_segments,decoder=legacy.deserialize_segments,
                    extra_signature={'segments':original_rows,'fixture_version':'20260915-coverage'})
                write('polished-rows.json',legacy.serialize_segments(polished))
                write('task-states.json',dict(terminology=ctx.terminology_status,polishing=ctx.polishing_summary))
                cues=[legacy.SubtitleCue(r.segment_id,r.start,r.end,r.text,speaker=r.speaker) for r in polished]
                ctx.studio_project_path=str(out/'polished.2byteproj')
                return complete_media_run(cues=cues,segments=polished,file_index=file_index,file_total=file_total,
                    started=started,audio_seconds=len(rows)*30,txt_path=str(out/'synthetic.txt'),srt_path=str(out/'synthetic.srt'),
                    stage_index=11,stage_total=11,legacy=legacy,runtime_context=ctx,
                    model_statuses={'MOSS':'synthetic fixture; not executed','FireRed':'synthetic fixture; not executed'})
            fixture_pipeline=SimpleNamespace(**vars(window.pipeline))
            fixture_pipeline.check_runtime=lambda _:None
            fixture_pipeline.precompute_moss_batch_cache=lambda *_:None
            fixture_pipeline.process_media=process_media
            fixture_pipeline.__file__=__file__
            window.pipeline=fixture_pipeline
            window._switch_page(0);window.media_paths=[str(source)];window._refresh_media_summary()
            window.game_box.setCurrentText('原神')
            window.refresh_polish.setChecked(False);window.refresh_group.setChecked(False)
            window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids']=[]
            window._refresh_asr_summary();pump(.2)
            # Drive the actual library picker, then the normal Start button.
            window._pick_glossaries();pump(.2)
            picker=window.findChild(ui.GlossaryPickerDialog)
            check('normal glossary picker opened',picker is not None)
            picker.search.setText('原神');pump(.1)
            for i in range(picker.list_widget.count()):
                item=picker.list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole)=='原神':
                    item.setCheckState(Qt.CheckState.Checked)
            button=next(b for b in picker.findChildren(QPushButton) if b.text()=='确定')
            click(button,'启用原神词库')
            check('genshin enabled through picker','原神' in window._enabled_glossary_ids())
            window.grab().save(str(out/'enabled-glossary-qt.png'))
            click(window.start_button,'开始生成字幕')
            check('normal worker launched',window.worker is not None)
            wait(lambda:not window.worker.isRunning(),1200,'normal worker finished')
            pump(.4)
            result['completion_title']=window.result_title.text()
            result['completion_summary']=window.result_summary.text()
            result['completion_text']=window.result_files.toPlainText()
            if window._completion_dialog:
                window._completion_dialog.close();pump(.5)
            window.grab().save(str(out/'completion-qt.png'))
            check('polish stage produced state',(out/'task-states.json').is_file())
            states=json.loads((out/'task-states.json').read_text('utf8'))
            result['task_states']=states
            result['completion_text']=window.result_files.toPlainText()
            result['retry_visible']=window.retry_failed_button.isVisible()
            project=load_project(out/'polished.2byteproj')
            rows=json.loads((out/'polished-rows.json').read_text('utf8'))
            check('all source IDs preserved',[r['segment_id'] for r in rows]==[r['segment_id'] for r in original_rows])
            check('speaker time unchanged',[(r['speaker'],r['start'],r['end']) for r in rows]==[(r['speaker'],r['start'],r['end']) for r in original_rows])
            check('reliable verified name corrected','阿蕾奇诺' in rows[0]['text'] and '阿雷奇诺' not in rows[0]['text'])
            check('inconclusive name preserved','洛琪娜' in rows[1]['text'])
            check('all six batches polished',states['polishing'].get('success_batches')==6 and states['polishing'].get('success_cues')==96)
            check('actual search and all terminology evidence checked',states['terminology'].get('status')=='success'
                and states['terminology'].get('unverified_count')==0 and states['terminology'].get('batches',0)>0)
            save_project(project,out/'polished.2byteproj')
            write('saved-state.json',dict(cues_hash=digest(cue_rows(project)),polishing_summary=project.generation_metadata['polishing_summary']))
        result['passed']=True
    except Exception:
        result['error']=traceback.format_exc();result['passed']=False
    finally:
        result['elapsed_seconds']=time.time()-result['started']
        write(phase+'-result.json',result)
        if getattr(window,'worker',None) and window.worker.isRunning():
            window.token.cancel()
            deadline=time.monotonic()+15
            while window.worker.isRunning() and time.monotonic()<deadline:pump(.05)
        if getattr(window,'studio_page',None):window.studio_page.close_page()
        window.hide()
        QTimer.singleShot(200,QApplication.instance().quit)
