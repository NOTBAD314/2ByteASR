"""Normal-entry 744-caption proofread audit on a private Windows desktop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import wave
import time
import threading
import importlib.util
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--theme", choices=("warm", "grape"), default="warm")
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--expected-gui-sha256")
    parser.add_argument("--audio-output",action="store_true")
    parser.add_argument("--audio-analyzer",type=Path)
    args = parser.parse_args()
    if args.audio_output and (args.audio_analyzer is None or not args.audio_analyzer.is_file()):
        parser.error("--audio-output requires the external host --audio-analyzer")
    if args.exe and not args.exe.is_file():parser.error("--exe must exist")
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/"tmp") or out.exists() and not args.restart:
        parser.error("use a fresh tmp directory (or --restart on this audit's directory)")
    out.mkdir(parents=True, exist_ok=True)
    profile = out/"profile"
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(profile)
    from twobyteasr.test_isolation import install,require_isolated_paths
    install();paths=require_isolated_paths("proofread-runner",emit=lambda _s:None)
    (out/"isolation-runner.json").write_text(json.dumps({k:str(v) for k,v in paths.items()},indent=2),"utf-8")
    if not args.restart:
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project
        import subtitle_core as legacy
        # SAPI produces adjacent *speech*, with lengths taken from WAV frames.
        import win32com.client
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        tokens = voice.GetVoices()
        chinese = next((tokens.Item(i) for i in range(tokens.Count)
                        if "804" in tokens.Item(i).GetAttribute("Language")), None)
        if chinese is None:
            raise RuntimeError("Chinese SAPI voice required for this adjacent speech audit")
        voice.Voice = chinese
        for filename, text in (("phrase-a.wav", "啊，属性减一。"), ("phrase-b.wav", "那还要继续测试。")):
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(str(out/filename), 3)
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()
        (out/"voice.txt").write_text(chinese.GetDescription()+" / "+chinese.GetAttribute("Language"), "utf-8")
        from twobyteasr.studio.studio_video_track import ffmpeg_executable
        ffmpeg = str(ffmpeg_executable())
        subprocess.run([ffmpeg,"-v","error","-y","-i",str(out/"phrase-a.wav"),"-i",str(out/"phrase-b.wav"),
            "-filter_complex","[0:a][1:a]concat=n=2:v=0:a=1[a]","-map","[a]","-ar","48000","-ac","2",str(out/"speech.wav")],check=True,capture_output=True)
        with wave.open(str(out/"phrase-a.wav")) as stream:
            boundary = round(stream.getnframes()/stream.getframerate()*1000)
        with wave.open(str(out/"speech.wav")) as stream:
            duration = round(stream.getnframes()/stream.getframerate()*1000)
        library = legacy.create_learned_content("校对验收词库", create_new=True)
        other = legacy.create_learned_content("来源核对库", create_new=True)
        for source, target in (("泥浆铠甲","泥浆铠甲"),("降灵","降灵"),("减益","减益"),
                               ("骨龙","骨龙"),("古龙","骨龙"),("术语甲","骨龙"),("火龙","火笼"),("NameID","NameID")):
            legacy.add_learned_mapping(library, source, target)
        legacy.add_learned_mapping(other,"降玲","降灵")
        texts = ["啊 属性减一", "那还要继续测试", "泥浆铠甲啊", "这个精灵有意思", "术语甲和火龙来了"]
        texts += ['古龙和火龙来了']*(15-len(texts))
        texts += ['啊 这 有点 有点','它 它有什么很厉害的草系技能吗','那 那就很赚','那 那古龙很赚']
        cues = [StudioCue(f"stable-{i}", i*3000, i*3000+2200,
                         texts[i] if i<len(texts) else "古龙和火龙来了", speaker_id="B" if i%2 else "A") for i in range(744)]
        cues[0].start_ms=0; cues[0].end_ms=boundary
        cues[1].start_ms=boundary; cues[1].end_ms=duration
        project = SubtitleProject(StudioMedia(str(out/"speech.wav"), duration_ms=2232000), cues=cues,
            speakers=[StudioSpeaker("A","甲"),StudioSpeaker("B","乙")], glossary_ids=[library,other],
            render_settings={"_cue_domain":"timeline"})
        project.validate(); save_project(project,out/"work.2byteproj")
        save_project(SubtitleProject(StudioMedia("")),out/"entry.2byteproj")
        (out/"fixture.json").write_text(json.dumps({"library":library,"other":other,"boundary_ms":boundary,"case_term":True,
             "duration_ms":duration,"voice_culture":(out/"voice.txt").read_text("utf-8-sig").strip(),
             "input_sha256":hashlib.sha256((out/"work.2byteproj").read_bytes()).hexdigest()},ensure_ascii=False,indent=2),"utf-8")
    if args.audio_output and not args.restart:
        import numpy as np
        rate=48000;t=np.arange(rate*8)/rate
        frequencies=np.select([t<2,t<4,t<6],[600,1200,900],default=1500)
        data=(np.sin(2*np.pi*frequencies*t)*7000).astype("<i2")
        with wave.open(str(out/"audio-probe.wav"),"wb") as stream:
            stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(rate)
            stream.writeframes(np.repeat(data[:,None],2,axis=1).tobytes())
    chunks=[];capture_errors=[];capture_warnings=[];stop=threading.Event();ready=threading.Event()
    def capture():
        try:
            import soundcard as sc
            device=sc.get_microphone(sc.default_speaker().id,include_loopback=True)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with device.recorder(samplerate=48000,channels=2,blocksize=480) as recorder:
                    ready.set()
                    while not stop.is_set():
                        data=recorder.record(numframes=480);chunks.append((time.perf_counter(),data.copy()))
                capture_warnings.extend(str(w.message) for w in caught)
        except Exception as exc:capture_errors.append(repr(exc));ready.set()
    if args.audio_output:
        capture_thread=threading.Thread(target=capture,daemon=True);capture_thread.start();ready.wait(5)
    env = {**os.environ, "TWOBYTEASR_ACCEPTANCE_SCENARIO":"proofread-audio-lexicon-batch",
           "TWOBYTEASR_ACCEPTANCE_DIR":str(out), "TWOBYTEASR_STARTUP_PROJECT":str(out/"entry.2byteproj"),
           "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD":"1", "TWOBYTEASR_INVOKER_CWD":str(ROOT),
           "TWOBYTEASR_PROOFREAD_AUDIT_RESTART":"1" if args.restart else "0",
           "TWOBYTEASR_ACCEPTANCE_THEME":args.theme, "QT_QPA_PLATFORM":"windows", "PYTHONUTF8":"1",
           "PYTHONFAULTHANDLER":"1", "PYTHONDONTWRITEBYTECODE":"1",
           "TWOBYTEASR_PROOFREAD_AUDIO_OUTPUT":"1" if args.audio_output else "0"}
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(ROOT/"quick_start.py")]
    code = run_on_desktop(command,cwd=ROOT,env=env,
                           output=out/("process-restart" if args.restart else "process"),timeout=300)
    result_path = out/("result-restart.json" if args.restart else "result.json")
    result = json.loads(result_path.read_text("utf-8")) if result_path.exists() else {"passed":False,"error":"Audit did not produce result; inspect process/stderr.log"}
    if args.audio_output:
        import numpy as np,soundcard as sc
        signal=np.repeat((.15*np.sin(2*np.pi*1800*np.arange(48000)/48000))[:,None],2,axis=1)
        control_time=time.perf_counter();sc.default_speaker().play(signal,samplerate=48000)
        time.sleep(.3);stop.set();capture_thread.join(3)
        actions=result.get("audio_actions",[])+[{"name":"capture_control","time":control_time}]
        spec=importlib.util.spec_from_file_location("proofread_audio_host",args.audio_analyzer)
        host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        analysis=host.tone_analysis(actions,chunks) if result.get("audio_actions") and chunks else {"passed":False}
        analysis.update(capture_errors=capture_errors,capture_warnings=capture_warnings)
        (out/"audio-output.json").write_text(json.dumps(analysis,ensure_ascii=False,indent=2),"utf-8")
        np.savez_compressed(out/"audio-output.npz",times=np.array([x for x,_d in chunks]),samples=np.concatenate([d for _x,d in chunks]) if chunks else np.zeros((0,2)))
        result["audio_output_passed"]=bool(analysis["passed"] and not capture_errors)
        result["passed"]=bool(result.get("passed") and result["audio_output_passed"])
    runtime=result.get("runtime",{})
    if args.exe:
        expected=args.expected_gui_sha256 or hashlib.sha256(args.exe.read_bytes()).hexdigest()
        result["identity_passed"]=bool(runtime.get("frozen") and runtime.get("exe_sha256")==expected)
        result["passed"]=bool(result.get("passed") and result["identity_passed"])
    import psutil
    pid=runtime.get("pid")
    if pid and psutil.pid_exists(pid):
        try:result["gui_exit"]=psutil.Process(pid).wait(timeout=30)
        except psutil.NoSuchProcess:result["gui_exit"]=0
        except psutil.TimeoutExpired:result["passed"]=False;result["error"]="Owned audit GUI did not close"
    result["passed"]=bool(result.get("passed") and result.get("gui_shutdown") and result.get("gui_exit",0)==0)
    result["exit_code"] = code
    (out/("result-restart.json" if args.restart else "result.json")).write_text(json.dumps(result,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps({k:result.get(k) for k in ("passed","error","exit_code","timings_ms","checks")},ensure_ascii=False,indent=2))
    return int(code!=0 or not result.get("passed"))


if __name__ == "__main__":
    raise SystemExit(main())
