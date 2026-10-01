"""Measure real Studio V2 frames/audio/seek latency without screenshot stalls.

All settings and the regression project are copied under tmp. Media is read-only.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    run = root/'tmp/v2-sync'/time.strftime('%Y%m%d-%H%M%S'); run.mkdir(parents=True)
    sys.path.insert(0, str(root))
    os.environ.update(LOCALAPPDATA=str(run/'local'), APPDATA=str(run/'roaming'), QT_QPA_PLATFORM='windows',
                     QT_SCALE_FACTOR='1', DASHSCOPE_API_KEY='sk-local-test-dummy')
    from PySide6 import QtCore
    from PySide6.QtCore import QSettings, Qt, QTimer
    class IsolatedSettings(QSettings):
        def __init__(self, *a, **kw): super().__init__(str(run/'qt.ini'), QSettings.Format.IniFormat)
    QtCore.QSettings = IsolatedSettings
    from twobyteasr import settings, studio_project
    settings.stable_settings_root = lambda: run/'config'
    pref = run/'studio-settings.json'
    pref.write_text(json.dumps({'recent_projects': [], 'project_root': str(run/'projects'),
        'studio_preferences': {'autosave_enabled': False, 'auto_cover': False, 'recovery_policy': 'official'}}))
    studio_project.studio_settings_path = lambda: pref
    studio_project.project_library_root = lambda: run/'projects'
    data = json.loads(args.project.read_text(encoding='utf-8-sig'))
    overlay = data['video_tracks'][1]; clip = overlay['clips'][0]
    entry = int(clip['timeline_in_ms']); base = entry + 5000
    data['report_path'] = ''; data['original_outputs'] = {}; data.pop('autosave', None)
    data.setdefault('studio_state', {}).update(audio_master_mode='mix_all', audio_master_track_id='')
    data['cues'] = [dict(id='v2-sync', start_ms=entry, end_ms=clip['timeline_out_ms'],
        text='V2 同步与 60fps 验证', speaker_id='S00', style_id='default')]
    data['speakers'] = [dict(id='S00', name='验证', style_id='default')]
    fixture = run/'fixture.2byteproj'; fixture.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
    from PySide6.QtWidgets import QApplication
    import subtitle_core
    from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.theme_manager import apply_theme
    app = QApplication([]); _register_bundled_fonts(); app.setFont(_app_font()); apply_theme('slate', app)
    win = MainWindow([], subtitle_core, object(), None); win.resize(1600, 960); win.show()
    def settle(sec):
        end=time.perf_counter()+sec
        while time.perf_counter()<end: app.processEvents(); time.sleep(.001)
    settle(.5)
    win.open_studio_project(str(fixture), mode='edit', source='v2-sync-audit')
    page=win.studio_page; page._queue_advanced_preview_job=lambda *a,**kw: None
    settle(5)
    comp=page.video_compositor; samples=[]; phase=-1; phase_start=0.; native=[]
    original=page.video.publish_compositor_overlay
    def publish(slot, *a, **kw):
        result=original(slot, *a, **kw)
        if slot==0:
            native.append({'phase':phase,'at':time.perf_counter(),'pts':[p.pts_ms for p in comp._players.values()]})
        return result
    page.video.publish_compositor_overlay=publish
    scenarios=[('cold_seek', base, False, 3), ('play', None, True, 6),
               ('seek_forward', base+25000, True, 6), ('seek_backward', base+10000, True, 6),
               ('pause', None, False, 2), ('resume', None, True, 5)]
    def sample():
        at=time.perf_counter()
        aud=page.audio_engine.telemetry_snapshot()
        rows=[]
        for layer in comp._layers:
            player=comp._players.get(str(layer['clip_id']))
            if player is not None:
                target=layer['source_in_ms']+round((page.timeline.playhead_ms-layer['timeline_in_ms'])*layer['playback_rate'])
                rows.append({'target':target,'pts':player.pts_ms,'lag':target-player.pts_ms,'age':player.frame_age_ms})
        samples.append({'phase':phase,'ms':(at-phase_start)*1000,'rows':rows,
            'audio_target':aud.get('requested_source_ms'),'audio_estimate':aud.get('estimated_source_ms'),
            'audio_drift':aud.get('drift_ms'),'audio_gen':aud.get('source_generation'),
            'audio_alive':aud.get('ffmpeg_process_alive'),'audio_bytes':aud.get('sink_consumed_bytes')})
    timer=QTimer(); timer.setTimerType(Qt.TimerType.PreciseTimer); timer.setInterval(16); timer.timeout.connect(sample)
    results=[]
    for i,(name,target,playing,duration) in enumerate(scenarios):
        phase=i; phase_start=time.perf_counter()
        if bool(page.video.playback_position_snapshot().paused)==playing: page._toggle_playback()
        if target is not None: page._seek(target/1000)
        comp.reset_performance_samples(); timer.start(); settle(duration); timer.stop()
        rows=[s for s in samples if s['phase']==phase and s['rows']]
        ready=[s for s in rows if all(abs(r['lag'])<100 for r in s['rows'])]
        steady=[s for s in rows if s['ms']>1000]
        lag=sorted(abs(r['lag']) for s in steady for r in s['rows'])
        audio=sorted(abs(s['audio_drift']) for s in steady if s['audio_drift'] is not None)
        pubs=[s for s in native if s['phase']==phase and s['at']-phase_start>1]
        unique=[s for j,s in enumerate(pubs) if j==0 or s['pts']!=pubs[j-1]['pts']]
        summary={'phase':name,'first_aligned_ms':ready[0]['ms'] if ready else None,
            'video_abs_lag_p95':lag[int(len(lag)*.95)] if lag else None,
            'audio_abs_lag_p95':audio[int(len(audio)*.95)] if audio else None,
            'unique_native_fps':(len(unique)-1)/(unique[-1]['at']-unique[0]['at']) if len(unique)>1 else 0,
            'performance':comp.performance_snapshot()}
        results.append(summary); print(json.dumps(summary),flush=True)
    if not page.video.playback_position_snapshot().paused: page._toggle_playback()
    page._video_clip_selected(overlay['id'],clip['id']); page.context_drawer.show(); settle(.4)
    win.grab().save(str(run/'studio-panel.png'))
    rect=win.frameGeometry(); win.screen().grabWindow(0,rect.x(),rect.y(),rect.width(),rect.height()).save(str(run/'studio-screen.png'))
    (run/'result.json').write_text(json.dumps({'summary':results,'samples':samples,'native':native},indent=2),encoding='utf8')
    page.close_page(); settle(.5); win.hide(); print('EVIDENCE',run,flush=True)

if __name__=='__main__': main()
