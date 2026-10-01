# SPDX-License-Identifier: GPL-3.0-only
"""Native-host and dependency diagnostics; JSON distinguishes probes from QA."""
from __future__ import annotations
import argparse
import importlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--require-host",action="store_true")
    parser.add_argument("--probe-torch",action="store_true")
    args=parser.parse_args(argv)
    from twobyteasr.platform_macos import device_capabilities
    payload={"platform":sys.platform,"architecture":platform.machine(),"python":platform.python_version(),
             "macos":platform.mac_ver()[0],"native_arm64":sys.platform=="darwin" and platform.machine()=="arm64",
             "imports":{},"tools":{},"validation":{"app_build":False,"model":False,"studio":False,
             "physical_ime":False,"human_listening":False,"developer_id":False,"notarized":False}}
    for name in ("numpy","PySide6.QtCore","PySide6.QtMultimedia","twobyteasr.studio_mpv",
                 "twobyteasr.media_service","twobyteasr.ui","moss_firered_pipeline","subtitle_core"):
        try:
            importlib.import_module(name)
            payload["imports"][name]={"passed":True}
        except Exception as exc:
            payload["imports"][name]={"passed":False,"error_type":type(exc).__name__}
    for name in ("ffmpeg","ffprobe","mpv","node"):
        executable=shutil.which(name)
        row={"found":bool(executable),"path":executable}
        if executable:
            result=subprocess.run([executable,"--version" if name in {"mpv","node"} else "-version"],capture_output=True,text=True,timeout=20)
            row.update(exit_code=result.returncode,version=(result.stdout or result.stderr).splitlines()[:2])
            if sys.platform=="darwin":
                arch=subprocess.run(["/usr/bin/lipo","-archs",executable],capture_output=True,text=True,timeout=10)
                row["architectures"]=arch.stdout.strip()
        payload["tools"][name]=row
    torch=None
    if args.probe_torch:
        try:
            torch=importlib.import_module("torch")
            payload["torch_version"]=torch.__version__
        except ImportError: payload["torch_imported"]=False
    payload["devices"]=device_capabilities(torch)
    payload["preview"]={"backend":"Qt QMediaPlayer/QVideoSink","surface":"embedded-qt-video-sink",
                        "audio_owner":"existing independent PCM endpoint","native_preview_verified":False}
    payload["passed"]=all(x["passed"] for x in payload["imports"].values()) and (payload["native_arm64"] or not args.require_host)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"output":str(args.output),"passed":payload["passed"],"native_arm64":payload["native_arm64"]}))
    return 0 if payload["passed"] else 1


if __name__=="__main__": raise SystemExit(main())
