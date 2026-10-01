"""Actual range movies compared with preview PCM inside the audited EXE."""
import copy
from types import SimpleNamespace


def verify_audio_graph_matrix(project,ffmpeg,output):
    import numpy as np
    from .audio_graph import capture_audio_graph,preview_audio_layers
    from .audio_engine import build_audio_mix_command
    from .audio_export import audio_mix_arguments
    from .video_export import capture_video_graph
    from .studio_media_pool import set_audio_master_mode,trim_video_clip_edges
    from .studio_track_gain import gain_command
    from .processes import run_hidden_subprocess
    results={}
    for mode in ('default','positive-negative','mute','solo','linked-trim'):
        fixture=copy.deepcopy(project)
        fixture.studio_state.pop('audio_track_gain_db',None)
        fixture.studio_state.pop('audio_solo_track_ids',None)
        for track in (*fixture.video_tracks,*fixture.audio_tracks):
            track.enabled=True;track.muted=False
        set_audio_master_mode(fixture,'mix_all')
        if mode=='positive-negative':
            gain_command(fixture,'A1',6).redo();gain_command(fixture,'A2',-12).redo()
        if mode=='mute':fixture.audio_tracks[0].muted=True
        if mode=='solo':fixture.studio_state['audio_solo_track_ids']=['A2']
        if mode=='linked-trim':
            clip=fixture.video_tracks[1].clips[0]
            trim_video_clip_edges(fixture,'V2',clip.id,timeline_in_ms=250,timeline_out_ms=1250)
        contract=capture_audio_graph(fixture)
        graph=capture_video_graph(fixture)
        job=SimpleNamespace(start_seconds=.5,duration_seconds=.5,video_graph=graph)
        movie=output/f'audio-graph-{mode}.mkv'
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',
            'color=s=160x90:r=10:d=0.5',*audio_mix_arguments(ffmpeg,job,graph['audio_mix']),
            '-map','0:v','-c:v','ffv1','-t','0.5',str(movie)],
            purpose='isolated audio graph range movie',check=True,timeout=20)
        layers=preview_audio_layers(contract,500)
        layers=[{**x,'source_out_ms':x['source_ms']+500} for x in layers]
        preview=run_hidden_subprocess(build_audio_mix_command(ffmpeg,layers),
            purpose='isolated preview range PCM',capture_output=True,check=True,timeout=20).stdout
        actual=run_hidden_subprocess([str(ffmpeg),'-v','error','-i',str(movie),'-vn',
            '-ac','2','-ar','48000','-f','s16le','pipe:1'],
            purpose='isolated range movie PCM',capture_output=True,check=True,timeout=20).stdout
        a=np.frombuffer(actual,dtype='<i2').astype(float)
        b=np.frombuffer(preview,dtype='<i2').astype(float)
        correlation=float(np.corrcoef(a,b)[0,1]) if len(a)==len(b) and len(a) else 0.
        ratio=float(np.sqrt(np.mean(a*a)/np.mean(b*b))) if len(a) and len(b) else 0.
        results[mode]={'contract':contract,'movie':str(movie),'preview_samples':len(b),
            'movie_samples':len(a),'correlation':correlation,'rms_ratio':ratio,
            'passed':len(a)==len(b)==48000 and correlation>.999 and abs(ratio-1)<.003
                and graph['audio_mix']==contract['segments']}
    return results
