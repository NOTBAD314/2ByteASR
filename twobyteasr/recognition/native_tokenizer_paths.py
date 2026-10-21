"""Load validated tokenizer bytes when Windows native filename APIs fail."""
import os
from pathlib import Path


def prepare_sentencepiece_unicode_paths():
    if os.name!='nt':return
    import sentencepiece
    processor=sentencepiece.SentencePieceProcessor
    original=processor.Load
    if getattr(original,'_twobyte_unicode_paths',False):return

    def load(self,model_file=None,model_proto=None):
        if model_file and not model_proto and not str(model_file).isascii():
            # Use the library's supported in-memory API. Python opens Unicode
            # paths correctly; no renamed/copied models or modified packages.
            return original(self,model_proto=Path(model_file).read_bytes())
        return original(self,model_file=model_file,model_proto=model_proto)

    load._twobyte_unicode_paths=True
    processor.Load=load
    if processor.load is original:processor.load=load
