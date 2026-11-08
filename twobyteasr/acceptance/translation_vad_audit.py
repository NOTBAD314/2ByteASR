"""Opt-in, isolated checks of actual translation and VAD entry points."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import wave


def long_vad(output, seconds, speech):
    import numpy as np
    import psutil
    import moss_firered_pipeline as pipeline
    import subtitle_core as legacy
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with wave.open(str(speech),'rb') as stream:
        rate=stream.getframerate()
        if (rate,stream.getnchannels(),stream.getsampwidth())!=(16000,1,2):
            raise ValueError('The test speech must be mono PCM16 at 16000 Hz')
        phrase=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32767
    period=np.zeros(max(len(phrase)+16000,16000*13),dtype=np.float32)
    period[:len(phrase)]=phrase
    samples=round(seconds*rate)
    audio=np.lib.format.open_memmap(output/'audio.npy',mode='w+',dtype=np.float32,shape=(samples,))
    for start in range(0,samples,rate*30):
        end=min(samples,start+rate*30)
        audio[start:end]=period[np.arange(start,end)%len(period)]
    audio.flush();del audio
    audio=np.load(output/'audio.npy',mmap_mode='r')
    stop=threading.Event();telemetry={};parent=psutil.Process()
    def monitor():
        while not stop.wait(.05):
            for process in [parent,*parent.children(recursive=True)]:
                try:
                    memory=process.memory_info()
                    entry=telemetry.setdefault(str(process.pid),dict(command=process.cmdline(),peak_rss=0,peak_private=0,observations=0))
                    entry['peak_rss']=max(entry['peak_rss'],memory.rss)
                    entry['peak_private']=max(entry['peak_private'],getattr(memory,'private',0))
                    entry['observations']+=1
                except (psutil.NoSuchProcess,psutil.AccessDenied):
                    pass
    thread=threading.Thread(target=monitor,daemon=True);thread.start();started=time.perf_counter()
    try:
        regions=pipeline.detect_firered_vad(audio,legacy)
        result=dict(seconds=seconds,elapsed_seconds=time.perf_counter()-started,
            execution=regions.execution,regions=list(regions),processes=telemetry,
            input_kind='Windows SAPI speech repeated with silence on a sample grid; synthetic long workload')
        if not regions or regions[-1]['end']>seconds:
            raise AssertionError('Expected bounded speech intervals within the true input duration')
    finally:
        stop.set();thread.join()
    (output/'vad-memory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return result


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..projects.studio_project import load_project,save_project
    from ..subtitle_rules import subtitle_translation as st
    from ..providers import ai_providers,llm_config
    output=Path(output)
    result=dict(passed=False,checks=[],requests=[],pid=os.getpid())
    def quitting():
        result['gui_shutdown']=True
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    QApplication.instance().aboutToQuit.connect(quitting)
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def finish(error=None):
        if error:result['error']=str(error)
        result['passed']=bool(result['checks']) and all(row['passed'] for row in result['checks']) and not error
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        page=getattr(window,'studio_page',None)
        if page and page.project:
            page.undo_stack.setClean();page.project_dirty=False
        window.close();QTimer.singleShot(500,QApplication.instance().quit)
    class Provider:
        provider_id=model='isolated-replay'
        def structured_complete(self,messages,schema,**options):
            body=json.loads(messages[-1]['content']);result['requests'].append(body)
            return {'items':[dict(id=identity,translation=('小姐，你好' if len(result['requests'])==1 else '爱弥斯小姐，你好')
                if identity=='name' else '你好') for identity in body['output_ids']]}
    ai_providers.provider_for_stage=lambda *a,**k:Provider()
    llm_config.text_ai_key_missing=lambda *a,**k:False
    window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
    deadline=time.monotonic()+80
    def ready():
        try:
            page=window.built_page('studio')
            if page is None or page.project is None or not page._readiness.ready or page._readiness.active:
                if time.monotonic()>deadline:raise TimeoutError('Studio readiness')
                QTimer.singleShot(100,ready);return
            window.showMaximized();page._seek(.9);page.select_cue('name')
            page._open_translation_dialog(scope='all')
            dialog=page._translation_dialog;dialog.start_button.setEnabled(True);dialog.show();dialog._start()
            def translated():
                try:
                    if dialog._thread is not None:
                        if time.monotonic()>deadline:raise TimeoutError('Translation')
                        QTimer.singleShot(50,translated);return
                    check('studio_name_repaired',st.records_of(page.project)['name']['text']=='爱弥斯小姐，你好')
                    check('only_bad_cue_retried',result['requests'][1]['output_ids']==['name'])
                    check('unrelated_cue_has_no_name',st.records_of(page.project)['other']['text']=='你好')
                    check('real_request_has_selected_library',result['requests'][0]['required_terms_by_id']['name'][0]['target']=='爱弥斯小姐')
                    dialog.grab().save(str(output/'translation-dialog.png'));dialog.close()
                    from ..studio.studio_bilingual import apply_display
                    apply_display(page,mode='bilingual',layout='ink_v1')
                    from ..caption_style.bilingual_layout import project_display_cues
                    from ..exports.studio_subtitle_export import _compile_format
                    shown=project_display_cues(page.project)
                    check('preview_model_has_full_name',any('爱弥斯小姐' in cue.text for cue in shown))
                    saved=save_project(page.project,output/'saved.2byteproj')
                    reopened=load_project(saved)
                    check('save_reopen_keeps_translation',st.translation_view(reopened)['name']['text']=='爱弥斯小姐，你好')
                    exported=_compile_format(reopened,'srt');(output/'translated.srt').write_text(exported,'utf8')
                    check('srt_contains_full_name','爱弥斯小姐' in exported)
                    check('source_and_timing_unchanged',[(cue.text, cue.start_ms, cue.end_ms) for cue in reopened.cues]==[('エイミスさん、こんにちは',100,2700),('こんにちは',3100,5700)])
                    from ..studio.studio_bilingual import apply_display
                    apply_display(page,mode='bilingual',layout='ink_v1')
                    page._seek(.9)
                    QTimer.singleShot(1600,capture)
                except Exception as exc:finish(exc)
            QTimer.singleShot(50,translated)
        except Exception as exc:finish(exc)
    def capture():
        try:
            page=window.built_page('studio')
            trace=page.subtitle_visibility_trace(reason='translation_name_audit')
            (output/'preview-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2,default=str),'utf8')
            check('actual_caption_pixels',any(row.get('alpha_nonzero',0)>10 for row in trace.get('cue_pixels',[])))
            from .blank_project_audit import _capture
            _capture(window,output/'studio-preview.png')
            page.video.controller.screenshot_to_file(output/'preview-native.png')
            QTimer.singleShot(800,check_vad)
        except Exception as exc:finish(exc)
    def check_vad():
        seconds=float(os.environ.get('TWOBYTEASR_VAD_AUDIT_SECONDS','0'))
        if seconds<=0:
            finish();return
        failures=[]
        def run():
            try:
                result['vad']=long_vad(output/'vad',seconds,os.environ['TWOBYTEASR_VAD_AUDIT_SPEECH'])
            except Exception as exc:
                failures.append(exc)
        thread=threading.Thread(target=run,name='isolated-vad-audit',daemon=True);thread.start()
        def poll():
            if thread.is_alive():
                QTimer.singleShot(100,poll);return
            if failures:
                finish(failures[0]);return
            check('frozen_or_source_vad_uses_real_worker',result['vad']['execution']['actual_backend']=='firered_vad')
            finish()
        QTimer.singleShot(100,poll)
    QTimer.singleShot(100,ready)
