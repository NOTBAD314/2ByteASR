"""Main / secondary speaker classification for timeline grouping (2026-10-12, v2 2026-10-13).

Editing convenience, not story analysis: a "main" speaker talks often within
some stretch of the media and keeps an own timeline track; the others share
one collapsed "secondary" track. Speaker identity, cue ownership, styles and
exports never change.

Rule (one sentence each, all in ``explain``):

* Long media (>= 10 min): a candidate when, in some 10-minute stretch
  (sliding, not fixed blocks), the speaker has more than 10 utterances, or
  speaks for at least 90 s in that stretch (a long monologue is one
  utterance).
* 1-10 min: the stretch is the whole media; the count threshold scales with
  length (more than 10 x minutes / 10, at least 2), speech at least 15 % of
  the media (at least 20 s).
* Shorter than 1 min: a candidate with 2 utterances or 15 % of all speech (at
  least 3 s); with 3 or fewer speakers everyone is main.
* At most 5 candidates (the project's cap: 3, 5 or 8) become main, ranked by
  utterances in their busiest stretch, then speech; the speaker with the most
  speech is always main.

Utterances are counted from the recognition's source segments (``segment:N``
evidence refs), so one sentence split into three cues counts once, and a
translation never counts. Cues without source segments (hand-made) merge with
the same speaker's neighbour when the gap is under 300 ms. Repeated text of
the same speaker within 1 s (overlapping chunk duplicates) counts once.
Manual choices ("main", "secondary", "own" = always an own track) win.
"""
from __future__ import annotations

import bisect
import re

POLICY = "speaker-roles-v2"
WINDOW_MS = 600_000
COUNT_ABOVE = 10
SPEECH_MS = 90_000
MAIN_CAP = 5
CAP_CHOICES = (3, 5, 8)
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
    """{"policy", "media_ms", "rule", "cap", "speakers": {id: {role, source, utterances, peak_count, peak_speech_ms}}}"""
    manual = {str(k): v for k, v in (manual or {}).items() if v in MANUAL_ROLES}
    spans = utterances(cues)
    media_ms = max(1, int(media_ms or 0), max((e for v in spans.values() for _, e in v), default=0))
    total_speech = sum(e - s for v in spans.values() for s, e in v) or 1
    if media_ms >= WINDOW_MS:
        window, count_above, speech_ms = WINDOW_MS, COUNT_ABOVE, SPEECH_MS
        rule = f"10 分钟滑动区间内发言超过 10 次，或该区间内说话至少 {SPEECH_MS // 1000} 秒"
    elif media_ms >= SHORT_MS:
        window = media_ms
        count_above = max(2, round(COUNT_ABOVE * media_ms / WINDOW_MS))
        speech_ms = max(20_000, round(0.15 * media_ms))
        rule = f"全片（{media_ms / 60000:.1f} 分钟）发言超过 {count_above} 次，或说话至少 {speech_ms / 1000:.0f} 秒"
    else:
        window, count_above, speech_ms = media_ms, 1, None
        rule = "短片：至少 2 次发言或占全部说话的 15%（至少 3 秒）；3 位以内说话人全部保留独立轨"
    cap = int(cap) if cap else None
    if cap:
        rule += f"；最多 {cap} 位主要角色（按最忙区间的发言次数排序）"
    result = {}
    for speaker, items in spans.items():
        count, speech = _peak(items, window)
        if speech_ms is None:
            main = count > count_above or speech >= max(3_000, 0.15 * total_speech) or len(spans) <= 3
        else:
            main = count > count_above or speech >= speech_ms
        result[speaker] = dict(role="main" if main else "secondary", source="auto", utterances=len(items),
                               peak_count=count, peak_speech_ms=speech)
    if result and not any(v["role"] == "main" for v in result.values()):
        top = max(result, key=lambda key: (result[key]["peak_speech_ms"], result[key]["utterances"]))
        result[top].update(role="main", note="most speech")
    if cap:
        # Keep the busiest candidates; the speaker with the most speech stays main.
        ranked = sorted((key for key, row in result.items() if row["role"] == "main"),
                        key=lambda key: (-result[key]["peak_count"], -result[key]["peak_speech_ms"], key))
        top_speech = max(result, key=lambda key: (result[key]["peak_speech_ms"], result[key]["utterances"]))
        keep = set(ranked[:cap])
        if top_speech not in keep:
            keep = set(ranked[:cap - 1]) | {top_speech}
        for key in ranked:
            if key not in keep:
                result[key].update(role="secondary", note="over cap")
    for speaker, role in manual.items():
        row = result.setdefault(speaker, dict(utterances=0, peak_count=0, peak_speech_ms=0))
        row.update(role=role, source="manual")
    return dict(policy=POLICY, media_ms=media_ms, rule=rule, window_ms=window, cap=cap, speakers=result)


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


def decide(project, *, manual=None, expanded=False, source="organize", cap=None) -> dict:
    """A fresh role state for ``project`` (classification + kept manual roles).

    ``cap``: automatic main tracks (CAP_CHOICES); default the project's last
    choice, else MAIN_CAP."""
    previous = state_of(project)
    manual = dict(manual if manual is not None else previous.get("manual") or {})
    cap = int(cap or previous.get("cap") or MAIN_CAP)
    result = classify(project.cues, media_ms_of(project), manual=None, cap=cap)
    auto = {key: row["role"] for key, row in result["speakers"].items()}
    return dict(policy=POLICY, grouped=True, expanded=bool(expanded), auto=auto, manual=manual, cap=cap,
                rule=result["rule"], media_ms=result["media_ms"], source=source,
                counts={key: dict(utterances=row["utterances"], peak_count=row["peak_count"],
                                  peak_speech_ms=row["peak_speech_ms"])
                        for key, row in result["speakers"].items()})


def initialize_for_recognition(project) -> None:
    """New projects from a recognition start grouped (nothing the user arranged)."""
    if KEY not in project.studio_state and project.cues:
        project.studio_state[KEY] = decide(project, manual={}, source="recognition")
