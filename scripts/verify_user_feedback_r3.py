"""Focused normal-window checks for r3, using only isolated synthetic media."""
import argparse, json, os, subprocess, sys
from pathlib import Path

def main():
 root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
 parser.add_argument('--scale',type=float);args=parser.parse_args();out=args.output.resolve()
 if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('fresh repository tmp directory required')
 out.mkdir(parents=True)
 for name in ('sources','local','roaming','temp'): (out/name).mkdir()
 from twobyteasr.processes import run_hidden_subprocess
 sources=[]
 for i,(freq,color) in enumerate(((440,'0x183347'),(660,'0x303438'),(880,'0x243e52')),1):
  path=out/'sources'/f'中文 素材 {i} 新名称.mp4'
  run_hidden_subprocess([root/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=640x360:r=25',
   '-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000','-t','12','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',path],
   timeout=30,check=True,capture_output=True,purpose='isolated r3 media')
  sources.append(path)
 from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioSpeaker,StudioCue,SubtitleStyle,save_project,hydrate_media_contract
 from twobyteasr.studio_helpers import probe_media_identity
 from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip,set_video_track_state
 from twobyteasr.studio_edit_sequence import sequence_of
 p=SubtitleProject(media=StudioMedia(str(sources[0]),duration_ms=12000,width=640,height=360));p.validate()
 hydrate_media_contract(p,probe_media_identity(str(sources[0])))
 set_video_track_state(p,'V1',locked=False);sequence_of(p).video_track_locked=False
 for i,source in enumerate(sources[1:],2):
  a=add_media_asset(p,source if i==2 else out/'已经不存在的目录'/'旧名字.mp4',duration_ms=12000,
   video_metadata={'has_video':True,'width':640,'height':360},audio_metadata={'has_audio':True,'sample_rate':48000,'channels':1})
  t=create_video_track(p)
  add_video_clip(p,t.id,a.asset_id,source_out_ms=4000 if i==2 else 10000)
  if i==2:add_video_clip(p,t.id,a.asset_id,source_in_ms=4000,source_out_ms=8000,timeline_in_ms=6000)
 p.speakers=[StudioSpeaker('S'+str(i),name='S0'+str(i)) for i in range(3)]
 p.styles=[SubtitleStyle('style'+str(i),'style'+str(i),font_family='Microsoft YaHei UI',font_size=56,primary_color=c,position_x=960,position_y=200+i*290)
  for i,c in enumerate(('#ff5555','#55ff55','#55aaff'))]
 p.cues=[StudioCue('cue'+str(i),0,11500,'第'+str(i+1)+'轨 独立字幕','S'+str(i),style_id='style'+str(i)) for i in range(3)]
 p.studio_state.update(playhead_ms=1000,speaker_track_order=['S0','S1','S2'])
 save_project(p,out/'fixture.2byteproj')
 (out/'audit-config.json').write_text(json.dumps(dict(relink_path=str(sources[2]),offline_asset_id=p.video_tracks[-1].clips[0].asset_id),ensure_ascii=False),'utf8')
 env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'),
  PYTHONIOENCODING='utf-8',QT_QPA_PLATFORM='windows',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
  TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='user-feedback-r3')
 if args.scale:env['QT_SCALE_FACTOR']=str(args.scale)
 command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
 results=[]
 for phase in ('exercise','reopen'):
  env['TWOBYTEASR_USER_FEEDBACK_PHASE']=phase
  with (out/(phase+'-process.log')).open('w',encoding='utf8') as log:
   child=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=210,purpose='r3 normal UI '+phase)
  result=json.loads((out/(phase+'-result.json')).read_text('utf8'));results.append(result)
  if child.returncode or not result['passed']:break
 passed=len(results)==2 and all(r['passed'] for r in results)
 (out/'combined.json').write_text(json.dumps(dict(passed=passed,phases=results),ensure_ascii=False,indent=2),'utf8')
 print(json.dumps(dict(passed=passed,output=str(out),error=results[-1].get('error','')),ensure_ascii=False));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
