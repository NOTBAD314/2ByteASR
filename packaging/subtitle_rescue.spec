# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import PySide6

root=Path(SPECPATH).parent
analysis=Analysis([str(root/'scripts/subtitle_rescue.py')],pathex=[str(root)],
    datas=[(str(root/'rescue-build.json'),'.'), (str(root/'assets/fonts'),'assets/fonts')],
    hiddenimports=[],
    # This tool neither recognizes nor renders media. Keep optional model and
    # browser stacks out of a recovery executable.
    excludes=['torch','transformers','torchaudio','torchvision','numpy','scipy','pandas',
              'matplotlib','cv2','PIL','tkinter','pytest','IPython','sounddevice','soundfile',
              'onnxruntime','openai','anthropic','gradio','sympy','sentencepiece','tokenizers',
              'librosa','sklearn','numba','llvmlite','av','soxr','soundcard',
              'funasr','qwen_asr','dynet','_dynet','nagisa','soynlp',
              'twobyteasr.app','twobyteasr.studio','twobyteasr.playback','twobyteasr.design',
              'twobyteasr.recognition.service','twobyteasr.rendering.advanced_renderer',
              'twobyteasr.providers'] +
             ['PySide6.'+p.stem for p in Path(PySide6.__file__).parent.glob('Qt*.pyd')
              if p.stem not in {'QtCore','QtGui','QtWidgets','QtTest'}])
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='2ByteASR-Subtitle-Rescue',
        debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
collection=COLLECT(exe,analysis.binaries,analysis.datas,strip=False,upx=False,name='2ByteASR-Subtitle-Rescue')
