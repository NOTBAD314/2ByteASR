"""Serializable instance-owned audio routing shared by preview and export.

Transport speed is a preview compiler input, never project storage.
"""
from __future__ import annotations

from .audio_playback_graph import AudioPlaybackGraph, solo_track_ids
from ..timeline.studio_track_gain import track_gain_db


def audio_graph_signature(project):
    state = project.studio_state
    tracks = tuple((t.id, t.enabled, t.muted, getattr(t, 'soloed', False),
        tuple((c.id,c.asset_id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms,
               c.enabled,getattr(c,'audio_enabled',True),getattr(c,'playback_rate',1.),getattr(c,'gain_db',0.),
               getattr(c,'linked_video_clip_id',''),getattr(c,'link_group_id',''),getattr(c,'stream_index',0)) for c in t.clips))
        for t in (*project.video_tracks,*project.audio_tracks))
    return (id(project),tracks,tuple((a.asset_id,a.canonical_source,a.offline,repr(a.audio_metadata),repr(a.video_metadata)) for a in project.media_pool),
        tuple((g.video_track_id,g.audio_track_id,g.linked) for g in project.av_track_groups),
        tuple(sorted(state.get('audio_track_gain_db',{}).items())),
        tuple(sorted(solo_track_ids(project))),
        tuple((k,repr(v)) for k,v in state.items() if k.startswith('audio_') or k in {'selected_video_track_id','clip_transitions'}))


def capture_audio_graph(project):
    from ..timeline.studio_media_pool import effective_audio_master_track_id, primary_video_track_id
    assets = {a.asset_id:a for a in project.media_pool}
    associated = {g.video_track_id for g in project.av_track_groups}
    linked = {g.video_track_id:g.audio_track_id for g in project.av_track_groups if g.linked}
    audio = {a.id:a for a in project.audio_tracks}
    detached_owners = {(g.video_track_id, c.linked_video_clip_id)
                       for g in project.av_track_groups if not g.linked
                       for c in getattr(audio.get(g.audio_track_id), 'clips', ()) if c.linked_video_clip_id}
    from ..timeline.studio_transitions import transition_windows, transition_records
    windows = transition_windows(project, 'audio')
    layers = []
    tracks = [t for t in project.video_tracks if t.id in linked or t.id not in associated]

    def append_layer(track, clip, sound, linked_clip, *, standalone):
        asset = assets.get(clip.asset_id)
        if asset is None or asset.offline or (asset.audio_metadata or {}).get('has_audio') is False:
            return
        window = windows.get((sound.id, linked_clip.id), windows.get(linked_clip.id, {}))
        envelopes = window.get('envelopes', []) if not window.get('track_id') or window['track_id'] == sound.id else []
        geometry = window if envelopes else {}
        layers.append(dict(track_id=track.id,audio_track_id=linked.get(track.id,track.id),
            track_name=track.name,clip_id=clip.id,asset_id=clip.asset_id,source_path=asset.canonical_source,
            audio_clip_id=linked_clip.id,stream_index=int(getattr(linked_clip,'stream_index',0)),
            timeline_in_ms=geometry.get('timeline_in_ms',clip.timeline_in_ms),timeline_out_ms=geometry.get('timeline_out_ms',clip.timeline_out_ms),
            source_in_ms=geometry.get('source_in_ms',clip.source_in_ms),source_out_ms=geometry.get('source_out_ms',clip.source_out_ms),
            audio_envelopes=envelopes,
            playback_rate=float(getattr(clip,'playback_rate',1.)),gain_db=track_gain_db(project,track.id) + float(getattr(linked_clip,'gain_db',0.)),
            # A linked waveform is the video's audio component, never a
            # fallback source when its owning video is disabled or has a gap.
            audio_enabled=bool(track.enabled and clip.enabled and sound.enabled and linked_clip.enabled
                               and getattr(clip,'audio_enabled',True)),
            track_muted=bool(track.muted or sound.muted),
            audio_only=standalone or (asset.video_metadata or {}).get('has_video') is False,
            audio_only_source=standalone or (asset.video_metadata or {}).get('has_video') is False,
            primary_media=standalone or track.id==primary_video_track_id(project)))

    for track in tracks:
        sound = audio.get(linked[track.id]) if track.id in linked else track
        if sound is None:
            continue
        owned = {c.linked_video_clip_id:c for c in sound.clips if c.linked_video_clip_id} if track.id in linked else {}
        for clip in track.clips:
            if (track.id, clip.id) in detached_owners:
                continue
            linked_clip = owned.get(clip.id) if track.id in linked else clip
            if linked_clip is not None:
                append_layer(track,clip,sound,linked_clip,standalone=False)
    for track in project.audio_tracks:
        # Independent audio on an An lane has no video-instance owner.
        independent = track.id not in linked.values()
        for clip in track.clips:
            if independent or not clip.linked_video_clip_id:
                append_layer(track,clip,track,clip,standalone=True)
    boundaries = sorted({p for x in layers for p in (x['timeline_in_ms'],x['timeline_out_ms'])})
    graph = AudioPlaybackGraph()
    resolved = []
    solos = solo_track_ids(project)
    solos = frozenset(next((v for v,a in linked.items() if a==key),key) for key in solos)
    for start,end in zip(boundaries,boundaries[1:]):
        active = [x for x in layers if x['timeline_in_ms']<=start<x['timeline_out_ms']]
        master = effective_audio_master_track_id(project, tuple(x['track_id'] for x in active),
            selected_track_id=str(project.studio_state.get('selected_video_track_id') or ''))
        graph.configure(master_track_id='' if solos else master,solo_track_ids=solos)
        choice = graph.decide(active)
        ids = choice.mix_track_ids if choice.mix_mode else (choice.audible_track_id,)
        for layer in active:
            if layer['track_id'] not in ids or not layer['audio_enabled'] or layer['track_muted']:
                continue
            rate=layer['playback_rate']
            resolved.append({**layer,'source_in_ms':layer['source_in_ms']+round((start-layer['timeline_in_ms'])*rate),
                'source_out_ms':min(layer['source_out_ms'],layer['source_in_ms']+round((end-layer['timeline_in_ms'])*rate)),
                'timeline_in_ms':start,'timeline_out_ms':end})
    return {'version':1,'inputs':layers,'segments':resolved,'solo_track_ids':sorted(solos),
            'mix_order':list(dict.fromkeys(x['track_id'] for x in layers)),
            'pitch':'preserve','preview_rate_in_graph':False,'clip_transitions':transition_records(project, 'audio')}


def preview_audio_layers(graph, timeline_ms):
    return [{**layer,'project_ms':int(timeline_ms),'source_ms':layer['source_in_ms']+round((timeline_ms-layer['timeline_in_ms'])*layer['playback_rate'])}
            for layer in graph['segments'] if layer['timeline_in_ms']<=timeline_ms<layer['timeline_out_ms']]
