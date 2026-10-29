"""Repeatable command-only costs; GUI measurements use the headed audit separately."""
import argparse, cProfile, io, json, os, pstats, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',action='store_true')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ.update(QT_QPA_PLATFORM='offscreen',TWOBYTEASR_TEST_ROOT=str(out/'profile'))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    from twobyteasr.caption_style.style_field_patch import style_fields_command
    from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
    results={}
    for filename in ['mix100','mix1000','base','dense5000']:
        p=load_project(args.fixtures/(filename+'.2byteproj'));ensure_independent_captions(p)
        ids=[c.id for c in p.cues]; rows=[]
        for op,make in [('font-size',lambda:style_fields_command(p,ids,{'font_size':66})),
                        ('font',lambda:style_fields_command(p,ids,{'font_family':'Arial'})),
                        ('position',lambda:style_fields_command(p,ids,{'position_x':900,'position_y':800})),
                        ('outline',lambda:style_fields_command(p,ids,{'outline_width':5,'outline_color':'#FF112233'})),
                        ('shadow',lambda:style_fields_command(p,ids,{},shadow_patch={'opacity':.6})),
                        ('replace-text',lambda:BatchReplaceTextCommand(p,{c.id:c.text+'好' for c in p.cues}))]:
            for repeat in range(3):
                profiler=cProfile.Profile() if args.profile and repeat==0 else None
                if profiler:profiler.enable()
                start=time.perf_counter();cmd=make();built=time.perf_counter();cmd.redo();applied=time.perf_counter();cmd.undo();undone=time.perf_counter()
                if profiler:
                    profiler.disable();buf=io.StringIO();pstats.Stats(profiler,stream=buf).sort_stats('cumtime').print_stats(35)
                    (out/(filename+'-'+op+'.txt')).write_text(buf.getvalue(),'utf8')
                rows.append(dict(operation=op,repeat=repeat,build_ms=1000*(built-start),redo_ms=1000*(applied-built),undo_ms=1000*(undone-applied)))
        results[filename]={'count':len(ids),'samples':rows}
        (out/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
        print(filename,len(ids),flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
