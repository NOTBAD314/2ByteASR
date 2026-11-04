"""Compare real WASAPI output to submitted PCM; never substitute one for the other."""
from pathlib import Path
import argparse,json,wave
import numpy as np

def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    folder=args.directory
    source=np.fromfile(folder/'device-submission.s16le',dtype='<i2').reshape(-1,2).mean(axis=1)/32768
    with wave.open(str(folder/'wasapi-loopback.wav'),'rb') as wav:
        recorded=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').reshape(-1,wav.getnchannels()).mean(axis=1)/32768
        sample_rate=wav.getframerate()
    # Correlate only the onset to establish device latency; FFT avoids O(n*m).
    from scipy.signal import correlate, correlation_lags
    factor=8;ref=source[:sample_rate*3:factor];got=recorded[:sample_rate*12:factor]
    corr=correlate(got,ref,method='fft');lags=correlation_lags(len(got),len(ref))
    offset=int(lags[int(np.argmax(corr))])*factor
    rows=[]; tracked_shift=0
    for seconds in range(0,len(source)//sample_rate,5):
        begin=seconds*sample_rate;ref=source[begin:begin+sample_rate]
        target=begin+offset+tracked_shift
        if target<0 or target+len(ref)>len(recorded):continue
        got=recorded[target:target+len(ref)]
        # Find bounded slow device drift separately from gaps/repeated content.
        search_start=max(0,target-2400)
        local=recorded[search_start:min(len(recorded),target+len(ref)+2400):factor]
        c=correlate(local,ref[::factor],mode='valid',method='fft')
        shift=int(np.argmax(c))*factor+search_start-target
        choices=[i for i in range(shift-factor,shift+factor+1) if
                 target+i>=0 and target+i+len(ref)<=len(recorded)]
        if choices:
            shift=max(choices,key=lambda i:np.dot(ref,recorded[target+i:target+i+len(ref)]))
        aligned=recorded[target+shift:target+shift+len(ref)]
        if len(aligned)!=len(ref):continue
        rms=float(np.sqrt(np.mean(ref**2)))
        similarity=float(np.corrcoef(ref,aligned)[0,1]) if rms>.00001 else None
        total_shift=tracked_shift+shift
        if similarity is not None and similarity>.7:tracked_shift=total_shift
        rows.append({'seconds':seconds,'shift_ms':total_shift*1000/sample_rate,
            'correlation':similarity,
            'submitted_rms':rms,'loopback_rms':float(np.sqrt(np.mean(aligned**2))),
            'loopback_silence_fraction':float(np.mean(abs(aligned)<1/32768))})
    result={'sample_rate':sample_rate,'submitted_seconds':len(source)/sample_rate,
        'recorded_seconds':len(recorded)/sample_rate,'initial_offset_ms':offset*1000/sample_rate,
        'windows':rows,'interpretation':'Correlation measures device-output correspondence; human listening remains a separate gate.'}
    (folder/'loopback-analysis-v2.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='windows'}))
    if rows:print('window correlations',min(x['correlation'] for x in rows if x['correlation'] is not None))

if __name__=='__main__':main()
