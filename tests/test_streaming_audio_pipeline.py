import io
import threading
import wave
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from twobyteasr.recognition.streaming_audio import StreamingAudio,PreparedPCMReader,RATE
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
from twobyteasr.recognition.alignment_audio import prepare_audio,pcm_digest


def test_canonical_stream_bytes_and_quiet_ranges_equal_full_decode(tmp_path):
    from twobyteasr.recognition.cache import decode_audio_to_array
    from twobyteasr.providers.mosi_asr import plan_ranges
    source=tmp_path/'source.wav'
    pcm=(np.sin(np.arange(RATE*12)*.13)*12000).astype('<i2')
    with wave.open(str(source),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(RATE);stream.writeframes(pcm.tobytes())
    expected=decode_audio_to_array(source)
    context=RuntimeContext()
    with activate_runtime_context(context):
        producer=StreamingAudio(source,{'cache_dir':str(tmp_path/'cache'),'identity':{'test':'canonical'}},
            len(expected),single_seconds=1,max_seconds=4,search_seconds=.1)
        producer.start();actual=producer.complete_audio()
        assert np.array_equal(actual,expected)
        assert [(row['start'],row['end']) for row in producer.requests]==plan_ranges(expected,
            single_seconds=1,max_seconds=4,search_seconds=.1)
        producer.close()


def test_first_request_finishes_while_later_pcm_is_still_preparing(tmp_path,monkeypatch):
    from twobyteasr.system import processes
    from twobyteasr.providers import mosi_asr
    from tests.test_mosi_parallel_requests import ScriptedMosi,tiny_sleep
    from tests.test_no_cuda_cloud_asr import mosi_endpoint
    source=tmp_path/'fixture.bin';source.write_bytes(b'controlled decoder fixture')
    data=(np.sin(np.arange(RATE*60)*.1)*.2).astype('<f4').tobytes()
    release=threading.Event();first=threading.Event()
    class Pipe:
        def __init__(self):self.position=0
        def read(self,size):
            if self.position>=30*RATE*4:assert release.wait(8)
            value=data[self.position:self.position+size];self.position+=len(value)
            return value
    class Process:
        def __init__(self):self.stdout=Pipe();self.stderr=io.BytesIO();self.returncode=None
        def poll(self):return self.returncode
        def wait(self,timeout=None):self.returncode=0;return 0
        def terminate(self):self.returncode=1;release.set()
    context=RuntimeContext()
    with activate_runtime_context(context):
        producer=StreamingAudio(source,{'cache_dir':str(tmp_path/'pcm'),'identity':{'test':'delayed'}},RATE*60,
            single_seconds=5,max_seconds=20,search_seconds=1)
        monkeypatch.setattr(processes,'popen_hidden_subprocess',lambda *a,**k:Process())
        monkeypatch.setattr(processes,'stop_process_tree',lambda process:process.terminate())
        producer.start()
        reader=PreparedPCMReader(producer.spec)
        client=ScriptedMosi()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(mosi_asr.transcribe,reader,mosi_endpoint(),tmp_path/'remote',
                client=client,sleep=tiny_sleep,parallel=2,upload_parallel=2,
                on_rows=lambda index,total,rows:first.set() if index==0 else None)
            try:
                assert first.wait(5)
                assert not producer.sealed
                assert len(client.posts)>=1
                # A model can use this ready interval without hashing the
                # unfinished rest of the waveform.
                context.streaming_preparation=producer
                job=dict(id='first',window_start_ms=100,window_end_ms=500)
                spec=prepare_audio(producer.audio,tmp_path,jobs=[job])
                assert spec['sha256'] is None and spec['window_hashes']['first']==pcm_digest(producer.audio[1600:8000])
            finally:release.set()
            rows=future.result(timeout=8)
        producer.complete_audio()
        assert len(rows)==3
        assert all(abs(row['start']-(producer.requests[index]['start']/RATE+.2))<1e-6
                   for index,row in enumerate(rows))
        reader.close();producer.close();context.streaming_preparation=None
