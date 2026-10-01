"""Normal source/frozen user-failure acceptance with small synthetic media."""
import argparse,json,os,sys,subprocess
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    parser.add_argument('--scenario',choices=['audio','tracks','offline'],default='audio')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use a fresh directory under repository tmp')
    out.mkdir(parents=True);(out/'temp').mkdir();(out/'sources').mkdir()
    from twobyteasr.processes import run_hidden_subprocess
    ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    def make(name,freq,color=None):
        path=out/'sources'/name
        command=[ffmpeg,'-v','error','-y']
        if color:command+=['-f','lavfi','-i',f'color=c={color}:s=640x360:r=25']
        command+=['-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000','-t','120']
        command+=['-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac'] if color else ['-c:a','pcm_s16le']
        run_hidden_subprocess(command+[path],check=True,capture_output=True,timeout=35,purpose='small synthetic acceptance media')
        return path
    sources=[make('video-440.mp4',440,'0x183347'),make('video-660.mp4',660,'0x303438'),make('audio-880.wav',880)]
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,SubtitleStyle,save_project,hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip,set_video_track_state
    from twobyteasr.studio_edit_sequence import sequence_of
    p=SubtitleProject(media=StudioMedia(str(sources[0]),duration_ms=120000,width=640,height=360))
    p.validate()
    hydrate_media_contract(p,probe_media_identity(str(sources[0])))
    set_video_track_state(p,'V1',locked=False);sequence_of(p).video_track_locked=False
    a=add_media_asset(p,sources[1],duration_ms=120000,video_metadata={'has_video':True,'width':640,'height':360},audio_metadata={'has_audio':True,'sample_rate':48000,'channels':1})
    t=create_video_track(p,'660 Hz 视频');add_video_clip(p,t.id,a.asset_id,source_out_ms=120000)
    a=add_media_asset(p,sources[2],duration_ms=120000,video_metadata={'has_video':False},audio_metadata={'has_audio':True,'sample_rate':48000,'channels':1})
    independent=next(t.id for t in p.audio_tracks if any(c.asset_id==a.asset_id for c in t.clips))
    p.speakers=[StudioSpeaker(f'S{i}',name=f'验收字幕 {i+1}') for i in range(3)]
    p.styles=[SubtitleStyle(f'style{i}',f'style{i}',font_family='Microsoft YaHei UI',font_size=56,
        primary_color=['#ff5555','#55ff55','#55aaff'][i],position_x=960,position_y=200+i*290) for i in range(3)]
    p.cues=[StudioCue(f'cue{i}',0,115000,f'第 {i+1} 轨 独立字幕',f'S{i}',style_id=f'style{i}') for i in range(3)]
    p.studio_state.update(playhead_ms=1000,speaker_track_order=['S0','S1','S2'])
    junction=None
    if args.scenario=='audio':
        # A removable directory junction models a disappearing volume/path.
        # Windows denies renaming a file while its decoder handle is open.
        junction=out/'live-source'
        run_hidden_subprocess(['cmd','/d','/c','mklink','/J',str(junction),str(out/'sources')],check=True,capture_output=True,
            timeout=5,purpose='owned acceptance source mount')
        alias=str(junction/sources[0].name);original=str(sources[0])
        p.media.path=alias
        for asset in p.media_pool:
            if asset.canonical_source==original:asset.canonical_source=alias
        seq=sequence_of(p);seq.source_path=alias
        for segment in seq.segments:
            if segment.source_path==original:segment.source_path=alias
    if args.scenario=='offline':
        # Only owned generated files are renamed. Video sound goes offline,
        # while the independent 880 Hz audio and all subtitle cues remain.
        for source in sources[:2]:source.rename(source.with_suffix('.offline'))
    config=dict(matrix=args.scenario,independent_audio_id=independent,expected_cue_count=3,
        offline_count=2 if args.scenario=='offline' else 0,has_audio=True,
        runtime_source=p.media.path,runtime_junction=str(junction) if junction else '',
        runtime_target=str(out/'sources'),relink_path=str(sources[0].with_suffix('.offline')))
    save_project(p,out/'fixture.2byteproj');(out/'audit-config.json').write_text(json.dumps(config),'utf8')
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'),
        QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf-8',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='user-failures')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    results=[]
    for phase in ('exercise','reopen'):
        env['TWOBYTEASR_USER_FAILURE_PHASE']=phase
        with (out/(phase+'-process.log')).open('w',encoding='utf8') as log:
            run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,purpose='normal UI user failure '+phase)
        result=json.loads((out/'result.json').read_text('utf8'))
        (out/(phase+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8');results.append(result)
        if result['error'] or not all(result.get('checks',{}).values()):break
    passed=len(results)==2 and all(not r['error'] and all(r.get('checks',{}).values()) for r in results)
    (out/'combined.json').write_text(json.dumps(dict(passed=passed,phases=results),ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=passed,checks=result.get('checks'),error=result['error'],output=str(out)),ensure_ascii=False))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
