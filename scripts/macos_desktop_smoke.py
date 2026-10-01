# SPDX-License-Identifier: GPL-3.0-only
"""Bounded packaged native Home/Studio test; no injected ASR results or keys."""
from __future__ import annotations
import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--app",type=Path,required=True)
    parser.add_argument("--runtime",type=Path,required=True)
    parser.add_argument("--fresh-runtime",action="store_true",help="Exercise ordinary GUI uv/Python bootstrap, not the CI build venv")
    parser.add_argument("--audio",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    if sys.platform!="darwin" or platform.machine()!="arm64":
        raise SystemExit("Native Apple Silicon desktop is required")
    output=args.output.resolve()
    if output.exists() or "tmp" not in {part.casefold() for part in output.parts}:
        raise SystemExit("Select a new absolute disposable tmp output")
    output.mkdir(parents=True)
    app=args.app.resolve()
    ffmpeg=app/"Contents/Resources/tools/ffmpeg/bin/ffmpeg"
    if not ffmpeg.is_file():
        ffmpeg=app/"Contents/Frameworks/tools/ffmpeg/bin/ffmpeg"
    media=output/"中文 字幕・日本語.mp4"
    with (output/"sample-media.log").open("wb") as log:
        subprocess.run([str(ffmpeg),"-v","warning","-f","lavfi","-i","testsrc2=s=640x360:r=30:d=12",
                        "-i",str(args.audio.resolve()),"-c:v","libx264","-pix_fmt","yuv420p",
                        "-c:a","aac","-ar","48000","-t","12",str(media)],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    (output/"home-flow.json").write_text(json.dumps({"media":str(media),"timeout":360},ensure_ascii=False),encoding="utf8")
    guard=output/"guard.2byteproj";guard.write_text("{}",encoding="utf8")
    invoker=output.parents[2]
    # Establish the existing acceptance guard without touching a CI user's
    # normal profile. The empty guard is not opened as a recognition project.
    env={key:os.environ[key] for key in ("HOME","LANG","LC_ALL","TMPDIR","DISPLAY") if key in os.environ}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin",PYTHONNOUSERSITE="1",
               TWOBYTEASR_TEST_ROOT=str(output),
               TWOBYTEASR_INVOKER_CWD=str(invoker),TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="macos-desktop",TWOBYTEASR_STARTUP_PROJECT=str(guard),
               LOCALAPPDATA=str(output/"local"),APPDATA=str(output/"roaming"))
    if not args.fresh_runtime:env["TWOBYTEASR_MAIN_PYTHON"]=str(args.runtime.resolve()/"bin/python")
    for folder in ("local","roaming","temp"):(output/folder).mkdir()
    env.update(TEMP=str(output/"temp"),TMP=str(output/"temp"))
    with (output/"desktop.log").open("wb") as log:
        result=subprocess.run([str(app/"Contents/MacOS/2ByteASR")],env=env,cwd=invoker,
                              stdout=log,stderr=subprocess.STDOUT,timeout=1500)
    workshop=json.loads((output/"workshop-result.json").read_text(encoding="utf8")) if (output/"workshop-result.json").is_file() else {}
    home=json.loads((output/"result.json").read_text(encoding="utf8")) if (output/"result.json").is_file() else {}
    passed=result.returncode==0 and workshop.get("passed") is True and home.get("passed") is True
    (output/"desktop-summary.json").write_text(json.dumps({"passed":passed,"exit_code":result.returncode,
        "C_gui_model_preparation":workshop.get("passed",False),"D_real_home_studio_flow":home.get("passed",False),
        "E_embedded_audio_effects":False,"F_human_and_hardware":False,
        "fixture":"Original synthetic Chinese diagnostic speech; no private speech or injected transcript",
        "fresh_end_user_runtime_bootstrap_verified":bool(args.fresh_runtime and workshop.get("passed"))},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
