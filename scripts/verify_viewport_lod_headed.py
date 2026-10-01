"""Bounded real-media LOD/PTS verification; only a 30s viewport and 31.8–35.6s."""
import argparse,json,os,sys,time,traceback,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert out.is_relative_to(ROOT/'tmp')
    os.environ.update(QT_QPA_PLATFORM='windows',LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'))
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint,QPointF,Qt,QTimer
    from PySide6.QtGui import QWheelEvent
    from twobyteasr.studio_project import load_project
    from twobyteasr.studio_timeline import WaveformTimeline
    from twobyteasr.video_filmstrip import FilmstripCache
    app=QApplication.instance() or QApplication([])
    project=load_project(args.project)
    timeline=WaveformTimeline();timeline.resize(1400,520);timeline.move(70,70)
    timeline._thumbnails.close()
    cache=FilmstripCache(timeline,cache_root=out/'cache')
    timeline._thumbnails=cache;cache.updated.connect(lambda *_:timeline.update())
    timeline.set_project(project);timeline.set_visible_window(26000,30000)
    timeline.show();QTest.qWaitForWindowExposed(timeline)
    result=dict(passed=False,checks=[],samples=[],playback_seconds=0)
    gaps=[];last=[time.perf_counter()]
    timer=QTimer(timeline);timer.setInterval(10)
    def tick():
        now=time.perf_counter();gaps.append((now-last[0])*1000);last[0]=now
    timer.timeout.connect(tick);timer.start()
    def check(name,passed,detail=None):
        result['checks'].append(dict(name=name,passed=bool(passed),detail=detail))
        if not passed:raise AssertionError(name)
    def wait(predicate,seconds=12):
        start=time.perf_counter()
        # Unlike the normal QApplication.exec(), repeated QTest.qWait calls
        # can hold the Python GIL while handling paints. Release it explicitly
        # so this harness does not throttle the Python/PyAV worker it measures.
        while not predicate() and time.perf_counter()-start<seconds:
            app.processEvents();time.sleep(.005)
        return predicate(),round((time.perf_counter()-start)*1000,2)
    def visible_keys():return [k for k,job in cache.wanted.items() if job[0]<2]
    def refined():return bool(visible_keys()) and all(k in cache.refined and k in cache.memory for k in visible_keys())
    def shot(name):timeline.grab().save(str(out/(name+'.png')))
    try:
        ready,first_ms=wait(lambda:bool(cache.memory))
        check('coarse first cells progressive',ready,first_ms)
        shot('coarse-first')
        ready,fill_ms=wait(refined,20)
        check('30s viewport exact samples complete',ready,dict(ms=fill_ms,metrics=cache.metrics,trace=cache.trace[-8:]))
        shot('coarse-complete')
        coarse_key=cache.view_key;coarse_lods={v.lod_ms for v in cache.views}
        coarse_decodes=cache.metrics['decoded']
        timeline.set_visible_window(31800,3800)
        timeline.repaint();app.processEvents()
        initial=[cache.get(v.source,t,lod_ms=v.lod_ms) for v in cache.views for t in v.visible]
        check('coarse images remain immediately on zoom',bool(initial) and all(image is not None for image in initial))
        shot('zoom-coarse-retained')
        fine_generation=cache.generation
        ready,fine_ms=wait(refined,20)
        check('zoom dense exact samples complete',ready,dict(ms=fine_ms,metrics=cache.metrics,trace=cache.trace[-8:]))
        fine_lods={v.lod_ms for v in cache.views}
        check('LOD becomes denser',min(fine_lods)<min(coarse_lods),dict(coarse=sorted(coarse_lods),fine=sorted(fine_lods)))
        fine=[row for row in cache.trace if row.get('generation')==fine_generation and row.get('exact') and 31800<=row['requested_ms']<=35600]
        check('multiple subsecond actual samples',len({r['requested_ms'] for r in fine})>=8,fine)
        check('PTS follows requested time',all(abs(r['pts_ms']-r['requested_ms'])<=34 for r in fine))
        check('distinct decoded PTS',len({r['pts_ms'] for r in fine})>=8)
        check('visible and prefetch jobs bounded',len(cache.wanted)<=48 and all(31000<=job[2]<=36500 for job in cache.wanted.values()),dict(count=len(cache.wanted),range=[min(j[2] for j in cache.wanted.values()),max(j[2] for j in cache.wanted.values())]))
        shot('zoom-31.8-35.6-exact')
        result['samples']=fine
        # Real wheel events, alternating zoom and horizontal time movement.
        event_cost=[]
        for i in range(18):
            point=QPointF(timeline.width()*.6,50)
            modifier=Qt.KeyboardModifier.ControlModifier if i%3 else Qt.KeyboardModifier.NoModifier
            event=QWheelEvent(point,QPointF(timeline.mapToGlobal(point.toPoint())),QPoint(),QPoint(0,120 if i%2 else -120),Qt.MouseButton.NoButton,modifier,Qt.ScrollPhase.NoScrollPhase,False)
            began=time.perf_counter();app.sendEvent(timeline,event);app.processEvents();event_cost.append((time.perf_counter()-began)*1000)
            QTest.qWait(12)
        check('pan zoom changes demand generations',cache.generation>fine_generation+3,cache.generation)
        check('pan zoom remains interactive',max(event_cost)<200,dict(max_ms=max(event_cost),costs=event_cost))
        final_sources={v.source for v in cache.views}
        check('no orphan source jobs',all(j[1] in final_sources for j in cache.wanted.values()))
        # Restore coarse view: the on-disk/in-memory LOD is reused.
        cache.set_paused(True)
        timeline.set_visible_window(26000,30000);timeline.repaint();app.processEvents()
        check('coarse cache immediately reused',all(cache.get(v.source,t,lod_ms=v.lod_ms) is not None for v in cache.views for t in v.visible))
        before=cache.metrics['decoded'];QTest.qWait(80)
        check('zoom out does not decode whole source',cache.metrics['decoded']==before and cache.metrics['idle_generated']==0)
        result.update(metrics=cache.metrics,trace=cache.trace,gui_timer_max_ms=max(gaps,default=0),source=project.media.path)
        result['passed']=True
    except Exception:result['error']=traceback.format_exc();result.update(metrics=cache.metrics,trace=cache.trace);shot('failure')
    finally:
        timer.stop();timeline.close();cache.close();cache.thread.join(2)
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','error','metrics','gui_timer_max_ms')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
