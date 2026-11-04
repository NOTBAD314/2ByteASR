"""Compact, actual boundary/hold evidence for long and short authored cues.

These contact sheets supplement continuous playback; they are not an animation
quality score. Every cell uses the same crop and the production seek clock.
"""
import io
from pathlib import Path


def capture_motion_review(service, theme, text, folder, *, cancel_check=lambda: False):
    from PIL import Image, ImageDraw
    from .web_theme import theme_archive_html
    import hashlib
    folder = Path(folder)
    spec = theme.get('motionSpec', {})
    groups = {key: [] for key in ('motion_entry', 'motion_hold', 'motion_exit')}
    bounds = []
    samples = []
    for duration in (6000, 1500):
        build = min(float(spec.get('buildMs', 800)), duration * .20)
        resolve = min(float(spec.get('resolveMs', 500)), duration * .15)
        if spec.get('version')==2 and duration<1600:
            build=min(build,160);resolve=min(resolve,100)
        times = {
            'motion_entry': [0, build * .2, build * .5, build * .8, build],
            'motion_hold': [build + (duration - resolve - build) * n for n in (.05, .25, .5, .75, .95)],
            'motion_exit': [duration - resolve, duration - resolve * .65,
                            duration - resolve * .3, duration - resolve * .06, duration],
        }
        service.live_set(theme_archive_html(theme, sample_text=text,
                         duration_seconds=duration / 1000, auto_replay=False), width=1920, height=1080)
        for label, stamps in times.items():
            for ms in stamps:
                if cancel_check():
                    raise InterruptedError('动效关键帧检查已取消')
                bitmap = Image.open(io.BytesIO(service.live_pause(cue_ms=ms, stage_ms=ms))).convert('RGBA')
                bbox = bitmap.getchannel('A').getbbox()
                if bbox:
                    bounds.append(bbox)
                groups[label].append((duration, ms, bitmap))
                samples.append(dict(label=label, duration_ms=duration, milliseconds=ms,
                                    pixel_sha256=hashlib.sha256(bitmap.tobytes()).hexdigest(),
                                    alpha_pixels=sum(bitmap.getchannel('A').histogram()[1:]),
                                    subject_bbox=list(bbox) if bbox else None))
    crop = (max(0, min(b[0] for b in bounds) - 24), max(0, min(b[1] for b in bounds) - 24),
            min(1920, max(b[2] for b in bounds) + 24), min(1080, max(b[3] for b in bounds) + 24)) if bounds else (0, 0, 1920, 1080)
    paths = []
    for label, rows in groups.items():
        sheet = Image.new('RGB', (1920, 512), '#252b29')
        draw = ImageDraw.Draw(sheet)
        for index, (duration, ms, bitmap) in enumerate(rows):
            image = bitmap.crop(crop)
            image.thumbnail((384, 224))
            x, y = (index % 5) * 384, (index // 5) * 256
            sheet.paste(image, (x + (384 - image.width) // 2, y + 28), image)
            draw.text((x + 8, y + 8), f'{duration / 1000:g}s cue | {ms / 1000:.3f}s', fill='white')
        path = folder / (label + '.png')
        sheet.save(path)
        paths.append(path)
    observations=[]
    for duration in (6000,1500):
        entry=[r for r in samples if r['duration_ms']==duration and r['label']=='motion_entry']
        leave=[r for r in samples if r['duration_ms']==duration and r['label']=='motion_exit']
        hold=[r for r in samples if r['duration_ms']==duration and r['label']=='motion_hold']
        def distinct(rows):return len({r['pixel_sha256'] for r in rows if r['alpha_pixels']})
        observations.append(dict(duration_ms=duration,start_clear=entry[0]['alpha_pixels']==0,
            entry_distinct_visible_frames=distinct(entry),exit_distinct_visible_frames=distinct(leave),
            end_clear=leave[-1]['alpha_pixels']==0,hold_visible=all(r['alpha_pixels'] for r in hold),
            warning='检查正常速度动画：少于三个可见变化帧可能是闪现/闪没' if min(distinct(entry),distinct(leave))<3 else '',
            aesthetic_approval=False))
    return paths, dict(crop=list(crop), same_scale=True, samples=samples,observations=observations,
                       note='Discrete real frames; inspect normal-speed movies for rhythm, not these sheets alone.')
