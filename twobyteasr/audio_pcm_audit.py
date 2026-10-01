"""Opt-in device submission capture, with the normal tmp isolation guard."""
import hashlib
import json
import re
import threading
import time


class EndpointRecorder:
    def __init__(self):
        from .studio_acceptance_audit import audit_directory
        self.output = audit_directory()
        if self.output is None: raise ValueError('PCM capture requires isolated acceptance')
        from .audio_engine import _PcmRingDevice
        self.original = _PcmRingDevice.readData
        self.chunks = None
        self.raw_chunks = None
        original_mix = _PcmRingDevice._mix_output
        def mix(device, payload):
            result = original_mix(device, payload)
            if self.raw_chunks is not None:
                self.raw_chunks.append((device._generation, tuple(device._mix_ids), bytes(payload)))
            return result
        _PcmRingDevice._mix_output = mix
        def read(device, count):
            data = self.original(device, count)
            chunks = self.chunks
            if chunks is not None and data:
                chunks.append((time.perf_counter(), device._generation, bytes(data)))
            return data
        _PcmRingDevice.readData = read

    def command(self, payload):
        name = str(payload['name'])
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', name): raise ValueError('Invalid capture name')
        if payload['enabled']:
            self.chunks = []
            self.raw_chunks = []
            (self.output/f'{name}.started').write_text('ready', encoding='ascii')
        else:
            chunks, self.chunks = self.chunks or [], None
            raw_chunks, self.raw_chunks = self.raw_chunks or [], None
            def save():
                raw_rows=[]; raw_offset=0
                with (self.output/f'{name}.tracks.f32').open('wb') as raw:
                    for generation,ids,data in raw_chunks:
                        raw.write(data)
                        raw_rows.append(dict(generation=generation,ids=ids,offset=raw_offset,bytes=len(data)))
                        raw_offset+=len(data)
                (self.output/f'{name}.tracks.json').write_text(json.dumps(raw_rows),encoding='utf8')
                rows = []; offset = 0
                with (self.output/f'{name}.pcm').open('wb') as stream:
                    for wall, generation, data in chunks:
                        stream.write(data)
                        rows.append({'wall':wall,'generation':generation,'offset':offset,
                                     'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
                        offset += len(data)
                temporary=self.output/f'{name}.json.tmp'
                temporary.write_text(json.dumps(rows),encoding='utf8')
                temporary.replace(self.output/f'{name}.json')
            threading.Thread(target=save, name='audio-audit-save', daemon=True).start()


def read_capture(output, name):
    data = (output/f'{name}.pcm').read_bytes()
    rows = json.loads((output/f'{name}.json').read_text('utf8'))
    return [(x['wall'],x['generation'],data[x['offset']:x['offset']+x['bytes']]) for x in rows]
