"""Actual Qt sink + WASAPI output loopback, never a mocked playback clock."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import warnings
import wave


def tone_analysis(actions, chunks, *, has_resume=True):
    """Identify the fixture's pure carriers, excluding unrelated desktop sound.

    10ms contains an integer number of each carrier's cycles. At least 65% of
    window power and amplitude > .08 must belong to the known tone; raw RMS
    alone would count another application's speech as delayed pause output.
    """
    import numpy as np
    times=np.array([stamp for stamp,_ in chunks])
    samples=np.stack([data.mean(axis=1) for _,data in chunks])
    samples=samples-samples.mean(axis=1,keepdims=True)
    rms=np.sqrt(np.mean(samples*samples,axis=1))
    spectrum=np.abs(np.fft.rfft(samples,axis=1))*2/samples.shape[1]
    carriers={hz:(spectrum[:,hz//100]>.08)&(spectrum[:,hz//100]**2/(2*np.maximum(rms*rms,1e-12))>.65)
              for hz in (600,900,1200,1800)}
    measures={}
    for index,event in enumerate(actions):
        end=actions[index+1]["time"] if index+1<len(actions) else float("inf")
        hz=1800 if event["name"]=="capture_control" else 900 if event["name"]=="rapid_C" else 1200 if event["name"]=="loading_B" else 600
        selected=times[(times>=event["time"])&(times<end)&carriers[hz]]
        measures[event["name"]]={"carrier_hz":hz,"first_ms":round((selected[0]-event["time"])*1000,1) if len(selected) else None,
                                 "last_ms":round((selected[-1]-event["time"])*1000,1) if len(selected) else None}
    by_name={event["name"]:event["time"] for event in actions}
    first_window=(times>=by_name["first_A"])&(times<by_name["repeat_A_0"])
    settled=(times>=by_name["rapid_C"]+.2)&(times<by_name["rapid_C"]+1.5)
    loading_window=(times>=by_name["pause_loading"])&(times<by_name["rapid_A"])
    checks={"capture_control_audible":measures["capture_control"]["first_ms"] is not None,
        "first_audible":measures["first_A"]["first_ms"] is not None,
        "no_next_sentence_carrier":not bool(np.any(first_window&carriers[1200])),
        "all_repeats_audible":all(measures[f"repeat_A_{i}"]["first_ms"] is not None for i in range(3)),
        "pause_within_100ms":all((measures[f"pause_A_{i}"]["last_ms"] or 0)<=100 for i in range(3)),
        "paused_loading_silent":not bool(np.any(loading_window&(carriers[600]|carriers[900]|carriers[1200]))),
        "last_selected_only_after_settle":bool(np.any(settled&carriers[900])) and not bool(np.any(settled&(carriers[600]|carriers[1200]))),
        "all_resumes_audible":all(measures.get(f"resume_A_{i}",{}).get("first_ms") is not None for i in range(3)) if has_resume else None}
    first_carrier_ms=int(np.count_nonzero(first_window&carriers[600]))*10
    checks["whole_caption_tail_preserved"]=1980<=first_carrier_ms<=2020
    return {"method":"known-carrier >=65% power, amplitude >.08; 10ms windows; preserves raw loopback", "measures":measures,"checks":checks,
            "first_carrier_ms":first_carrier_ms,"passed":all(v for v in checks.values() if v is not None)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/"tmp"):
        parser.error("output must be a fresh directory within repository tmp")
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/"profile"), QT_QPA_PLATFORM="windows")
    # This module can be imported before CLI arguments are available. Install
    # the boundary explicitly before importing *any* owning runtime modules.
    from ..test_isolation import install, require_isolated_paths
    install()
    paths = require_isolated_paths("proofread-audio-output", emit=lambda _message: None)
    (out/"isolation.json").write_text(json.dumps({k:str(v) for k,v in paths.items()},indent=2),"utf-8")
    if args.baseline:
        baseline = args.baseline.resolve()
        if not baseline.is_relative_to(root/"tmp"):
            parser.error("baseline must be a preserved source snapshot within tmp")
        for name in ("playback.cue_audio_preview", "glossary.glossary_proofread"):
            full = "twobyteasr."+name
            spec = importlib.util.spec_from_file_location(full, baseline/"twobyteasr"/(name.replace(".", "/")+".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[full] = module
            spec.loader.exec_module(module)
    import numpy as np
    import soundcard as sc
    from PySide6.QtWidgets import QApplication
    from ..glossary.glossary_proofread import CuePlayer
    from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue

    rate = 48000
    t = np.arange(rate*8)/rate
    hz = np.select([t<2, t<4, t<6], [600, 1200, 900], default=1500)
    pcm = (np.sin(2*np.pi*hz*t)*7000).astype("<i2")
    media = out/"adjacent.wav"
    with wave.open(str(media), "wb") as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(rate)
        stream.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())
    project = SubtitleProject(StudioMedia(str(media), duration_ms=8000), cues=[
        StudioCue("A", 0, 2000, "啊 属性减一"), StudioCue("B", 2000, 4000, "那还……"),
        StudioCue("C", 4000, 6000, "第三句")], render_settings={"_cue_domain": "timeline"})
    project.validate()
    app = QApplication.instance() or QApplication([])
    player = CuePlayer()
    actions, states, chunks, errors, capture_warnings = [], [], [], [], []
    stopped, ready = threading.Event(), threading.Event()
    epoch = time.perf_counter()

    def capture():
        try:
            device = sc.get_microphone(sc.default_speaker().id, include_loopback=True)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with device.recorder(samplerate=rate, channels=2, blocksize=480) as recorder:
                    ready.set()
                    while not stopped.is_set():
                        data = recorder.record(numframes=480)
                        chunks.append((time.perf_counter()-epoch, data.copy()))
                capture_warnings.extend(str(w.message) for w in caught)
        except Exception as exc:
            errors.append(repr(exc)); ready.set()

    thread = threading.Thread(target=capture, daemon=True)
    thread.start(); ready.wait(5)
    player.state_changed.connect(lambda cue, state: states.append({"time": time.perf_counter()-epoch, "cue": cue, "state": state}))
    player.failed.connect(errors.append)

    def pump(seconds):
        end = time.perf_counter()+seconds
        while time.perf_counter()<end:
            app.processEvents(); time.sleep(.002)

    def action(name, callback):
        stamp = time.perf_counter()-epoch
        callback()
        actions.append({"name": name, "time": stamp, "return_ms": (time.perf_counter()-epoch-stamp)*1000})

    try:
        pump(.4)
        action("first_A", lambda: player.play(project, "A")); pump(3.2)
        for index in range(3):
            action(f"repeat_A_{index}", lambda: player.play(project, "A")); pump(.7)
            action(f"pause_A_{index}", lambda: player.pause() if hasattr(player, "pause") else player.stop()); pump(.4)
            if hasattr(player, "resume"):
                action(f"resume_A_{index}", player.resume); pump(.25)
            action(f"stop_{index}", player.stop); pump(.25)
        action("loading_B", lambda: player.play(project, "B"))
        action("pause_loading", lambda: player.pause() if hasattr(player, "pause") else player.stop()); pump(1)
        action("rapid_A", lambda: player.play(project, "A")); pump(.01)
        action("rapid_B", lambda: player.play(project, "B")); pump(.01)
        for index in range(18):
            action(f'rapid_switch_{index}', lambda cue='ABC'[index%3]: player.play(project, cue)); pump(.01)
        action("rapid_C", lambda: player.play(project, "C")); pump(2.7)
        action("leave", player.stop); pump(.3)
        # Independent WASAPI writer checks whether silence is an output fault
        # or loss in the loopback recorder itself.
        control = np.repeat((.15*np.sin(2*np.pi*1800*np.arange(rate)/rate))[:,None],2,axis=1)
        control_thread = threading.Thread(target=lambda: sc.default_speaker().play(control, samplerate=rate), daemon=True)
        action("capture_control", control_thread.start); pump(1.3); control_thread.join(2)
    finally:
        player.shutdown(); stopped.set(); thread.join(3)
    blocks = []
    for stamp, data in chunks:
        mono = data.mean(axis=1)
        spectrum = np.abs(np.fft.rfft(mono*np.hanning(len(mono))))
        blocks.append({"time": stamp, "rms": float(np.sqrt(np.mean(mono**2))), "hz": float(np.argmax(spectrum)*100)})
    measures = {}
    for index, event in enumerate(actions):
        end = actions[index+1]["time"] if index+1<len(actions) else float("inf")
        loud = [b for b in blocks if event["time"] <= b["time"] < end and b["rms"] > .01]
        measures[event["name"]] = {"first_ms": round((loud[0]["time"]-event["time"])*1000, 1) if loud else None,
                                   "last_ms": round((loud[-1]["time"]-event["time"])*1000, 1) if loud else None,
                                   "tones": sorted({b["hz"] for b in loud})}
    result = {"baseline": str(args.baseline) if args.baseline else None, "actions": actions, "states": states,
              "measures": measures, "errors": errors, "capture_warnings": capture_warnings,
              "device": str(sc.default_speaker()), "sample_block_ms": 10, "blocks": blocks,
              "limitation": "System output loopback with callback scheduling/10ms sampling uncertainty; no acoustic microphone or human listening."}
    result["raw_rms_measures"]=measures
    analysis=tone_analysis(actions,chunks,has_resume=hasattr(player,"resume")) if chunks else {"passed":False,"checks":{},"measures":{}}
    result.update(measures=analysis["measures"],checks=analysis["checks"],measurement_method=analysis.get("method"))
    result["first_carrier_ms"]=analysis.get("first_carrier_ms")
    result["passed"] = not errors and analysis["passed"]
    (out/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    np.savez_compressed(out/"loopback.npz", times=np.array([s for s, d in chunks]),
                        samples=np.concatenate([d for s, d in chunks]) if chunks else np.zeros((0,2)))
    print(json.dumps({"measures": result["measures"], "checks":result["checks"], "errors": errors,
                      "capture_warnings": len(capture_warnings)}, ensure_ascii=False, indent=2))
    return int(not result["passed"])
