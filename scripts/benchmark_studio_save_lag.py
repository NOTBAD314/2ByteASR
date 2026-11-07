"""Isolated report-size manual-save phases and GUI heartbeat (no user files)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--words',type=int,default=24)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('fresh source/tmp required')
    out.mkdir(parents=True)
    os.environ.update(QT_QPA_PLATFORM='offscreen',TWOBYTEASR_TEST_ROOT=str(out/'profile'))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QWidget
    from twobyteasr.acceptance.studio_search_fixture import make_project
    from twobyteasr.projects import studio_save as saves
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.playback.playback_gc_budget import install_gui_thread_collector,private_bytes
    app=QApplication([]);p=make_project(evidence_words=args.words)
    page=QWidget();page._revision_store=StudioRevisionStore(p)
    page._autosave_timer=QTimer(page)
    collector=install_gui_thread_collector(app)
    target=out/'saved.2byteproj';rows=[];phases={}
    original=saves.save_project_revision
    def writer(revision,path):
        result,details=original(revision,path);phases.update(details);return result,details
    saves.save_project_revision=writer
    for i in range(2):
        p.cues[0].text=f'第{i}次保存后的原文'
        p.asr_evidence['segment:0']['words'][0]['text']=f'第{i}次直接证据修改'
        ticks=[];last=[time.perf_counter()]
        def tick():
            now=time.perf_counter();ticks.append((now-last[0])*1000);last[0]=now
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(tick);timer.start()
        begin=time.perf_counter()
        with saves.manual_save_scope(page):
            revision=saves.capture_manual_save(page,p,i)
            captured=time.perf_counter();saves.persist_with_progress(page,revision,target)
        ticks.append((time.perf_counter()-last[0])*1000);timer.stop()
        row=dict(save=i,snapshot_ms=(captured-begin)*1000,total_ms=(time.perf_counter()-begin)*1000,
            max_gui_gap_ms=max(ticks),file_size=target.stat().st_size,private_bytes=private_bytes(),phases=dict(phases))
        print(json.dumps(row),flush=True);rows.append(row)
        loaded=load_project(target)
        assert loaded.cues[0].text==p.cues[0].text
        assert loaded.asr_evidence['segment:0']['words'][0]['text']==p.asr_evidence['segment:0']['words'][0]['text']
    collector.stop()
    (out/'result.json').write_text(json.dumps(dict(words=args.words,saves=rows),indent=2),'utf8')
    from twobyteasr.system.resident_worker import close_shared_worker
    close_shared_worker()


if __name__=='__main__':main()
