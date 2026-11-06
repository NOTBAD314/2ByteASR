"""Actual filter pixels and full alpha coverage, including odd placements."""
from pathlib import Path
import hashlib
import subprocess
import av
import numpy as np
import pytest
from PIL import Image
from twobyteasr.exports.caption_composite_region import append_region_overlay, moving_alpha_bounds
from twobyteasr.system.platform_media import ffmpeg_tool
from twobyteasr.system.processes import run_hidden_subprocess


@pytest.mark.parametrize('full_canvas',[False,True])
def test_local_blend_keeps_rgba_edges_at_odd_pixel_coordinates(tmp_path,full_canvas):
    width,height=320,180
    x,y,w,h=101,83,64,22
    pixels=np.zeros((h,w,4),np.uint8)
    pixels[:,:,:3]=[210,65,180]
    pixels[:,:,3]=np.linspace(1,255,w,dtype=np.uint8)[None,:]
    if full_canvas:
        full=np.zeros((height,width,4),np.uint8);full[y:y+h,x:x+w]=pixels;pixels=full
    image=tmp_path/'pixels.png';Image.fromarray(pixels).save(image)
    reference=f'[0:v][1:v]overlay=x={0 if full_canvas else x}:y={0 if full_canvas else y}:format=auto[v]'
    filters=[]
    label=append_region_overlay(filters,'[0:v]','[1:v]',bounds=(x,y,x+w,y+h),width=width,height=height,
        pixel_format='yuv420p',tag='region',full_canvas=full_canvas)
    graphs=[(reference,'[v]'),(';'.join(filters),label)]
    outputs=[]
    for graph,label in graphs:
        graph+=f';{label}format=yuv420p,format=rgb24[final]'
        result=run_hidden_subprocess([str(ffmpeg_tool()),'-v','error','-filter_complex_threads','1','-f','lavfi','-i',
            f'testsrc2=s={width}x{height}:r=30:d=1','-i',str(image),'-filter_complex',graph,
            '-map','[final]','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
            purpose='lossless caption region pixel regression',capture_output=True,check=True,timeout=20)
        outputs.append(np.frombuffer(result.stdout,np.uint8).reshape(height,width,3))
    difference=np.abs(outputs[0][y:y+h,x:x+w].astype(int)-outputs[1][y:y+h,x:x+w].astype(int))
    assert difference.max()<=1 and difference.mean()<.01


def test_wide_or_high_bit_depth_layer_keeps_full_composition():
    for bounds,pixel_format in [((0,0,320,180),'yuv420p'),((100,80,170,100),'yuv420p10le')]:
        graph=[]
        append_region_overlay(graph,'[base]','[pixels]',bounds=bounds,width=320,height=180,
            pixel_format=pixel_format,tag='full',full_canvas=True)
        assert len(graph)==1 and 'crop=' not in graph[0] and 'format=auto' in graph[0]


def test_alpha_union_covers_faint_first_last_frames_and_cache_digest(tmp_path):
    width,height=160,90
    frames=np.zeros((3,height,width,4),dtype='<u2')
    frames[:,:,:,0]=60000
    frames[:,30:50,50:80,3]=65535
    frames[0,2,1,3]=256
    frames[2,74,109,3]=256
    movie=tmp_path/'moving.mov'
    run_hidden_subprocess([str(ffmpeg_tool()),'-v','error','-f','rawvideo','-s',f'{width}x{height}',
        '-pix_fmt','rgba64le','-r','30','-i','pipe:0','-c:v','prores_ks','-profile:v','4',
        '-threads:v','2','-pix_fmt','yuva444p10le',str(movie)],
        purpose='faint alpha full-window fixture',input=frames.tobytes(),capture_output=True,check=True,timeout=20)
    movie.with_suffix('.sha256').write_text(hashlib.sha256(movie.read_bytes()).hexdigest(),'ascii')
    bounds=moving_alpha_bounds(movie,width=width,height=height,frames=3,cached=movie)
    assert bounds==[1,2,110,75]
    assert moving_alpha_bounds(movie,width=width,height=height,frames=3,cached=movie)==bounds
    movie.with_suffix('.roi.json').write_text('[]','utf8')
    assert moving_alpha_bounds(movie,width=width,height=height,frames=3,cached=movie)==bounds
    movie.with_suffix('.sha256').write_text('changed-renderer-digest','ascii')
    assert moving_alpha_bounds(movie,width=width,height=height,frames=3,cached=movie)==bounds
    assert moving_alpha_bounds(movie,width=width,height=height,frames=301,cached=movie) is None

