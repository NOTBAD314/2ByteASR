"""Request-scoped speaker identities and timestamp-based MOSS fusion."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def label_summary(rows):
    """Bounded identity counts without transcript text or fabricated defaults."""
    counts = {}
    missing = 0
    for row in rows:
        label = row.get('speaker') if isinstance(row, dict) else getattr(row, 'speaker', None)
        if label is None or not str(label).strip():
            missing += 1
            continue
        label = str(label)
        counts[label] = counts.get(label, 0) + 1
    return {'labels': counts, 'identity_count': len(counts), 'missing_labels': missing}


def save_speaker_evidence(root, name, payload):
    if not root:
        return
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    from .theme_persistence import write_text_atomic
    write_text_atomic(path / (name + ".json"), json.dumps(public_evidence(payload), ensure_ascii=False, indent=2))


def public_evidence(value, key=''):
    if key.lower() in {'api_key','api_secret','authorization','cookie','access_token','secret'}:
        return '[REDACTED]'
    if isinstance(value, dict):
        return {str(k):public_evidence(v, str(k)) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [public_evidence(v) for v in value]
    if isinstance(value,str) and value.startswith(('https://','http://','wss://')):
        parts=urlsplit(value)
        return urlunsplit((parts.scheme,parts.netloc.rsplit('@',1)[-1],parts.path,'',''))
    return value


def public_request(endpoint, **fields):
    url = urlsplit(endpoint.get("url", ""))
    return {"model": endpoint.get("model"), "protocol": endpoint.get("protocol"),
            "url": urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], url.path, "", "")), **fields}


def scope_request_speakers(rows, request_index, request_count):
    result = copy.deepcopy(rows)
    for row in result:
        speaker = row.get("speaker")
        row["speaker_evidence"] = {"local_speaker": speaker, "request_index": request_index,
            "scope": "request", "identity_confirmed": False,
            "granularity": "provider_phrase" if speaker is not None else "unavailable"}
        if speaker is not None and request_count > 1:
            row["speaker"] = f"R{request_index + 1:03d}_{speaker}"
        elif speaker is not None:
            # Provider speaker 0 is a real label; reserve S00 for unassigned.
            row["speaker"] = f"API_{speaker}"
        elif speaker is None:
            row["speaker"] = "S00"
    return result


def fuse_moss_speakers(references, moss_rows):
    """Keep API text; split at acoustic word or exact phrase boundaries.

    Conflicting acoustic evidence remains unassigned. Majority voting on an
    entire long sentence would erase short replies from another speaker.
    """
    output = []
    expanded = []
    for row in references:
        expanded.extend(_split_exact_moss_phrases(row, moss_rows))
    for row in expanded:
        words = row.get("tokens") or []
        groups = []
        for unit in words or [row]:
            start, end = float(unit["start"]), float(unit["end"])
            spans = {}
            for moss in moss_rows:
                overlap = max(0., min(end,float(moss["end"]))-max(start,float(moss["start"])))
                if overlap > 0:
                    raw_speaker = moss.get("speaker")
                    key = str(raw_speaker) if raw_speaker is not None else "S00"
                    spans[key] = max(spans.get(key,0.),overlap)
            strong = [s for s,seconds in spans.items() if seconds >= .5*max(.001,end-start)]
            certain = len(strong) == 1 and (bool(words) or len(spans) == 1)
            speaker = strong[0] if certain else "S00"
            key = (speaker, tuple(sorted(spans)) if not certain else ())
            if not groups or groups[-1][0] != key:
                groups.append((key,[]))
            groups[-1][1].append(unit)
        for (speaker,candidates), units in groups:
            item = copy.deepcopy(row)
            item.update(start=min(float(w["start"]) for w in units),
                        end=max(float(w["end"]) for w in units),speaker=speaker)
            if words:
                item["tokens"] = copy.deepcopy(units)
                item["text"] = "".join(str(w.get("text") or w.get("word") or "") for w in units)
            item["speaker_evidence"] = {"source":"moss", "candidates":list(candidates),
                                       "needs_confirmation":bool(candidates) or speaker == "S00"}
            output.append(item)
    return output


def _split_exact_moss_phrases(row, moss_rows):
    """Split untimed API text only at exactly matching acoustic phrase boundaries.

    No proportional pseudo-word timing: disagreement or overlapping speech
    retains the original row for the uncertain-speaker path above.
    """
    from .caption_arbitration import content
    if row.get('tokens'):
        return [row]
    candidates = sorted([r for r in moss_rows if min(float(r['end']),float(row['end'])) >
                         max(float(r['start']),float(row['start']))], key=lambda r:float(r['start']))
    if len({str(r.get('speaker')) for r in candidates}) < 2:
        return [row]
    if any(float(a['end']) > float(b['start']) for a,b in zip(candidates,candidates[1:])):
        return [row]
    text = str(row.get('text') or '')
    if not text or ''.join(content(r.get('text','')) for r in candidates) != content(text):
        return [row]
    output = []
    cursor = 0
    for index, segment in enumerate(candidates):
        amount = len(content(segment.get('text','')))
        if amount == 0:
            return [row]
        end = cursor
        while end < len(text) and len(content(text[cursor:end])) < amount:
            end += 1
        while end < len(text) and not content(text[end]):
            end += 1
        if index == len(candidates)-1:
            end = len(text)
        item = copy.deepcopy(row)
        item.update(text=text[cursor:end], start=max(float(row['start']),float(segment['start'])),
                    end=min(float(row['end']),float(segment['end'])))
        item['alignment_evidence'] = 'exact_transcript_moss_phrase_boundary'
        output.append(item)
        cursor = end
    return output


def needs_moss_speakers(mode, references):
    # Full ASR is deliberately opt-in; missing native tags are not permission
    # to transcribe the same task again.
    return mode == 'moss'
