"""Prepare one continuous 1080p60 source pair for equal-duration 1x/2x/4x runs.

Preparation only: this does not launch a GUI or claim performance. The runner
consumes the generated cases.json, retaining every repetition and failed run.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_project(media, duration, layers):
    from twobyteasr.projects.studio_project import (
        MediaAsset, StudioCue, StudioMedia, SubtitleProject, VideoClip, VideoTrack, VideoTransform)
    project = SubtitleProject(media=StudioMedia(path=str(media[0]), duration_ms=duration*1000,
                                               width=1920, height=1080))
    for index, path in enumerate(media[:layers], 1):
        asset = MediaAsset(asset_id=f'cadence-asset-{index}', canonical_source=str(path),
            duration_ms=duration*1000, video_metadata={'width':1920,'height':1080,'fps':60},
            audio_metadata={'sample_rate':48000,'channels':2})
        transform = VideoTransform() if index == 1 else VideoTransform(
            position_x=.72, position_y=.3, scale_x=.45, scale_y=.45)
        clip = VideoClip(id=f'cadence-clip-{index}', asset_id=asset.asset_id,
            source_out_ms=duration*1000, timeline_out_ms=duration*1000, transform=transform)
        project.media_pool.append(asset)
        project.video_tracks.append(VideoTrack(id=f'V{index}',name=f'V{index}',clips=[clip],z_index=index-1))
    project.cues = [StudioCue(f'cadence-cue-{i}', i*2000, i*2000+1800,
        f'第 {i+1} 条字幕：同条件播放与图层边界检查') for i in range(duration//2)]
    project.validate()
    return project


def matrix_cases(*, seconds=65, repeat=3, start=5, settle=5, zoom=110):
    cases = []
    for layers in (1, 2):
        for rate in (1, 2, 4):
            cases.append({'id':f'layers-{layers}-rate-{rate}', 'project':f'layers-{layers}.2byteproj',
                'seconds':seconds,'repeat':repeat,'start':start,'settle':settle,'rate':rate,
                'zoom':zoom,'follow':True,'barcode_y':710,'frame_code_period':4096,
                'regions':['v2,.495,.075,.45,.45,710'] if layers == 2 else []})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=65)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('choose a NEW directory under this checkout/tmp')
    if not 16 <= args.seconds <= 180 or not 1 <= args.repeat <= 10:
        parser.error('seconds 16..180; repeat 1..10')
    out.mkdir(parents=True)
    # Fixture preparation must not register projects or write process logs in
    # the user's normal profile, even when called directly from a terminal.
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    duration = math.ceil(5 + args.seconds*4 + 2)
    from verify_visible_playback import make_media
    folder = make_media(ROOT, out/'media', duration=duration, with_loop=False)
    media = [folder/f'V{index}-{duration}s.mp4' for index in (1,2)]
    receipts = []
    for path in media:
        result = subprocess.check_output([str(ROOT/'tools/ffmpeg/bin/ffprobe.exe'),'-v','error',
            '-show_streams','-show_format','-of','json',str(path)],
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        metadata = json.loads(result)
        video = next(row for row in metadata['streams'] if row['codec_type']=='video')
        if (video['width'],video['height'],video['avg_frame_rate']) != (1920,1080,'60/1'):
            raise ValueError('generated source is not the declared 1080p60 fixture')
        if float(metadata['format']['duration']) < duration-.05:
            raise ValueError('generated source is too short for the shared 4x window')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        receipts.append({'path':str(path),'sha256':digest.hexdigest(),
                         'ffprobe':metadata})
    from twobyteasr.projects.studio_project import save_project
    for count in (1,2):
        save_project(build_project(media,duration,count),out/f'layers-{count}.2byteproj')
    (out/'cases.json').write_text(json.dumps({'cases':matrix_cases(seconds=args.seconds,repeat=args.repeat)},
        ensure_ascii=False,indent=2),encoding='utf8')
    (out/'inputs.json').write_text(json.dumps({'sources':receipts,'generated_duration_seconds':duration,
        'quality':'1920x1080 CFR60; libx264 CRF18; identical continuous sources for every rate',
        'audio':'48kHz stereo silence; PCM transport remains enabled',
        'measurement_status':'NOT_RUN'},ensure_ascii=False,indent=2),encoding='utf8')
    print(out/'cases.json')


if __name__ == '__main__':
    main()
