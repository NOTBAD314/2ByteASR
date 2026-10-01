def main():
    """Read existing media through a copied regression project; all writes under tmp."""
    import argparse, json, os, sys, time
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    RUN = ROOT / 'tmp/ui-polish-recovery/v2' / time.strftime('%Y%m%d-%H%M%S')
    RUN.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update(LOCALAPPDATA=str(RUN/'local'), APPDATA=str(RUN/'roaming'),
                      QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1',
                      DASHSCOPE_API_KEY='sk-local-test-dummy')
    from PySide6 import QtCore
    from PySide6.QtCore import QSettings, Qt
    class IsolatedSettings(QSettings):
        def __init__(self, *a, **kw):
            super().__init__(str(RUN/'qt.ini'), QSettings.Format.IniFormat)
    QtCore.QSettings = IsolatedSettings
    from twobyteasr import settings, studio_project
    settings.stable_settings_root = lambda: RUN/'config'
    fixture_settings = RUN/'studio-settings.json'
    fixture_settings.write_text(json.dumps({'recent_projects': [], 'project_root': str(RUN/'projects'),
        'studio_preferences': {'autosave_enabled': False, 'auto_cover': False, 'recovery_policy': 'official'}}))
    studio_project.studio_settings_path = lambda *a: fixture_settings
    studio_project.project_library_root = lambda *a: RUN/'projects'
    parser = argparse.ArgumentParser(description='Isolated real-media V2/LIVE native presentation check')
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.project.read_text(encoding='utf-8-sig'))
    assert all(Path(a['canonical_source']).is_file() for a in data['media_pool'])
    overlay_track = data['video_tracks'][1]
    clip = overlay_track['clips'][0]
    probe_ms = (clip['timeline_in_ms'] + clip['timeline_out_ms']) // 2
    exit_ms = clip['timeline_out_ms'] + 1500
    data['report_path'] = ''
    data['original_outputs'] = {}
    data.pop('autosave', None)
    data['cues'] = [dict(id='native-probe', start_ms=clip['timeline_in_ms'], end_ms=exit_ms+5000,
                        text='普通字幕 · 应显示在 V2 上方', speaker_id='S00', style_id='default')]
    data['speakers'] = [dict(id='S00', name='验证', style_id='default')]
    # Subtitle positions are ASS play-resolution pixels, unlike normalized video transforms.
    data['styles'][0].update(position_x=1190, position_y=540, font_size=82)
    data['render_settings'].update(play_res_x=1920, play_res_y=1080)
    project_path = RUN/'fixture.2byteproj'
    project_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    import numpy as np
    import subtitle_core
    from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.theme_manager import apply_theme
    app = QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    apply_theme('slate', app)
    from twobyteasr.studio_ai import style_recipe_for_prompt
    recipe = style_recipe_for_prompt('黄色到青色渐变字幕')
    recipe.engine = 'remotion'
    advanced_start = probe_ms + 12000
    advanced_end = exit_ms - 500
    assert advanced_start + 3000 < advanced_end, 'Need a longer secondary clip for this probe'
    data['cues'][0]['end_ms'] = advanced_start
    data['styles'].append({**data['styles'][0], 'id': 'advanced'})
    data['style_recipes']['advanced'] = recipe.to_dict()
    data['cues'].extend([
        dict(id='advanced-probe', start_ms=advanced_start, end_ms=advanced_end,
             text='高级 LIVE · 显示在 V2 上方', speaker_id='S00', style_id='advanced'),
        dict(id='native-after', start_ms=advanced_end, end_ms=exit_ms+5000,
             text='普通字幕 · V2 离场后恢复', speaker_id='S00', style_id='default'),
    ])
    project_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    win = MainWindow([], subtitle_core, object(), None)
    win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    win.show()
    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.01)
    settle(1)
    win.showNormal()
    win.resize(1600, 960)
    win.open_studio_project(str(project_path), mode='edit', source='recovery-v2-probe')
    page = win.studio_page
    # This probe covers LIVE foreground, without scheduling expensive Fidelity exports.
    page._queue_advanced_preview_job = lambda *a, **kw: None
    settle(12)
    page._seek(probe_ms / 1000)
    settle(8)
    comp = page.video_compositor
    results = {'runtime': 'dev', 'real_user_click': False, 'samples': [], 'screenshots': []}
    def record(phase):
        image = comp.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.bits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(),image.width(),4)
        sample = {'phase': phase, 'opaque_pixels': int((pixels[:,:,3]>150).sum()),
                  'players': [{'pts': int(p.pts_ms), 'age': float(p.frame_age_ms)} for p in comp._players.values()],
                  'layer_count': len(comp._layers), 'visible': comp.isVisible()}
        results['samples'].append(sample)
        sample['overlay_ids'] = page.video.active_compositor_overlay_ids()
        sample['renderer'] = page.ensure_active_subtitle_renderer(reason='native-v2-probe')
        sample['performance'] = comp.performance_snapshot()
        snapshot = getattr(page.advanced_cue_overlay, '_snapshot', None)
        sample['live_text'] = snapshot.text if snapshot else ''
        print(json.dumps(sample), flush=True)
        image.save(str(RUN/f'{phase}-compositor.png'))
        win.raise_()
        win.activateWindow()
        settle(.2)
        rect = win.frameGeometry()
        target = RUN/f'{phase}-screen.png'
        win.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(str(target))
        results['screenshots'].append(str(target))
        page.video.controller.screenshot_to_file(RUN/f'{phase}-mpv.png')
    record('paused')
    comp.reset_performance_samples()
    page._toggle_playback()
    for i in range(3):
        settle(2)
        record(f'playing-{i}')
    page._toggle_playback()
    settle(2)
    record('paused-after')
    from twobyteasr.studio_media_pool import update_video_clip_transform
    update_video_clip_transform(page.project, overlay_track['id'], clip['id'], {'opacity': .45})
    page._sync_video_compositor(page.timeline.playhead_ms)
    settle(1)
    record('translucent-v2')
    page._seek((advanced_start + 3000) / 1000)
    settle(3)
    record('advanced-live')
    page._video_clip_selected(overlay_track['id'], clip['id'])
    settle(1)
    record('video-transform')
    page._video_track_action(overlay_track['id'], 'enabled')
    settle(1)
    record('hidden-track')
    page._video_track_action(overlay_track['id'], 'enabled')
    page._seek(exit_ms / 1000)
    settle(3)
    record('outside-v2')
    playing = [x for x in results['samples'] if x['phase'].startswith('playing')]
    results['playing_nonempty'] = all(x['opaque_pixels'] > 10000 for x in playing)
    results['playing_subtitles'] = all(x['renderer']['foreground_owner'] == 'advanced_live' for x in playing)
    results['advanced_text_current'] = any(x['phase'] == 'advanced-live' and '高级 LIVE' in x['live_text'] for x in results['samples'])
    results['cleaned_hidden_and_outside'] = all(0 not in x['overlay_ids'] for x in results['samples'] if x['phase'] in ('hidden-track', 'outside-v2'))
    page.close_page()
    settle(.3)
    results['closed_overlay_ids'] = page.video.active_compositor_overlay_ids()
    (RUN/'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('EVIDENCE', RUN, flush=True)
    win.hide()
    settle(.2)
    raise SystemExit(0 if results['playing_nonempty'] and results['playing_subtitles'] and results['advanced_text_current'] and results['cleaned_hidden_and_outside'] and not results['closed_overlay_ids'] else 1)

if __name__ == '__main__':
    main()
