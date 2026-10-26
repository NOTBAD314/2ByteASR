"""Private persistent QC process. Heavy Python rules never share the GUI GIL.

The length-prefixed pickle protocol is ONLY between this app and its own child
over inherited anonymous pipes; it is never used for files or network input.
"""
from __future__ import annotations
import pickle
import struct
import sys
import time

MAX_PACKET=64*1024*1024

def write_packet(stream, value):
    payload=pickle.dumps(value,protocol=5)
    if len(payload)>MAX_PACKET:raise ValueError('QC snapshot exceeds bounded packet capacity')
    stream.write(struct.pack('<I',len(payload)));stream.write(payload);stream.flush()

def read_packet(stream):
    header=stream.read(4)
    if not header:raise EOFError('QC process pipe closed')
    if len(header)!=4:raise EOFError('incomplete QC header')
    length=struct.unpack('<I',header)[0]
    if length>MAX_PACKET:raise ValueError('invalid QC packet size')
    data=bytearray()
    while len(data)<length:
        part=stream.read(length-len(data))
        if not part:raise EOFError('incomplete QC payload')
        data.extend(part)
    return pickle.loads(data)

def evaluate(snapshot, config, terminology):
    from ..projects.studio_project import SubtitleProject
    from .studio_qc import SubtitleQCEngine
    began=time.perf_counter()
    project=SubtitleProject.from_dict(snapshot.to_payload(),owned=True)
    result=SubtitleQCEngine(config).analyze(project,terminology=terminology)
    return {'result':result,'compute_ms':(time.perf_counter()-began)*1000}

def main():
    source=sys.stdin.buffer;target=sys.stdout.buffer
    while True:
        try:request=read_packet(source)
        except EOFError:return 0
        try:response=evaluate(*request)
        except Exception as error:response={'error':f'{type(error).__name__}: {error}'}
        write_packet(target,response)

if __name__=='__main__':raise SystemExit(main())
