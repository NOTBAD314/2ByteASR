"""Discrete-operation capture, using fresh native geometry for every segment.

The generator is driven by the existing acceptance QTimer. It never pumps an
event loop, blocks for a child process, or labels an uncaptured gap smooth.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import time


class StableViewport:
    def __init__(self, *, minimum_seconds=.05, minimum_samples=3):
        self.minimum_seconds = minimum_seconds
        self.minimum_samples = minimum_samples
        self.value = None
        self.since = None
        self.count = 0

    def observe(self, value, now):
        value = tuple(value)
        if value != self.value:
            self.value, self.since, self.count = value, now, 1
        else:
            self.count += 1
        return self.count >= self.minimum_samples and now-self.since >= self.minimum_seconds


class ResizeCapture:
    """Before, narrower, restored: each stable interval has a new collector."""
    def __init__(self, window, page, out, spec, owned, viewport):
        self.window, self.page, self.out, self.spec = window, page, Path(out), spec
        self.owned, self.viewport = owned, viewport
        self.segments, self.operations, self.gaps = [], [], []
        self.stable_seconds = float(spec['seconds'])/3
        self.original_size = (window.width(), window.height())
        self.current = None

    def _start(self, name):
        if self.current is not None and self.current[2] is not None and self.current[2].poll() is None:
            raise RuntimeError('previous desktop collector must finish before another viewport starts')
        folder = self.out/'resize-segments'/name
        folder.mkdir(parents=True, exist_ok=False)
        now = time.perf_counter()
        rect = list(self.viewport())
        record = {'id':name, 'roi_generation':len(self.segments)+1,
            'directory':str(folder.relative_to(self.out)), 'viewport':rect,
            'configured_at':now, 'dpr':self.window.devicePixelRatioF(),
            'screen':self.window.screen().name(), 'refresh_hz':self.window.screen().refreshRate(),
            'window_logical_size':[self.window.width(),self.window.height()],
            'geometry_valid':True, 'geometry_samples':[{'at':now,'viewport':rect}],
            'errors':[], 'regions':self.spec.get('regions',[])}
        process = log = None
        if self.spec.get('capture'):
            log = (folder/'capture.log').open('wb')
            command = [self.spec['capture'],*map(str,rect),str(self.stable_seconds+3),
                       str(self.spec.get('barcode_y',-1)),str(folder/'desktop.csv')]
            process = subprocess.Popen(command,stdout=log,stderr=log,
                                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.owned.append((process,log))
            record['command'] = command
        else:
            record['errors'].append('no desktop collector supplied')
        self.segments.append(record)
        self.current = (record,folder,process,log)
        return record

    def _ready(self):
        record,folder,process,_ = self.current
        if process is None:
            return True
        names = ['desktop.csv',*[row['name']+'-desktop.csv' for row in self.spec.get('regions',[])]]
        markers = {}
        for name in names:
            try:
                markers[name] = json.loads((folder/(name+'.ready')).read_text('utf8'))
            except (OSError,ValueError):
                pass
        record['capture_readiness'] = markers
        if len(markers) == len(names):
            record['capture_ready_qpc'] = max(row['ready_qpc_s'] for row in markers.values())
            return True
        if process.poll() is not None:
            record['errors'].append('collector exited before all regions became ready')
            return True
        return False

    def _monitor(self):
        record,_,_,_ = self.current
        now = time.perf_counter()
        if now-record['geometry_samples'][-1]['at'] < .1:
            return
        rect = list(self.viewport())
        record['geometry_samples'].append({'at':now,'viewport':rect})
        if rect != record['viewport']:
            record['geometry_valid'] = False

    def prepare(self):
        self._start('00-before')
        yield self._ready

    def _collect(self, start):
        record,_,process,log = self.current
        record['sample_start_qpc'] = start
        record['sample_end_qpc'] = start+self.stable_seconds
        def sampled():
            self._monitor()
            if process is not None and process.poll() is not None:
                if time.perf_counter() < record['sample_end_qpc']:
                    record['errors'].append('collector ended before the declared stable interval')
                    record['sample_end_qpc'] = time.perf_counter()
                return True
            return time.perf_counter() >= record['sample_end_qpc']
        yield sampled
        if process is not None:
            yield lambda:process.poll() is not None
            record['capture_exit_code'] = process.returncode
            if process.returncode:
                record['errors'].append('collector failed with exit '+str(process.returncode))
            log.close()
        record['completed_at'] = time.perf_counter()

    def run(self, begin):
        # The parent has already excluded the normal first playback second.
        yield from self._collect(begin+1)
        width,height = self.original_size
        sizes = ((max(self.window.minimumWidth(),width-160),
                  max(self.window.minimumHeight(),height-80)), self.original_size)
        for index,size in enumerate(sizes,1):
            prior = self.segments[-1]
            before = list(self.viewport())
            operation = {'kind':'resize','id':f'resize-{index}', 'at':time.perf_counter(),
                         'requested_logical_size':list(size),'viewport_before':before}
            self.window.resize(*size)
            operation['gui_ms'] = (time.perf_counter()-operation['at'])*1000
            self.operations.append(operation)
            stable = StableViewport()
            def settled():
                now = time.perf_counter()
                rect = list(self.viewport())
                if stable.observe(rect,now):
                    operation.update(geometry_stable_at=now,viewport_after=rect,
                                     geometry_changed=rect!=before)
                    return True
                if now-operation['at']>5:
                    raise TimeoutError('native viewport did not settle after resize')
                return False
            yield settled
            self._start(f'{index:02d}-'+('narrower' if index==1 else 'restored'))
            yield self._ready
            record = self.current[0]
            sample_start = max(time.perf_counter(),record.get('capture_ready_qpc',0))
            operation['capture_ready_qpc'] = record.get('capture_ready_qpc')
            operation['roi_generation'] = record['roi_generation']
            operation['prior_segment'] = prior['id']
            operation['segment'] = record['id']
            self.gaps.append({'start':prior['sample_end_qpc'],'end':sample_start,
                'reason':'collector handoff and actual native geometry stabilization; not measured',
                'operation':operation['id']})
            yield from self._collect(sample_start)


def record_seek(page, result, target):
    operations = result.setdefault('operations',[])
    previous = next((row for row in reversed(operations) if row.get('kind')=='seek'),None)
    item = {'kind':'seek','id':f'seek-{sum(row.get("kind")=="seek" for row in operations)+1}',
            'target':target,'at':time.perf_counter()}
    observed = page.video.controller.observed_properties()
    item['before_source_seconds'] = observed.get('time-pos')
    if previous is not None:
        previous['superseded_by'] = item['id']
        previous['superseded_at'] = item['at']
        previous['superseded_before_deadline'] = item['at']-previous['at'] < .250
    prior_generation = page.video._playback_clock.generation
    page._seek(target)
    trace = getattr(page.video,'_active_seek_trace',None) or {}
    item.update(gui_ms=(time.perf_counter()-item['at'])*1000,
        generation=page.video._playback_clock.generation,
        request_issued=page.video._playback_clock.generation!=prior_generation,
        source_path=getattr(page.video,'_media_path',''),
        target_source_seconds=trace.get('decoder_target_seconds'),
        ui_playhead_ms=int(page.timeline.playhead_ms))
    operations.append(item)


def sample_seek_witness(page, result, now):
    item = next((row for row in reversed(result.get('operations',[])) if row.get('kind')=='seek'),None)
    if item is None or item.get('native_frame_ready_qpc') is not None:
        return
    reader = getattr(page.video.controller,'observed_frame',None)
    if not callable(reader):
        return  # Older baselines have no witness; never manufacture one.
    witness = reader()
    if (witness.get('status')=='ready' and witness.get('source_generation')==item.get('generation')
            and not page.video._playback_clock.exact_seek_pending):
        item['native_frame_ready_qpc'] = now
        item['native_frame_witness'] = witness
        item['native_frame_ready_ms'] = (now-item['at'])*1000
