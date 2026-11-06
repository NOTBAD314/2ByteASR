"""Preview-only eligibility. Timeline/list selection deliberately does not use it."""
from ..caption_style.bilingual_layout import settings_from_state, translations_of


def layer_is_shown(page, cue, language="original"):
    project = getattr(page, "project", None)
    if project is None or cue is None:
        return False
    runtime = getattr(getattr(page, "session", None), "runtime", None)
    if runtime is not None and cue.id not in runtime.cue_by_id:
        return False
    sample = getattr(page, "_caption_sample_ms", None)
    milliseconds = sample() if callable(sample) else page.timeline.playhead_ms
    if not cue.start_ms <= milliseconds < cue.end_ms:
        return False
    if (cue.speaker_id in getattr(page.timeline, "hidden_speakers", ())
            or not getattr(page, "_subtitle_track_visibility", {}).get(cue.speaker_id, True)):
        return False
    mode = settings_from_state(project.studio_state).mode
    if language == "translation":
        return mode in {"translation", "bilingual"} and bool(translations_of(project.generation_metadata).get(cue.id, "").strip())
    return mode in {"original", "bilingual"} or (mode == "translation" and not translations_of(project.generation_metadata).get(cue.id, "").strip())


def visible_object_at(page, point):
    """Hit only the published active scene, in its actual composition order."""
    from PySide6.QtCore import QRectF
    from ..caption_style.bilingual_layout import COMPANION_SUFFIX
    mode = settings_from_state(page.project.studio_state).mode if page.project else 'original'
    scene = getattr(page, '_caption_scene', None)
    token = getattr(scene, 'token', None)
    if scene is None or token is None or not scene.still_current(token):
        return None
    trace = scene.trace()
    if not trace.get('visible', False):return None
    content = page.position_overlay._content_rect()
    # Scene rows follow bottom-to-top painting; hidden rows never occlude one
    # below them. This list contains only current objects, not the whole project.
    for row in reversed(trace.get('cue_pixels', ())):
        box, viewport = row.get('bounds'), row.get('viewport')
        if not box or not viewport or row.get('alpha_nonzero', 1) <= 0:
            continue
        key = str(row.get('cue_id', ''))
        layer = 'translation' if key.endswith(COMPANION_SUFFIX) else 'original'
        cue_id = key[:-len(COMPANION_SUFFIX)] if layer == 'translation' else key
        cue = getattr(page, '_cue_lookup', {}).get(cue_id)
        if (layer == 'original' and mode == 'translation' and page.project
                and translations_of(page.project.generation_metadata).get(cue_id, '').strip()):
            layer = 'translation'
        if not layer_is_shown(page, cue, layer):
            continue
        x, y, w, h = box
        width, height = viewport
        rect = QRectF(content.x()+x*content.width()/width, content.y()+y*content.height()/height,
                      w*content.width()/width, h*content.height()/height)
        if rect.contains(point):
            return cue_id, layer
    return None
