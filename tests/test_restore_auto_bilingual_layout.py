from copy import deepcopy
from tests.test_style_bilingual_reflow import project,boxes
from twobyteasr.caption_style.caption_layer_transform import restore_automatic_layout_command
from twobyteasr.caption_style.scoped_style import style_patch_command


def test_explicit_recovery_releases_only_layer_positions_and_keeps_appearance():
    p=project();c=p.cues[0]
    c.transform={'position_x':810.,'position_y':890.,'language_layers':{'original':{'position_x':800.,'position_y':850.,'anchor_x':.5,'anchor_y':1.,'font_size':60.,'scale_x':105.},
        'translation':{'position_x':800.,'position_y':820.,'anchor_x':.5,'anchor_y':1.,'font_size':60.,'scale_y':95.}}}
    before=deepcopy((c.transform,c.appearance_override))
    command=restore_automatic_layout_command(p,[c.id]);command.redo()
    assert c.transform['position_x']==810. and c.transform['position_y']==890.
    assert c.transform['language_layers']['original']=={'font_size':60.,'scale_x':105.}
    assert c.transform['language_layers']['translation']=={'font_size':60.,'scale_y':95.}
    assert c.appearance_override==before[1]
    for size in (60.,82.,45.):
        style_patch_command(p,[c.id],{'font_size':size},layer='group').redo()
        a,b=boxes(p);assert a[1]<=b[0]
    command.undo();assert (c.transform,c.appearance_override)==before


def test_recovery_skips_missing_translation_and_is_idempotent():
    p=project();p.generation_metadata['translations'].clear()
    p.cues[0].transform={'language_layers':{'original':{'position_y':700}}}
    assert restore_automatic_layout_command(p,['a']) is None
    p=project();assert restore_automatic_layout_command(p,['a']) is None
