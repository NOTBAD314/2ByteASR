"""Download segment onset anchors, kept separate from measured acoustic words.

YouTube automatic captions give one segment per word with its start time;
those onsets become the caption's words (``onset_words``, 2026-10-26)."""
from __future__ import annotations
import copy

SENTENCE_TIMING = "downloaded_sentence_or_segment_start"


def single_word(text, start_ms, end_ms, evidence_ref):
    """An automatic caption row that is one space-separated word ("wearing"):
    YouTube sends it as one segment without an offset, so it starts with its
    row. Chinese / Japanese rows are never one word."""
    import unicodedata
    stripped = text.strip()
    if not stripped or any(ch.isspace() or unicodedata.east_asian_width(ch) in ("W", "F") for ch in stripped):
        return []
    lo = text.index(stripped)
    return [dict(text=stripped, char_start=lo, char_end=lo + len(stripped), start_ms=int(start_ms),
                 end_ms=int(end_ms), evidence_ref=evidence_ref)]


def onset_words(text, anchors, start_ms, end_ms, evidence_ref):
    """Words of a downloaded caption from its segment onsets, or [].

    Only when every word of ``text`` starts at a known onset; a word ends where
    the next one starts (the caption's end for the last) because the source
    gives no word ends. Punctuation-only segments are not words; two segments
    starting at the same moment become one word."""
    from ..recognition.cue_word_alignment import content_positions
    rows = []
    for anchor in sorted(anchors, key=lambda a: (int(a["char_start"]), int(a["start_ms"]))):
        lo, hi = int(anchor["char_start"]), int(anchor["char_end"])
        while lo < hi and text[lo].isspace():
            lo += 1
        while hi > lo and text[hi-1].isspace():
            hi -= 1
        if hi <= lo or not content_positions(text[lo:hi]):
            continue
        onset = min(max(int(anchor["start_ms"]), int(start_ms)), int(end_ms) - 1)
        if rows and onset < rows[-1]["start_ms"]:
            return []   # onsets out of text order: not a word stream
        if rows and (onset == rows[-1]["start_ms"] or lo < rows[-1]["char_end"]):
            rows[-1]["char_end"] = max(rows[-1]["char_end"], hi)
            continue
        rows.append(dict(char_start=lo, char_end=hi, start_ms=onset,
                         interval_end=anchor.get("end_ms") if anchor.get("precision") == "segment_interval" else None))
    if not rows:
        return []
    covered = set()
    for row in rows:
        covered.update(range(row["char_start"], row["char_end"]))
    if any(index not in covered for index, _char in content_positions(text)):
        return []
    words = []
    for index, row in enumerate(rows):
        end = rows[index+1]["start_ms"] if index + 1 < len(rows) else int(end_ms)
        if row["interval_end"] is not None and row["start_ms"] < int(row["interval_end"]) < end:
            end = int(row["interval_end"])
        if end <= row["start_ms"]:
            return []
        words.append(dict(text=text[row["char_start"]:row["char_end"]], char_start=row["char_start"],
                          char_end=row["char_end"], start_ms=row["start_ms"], end_ms=end,
                          evidence_ref=evidence_ref))
    return words


def cue_start_anchors(project, cue):
    if project is None:
        return []
    receipt = project.studio_state.get("caption_timeline", {}).get("instances", {}).get(cue.id, {})
    if receipt.get("anchor_base_text") != cue.text:
        return []  # A text edit must not keep stale character indexes.
    base = receipt.get("anchor_base_interval", ())
    if len(base) != 2 or cue.end_ms-cue.start_ms != base[1]-base[0]:
        return []  # Trimming/stretching needs a new explicit mapping.
    delta = cue.start_ms-base[0]
    return [dict(row, start_ms=row["start_ms"]+delta,
                 **({"end_ms":row["end_ms"]+delta} if "end_ms" in row else {})) for row in receipt.get("segment_anchors", [])
            if cue.start_ms <= row["start_ms"]+delta < cue.end_ms
            and cue.text[row["char_start"]:row["char_end"]] == row["text"]]


def split_at_source_starts(project, cue, indices):
    anchors = cue_start_anchors(project, cue)
    times = []
    for index in indices:
        right = next((a for a in anchors if a["char_start"] >= index+1
                      and not cue.text[index+1:a["char_start"]].strip()), None)
        if right is None:
            return []
        times.append(right["start_ms"])
    bounds = [cue.start_ms, *times, cue.end_ms]
    if any(b-a < 50 for a, b in zip(bounds, bounds[1:])):
        return []
    return list(zip(bounds, bounds[1:]))


def inherit_start_anchors(project, removed, inserted, after):
    """Only a text-conserving split/merge can inherit source start indexes."""
    if "".join(c.text for c in removed) != "".join(c.text for c in inserted):
        return
    anchors, offset = [], 0
    for cue in removed:
        anchors.extend(dict(a, char_start=a["char_start"]+offset, char_end=a["char_end"]+offset)
                       for a in cue_start_anchors(project, cue))
        offset += len(cue.text)
    offset = 0
    for cue in inserted:
        rows = [dict(a, char_start=a["char_start"]-offset, char_end=a["char_end"]-offset)
                for a in anchors if offset <= a["char_start"] < a["char_end"] <= offset+len(cue.text)
                and cue.start_ms <= a["start_ms"] < cue.end_ms]
        if rows and after.get(cue.id) is not None:
            after[cue.id].update(segment_anchors=copy.deepcopy(rows),
                anchor_base_text=cue.text, anchor_base_interval=[cue.start_ms, cue.end_ms])
        offset += len(cue.text)


def _follow_words(receipt, old, original, cue, complete):
    """Downloaded word onsets move with their caption; a cut or retimed
    caption falls back to sentence timing instead of keeping stale words."""
    from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS
    if old.get("word_alignment") != DOWNLOADED_WORD_ONSETS or not old.get("words"):
        return
    if complete and cue.end_ms - cue.start_ms == original.end_ms - original.start_ms:
        delta = cue.start_ms - original.start_ms
        words = [dict(w, start_ms=w["start_ms"]+delta, end_ms=w["end_ms"]+delta) for w in old["words"]]
        alignment = DOWNLOADED_WORD_ONSETS
    else:
        words, alignment = [], SENTENCE_TIMING
    receipt.update(words=words, word_alignment=alignment, word_base_words=copy.deepcopy(words),
                   word_base_interval=[cue.start_ms, cue.end_ms], word_base_alignment=alignment,
                   word_clock_offset_ms=0)


def remap_download_captions(before, after):
    """Follow only download-bound instances; unrelated independent captions stay put.

    A manual timing edit detaches the follow behavior. Razor-only adjacent
    instances remain one sentence; discontinuous/trimmed sentences get review
    rather than fabricated text or duplicated words.
    """
    from .clip_time_mapper import source_to_project
    from .studio_edit_sequence import sequence_of
    old_cues = {cue.id: cue for cue in before.cues}
    old_receipts = before.studio_state.get("caption_timeline", {}).get("instances", {})
    receipts = after.studio_state.get("caption_timeline", {}).get("instances", {})
    clips = [c for t in after.video_tracks for c in t.clips]
    lineage = sequence_of(after).segment_lineage
    review = []
    for cue in after.cues:
        original = old_cues.get(cue.id)
        receipt = receipts.get(cue.id, {})
        link = old_receipts.get(cue.id, {}).get("link_follow")
        if not link or original is None:
            continue
        if list(link["timeline_interval"]) != [original.start_ms, original.end_ms]:
            receipt.pop("link_follow", None)
            continue
        source_lo, source_hi = link["source_interval"]
        matches = [c for c in clips if c.asset_id == link["asset_id"]
                   and (c.id == link["clip_id"] or link["clip_id"] in lineage.get(c.id, []))]
        spans = []
        for clip in matches:
            a,b=max(source_lo,clip.source_in_ms),min(source_hi,clip.source_out_ms)
            if b>a:
                spans.append((a,b,source_to_project(clip,a),source_to_project(clip,b),clip))
        spans.sort(key=lambda s:s[0])
        complete = bool(spans) and spans[0][0]==source_lo and spans[-1][1]==source_hi and all(
            a[1]==b[0] and abs(a[3]-b[2])<=1 for a,b in zip(spans,spans[1:]))
        if not spans:
            # Removed media: preserve current text for review, never silently delete it.
            receipt["review"]="download_media_removed_needs_text_review"
            review.append(cue.id)
            receipt.pop("link_follow", None)
            continue
        selected = spans if complete else [max(spans,key=lambda s:s[1]-s[0])]
        cue.start_ms,cue.end_ms=selected[0][2],selected[-1][3]
        if not complete:
            receipt["review"]="download_clip_cut_needs_text_review"
            review.append(cue.id)
        _follow_words(receipt, old_receipts.get(cue.id, {}), original, cue, complete)
        mapped = []
        for anchor in cue_start_anchors(before,original):
            # Source anchors persisted at import; an onset remains a point.
            source = anchor.get("source_start_ms")
            owner = next((s for s in selected if source is not None and s[0]<=source<s[1]),None)
            if owner:
                value = dict(anchor,start_ms=source_to_project(owner[4],source))
                if "end_ms" in value:
                    source_end = value.get("source_end_ms")
                    end_owner = next((s for s in selected if source_end is not None and s[0]<source_end<=s[1]),None)
                    if end_owner:
                        value["end_ms"] = source_to_project(end_owner[4],source_end)
                    else:
                        value.pop("end_ms",None);value["precision"]="segment_start"
                mapped.append(value)
        receipt.update(segment_anchors=mapped,anchor_base_interval=[cue.start_ms,cue.end_ms],
                       anchor_base_text=original.text)
        receipt["link_follow"] = dict(link,timeline_interval=[cue.start_ms,cue.end_ms])
    after.studio_state["link_import_clip_review"] = review
