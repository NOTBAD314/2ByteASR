"""Main / secondary speaker classification for timeline grouping (2026-10-12, v3 2026-10-22).

Editing convenience, not story analysis: a "main" speaker keeps an own
timeline track; the others share one collapsed "secondary" track. Speaker
identity, cue ownership, styles and exports never change.

Rule (one sentence each, all in ``explain``):

* The speakers with the most subtitles keep an own track: 2 by default (the
  「默认独立字幕轨」 preference, or the project's own choice: 1, 2, 3, 5 or 8).
* Ties go to the speaker with more speech; everyone else shares one track.

Speech (the tie-break) is measured over utterances counted from the
recognition's source segments (``segment:N``
evidence refs), so one sentence split into three cues counts once, and a
translation never counts. Cues without source segments (hand-made) merge with
the same speaker's neighbour when the gap is under 300 ms. Repeated text of
the same speaker within 1 s (overlapping chunk duplicates) counts once.
Manual choices ("main", "secondary", "own" = always an own track) win.

2026-10-22 (user): v2 kept every speaker that was busy somewhere (more than
10 utterances or 90 s in a 10-minute stretch, at most 5), which on a
26-speaker episode still left five speaker rows plus the group above the
translation row. Projects grouped automatically by v1/v2 are regrouped by
this rule when opened (``refresh_automatic_roles``); a cap the user picked
and manual roles are kept.
"""
from __future__ import annotations

import bisect
import re

POLICY = "speaker-roles-v3"
WINDOW_MS = 600_000
COUNT_ABOVE = 10
SPEECH_MS = 90_000
MAIN_CAP = 2
CAP_CHOICES = (1, 2, 3, 5, 8)
SHORT_MS = 60_000
MERGE_GAP_MS = 300
MANUAL_ROLES = ("main", "secondary", "own")
KEY = "speaker_roles"          # studio_state key
GROUP_KEY = "@secondary"       # timeline row id of the shared group


def _segment_refs(cue):
    return tuple(sorted(str(ref) for ref in (getattr(cue, "evidence_refs", None) or ()) if str(ref).startswith("segment:")))


def utterances(cues) -> dict[str, list[tuple[int, int]]]:
    """Per speaker: (start_ms, end_ms) of each effective utterance."""
    by_speaker: dict[str, list] = {}
    for cue in sorted(cues, key=lambda c: (int(c.start_ms), int(c.end_ms))):
        by_speaker.setdefault(str(cue.speaker_id), []).append(cue)
    out: dict[str, list[tuple[int, int]]] = {}
    for speaker, items in by_speaker.items():
        spans: dict[str, list[int]] = {}
        loose: list[list[int]] = []
        last_text: dict[str, int] = {}
        for cue in items:
            start, end = int(cue.start_ms), int(cue.end_ms)
            text = re.sub(r"\s+", "", str(getattr(cue, "text", "") or ""))
            if text and text in last_text and start - last_text[text] <= 1000:
                continue                                   # duplicated chunk output
            last_text[text] = end
            refs = _segment_refs(cue)
            if refs:
                for ref in refs:
                    span = spans.setdefault(ref, [start, end])
                    span[0], span[1] = min(span[0], start), max(span[1], end)
            elif loose and start - loose[-1][1] < MERGE_GAP_MS:
                loose[-1][1] = max(loose[-1][1], end)
            else:
                loose.append([start, end])
        out[speaker] = sorted([tuple(v) for v in spans.values()] + [tuple(v) for v in loose])
    return out


def _peak(spans, window_ms):
    """Most utterances starting in any window, and most speech (ms) of those."""
    starts = [s for s, _ in spans]
    best_count = best_speech = 0
    for index, (start, _) in enumerate(spans):
        last = bisect.bisect_left(starts, start + window_ms)
        inside = spans[index:last]
        best_count = max(best_count, len(inside))
        best_speech = max(best_speech, sum(max(0, e - s) for s, e in inside))
    return best_count, best_speech


def classify(cues, media_ms: int, manual=None, cap: int | None = MAIN_CAP) -> dict:
    """{"policy", "media_ms", "rule", "cap", "speakers": {id: {role, source, utterances, peak_count, peak_speech_ms}}}

    ``utterances`` / ``peak_count``: subtitles of the speaker (``peak_count``
    kept for older readers); ``peak_speech_ms``: all their speech."""
    manual = {str(k): v for k, v in (manual or {}).items() if v in MANUAL_ROLES}
    spans = utterances(cues)
    media_ms = max(1, int(media_ms or 0), max((e for v in spans.values() for _, e in v), default=0))
    counts: dict[str, int] = {}
    for cue in cues:
        counts[str(cue.speaker_id)] = counts.get(str(cue.speaker_id), 0) + 1
    cap = max(1, int(cap)) if cap else MAIN_CAP
    rule = f"字幕最多的 {cap} 位说话人各占一条轨，其余说话人合成一条轨"
    speech = {speaker: sum(max(0, e - s) for s, e in items) for speaker, items in spans.items()}
    ranked = sorted(spans, key=lambda key: (-counts.get(key, 0), -speech[key], key))
    keep = set(ranked[:cap])
    result = {speaker: dict(role="main" if speaker in keep else "secondary", source="auto",
                            utterances=counts.get(speaker, 0), peak_count=counts.get(speaker, 0),
                            peak_speech_ms=speech[speaker])
              for speaker in spans}
    for speaker in ranked[cap:]:
        result[speaker]["note"] = "over cap"
    for speaker, role in manual.items():
        row = result.setdefault(speaker, dict(utterances=0, peak_count=0, peak_speech_ms=0))
        row.update(role=role, source="manual")
    return dict(policy=POLICY, media_ms=media_ms, rule=rule, window_ms=media_ms, cap=cap, speakers=result)


def explain() -> str:
    return __doc__.split("Rule (one sentence each, all in ``explain``):", 1)[1].split("Utterances are counted", 1)[0].strip()


# ---- project role state (studio_state["speaker_roles"]) ----

def state_of(project) -> dict:
    value = (project.studio_state or {}).get(KEY) if project is not None else None
    return value if isinstance(value, dict) else {}


def media_ms_of(project) -> int:
    ends = [clip.timeline_out_ms for track in getattr(project, "video_tracks", ()) for clip in track.clips]
    ends += [clip.timeline_out_ms for track in getattr(project, "audio_tracks", ()) for clip in track.clips]
    ends += [cue.end_ms for cue in project.cues]
    return max(ends, default=0)


def effective_roles(project) -> dict[str, str]:
    """Role per speaker present in the project: manual, else snapshot, else main."""
    state = state_of(project)
    auto = state.get("auto") if isinstance(state.get("auto"), dict) else {}
    manual = state.get("manual") if isinstance(state.get("manual"), dict) else {}
    ids = list(dict.fromkeys([s.id for s in project.speakers] + [c.speaker_id for c in project.cues]))
    return {key: str(manual.get(key) or auto.get(key) or "main") for key in ids}


def group_members(project) -> tuple[str, ...]:
    """Speakers drawn in the shared secondary row (empty: no group)."""
    state = state_of(project)
    if not state.get("grouped"):
        return ()
    members = tuple(key for key, role in effective_roles(project).items() if role == "secondary")
    return members if len(members) >= 2 else ()


def decide(project, *, manual=None, expanded=False, source="organize", cap=None, default_cap=None) -> dict:
    """A fresh role state for ``project`` (classification + kept manual roles).

    ``cap``: a limit the user picks now (saved as the project's own choice).
    Otherwise the project's own earlier choice, else ``default_cap`` (the
    preference), else MAIN_CAP."""
    previous = state_of(project)
    manual = dict(manual if manual is not None else previous.get("manual") or {})
    chosen = bool(cap) or bool(previous.get("cap_chosen"))
    cap = int(cap or (previous.get("cap") if previous.get("cap_chosen") else None) or default_cap or MAIN_CAP)
    result = classify(project.cues, media_ms_of(project), manual=None, cap=cap)
    auto = {key: row["role"] for key, row in result["speakers"].items()}
    return dict(policy=POLICY, grouped=True, expanded=bool(expanded), auto=auto, manual=manual, cap=cap,
                cap_chosen=chosen, rule=result["rule"], media_ms=result["media_ms"], source=source,
                counts={key: dict(utterances=row["utterances"], peak_count=row["peak_count"],
                                  peak_speech_ms=row["peak_speech_ms"])
                        for key, row in result["speakers"].items()})


def initialize_for_recognition(project, cap=None) -> None:
    """New projects from a recognition start grouped (nothing the user arranged)."""
    if KEY not in project.studio_state and project.cues:
        project.studio_state[KEY] = decide(project, manual={}, source="recognition", default_cap=cap)


def refresh_automatic_roles(project, cap) -> bool:
    """Regroup a project grouped automatically under an older rule or another
    default (``cap``: the 「默认独立字幕轨」 preference). Manual roles, a cap
    the user picked, ungrouped and never-grouped projects stay as they are."""
    state = state_of(project)
    if not state or not state.get("grouped") or state.get("cap_chosen") or not project.cues:
        return False
    cap = int(cap or MAIN_CAP)
    if state.get("policy") == POLICY and int(state.get("cap") or 0) == cap:
        return False
    project.studio_state[KEY] = decide(project, expanded=bool(state.get("expanded")),
                                       source="refresh", default_cap=cap)
    return True
