"""Read credentials without mutation; audit authorized task audio on its provider."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--mode", choices=("inspect","full","chunks","flash","filetrans"), default="inspect")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Audit output must stay in workspace tmp")
    out.mkdir(parents=True, exist_ok=True)
    from twobyteasr.llm_config import read_asr_api_key
    flash = args.mode == "flash"
    provider = "dashscope_qwen_audio" if flash else "openrouter"
    url = ("https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation" if flash
           else "https://openrouter.ai/api/v1/audio/transcriptions")
    key, source = read_asr_api_key(provider, url)
    endpoint = {"provider":provider, "url":url,"api_key":key,
        "protocol":"dashscope_multimodal" if flash else "openrouter_verbose_json",
        "model":"qwen-audio-3.0-asr-flash" if flash else "microsoft/mai-transcribe-2",
        "style":"verbatim", "audit_root":str(out)}
    storage=None
    if args.mode == 'filetrans':
        from twobyteasr import settings
        from twobyteasr.temp_audio_storage import oss_storage_from_settings
        user_root=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'2ByteASR'
        raw=json.loads((user_root/'2byteasr_settings.json').read_text(encoding='utf-8'))
        config,_=settings._merge_known_settings(settings.DEFAULT_SETTINGS,raw)
        config['models']['oss_auto_delete']=True
        storage=oss_storage_from_settings(config)
        provider='qwen_filetrans'
        url='https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription'
        key,source=read_asr_api_key(provider,url)
        endpoint.update(provider=provider,url=url,api_key=key,protocol='dashscope_filetrans',model='qwen-audio-3.0-asr-flash-filetrans')
    metadata = {"provider":provider,"model":endpoint["model"],"key_available":bool(key),
        "key_source":source,"audio":str(args.audio.resolve()),"mode":args.mode}
    print(json.dumps(metadata,ensure_ascii=False),flush=True)
    if args.mode == "inspect" or not key:
        return
    os.environ.update(LOCALAPPDATA=str(out/"local"),APPDATA=str(out/"roaming"))
    os.environ["2BYTEASR_USER_DATA_ROOT"] = str(out/"data")
    from twobyteasr import settings
    settings.stable_settings_root = lambda: out/"config"
    import numpy as np
    from twobyteasr.asr import call_qwen_asr_api, _api_transcription_rows
    from twobyteasr.speaker_evidence import scope_request_speakers
    with wave.open(str(args.audio), "rb") as wav:
        assert wav.getframerate() == 16000 and wav.getnchannels() == 1
        pcm = np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2").astype(np.float32)/32768
    step = 10*16000 if args.mode == "chunks" else len(pcm)
    chunks = [(i,pcm[i:i+step]) for i in range(0,len(pcm),step)]
    all_rows = []
    started = time.perf_counter()
    if args.mode == 'filetrans':
        import subtitle_core
        subtitle_core.RUNTIME_SETTINGS=config
        from twobyteasr.asr import _transcribe_qwen_filetrans
        all_rows=_transcribe_qwen_filetrans(str(args.audio.resolve()),pcm,endpoint=endpoint,storage=storage)
        metadata.update(elapsed_seconds=time.perf_counter()-started,request_count=1,audio_seconds=len(pcm)/16000,
            rows=all_rows,labels=sorted({r.get('speaker','') for r in all_rows}),human_reference_available=False)
        (out/'comparison.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    for index,(offset,audio) in enumerate(chunks):
        ep = dict(endpoint,audit_request=f"request-{index:03d}")
        result = call_qwen_asr_api(audio,"",endpoint=ep)
        chunk = {"start":offset/16000,"end":(offset+len(audio))/16000}
        rows = _api_transcription_rows(result if isinstance(result,dict) else {"text":result},chunk)
        all_rows.extend(scope_request_speakers(rows,index,len(chunks)))
        print(f"request={index+1}/{len(chunks)} rows={len(rows)}",flush=True)
    metadata.update(elapsed_seconds=time.perf_counter()-started,request_count=len(chunks),
        audio_seconds=len(pcm)/16000,rows=all_rows,labels=sorted({r.get('speaker','') for r in all_rows}),
        human_reference_available=False)
    (out/"comparison.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
