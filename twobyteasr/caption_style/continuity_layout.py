"""Seek-independent slot leases for local continuous subtitle chains."""
from __future__ import annotations

import heapq
from bisect import bisect_left, bisect_right
from dataclasses import replace
from PySide6.QtCore import QRectF

from ..subtitle_rules.display_continuity import continuity_successors, chain_key, MAX_DISPLAY_MS


def cue_key(cue):
    return str(getattr(cue,'id',getattr(cue,'cue_id','')))


def continuity_components(cues):
    rows=sorted(cues,key=lambda c:(c.start_ms,c.end_ms,cue_key(c)))
    successors=continuity_successors(rows)
    by_id={cue_key(c):c for c in rows}
    starts=[cue.start_ms for cue in rows]
    lane_starts={}
    for cue in rows:
        lane_starts.setdefault(chain_key(cue),[]).append(cue.start_ms)
    clusters,cluster=[],[]
    ending=(float('-inf'),False)
    for cue in rows:
        if cluster and (cue.start_ms>ending[0] or cue.start_ms==ending[0] and not ending[1]):
            clusters.append(cluster)
            cluster=[]
        cluster.append(cue)
        successor=by_id.get(successors.get(cue_key(cue)))
        if successor is not None:
            # A solo continuation can start a compact independent component.
            # Connect the lease across a gap only when a different owner
            # actually enters there. Real overlaps already connect naturally.
            lane=lane_starts[chain_key(cue)]
            all_entries=bisect_right(starts,successor.start_ms)-bisect_left(starts,cue.end_ms)
            same_entries=bisect_right(lane,successor.start_ms)-bisect_left(lane,cue.end_ms)
            if all_entries==same_entries:
                successor=None
        ending=max(ending,(cue.end_ms,False),
                   (successor.start_ms,True) if successor else (cue.end_ms,False))
    if cluster:
        clusters.append(cluster)
    return clusters


class ContinuityLayout:
    """Measure a bounded lookahead; replay events only once per revision."""
    def __init__(self,rows,snapshots_for,*,bounds_for=None,enabled=True):
        self.rows=sorted(rows,key=lambda c:(c.start_ms,c.end_ms,cue_key(c)))
        self.by_id={cue_key(c):c for c in self.rows}
        self.successors=continuity_successors(self.rows)
        self.predecessors={right:left for left,right in self.successors.items()}
        self.snapshots_for=snapshots_for
        self.bounds_for=bounds_for
        self.enabled=enabled
        self.cursor=0
        self.active={}
        self.endings=[]
        self.offsets={}
        self.warnings=[]
        self.members={}
        self.bounds={}

    def load(self,key):
        if key not in self.members:
            self.members[key]=tuple(self.snapshots_for(self.by_id[key]))
        return self.members[key]

    def bounds_of(self,key):
        if key not in self.bounds:
            from .collision_layout import visual_bounds
            box=QRectF()
            for snapshot in self.load(key):
                supplied=self.bounds_for(snapshot) if self.bounds_for else None
                value=supplied if supplied is not None else snapshot.collision_bounds
                value=visual_bounds(snapshot) if value is None else QRectF(*value) if not isinstance(value,QRectF) else value
                box=box.united(value)
            self.bounds[key]=box
        return QRectF(self.bounds[key])

    def reserved_snapshots(self,key):
        box=self.bounds_of(key)
        next_key=self.successors.get(key)
        horizon=self.by_id[key].start_ms+MAX_DISPLAY_MS
        measured=0
        while next_key and self.by_id[next_key].start_ms<=horizon and measured<64:
            box=box.united(self.bounds_of(next_key))
            next_key=self.successors.get(next_key)
            measured+=1
        return [replace(snapshot,collision_bounds=(box.x(),box.y(),box.width(),box.height()))
                for snapshot in self.load(key)]

    def advance(self,target):
        from .collision_layout import solve_layout
        while self.cursor<len(self.rows) and self.rows[self.cursor].start_ms<=target:
            at=self.rows[self.cursor].start_ms
            while self.endings and self.endings[0][0]<=at:
                _,key=heapq.heappop(self.endings)
                self.active.pop(key,None)
                self.members.pop(key,None)
            stop=self.cursor+1
            while stop<len(self.rows) and self.rows[stop].start_ms==at:
                stop+=1
            entering=[cue_key(row) for row in self.rows[self.cursor:stop]]
            fixed={snapshot.cue_id:self.offsets[snapshot.cue_id]
                   for values in self.active.values() for snapshot in values}
            new_snapshots=[]
            for key in entering:
                snapshots=self.reserved_snapshots(key)
                previous=self.predecessors.get(key)
                # Resume a lease before placing unrelated simultaneous entries.
                # A safe solo entry can compact after the other chain ended.
                if previous and (self.active or len(entering)>1):
                    prior=self.offsets.get(previous)
                    if prior is not None:
                        fixed.update((s.cue_id,prior) for s in snapshots)
                new_snapshots.extend(snapshots)
            layout=solve_layout([s for values in self.active.values() for s in values]+new_snapshots,
                                enabled=self.enabled,fixed_offsets=fixed)
            self.warnings.extend(layout.warnings)
            for key in entering:
                snapshots=tuple(s for s in new_snapshots if s.cue_id==key or s.cue_id==key+'#tr')
                self.active[key]=snapshots
                for snapshot in snapshots:
                    self.offsets[snapshot.cue_id]=layout.offsets.get(snapshot.cue_id,0.)
                successor=self.by_id.get(self.successors.get(key))
                end=successor.start_ms if successor else self.by_id[key].end_ms
                heapq.heappush(self.endings,(end,key))
            self.cursor=stop
        return self.offsets
