"""Bounded real-window cue handoff audit; synthetic four-second media only."""
import argparse, copy, json, os, subprocess, sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fps', default='60')
    parser.add_argument('--routes', default='native,static,html')
    parser.add_argument('--gap', type=int, default=0)
    parser.add_argument('--count',type=int,choices=(2,20,1000),default=2)
    parser.add_argument('--speakers',type=int,choices=(1,2),default=1)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--media',type=Path,help='Reuse unmodified synthetic media for independent pixel-to-source PTS matching; barcode analysis is unavailable')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root / 'tmp') or out.exists():
        raise ValueError('A fresh repository tmp subdirectory is required')
    out.mkdir(parents=True)
    (out/'temp').mkdir()
    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'),
               TEMP=str(out/'temp'),TMP=str(out/'temp'),
               QT_QPA_PLATFORM='windows', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-boundary',
               TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
               TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    os.environ.update({key: env[key] for key in ('LOCALAPPDATA', 'APPDATA','TEMP','TMP')})
    from twobyteasr.processes import run_hidden_subprocess
    ffmpeg = str(root/'tools/ffmpeg/bin/ffmpeg.exe')
    duration=4 if args.count==2 else 2+(args.count-2)*.05+1
    filters = [f'color=c=0x2c145c:s=1280x720:r={args.fps}:d={duration}',
               'drawbox=x=30:y=30:w=1060:h=80:color=black:t=fill']
    for bit in range(16):
        condition = f'mod(floor(n/{2**bit}),2)' if bit < 12 else str((10 >> (bit-12)) & 1)
        filters.append(f"drawbox=x={40+64*bit}:y=40:w=48:h=60:color=white:t=fill:enable='{condition}'")
    media = args.media.resolve() if args.media else out/'synthetic.mp4'
    if args.media:
        if not media.is_file():raise ValueError('Explicit fixture media does not exist')
    else:
        run_hidden_subprocess([ffmpeg, '-v','error','-f','lavfi','-i',','.join(filters),
            '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(duration),'-c:v','libx264',
            '-preset','ultrafast','-crf','12','-pix_fmt','yuv420p','-c:a','aac',str(media)],
            check=True, timeout=45, purpose='four-second no-animation caption boundary fixture')
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,SubtitleStyle,save_project,hydrate_media_contract
    from twobyteasr.studio_helpers import probe_media_identity
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.visual_design_graph import glitch_graph,MotionGraph
    from twobyteasr.web_theme import WebThemeDocument
    media_identity=probe_media_identity(str(media))
    if args.media and media_identity.get('duration_ms',0)<duration*1000:
        raise ValueError('Reused media is shorter than the complete audit')
    config = dict(fps=args.fps,gap=args.gap,count=args.count,speakers=args.speakers,
        media=str(media),barcode=not bool(args.media),
        play_seconds=2.3 if args.count==2 else duration-.7,cases=[])
    for route in args.routes.split(','):
        style = SubtitleStyle(id='sample',name='边界无动画',font_family='Source Han Sans SC',
            font_size=94,font_weight=900,outline_width=4,shadow=0,position_x=960,position_y=900)
        project = SubtitleProject(media=StudioMedia(str(media),duration_ms=round(duration*1000),width=1280,height=720),
            speakers=[StudioSpeaker('AUDIT')]+([StudioSpeaker('OTHER')] if args.speakers==2 else []),styles=[style],cues=[
                StudioCue('A',0,1000,'甲甲甲甲 AAAA','AUDIT',style_id='sample'),
                StudioCue('B',1000+args.gap,2000,'乙乙乙乙 BBBB','OTHER' if args.speakers==2 else 'AUDIT',style_id='sample')])
        for index in range(2,args.count):
            project.cues.append(StudioCue(f'cue-{index}',2000+(index-2)*50,2000+(index-1)*50,
                '乙乙乙乙 BBBB' if index%2 else '甲甲甲甲 AAAA',
                'OTHER' if args.speakers==2 and index%2 else 'AUDIT',style_id='sample'))
        if route == 'static':
            graph=glitch_graph();graph.motion_graph=MotionGraph(2000,[])
            graph.effect_layers=[];graph.decoration_layers=[]
            project.style_recipes['sample']=StyleRecipe('静态无动画',engine='remotion',visual_graph=graph.to_dict(),
                typography={'fontFamily':style.font_family,'fontSize':94,'fontWeight':900},colors={'fill':'#FFFFFFFF'}).to_dict()
        elif route == 'html':
            theme=WebThemeDocument.from_dict(dict(name='网页无动画',id='boundary-no-animation',
                palette={'primary':'#FFFFFF','text':'#FFFFFF'},
                appearance={'fontFamily':'Source Han Sans SC Heavy','fontSize':94,'fontWeight':900,
                    'color':'#FFFFFF','strokeColor':'#000000','strokeWidth':4},
                cueHtml='<div class="caption">{{text}}</div>',
                cueCss='.caption{position:absolute;left:50%;bottom:12%;transform:translateX(-50%);width:max-content;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:900;color:#FFFFFF;line-height:1.1;white-space:pre;-webkit-text-stroke:var(--wt-stroke-w) #000000;paint-order:stroke fill;}',
                stageHtml='',stageCss='')).to_dict()
            project.style_recipes['sample']=StyleRecipe('网页无动画',engine='remotion',web_theme=theme).to_dict()
        hydrate_media_contract(project,probe_media_identity(str(media)))
        save_project(project,out/(route+'.2byteproj'))
        config['cases'].append(dict(id=route,route=route,cues=[dict(id=c.id,start=c.start_ms,end=c.end_ms,
            speaker=c.speaker_id,pixels='A' if c.text.startswith('甲') else 'B') for c in project.cues]))
    (out/'fixture.2byteproj').write_bytes((out/(config['cases'][0]['id']+'.2byteproj')).read_bytes())
    (out/'matrix.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf8')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    with (out/'process.log').open('w',encoding='utf8') as log:
        child=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
            timeout=max(240,round(3*(duration+60))),purpose='bounded native/static/HTML real-window boundary capture')
    if (out/'result.json').exists():
        result=json.loads((out/'result.json').read_text('utf8'))
        print(json.dumps(dict(error=result.get('error'),cases=[c['id'] for c in result.get('cases',[])])))
    else: print('No result; see process.log')
    return child.returncode


if __name__=='__main__': raise SystemExit(main())
