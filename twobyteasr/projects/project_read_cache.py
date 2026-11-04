"""Version-keyed bounded immutable payload cache and coalesced disk reads.

Never lend a mutable document to another consumer. Cached row bytes have no
Qt objects or references to a live project, undo stack, view, or worker.
"""
from collections import OrderedDict
from concurrent.futures import Future
import json,marshal,threading,time,os
from pathlib import Path

_lock=threading.RLock();_entries=OrderedDict();_flights={}
_read_slots=threading.BoundedSemaphore(2)
_stats=dict(hits=0,misses=0,joined=0,evictions=0,bytes=0,reads=0)
_parked=OrderedDict()

def identity(path):
    path=Path(path).resolve();st=path.stat()
    return (os.path.normcase(str(path)),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)

def budget():
    from ..system.memory_budget import memory_status
    status=memory_status()
    limit=min(768*1024**2,max(0,status['available']//8))
    if status['rss']>status['total']//4:limit=min(limit,128*1024**2)
    return limit


def stats():
    with _lock:return dict(_stats,entries=len(_entries),inflight=len(_flights),budget=budget(),
        parked=len(_parked),parked_estimated_bytes=sum(row[3] for row in _parked.values()))

def park(path,project,store,consistency):
    """Keep at most one clean detached document for the next library reopen.

    Ownership is transferred, never shared: checkout removes it atomically.
    The estimate is deliberately conservative and independent of byte cache.
    """
    if project is None or store is None:return
    runtime=getattr(project,'_studio_state_runtime',None)
    if runtime is None or runtime.has_subscribers or runtime._active is not None:return
    try:key=identity(path)
    except OSError:return
    estimate=key[3]*8
    if estimate>budget()*2:return
    with _lock:
        _parked.clear()
        _parked[key]=(project,store,consistency,estimate)

def take(path):
    try:key=identity(path)
    except OSError:return None
    with _lock:
        for old in list(_parked):
            if (old[0]==key[0] and old!=key) or _parked[old][3]>budget()*2:
                _parked.pop(old,None)
        row=_parked.pop(key,None)
        if row is None:return None
        _stats['parked_hits']=_stats.get('parked_hits',0)+1
    project,store,consistency,_=row
    runtime=project._studio_state_runtime
    project._prepared_open=(project.project_id,runtime.revision,consistency,0,store)
    return project

def _freeze(payload):
    result={};deadline=time.perf_counter()+.006
    for field,value in payload.items():
        if isinstance(value,dict):items=value.items();kind='dict'
        elif isinstance(value,list):items=enumerate(value);kind='list'
        else:result[field]=('value',marshal.dumps(value));continue
        rows=[]
        for key,row in items:
            rows.append((key,marshal.dumps(row)))
            if time.perf_counter()>=deadline:time.sleep(.001);deadline=time.perf_counter()+.006
        result[field]=(kind,tuple(rows))
    return result

def _thaw(frozen):
    result={};deadline=time.perf_counter()+.006
    for field,(kind,rows) in frozen.items():
        if kind=='value':result[field]=marshal.loads(rows);continue
        value={} if kind=='dict' else []
        for key,blob in rows:
            item=marshal.loads(blob)
            if kind=='dict':value[key]=item
            else:value.append(item)
            if time.perf_counter()>=deadline:time.sleep(.001);deadline=time.perf_counter()+.006
        result[field]=value
    return result

def _parse_worker(connection,path):
    """Pure-data spawn target. Never import or receive GUI/runtime objects."""
    try:
        import gc
        # This child owns only acyclic JSON and exits after one document.
        # Its collector need not repeatedly scan millions of temporary rows.
        gc.disable()
        started=time.perf_counter()
        with open(path,'r',encoding='utf-8-sig') as stream:payload=json.load(stream)
        decoded=time.perf_counter()
        frozen=_freeze(payload)
        connection.send((True,(frozen,{'decode_ms':(decoded-started)*1000,
                                      'encode_ms':(time.perf_counter()-decoded)*1000})))
    except BaseException as exc:
        connection.send((False,(type(exc).__name__,str(exc))))
    finally:connection.close()

def _read_large(path):
    # stdlib JSON's C decoder holds the GIL. A Python reader thread alone
    # cannot keep the animation moving while it decodes a 130 MB document.
    import multiprocessing
    with _read_slots:
        context=multiprocessing.get_context('spawn')
        receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=_parse_worker,args=(sender,str(path)),name='project-json-reader',daemon=True)
        try:
            process.start();sender.close()
            if not receiver.poll(120):raise TimeoutError('Project JSON reader timed out')
            ok,value=receiver.recv()
            if not ok:raise ValueError(f'{value[0]}: {value[1]}')
            return value
        finally:
            receiver.close();sender.close()
            if process.pid is not None:
                process.join(1)
                if process.is_alive():process.terminate();process.join(2)
                process.close()

def read_payload(path):
    key=identity(path)
    with _lock:
        entry=_entries.get(key)
        if entry is not None:
            _entries.move_to_end(key);_stats['hits']+=1
        future=_flights.get(key)
        owner=entry is None and future is None
        if owner:future=_flights[key]=Future();_stats['misses']+=1
        elif entry is None:_stats['joined']+=1
    if entry is not None:return _thaw(entry[0])
    if not owner:return _thaw(future.result())
    try:
        if key[3]>=4*1024*1024:
            frozen,phases=_read_large(path)
            started=time.perf_counter();payload=_thaw(frozen)
            phases['materialize_ms']=(time.perf_counter()-started)*1000
            with _lock:_stats['last_large_read']=phases
        else:
            with Path(path).open('rb') as stream:
                payload=json.load(stream)
            frozen=_freeze(payload)
        if identity(path)!=key:raise OSError('Project changed while reading; reopen its current version')
        if not isinstance(payload,dict):raise ValueError('Expected project object')
        size=sum(len(rows) if kind=='value' else sum(len(blob) for _,blob in rows) for kind,rows in frozen.values())
        with _lock:
            _stats['reads']+=1
            limit=budget()
            for old in list(_entries):
                if old[0]==key[0]:
                    _stats['bytes']-=_entries.pop(old)[1];_stats['evictions']+=1
            if size<=limit:_entries[key]=(frozen,size);_stats['bytes']+=size
            while _entries and _stats['bytes']>limit:
                _,(_,released)=_entries.popitem(last=False);_stats['bytes']-=released;_stats['evictions']+=1
            future.set_result(frozen)
        return payload
    except BaseException as exc:
        future.set_exception(exc);raise
    finally:
        with _lock:_flights.pop(key,None)

def clear():
    with _lock:
        _entries.clear();_parked.clear();_stats['bytes']=0

def trim():
    """Idle pressure recovery; called only on the GUI's safe collection turn."""
    limit=budget()
    with _lock:
        while _entries and _stats['bytes']>limit:
            _,(_,released)=_entries.popitem(last=False)
            _stats['bytes']-=released;_stats['evictions']+=1
        for key in list(_parked):
            if _parked[key][3]>limit*2:
                _parked.pop(key,None);_stats['evictions']+=1
