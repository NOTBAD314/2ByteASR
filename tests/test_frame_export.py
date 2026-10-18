from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from twobyteasr.frame_export import save_project_frame,safe_frame_name
from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.video_export import capture_video_graph
from twobyteasr.export_timeline import export_project_snapshot
from twobyteasr.processes import run_hidden_subprocess

FFMPEG=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'


def test_exact_frame_unique_outputs_and_caption_option(tmp_path):
    app=QApplication.instance() or QApplication([])
    media=tmp_path/'frames.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=25:d=2',
        '-c:v','ffv1',str(media)],check=True,timeout=20,purpose='frame export integration fixture')
    p=SubtitleProject(media=StudioMedia(str(media),duration_ms=2000,width=640,height=360),
        cues=[StudioCue('a',400,950,'保存指定帧')]);p.validate()
    frozen=export_project_snapshot(p);graph=capture_video_graph(p)
    a=save_project_frame(frozen,graph,777,tmp_path,'CON',subtitles=False,ffmpeg=FFMPEG)
    b=save_project_frame(frozen,graph,777,tmp_path,'CON',subtitles=True,ffmpeg=FFMPEG)
    assert a['decode'][0]['frame_seconds']<=.777<a['decode'][0]['next_seconds']
    assert a['path']!=b['path'] and (a['width'],a['height'])==(640,360)
    assert QImage(a['path'])!=QImage(b['path'])
    assert QImage(a['path']).width()==640
    with pytest.raises(ValueError):save_project_frame(frozen,graph,2000,tmp_path,'end',ffmpeg=FFMPEG)
    with pytest.raises(OSError):save_project_frame(frozen,graph,100,tmp_path/'missing','bad',ffmpeg=FFMPEG)
    assert safe_frame_name('a:b?',777).startswith('a_b_')


def test_frame_composes_layers_visibility_and_trim_rate(tmp_path):
    from twobyteasr.studio_project import VideoTransform
    from twobyteasr.studio_media_pool import add_media_asset,create_video_track,add_video_clip
    app=QApplication.instance() or QApplication([])
    paths=[]
    for color in ('red','blue','lime'):
        path=tmp_path/(color+'.mkv')
        run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i',
            f'color={color}:s=320x180:r=25:d=2','-c:v','ffv1',str(path)],check=True,timeout=20,purpose='frame layer fixture')
        paths.append(path)
    p=SubtitleProject(media=StudioMedia(str(paths[0]),duration_ms=2000,width=320,height=180));p.validate()
    for i,path in enumerate(paths[1:]):
        asset=add_media_asset(p,path,duration_ms=2000,video_metadata={'has_video':True,'width':320,'height':180})
        track=create_video_track(p,f'V{i+2}')
        clip=add_video_clip(p,track.id,asset.asset_id,source_in_ms=200,source_out_ms=1800,timeline_in_ms=400)
        clip.playback_rate=2.;clip.timeline_out_ms=1200
        clip.transform=VideoTransform(scale_x=.5,scale_y=.5,position_x=.25 if i==0 else .75)
        track.enabled=i==0
    result=save_project_frame(export_project_snapshot(p),capture_video_graph(p),500,tmp_path,'layers',subtitles=False,extension='jpg',ffmpeg=FFMPEG)
    image=QImage(result['path'])
    assert result['path'].endswith('.jpg') and len(result['decode'])==2
    assert abs(result['decode'][1]['source_seconds']-.4)<1e-9
    assert image.pixelColor(80,90).blue()>230
    assert image.pixelColor(240,90).red()>230


@pytest.mark.parametrize('look,milliseconds,check',[
    (None,1500,'dissolve'),(None,1250,'quarter'),
    (dict(id='push',direction='left'),1500,'split'),(dict(id='flash'),1500,'white'),
])
def test_frame_inside_a_seam_draws_the_transition(tmp_path,look,milliseconds,check):
    # Same edit as the export check: red 0–1.5 s cut to blue, 1 s seam
    # 1.0–2.0 s. Without the transition only one clip covers each instant.
    from twobyteasr.studio_project import VideoClip
    from twobyteasr.studio_edit_sequence import sequence_of
    from twobyteasr.studio_media_pool import sync_linked_av_contract
    from twobyteasr.studio_transitions import set_transition
    app=QApplication.instance() or QApplication([])
    source=tmp_path/'red then blue.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i','color=red:s=160x90:r=10:d=2',
        '-f','lavfi','-i','color=blue:s=160x90:r=10:d=2','-filter_complex','[0][1]concat=n=2:v=1',
        '-c:v','ffv1',str(source)],check=True,timeout=20,purpose='frame transition fixture')
    p=SubtitleProject(media=StudioMedia(str(source),duration_ms=4000,width=160,height=90));p.validate()
    asset=p.media_pool[0];asset.offline=False
    asset.video_metadata=dict(asset.video_metadata or {},width=160,height=90,has_video=True,fps=10)
    p.video_tracks[0].clips=[VideoClip('red',asset.asset_id,0,1500,0,1500),
                             VideoClip('blue',asset.asset_id,2500,4000,1500,3000)]
    p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    sync_linked_av_contract(p)
    set_transition(p,'video',p.video_tracks[0].id,'red','blue',duration_ms=1000,look=look)
    result=save_project_frame(export_project_snapshot(p),capture_video_graph(p),milliseconds,tmp_path,'seam',
                              subtitles=False,ffmpeg=FFMPEG)
    assert sorted(r['clip_id'] for r in result['decode'])==['blue','red']
    image=QImage(result['path'])
    left,middle,right=image.pixelColor(20,45),image.pixelColor(80,45),image.pixelColor(140,45)
    if check=='dissolve':
        assert abs(middle.red()-128)<=6 and abs(middle.blue()-128)<=6
    elif check=='quarter':
        # Before the cut: the incoming clip is already a quarter in.
        assert abs(middle.red()-191)<=6 and abs(middle.blue()-64)<=6
    elif check=='split':
        assert left.red()>200 and left.blue()<40 and right.blue()>200 and right.red()<40
    else:
        assert min(middle.red(),middle.green(),middle.blue())>240
