"""Author review fixtures for the curated motion catalog (2026-10-17).

Contact sheets, LIVE-vs-libass and LIVE-vs-Remotion frame comparisons, and a
labelled gallery video. Run through ``scripts/verify_motion_catalog.py``,
which owns data isolation. Pictures are evidence for a human looking at
them, not pixel assertions.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
FPS = 30
CUE = 2000
W, H = 960, 540
CASES = [('entry', 'push_in', .25), ('entry', 'whip_in', .2), ('entry', 'doors_in', .2), ('entry', 'shine_in', .55),
         ('entry', 'glitch_in', .3), ('entry', 'char_flip', .45), ('entry', 'typewriter', .55), ('entry', 'wipe_in', .45),
         ('entry', 'flash_in', .2), ('entry', 'slice_in', .3), ('exit', 'zoom_blur_out', .4), ('exit', 'shatter_out', .45),
         ('loop', 'loop_shine', .35), ('loop', 'loop_wave', .5), ('words', 'word_current_pop', .5)]


def contact_sheets(out, *args):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    stages = args[0].split(',') if args else ['entry', 'exit', 'loop', 'words']
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    from PySide6.QtCore import QPointF
    app = QApplication.instance() or QApplication([])
    from dataclasses import replace
    from .studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
    from .effect_dsl import validate_effect
    from .visual_snapshot import build_visual_cue_snapshot
    from .caption_scene import SceneRasterizer
    from .motion_catalog import ENTRY, EXIT, LOOP, spec
    from .motion_inspector_ui import CHOICES
    text = '这波操作 Nice'
    duration = 4000
    cols, cw, ch = 9, 250, 104

    def project(effect):
        p = SubtitleProject(media=StudioMedia(path='sheet', duration_ms=duration),
            styles=[SubtitleStyle('default', 's', font_family='Microsoft YaHei', font_size=80, primary_color='#FFFFFFFF',
                                  outline_width=2.5, outline_color='#FF101010', shadow=0)],
            cues=[StudioCue('c', 0, duration, text, effect_id='e', evidence_refs=['c'])],
            asr_evidence={'c': {'words': [dict(text=t, start_ms=300+i*260, end_ms=520+i*260)
                                          for i, t in enumerate(text.replace(' ', ''))]}})
        p.effects['e'] = validate_effect(effect)
        return p

    for stage in stages:
        if stage == 'words':
            items = [(k, label) for k, label in CHOICES['words']]
        else:
            items = [(m.key, m.label) for m in {'entry': ENTRY, 'exit': EXIT, 'loop': LOOP}[stage]]
        sheet = QImage(150+cols*cw, 30+len(items)*ch, QImage.Format_RGB32)
        sheet.fill(QColor('#0E141C'))
        painter = QPainter(sheet)
        font = QFont('Microsoft YaHei'); font.setPixelSize(15); painter.setFont(font)
        for row, (key, label) in enumerate(items):
            effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
            if stage == 'loop':
                effect['loop'] = {'type': key}
            elif stage == 'words':
                effect['word_highlight'] = {'type': key}
            else:
                effect[stage] = {'type': key}
            p = project(effect)
            snap = build_visual_cue_snapshot(p, 'c')
            snap = replace(snap, position_x=cw/2, position_y=ch/2, playres_x=cw, playres_y=ch, font_size=30,
                           anchor_x=.5, anchor_y=.5, alignment=5, resolved_caption=None,
                           strokes=tuple({**s, 'width': 1.2} for s in snap.strokes))
            prepared = SimpleNamespace(snapshot=snap, snapshot_hash=snap.stable_hash())
            raster = SceneRasterizer()
            m = spec(stage, key) if stage != 'words' else None
            length = p.effects['e'].get(stage, {}).get('duration', 400) if stage in ('entry', 'exit') else 0
            if stage == 'entry':
                times = [length*j/(cols-2) for j in range(cols-1)]+[duration*.5]
            elif stage == 'exit':
                times = [duration*.5]+[duration-length+length*j/(cols-2) for j in range(cols-1)]
                times[-1] = duration-1
            elif stage == 'loop':
                period = p.effects['e']['loop'].get('duration', 1200)
                times = [600+period*j/(cols-1) for j in range(cols)]
            else:
                times = [200+260*j*.9 for j in range(cols)]
            y = 30+row*ch
            painter.setPen(QColor('#E8EEF5'))
            painter.drawText(10, y+ch//2+6, f'{label}')
            painter.setPen(QColor('#6B7A8C'))
            painter.drawText(10, y+ch//2+26, key[:16])
            for col, t in enumerate(times):
                image = raster.native_frame(prepared, min(duration-1, t), cw-6, ch-6)
                x = 150+col*cw
                painter.fillRect(x+2, y+2, cw-4, ch-4, QColor('#1B2533'))
                painter.drawImage(QPointF(x+3, y+3), image)
                if row == 0:
                    painter.setPen(QColor('#6B7A8C'))
                    painter.drawText(x+6, 20, f'{t:.0f} ms')
            raster.close()
        painter.end()
        sheet.save(str(out/f'{stage}.png'))
        print(stage, len(items), out/f'{stage}.png')


def ass_comparison(out, *args):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    keys = (args[0] if args else 'push_in,whip_in,doors_in,shine_in,glitch_in,typewriter').split(',')
    fractions = [float(v) for v in (args[1] if len(args) > 1 else '.15,.35,.6').split(',')]
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    from PySide6.QtCore import QPointF
    app = QApplication.instance() or QApplication([])
    from .studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
    from .effect_dsl import validate_effect
    from .visual_snapshot import build_visual_cue_snapshot
    from .motion_catalog import spec
    from .caption_scene import SceneRasterizer
    from .ass_compiler import compile_ass
    W, H = 960, 270
    CUE = 2400
    text = '这波操作 Nice'
    cues, effects, plan = [], {}, []
    for i, key in enumerate(keys):
        stage = 'entry' if spec('entry', key) else 'exit' if spec('exit', key) else 'loop'
        effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
        if stage == 'loop':
            effect['loop'] = {'type': key}
        else:
            effect[stage] = {'type': key}
        effect = validate_effect(effect)
        effects[key] = effect
        start = i*CUE
        cues.append(StudioCue(key, start, start+CUE, text, effect_id=key, evidence_refs=[key]))
        length = effect.get(stage, {}).get('duration', 1200)
        for f in fractions:
            rel = (length*f if stage == 'entry' else CUE-length+length*f if stage == 'exit' else 500+length*f)
            plan.append((i, key, rel))
    p = SubtitleProject(media=StudioMedia(path=str(out/'media.mp4'), duration_ms=CUE*len(keys), width=W, height=H),
        styles=[SubtitleStyle('default', 's', font_family='Microsoft YaHei', font_size=72, primary_color='#FFFFFFFF',
                              outline_width=3, outline_color='#FF101010', shadow=0, alignment=5,
                              position_x=W//2, position_y=H//2)],
        cues=cues)
    p.effects.update(effects)
    p.render_settings.update(play_res_x=W, play_res_y=H)
    ass = out/'compare.ass'
    ass.write_text(compile_ass(p), encoding='utf-8-sig')
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    font = QFont('Microsoft YaHei'); font.setPixelSize(16)
    rows = []
    for i, key, rel in plan:
        t = cues[i].start_ms+rel
        target = out/f'ass-{key}-{int(rel)}.png'
        filt = f"ass=filename='{ass.as_posix().replace(':', chr(92)+':')}'"
        subprocess.run([str(ffmpeg), '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f'color=c=0x1B2533:s={W}x{H}:r=50:d={(t+200)/1000:.3f}', '-vf', filt,
                        '-ss', f'{t/1000:.3f}', '-frames:v', '1', str(target)], check=True)
        snap = build_visual_cue_snapshot(p, key)
        live = SceneRasterizer().native_frame(SimpleNamespace(snapshot=snap, snapshot_hash=snap.stable_hash()), rel, W, H)
        rows.append((key, rel, live, QImage(str(target))))
    sheet = QImage(W*2+20, len(rows)*(H+8)+10, QImage.Format_RGB32); sheet.fill(QColor('#0B1016'))
    painter = QPainter(sheet); painter.setFont(font)
    for r, (key, rel, live, burned) in enumerate(rows):
        y = 10+r*(H+8)
        painter.fillRect(0, y, W, H, QColor('#1B2533'))
        painter.drawImage(QPointF(0, y), live)
        painter.drawImage(QPointF(W+20, y), burned)
        painter.setPen(QColor('#9FB0C4'))
        painter.drawText(8, y+20, f'LIVE {key} {rel:.0f}ms')
        painter.drawText(W+28, y+20, f'ASS/libass {key} {rel:.0f}ms')
    painter.end()
    sheet.save(str(out/'compare.png'))
    print(out/'compare.png')


def remotion_comparison(out, *args):
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    from PySide6.QtCore import QPointF
    app = QApplication.instance() or QApplication([])
    from .studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle, save_project
    from .effect_dsl import validate_effect
    from .style_recipe import StyleRecipe
    from .visual_snapshot import build_visual_cue_snapshot
    from .caption_scene import SceneRasterizer
    from .ass_compiler import compile_ass
    from .advanced_renderer import AdvancedRendererBackend
    from .studio_render import RenderJob, RenderSettings
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    media = out/'source.mp4'
    total = CUE*len(CASES)
    if not media.exists():
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f'color=c=0x1B2533:s={W}x{H}:r=30:d={total/1000+1}', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        str(media)], check=True)
    text = '这波操作 Nice'
    cues, effects, evidence, times = [], {}, {}, []
    for i, (stage, key, fraction) in enumerate(CASES):
        effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
        if stage == 'loop':
            effect['loop'] = {'type': key}
        elif stage == 'words':
            effect['word_highlight'] = {'type': key, 'color': '#FFD166'}
        else:
            effect[stage] = {'type': key}
        effect = validate_effect(effect)
        start = i*CUE
        cues.append(StudioCue(key, start, start+CUE, text, effect_id=key, evidence_refs=[key], style_id='grad'))
        evidence[key] = {'words': [dict(text=t, start_ms=start+200+k*170, end_ms=start+340+k*170)
                                   for k, t in enumerate(text.replace(' ', ''))]}
        effects[key] = effect
        length = effect.get(stage, {}).get('duration', 0) if stage in ('entry', 'exit') else 0
        rel = (length*fraction if stage == 'entry' else CUE-length+length*fraction if stage == 'exit'
               else CUE*fraction)
        times.append((key, start, rel))
    style = SubtitleStyle('grad', '渐变', font_family='Microsoft YaHei', font_size=76, primary_color='#FFFFFFFF',
                          outline_width=3, outline_color='#FF101010', shadow=0)
    p = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=total, width=W, height=H),
                        styles=[style], cues=cues, asr_evidence=evidence)
    p.effects.update(effects)
    p.render_settings.update(play_res_x=W, play_res_y=H)
    p.style_recipes['grad'] = StyleRecipe(name='渐变', engine='remotion', colors={
        'fill': {'type': 'linear-gradient', 'angle': 0, 'stops': [{'position': 0, 'color': '#FFFFFFFF'},
                                                                 {'position': 1, 'color': '#FFFFD3A0'}]}}).to_dict()
    save_project(p, out/'remotion.2byteproj')
    ass = out/'mixed.ass'; ass.write_text(compile_ass(p), encoding='utf-8-sig')
    settings = RenderSettings(encoder='libx264', width=W, height=H, fps=30, audio_codec='none')
    target = out/'remotion.mp4'
    if not target.exists():
        job = RenderJob(str(media), str(ass), str(target), settings=settings, start_seconds=0, duration_seconds=total/1000)
        print(AdvancedRendererBackend().render(p, ffmpeg, job), flush=True)
    raster = SceneRasterizer()
    rows = []
    for key, start, rel in times:
        frame = out/f'remotion-{key}.png'
        frame_no = round((start+rel)/1000*30)
        subprocess.run([str(ffmpeg), '-y', '-hide_banner', '-loglevel', 'error', '-i', str(target), '-vf',
                        f'select=eq(n\\,{frame_no})', '-frames:v', '1', str(frame)], check=True)
        snap = build_visual_cue_snapshot(p, key)
        live = raster.native_frame(SimpleNamespace(snapshot=snap, snapshot_hash=snap.stable_hash()), frame_no*1000/30-start, W, H)
        rows.append((key, rel, live, QImage(str(frame))))
    band = 200
    sheet = QImage(W*2+20, len(rows)*(band+6), QImage.Format_RGB32); sheet.fill(QColor('#0B1016'))
    painter = QPainter(sheet); font = QFont('Microsoft YaHei'); font.setPixelSize(15); painter.setFont(font)
    for r, (key, rel, live, burned) in enumerate(rows):
        y = r*(band+6)
        top = H-band-10
        painter.fillRect(0, y, W, band, QColor('#1B2533'))
        painter.drawImage(QPointF(0, y), live, live.rect().adjusted(0, top, 0, -(H-band-top)))
        painter.drawImage(QPointF(W+20, y), burned, burned.rect().adjusted(0, top, 0, -(H-band-top)))
        painter.setPen(QColor('#9FB0C4'))
        painter.drawText(8, y+18, f'LIVE {key} {rel:.0f}ms'); painter.drawText(W+28, y+18, f'Remotion export {key}')
    painter.end(); sheet.save(str(out/'remotion-compare.png'))
    print(out/'remotion-compare.png')


def gallery_video(out, *args):
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor, QFont, QLinearGradient
    from PySide6.QtCore import QPointF, QRectF, Qt
    app = QApplication.instance() or QApplication([])
    from dataclasses import replace
    from .studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
    from .effect_dsl import validate_effect
    from .visual_snapshot import build_visual_cue_snapshot
    from .caption_scene import SceneRasterizer
    from .motion_catalog import ENTRY, EXIT, LOOP
    from .motion_inspector_ui import WORDS, CATEGORIES
    text = '这波操作 Nice'
    W, H = 1920, 1080
    sections = [
        ('入场', 'entry', [(m.key, m.label, m.category) for m in ENTRY if m.key != 'none'], 2600, 5.2),
        ('出场', 'exit', [(m.key, m.label, m.category) for m in EXIT if m.key != 'none'], 2600, 5.2),
        ('循环', 'loop', [(m.key, m.label, m.category) for m in LOOP if m.key != 'none'], 4000, 5.0),
        ('逐词', 'words', [(k, l, c) for k, l, c, _ in WORDS if k != 'none'], 3400, 5.6),
    ]
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    proc = subprocess.Popen([str(ffmpeg), '-y', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo', '-pixel_format',
                             'rgba', '-video_size', f'{W}x{H}', '-framerate', str(FPS), '-i', '-', '-c:v', 'libx264',
                             '-crf', '20', '-pix_fmt', 'yuv420p', str(out/'motion-gallery.mp4')], stdin=subprocess.PIPE)
    title_font = QFont('Microsoft YaHei'); title_font.setPixelSize(30); title_font.setWeight(QFont.DemiBold)
    label_font = QFont('Microsoft YaHei'); label_font.setPixelSize(17)
    small_font = QFont('Microsoft YaHei'); small_font.setPixelSize(13)
    for title, stage, items, duration, seconds in sections:
        cols = 6 if len(items) > 20 else 5 if len(items) > 12 else 4
        rows = (len(items)+cols-1)//cols
        cw, ch = (W-60)//cols, min(190, (H-110)//rows)
        cells = []
        for i, (key, label, category) in enumerate(items):
            effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
            if stage == 'loop':
                effect['loop'] = {'type': key}
            elif stage == 'words':
                effect['word_highlight'] = {'type': key, 'color': '#FFD166' if key not in ('karaoke_wipe',) else '#4D9FFF'}
            else:
                effect[stage] = {'type': key}
            p = SubtitleProject(media=StudioMedia(path='gallery', duration_ms=duration),
                styles=[SubtitleStyle('default', 's', font_family='Microsoft YaHei', font_size=80, primary_color='#FFFFFFFF',
                                      outline_width=2.5, outline_color='#FF0B0F14', shadow=0)],
                cues=[StudioCue('c', 0, duration, text, effect_id='e', evidence_refs=['c'])],
                asr_evidence={'c': {'words': [dict(text=t, start_ms=250+k*300, end_ms=480+k*300)
                                              for k, t in enumerate(text.replace(' ', ''))]}})
            p.effects['e'] = validate_effect(effect)
            snap = build_visual_cue_snapshot(p, 'c')
            snap = replace(snap, position_x=(cw-12)/2, position_y=(ch-40)/2, playres_x=cw-12, playres_y=ch-40,
                           font_size=min(40, (cw-40)/7.2), anchor_x=.5, anchor_y=.5, alignment=5, resolved_caption=None,
                           strokes=tuple({**s, 'width': 1.6} for s in snap.strokes))
            cells.append((label, category, snap, SceneRasterizer()))
        names = dict(CATEGORIES[stage])
        for frame in range(round(seconds*FPS)):
            t = frame/FPS*1000
            local = t % (duration+500)
            image = QImage(W, H, QImage.Format_RGBA8888); image.fill(QColor('#0D1218'))
            painter = QPainter(image); painter.setRenderHint(QPainter.Antialiasing)
            painter.setFont(title_font); painter.setPen(QColor('#F2F5F9'))
            painter.drawText(30, 58, f'{title} · {len(items)} 个')
            painter.setFont(small_font); painter.setPen(QColor('#7D8DA1'))
            painter.drawText(W-560, 58, '2ByteASR 字幕动效 · 实际 LIVE 渲染（与导出共用同一组关键帧）')
            for i, (label, category, snap, raster) in enumerate(cells):
                x = 30+(i % cols)*cw; y = 80+(i//cols)*ch
                rect = QRectF(x+6, y+6, cw-12, ch-12)
                gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                gradient.setColorAt(0, QColor('#25364A')); gradient.setColorAt(1, QColor('#151D29'))
                painter.setPen(Qt.NoPen); painter.setBrush(gradient); painter.drawRoundedRect(rect, 10, 10)
                if local < duration:
                    layer = raster.native_frame(SimpleNamespace(snapshot=snap, snapshot_hash=snap.stable_hash()),
                                                local, cw-12, ch-40)
                    painter.drawImage(QPointF(x+6, y+8), layer)
                painter.setFont(label_font); painter.setPen(QColor('#E9EEF4'))
                painter.drawText(QRectF(x+14, y+ch-40, cw-28, 26), Qt.AlignLeft | Qt.AlignVCenter, label)
                painter.setFont(small_font); painter.setPen(QColor('#8193A8'))
                painter.drawText(QRectF(x+14, y+ch-40, cw-28, 26), Qt.AlignRight | Qt.AlignVCenter, names.get(category, ''))
            painter.end()
            if frame == round(seconds*FPS*.5):
                image.save(str(out/f'gallery-{stage}.png'))
            proc.stdin.write(bytes(image.constBits()))
        for _, _, _, raster in cells:
            raster.close()
        print(stage, len(items), flush=True)
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError('encoding failed')
    print(out/'motion-gallery.mp4')
