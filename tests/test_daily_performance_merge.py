"""Performance reuse stays inside the current daily language-layer contract."""
import copy
from tests.test_subtitle_translation import make_project
from twobyteasr.caption_style import scoped_style
from twobyteasr.caption_style.style_resolution import resolve_cue_visual


def test_actual_scoped_route_reuses_native_materialization(monkeypatch):
    p=make_project();calls=[];original=scoped_style.resolve_cue_visual
    for c in p.cues:c.speaker_id='S00'
    def counted(*args):calls.append(args[1].id);return original(*args)
    monkeypatch.setattr(scoped_style,'resolve_cue_visual',counted)
    before=copy.deepcopy(p.cues)
    cmd=scoped_style.style_patch_command(p,[c.id for c in p.cues],{'font_size':77},
        recipe_patch={'colors':{'fill':'#FF112233'}},layer='original')
    assert len(calls)<len(p.cues)
    cmd.redo()
    assert all(resolve_cue_visual(p,c).style.font_size==77 for c in p.cues)
    cmd.undo()
    assert [(c.transform,c.appearance_override,c.style_id) for c in p.cues]==[(c.transform,c.appearance_override,c.style_id) for c in before]


def test_original_layer_preserves_each_translation_and_other_properties():
    p=make_project();p.generation_metadata['translations']={c.id:'English '+c.id for c in p.cues}
    p.cues[1].appearance_override={'translation':{'style':{'font_size':23,'primary_color':'#FF334455'}}}
    before={c.id:copy.deepcopy(scoped_style.effective_layer_style(p,c,'translation')) for c in p.cues}
    cmd=scoped_style.style_patch_command(p,[c.id for c in p.cues],{'font_size':77},layer='original')
    cmd.redo()
    for c in p.cues:
        actual=scoped_style.effective_layer_style(p,c,'translation');old=before[c.id]
        assert actual.font_size==old.font_size and actual.primary_color==old.primary_color
    cmd.undo()
    assert p.cues[1].appearance_override=={'translation':{'style':{'font_size':23,'primary_color':'#FF334455'}}}
