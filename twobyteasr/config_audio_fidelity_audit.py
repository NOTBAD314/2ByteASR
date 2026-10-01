"""Opt-in normal-entry regression, with isolated settings and project copies."""
import json, os, time, traceback
from pathlib import Path


def start(window, out):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity
    from .asr_provider_snapshot import resolve_provider_snapshot
    from .settings import project_settings_path
    out = Path(out); page = window.studio_page
    phase = os.environ.get('TWOBYTEASR_FIDELITY_PHASE', 'initial')
    report = {'passed': False, 'checks': {}, 'samples': [], 'phase': phase,
              'identity': load_build_identity().to_dict(), 'settings_path': str(project_settings_path())}

    def pump(seconds=.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents(); time.sleep(.003)

    def wait(predicate, seconds=40):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            pump(.03)
        raise TimeoutError('fidelity audit wait')

    def check(name, value):
        report['checks'][name] = bool(value)
        (out/'progress.json').write_text(json.dumps(report, ensure_ascii=False, default=str), 'utf8')
        if not value: raise AssertionError(name)

    def opened(name):
        page.video.set_paused(True); page.undo_stack.setClean()
        page.show_project_hub(skip_dirty_guard=True); pump(.2)
        ready = []
        window.open_studio_project(out/name, on_ready=lambda *_: ready.append(True))
        wait(lambda: bool(ready) and page._readiness.ready)
        page.video.set_paused(True); page.volume_slider.setValue(35); pump(.2)

    def sample(name, position, rate):
        page.video.set_paused(True); page._seek(position)
        wait(lambda: not page.video._playback_clock.exact_seek_pending)
        page._set_speed(rate); page.video.set_paused(False)
        wait(lambda: page.audio_engine.telemetry_snapshot().get('state') == 'PLAYING', 20)
        page.audio_engine.capture_pcm(name, True)
        capture=None
        helper=os.environ.get('TWOBYTEASR_PROCESS_LOOPBACK')
        if helper:
            from .processes import popen_hidden_subprocess
            import subprocess
            endpoint=page.audio_engine.telemetry_snapshot().get('endpoint_pid')
            capture=popen_hidden_subprocess([helper,str(endpoint),'2',str(out/(name+'-loopback.wav'))],
                purpose='Read-only target process audio capture',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        before = page.timeline.playhead_ms; pump(2.5)
        state = page.audio_engine.telemetry_snapshot()
        report['samples'].append({'name': name, 'before': before, 'after': page.timeline.playhead_ms,
            'telemetry': state, 'request': page.audio_engine._last_payload})
        if capture:
            try:
                stdout,stderr=capture.communicate(timeout=5)
                report['samples'][-1]['loopback']={'exit':capture.returncode,'data':stdout.decode('utf8','replace'),'error':stderr.decode('utf8','replace')}
            except Exception as exc:
                capture.kill();capture.communicate()
                report['samples'][-1]['loopback']={'error':str(exc)}
        page.audio_engine.capture_pcm(name, False)
        check(name+' clock advances', page.timeline.playhead_ms > before+500)
        check(name+' output created', state.get('windows_sink_count') == 1)
        page.video.set_paused(True); pump(.3)
        window.grab().save(str(out/(name+'.png')))

    def run():
        try:
            wait(lambda: page.project is not None and page._readiness.ready)
            if phase == 'initial':
                window._open_model_workshop(); pump(.2)
                window.workshop_page._perform_action('nemotron', role='speaker')
                check('workshop closes speaker', window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] == 'single')
                values = {'service': 'deepseek', 'provider': 'deepseek', 'transport': 'openai_compatible',
                    'base_url': 'https://api.deepseek.com/v1', 'model': 'deepseek-v4-pro', 'protocol': 'auto'}
                window.group_editor.restore_profile_values(values, window.legacy.RUNTIME_SETTINGS)
                window.prefer_arabic_numbers.setChecked(False)
                check('save role configuration', window._save_ai_configuration(show_feedback=False))
                check('numeric preference false persisted', not json.loads(project_settings_path().read_text('utf8'))['switches']['prefer_arabic_numbers'])
                window.prefer_arabic_numbers.setChecked(True)
                check('save numeric preference true', window._save_ai_configuration(show_feedback=False))
                for index in range(5):
                    window._return_to_settings(); pump(.05)
                    window._open_model_workshop(); pump(.05)
                    check(f'navigation {index+1}', window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] == 'single'
                          and resolve_provider_snapshot(window.legacy.RUNTIME_SETTINGS).model == 'deepseek-v4-pro')
            check('persistent speaker closed', window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] == 'single')
            snap = resolve_provider_snapshot(window.legacy.RUNTIME_SETTINGS)
            report['route'] = snap.public_identity()
            check('persistent role selection', snap.model == 'deepseek-v4-pro')
            check('numeric preference persisted', window.legacy.RUNTIME_SETTINGS['switches']['prefer_arabic_numbers'])
            opened('original.2byteproj')
            from .studio_cue_table import _speaker_name
            from .studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
            before_names={s.id:s.name for s in page.project.speakers}
            report['speaker_names']=before_names
            check('legacy default speaker names normalized',all(name.startswith('S') and name[1:].isdigit() for name in before_names.values()))
            check('cue table and tracks use same names',all(_speaker_name(page.project,s.id)==s.name for s in page.project.speakers))
            exports=export_subtitle_artifacts(page.project,out/'named-subtitles','speakers',SubtitleExportOptions(speaker_mode='per_speaker'))
            check('new exports use same speaker names',all(x.path.stem.endswith('_'+before_names[x.speaker_id]) for x in exports))
            page.save();opened('original.2byteproj')
            check('names survive reopen without merging',before_names=={s.id:s.name for s in page.project.speakers})
            from .studio_speaker_manager import SpeakerManagerDialog
            dialog=SpeakerManagerDialog(page);dialog.show();pump(.2)
            dialog.grab().save(str(out/(phase+'-speaker-manager.png')))
            check('speaker manager uses display identity',all(dialog.table.item(i,1).text() in before_names.values() for i in range(dialog.table.rowCount())))
            dialog.close();dialog.deleteLater();pump(.1)
            sample(phase+'-mp3-1x', 20, 1)
            sample(phase+'-mp3-2x', 45, 2)
            sample(phase+'-mp3-backward', 14, 1)
            page.video.set_paused(False); pump(1); page.video.set_paused(True)
            check('resume advances', page.timeline.playhead_ms > 16500)
            page.save(); opened('video.2byteproj'); sample(phase+'-video', 2, 1)
            opened('original.2byteproj'); sample(phase+'-reopen', 80, 2)
            check('project opening preserves settings', window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] == 'single'
                  and resolve_provider_snapshot(window.legacy.RUNTIME_SETTINGS).model == 'deepseek-v4-pro')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            report['final_audio'] = page.audio_engine.telemetry_snapshot()
            report['canvas'] = {'external': page.video._external_clock_enabled, 'has_video': page.video._media_has_video,
                'startup': page.video._startup_state, 'clock': str(page.video._playback_clock.snapshot()),
                'clock_audit': page.video._playback_clock.diagnostics() if hasattr(page.video._playback_clock,'diagnostics') else ''}
            report['final_request'] = page.audio_engine._last_payload
            (out/(phase+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf8')
            page.video.set_paused(True); page.undo_stack.setClean(); QTimer.singleShot(100,window.close)
    QTimer.singleShot(500,run)
