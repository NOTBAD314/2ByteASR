"""Read a real recording project; create isolated noncontiguous audio evidence."""
import copy
import json
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
source_project = Path(sys.argv[1])
out = ROOT/"tmp/timeline-recognition-round/real-input"
out.mkdir(parents=True,exist_ok=True)
os.environ["LOCALAPPDATA"] = str(out/"local")
os.environ["APPDATA"] = str(out/"roaming")
from twobyteasr.studio_project import load_project,save_project
from twobyteasr.studio_edit_sequence import EditSequence,VideoSegment,store_sequence,timeline_duration_ms
from twobyteasr.studio_media_pool import sync_primary_video_track_from_sequence
from twobyteasr.recognition_input import capture_recognition_snapshot,prepare_recognition_input

project = load_project(source_project)
baseline = {"project": str(source_project),"media": project.media.path,
            "source_duration_ms": project.media.duration_ms,
            "timeline_duration_ms":timeline_duration_ms(project),
            "audio_tracks":[{"id":t.id,"linked":t.linked_video_track_id,
                "clips":[[c.timeline_in_ms,c.timeline_out_ms] for c in t.clips]} for t in project.audio_tracks]}
cases = {"three_minutes":[(120000,180000,0,60000),(600000,660000,60000,120000),(1200000,1260000,120000,180000)],
         "reorder_repeat_rate_gap":[(1200000,1260000,10000,70000),(120000,180000,80000,110000),
                                     (1200000,1260000,110000,170000)]}
results = []
for name,spans in cases.items():
    p = copy.deepcopy(project)
    # Fixture has a single linked A/V pair; independent authored tracks are
    # recorded above, then explicitly excluded from this controlled scenario.
    p.video_tracks = p.video_tracks[:1]
    p.audio_tracks = [t for t in p.audio_tracks if t.linked_video_track_id == p.video_tracks[0].id]
    p.av_track_groups = [g for g in p.av_track_groups if g.video_track_id == p.video_tracks[0].id]
    seq = EditSequence(source_path=p.media.path,source_duration_ms=p.media.duration_ms,video_track_locked=False,
        segments=[VideoSegment(f"audit{i}",p.media.path,*span) for i,span in enumerate(spans)])
    store_sequence(p,seq)
    sync_primary_video_track_from_sequence(p,seq)
    target = out/f"{name}.2byteproj"
    save_project(p,target)
    snapshot = capture_recognition_snapshot(p,str(target))
    wav = prepare_recognition_input(snapshot,out/"cache",ROOT/"tools/ffmpeg/bin/ffmpeg.exe")
    with wave.open(wav,"rb") as audio:
        actual = audio.getnframes()/audio.getframerate()
    results.append({"case":name,"snapshot":snapshot["fingerprint"],"input":wav,
        "duration":actual,"layers":snapshot["audio_graph"]["segments"]})
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)
(out/"evidence.json").write_text(json.dumps({"baseline":baseline,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
