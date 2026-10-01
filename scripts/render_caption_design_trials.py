"""Chromium screenshots and deterministic static caption validation."""
import argparse,base64,json,os,sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--game',type=Path,required=True)
    args=parser.parse_args();directory=args.directory.resolve()
    if not directory.is_relative_to(root/'tmp') and not directory.is_relative_to(root/'examples'):raise ValueError('workspace artifact directory required')
    os.environ.update(LOCALAPPDATA=str(root/'tmp/caption-runtime-trials/static-render/local'),APPDATA=str(root/'tmp/caption-runtime-trials/static-render/roaming'))
    from twobyteasr.caption_design_trials import compile_static_candidate,design_style_checks
    from twobyteasr.renderer_service import RendererService
    from PIL import Image
    service=RendererService();rows=[]
    try:
        for spec_path in directory.glob('*/spec.json'):
            folder=spec_path.parent;spec=json.loads(spec_path.read_text('utf8'))
            row={'id':folder.name,'name':spec['name'],'spec_path':str(spec_path),'checks':design_style_checks(spec)}
            for variant,background in [('game',args.game),('transparent',None)]:
                html=compile_static_candidate(spec,'啊感觉他就是你看',background_path=background)
                (folder/(variant+'.html')).write_text(html,encoding='utf8')
                service.live_set(html,width=1920,height=1080)
                (folder/(variant+'.png')).write_bytes(service.live_pause(cue_ms=1000,stage_ms=1000))
                diag=service._live_request({'type':'live_caption_review'},timeout=10)
                metrics=diag['metrics'];row['metrics']=metrics
                if variant=='game':(folder/'detail-1to1.png').write_bytes(base64.b64decode(diag['detail_png_base64']))
                row['checks'].update(font_loaded=metrics['fontLoaded'],single_line=metrics['lineCount']==1,
                    unique_semantic_text=metrics['semanticCount']==1,no_script_errors=not diag['script_errors'])
                text_rect=metrics['rects'][-1]
                row['checks']['text_in_safe_zone']=text_rect[0]>=96 and text_rect[1]>=810 and text_rect[0]+text_rect[2]<=1824 and text_rect[1]+text_rect[3]<=1026
                if variant=='transparent':
                    im=Image.open(folder/'transparent.png').convert('RGBA');alpha=im.getchannel('A');bbox=alpha.getbbox()
                    # Shadows may feather to the outer safety boundary. Ignore
                    # alpha <=8 instead of counting near-invisible blur tails.
                    visible=alpha.point(lambda value:255 if value>8 else 0).getbbox()
                    row['alpha_bbox']=bbox;row['visible_bbox']=visible
                    row['checks']['transparent_outside_caption']=bool(visible and visible[0]>=96 and visible[1]>=810 and visible[2]<=1824 and visible[3]<=1026)
                    row['checks']['visible_pixels']=bool(visible)
            row['passed']=all(value for value in row['checks'].values() if isinstance(value,bool))
            (folder/'browser-checks.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf8')
            rows.append(row);print(json.dumps({'id':folder.name,'passed':row['passed'],'checks':row['checks']},ensure_ascii=False),flush=True)
    finally:service.shutdown()
    (directory/'browser-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if rows and all(row['passed'] for row in rows) else 1


if __name__=='__main__':raise SystemExit(main())
