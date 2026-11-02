"""One canonical FFmpeg decode; ready sample ranges can be uploaded at once.

Only committed prefixes are readable. The owned manifest carries the strong
source/decoder identity and the exact same quiet-point ranges as a full PCM
plan. Neither a remote task nor a model reads unfinished samples.
"""
from __future__ import annotations

import hashlib,json,math,os,shutil,subprocess,threading,time,uuid
from collections import deque
from fractions import Fraction
from pathlib import Path

FORMAT='ready-pcm-prefix-v1'
RATE=16000


def _save(path,data):
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(path,json.dumps(data,ensure_ascii=False))


def probe_samples(path):
    from ..system.processes import run_hidden_subprocess
    probe=shutil.which('ffprobe')
    if not probe:return None
    result=run_hidden_subprocess([probe,'-v','error','-show_entries',
        'stream=codec_type,duration_ts,time_base,duration','-of','json',str(path)],
        purpose='probe streaming PCM sample clock',capture_output=True,text=True,encoding='utf-8',timeout=20)
    if result.returncode:return None
    try:
        tracks=[row for row in json.loads(result.stdout)['streams'] if row.get('codec_type')=='audio']
        if len(tracks)!=1:return None
        row=tracks[0]
        duration=(int(row['duration_ts'])*Fraction(row['time_base']) if row.get('duration_ts') is not None
                  and row.get('time_base') else Fraction(str(row['duration'])))
        return math.ceil(duration*RATE) if duration>0 else None
    except (ValueError,KeyError,TypeError,ZeroDivisionError):return None


class _Ranges:
    def __init__(self,reader):self.reader=reader;self.known={}
    def __len__(self):return self.reader.total
    def __getitem__(self,index):
        if not 0<=index<len(self):raise IndexError(index)
        if index in self.known:return self.known[index]
        while True:
            state=self.reader.state()
            rows=state['requests']
            if index<len(rows):return int(rows[index]['start']),int(rows[index]['end'])
            self.reader.check();time.sleep(.05)
    def __iter__(self):
        for index in range(len(self)):yield self[index]


class PreparedPCMReader:
    prepared_pcm=True
    def __init__(self,spec,*,check=lambda:None):
        self.spec=spec;self.manifest=Path(spec['manifest']);self.check=check
        self.total=int(spec['total']);self.samples=int(spec['expected_samples'])
        self.job_identity=spec['job_identity'];self.ranges=_Ranges(self)
        self._array=None;self._path=None
    def __len__(self):return self.samples
    def state(self):
        self.check()
        deadline=time.monotonic()+2.
        while True:
            try:
                value=json.loads(self.manifest.read_text(encoding='utf-8'));break
            except (PermissionError,FileNotFoundError):
                if time.monotonic()>=deadline:raise
                self.check();time.sleep(.02)
        if (value.get('format')!=FORMAT or value.get('owner')!=self.spec['owner']
                or value.get('identity')!=self.job_identity):
            raise RuntimeError('音频准备任务已被替换，拒绝读取旧分片。')
        if value.get('error'):raise RuntimeError('音频准备失败：'+str(value['error'])[:300])
        return value
    def __getitem__(self,key):
        import numpy as np
        if not isinstance(key,slice) or key.step not in (None,1):raise TypeError('PCM reader requires a contiguous slice')
        start,end=int(key.start or 0),int(key.stop if key.stop is not None else self.samples)
        while True:
            value=self.state()
            if value['ready_samples']>=end or value['sealed']:break
            time.sleep(.05)
        if value['sealed']:end=min(end,int(value['actual_samples']))
        path=value['audio_path']
        if self._array is None or self._path!=path:
            # Existing views may still be in uploads; their mmap owns its
            # lifetime. Do not close a mapping behind a live request.
            self._array=np.load(path,mmap_mode='r',allow_pickle=False);self._path=path
        return self._array[start:end]

    def close(self):
        if self._array is not None:self._array._mmap.close();self._array=None


class StreamingAudio:
    def __init__(self,media,cache_context,expected_samples,*,check=lambda:None,
                 single_seconds=None,max_seconds=None,search_seconds=None):
        import numpy as np
        from ..providers.mosi_asr import SINGLE_REQUEST_SECONDS,REQUEST_MAX_SECONDS,SEAM_SEARCH_SECONDS
        self.media=Path(media);self.cache=cache_context;self.expected_samples=int(expected_samples);self.check=check
        self.root=Path(cache_context['cache_dir']);self.manifest=self.root/'streaming-audio.json'
        self.single=SINGLE_REQUEST_SECONDS if single_seconds is None else single_seconds
        self.maximum=REQUEST_MAX_SECONDS if max_seconds is None else max_seconds
        self.search=SEAM_SEARCH_SECONDS if search_seconds is None else search_seconds
        self.total=1 if expected_samples<=self.single*RATE else math.ceil(expected_samples/(self.maximum*RATE))
        self.identity=dict(format=FORMAT,media=cache_context['identity'],sample_rate=RATE,
                           decoder='ffmpeg-mono-f32le-canonical-v1')
        self.ffmpeg=shutil.which('ffmpeg') or 'ffmpeg'
        from ..system.processes import run_hidden_subprocess
        version=run_hidden_subprocess([self.ffmpeg,'-version'],purpose='identify canonical PCM decoder',
            capture_output=True,text=True,encoding='utf8',errors='replace',timeout=15)
        self.identity['decoder_build']=version.stdout.splitlines()[0] if version.stdout else ''
        self.clock_identity=hashlib.sha256(json.dumps(self.identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.owner=uuid.uuid4().hex;self.condition=threading.Condition();self.stop=threading.Event()
        self.ready_samples=0;self.actual_samples=0;self.sealed=False;self.error='';self.requests=[]
        self.process=None;self.thread=None;self.on_piece=None;self._audio_result=None
        self.retained=[]
        self.root.mkdir(parents=True,exist_ok=True)
        previous=self._previous()
        if previous:
            self.total=int(previous['total'])
            self.owner=previous['owner'];self.requests=previous['requests'];self.sealed=True
            self.actual_samples=int(previous['actual_samples']);self.ready_samples=self.actual_samples
            self.audio_path=Path(previous['audio_path']);self.audio=np.load(self.audio_path,mmap_mode='r',allow_pickle=False)
            self._writer=None
        else:
            try:
                earlier=json.loads(self.manifest.read_text(encoding='utf8'))
                if earlier.get('identity')==self.identity:
                    self.retained=list(earlier.get('requests') or [])
                    self.total=int(earlier['total'])
            except (OSError,ValueError,KeyError,TypeError):pass
            self.audio_path=self.root/f'audio-stream-{self.owner}.npy'
            # The one-second tail is storage capacity only. valid_samples
            # prevents upload/alignment/energy evidence from reading it.
            self._writer=np.lib.format.open_memmap(self.audio_path,mode='w+',dtype='float32',
                                                  shape=(self.expected_samples+RATE,))
            self.audio=np.load(self.audio_path,mmap_mode='r',allow_pickle=False)
            self._publish()
        self.spec=dict(manifest=str(self.manifest),owner=self.owner,total=self.total,
                       expected_samples=self.expected_samples,job_identity=self.identity)

    def _previous(self):
        try:
            data=json.loads(self.manifest.read_text(encoding='utf-8'))
            if data.get('identity')==self.identity and data.get('sealed') and Path(data['audio_path']).is_file():
                import numpy as np
                pcm=np.load(data['audio_path'],mmap_mode='r',allow_pickle=False)
                from .alignment_audio import pcm_digest
                valid=(pcm.dtype==np.float32 and pcm.ndim==1 and pcm.size==int(data['actual_samples'])
                       and bool(data.get('audio_sha256')) and pcm_digest(pcm)==data['audio_sha256'])
                pcm._mmap.close()
                if valid:return data
        except (OSError,ValueError,TypeError,KeyError):pass
        return None

    def _publish(self):
        _save(self.manifest,dict(format=FORMAT,identity=self.identity,owner=self.owner,total=self.total,
            expected_samples=self.expected_samples,ready_samples=self.ready_samples,actual_samples=self.actual_samples,
            audio_path=str(self.audio_path),sealed=self.sealed,error=self.error,requests=self.requests,
            audio_sha256=getattr(self,'audio_sha256',None)))

    def start(self,on_piece=None):
        self.on_piece=on_piece
        if self.sealed:
            if on_piece:
                for index,row in enumerate(self.requests):on_piece(index,int(row['start']),int(row['end']))
            return
        from .run_context import ContextExecutor
        self.pool=ContextExecutor(max_workers=1,thread_name_prefix='pcm-prefix')
        self.future=self.pool.submit(self._decode)

    def _announce(self,start,end):
        from .cache import record_run_event
        index=len(self.requests);self.requests.append(dict(start=start,end=end))
        self._writer.flush();self._publish()
        record_run_event('audio_shard_ready',request_index=index,request_total=self.total,
                         start=start/RATE,end=end/RATE,samples=end-start)
        if self.on_piece:self.on_piece(index,start,end)

    def _decode(self):
        import numpy as np
        from ..system.processes import popen_hidden_subprocess,stop_process_tree
        from ..providers.mosi_asr import _quietest_cut
        from .cache import record_run_event
        stderr=deque(maxlen=24);started=time.perf_counter()
        try:
            command=[self.ffmpeg,'-v','error','-i',str(self.media),'-vn','-ac','1','-ar',str(RATE),'-f','f32le','pipe:1']
            self.process=popen_hidden_subprocess(command,purpose='stream canonical recognition PCM',
                stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def drain():
                for line in iter(self.process.stderr.readline,b''):stderr.append(line)
            reader=threading.Thread(target=drain,daemon=True);reader.start()
            count=0;part=self.expected_samples/self.total
            search=int(min(self.search*RATE,part/4));next_edge=1;last=0
            while True:
                self.check()
                block=self.process.stdout.read(15*RATE*4)
                if not block:break
                if len(block)%4:raise RuntimeError('FFmpeg PCM sample is incomplete')
                values=np.frombuffer(block,dtype='<f4')
                if not np.isfinite(values).all():raise RuntimeError('音频包含非有限值样本。')
                if count+values.size>self._writer.size:raise RuntimeError('音轨时长与元数据不一致；未提交未知尾片。')
                self._writer[count:count+values.size]=values;count+=values.size
                with self.condition:
                    self.ready_samples=count;self.condition.notify_all()
                while next_edge<self.total:
                    target=round(next_edge*part)
                    if count<target+search:break
                    cut=(int(self.retained[next_edge-1]['end']) if next_edge-1<len(self.retained)
                         else _quietest_cut(self._writer,max(last+1,target-search),target+search,target))
                    self._announce(last,cut);last=cut;next_edge+=1
            self.process.wait(timeout=20);reader.join(timeout=2)
            if self.process.returncode:
                raise RuntimeError('FFmpeg 音频准备失败：'+b''.join(stderr).decode('utf8','replace')[-1200:])
            if not count:raise RuntimeError('音轨没有可用样本。')
            initial=self.cache['identity'];stat=self.media.stat()
            if (initial.get('size') is not None and stat.st_size!=initial['size']
                    or initial.get('mtime_ns') is not None and stat.st_mtime_ns!=initial['mtime_ns']):
                raise RuntimeError('准备过程中源媒体已变化，拒绝发布旧输入。')
            # Probe inaccuracies affect only the still-unsubmitted tail.
            while next_edge<self.total:
                target=min(count-1,round(next_edge*part))
                cut=_quietest_cut(self._writer,max(last+1,target-search),min(count,target+search),target)
                self._announce(last,cut);last=cut;next_edge+=1
            self.actual_samples=count
            self._announce(last,count)
            from .alignment_audio import pcm_digest
            self.audio_sha256=pcm_digest(self._writer[:count],check=self.check)
            final=self.root/'audio_16k.npy';temporary=self.root/f'audio-{self.owner}.sealed.npy'
            np.save(temporary,self._writer[:count],allow_pickle=False);self.check();os.replace(temporary,final)
            from .cache import CACHE_SCHEMA_VERSION,cache_stage_signature,stable_digest,atomic_write_json
            atomic_write_json(str(self.root/'audio_meta.json'),dict(schema=CACHE_SCHEMA_VERSION,created_at=time.time(),
                identity=self.cache['identity'],signature=cache_stage_signature('audio'),sample_rate=RATE,
                samples=count,dependency_hash=stable_digest(self.cache['identity'])))
            self._writer.flush();self._writer._mmap.close();self._writer=None
            # Current model views keep the immutable prefix mapping alive;
            # future ASR views can borrow the final canonical array.
            with self.condition:
                self.sealed=True;self.ready_samples=count;self.audio_path=final
                self._publish();self.condition.notify_all()
            record_run_event('audio_stream_sealed',samples=count,seconds=count/RATE,
                             elapsed_seconds=round(time.perf_counter()-started,6),requests=len(self.requests))
        except BaseException as exc:
            self.error=f'{type(exc).__name__}: {exc}'[:700]
            with self.condition:self._publish();self.condition.notify_all()
            if self.process is not None and self.process.poll() is None:stop_process_tree(self.process)
            raise

    def wait_ready(self,end):
        with self.condition:
            while self.ready_samples<end and not self.sealed and not self.error:
                self.check();self.condition.wait(.05)
            if self.error:raise RuntimeError(self.error)
            self.check()
            return min(end,self.actual_samples if self.sealed else self.ready_samples)

    @property
    def valid_samples(self):return self.actual_samples if self.sealed else self.ready_samples

    def owns(self,audio):
        import numpy as np
        if not isinstance(audio,np.memmap):return False
        root=audio
        while isinstance(getattr(root,'base',None),np.ndarray):root=root.base
        return (audio.shape==root.shape and audio.ctypes.data==root.ctypes.data
                and Path(audio.filename).parent==self.root
                and Path(audio.filename).name in {f'audio-stream-{self.owner}.npy','audio_16k.npy'})

    def complete_audio(self):
        import numpy as np
        if not self.sealed:
            while not self.future.done():self.check();time.sleep(.05)
            self.future.result()
        if self._audio_result is None:self._audio_result=np.load(self.audio_path,mmap_mode='r',allow_pickle=False)
        return self._audio_result

    def close(self):
        from ..system.processes import stop_process_tree
        self.stop.set()
        if self.process is not None and self.process.poll() is None:stop_process_tree(self.process)
        if getattr(self,'pool',None):self.pool.shutdown(wait=True,cancel_futures=True)
        if self._writer is not None:self._writer._mmap.close();self._writer=None
        if self.audio is not None:self.audio._mmap.close()
        if self._audio_result is not None:self._audio_result._mmap.close();self._audio_result=None
        # The canonical audio is retained. Only this producer's temporary
        # prefix file is eligible, after all owned consumers have joined.
        temporary=self.root/f'audio-stream-{self.owner}.npy'
        try:temporary.unlink(missing_ok=True)
        except OSError:pass
