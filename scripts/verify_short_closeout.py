"""One bounded real-media V1/V2/Web flow, source or a single new package."""
from pathlib import Path
import argparse,json,os,sys,time

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--media',type=Path,required=True)
    parser.add_argument('--seek-cache',type=Path,required=True)
    parser.add_argument('--theme',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--smoke',action='store_true',help='Brief packaged smoke after the source four-minute flow')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    output=root/'tmp/four-p0-closeout'/('frozen-' if args.exe else 'headed-')/time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(output/'local'),APPDATA=str(output/'roaming'),QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1',DASHSCOPE_API_KEY='sk-local-test-dummy',
        TWOBYTEASR_SEEK_CACHE_ROOT=str(args.seek_cache.resolve()))
    os.environ['TWOBYTEASR_SHORT_SMOKE']='1' if args.smoke else '0'
    from twobyteasr.processes import run_hidden_subprocess
    probe=run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffprobe.exe'),'-v','error','-show_streams','-show_format','-of','json',str(args.media.resolve())],
        purpose='short audit read-only metadata',timeout=10,capture_output=True,check=True)
    meta=json.loads(probe.stdout);video=next(s for s in meta['streams'] if s['codec_type']=='video')
    duration=round(float(meta['format']['duration'])*1000)
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,VideoTransform,save_project
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip,set_audio_master_mode,set_video_track_state
    project=SubtitleProject(media=StudioMedia(path=str(args.media.resolve()),duration_ms=duration,width=video['width'],height=video['height']),
        cues=[StudioCue('p0-cue' if i==0 else f'p0-cue-{i}',i*30000,(i+1)*30000,'碰撞必须得做的特别好') for i in range(20)]);project.validate()
    asset=add_media_asset(project,args.media.resolve(),duration_ms=duration,
        video_metadata={'has_video':True,'width':video['width'],'height':video['height'],'fps':60},audio_metadata={'has_audio':True})
    track=create_video_track(project);clip=add_video_clip(project,track.id,asset.asset_id,source_out_ms=duration)
    clip.transform=VideoTransform(scale_x=.45,scale_y=.45,position_x=.72)
    set_video_track_state(project,track.id,enabled=False,muted=True);set_audio_master_mode(project,'mix_all')
    fixture=save_project(project,output/'fixture.2byteproj')
    (output/'theme.json').write_bytes(args.theme.read_bytes())
    (output/'provenance.json').write_text(json.dumps(dict(media=str(args.media.resolve()),theme=str(args.theme.resolve()),
        caption='explicit regression caption; not a claimed transcript',seek_cache=str(args.seek_cache.resolve())),ensure_ascii=False,indent=2),encoding='utf8')
    os.environ.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='short-closeout',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    print('EVIDENCE',output,flush=True)
    if args.exe:
        run_hidden_subprocess([str(args.exe.resolve())],cwd=root,purpose='frozen short closeout',timeout=285,check=True)
    else:
        from twobyteasr.studio_acceptance_audit import isolate_acceptance_settings,start_acceptance
        isolate_acceptance_settings()
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        import subtitle_core
        from twobyteasr.ui import MainWindow,_register_bundled_fonts,_app_font
        from twobyteasr.theme_manager import apply_theme
        app=QApplication([]);_register_bundled_fonts();app.setFont(_app_font());apply_theme('warm',app)
        window=MainWindow([],subtitle_core,object(),None);window.show()
        def enter():
            window.open_studio_project(str(fixture),mode='edit',source='short-closeout')
            start_acceptance(window)
        QTimer.singleShot(0,enter);app.exec()
    result=json.loads((output/'short-closeout-acceptance.json').read_text(encoding='utf8'))
    print(json.dumps({k:result.get(k) for k in ('checks','summary','error','elapsed_seconds')},ensure_ascii=False,indent=2))
    assert not result.get('error') and all(result['checks'].values())
if __name__=='__main__':main()
