# SPDX-License-Identifier: GPL-3.0-only
"""Optional real CPU SenseVoice smoke; uses the existing production worker."""
from __future__ import annotations
import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--audio",type=Path,required=True)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--runtime",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    if sys.platform!="darwin" or platform.machine()!="arm64": raise SystemExit("Run this smoke on native Apple Silicon")
    if args.output.exists(): raise SystemExit("Output already exists; choose a new smoke directory")
    args.output.mkdir(parents=True)
    audio=args.audio.resolve()
    if not audio.is_file(): raise SystemExit("Explicit non-private sample is missing")
    interpreter=args.runtime.resolve()/"bin/python"
    probe=subprocess.check_output([shutil.which("ffprobe") or "ffprobe","-v","error","-show_entries","format=duration","-of","json",str(audio)],text=True,timeout=20)
    duration=float(json.loads(probe)["format"]["duration"])
    manifest=args.output/"manifest.json"
    manifest.write_text(json.dumps({"jobs":[{"segment_id":1,"path":str(audio),"start":0,"end":duration}]}),encoding="utf8")
    result=args.output/"recognized.json"
    with (args.output/"worker.log").open("wb") as stream:
        completed=subprocess.run([str(interpreter),"-I","-X","utf8",str(ROOT/"sensevoice_worker.py"),
                                  "--manifest",str(manifest),"--output",str(result),"--model-key","sensevoice",
                                  "--model-dir",str(args.model.resolve())],stdout=stream,stderr=subprocess.STDOUT,timeout=600)
    recognized=json.loads(result.read_text(encoding="utf8")) if result.exists() else {}
    valid=completed.returncode==0 and any(str(row.get("text") or "").strip() for row in recognized.get("results",[]))
    receipt={"platform":"darwin","architecture":"arm64","production_worker":"sensevoice_worker.py",
             "runtime":str(interpreter),"sample":str(audio),"model":str(args.model.resolve()),
             "exit_code":completed.returncode,"real_model_inference_passed":valid,
             "studio_full_flow_verified":False,"chinese_quality_verified":False,"mps_model_verified":False}
    if valid:
        from twobyteasr.models import SubtitleCue
        from twobyteasr.output import render_srt
        cues=[SubtitleCue(cue_id=index+1,start=float(row["start"]),end=float(row["end"]),text=str(row["text"])) for index,row in enumerate(recognized["results"]) if str(row.get("text") or "").strip()]
        # A minimal recognition smoke is separately labeled; it does not
        # stand in for UI editing, cue alignment quality or Chinese QA.
        subtitle=args.output/"recognized.srt"
        rendered=render_srt(cues)
        subtitle.write_text(rendered,encoding="utf8")
        receipt["subtitle_written"]=subtitle.is_file()
        receipt["subtitle_readback_passed"]=subtitle.read_text(encoding="utf8")==rendered and " --> " in rendered
    (args.output/"result.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return 0 if valid else 1


if __name__=="__main__": raise SystemExit(main())
