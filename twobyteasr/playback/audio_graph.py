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


def _stream_start_ms(asset, ordinal):
    """Late start of a further audio stream; 0 for the first (as before)."""
    if ordinal <= 0:
        return 0.
    from ..media.audio_streams import stream_by_ordinal
    row = stream_by_ordinal(asset, ordinal)
    return max(0., float(row.get('start_ms') or 0.)) if row else 0.


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
            stream_start_ms=_stream_start_ms(asset, int(getattr(linked_clip,'stream_index',0))),
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
    followers = [t for t in project.audio_tracks if getattr(t, 'stream_ordinal', -1) >= 0]
    videos = {t.id: t for t in project.video_tracks}
    for lane in followers:
        # 2026-10-24: a further audio stream of the video track's clips. It
        # routes as its own lane (mute/solo/mix by lane id), timed by the clip.
        video = videos.get(lane.linked_video_track_id)
        if video is None:
            continue
        owned = {c.linked_video_clip_id: c for c in lane.clips if c.linked_video_clip_id}
        for clip in video.clips:
            if clip.id in owned:
                before = len(layers)
                append_layer(video, clip, lane, owned[clip.id], standalone=False)
                if len(layers) > before:
                    # Only its own mute: muting A1 (stored on the video lane)
                    # is how a user switches to another dub, not a mute of all.
                    layers[-1].update(track_id=lane.id, audio_track_id=lane.id, track_name=lane.name,
                                      track_muted=bool(lane.muted))
    for track in project.audio_tracks:
        if getattr(track, 'stream_ordinal', -1) >= 0:
            continue
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


def audio_lane_ids(project):
    """Audio lanes in timeline order, by the id the routing uses for each."""
    linked = {g.audio_track_id: g.video_track_id for g in project.av_track_groups if g.linked and g.video_track_id}
    return [(t.id, linked.get(t.id, t.id)) for t in project.audio_tracks]


def capture_lane_audio_graph(project, lane_id):
    """The graph of exactly one audio lane, for recognizing or auditioning it.

    The user picked this lane on purpose, so monitoring state does not apply:
    its own mute, other lanes' solo, clip-audio switches and the master
    choice are ignored. The edit still does: disabled video tracks and clips
    stay out, gaps stay silent, speed and crossfades are kept.
    """
    import copy
    lane_id = str(lane_id)
    working = copy.deepcopy(project)
    lane = next((t for t in working.audio_tracks if t.id == lane_id), None)
    if lane is None:
        raise KeyError(lane_id)
    group = next((g for g in working.av_track_groups if g.audio_track_id == lane_id), None)
    owner_ids = {group.video_track_id} if group is not None and group.linked and group.video_track_id else set()
    if getattr(lane, 'stream_ordinal', -1) >= 0:
        owner_ids.add(lane.linked_video_track_id)
    for track in working.audio_tracks:
        track.muted = track.id != lane_id
        track.soloed = False
    for track in working.video_tracks:
        track.soloed = False
        # A video lane's own audio counts only when it is the picked lane.
        track.muted = track.id not in owner_ids
        if track.id in owner_ids:
            for clip in track.clips:
                clip.audio_enabled = True
    lane.enabled = True
    for clip in lane.clips:
        clip.enabled = True
    state = working.studio_state
    state['audio_solo_track_ids'] = []
    state['audio_master_mode'] = 'mix_all'
    graph = capture_audio_graph(working)
    route_id = next((video for audio, video in audio_lane_ids(working) if audio == lane_id), lane_id)
    graph['segments'] = [s for s in graph['segments'] if s['track_id'] in {lane_id, route_id}
                         and s.get('audio_track_id', s['track_id']) in {lane_id, route_id}]
    graph['lane_id'] = lane_id
    return graph


def preview_audio_layers(graph, timeline_ms):
    return [{**layer,'project_ms':int(timeline_ms),'source_ms':layer['source_in_ms']+round((timeline_ms-layer['timeline_in_ms'])*layer['playback_rate'])}
            for layer in graph['segments'] if layer['timeline_in_ms']<=timeline_ms<layer['timeline_out_ms']]
