"""Render each effect's two gradients through both production browser components."""
from pathlib import Path
import argparse
import json
import os
import copy


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('fresh source/tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from ..test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtCore import QByteArray
    app=QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFontFromData(QByteArray((root/'assets/fonts/SourceHanSansSC-Heavy.otf').read_bytes()))
    from ..projects.studio_project import SubtitleProject,SubtitleStyle,StudioCue,StudioMedia
    from ..caption_style.style_recipe import StyleRecipe
    from ..caption_style.effect_paints import apply_paint_command,TARGETS
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..caption_design.visual_design_graph import graph_from_style_recipe
    from ..rendering.advanced_renderer import normalized_visual_snapshot
    from ..rendering.renderer_service import RendererService,RendererJob
    from PIL import Image
    import numpy as np
    jobs=[];labels=[]
    for graph in (False,True):
        for target in ('fill', *TARGETS):
            for kind in ('linear-gradient','radial-gradient'):
                style=SubtitleStyle('paint','Browser paint',font_family='Source Han Sans SC Heavy',font_weight=900,font_size=90,
                    primary_color='#00000000' if target in ('background','shadow','glow') else '#FFFFFFFF',
                    outline_width=5 if target=='outline' else 0,outline2_width=12 if target=='outline2' else 0,
                    outline2_color='#FF000000',shadow=12 if target=='shadow' else 0,
                    border_style=3 if target=='background' else 1,back_color='#FF000000',position_x=320,position_y=180,alignment=5)
                recipe=StyleRecipe('Browser paint',engine='remotion',colors={'fill':style.primary_color},
                    outline={'shadow':{'enabled':target=='shadow','color':'#FF000000','offset_x':12,'offset_y':12,'opacity':1,'blur_radius':3}},
                    effects={'glow':{'enabled':target=='glow','color':'#FFFFFFFF','radius':14,'opacity':1}},
                    background={'enabled':target=='background','color':style.back_color,'padding':24})
                p=SubtitleProject(StudioMedia('',duration_ms=2000,width=640,height=360),styles=[style],
                    cues=[StudioCue('c',0,2000,'渐变 TEST',style_id='paint')],style_recipes={'paint':recipe.to_dict()},
                    render_settings={'play_res_x':640,'play_res_y':360})
                p.validate()
                paint=dict(type=kind,angle=0,radius=1,stops=[dict(color='#FFFF0000',position=0),dict(color='#800000FF',position=1)])
                if target=='fill':p.style_recipes['paint']['colors']['fill']=paint
                else:apply_paint_command(p,['c'],target,paint).redo()
                snap=build_visual_cue_snapshot(p,'c')
                if graph:
                    payload=copy.deepcopy(snap.style_recipe);payload['visualGraph']=graph_from_style_recipe(payload).to_dict()
                    from dataclasses import replace
                    snap=replace(snap,style_recipe=payload)
                visual=normalized_visual_snapshot(snap)
                props=dict(schemaVersion=1,width=640,height=360,fps=24,durationInFrames=48,
                    cues=[dict(id='c',text=snap.text,startMs=0,endMs=2000,styleId='paint',visual=visual)],recipes={'paint':visual})
                label=('graph' if graph else 'trusted')+'-'+target+'-'+kind
                jobs.append(RendererJob(str(out/(label+'.png')),props,12,job_kind='diagnostic'))
                labels.append(label)
    service=RendererService(root/'renderer')
    result=dict(passed=False,checks=[],outputs=labels)
    try:
        rendered=service.submit(jobs,timeout=240,batch_group='effect-paint-pixels').result(250)
        for job,label in zip(jobs,labels):
            rendered.require_job(job)
            pixels=np.array(Image.open(job.output).convert('RGBA')).astype(np.int16)
            red=(pixels[:,:,0]>pixels[:,:,1]*1.2+20)&(pixels[:,:,0]>pixels[:,:,2]*1.2+20)&(pixels[:,:,3]>30)
            blue=(pixels[:,:,2]>pixels[:,:,1]*1.2+20)&(pixels[:,:,2]>pixels[:,:,0]*1.2+20)&(pixels[:,:,3]>30)
            row=dict(name=label,red=int(red.sum()),blue=int(blue.sum()),passed=bool(red.sum()>10 and blue.sum()>10))
            result['checks'].append(row)
        result['passed']=all(row['passed'] for row in result['checks'])
    except Exception:
        import traceback
        result['error']=traceback.format_exc()
    finally:
        service.shutdown()
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checked=len(result['checks']),failed=[r for r in result['checks'] if not r['passed']],error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
