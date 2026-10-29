"""Windows filename compatibility for the pinned Qwen/nagisa dependency.

With the pinned dynet38 2.2 wheel, native parameter loading fails for a full
Unicode filename on Windows while Python can read nagisa's vocabulary there.
The worker temporarily uses the model directory and its ASCII filename;
the model bytes, package files and segmentation implementation stay unchanged.
Call only in an isolated Qwen/validation process before importing qwen_asr.
"""
from __future__ import annotations

import os
from pathlib import Path
import threading

_DIRECTORY_LOCK = threading.RLock()


def populate_native(populate, filename, *args, **kwargs):
    """Retain the exact path, restore cwd even if the native load fails."""
    path=Path(filename).absolute()
    if os.name!='nt' or str(path).isascii():
        return populate(str(path),*args,**kwargs)
    if not path.name.isascii():
        raise ValueError('原生参数文件名必须为 ASCII；nagisa 固定文件名应为 nagisa_v001.model')
    with _DIRECTORY_LOCK:
        previous=os.getcwd()
        try:
            os.chdir(path.parent)
            return populate(path.name,*args,**kwargs)
        finally:
            os.chdir(previous)


def prepare_qwen_import():
    if os.name!='nt':return
    # Same settings as nagisa.model, before the native library is initialized.
    import dynet_config
    dynet_config.set(mem=32,random_seed=1234)
    import dynet
    original=dynet.ParameterCollection
    if getattr(original,'_twobyte_unicode_filenames',False):return

    class UnicodeParameterCollection(original):
        _twobyte_unicode_filenames=True

        def populate(self,filename,*args,**kwargs):
            return populate_native(super().populate,filename,*args,**kwargs)

    dynet.ParameterCollection=UnicodeParameterCollection
    if dynet.Model is original:dynet.Model=UnicodeParameterCollection
