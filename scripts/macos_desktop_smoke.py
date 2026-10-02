# SPDX-License-Identifier: GPL-3.0-only
"""Bounded packaged native Home/Studio test; no injected ASR results or keys."""
from __future__ import annotations
import argparse
import hashlib
import shutil
import time
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def cache_snapshot(profile: Path) -> dict:
    data=profile/"local/2ByteASR"
    registration=json.loads((data/"runtimes/registry.json").read_text("utf8"))["runtimes"]["main"]
    runtime=Path(registration["root"])
    models=json.loads((data/"runtime_paths.json").read_text("utf8"))["model_root"]
    files=[runtime/"pyvenv.cfg",runtime/"pip-install.json",runtime/"managed-runtime.json"]
    folder=Path(models)/"SenseVoiceSmall"
    files.extend(path for path in folder.iterdir() if path.is_file() and not path.name.startswith("."))
    rows=[]
    for path in sorted(files):
        digest=hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda:stream.read(4*1024*1024),b""):digest.update(block)
        rows.append(dict(path=str(path),sha256=digest.hexdigest(),bytes=path.stat().st_size,
                         mtime_ns=path.stat().st_mtime_ns))
    return dict(registration=registration,files=rows)

def preserve_diagnostics(profile: Path) -> None:
    data=profile/"local/2ByteASR"
    target=profile/"runtime-evidence";target.mkdir(exist_ok=True)
    # Only logs produced inside this disposable owned profile; no global logs.
    for pattern in ('studio-open.log', 'audio-endpoint-*.log', 'subtitle-render-diagnostics.jsonl'):
        for path in (data/'logs').glob(pattern):
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 4*1024*1024))
                (target/path.name).write_bytes(stream.read())
    for path in (data/"logs/python-runtime").glob("*.json"):
        shutil.copy2(path,target/path.name)
    for path in (data/"model-readiness").glob("*.json"):
        shutil.copy2(path,target/("readiness-"+path.name))
    saved=data/"runtimes/registry.json"
    if saved.is_file():
        shutil.copy2(saved,target/"registry.json")
        registration=json.loads(saved.read_text("utf8")).get("runtimes",{}).get("main",{})
        for name in ("pyvenv.cfg","pip-install.json","managed-runtime.json","mac-native-wheels.json"):
            path=Path(registration.get("root",""))/name
            if path.is_file():shutil.copy2(path,target/name)
    # Failed attempts can precede registration. Select only small named
    # installer receipts from the known versioned main directory, never caches.
    for folder in (data/"runtimes/main").glob("macos-cpu-*"):
        for name in ("pyvenv.cfg","pip-install.json","managed-runtime.json","mac-native-wheels.json"):
            path=folder/name
            if path.is_file():shutil.copy2(path,target/(folder.name+"-"+name))

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
        try:
            result=subprocess.run([str(app/"Contents/MacOS/2ByteASR")],env=env,cwd=invoker,
                                  stdout=log,stderr=subprocess.STDOUT,timeout=1500)
        finally:
            preserve_diagnostics(output)
    workshop=json.loads((output/"workshop-result.json").read_text(encoding="utf8")) if (output/"workshop-result.json").is_file() else {}
    home=json.loads((output/"result.json").read_text(encoding="utf8")) if (output/"result.json").is_file() else {}
    restart={"passed":False,"status":"not_executed"}
    video={"passed":False,"status":"not_executed"}
    if home.get("video_output"):
        destination=Path(home["video_output"])
        ffprobe=ffmpeg.with_name("ffprobe")
        try:
            details=subprocess.run([str(ffprobe),"-v","error","-show_streams","-show_format","-of","json",str(destination)],
                capture_output=True,text=True,check=True,timeout=60)
            metadata=json.loads(details.stdout)
            with (output/"export-decode.log").open("wb") as log:
                subprocess.run([str(ffmpeg),"-v","error","-i",str(destination),"-f","null","-"],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
            streams=metadata["streams"]
            project=json.loads(Path(home["saved_project"]).read_text("utf8"))
            cue=project["cues"][0]
            frame_time=(float(cue["start_ms"])+min(300,(float(cue["end_ms"])-float(cue["start_ms"]))/2))/1000
            subprocess.run([str(ffmpeg),"-v","error","-ss",str(frame_time),"-i",str(destination),
                "-frames:v","1",str(output/"export-chinese-frame.png")],check=True,timeout=30)
            audio=subprocess.run([str(ffmpeg),"-v","error","-i",str(destination),"-vn","-f","f32le","-ac","1","-ar","16000","-"],
                capture_output=True,check=True,timeout=60).stdout
            import array
            samples=array.array("f");samples.frombytes(audio)
            audio_rms=(sum(float(value)**2 for value in samples)/max(1,len(samples)))**.5
            expected_duration=float(project["media"]["duration_ms"])/1000
            duration=float(metadata["format"]["duration"])
            duration_matches=abs(duration-expected_duration)<.2
            subtitle_paths=home.get('subtitle_artifacts',[])
            subtitle_text_verified=(len(subtitle_paths)==4 and
                {Path(p).suffix.lower() for p in subtitle_paths}=={'.srt','.ass','.txt','.json'} and
                all('实际识别后中文编辑' in Path(p).read_text('utf-8-sig') for p in subtitle_paths))
            video=dict(passed=any(s["codec_type"]=="video" for s in streams) and any(s["codec_type"]=="audio" for s in streams)
                       and duration_matches and audio_rms>1e-5 and subtitle_text_verified,status="executed",metadata=metadata,
                       expected_duration=expected_duration,duration_matches=duration_matches,audio_rms=audio_rms,
                       chinese_frame_time=frame_time,chinese_frame=str(output/"export-chinese-frame.png"),
                       subtitle_text_verified=subtitle_text_verified)
        except Exception as exc:video=dict(passed=False,status="failed",error=str(exc))
    (output/"export-validation.json").write_text(json.dumps(video,ensure_ascii=False,indent=2),encoding="utf8")
    if result.returncode==0 and workshop.get("passed") is True:
        # Reopen the normal app with the same profile and no runtime override.
        # The second audit only clicks Home Start for another real short task.
        restart_dir=output/"restart";restart_dir.mkdir()
        # Distinct media bytes/path require a fresh ASR worker, while models and
        # runtime remain registered and unchanged across the normal restart.
        second_media=output/'再起動・第二任务.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-i',str(media),'-t','10',
                        '-c:v','copy','-c:a','aac',str(second_media)],check=True,timeout=60)
        (restart_dir/"home-flow.json").write_text(json.dumps(dict(media=str(second_media),timeout=360,recognition_only=True)),encoding="utf8")
        before=cache_snapshot(output)
        reuse_env=dict(env,TWOBYTEASR_MACOS_REUSE="1")
        reuse_env.pop("TWOBYTEASR_MAIN_PYTHON",None)
        try:
            with (restart_dir/"desktop.log").open("wb") as log:
                second=subprocess.run([str(app/"Contents/MacOS/2ByteASR")],env=reuse_env,cwd=invoker,
                    stdout=log,stderr=subprocess.STDOUT,timeout=600)
            second_home=json.loads((restart_dir/"result.json").read_text("utf8")) if (restart_dir/"result.json").is_file() else {}
            after=cache_snapshot(output)
            unchanged=before==after
            restart=dict(passed=second.returncode==0 and second_home.get("passed") is True and unchanged,
                         status="executed",exit_code=second.returncode,second_task=second_home,
                         runtime_and_model_files_unchanged=unchanged,before=before,after=after,
                         environment_runtime_override=False)
        except Exception as exc:restart=dict(passed=False,status="failed",error=str(exc),before=before)
    (output/"restart-summary.json").write_text(json.dumps(restart,ensure_ascii=False,indent=2),encoding="utf8")
    preserve_diagnostics(output)
    passed=result.returncode==0 and workshop.get("passed") is True and home.get("passed") is True and restart["passed"] and video["passed"]
    (output/"desktop-summary.json").write_text(json.dumps({"passed":passed,"exit_code":result.returncode,
        "restart_reuse":restart,"export_validation":video,
        "C_gui_model_preparation":workshop.get("passed",False),"D_real_home_studio_flow":home.get("passed",False),
        "E_embedded_audio_effects":False,"F_human_and_hardware":False,
        "fixture":"Original synthetic Chinese diagnostic speech; no private speech or injected transcript",
        "fresh_end_user_runtime_bootstrap_verified":bool(args.fresh_runtime and workshop.get("passed"))},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
