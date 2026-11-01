"""Large real-project evidence stays on the bounded QC process transport."""
import io
import pickle
import struct
import zlib
import pytest
from twobyteasr.subtitle_rules import qc_process as protocol


def test_small_packets_keep_the_existing_wire_format():
    value={'cues':['字幕','translation'],'revision':42}
    stream=io.BytesIO();protocol.write_packet(stream,value)
    data=stream.getvalue()
    assert struct.unpack('<I',data[:4])[0]==len(data)-4
    assert protocol.read_packet(io.BytesIO(data))==value


def test_oversized_raw_evidence_roundtrips_without_raising_pipe_limit(monkeypatch):
    monkeypatch.setattr(protocol,'MAX_PACKET',1024)
    value={'evidence':b'word timestamp evidence\n'*3000,'revision':42}
    assert len(pickle.dumps(value,protocol=5))>protocol.MAX_PACKET
    stream=io.BytesIO();protocol.write_packet(stream,value)
    data=stream.getvalue();header=struct.unpack('<I',data[:4])[0]
    assert header & protocol.COMPRESSED
    assert len(data)-4<=protocol.MAX_PACKET
    assert protocol.read_packet(io.BytesIO(data))==value


def test_compressed_expansion_is_bounded_before_unpickling(monkeypatch):
    monkeypatch.setattr(protocol,'MAX_UNCOMPRESSED',4096)
    payload=zlib.compress(b'x'*100000)
    data=struct.pack('<I',len(payload)|protocol.COMPRESSED)+payload
    with pytest.raises(ValueError,match='oversized'):
        protocol.read_packet(io.BytesIO(data))


@pytest.mark.parametrize('payload',[b'invalid deflate',zlib.compress(pickle.dumps(1))[:-1],
                                    zlib.compress(pickle.dumps(1))+b'trailing'])
def test_malformed_compressed_packets_are_rejected(payload):
    stream=io.BytesIO(struct.pack('<I',len(payload)|protocol.COMPRESSED)+payload)
    with pytest.raises((ValueError,zlib.error)):
        protocol.read_packet(stream)


def test_uncompressible_or_excessive_input_remains_bounded(monkeypatch):
    monkeypatch.setattr(protocol,'MAX_UNCOMPRESSED',128)
    with pytest.raises(ValueError,match='expansion'):
        protocol.write_packet(io.BytesIO(),b'x'*1024)
