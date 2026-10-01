"""Generate an isolated three-track fixture and audit source or --exe PATH."""
from pathlib import Path
import argparse
import json
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scenario', choices=('feedback', 'studio-polish', 'live-edit', 'web-clock', 'providers', 'reliability', 'endurance'), default='feedback')
    parser.add_argument('--media',type=Path)
    parser.add_argument('--seconds',type=float,default=300.)
    parser.add_argument('--rate',type=float,default=4.)
    parser.add_argument('--tracks',choices=('v1','v2','both'),default='both')
    parser.add_argument('--theme', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    output = root/'tmp/theme-track-playback'/('frozen-' if args.exe else 'headed-')/time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    real_local=os.environ.get('LOCALAPPDATA','')
    os.environ['TWOBYTEASR_ACCEPTANCE_REAL_LOCALAPPDATA']=real_local
    codex=Path(real_local)/'Programs/OpenAI/Codex/bin/codex.exe'
    if codex.is_file():os.environ['TWOBYTEASR_CODEX_EXECUTABLE']=str(codex)
    os.environ.update(LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', DASHSCOPE_API_KEY='sk-local-test-dummy')
    from twobyteasr.processes import run_hidden_subprocess
    ffmpeg = root/'tools/ffmpeg/bin/ffmpeg.exe'
    sources = []
    for i, size in enumerate(('1920x1080', '640x480', '640x360')):
        if args.scenario=='endurance':
            if args.media is None or not args.media.is_file():
                raise ValueError('endurance requires --media with an existing read-only source')
            sources.append(args.media.resolve())
            continue
        source = output/f'tone-{i}.mp4'
        run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-y', '-f', 'lavfi', '-i',
            (f'color=c=0x30404a:size={size}:rate=60:duration=6' if args.scenario in ('studio-polish','live-edit') and i == 0
             else f'testsrc2=size={size}:rate=60:duration=6'), '-f', 'lavfi', '-i',
            (f'aevalsrc=0.08*sin(2*PI*({440+i*330}*t+23*t*t))+0.25*eq(mod(n\\,4800)\\,0):s=48000:d=6'
             if args.scenario=='reliability' else f'sine=frequency={440+i*330}:sample_rate=48000:duration=6'),
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-c:a', 'aac', str(source)],
            purpose='isolated feedback audit fixture', check=True, timeout=60)
        sources.append(source)
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, VideoTransform, save_project
    from twobyteasr.studio_media_pool import add_media_asset, create_video_track, add_video_clip, set_audio_master_mode
    project = SubtitleProject(media=StudioMedia(path=str(sources[0]), duration_ms=6000, width=1920, height=1080),
        cues=[StudioCue('cue', 0, 6000, '逐轨音量 · 首尾完整性验证')])
    project.validate()
    if args.theme:
        from twobyteasr.web_theme import import_theme_archive
        from twobyteasr.style_recipe import StyleRecipe
        project.style_recipes[project.cues[0].style_id] = StyleRecipe(
            name='Clock acceptance',engine='remotion',web_theme=import_theme_archive(args.theme)).to_dict()
    for i in ((1,) if args.scenario=='endurance' else (1, 2)):
        asset = add_media_asset(project, sources[i], duration_ms=6000,
            video_metadata={'has_video': True, 'width': 640, 'height': 480 if i == 1 else 360, 'fps': 60},
            audio_metadata={'has_audio': True})
        track = create_video_track(project)
        clip = add_video_clip(project, track.id, asset.asset_id, source_out_ms=6000)
        clip.transform = VideoTransform(scale_x=.45, scale_y=.45, position_x=.3 if i == 1 else .72)
    set_audio_master_mode(project, 'mix_all')
    if args.scenario=='endurance':
        project.media.duration_ms=1_260_000
        project.media.width=2560;project.media.height=1440
        for a in project.media_pool:a.duration_ms=1_260_000
        project.cues[0].end_ms=1_260_000
        for track in project.video_tracks:
            for c in track.clips:c.source_out_ms=c.timeline_out_ms=1_260_000
        project.video_tracks=project.video_tracks[:2]
        project.validate()
        for index,track in enumerate(project.video_tracks):
            enabled=args.tracks=='both' or (args.tracks=='v1' and index==0) or (args.tracks=='v2' and index==1)
            track.enabled=enabled
            for group in project.av_track_groups:
                if group.video_track_id==track.id:
                    next(t for t in project.audio_tracks if t.id==group.audio_track_id).muted=not enabled
        os.environ.update(TWOBYTEASR_ENDURANCE_SECONDS=str(args.seconds),TWOBYTEASR_ENDURANCE_RATE=str(args.rate))
    fixture = save_project(project, output/'fixture.2byteproj')
    os.environ.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(fixture),
                      TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario, TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
                      TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    print('EVIDENCE', output, flush=True)
    if args.exe:
        run_hidden_subprocess([str(args.exe.resolve())], cwd=root, purpose='frozen feedback acceptance',
            timeout=max(180,args.seconds+160) if args.scenario=='endurance' else 260, check=True)
    else:
        from twobyteasr.studio_acceptance_audit import isolate_acceptance_settings, start_acceptance
        isolate_acceptance_settings()
        from PySide6.QtWidgets import QApplication
        import subtitle_core
        from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
        from twobyteasr.theme_manager import apply_theme
        from PySide6.QtCore import QObject, QEvent, QTimer
        app = QApplication([])
        _register_bundled_fonts(); app.setFont(_app_font()); apply_theme('warm', app)
        application_started=time.perf_counter()
        window = MainWindow([], subtitle_core, object(), None)
        class FirstPaint(QObject):
            def eventFilter(self, watched, event):
                if watched is window and event.type()==QEvent.Type.Paint:
                    window.removeEventFilter(self)
                    (output/'application-startup.json').write_text(json.dumps({
                        'main_window_first_paint_ms':(time.perf_counter()-application_started)*1000}),encoding='utf8')
                    def enter():
                        window.open_studio_project(str(fixture), mode='edit', source='feedback-acceptance')
                        start_acceptance(window)
                    QTimer.singleShot(0,enter)
                return False
        window._first_paint_audit=FirstPaint(window)
        window.installEventFilter(window._first_paint_audit)
        window.show()
        app.exec()
    result = json.loads((output/f'{args.scenario}-acceptance.json').read_text(encoding='utf-8'))
    summary = {key: result.get(key) for key in ('build', 'checks', 'error', 'startup', 'pause_delta_ms')}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    assert 'error' not in result and all(result['checks'].values()), summary


if __name__ == '__main__':
    main()
