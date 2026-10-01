"""Silent, <=30s real-widget playback with independently captured screen pixels."""
from pathlib import Path
import argparse
import json
import os
import sys
import time


def make_media(root):
    from twobyteasr.processes import run_hidden_subprocess
    folder = root/'tmp/visible-playback-v2/media/subtitle-safe'
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg = str(root/'tools/ffmpeg/bin/ffmpeg.exe')
    for layer, color in ((1, '0x126879'), (2, '0xb64928')):
        short = folder/f'V{layer}-30s.mp4'
        long = folder/f'V{layer}-120s.mp4'
        if not short.exists():
            filters = [f'testsrc2=s=1920x1080:r=60:d=30',
                f'drawbox=x=0:y=560:w=1920:h=250:color={color}:t=fill',
                'drawbox=x=96:y=650:w=1056:h=130:color=black:t=fill',
                "drawtext=fontfile='C\\:/Windows/Fonts/consola.ttf':text='V%d  FRAME %%{n}  %%{pts\\:hms}':x=100:y=580:fontsize=64:fontcolor=white" % layer]
            # 12 binary cells and four constant sync cells, decoded from pixels.
            for bit in range(16):
                condition = f'mod(floor(n/{2**bit}),2)' if bit < 12 else str((0b1010 >> (bit-12)) & 1)
                filters.append(f"drawbox=x={100+64*bit}:y=660:w=56:h=100:color=white:t=fill:enable='{condition}'")
            run_hidden_subprocess([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', ','.join(filters),
                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-g', '60',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k', str(short)],
                purpose='silent 1080p60 frame-code fixture', check=True, timeout=120)
        if not long.exists():
            run_hidden_subprocess([ffmpeg, '-v', 'error', '-y', '-stream_loop', '3', '-i', str(short),
                '-c', 'copy', str(long)], purpose='lossless repeat for twenty seconds at 4x', check=True, timeout=30)
    return folder


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--rate', type=float, default=4)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--ablation', choices=['none','web-off','waveform-off','selection-off','audio-off','video-only'], default='none')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--captions', choices=['none','native','web'],default='none')
    parser.add_argument('--mode', choices=['playback','placement','filmstrip'],default='playback')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--theme',type=Path)
    parser.add_argument('--recover',action='store_true')
    parser.add_argument('--capture',choices=['gdi','wgc'],default='gdi')
    parser.add_argument('--real-project',type=Path,help='Read-only project copy; preserve video packets and silence audio in isolated media')
    parser.add_argument('--thumbnails',choices=['on','off'],default='on')
    args = parser.parse_args()
    if args.mode == 'placement':
        if not .1 <= args.seconds <= 8: parser.error('Placement checks must use a 0.1 to 8 second budget')
    elif not 15 <= args.seconds <= 30: parser.error('Each playback scene must be 15 to 30 seconds')
    media = root/'tmp/progressive-v2-theme/silent-media' if args.real_project else make_media(root)
    media.mkdir(parents=True,exist_ok=True)
    if args.mode=='filmstrip':
        from twobyteasr.processes import run_hidden_subprocess
        for layer in (1,2):
            long=media/f'V{layer}-1200s.mp4'
            if not long.exists():
                run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y',
                    '-f','lavfi','-i',f'testsrc2=s=640x360:r=2:d=1200',
                    '-vf',"drawtext=fontfile='C\\:/Windows/Fonts/consola.ttf':text='SOURCE %{pts\\:hms}':x=15:y=290:fontsize=24:fontcolor=white:box=1:boxcolor=black",
                    '-an','-c:v','libx264','-preset','ultrafast','-crf','30','-g','2',str(long)],
                    purpose='twenty-minute silent filmstrip fixture, no playback',check=True,timeout=90)
    def tc(ms):
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    (media/'captions.srt').write_text('\n\n'.join(f'{i+1}\n{tc(i*2000)} --> {tc(i*2000+1900)}\n这是第{i+1}条字幕，画面持续运动' for i in range(600)),encoding='utf8')
    if args.prepare_only:
        print(media); return
    out = root/'tmp/visible-playback-v2/runs'/f'{time.strftime("%Y%m%d-%H%M%S")}-{args.rate:g}x-{args.captions}-{args.ablation}'
    out.mkdir(parents=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1', DASHSCOPE_API_KEY='sk-local-test-dummy', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'), TWOBYTEASR_ACCEPTANCE_SCENARIO='visible-playback',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_VISIBLE_MEDIA=str(media), TWOBYTEASR_VISIBLE_RATE=str(args.rate),
        TWOBYTEASR_VISIBLE_SECONDS=str(args.seconds), TWOBYTEASR_VISIBLE_ABLATION=args.ablation,
        TWOBYTEASR_VISIBLE_PROFILE='1' if args.profile else '0')
    os.environ['TWOBYTEASR_VISIBLE_CAPTIONS']=args.captions
    os.environ['TWOBYTEASR_VISIBLE_MODE']=args.mode
    os.environ['TWOBYTEASR_VISIBLE_THEME']=str(args.theme.resolve()) if args.theme else ''
    os.environ['TWOBYTEASR_VISIBLE_RECOVER']='1' if args.recover else '0'
    os.environ['TWOBYTEASR_VISIBLE_CAPTURE']=args.capture
    os.environ['TWOBYTEASR_VISIBLE_REAL']='1' if args.real_project else '0'
    os.environ['TWOBYTEASR_VISIBLE_THUMBNAILS']=args.thumbnails
    os.environ['TWOBYTEASR_STARTUP_TRACE']=str(out/'startup-trace.jsonl')
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, save_project
    from twobyteasr.processes import run_hidden_subprocess
    if args.real_project:
        # Recursively replace only media path strings in the isolated fixture.
        # Video is stream copied; audio packet content alone is made silent.
        data=json.loads(args.real_project.read_text('utf8'));mapping={}
        import hashlib
        for asset in data['media_pool']:
            source=Path(asset['canonical_source']);stat=source.stat()
            key=hashlib.sha256(f'{source}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
            destination=media/(key+'.mp4')
            if not destination.exists():
                run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-i',str(source),
                    '-map','0:v:0','-map','0:a:0?','-c:v','copy','-af','volume=0','-c:a','aac',str(destination)],
                    purpose='isolated actual video packet copy with silent audio',check=True,timeout=30)
            mapping[str(source)]=str(destination)
        def replace(value):
            if isinstance(value,str):return mapping.get(value,value)
            if isinstance(value,list):return [replace(v) for v in value]
            if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
            return value
        (out/'fixture.2byteproj').write_text(json.dumps(replace(data),ensure_ascii=False,indent=2),encoding='utf8')
        (out/'media-map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf8')
    else:
        save_project(SubtitleProject(media=StudioMedia(path='', display_name='静音呈现诊断')), out/'fixture.2byteproj')
    print('EVIDENCE', out, flush=True)
    with (out/'application.log').open('wb') as log:
        result = run_hidden_subprocess([str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root/'quick_start.py')], cwd=root,
            purpose='silent short Studio screen-content audit', stdout=log, stderr=log, timeout=150)
    print('exit', result.returncode, flush=True)
    if args.capture=='wgc' and not args.real_project:
        run_hidden_subprocess([sys.executable,'-B',str(root/'scripts/analyze_visible_playback.py'),str(out)],purpose='count actual frames from short WGC recording',check=True,timeout=40)
    report = json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({k:report.get(k) for k in ('error','screen','checks')}, ensure_ascii=False), flush=True)
    if result.returncode or report.get('error') or not all(report.get('checks',{}).values()): raise SystemExit(1)


if __name__ == '__main__': main()
