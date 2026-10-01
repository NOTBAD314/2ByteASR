"""Bounded real HTML output: full decorations, rotation, shadows, overlap."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--theme', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():
        raise ValueError('New workspace/tmp directory required')
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out), QT_QPA_PLATFORM='offscreen')
    sys.path.insert(0,str(root))
    from twobyteasr.studio_project import SubtitleProject
    from twobyteasr.export_timeline import export_project_snapshot
    from twobyteasr.theme_visual_bounds import calibrate_theme_bounds
    from twobyteasr.subtitle_stacking import project_stack_layout
    from twobyteasr.frame_export import save_project_frame
    from twobyteasr.video_export import capture_video_graph
    from twobyteasr.renderer_service import GLOBAL_RENDERER_SERVICE, RendererJob
    from twobyteasr.advanced_renderer import compile_composition_data
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QImage
    app=QApplication([])
    for path in (root/'assets/fonts').glob('*.otf'):
        QFontDatabase.addApplicationFont(str(path))
    p=SubtitleProject.from_dict(json.loads(args.project.read_text(encoding='utf-8-sig')))
    first=deepcopy(p.cues[0]);first.id='bounds-a';first.start_ms=4000;first.end_ms=5500
    first.transform={'web_placement':dict(x=.5,y=.69,originX=.5,originY=.5,scaleX=.47,scaleY=.47,rotation=9)}
    second=deepcopy(first);second.id='bounds-b';second.style_id='cover-bounds-second';second.text='重叠主题也保留完整装饰'
    second.transform['web_placement']['rotation']=-7
    recipe=deepcopy(p.style_recipes[first.style_id])
    recipe['webTheme']=json.loads(args.theme.read_text(encoding='utf-8-sig'))
    p.style_recipes[second.style_id]=recipe
    second_style=deepcopy(next(style for style in p.styles if style.id==first.style_id))
    second_style.id=second.style_id;p.styles.append(second_style)
    p.cues=[first,second]
    p.studio_state['auto_subtitle_stacking']=True
    p.validate()
    snapshot=export_project_snapshot(p)
    before=project_stack_layout(snapshot)
    report=dict(before={'offsets':before.offsets,'warnings':before.warnings})
    try:
        measured,receipt=calibrate_theme_bounds(snapshot,output=out/'measurements.json',progress=lambda line:print(line,flush=True))
        snapshot.studio_state['theme_visual_bounds']=measured;snapshot._stack_layout_cache=None
        after=project_stack_layout(snapshot)
        report.update(after={'offsets':after.offsets,'warnings':after.warnings},measurement=receipt)
        if not measured or not after.offsets:raise AssertionError('Measured envelopes did not move an overlapping theme')
        graph=capture_video_graph(p)
        report['frames']=[]
        for ms in (4100,4450,4750,5200,5466):
            receipt=save_project_frame(snapshot,graph,ms,out,'完整装饰',subtitles=True,ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe')
            report['frames'].append(receipt)
        props=compile_composition_data(snapshot,width=1920,height=1080,fps=30,start_seconds=0,duration_seconds=9)
        job=RendererJob(str(out/'overlay.png'),props,round(4.75*30))
        GLOBAL_RENDERER_SERVICE.render([job],render_type='still',resolution=(1920,1080),timeout=90).require_job(job)
        report['passed']=all(QImage(r['path']).width()==graph['width'] for r in report['frames']) and not after.warnings
        (out/'fixture.2byteproj').write_text(json.dumps(snapshot.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        GLOBAL_RENDERER_SERVICE.shutdown()
    print(json.dumps({'passed':report.get('passed',False),'after':report.get('after')},ensure_ascii=False))
    return 0 if report.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
