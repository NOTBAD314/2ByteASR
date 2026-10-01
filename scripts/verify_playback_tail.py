"""Launch a normal Studio process against an isolated real/dense project copy."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--media',type=Path,help='Explicit synthetic media for a fresh numbered-cue fixture')
    parser.add_argument('--cue-corpus', type=Path, help='Use distinct existing cue entries once each for the dense run')
    parser.add_argument('--count', type=int, default=112)
    parser.add_argument('--actual', action='store_true', help='Keep source project times/content unchanged')
    parser.add_argument('--tracks', type=int, choices=(1,2), default=2)
    parser.add_argument('--caption', choices=('native','static','html'), default='html')
    parser.add_argument('--theme', type=Path)
    parser.add_argument('--panels', choices=('both','list','tools','none'), default='both')
    parser.add_argument('--selected', choices=('0','1'), default='1')
    parser.add_argument('--dpi', type=float, default=1.5)
    parser.add_argument('--window-seconds', type=float, default=0, help='Follow a bounded timeline viewport instead of fitting the entire stress project')
    parser.add_argument('--probe', choices=('detailed','light'), default='detailed')
    parser.add_argument('--exercise-gc-limit', action='store_true', help='Diagnostic only: allocate 129 MiB during playback and retain all resulting stalls')
    parser.add_argument('--ablation', choices=('none','list-highlight','autoscroll','inspector','overlay','html','waveform','snap','elapsed-source','coarse-elapsed','no-gc-budget','gc','opaque','workspace-opaque','consumer-8ms'), default='none')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(root/'tmp'): raise ValueError('Output must be inside repository tmp')
    if (out/'result.json').exists(): raise ValueError('Refusing to overwrite existing evidence')
    out.mkdir(parents=True, exist_ok=True)
    (out/'temp').mkdir(exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'), APPDATA=str(out/'roaming'), QT_QPA_PLATFORM='windows',
        TEMP=str(out/'temp'),TMP=str(out/'temp'),
        QT_SCALE_FACTOR=str(args.dpi/1.75), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime', TWOBYTEASR_CAPTION_AUDIT_MODE='boundary-tail',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_BOUNDARY_PANELS=args.panels, TWOBYTEASR_PLAYBACK_PROBE='1',
        TWOBYTEASR_PLAYBACK_PROBE_LIMIT='1500000', TWOBYTEASR_TAIL_ABLATION=args.ablation,
        TWOBYTEASR_TAIL_SELECTED=args.selected)
    os.environ['TWOBYTEASR_TAIL_DPR']=str(args.dpi)
    os.environ['TWOBYTEASR_TAIL_CAPTION']=args.caption
    os.environ['TWOBYTEASR_TAIL_TRACKS']=str(args.tracks)
    os.environ['TWOBYTEASR_TAIL_WINDOW_MS']=str(round(args.window_seconds*1000))
    os.environ['TWOBYTEASR_PLAYBACK_PROBE_DETAIL']=args.probe
    os.environ['TWOBYTEASR_TAIL_GC_PRESSURE']='1' if args.exercise_gc_limit else '0'
    from twobyteasr.studio_project import (SubtitleProject, StudioMedia, StudioCue, StudioSpeaker,
                                          load_project, save_project, hydrate_media_contract)
    from twobyteasr.studio_helpers import probe_media_identity
    from twobyteasr.processes import run_hidden_subprocess
    source = load_project(args.project) if args.project else None
    corpus = json.loads(args.cue_corpus.read_text('utf8')).get('cues', []) if args.cue_corpus else []
    if args.cue_corpus and len(corpus) < args.count:
        raise ValueError('The corpus must contain at least count cue entries; repeating entries is prohibited')
    provenance = dict(source_project_sha256=hashlib.sha256(args.project.read_bytes()).hexdigest() if args.project else None,
                      source_cue_count=len(source.cues) if source else None,
                      actual_times_preserved=args.actual,
                      dense_duration_ms=None if args.actual else 225,
                      privacy='Source project/media read-only; fixture saved in isolated tmp')
    if corpus:
        provenance.update(corpus_sha256=hashlib.sha256(args.cue_corpus.read_bytes()).hexdigest(),
                          corpus_cues=len(corpus), unique_corpus_entries=args.count,
                          corpus_matches_media=False)
    if args.actual:
        if source is None: raise ValueError('--actual requires --project')
        project = source
        active_speakers = list(dict.fromkeys(cue.speaker_id for cue in project.cues))
        provenance['original_active_subtitle_tracks']=len(active_speakers)
        if len(active_speakers) > args.tracks:
            raise ValueError('Refusing to remove original subtitle tracks for an actual-project audit')
        if args.tracks == 2 and len(active_speakers) == 1:
            from copy import copy
            original_cues = tuple(project.cues)
            speaker = copy(next(item for item in project.speakers if item.id == active_speakers[0]))
            existing = {item.id for item in project.speakers}
            speaker.id = 'AUDIT-SECOND'
            while speaker.id in existing: speaker.id += '-B'
            project.speakers.append(speaker)
            cue_ids = {cue.id for cue in project.cues}
            for original_cue in original_cues:
                copied = deepcopy(original_cue)
                copied.id = 'AUDIT-SECOND-'+original_cue.id
                while copied.id in cue_ids: copied.id += '-B'
                copied.speaker_id = speaker.id
                cue_ids.add(copied.id)
                project.cues.append(copied)
            provenance['track_transform']=dict(operation='duplicate_each_source_cue_once',
                copied_cue_count=len(original_cues), times_text_and_appearance_preserved=True)
        seconds = project.media.duration_ms/1000-.1
        count = len({c.start_ms for c in project.cues})
    else:
        if not 32 <= args.count <= 1200: raise ValueError('count must be 32..1200')
        count = args.count; seconds = .45+count*.225
        media = Path(source.media.path) if source else args.media or root/'tmp/visible-playback-v2/media/subtitle-safe/V1-30s.mp4'
        duration = source.media.duration_ms if source else int(probe_media_identity(str(media)).get('duration_ms') or 30000)
        if seconds*1000 > duration:
            loop = out.parent/f'looped-{hashlib.sha256(str(media).encode()).hexdigest()[:8]}-{count}.mp4'
            if not loop.exists():
                run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y',
                    '-stream_loop','-1','-i',str(media),'-t',str(seconds+2),'-map','0:v:0','-map','0:a?',
                    '-c','copy',str(loop)], check=True, timeout=90, purpose='Prepare local read-only media repetition for 1000 cue audit')
            media = loop; duration = int((seconds+2)*1000)
        cues = []
        for track in range(args.tracks):
            for index in range(count):
                template = source.cues[index % len(source.cues)] if source and source.cues else None
                cue = StudioCue(f'T{track+1}-{index:04}',250+index*225,475+index*225,
                                corpus[index]['text'] if corpus else template.text if template else f'第{index+1}条字幕', f'S0{track+1}')
                if template and args.caption=='static':
                    identity = (cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id)
                    cue = deepcopy(template)
                    cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id = identity
                cues.append(cue)
        project = SubtitleProject(media=StudioMedia(str(media), duration_ms=duration,width=1920,height=1080),
            speakers=[StudioSpeaker(f'S0{i+1}') for i in range(args.tracks)], cues=cues)
        if source:
            project.generation_metadata = deepcopy(source.generation_metadata)
            if args.caption=='static':
                project.styles = deepcopy(source.styles)
                project.style_recipes = deepcopy(source.style_recipes)
        hydrate_media_contract(project, probe_media_identity(str(media)))
    if args.caption=='html':
        theme_path = args.theme or root/'examples/web-themes/balatro-object-motion-20260911/A/theme.json'
        theme = json.loads(theme_path.read_text('utf8'))
        project.style_recipes['tail-html'] = dict(name=theme['name'],engine='remotion',webTheme=theme)
        for cue in project.cues: cue.style_id='tail-html'
        provenance['theme_sha256']=hashlib.sha256(theme_path.read_bytes()).hexdigest()
    elif args.caption=='native':
        for cue in project.cues: cue.style_id=''
    save_project(project,out/'fixture.2byteproj')
    provenance['media_duration_ms']=project.media.duration_ms
    provenance['media_video_metadata']=[a.video_metadata for a in project.media_pool]
    provenance['requested_rate']=1.0
    provenance['actual_active_subtitle_tracks']=len({cue.speaker_id for cue in project.cues})
    (out/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf8')
    os.environ['TWOBYTEASR_TAIL_SECONDS']=str(seconds)
    os.environ['TWOBYTEASR_BOUNDARY_COUNT']=str(count)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')]
    with (out/'process.log').open('w',encoding='utf8') as log:
        process=run_hidden_subprocess(command,cwd=root,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,
            timeout=seconds+110,purpose='Isolated normal-entry playback paint-tail audit')
    result=json.loads((out/'result.json').read_text('utf8'))
    print(json.dumps({k: result.get(k) for k in ('passed','error','configuration','checks','boundary_paint_intervals','ordinary_paint_intervals','moving_paint_intervals','heartbeat')},ensure_ascii=False))
    return process.returncode or (0 if result.get('passed') else 1)


if __name__=='__main__': raise SystemExit(main())
