"""Identical Qt-dialog workload for the report baseline and patched source."""
import argparse
import cProfile
import collections
import json
import os
from pathlib import Path
import platform
import pstats
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--count',type=int,default=5555)
    parser.add_argument('--terms',type=int,default=300)
    parser.add_argument('--words',type=int,default=24)
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--project',type=Path)
    parser.add_argument('--needle',default='待替换名')
    parser.add_argument('--input-needle',default='勇者')
    parser.add_argument('--term-shape',choices=['disjoint','shared-alias'],default='disjoint')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('fresh source/tmp directory required')
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),QT_QPA_PLATFORM='windows' if args.headed else 'offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication,QWidget
    from twobyteasr.acceptance.studio_search_fixture import make_project
    from twobyteasr.studio.studio_find_replace import FindReplaceDialog
    app=QApplication.instance() or QApplication([])
    original_sha=None
    if args.project:
        import shutil,hashlib
        from twobyteasr.projects.studio_project import load_project
        original_sha=hashlib.sha256(args.project.read_bytes()).hexdigest()
        shutil.copy2(args.project,out/'input.2byteproj')
        p=load_project(out/'input.2byteproj')
    else:p=make_project(args.count,args.terms,args.words,term_shape=args.term_shape)
    class Page(QWidget):
        def __init__(self):
            super().__init__()
            self.session=SimpleNamespace(project=p,undo_stack=QUndoStack(self),selected_cue_id=p.cues[0].id if args.project else '400',generation=1)
            self.timeline=SimpleNamespace(active_subtitle_layer='translation',translation_selected_ids=['400'])
        def selected_cue_ids(self):return ['400']
        def _changed(self):pass
        def _show_studio_hint(self,*args):pass
    page=Page()
    counts=collections.Counter()
    watched={'relevant','rule_version','statuses','translation_view','text_entries','_document_fingerprint','entry_lookup'}
    def profiler(frame,event,arg):
        if event=='call' and frame.f_code.co_name in watched:counts[frame.f_code.co_name]+=1
    rows=[]
    def wait_until_quiet(d, timeout=90):
        started=time.perf_counter()
        while d._search_timer.isActive() or getattr(d,'_search_pending',False):
            app.processEvents()
            if time.perf_counter()-started>timeout:raise TimeoutError('search')
            time.sleep(.001)
        app.processEvents()
    def measure(name, action, d=None):
        counts.clear();ticks=[];last=[time.perf_counter()]
        def tick():
            now=time.perf_counter();ticks.append((now-last[0])*1000);last[0]=now
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(tick);timer.start()
        app.processEvents();time.sleep(.012);app.processEvents()
        ticks.clear();last[0]=time.perf_counter()
        if args.profile:sys.setprofile(profiler)
        start=time.perf_counter();value=action();handler=(time.perf_counter()-start)*1000
        if d is not None:wait_until_quiet(d)
        elapsed=(time.perf_counter()-start)*1000
        if args.profile:sys.setprofile(None)
        ticks.append((time.perf_counter()-last[0])*1000);timer.stop()
        row=dict(name=name,handler_ms=handler,total_ms=elapsed,max_heartbeat_gap_ms=max(ticks,default=0),calls=dict(counts))
        if d is not None:row.update(hits=len(d._preview_hits),rows=d.preview.count())
        if d is not None and hasattr(d,'_last_search_metrics'):row['work']=d._last_search_metrics
        if name=='replace-2' and d is not None:row['apply_work']=getattr(d,'_last_text_work',{})
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        return value
    d=measure('open',lambda:FindReplaceDialog(page))
    d._search_timer.stop()
    if args.headed:d.show();app.processEvents()
    for mode in ['original','translation','both']:
        d.text_targets.mode.setCurrentIndex(d.text_targets.mode.findData(mode))
        d._search_timer.stop()
        d.find_edit.blockSignals(True);d.find_edit.setText(args.needle);d.find_edit.blockSignals(False)
        d.replace_edit.blockSignals(True);d.replace_edit.setText('新译名');d.replace_edit.blockSignals(False)
        for phase in ['cold','warm']:
            measure(mode+'-'+phase,lambda:d._do_preview(),d)
        measure(mode+'-input',lambda:d.find_edit.setText(args.input_needle),d)
    if args.headed:
        d.grab().save(str(out/'search.png'))
    d.find_edit.setText(args.needle);wait_until_quiet(d)
    if args.project and len(d._preview_hits)>2:
        from PySide6.QtCore import Qt
        d._set_all_preview_checked(False)
        for i in range(2):d.preview.item(i).setCheckState(Qt.Checked)
    measure('replace-2',lambda:d._do_apply_preview(),d)
    d.reject();app.processEvents()
    unchanged=True if not args.project else hashlib.sha256(args.project.read_bytes()).hexdigest()==original_sha
    (out/'result.json').write_text(json.dumps(dict(python=sys.version,platform=platform.platform(),processor=os.environ.get('PROCESSOR_IDENTIFIER'),count=len(p.cues),terms=args.terms,words=args.words,profiled=args.profile,original_sha256=original_sha,original_unchanged=unchanged,operations=rows),ensure_ascii=False,indent=2),'utf8')
    return 0


if __name__=='__main__':raise SystemExit(main())
