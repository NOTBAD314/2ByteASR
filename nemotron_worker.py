"""Optional Python3.12 worker. Never downloads weights or imports into the GUI."""
import json
import hashlib
import importlib.metadata
import sys
from pathlib import Path


def main():
    def event(state, **details):
        print('[2BYTEASR_SPEAKER] '+json.dumps(dict(state=state,backend='nemotron',**details)),flush=True)
    root=Path(__file__).resolve().parent
    if root.name=='workers':root=root.parent
    sys.path.append(str(root))
    request=json.loads(sys.stdin.read())
    event('loading')
    import numpy as np
    import torch
    from transformers import AutoProcessor,AutoModelForAudioFrameClassification
    from twobyteasr.nemotron_stream import probabilities,MODE,MODEL_REVISION,RUNTIME_REVISION
    audio=np.load(request['audio_array'],mmap_mode='r')
    if audio.ndim!=1 or not np.isfinite(audio).all():raise ValueError('统一分析音频非法')
    processor=AutoProcessor.from_pretrained(request['model_path'],local_files_only=True)
    processor.set_streaming_mode(MODE)
    if processor.feature_extractor.sampling_rate!=16000:raise ValueError('Nemotron 采样率契约不匹配')
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=AutoModelForAudioFrameClassification.from_pretrained(request['model_path'],local_files_only=True)
    model.to(device).eval()
    event('loaded',device=device,total_seconds=len(audio)/16000)
    # A disk-backed array bounds memory even for hours of analysis audio.
    target=Path(request['probabilities']);pending=target.with_suffix('.pending.npy')
    max_frames=len(audio)//processor.feature_extractor.hop_length+1
    result=np.lib.format.open_memmap(pending,mode='w+',dtype='float32',shape=(max_frames,8))
    count=0;chunks=[]
    frame_step=processor.feature_extractor.hop_length/processor.feature_extractor.sampling_rate
    for origin,values in probabilities(audio,processor,model,torch,observe=chunks.append):
        result[origin:origin+len(values)]=values;count=origin+len(values)
        if origin%7200==0:event('analyzing',processed_start=origin*frame_step,processed_end=count*frame_step,total_seconds=len(audio)/16000)
    result.flush();del result
    # Unused capacity is excluded by frame_count; no synthetic tail activity.
    pending.replace(target)
    payload=dict(frame_count=count,frame_step_seconds=frame_step,
                 device=device,probabilities=str(target),mode=MODE,
                 contract=dict(activation='sigmoid exactly once', channels=8,
                    encoder_step_seconds=frame_step*processor.subsampling_factor,
                    output_step_seconds=frame_step, chunks=chunks,
                    final_unscored_samples=max(0,len(audio)-round(count*frame_step*16000))),
                 audio=dict(path=str(Path(request['audio_array']).resolve()),
                    sha256=hashlib.sha256(np.asarray(audio,dtype='<f4').tobytes()).hexdigest(),
                    samples=len(audio),sample_rate=16000,channels=1,duration=len(audio)/16000),
                 versions=dict(model_revision=MODEL_REVISION,runtime_revision=RUNTIME_REVISION,
                    python=sys.version,torch=torch.__version__,cuda=torch.version.cuda,
                    transformers=importlib.metadata.version('transformers')))
    output=Path(request['output']);temporary=output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload),'utf8');temporary.replace(output)
    event('analyzed',processed_start=0,processed_end=count*payload['frame_step_seconds'],frame_count=count)


if __name__=='__main__':main()
