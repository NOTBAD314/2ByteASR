"""Immutable time-window views for independent text requests."""
from __future__ import annotations
import bisect
from itertools import accumulate


class EvidenceWindows:
    def __init__(self, rows):
        self.rows=sorted(rows or (),key=lambda row:float(row.get('start',0)))
        self.starts=[float(row.get('start',0)) for row in self.rows]
        self.ends=list(accumulate((float(row.get('end',0)) for row in self.rows),max))

    def between(self,start,end):
        lo=bisect.bisect_left(self.ends,start)
        hi=bisect.bisect_right(self.starts,end)
        return [self.rows[index] for index in range(lo,hi)
                if float(self.rows[index].get('end',0))>=start]
