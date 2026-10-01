"""Disposable transparent cue proxies. HTML remains the source of truth.

One bounded background renderer, atomic complete sequences, absolute cue-time
sampling. No proxy path is serialized into a project or an adopted theme.
"""
from collections import OrderedDict
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid

VERSION = 'caption-proxy-2'
FPS = 30
MAX_CUE_MS = 15000
MAX_DISK_BYTES = 512 * 1024 * 1024


def quality_name(value):
    return {'low':'draft','draft':'draft','medium':'standard','balanced':'standard',
            'auto':'standard','high':'full','full':'full','standard':'standard'}.get(str(value), 'standard')


def with_quality(prepared, quality):
    """Private presentation copy; never write a quality tier into author source."""
    quality = quality_name(quality)
    if 'noita-caption-1' not in prepared.html or quality == 'full':
        return prepared
    rule = ('.nt-dust,.nt-grain{visibility:hidden!important}' if quality == 'draft' else
            '.nt-mote-4,.nt-mote-5{visibility:hidden!important}')
    markup = prepared.html.replace('</head>', '<style>'+rule+'</style></head>', 1)
    return replace(prepared, html=markup,
                   theme_key=prepared.theme_key+'-'+quality, strip_key=prepared.strip_key+'-'+quality)


@lru_cache(maxsize=1)
def runtime_digest():
    from .runtime_paths import detect_install_root
    root = Path(detect_install_root())
    paths = ['renderer/service.mjs','renderer/src/webThemeMotion.js','renderer/src/webThemeClock.js','renderer/package-lock.json']
    h = hashlib.sha256(VERSION.encode())
    for name in paths:
        h.update((root/name).read_bytes())
    return h.hexdigest()


def proxy_key(prepared, width, height):
    # HTML contains the exact bundled font bytes and compiled theme runtime.
    payload = [VERSION, runtime_digest(), hashlib.sha256(prepared.html.encode()).hexdigest(),
               prepared.strip_key, prepared.text, prepared.speaker, prepared.duration,
               prepared.placement, int(width), int(height), FPS]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def eligible(prepared):
    # Pure cue-local MotionSpec uses only absolute cue time. Stage-dependent
    # scenes and autonomous CSS animations retain the live route.
    return bool(prepared.explicit_motion and prepared.proxy_safe
                and .05 <= prepared.duration <= MAX_CUE_MS/1000
                and 'data-noita-stage-dependent' not in prepared.html)


class CaptionProxyStore:
    def __init__(self, root=None, *, service_factory=None):
        if root is None:
            from .studio_project import studio_data_root
            root = studio_data_root()/'caption-proxies-v1'
        self.root = Path(root).resolve()
        self._factory = service_factory
        self._lock = threading.RLock()
        self._jobs = queue.Queue(maxsize=8)
        self._pending = set()
        self._ready = {}
        self._failed = {}
        self._progress = {}
        self._memory = OrderedDict()
        self._memory_bytes = 0
        self._thread = None
        self.metrics = []

    def _load(self, key):
        if key in self._ready:
            return self._ready[key]
        folder = self.root/key
        try:
            data = json.loads((folder/'manifest.json').read_text('utf8'))
            count = data['frame_count']
            if data['version'] != VERSION or data['key'] != key or data['fps'] != FPS or not 1 <= count <= 450:
                return None
            if count != math.ceil(data['duration_ms']*FPS/1000) or len(data['sha256']) != count:
                return None
            if not all((folder/f'{i:04}.png').is_file() for i in range(count)):
                return None
            self._ready[key] = data
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def status(self, key):
        with self._lock:
            if key in self._failed: return 'failed'
            if self._load(key): return 'ready'
            return 'building' if key in self._pending else 'missing'

    def ensure(self, prepared, width, height, *, cancel_check=lambda:False):
        if not eligible(prepared): return None
        key = proxy_key(prepared,width,height)
        with self._lock:
            if self.status(key) in ('ready','building','failed'): return key
            try:
                self._jobs.put_nowait((key,prepared,int(width),int(height),cancel_check))
            except queue.Full:
                return key  # LIVE continues; a later configuration may enqueue it.
            self._pending.add(key)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run,daemon=True,name='caption-proxy-builder')
                self._thread.start()
        return key

    def progress(self, key):
        with self._lock:
            return self.status(key),self._progress.get(key,(0,0))

    def frame_at(self, key, cue_ms):
        with self._lock:
            data = self._load(key)
            if data is None or key in self._failed or not 0 <= cue_ms < data['duration_ms']:
                return None
            index = min(data['frame_count']-1, int(cue_ms*FPS/1000))
            cache_key = (key,index)
            png = self._memory.get(cache_key)
            if png is not None:
                self._memory.move_to_end(cache_key)
                return png,index*1000/FPS
            try:
                png = (self.root/key/f'{index:04}.png').read_bytes()
                if hashlib.sha256(png).hexdigest() != data['sha256'][index]:
                    raise ValueError('透明代理帧校验失败')
            except (OSError,ValueError) as exc:
                self._failed[key] = str(exc)
                self._ready.pop(key,None)
                return None
            self._memory[cache_key] = png
            self._memory_bytes += len(png)
            while self._memory_bytes > 32*1024*1024 and len(self._memory)>1:
                _, old = self._memory.popitem(last=False)
                self._memory_bytes -= len(old)
            return png,index*1000/FPS

    def _run(self):
        service = None
        try:
            while True:
                try:
                    job = self._jobs.get(timeout=1)
                except queue.Empty:
                    # Clearing under the same lock as ensure prevents a stranded job.
                    with self._lock:
                        if self._jobs.empty():
                            self._thread = None
                            return
                    continue
                key,prepared,width,height,cancel = job
                staging = self.root/('.pending-'+key+'-'+uuid.uuid4().hex[:8])
                started = time.perf_counter()
                try:
                    if cancel(): continue
                    self.root.mkdir(parents=True,exist_ok=True)
                    used = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
                    if used >= MAX_DISK_BYTES:
                        raise ValueError('代理缓存已到512MiB上限，继续HTML预览')
                    if service is None:
                        from .renderer_service import RendererService
                        service = self._factory() if self._factory else RendererService()
                    staging.mkdir()
                    service.live_set(prepared.html,width=width,height=height)
                    service.live_text(text=prepared.text,speaker=prepared.speaker,duration_ms=prepared.duration*1000,placement=prepared.placement)
                    count = math.ceil(prepared.duration*FPS)
                    with self._lock:self._progress[key]=(0,count)
                    hashes = []
                    for index in range(count):
                        if cancel(): raise InterruptedError('代理任务已退出')
                        ms = index*1000/FPS
                        png = service.live_frame(cue_ms=ms,stage_ms=ms)
                        used += len(png)
                        if used > MAX_DISK_BYTES: raise ValueError('代理缓存预算已用完，继续HTML预览')
                        (staging/f'{index:04}.png').write_bytes(png)
                        hashes.append(hashlib.sha256(png).hexdigest())
                        with self._lock:self._progress[key]=(index+1,count)
                    data = dict(version=VERSION,key=key,fps=FPS,frame_count=count,duration_ms=prepared.duration*1000,
                                width=width,height=height,sha256=hashes,source_key=prepared.strip_key)
                    (staging/'manifest.json').write_text(json.dumps(data,sort_keys=True),'utf8')
                    if cancel(): raise InterruptedError('代理任务已退出')
                    final = self.root/key
                    if not final.exists(): staging.rename(final)
                    with self._lock:
                        if self._load(key) is None:
                            raise ValueError('代理未完整发布，继续HTML预览')
                    self.metrics.append(dict(key=key,phase='build',duration_ms=(time.perf_counter()-started)*1000,frames=count))
                    del self.metrics[:-100]
                except InterruptedError:
                    pass
                except Exception as exc:
                    with self._lock: self._failed[key]=str(exc)
                finally:
                    # Only delete this job's own unpublished, explicitly contained directory.
                    if staging.exists() and staging.resolve().parent == self.root and staging.name.startswith('.pending-'):
                        import shutil
                        shutil.rmtree(staging)
                    with self._lock: self._pending.discard(key)
                    self._jobs.task_done()
        finally:
            if service is not None: service.shutdown()


_store = None
_store_lock = threading.Lock()


def proxy_store():
    global _store
    with _store_lock:
        if _store is None: _store = CaptionProxyStore()
        return _store
