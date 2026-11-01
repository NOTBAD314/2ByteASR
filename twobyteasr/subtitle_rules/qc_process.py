"""Private persistent QC process. Heavy Python rules never share the GUI GIL.

The length-prefixed pickle protocol is ONLY between this app and its own child
over inherited anonymous pipes; it is never used for files or network input.
"""
from __future__ import annotations
import pickle
import struct
import sys
import time
import zlib

MAX_PACKET=64*1024*1024
# Keep the existing pipe budget. Long ASR projects contain large immutable
# evidence blobs; compress them on the IPC actor instead of falling back to
# full-project Python QC on the GUI thread. Expansion is bounded separately.
MAX_UNCOMPRESSED=256*1024*1024
COMPRESSED=1 << 31

def write_packet(stream, value):
    payload=pickle.dumps(value,protocol=5)
    if len(payload)>MAX_UNCOMPRESSED:raise ValueError('QC snapshot exceeds bounded expansion capacity')
    flag=0
    if len(payload)>MAX_PACKET:
        payload=zlib.compress(payload,level=1)
        flag=COMPRESSED
    if len(payload)>MAX_PACKET:raise ValueError('QC snapshot exceeds bounded packet capacity')
    stream.write(struct.pack('<I',len(payload)|flag));stream.write(payload);stream.flush()

def read_packet(stream):
    header=stream.read(4)
    if not header:raise EOFError('QC process pipe closed')
    if len(header)!=4:raise EOFError('incomplete QC header')
    packed=struct.unpack('<I',header)[0]
    compressed=bool(packed & COMPRESSED)
    length=packed & ~COMPRESSED
    if length>MAX_PACKET:raise ValueError('invalid QC packet size')
    data=bytearray()
    while len(data)<length:
        part=stream.read(length-len(data))
        if not part:raise EOFError('incomplete QC payload')
        data.extend(part)
    if compressed:
        decoder=zlib.decompressobj()
        data=decoder.decompress(data,MAX_UNCOMPRESSED+1)
        if (len(data)>MAX_UNCOMPRESSED or decoder.unconsumed_tail
                or not decoder.eof or decoder.unused_data):
            raise ValueError('invalid or oversized compressed QC packet')
    return pickle.loads(data)

def evaluate(snapshot, config, terminology):
    from ..projects.studio_project import SubtitleProject
    from .studio_qc import SubtitleQCEngine, QCResult
    began=time.perf_counter()
    project=SubtitleProject.from_dict(snapshot.to_payload(),owned=True)
    engine=SubtitleQCEngine(config)
    context=engine.build_context(project,terminology=terminology)
    result=QCResult(engine.evaluate_cues(context,context.ordered))
    # The list's calibrated source/translation issues are part of initial QC
    # preparation too. Building thousands of them in the ready callback froze
    # the GUI for seconds even though the rule scan itself was on this child.
    project._qc_result=result
    from .current_issues import prepare_issue_cache
    prepared=prepare_issue_cache(project)
    prepared['evidence_index']=context.evidence_index.compact() if context.evidence_index is not None else None
    return {'result':result,'issue_cache':prepared,'compute_ms':(time.perf_counter()-began)*1000}

def main():
    source=sys.stdin.buffer;target=sys.stdout.buffer
    while True:
        try:request=read_packet(source)
        except EOFError:return 0
        try:response=evaluate(*request)
        except Exception as error:response={'error':f'{type(error).__name__}: {error}'}
        write_packet(target,response)

if __name__=='__main__':raise SystemExit(main())
