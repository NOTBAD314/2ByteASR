"""Read-only foreground/ROI evidence for cadence collection, never focus control."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time


def visible_sample(root, coverage):
    """Owned modal windows can obscure video too; require the actual root."""
    return bool(coverage.get('foreground')==root and coverage.get('foreground_owned')
                and coverage.get('all_points_owned') and coverage.get('points')
                and all(point.get('root')==root for point in coverage['points']))


def visibility_summary(samples, begin, end):
    rows=[row for row in samples if begin-.2<=row['at']<=end+.2]
    issues=[]
    if not rows or rows[0]['at']>begin+.2 or rows[-1]['at']<end-.2:
        issues.append('foreground/ROI observations do not cover the measurement interval')
    invalid=[row for row in rows if begin<=row['at']<=end and not row.get('valid')]
    if invalid:issues.append('audited root lost foreground, ROI ownership, geometry, or native target')
    if any(right['at']-left['at']>.3 for left,right in zip(rows,rows[1:])):
        issues.append('foreground/ROI observation gap exceeds 300 ms')
    return {'measurement_valid':not issues,'invalid_reasons':issues,'samples':len(rows),
            'invalid_samples':len(invalid),'first_observed_qpc':rows[0]['at'] if rows else None,
            'last_observed_qpc':rows[-1]['at'] if rows else None,
            'scope':'100 ms native foreground and 9-point ROI ownership samples; pixel validity is checked separately'}


class PlaybackVisibility:
    def __init__(self, window, out, viewport, *, manual=False, fixed_roi=True):
        from .loading_native_probe import NativeLoadingProbe
        self.window,self.out,self.viewport=window,Path(out),viewport
        self.root=int(window.winId());self.probe=NativeLoadingProbe()
        self.manual,self.fixed_roi=bool(manual),bool(fixed_roi)
        self.expected_roi=None
        self.samples=[]
        self.started=time.perf_counter()
        self.last=None
        title=f'播放验证 · {self.out.parent.name} · {self.out.name}'
        window.setWindowTitle(title)
        self.request={'pid':os.getpid(),'hwnd':self.root,'title':title,
            'manual_approval_required':self.manual,'approval_file':str(self.out/'foreground-approved.json'),
            'instruction':'Activate this exact test window; capture and playback wait for foreground and unobscured ROI.'}
        (self.out/'foreground-request.json').write_text(json.dumps(self.request,ensure_ascii=False,indent=2),'utf8')
        print('PLAYBACK_FOREGROUND_GATE '+json.dumps(self.request,ensure_ascii=False),flush=True)

    def observe(self):
        now=time.perf_counter()
        try:
            roi=list(self.viewport());x,y,w,h=roi
            coverage=self.probe.coverage(self.root,(x,y,x+w,y+h))
            valid=visible_sample(self.root,coverage)
            if self.fixed_roi and self.expected_roi is not None and roi!=self.expected_roi:
                valid=False
            row={'at':now,'valid':valid,'viewport':roi,'expected_viewport':self.expected_roi,
                 'coverage':coverage}
        except Exception as error:
            row={'at':now,'valid':False,'error':f'{type(error).__name__}: {error}'}
        self.last=row
        return row

    def ready(self):
        approved=not self.manual
        if self.manual:
            try:
                value=json.loads((self.out/'foreground-approved.json').read_text('utf-8-sig'))
                approved=value.get('pid')==self.request['pid'] and value.get('hwnd')==self.root
            except (OSError,ValueError):pass
        row=self.observe()
        if approved and row['valid']:
            self.expected_roi=row['viewport']
            return True
        if time.perf_counter()-self.started>(300 if self.manual else 60):
            raise TimeoutError('foreground/ROI gate not satisfied; capture and playback did not start')
        return False

    def sample(self):
        # The gate's waiting time is not a measurement sample and cannot consume
        # this bounded recording capacity before the user grants the foreground.
        if len(self.samples)<6000:self.samples.append(self.observe())
