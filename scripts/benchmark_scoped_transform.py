"""Controlled same-cohort inspector cost; offscreen results do not measure pixels."""
import argparse,copy,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--counts',default='21,speaker,all,5000');parser.add_argument('--profile',action='store_true')
    parser.add_argument('--baseline',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('Fresh repository tmp directory required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out);os.environ['QT_QPA_PLATFORM']='offscreen'
    if args.baseline:
        import importlib.abc,importlib.util
        base=args.baseline.resolve()
        class Before(importlib.abc.MetaPathFinder):
            def find_spec(self,name,path=None,target=None):
                file=base/Path(*name.split('.')).with_suffix('.py')
                current=ROOT/Path(*name.split('.')).with_suffix('.py')
                if name.startswith('twobyteasr.') and file.is_file() and current.is_file() and file.read_bytes()!=current.read_bytes() and '.acceptance.' not in name:
                    return importlib.util.spec_from_file_location(name,file)
        sys.meta_path.insert(0,Before())
    from twobyteasr.test_isolation import install,require_isolated_paths
    install();require_isolated_paths('scope-transform-benchmark',emit=lambda *_:None)
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.timeline.selection_scope import SelectionScope
    from twobyteasr.caption_style.caption_layer_transform import resolved_values
    app=QApplication.instance() or QApplication([]);original=load_project(args.project)
    result={'measurement':'GUI handler/commit only; no physical preview latency','cases':{},'error':''}
    try:
        for label in args.counts.split(','):
            page=SubtitleStudioPage();p=copy.deepcopy(original)
            if label.isdigit() and int(label)>len(p.cues):
                count=int(label);source=copy.deepcopy(p.cues);span=max(c.end_ms for c in source)+500
                p.cues=[]
                for i in range(count):
                    cue=copy.deepcopy(source[i%len(source)]);cue.id='bench-'+str(i);offset=i//len(source)*span
                    cue.start_ms+=offset;cue.end_ms+=offset;p.cues.append(cue)
                p.media.duration_ms=max(c.end_ms for c in p.cues)
            p.validate();page.project=p;page.project_path=out/(label+'.2byteproj')
            page._cue_lookup={c.id:c for c in p.cues};page._manual_text_baselines={c.id:c.text for c in p.cues}
            page.cue_model.set_project(p);page.timeline.set_project(p);page._populate_speakers();page.select_cue(p.cues[0].id)
            chosen=(p.cues if label in ('all','5000') else [c for c in p.cues if c.speaker_id==p.cues[0].speaker_id]
                    if label=='speaker' else p.cues[:int(label)])
            stamp=time.perf_counter();page.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in chosen],chosen[0].id))
            page.style_scope.setCurrentIndex(page.style_scope.findData('selected'));panel=page.caption_transform_panel;panel.refresh()
            scope_ms=(time.perf_counter()-stamp)*1000
            before={c.id:copy.deepcopy(c.transform) for c in p.cues};value=resolved_values(p,chosen[0],'original')
            profiler=None
            if args.profile:
                import cProfile
                profiler=cProfile.Profile();profiler.enable()
            stamp=time.perf_counter();panel.begin_gesture();begin_ms=(time.perf_counter()-stamp)*1000
            moves=[]
            for i in range(30):
                stamp=time.perf_counter();panel.apply({'position_x':value['position_x']+i+1});moves.append((time.perf_counter()-stamp)*1000)
            stamp=time.perf_counter();panel.end_gesture();commit_ms=(time.perf_counter()-stamp)*1000
            stamp=time.perf_counter();panel.refresh();refresh_ms=(time.perf_counter()-stamp)*1000
            if profiler:
                import pstats,io
                profiler.disable();stream=io.StringIO();pstats.Stats(profiler,stream=stream).sort_stats('cumtime').print_stats(55)
                (out/(label+'-profile.txt')).write_text(stream.getvalue(),'utf8')
            changed=[c.id for c in p.cues if c.transform!=before[c.id]]
            result['cases'][label]={'project_count':len(p.cues),'targets':len(chosen),'changed':len(changed),
                'exact_cohort_changed':set(changed)=={c.id for c in chosen},'scope_ms':scope_ms,'begin_ms':begin_ms,
                'move_handler_ms':moves,'commit_ms':commit_ms,'refresh_ms':refresh_ms,'undo_steps':page.undo_stack.count()}
            print(label,json.dumps(result['cases'][label])[:650],flush=True)
            (out/'result.json').write_text(json.dumps(result,indent=2),'utf8')
            page.close_page();page.deleteLater();app.processEvents()
    except Exception:
        import traceback
        result['error']=traceback.format_exc();raise
    finally:(out/'result.json').write_text(json.dumps(result,indent=2),'utf8')


if __name__=='__main__':main()
