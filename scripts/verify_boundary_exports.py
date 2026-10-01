"""Production three-route exports with full streaming decode and pixel identity."""
import argparse,json,os,sys,hashlib
from pathlib import Path
from fractions import Fraction


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('fixture',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('fresh repository tmp required')
    out.mkdir(parents=True);(out/'temp').mkdir()
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen',TEMP=str(out/'temp'),TMP=str(out/'temp'))
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.studio_project import load_project
    from twobyteasr.ass_compiler import compile_ass
    from twobyteasr.studio_render import RenderJob,RenderSettings,run_render_job
    from twobyteasr.advanced_renderer import AdvancedRendererBackend,split_renderer_cues
    import av,numpy as np
    from PIL import Image,ImageDraw
    config=json.loads((args.fixture/'matrix.json').read_text('utf8'));fps=Fraction(config['fps']);reports=[]
    for case in config['cases']:
        project=load_project(args.fixture/(case['id']+'.2byteproj'));folder=out/case['id'];folder.mkdir()
        ass=folder/'captions.ass';ass.write_text(compile_ass(project,frame_rate=fps),'utf8')
        movie=folder/'export.mp4';duration=project.media.duration_ms/1000
        job=RenderJob(project.media.path,str(ass),str(movie),settings=RenderSettings(encoder='libx264',preset='ultrafast',
            width=1280,height=720,fps=float(fps),audio_codec='none'),start_seconds=0,duration_seconds=duration,overwrite_existing=True)
        if split_renderer_cues(project)[1]:AdvancedRendererBackend().render(project,root/'tools/ffmpeg/bin/ffmpeg.exe',job)
        else:run_render_job(root/'tools/ffmpeg/bin/ffmpeg.exe',job)
        refs={};rows=[];thumbs={};boundary=round(float(fps));masks={}
        with av.open(str(movie)) as container:
            for index,frame in enumerate(container.decode(video=0)):
                pts=Fraction(frame.pts)*frame.time_base*1000;pixels=frame.to_ndarray(format='rgb24')
                mask=pixels[round(720*.52):round(720*.98)].min(axis=2)>190
                if index in (round(float(fps)*.5),round(float(fps)*1.5)):refs['A' if index<fps else 'B']=mask.copy()
                if boundary-6<=index<=boundary+6:
                    masks[index]=mask.copy();im=Image.fromarray(pixels);im.thumbnail((420,236));thumbs[index]=im
                cues=[c.id for c in project.cues if c.start_ms<=pts<c.end_ms]
                rows.append(dict(frame=index,pts_ms=float(pts),pts_rational=str(pts),expected_cue_ids=cues,white_glyph_pixels=int(mask.sum())))
        selected=[]
        for row in rows:
            if row['frame'] not in masks:continue
            mask=masks[row['frame']];dist={k:float(np.logical_xor(mask,ref).sum()/max(1,np.logical_or(mask,ref).sum())) for k,ref in refs.items()}
            identity='None' if row['white_glyph_pixels']<100 else min(dist,key=dist.get)
            if identity!='None' and dist[identity]>.4:identity='Unknown'
            row.update(published_pixels_identity=identity,distances=dist)
            row['passed']=identity==('+'.join(row['expected_cue_ids']) or 'None');selected.append(row)
        sheet=Image.new('RGB',(1680,1040),'#181820');draw=ImageDraw.Draw(sheet)
        for i,row in enumerate(selected):
            x=i%4*420;y=i//4*260;sheet.paste(thumbs[row['frame']],(x,y+23));draw.text((x+5,y+5),f"{row['frame']} {row['pts_ms']:.4f}ms {row['published_pixels_identity']}",fill='white')
        sheet.save(folder/'contact.jpg',quality=93)
        report=dict(route=case['id'],fps=str(fps),fully_decoded_frames=len(rows),expected_frames=round(duration*float(fps)),
            movie_sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),bytes=movie.stat().st_size,boundary=selected,
            passed=len(selected)==13 and all(row['passed'] for row in selected) and abs(len(rows)-duration*float(fps))<=1)
        (folder/'frames.json').write_text(json.dumps(rows,separators=(',',':')),'utf8');reports.append(report)
        (out/'result.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps({k:v for k,v in report.items() if k!='boundary'}),flush=True)
    return 0 if all(r['passed'] for r in reports) else 1


if __name__=='__main__':raise SystemExit(main())
