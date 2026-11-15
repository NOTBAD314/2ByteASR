"""Explicit, out-of-process legacy CTC comparison; never imported by production."""
import argparse,json,os,sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy-source',type=Path,required=True)
    p.add_argument('--suite',type=Path,required=True)
    p.add_argument('--payload',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--models',type=Path,required=True)
    a=p.parse_args();legacy=a.legacy_source.resolve(strict=True);output=a.output.resolve()
    if output.exists():raise ValueError('Use a fresh output path')
    if not (legacy/'ctc_aligner_worker.py').is_file() or not (legacy/'twobyteasr/recognition/ctc_alignment.py').is_file():
        raise ValueError('The explicitly selected legacy source has no complete CTC implementation')
    output.parent.mkdir(parents=True,exist_ok=True)
    profile=output.parent/'legacy-ctc-profile';profile.mkdir(exist_ok=True)
    for key,leaf in [('LOCALAPPDATA','local'),('APPDATA','roaming'),('TEMP','temp'),('TMP','temp')]:
        folder=profile/leaf;folder.mkdir(exist_ok=True);os.environ[key]=str(folder)
    os.environ.update(PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TWOBYTEASR_DEVELOPER_RUNTIMES='1',TWOBYTEASR_MAIN_PYTHON=sys.executable)
    os.environ['2BYTEASR_MODEL_ROOT']=str(a.models.resolve())
    os.environ['2BYTEASR_JA_CTC_ALIGNER_DIR']=str(a.models.resolve()/'wav2vec2-large-xlsr-53-japanese')
    # The caller must launch this script in a separate interpreter. There are no
    # application imports before the explicit predecessor is selected.
    sys.path.insert(0,str(legacy))
    import numpy as np
    from twobyteasr.recognition import asr
    asr.SCRIPT_DIR=str(legacy)
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.acceptance.alignment_comparison import apply_production_ctc
    suite=json.loads(a.suite.read_text('utf8'));payload=json.loads(a.payload.read_text('utf8'));payload=payload.get('payload',payload)
    audio=np.load(a.suite.resolve().parent/suite['audio'],mmap_mode='r');context=RuntimeContext()
    try:
        with activate_runtime_context(context):times,events=apply_production_ctc(suite['samples'],payload,audio)
    finally:context.close_resources()
    output.write_text(json.dumps(dict(kind='explicit legacy offline reference; not production or gold truth',legacy_source=str(legacy),times=times,events=events),ensure_ascii=False,indent=2),'utf8')


if __name__=='__main__':main()
