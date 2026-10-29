import hashlib
import io
import os

import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows native filename compatibility')
def test_unicode_model_matches_serialized_model_without_changing_file(tmp_path):
    spm=pytest.importorskip('sentencepiece')
    from twobyteasr.recognition.native_tokenizer_paths import prepare_sentencepiece_unicode_paths
    writer=io.BytesIO()
    spm.SentencePieceTrainer.train(sentence_iterator=iter(['hello local speech test','the weather is sunny today']),
        model_writer=writer,vocab_size=40,hard_vocab_limit=False,minloglevel=2)
    data=writer.getvalue()
    folder=tmp_path/'中文 目录';folder.mkdir()
    path=folder/'分词器.model';path.write_bytes(data)
    reference=spm.SentencePieceProcessor(model_proto=data)
    original,alias=spm.SentencePieceProcessor.Load,spm.SentencePieceProcessor.load
    try:
        prepare_sentencepiece_unicode_paths()
        actual=spm.SentencePieceProcessor()
        assert actual.Load(str(path))
        assert actual.EncodeAsIds('hello local speech')==reference.EncodeAsIds('hello local speech')
        assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(data).digest()
        with pytest.raises(ValueError):
            actual.Load(model_file=str(path),model_proto=data)
    finally:
        spm.SentencePieceProcessor.Load=original
        spm.SentencePieceProcessor.load=alias
