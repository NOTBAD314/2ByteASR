"""Replay retained REAL MOSS progress through the normal application window."""
import json
import time
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .service import PipelineEvent
    from .studio_project import load_project, save_project
    from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions, verify_subtitle_artifact
    from . import blank_project_audit
    source=json.loads((output/'input.json').read_text('utf8'))
    events=[json.loads(line.split('MOSS_EVENT ',1)[1]) for line in Path(source['worker_log']).read_text('utf8').splitlines() if 'MOSS_EVENT ' in line]
    # Use each real phase once. These are replays, not a new model execution.
    selected={}
    for event in events:selected[event['phase']]=event
    queue=list(selected.values())
    checks=[]
    result={'passed':False,'scope':'retained real task UI replay / saved export integrity; no new inference',
            'checks':checks,'provider_calls':0}
    window._active_job_id='moss-progress-audit'
    window._recognition_terminal=''
    window._active_stages={2:{'label':'MOSS 整段上下文','resource':'GPU'}}
    window._completed_stages=set();window._stage_total=10
    window._current_media_total=window._current_media_index=1
    window.started_at=time.perf_counter()
    window.pages.setCurrentIndex(1)

    def finish():
        try:
            project=load_project(source['project'])
            original=[(c.id,c.text,c.speaker_id,c.start_ms,c.end_ms) for c in project.cues]
            for i,speaker in enumerate(project.speakers):
                speaker.name=f'人工名字{i+1}'
                speaker.color=['#123456','#654321','#abcdef','#fedcba'][i%4]
            saved=output/'named-copy.2byteproj';save_project(project,saved);reopened=load_project(saved)
            checks.append({'check':'actual saved cues and overlaps survive reopening',
                'passed':original==[(c.id,c.text,c.speaker_id,c.start_ms,c.end_ms) for c in reopened.cues]})
            checks.append({'check':'manual names colors retained','passed':reopened.speakers==project.speakers})
            artifacts=export_subtitle_artifacts(reopened,output/'exports','actual-full-context',
                SubtitleExportOptions(formats=frozenset({'srt','json'}),speaker_mode='both'))
            verified=[]
            import copy
            for artifact in artifacts:
                expected=copy.deepcopy(reopened)
                if artifact.speaker_id:
                    expected.cues=[cue for cue in expected.cues if cue.speaker_id==artifact.speaker_id]
                verified.append(verify_subtitle_artifact(artifact,expected).valid)
            checks.append({'check':'actual combined/per-speaker SRT and JSON parser verification',
                          'passed':all(verified), 'artifact_count':len(artifacts)})
            result['provider_calls']=blank_project_audit._provider_calls
            result['passed']=all(c['passed'] for c in checks) and result['provider_calls']==0
        except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        window.close()
        QTimer.singleShot(500,QApplication.instance().quit)

    def tick():
        try:
            if not queue:finish();return
            payload={'backend':'moss',**queue.pop(0)}
            event=PipelineEvent(kind='asr_worker_progress',timestamp='',payload=payload,job_id='moss-progress-audit')
            window._handle_event(event)
            # 2026-10-08 (M12): the bar stays determinate (real steps only);
            # the phase shows as the action title, tokens as a live fact.
            tokens=payload.get('generated_tokens')
            facts=dict(window.stage_metrics.metrics())
            checks.append({'phase':payload['phase'],'check':'real phase/token text and determinate bar',
                'passed':('MOSS' in window.progress_stage.text() and window.progress_bar.maximum()==1000
                          and (tokens is None or f'{int(tokens):,} tokens' in facts.values())),
                'text':window.progress_stage.text(),'bar_max':window.progress_bar.maximum(),'facts':facts})
            window.grab().save(str(output/(payload['phase']+'.png')))
            QTimer.singleShot(400,tick)
        except Exception as exc:
            result['error']=f'{type(exc).__name__}: {exc}'
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            QApplication.instance().quit()
    QTimer.singleShot(800,tick)
