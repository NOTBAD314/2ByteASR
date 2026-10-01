"""Same-source file baseline and pre-device PCM comparisons; no listening claim."""
import argparse
import json
from pathlib import Path
import sys
import wave


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mpv',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('Output must remain in tmp')
    out.mkdir(parents=True,exist_ok=True)
    import numpy as np
    from twobyteasr.processes import run_hidden_subprocess
    audit=json.loads((args.audit/'result.json').read_text('utf8'))
    result=dict(capture='Application QAudioSink callback before device',human_listening=False,
        baseline='Same source and rate, bundled mpv --no-config scaletempo2, PCM file output; not physical-device output',cases=[])
    mpv=args.mpv or root/'tools/mpv/mpv.exe'
    def metrics(audio):
        channels=[]
        for ch in audio.T:
            power=np.zeros(24001);blocks=0
            for start in range(0,len(ch)-48000,48000):
                part=ch[start:start+48000];power+=abs(np.fft.rfft(part*np.hanning(48000)))**2;blocks+=1
            bands={f'{lo}-{hi}Hz':float(power[lo:hi].sum()/max(power.sum(),1e-20)) for lo,hi in [(80,1000),(1000,4000),(4000,8000),(8000,16000)]}
            channels.append(dict(rms=float(np.sqrt(np.mean(ch**2))),peak=float(abs(ch).max()),
                clipped_fraction=float((abs(ch)>.999).mean()),bands=bands))
        return channels
    def wav(path,data):
        with wave.open(str(path),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000)
            f.writeframes((np.clip(data,-1,.999969)*32768).astype('<i2').tobytes())
    baselines={}
    for case in audit['cases']:
        if not case.get('samples'):continue
        snapshot=case['samples'][min(2,len(case['samples'])-1)]['audio']
        spec=snapshot['output_format']
        if (spec['sample_rate'],spec['channels'],spec['sample_format'])!=(48000,2,'Int16'):
            raise ValueError('Inspect actual PCM format before decoding')
        data=np.fromfile(args.audit/(case['name']+'.pcm'),dtype='<i2').reshape(-1,2).astype(np.float32)/32768
        row=dict(name=case['name'],rate=case['rate'],pcm_seconds=len(data)/48000,windows=[])
        result['cases'].append(row)
        source=snapshot['active_sources'][0]['source_path'];key=(source,case['rate'])
        if key not in baselines:
            baseline=out/f'baseline-{len(baselines)}.wav'
            command=[str(mpv),'--no-config','--load-scripts=no','--video=no','--audio-display=no','--sid=no',
                f'--speed={case["rate"]}','--audio-pitch-correction=yes','--audio-channels=stereo','--audio-samplerate=48000',
                '--audio-format=s16','--ao=pcm','--ao-pcm-waveheader=yes','--ao-pcm-file='+str(baseline),
                '--log-file='+str(baseline.with_suffix('.log')),source]
            run_hidden_subprocess(command,purpose='clean bundled mpv PCM file baseline, no device recording',
                capture_output=True,check=True,timeout=180)
            # mpv emits WAVE_FORMAT_EXTENSIBLE; Python 3.10 wave only accepts
            # the classic PCM header. Remux its unchanged samples locally.
            classic=baseline.with_name(baseline.stem+'-pcm.wav')
            run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y','-i',str(baseline),
                '-c:a','pcm_s16le','-ar','48000','-ac','2',str(classic)],
                purpose='read compatible PCM WAV header',capture_output=True,check=True,timeout=30)
            with wave.open(str(classic),'rb') as f:
                if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(2,2,48000):raise ValueError('Unexpected baseline format')
                ref=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,2).astype(np.float32)/32768
            baselines[key]=(baseline,ref,command)
        baseline,ref,command=baselines[key];row.update(baseline=str(baseline),baseline_command=command)
        # Align short RMS envelopes, limiting search to startup uncertainty.
        def envelope(x):
            x=x[:min(len(x)//480,500)*480].reshape(-1,480,2)
            return np.sqrt(np.mean(x*x,axis=(1,2)))
        a,b=envelope(data),envelope(ref);scores=[]
        for lag in range(-30,31):
            aa=a[max(0,lag):];bb=b[max(0,-lag):];n=min(len(aa),len(bb));aa=aa[:n];bb=bb[:n]
            scores.append((float(np.corrcoef(aa,bb)[0,1]) if aa.std()>1e-9 and bb.std()>1e-9 else 0.,lag))
        score,lag=max(scores);row.update(envelope_alignment_seconds=lag*.01,envelope_correlation=score)
        max_sec=min(len(data)/48000,max(0,len(ref)/48000+lag*.01))
        for label,start in [('early',2.),('late',max(2.,max_sec-7.))]:
            end=min(start+5,max_sec);a0=int(start*48000);a1=int(end*48000)
            b0=int((start-lag*.01)*48000);b1=b0+(a1-a0)
            clip=data[a0:a1];reference=ref[b0:b1]
            wav(out/(case['name']+'-'+label+'-app.wav'),clip)
            wav(out/(case['name']+'-'+label+'-mpv.wav'),reference)
            row['windows'].append(dict(label=label,output_seconds=[start,end],
                approximate_source_seconds=[start*case['rate'],end*case['rate']],app=metrics(clip),mpv=metrics(reference)))
        (out/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(cases=len(result['cases']),human_listening=False,output=str(out))))


if __name__=='__main__':main()
