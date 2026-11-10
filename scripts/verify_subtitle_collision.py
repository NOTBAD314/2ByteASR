"""Synthetic source-only collision audit; all files/config remain under tmp."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pixels(output, baseline=False):
    if baseline:
        import importlib.util
        for relative in ['caption_style/style_resolution', 'caption_style/subtitle_stacking',
                         'rendering/advanced_live_renderer', 'rendering/caption_scene', 'rendering/ass_compiler']:
            name = 'twobyteasr.'+relative.replace('/', '.')
            path = ROOT/'tmp/subtitle-collision-20261110/before/twobyteasr'/f'{relative}.py'
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor
    from twobyteasr.app.ui import _register_bundled_fonts
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, SubtitleStyle, save_project
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    from twobyteasr.caption_style.subtitle_stacking import initialize_project_layout
    from twobyteasr.caption_style.collision_layout import solve_layout, shifted_snapshot
    from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
    from twobyteasr.studio.selection_geometry import image_bounds
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.rendering.advanced_renderer import _ffmpeg_filter_path
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    p = SubtitleProject(media=StudioMedia('missing.mp4', duration_ms=6000),
        speakers=[StudioSpeaker('S0'), StudioSpeaker('S1')],
        styles=[SubtitleStyle('default','Default',font_size=135,outline_width=4,shadow=0,margin_v=65)],
        cues=[StudioCue('lower',0,4000,'那再刷一下吧',speaker_id='S0'),
              StudioCue('upper',100,5000,'那就再刷一下吧',speaker_id='S1',
                  appearance_override={'font_size':155,'outline_width':32,'outline_color':'#FFFF7900'})])
    # Both runs allocate independently from the same authored input. The before
    # run also retains the legacy saved project as the migration/reopen input.
    initialize_project_layout(p)
    save_project(p, output/'fixture.2byteproj')
    ss = [build_visual_cue_snapshot(p,c.id) for c in p.cues]
    layout = solve_layout(ss) if not baseline else None
    boxes = {}
    def capture(items, name, raw=False):
        canvas = QImage(1920,1080,QImage.Format_ARGB32_Premultiplied)
        canvas.fill(QColor('#334155'))
        painter = QPainter(canvas)
        for s in items:
            offset = 0 if baseline or raw else solve_layout(items).offsets.get(s.cue_id,0.)
            image = render_live_snapshot(shifted_snapshot(s,offset),width=1920,height=1080)
            boxes[name+':'+s.cue_id] = image_bounds(image)
            painter.drawImage(0,0,image)
        painter.end()
        canvas.save(str(output/f'{name}.png'))
    capture(ss,'01-two')
    capture([ss[1]],'02-delete-lower')
    capture([ss[0]],'03-delete-upper')
    p.cues = p.cues[1:]
    capture([build_visual_cue_snapshot(p,'upper')],'04-real-deleted')
    # Produce native ASS and real H.264 burn-in before and after the peer ends.
    from twobyteasr.projects.studio_project import load_project
    p = load_project(output/'fixture.2byteproj')
    ass = output/'captions.ass'
    ass.write_text(compile_ass(p),encoding='utf-8-sig')
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    vf = f'ass=filename={_ffmpeg_filter_path(ass)}:fontsdir={_ffmpeg_filter_path(ROOT/"assets/fonts")}'
    video = output/'burned.mp4'
    result=run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',
        'color=c=0x334155:s=1920x1080:r=10:d=5.5','-vf',vf,'-c:v','libx264','-preset','ultrafast',str(video)],capture_output=True,timeout=60,purpose='collision real burn-in audit')
    if result.returncode:raise RuntimeError(result.stderr.decode('utf8',errors='replace'))
    for at in (1.,4.5):
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss',str(at),'-i',str(video),'-frames:v','1',str(output/f'export-{at}.png')],check=True,capture_output=True,timeout=20,purpose='collision decoded frame audit')
    # Measure the actual libass alpha separately for each cue, retaining all
    # peers as the common layout context. No coordinates-only acceptance.
    exports={}
    for c in p.cues:
        one=output/f'{c.id}.ass';one.write_text(compile_ass(p,cues=[c]),encoding='utf-8-sig')
        for at in (1.,4.5):
            af=f'ass=filename={_ffmpeg_filter_path(one)}:fontsdir={_ffmpeg_filter_path(ROOT/"assets/fonts")}:alpha=1'
            image=output/f'alpha-{c.id}-{at}.png'
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',
                'color=c=black@0:s=1920x1080:r=10:d=5.5,format=rgba','-vf',af,
                '-ss',str(at),'-frames:v','1',str(image)],check=True,capture_output=True,timeout=20,purpose='collision libass alpha audit')
            exports[f'{c.id}:{at}']=image_bounds(QImage(str(image)))
    lower,upper=boxes['01-two:lower'],boxes['01-two:upper']
    result=dict(baseline=baseline,preview_gap=lower[1]-(upper[1]+upper[3]),boxes=boxes,export_boxes=exports,
        export_gap=exports['lower:1.0'][1]-sum(exports['upper:1.0'][1::2]),
        recovered=boxes['02-delete-lower:upper'][1]>boxes['01-two:upper'][1],
        offset=layout.offsets if layout else None)
    (output/'pixels.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--window',action='store_true')
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):parser.error('output must be under tmp')
    if args.window and not args.child:
        output.mkdir(parents=True,exist_ok=False)
        from isolated_windows_desktop import run_on_desktop
        env=os.environ.copy()
        env.update(QT_QPA_PLATFORM='windows',TWOBYTEASR_TEST_ROOT=str(output/'profile'),
            TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        code=run_on_desktop([sys.executable,'-X','utf8',str(Path(__file__).resolve()),
            '--window','--child','--output',str(output)],cwd=ROOT,env=env,output=output/'process',timeout=200)
        (output/'exit.json').write_text(json.dumps({'exit_code':code}),'utf8')
        return code
    output.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    if args.window:
        from twobyteasr.acceptance.collision_layout_audit import run
        return run(output)
    pixels(output,args.baseline)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
