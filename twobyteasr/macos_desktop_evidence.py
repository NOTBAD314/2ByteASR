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
