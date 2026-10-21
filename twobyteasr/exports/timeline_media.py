"""Bind frozen render graphs to the same per-source clock as Studio preview.

Only disposable worker graphs contain resolved paths. Persisted media and clip
coordinates remain canonical, instance-owned, half-open content milliseconds.
"""
from __future__ import annotations

import copy

TIME_CONTRACT = "timeline-content-v2"


def resolve_frame_graph(graph, milliseconds, ffmpeg, *, cache=None):
    """Resolve only the frozen instant's video, on the capture worker."""
    from ..timeline.studio_transitions import transition_windows
    graph = copy.deepcopy(graph)
    assets = {a['asset_id']: a for a in graph.get('media_pool', [])}
    # A seam overlaps both of its clips: keep each one active at this instant
    # by its transition window, so the still can draw the transition.
    windows = transition_windows(graph, 'video')
    tracks = []
    for track in graph.get('video_tracks', []):
        if not track.get('enabled', True):
            continue
        def span(c):
            window = windows.get((track['id'], c['id']), windows.get(c['id'], c))
            return window['timeline_in_ms'], window['timeline_out_ms']
        track['clips'] = [c for c in track.get('clips', [])
                          if c.get('enabled', True)
                          and span(c)[0] <= milliseconds < span(c)[1]
                          and assets[c['asset_id']].get('video_metadata', {}).get('has_video') is not False]
        if track['clips']:
            tracks.append(track)
    graph.update(video_tracks=tracks, audio_mix=[])
    return resolve_video_graph(graph, ffmpeg, cache=cache)


def resolve_audio_layers(layers, ffmpeg, *, cancelled=None, cache=None):
    if cache is None:
        from ..media.indexed_media import GLOBAL_INDEXED_MEDIA
        cache = GLOBAL_INDEXED_MEDIA
    resolved, receipts = [], {}
    for original in layers:
        layer = copy.deepcopy(original)
        if layer.get('media_time_contract') == TIME_CONTRACT:
            resolved.append(layer)
            continue
        source = layer['source_path']
        if source not in receipts:
            receipts[source] = cache.prepare_timeline_source(source, ffmpeg=ffmpeg, cancelled=cancelled)
        layer.update(source_path=receipts[source]['path'], original_source_path=source,
                     media_time_contract=TIME_CONTRACT)
        resolved.append(layer)
    return resolved, receipts


def resolve_video_graph(graph, ffmpeg, *, cancelled=None, cache=None):
    if graph.get('media_time_contract') == TIME_CONTRACT:
        return graph
    if cache is None:
        from ..media.indexed_media import GLOBAL_INDEXED_MEDIA
        cache = GLOBAL_INDEXED_MEDIA
    graph = copy.deepcopy(graph)
    audio, receipts = resolve_audio_layers(graph.get('audio_mix', []), ffmpeg,
                                          cancelled=cancelled, cache=cache)
    active_assets = {c['asset_id'] for t in graph.get('video_tracks', []) if t.get('enabled', True)
                     for c in t.get('clips', []) if c.get('enabled', True)}
    for asset in graph.get('media_pool', []):
        if asset['asset_id'] not in active_assets:
            continue
        source = asset['canonical_source']
        if source not in receipts:
            receipts[source] = cache.prepare_timeline_source(source, ffmpeg=ffmpeg, cancelled=cancelled)
        asset.update(original_source_path=source, canonical_source=receipts[source]['path'])
    graph.update(audio_mix=audio, media_time_contract=TIME_CONTRACT, media_timebases=receipts)
    return graph
