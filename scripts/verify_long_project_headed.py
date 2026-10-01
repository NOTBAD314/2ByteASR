"""Read-only long-media acceptance. Every artifact/configuration is under tmp."""
from pathlib import Path
import argparse
import json
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--cues', type=Path, required=True, help='Existing subtitle corpus, read only')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--mode', choices=('timeline', 'followers', 'endurance', 'transitions', 'ai'), default='timeline')
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--seek-cache', type=Path)
    parser.add_argument('--targets-ms',default='0,611234,5080167')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    output = root/'tmp/long-project'/time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', DASHSCOPE_API_KEY='sk-local-test-dummy')
    os.environ['TWOBYTEASR_SEEK_CACHE_ROOT'] = str((args.seek_cache or root/'tmp/long-project-cache/seek').resolve())
    from twobyteasr.processes import run_hidden_subprocess
    probe = run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffprobe.exe'), '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', str(args.media.resolve())],
        purpose='read-only long-media metadata', timeout=15, capture_output=True, check=True)
    metadata = json.loads(probe.stdout)
    (output/'media-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf8')
    duration = round(float(metadata['format']['duration'])*1000)
    video = next(s for s in metadata['streams'] if s['codec_type']=='video')
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, VideoTransform, load_project, save_project
    from twobyteasr.studio_media_pool import add_media_asset, create_video_track, add_video_clip
    original = load_project(args.cues)
    project = SubtitleProject(media=StudioMedia(path=str(args.media.resolve()), duration_ms=duration,
        width=video['width'], height=video['height']), cues=original.cues, speakers=original.speakers,
        styles=original.styles)
    project.validate()
    for index in (1, 2):
        asset = add_media_asset(project, args.media.resolve(), duration_ms=duration,
            video_metadata={'has_video':True, 'width':video['width'], 'height':video['height'], 'fps':60},
            audio_metadata={'has_audio':True})
        track = create_video_track(project)
        clip = add_video_clip(project, track.id, asset.asset_id, source_out_ms=duration)
        clip.transform = VideoTransform(scale_x=.45, scale_y=.45, position_x=.28 if index==1 else .73)
        if args.mode=='transitions':
            import copy
            from twobyteasr.studio_media_pool import sync_linked_av_contract
            clip.source_in_ms=611234;clip.source_out_ms=613234;clip.timeline_out_ms=2000
            right=add_video_clip(project,track.id,asset.asset_id,timeline_in_ms=2000,
                source_in_ms=3661234,source_out_ms=3669234)
            right.playback_rate=2.;right.timeline_out_ms=6000
            right.transform=copy.deepcopy(clip.transform)
            sync_linked_av_contract(project)
    fixture = save_project(project, output/'fixture.2byteproj')
    if args.mode=='ai':
        from twobyteasr.studio_project import StudioCue
        from twobyteasr.web_theme import parse_web_theme_sections
        project.cues=[StudioCue('original',0,3000,'我送的不是货，是整个人类的希望',speaker_id=project.speakers[0].id if project.speakers else '')]
        for track in project.video_tracks[1:]:track.enabled=False
        fixture=save_project(project,output/'fixture.2byteproj')
        raw=(root/'tests/fixtures/death_stranding_original.txt').read_text(encoding='utf8')
        (output/'original-response.txt').write_text(raw,encoding='utf8')
        (output/'theme.json').write_text(json.dumps(parse_web_theme_sections(raw),ensure_ascii=False),encoding='utf8')
    (output/'fixture-provenance.json').write_text(json.dumps({'media':str(args.media.resolve()),
        'cue_corpus':str(args.cues.resolve()), 'cues':len(project.cues), 'duration_ms':duration,
        'transcript_matches_recording':original.media.path==str(args.media.resolve()),
        'kind':'real recording with explicit theme sample text' if args.mode=='ai' else 'real recording with existing real subtitle corpus; no synthetic cues'}, ensure_ascii=False, indent=2),encoding='utf8')
    os.environ.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='theme-draft' if args.mode=='ai' else 'long-project', TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_LONG_MODE=args.mode,
        TWOBYTEASR_LONG_TARGETS=args.targets_ms,
        TWOBYTEASR_LONG_SECONDS=str(args.seconds))
    print('EVIDENCE', output, flush=True)
    if args.exe:
        run_hidden_subprocess([str(args.exe.resolve())], cwd=root, purpose='frozen long-project acceptance',
            timeout=max(600,args.seconds+240), check=True)
    else:
        from twobyteasr.studio_acceptance_audit import isolate_acceptance_settings, start_acceptance
        isolate_acceptance_settings()
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        import subtitle_core
        from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
        from twobyteasr.theme_manager import apply_theme
        app = QApplication([])
        _register_bundled_fonts(); app.setFont(_app_font()); apply_theme('warm', app)
        window = MainWindow([], subtitle_core, object(), None)
        window.show()
        def enter():
            window.open_studio_project(str(fixture), mode='edit', source='long-project-acceptance')
            start_acceptance(window)
        QTimer.singleShot(0, enter)
        app.exec()
    result=json.loads((output/('theme-draft-acceptance.json' if args.mode=='ai' else 'long-project-acceptance.json')).read_text(encoding='utf8'))
    print(json.dumps({k:result.get(k) for k in ('checks','summary','error')},ensure_ascii=False,indent=2))
    if result.get('error'): raise RuntimeError(result['error'])
    if not all(result.get('checks',{}).values()):raise AssertionError('Some measured acceptance gates failed; see evidence')


if __name__=='__main__':main()
