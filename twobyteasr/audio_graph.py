"""Serializable audio source/routing contract shared by preview and export.

Version is internal to a job snapshot; it does not change project storage.
Transport speed is a preview compiler input, never part of this contract.
"""
from __future__ import annotations

from .audio_playback_graph import AudioPlaybackGraph, solo_track_ids
from .studio_track_gain import track_gain_db


def audio_graph_signature(project):
    state = project.studio_state
    tracks = tuple((t.id, t.enabled, t.muted, getattr(t, 'soloed', False),
        tuple((c.id,c.asset_id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms,
               c.enabled,getattr(c,'audio_enabled',True),getattr(c,'playback_rate',1.),getattr(c,'gain_db',0.)) for c in t.clips))
        for t in (*project.video_tracks,*project.audio_tracks))
    return (id(project),tracks,tuple((a.asset_id,a.canonical_source,a.offline,repr(a.audio_metadata),repr(a.video_metadata)) for a in project.media_pool),
        tuple((g.video_track_id,g.audio_track_id,g.linked) for g in project.av_track_groups),
        tuple(sorted(state.get('audio_track_gain_db',{}).items())),
        tuple(sorted(solo_track_ids(project))),
        tuple((k,repr(v)) for k,v in state.items() if k.startswith('audio_') or k=='selected_video_track_id'))


def capture_audio_graph(project):
    from .studio_media_pool import effective_audio_master_track_id, primary_video_track_id
    assets = {a.asset_id:a for a in project.media_pool}
    associated = {g.video_track_id for g in project.av_track_groups}
    linked = {g.video_track_id:g.audio_track_id for g in project.av_track_groups if g.linked}
    audio = {a.id:a for a in project.audio_tracks}
    detached_tracks = {g.audio_track_id for g in project.av_track_groups if not g.linked}
    detached_clip_ids = {c.linked_video_clip_id for t in project.audio_tracks if t.id in detached_tracks
                         for c in t.clips if c.linked_video_clip_id}
    layers = []
    tracks = [t for t in project.video_tracks if t.id in linked or t.id not in associated]+[t for t in project.audio_tracks if t.id not in linked.values()]
    for track in tracks:
        sound = audio.get(linked.get(track.id), track)
        standalone = track.id not in linked and track in project.audio_tracks
        for clip in track.clips:
            if track.id in linked and clip.id in detached_clip_ids:
                continue
            linked_clip = next((a for a in sound.clips if a.linked_video_clip_id == clip.id), clip) if track.id in linked else clip
            asset = assets.get(clip.asset_id)
            if asset is None or asset.offline or (asset.audio_metadata or {}).get('has_audio') is False:
                continue
            layers.append(dict(track_id=track.id,audio_track_id=linked.get(track.id,track.id),
                track_name=track.name,clip_id=clip.id,asset_id=clip.asset_id,source_path=asset.canonical_source,
                timeline_in_ms=clip.timeline_in_ms,timeline_out_ms=clip.timeline_out_ms,
                source_in_ms=clip.source_in_ms,source_out_ms=clip.source_out_ms,
                playback_rate=float(getattr(clip,'playback_rate',1.)),gain_db=track_gain_db(project,track.id) + float(getattr(linked_clip,'gain_db',0.)),
                audio_enabled=bool(sound.enabled and linked_clip.enabled and getattr(clip,'audio_enabled',clip.enabled)),
                track_muted=bool(sound.muted),
                audio_only=standalone or (asset.video_metadata or {}).get('has_video') is False or not bool(track.enabled and clip.enabled),
                audio_only_source=standalone or (asset.video_metadata or {}).get('has_video') is False,
                primary_media=standalone or track.id==primary_video_track_id(project)))
    boundaries = sorted({p for x in layers for p in (x['timeline_in_ms'],x['timeline_out_ms'])})
    graph = AudioPlaybackGraph()
    resolved = []
    solos = solo_track_ids(project)
    # Accept either linked An identity or Vn identity for a solo request.
    solos = frozenset(next((v for v,a in linked.items() if a==key),key) for key in solos)
    for start,end in zip(boundaries,boundaries[1:]):
        active = list({x['track_id']:x for x in layers if x['timeline_in_ms']<=start<x['timeline_out_ms']}.values())
        master = effective_audio_master_track_id(project, tuple(x['track_id'] for x in active),
            selected_track_id=str(project.studio_state.get('selected_video_track_id') or ''))
        # Explicit Solo temporarily takes precedence over legacy manual sound.
        graph.configure(master_track_id='' if solos else master,solo_track_ids=solos)
        choice = graph.decide(active)
        ids = choice.mix_track_ids if choice.mix_mode else (choice.audible_track_id,)
        for layer in active:
            if layer['track_id'] not in ids: continue
            rate=layer['playback_rate']
            resolved.append({**layer,'source_in_ms':layer['source_in_ms']+round((start-layer['timeline_in_ms'])*rate),
                'source_out_ms':min(layer['source_out_ms'],layer['source_in_ms']+round((end-layer['timeline_in_ms'])*rate)),
                'timeline_in_ms':start,'timeline_out_ms':end})
    return {'version':1,'inputs':layers,'segments':resolved,'solo_track_ids':sorted(solos),
            'mix_order':[t.id for t in tracks],'pitch':'preserve','preview_rate_in_graph':False}


def preview_audio_layers(graph, timeline_ms):
    return [{**layer,'source_ms':layer['source_in_ms']+round((timeline_ms-layer['timeline_in_ms'])*layer['playback_rate'])}
            for layer in graph['segments'] if layer['timeline_in_ms']<=timeline_ms<layer['timeline_out_ms']]
