"""Offline archive/import/production parity for user-approved complete themes."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from twobyteasr.web_theme import import_theme_archive,theme_archive_html
    from twobyteasr.theme_draft import canonical_theme
    from twobyteasr.renderer_service import RendererService,RendererJob
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.studio_project import load_project
    from twobyteasr.advanced_renderer import compile_composition_data
    from PIL import Image
    import numpy as np
    sha=lambda value:hashlib.sha256(value).hexdigest()
    service=RendererService();results=[]
    try:
        for ident in 'ABC':
            source=args.reference/ident;target=out/ident;target.mkdir(exist_ok=True)
            original=(source/'theme.html').read_text('utf8');theme=import_theme_archive(source/'theme.html')
            original_theme=json.loads((source/'theme.json').read_text('utf8'))
            row=dict(id=ident,theme_id=theme['id'],source_hash=sha(canonical_theme(theme).encode()),
                archive_hash=sha((source/'theme.html').read_bytes()),json_hash=sha((source/'theme.json').read_bytes()),
                imported_json_equal=canonical_theme(theme)==canonical_theme(import_theme_archive(source/'theme.json')),
                fields_unchanged={k:theme.get(k)==original_theme.get(k) for k in ('cueHtml','cueCss','stageHtml','stageCss','motionSpec','assets','appearance')},
                frames=[],adaptation=[])
            for route,html in [('archive',original),('imported',theme_archive_html(theme,sample_text='这次终于找到出口了',duration_seconds=6,auto_replay=False))]:
                service.live_set(html,width=1920,height=1080)
                for ms in (150,750,1500,3000,5400,5850):
                    path=target/f'{route}-{ms}.png';path.write_bytes(service.live_pause(cue_ms=ms,stage_ms=ms))
                    if ms==1500:row[route+'_diagnostics']=service._live_request({'type':'live_diagnostics','selectors':['.wt-placement','.wt-cue','[data-caption-text]']},timeout=5)
            project_folder=out.parent/('import-A-02' if ident=='A' else 'import-'+ident)
            project=load_project(project_folder/'fixture.2byteproj')
            props=compile_composition_data(project,width=1920,height=1080,fps=30,start_seconds=.25,duration_seconds=6)
            stamps=(150,750,1500,3000,5400,5850)
            # Half-frame stamps are sampled at the same rounded frame by both routes below.
            frames=[round(ms*30/1000) for ms in stamps]
            service.render([RendererJob(str(target/f'production-{frame}.png'),props,frame,job_kind='production') for frame in frames],timeout=120)
            for ms,frame in zip(stamps,frames):
                a=np.array(Image.open(target/f'archive-{ms}.png').convert('RGBA')).astype(float)
                b=np.array(Image.open(target/f'imported-{ms}.png').convert('RGBA')).astype(float)
                row['frames'].append(dict(time_ms=ms,archive_imported_mae=float(abs(a-b).mean()),identical=bool(np.array_equal(a,b))))
                service.live_set(theme_archive_html(theme,sample_text='这次终于找到出口了',duration_seconds=6,auto_replay=False),width=1920,height=1080)
                from io import BytesIO
                a=np.array(Image.open(BytesIO(service.live_pause(cue_ms=frame/30*1000,stage_ms=frame/30*1000))).convert('RGBA')).astype(float)
                b=np.array(Image.open(target/f'production-{frame}.png').convert('RGBA')).astype(float)
                for v in (a,b):v[:,:,:3]*=v[:,:,3:]/255
                mask=np.maximum(a[:,:,3],b[:,:,3])>8
                row['frames'][-1]['live_production_visible_mae']=float(abs(a-b)[mask].mean()) if mask.any() else 0
            for text in ('为什么他觉得我要移花子了','为什么他觉得我要移花子了，明明这次我只是想穿过前面的传送门继续寻找出口'):
                service.live_text(text=text,speaker='',duration_ms=6000)
                path=target/f'adapted-{len(row["adaptation"])}.png';path.write_bytes(service.live_pause(cue_ms=1500,stage_ms=1500))
                row['adaptation'].append(dict(text=text,path=str(path),diagnostics=service._live_request({'type':'live_diagnostics','selectors':['.wt-cue','[data-caption-text]']},timeout=5)))
            row['passed']=row['imported_json_equal'] and all(row['fields_unchanged'].values()) and all(f['identical'] and f['live_production_visible_mae']<2 for f in row['frames'])
            results.append(row);(out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
            print(json.dumps(dict(id=ident,passed=row['passed'],frames=row['frames']),ensure_ascii=False),flush=True)
    finally:service.shutdown()
    return 0 if all(r['passed'] for r in results) else 1

if __name__=='__main__':raise SystemExit(main())
