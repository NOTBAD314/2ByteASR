"""Exercise the native SentencePiece parser with real Unicode-path files."""
import io
import os

import pytest

from sensevoice_worker import _enable_unicode_sentencepiece_paths


@pytest.fixture
def sentencepiece(monkeypatch):
    if os.name != 'nt':
        pytest.skip('Windows native path regression')
    spm = pytest.importorskip('sentencepiece')
    # Restore the optional library class after this test process finishes.
    monkeypatch.setattr(spm.SentencePieceProcessor, 'LoadFromFile', spm.SentencePieceProcessor.LoadFromFile)
    _enable_unicode_sentencepiece_paths()
    return spm


def test_real_tokenizer_loads_chinese_space_path(tmp_path, sentencepiece):
    model = io.BytesIO()
    sentencepiece.SentencePieceTrainer.train(
        sentence_iterator=iter(['hello world', 'hello subtitle', 'a different speaker']),
        model_writer=model, vocab_size=32, hard_vocab_limit=False, minloglevel=2)
    folder = tmp_path / '中文 模型目录'
    folder.mkdir()
    path = folder / '实际 tokenizer.model'
    path.write_bytes(model.getvalue())
    expected = sentencepiece.SentencePieceProcessor(model_proto=model.getvalue())
    actual = sentencepiece.SentencePieceProcessor(model_file=str(path))
    assert actual.encode('hello subtitle') == expected.encode('hello subtitle')
    assert actual.get_piece_size() == expected.get_piece_size()


def test_missing_tokenizer_still_fails(tmp_path, sentencepiece):
    with pytest.raises(FileNotFoundError):
        sentencepiece.SentencePieceProcessor(model_file=str(tmp_path / '不存在 模型.model'))
