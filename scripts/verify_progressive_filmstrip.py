"""Fifteen-second isolated real-media timeline paint audit, no playback."""
from pathlib import Path
import argparse
import json
import os
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    p=argparse.ArgumentParser()
    p.add_argument('--label',default='source')
    p.add_argument('--cache',type=Path)
    p.add_argument('--profile',action='store_true')
    p.add_argument('--ready-ui',action='store_true',help='Separate cold Qt window setup from media-open demand')
    p.add_argument('--interact',action='store_true',help='Pan/zoom cancellation and playback suspension within the same 15-second observation')
    args=p.parse_args()
    out=root/'tmp/progressive-v2-theme/filmstrip'/f'{time.strftime("%Y%m%d-%H%M%S")}-{args.label}'
    out.mkdir(parents=True)
    os.environ.update(QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        DASHSCOPE_API_KEY='sk-local-test-dummy',TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio_timeline import WaveformTimeline
    from twobyteasr.studio_project import load_project
    from twobyteasr.video_filmstrip import FilmstripCache,filmstrip_tiles
    app=QApplication([])
    rows=[];events=[];phase='initial'
    started=time.perf_counter()
    class Timeline(WaveformTimeline):
        def paintEvent(self,event):
            if args.profile and not rows:
                import cProfile,pstats
                profile=cProfile.Profile();profile.runcall(super().paintEvent,event)
                with (out/'first-paint-profile.txt').open('w') as f:pstats.Stats(profile,stream=f).sort_stats('cumulative').print_stats(35)
            else:super().paintEvent(event)
            now=time.perf_counter()
            state={'ms':(now-started)*1000,'phase':phase,'generation':self._thumbnails.generation,'tracks':{}}
            assets={a.asset_id:a for a in self.project.media_pool} if self.project else {}
            for track in self.project.video_tracks if self.project else []:
                rect=self._video_track_rect(track.id)
                keys=[]
                for clip in track.clips:
                    asset=assets[clip.asset_id]
                    left,right=self._time_to_x(clip.timeline_in_ms),self._time_to_x(clip.timeline_out_ms)
                    # Match both lane painters' inner thumbnail rectangles.
                    height=rect.height()-(18 if track.id=='V1' else 16)
                    tiles=filmstrip_tiles(left,right,max(left,self.TRACK_HEADER_WIDTH)+1,min(right,self._content_right())-1,clip.source_in_ms,clip.source_out_ms,height)
                    keys.extend(self._thumbnails.key(asset.canonical_source,t) for x,e,t in tiles)
                state['tracks'][track.id]={'needed':len(keys),'painted':sum(k in self._thumbnails.memory for k in keys)}
            rows.append(state)
    widget=Timeline()
    widget._thumbnails.close();widget._thumbnails.thread.join(2)
    cache=FilmstripCache(widget,cache_root=args.cache or out/'cache')
    widget._thumbnails=cache;cache.updated.connect(lambda _key:widget.update())
    project=load_project(root/'tmp/progressive-v2-theme/input-project.2byteproj')
    widget.resize(2048,390)
    widget.setWindowTitle('2ByteASR — 缩略图短时验收')
    if not args.ready_ui:widget.set_project(project);widget.set_visible_window(0,182317)
    started=time.perf_counter();widget.show()
    def open_media():
        nonlocal started
        rows.clear();started=time.perf_counter()
        widget.set_project(project);widget.set_visible_window(0,182317)
        if args.interact:
            for ms,name,start,duration in [(2000,'zoom',60000,30000),(2050,'pan',120000,30000),(3500,'pan-left',15000,30000),(5000,'overview',0,182317)]:
                QTimer.singleShot(ms,lambda name=name,start=start,duration=duration:change_view(name,start,duration))
            QTimer.singleShot(7000,lambda:suspend(True))
            QTimer.singleShot(10000,lambda:suspend(False))
        QTimer.singleShot(14900,finish)
    def change_view(name,start,duration):
        nonlocal phase
        phase=name;widget.set_visible_window(start,duration)
        events.append(dict(ms=(time.perf_counter()-started)*1000,name=name,decoded=cache.metrics['decoded'],generation=cache.generation))
    def suspend(value):
        cache.set_paused(value)
        events.append(dict(ms=(time.perf_counter()-started)*1000,name='pause' if value else 'resume',decoded=cache.metrics['decoded'],generation=cache.generation))
    def finish():
        widget.grab().save(str(out/'timeline.png'))
        cache.set_paused(True)
        result={'label':args.label,'ready_ui':args.ready_ui,'cache':str(cache.root),'seconds':time.perf_counter()-started,'rows':rows,'metrics':cache.metrics,
            'wanted_count':len(cache.wanted),'generated_files':len(list(cache.root.glob('*.jpg'))),'trace':getattr(cache,'trace',[]),'trace_origin_ms':(cache.started-started)*1000,'events':events}
        summary={}
        for track in ('V1','V2','all'):
            summary[track]={}
            for label,fraction in [('first',0),('50%',.5),('80%',.8),('100%',1)]:
                value=None
                for row in rows:
                    if row['phase']!='initial':continue
                    values=list(row['tracks'].values()) if track=='all' else [row['tracks'].get(track,{})]
                    needed=sum(v.get('needed',0) for v in values);painted=sum(v.get('painted',0) for v in values)
                    if needed and (painted>0 if fraction==0 else painted/needed>=fraction):value=round(row['ms'],2);break
                summary[track][label]=value
        result['milestones_ms']=summary
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'out':str(out),'milestones_ms':summary,'metrics':cache.metrics,'wanted':len(cache.wanted)},ensure_ascii=False),flush=True)
        widget.close();app.quit()
    if args.ready_ui:QTimer.singleShot(2000,open_media)
    else:QTimer.singleShot(14900,finish)
    app.exec();cache.close();cache.thread.join(3)


if __name__=='__main__':main()
