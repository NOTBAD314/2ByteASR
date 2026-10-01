# SPDX-License-Identifier: GPL-3.0-only
"""Attempt native VideoToolbox with software fallback disabled, record reality."""
from __future__ import annotations
import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--ffmpeg",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    if sys.platform!="darwin" or platform.machine()!="arm64":raise SystemExit("Native Mac arm64 is required")
    output=args.output.resolve()
    if output.exists():raise SystemExit("Choose a new hardware-probe output")
    output.mkdir(parents=True)
    command=[str(args.ffmpeg),"-hide_banner","-loglevel","verbose","-f","lavfi","-i","testsrc2=s=640x360:r=25:d=1",
             "-an","-c:v","h264_videotoolbox","-allow_sw","0","-frames:v","25",str(output/"actual-hardware-encode.mp4")]
    with (output/"videotoolbox.log").open("wb") as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=45)
    encoded=output/"actual-hardware-encode.mp4"
    available=result.returncode==0 and encoded.is_file() and encoded.stat().st_size>0
    receipt={"platform":"darwin","architecture":"arm64","hardware_encode_attempted":True,
             "software_fallback_allowed":False,"hardware_encode_passed":available,"exit_code":result.returncode,
             "video_hardware_decode_verified":False,"mps_model_verified":False,
             "reason":"Actual 25-frame encode completed with VideoToolbox software fallback disabled" if available else
                      "This runner did not complete a hardware-only encode; CPU export remains the baseline"}
    (output/"result.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return 0


if __name__=="__main__":raise SystemExit(main())
