"""Objective audition comparison; source projects/cache are only read.

WAV artifacts are available for a human listening comparison. Numerical PCM
checks do not certify the perceived quality of speech or ASR timestamps.
"""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys, time, wave
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--recognition-cache',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('fresh source/tmp output required')
    out.mkdir(parents=True)
    original=args.project.read_bytes();(out/'copy.2byteproj').write_bytes(original)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    import numpy as np
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.playback.cue_audio_preview import plan_cue_preview,preview_command,preview_cache_key
    from twobyteasr.playback.recognition_audio_preview import cached_recognition_pcm
    from twobyteasr.studio.studio_video_track import ffmpeg_executable
    from twobyteasr.recognition import cache
    p=load_project(out/'copy.2byteproj');ffmpeg=str(ffmpeg_executable())
    identity=p.generation_metadata.get('media_identity') or {}
    if args.recognition_cache and identity:
        key=cache.stable_digest(identity)[:24];source=args.recognition_cache/key;dest=out/'cache'/key
        dest.mkdir(parents=True)
        for name in ('audio_meta.json','audio_16k.npy'):
            if (source/name).is_file():
                os.link(source/name,dest/name)
        cache.CACHE_ROOT=str(out/'cache')
    def wav(path,payload):
        with wave.open(str(path),'wb') as stream:
            stream.setparams((2,2,48000,0,'NONE','PCM'));stream.writeframes(payload)
    probe=Path(ffmpeg).with_name('ffprobe.exe')
    metadata=json.loads(subprocess.check_output([str(probe),'-v','error','-show_streams','-show_format','-of','json',p.media.path]))
    chosen=[]
    for needle in ('おはよう','ギリギリ','知るか','水水','なんで'):
        cue=next((c for c in p.cues if needle in c.text),None)
        if cue and cue.id not in {c.id for c in chosen}:chosen.append(cue)
    for cue in (p.cues[0],p.cues[len(p.cues)//2],p.cues[-1]):
        if cue.id not in {c.id for c in chosen}:chosen.append(cue)
    rows=[]
    for n,cue in enumerate(chosen):
        plan=plan_cue_preview(p,cue.id)
        key=preview_cache_key(plan)
        started=time.perf_counter();command,receipts=preview_command(plan,ffmpeg)
        payload=subprocess.run(command,capture_output=True,check=True).stdout
        elapsed=(time.perf_counter()-started)*1000
        wav(out/f'{n:02d}-original-graph.wav',payload)
        samples=np.frombuffer(payload,dtype='<i2').reshape(-1,2).astype(float)
        old=cached_recognition_pcm(plan)
        row=dict(cue_id=cue.id,text=cue.text,plan=plan.diagnostic(),cache_key=key,command=command,
            frames=len(samples),duration_ms=len(samples)/48,expected_ms=plan.play_range_ms[1]-plan.play_range_ms[0],
            decode_ms=elapsed,recognition_shortcut_eligible=bool(old),
            clipping_samples=int(np.sum(np.abs(samples)>=32767)))
        if old:
            wav(out/f'{n:02d}-old-recognition-shortcut.wav',old)
            prior=np.frombuffer(old,dtype='<i2').reshape(-1,2).astype(float)
            row.update(old_pcm_frames=len(prior),old_stereo_identical=bool(np.array_equal(prior[:,0],prior[:,1])),
                new_stereo_identical=bool(np.array_equal(samples[:,0],samples[:,1])),
                old_new_ncc=float(np.corrcoef(prior[:min(len(prior),len(samples)),0],samples[:min(len(prior),len(samples)),0])[0,1]))
        # Same original-media baseline as normal source playback (no ASR input).
        if len(plan.layers)==1 and plan.layers[0]['playback_rate']==1:
            layer=plan.layers[0];source=plan.diagnostic()['layers'][0]['played_source_ms']
            direct=[ffmpeg,'-v','error','-ss',f'{source[0]/1000:.6f}','-i',layer['source_path'],
                '-map',f"0:a:{layer.get('stream_index',0)}",'-t',f'{(source[1]-source[0])/1000:.6f}',
                '-ac','2','-ar','48000','-f','s16le','-']
            reference=subprocess.run(direct,capture_output=True,check=True).stdout
            wav(out/f'{n:02d}-direct-source.wav',reference)
            ref=np.frombuffer(reference,dtype='<i2').reshape(-1,2).astype(float)
            length=min(len(ref),len(samples))
            row.update(direct_ncc=float(np.corrcoef(ref[:length].ravel(),samples[:length].ravel())[0,1]),
                       direct_frames=len(ref))
        rows.append(row)
    result=dict(project_id=p.project_id,cues=len(p.cues),source_sha256=hashlib.sha256(original).hexdigest(),
        original_unchanged=args.project.read_bytes()==original,media=metadata,samples=rows,
        passed=all(row['frames']==row['expected_ms']*48 and row.get('direct_ncc',1)>.999 for row in rows),
        listening_verified=False)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],cues=len(p.cues),samples=len(rows),
        cached_old=sum(r['recognition_shortcut_eligible'] for r in rows),
        duration_errors_ms=[r['duration_ms']-r['expected_ms'] for r in rows],output=str(out)),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
