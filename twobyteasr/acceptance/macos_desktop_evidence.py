# SPDX-License-Identifier: GPL-3.0-only
"""Bounded observations for the guarded native QA profile, without user caches."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def studio_snapshot(page) -> dict:
    readiness = getattr(page, '_readiness', None)
    video = getattr(page, 'video', None)
    result = {
        'project_id': getattr(getattr(page, 'project', None), 'project_id', None),
        'view_state': getattr(page, '_project_view_state', None),
        'readiness': {name: getattr(readiness, name, None) for name in
                      ('active', 'ready', 'path', 'profile', 'completed', 'next_stage',
                       'player_ready', 'hydrated', 'painted')},
        'last_open_profile': getattr(page, 'last_open_profile', None),
        'video': {name: getattr(video, name, None) for name in
                  ('_startup_state', '_media_path', '_web_last_decoded')},
        'preview_path': str(getattr(page, '_preview_path', '') or ''),
        'web_worker_present': getattr(page, '_web_live_worker', None) is not None,
    }
    # Keep raster data out of a diagnostic JSON; availability is sufficient.
    result['video']['_web_last_decoded'] = result['video']['_web_last_decoded'] is not None
    for name, callback in (
        ('video_actor', lambda: page.video.controller.actor_status()),
        ('video_visual', lambda: page.video.controller.applied_visual_state()),
        ('video_composition', lambda: page.video_compositor.performance_snapshot()),
        ('audio', lambda: page.audio_engine.telemetry_snapshot()),
        ('audio_ready', lambda: page.audio_engine.ready_for_playback()),
        ('audio_request', lambda: dict(page.audio_engine._last_payload)),
        ('video_followers', lambda: {key: source.performance_snapshot()
                                   for key, source in page.video_compositor._players.items()}),
        ('playback_buffers_ready', lambda: page._playback_buffers_ready()),
        ('caption_scene', lambda: page._caption_scene.trace()),
    ):
        try:
            result[name] = callback()
        except Exception as exc:
            result[name] = {'observation_error': str(exc)}
    # Convert sets/paths, but never serialize arbitrary object representations.
    return json.loads(json.dumps(result, ensure_ascii=False,
                                default=lambda value: sorted(value) if isinstance(value, set)
                                else str(value) if isinstance(value, Path) else type(value).__name__))


def image_colour_observation(image) -> dict:
    """Measure the owned colourful QA video, without treating handles as video."""
    from PySide6.QtCore import Qt
    if image.isNull():
        return {'width': 0, 'height': 0, 'colour_fraction': 0.0}
    # The upper two thirds avoid caption/edit handles near the bottom.
    sample = image.copy(0, 0, image.width(), max(1, image.height()*2//3)).scaled(
        64, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    colour = 0
    for y in range(sample.height()):
        for x in range(sample.width()):
            pixel = sample.pixelColor(x, y)
            rgb = (pixel.red(), pixel.green(), pixel.blue())
            colour += max(rgb) > 64 and max(rgb)-min(rgb) > 40
    return {'width': image.width(), 'height': image.height(),
            'colour_fraction': round(colour/(sample.width()*sample.height()), 6)}


def visible_caption_pixels(canvas) -> dict:
    """Compare actual widget pixels with/without the existing caption slot.

    The owned QA is paused. No event loop is pumped between the two grabs, so
    this changes only painting, not project data, time, or native publication.
    A successful raster receipt alone cannot pass this visibility check.
    """
    import numpy as np
    from PySide6.QtGui import QImage
    controller=canvas.controller;surface=controller.surface
    slot=getattr(canvas,'ADVANCED_OVERLAY_ID',1)
    item=getattr(surface,'overlays',{}).get(slot)
    if item is None:return dict(passed=False,changed_pixels=0,reason='caption slot missing')
    sequence=controller.actor_status().get('frame_sequence')
    before=canvas.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    try:
        surface.overlays.pop(slot,None)
        after=canvas.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    finally:
        surface.overlays[slot]=item
        surface.update()
    if before.size()!=after.size():return dict(passed=False,changed_pixels=0,reason='canvas resized')
    def pixels(image):
        return np.ndarray((image.height(),image.width(),4),dtype=np.uint8,buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))
    changed=np.any(np.abs(pixels(before).astype(np.int16)-pixels(after).astype(np.int16))>3,axis=2)
    stable=sequence==controller.actor_status().get('frame_sequence')
    return dict(passed=stable and int(changed.sum())>10,changed_pixels=int(changed.sum()),stable_frame=stable,
                caption_geometry=list(item[1]),caption_image_size=[item[0].width(),item[0].height()],
                canvas_dpr=canvas.devicePixelRatioF(),surface_dpr=surface.devicePixelRatioF())


def preserve_studio_preview(page, output: Path, label: str) -> dict:
    """Actual decoded raster AND visible composed canvas at owned QA milestones."""
    from PySide6.QtCore import Qt
    if label not in {'ready', 'bilingual', 'cut-before', 'cut-after', 'reopened'}:
        raise ValueError('Unknown owned preview milestone')
    canvas = page.video
    controller = canvas.controller
    surface = controller.surface
    decoded = surface.frame
    composed = canvas.grab().toImage()
    record = dict(backend=controller.backend, actor=controller.actor_status(),
                  decoded=image_colour_observation(decoded),
                  composed=image_colour_observation(composed),
                  surface_visible=surface.isVisible(), canvas_visible=canvas.isVisible(),
                  canvas_native=canvas.testAttribute(Qt.WA_NativeWindow),
                  surface_native=surface.testAttribute(Qt.WA_NativeWindow),
                  surface_geometry=list(surface.geometry().getRect()),
                  canvas_geometry=list(canvas.rect().getRect()),
                  overlays=controller.applied_visual_state(),
                  studio=studio_snapshot(page))
    from ..rendering.caption_scene import active_cues
    record['caption_required']=bool(active_cues(page,page._caption_sample_ms()))
    record['caption_visibility']=visible_caption_pixels(canvas)
    record['passed'] = bool(record['surface_visible'] and record['canvas_visible']
                            and record['decoded']['colour_fraction'] > .10
                            and record['composed']['colour_fraction'] > .10
                            and (not record['caption_required'] or record['caption_visibility']['passed']))
    if 1 in getattr(surface,'overlays',{}):
        surface.overlays[1][0].save(str(output/f'preview-{label}-caption.png'))
    for kind, raster in [('decoded', decoded), ('composed', composed)]:
        filename = f'preview-{label}-{kind}.png'
        if not raster.isNull():
            if not raster.save(str(output/filename)):
                raise OSError('Cannot preserve owned preview raster')
            record[kind]['file'] = filename
    (output/f'preview-{label}.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2)+'\n', 'utf8')
    return record


def preserve_owned_project(path: Path, output: Path, label: str) -> dict:
    path, output = path.resolve(), output.resolve()
    path.relative_to(output / 'projects')
    if path.suffix != '.2byteproj' or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Only a bounded owned QA project may be archived')
    if label not in {'recognized', 'final', 'restart'}:
        raise ValueError('Unknown QA project milestone')
    destination = output / 'owned-projects' / (label + '.2byteproj')
    destination.parent.mkdir(exist_ok=True)
    shutil.copy2(path, destination)
    return {'path': str(destination), 'bytes': destination.stat().st_size,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
