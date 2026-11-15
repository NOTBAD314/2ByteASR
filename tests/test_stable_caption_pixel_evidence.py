"""Native raster verification must detect missing/extra captions at small scale."""
import numpy as np
from PIL import Image
import pytest
from twobyteasr.acceptance.stable_captions_audit import native_caption_pixel_evidence


def fixture(tmp_path):
    scene=np.zeros((180,320,4),dtype=np.uint8)
    rows=[]
    for i,(x,y,w) in enumerate(((140,120,40),(100,140,120),(70,160,180))):
        scene[y+2:y+8,x+2:x+w-2]=[255,255,255,255]
        rows.append(dict(cue_id=str(i),bounds=[x,y,w,10]))
    scaled=np.array(Image.fromarray(scene).resize((303,170),Image.Resampling.NEAREST))
    native=np.zeros((280,303,3),dtype=np.uint8);native[55:225]=[51,65,85]
    mask=scaled[:,:,3]>0;view=native[55:225];view[mask]=scaled[:,:,:3][mask]
    # A selection handle cuts a white glyph row into disconnected bands.
    native[190:193,110:190]=[180,55,110]
    a,b=tmp_path/'scene.png',tmp_path/'native.png'
    Image.fromarray(scene).save(a);Image.fromarray(native).save(b)
    return a,b,rows,native


def test_small_scaled_glyphs_and_selection_handles_are_three_instances(tmp_path):
    a,b,rows,_=fixture(tmp_path)
    result=native_caption_pixel_evidence(a,b,rows)
    assert result['captions']==3 and result['unexpected_white_pixels']==0


def test_missing_native_caption_is_not_accepted(tmp_path):
    a,b,rows,native=fixture(tmp_path)
    native[205:218]=[51,65,85];Image.fromarray(native).save(b)
    with pytest.raises(AssertionError,match='Missing native caption'):
        native_caption_pixel_evidence(a,b,rows)


def test_extra_native_text_outside_expected_cues_is_not_accepted(tmp_path):
    a,b,rows,native=fixture(tmp_path)
    native[80:85,20:40]=255;Image.fromarray(native).save(b)
    with pytest.raises(AssertionError,match='Unexpected native caption'):
        native_caption_pixel_evidence(a,b,rows)
