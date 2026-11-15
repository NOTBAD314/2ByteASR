"""Owned synthetic 1.1.0 fixtures for the installed native Mac application."""
from pathlib import Path
import re,subprocess

def prepare_fixture(app,output,scenario,default):
    if scenario not in {'editor-download','english-track-loudness'}:return default
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    ffmpeg=app/'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
    if not ffmpeg.is_file():ffmpeg=app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    duration=327 if scenario=='english-track-loudness' else 12
    media=output/'fixture.mp4'
    with (output/'sample-media.log').open('wb') as log:
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i',f'color=c=0x26343d:s=960x540:r=12:d={duration}',
            '-f','lavfi','-i',f'sine=frequency=997:sample_rate=48000:duration={duration}',
            '-af','volume=0.4','-c:v','libx264','-preset','ultrafast','-threads','2',
            '-c:a','aac','-ac','2','-shortest',str(media)],check=True,timeout=180,stdout=log,stderr=log)
    if scenario=='editor-download':
        p=SubtitleProject(StudioMedia(str(media),duration_ms=12000,width=960,height=540),cues=[
            StudioCue('a',0,5000,'她如果真的不是的话，他和它在营第等我。'),
            StudioCue('b',5100,10000,'她在第一行\n他和它在营第。')])
        from twobyteasr.subtitle_rules import subtitle_translation as st
        text='她和他一起到营第。'
        p.generation_metadata.update(translations={'a':text},translation_records=dict(version=1,target='zh',
            records={'a':st._record(text,p.cues[0].text,origin=st.ORIGIN_MANUAL)},history=[]))
    else:
        from twobyteasr.timeline.studio_media_pool import add_media_asset,create_video_track,add_video_clip,set_audio_master_mode
        text="And uh but I just also say you what I'm going to do here does require studio."
        tokens=list(re.finditer(r'\S+',text));words=[];cursor=0;weights=[1+i%4 for i in range(len(tokens))]
        for token,weight in zip(tokens,weights):
            start=321039+round(cursor/sum(weights)*5681);cursor+=weight
            words.append(dict(text=token.group(),start_ms=start,end_ms=321039+round(cursor/sum(weights)*5681)))
        p=SubtitleProject(StudioMedia(str(media),duration_ms=327000,width=960,height=540),
            cues=[StudioCue('c132',321039,326720,text,evidence_refs=['fixture'])],asr_evidence={'fixture':{'words':words}})
        p.generation_metadata['language']={'code':'en','requested':'en'};p.validate()
        for track in (*p.video_tracks,*p.audio_tracks):track.locked=False
        asset=add_media_asset(p,media,duration_ms=327000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
        track=create_video_track(p);add_video_clip(p,track.id,asset.asset_id,source_out_ms=12000)
        set_audio_master_mode(p,'mix_all')
        for track in (*p.video_tracks,*p.audio_tracks):track.locked=False
    target=output/'fixture.2byteproj';save_project(p,target);return target
