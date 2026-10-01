"""Canonical ASR result contracts shared by isolated workers and the pipeline.

Worker protocols are allowed to be model-specific at their process boundary.
After that boundary, the pipeline only accepts a flat ``segments`` sequence.
The helpers in this module deliberately keep shape diagnostics bounded so a
schema failure cannot dump a transcript into the run report.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


# Version 2 makes the wrapper mandatory at model-adapter boundaries.  Stage 5
# receives a separately flattened token sequence, never the worker wrapper.
ASR_RESULT_SCHEMA_VERSION = 2
CANONICAL_SEGMENT_FIELDS = ("start", "end", "text")


class SchemaContractError(TypeError):
    """Raised when a producer sends a value outside its consumer contract."""

    def __init__(
        self,
        *,
        producer: str,
        consumer: str,
        received: Any,
        expected_schema: str,
        sample_shape: Any | None = None,
    ) -> None:
        self.producer = str(producer)
        self.consumer = str(consumer)
        self.received_type = type(received).__name__
        self.expected_schema = str(expected_schema)
        self.sample_shape = schema_shape(received) if sample_shape is None else sample_shape
        super().__init__(
            f"ASR schema contract failed: producer={self.producer}; "
            f"consumer={self.consumer}; received_type={self.received_type}; "
            f"expected_schema={self.expected_schema}; sample_shape={self.sample_shape}"
        )


def schema_shape(value: Any, *, max_items: int = 3) -> dict[str, Any]:
    """Return bounded type/shape information without transcript contents."""
    shape: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, Mapping):
        keys = [str(key) for key in value.keys()]
        shape["keys"] = keys[:max_items]
        shape["key_count"] = len(keys)
        if "segments" in value:
            rows = value.get("segments")
            shape["segments_type"] = type(rows).__name__
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                shape["segments_len"] = len(rows)
                if rows:
                    shape["first_item"] = _item_shape(rows[0], max_items=max_items)
        if "results" in value:
            rows = value.get("results")
            shape["results_type"] = type(rows).__name__
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                shape["results_len"] = len(rows)
                if rows:
                    shape["first_result"] = _item_shape(rows[0], max_items=max_items)
        if "chunks" in value:
            rows = value.get("chunks")
            shape["chunks_type"] = type(rows).__name__
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                shape["chunks_len"] = len(rows)
                if rows:
                    shape["first_chunk"] = _item_shape(rows[0], max_items=max_items)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        shape["len"] = len(value)
        if value:
            shape["first_item"] = _item_shape(value[0], max_items=max_items)
    return shape


def _item_shape(value: Any, *, max_items: int = 3) -> dict[str, Any]:
    if isinstance(value, Mapping):
        keys = [str(key) for key in value.keys()]
        return {"type": type(value).__name__, "keys": keys[:max_items], "key_count": len(keys)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result: dict[str, Any] = {"type": type(value).__name__, "len": len(value)}
        if value:
            result["first_item"] = _item_shape(value[0], max_items=max_items)
        return result
    return {"type": type(value).__name__}


def _raise_contract(producer: str, consumer: str, value: Any, expected: str) -> None:
    raise SchemaContractError(
        producer=producer,
        consumer=consumer,
        received=value,
        expected_schema=expected,
    )


def _validate_segment(row: Any, *, producer: str, consumer: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        _raise_contract(producer, consumer, row, "ASRSegment dict with start/end/text")
    missing = [field for field in CANONICAL_SEGMENT_FIELDS if field not in row]
    if missing:
        _raise_contract(
            producer,
            consumer,
            row,
            "ASRSegment dict with start/end/text (missing " + ",".join(missing) + ")",
        )
    try:
        start = float(row["start"])
        end = float(row["end"])
    except (TypeError, ValueError):
        _raise_contract(producer, consumer, row, "ASRSegment start/end are numeric")
    if end <= start:
        _raise_contract(producer, consumer, row, "ASRSegment end > start")
    text = str(row.get("text") or "").strip()
    if not text:
        _raise_contract(producer, consumer, row, "ASRSegment text is non-empty")
    normalized = dict(row)
    normalized.update({"start": start, "end": end, "text": text})
    return normalized


def validate_flat_segments(
    value: Any,
    *,
    producer: str,
    consumer: str,
    allow_empty: bool = True,
) -> list[dict[str, Any]]:
    """Validate an already-normalized flat segment sequence; never flatten it."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _raise_contract(producer, consumer, value, "Sequence[ASRSegment]")
    if not value and not allow_empty:
        _raise_contract(producer, consumer, value, "non-empty Sequence[ASRSegment]")
    return [
        _validate_segment(row, producer=producer, consumer=consumer)
        for row in value
    ]


def validate_canonical_result(
    value: Any,
    *,
    producer: str,
    consumer: str,
    allow_empty: bool = True,
) -> dict[str, Any]:
    """Validate a canonical ASRResult and return a shallow normalized copy."""
    if not isinstance(value, Mapping):
        _raise_contract(producer, consumer, value, "ASRResult dict with flat segments")
    segments = validate_flat_segments(
        value.get("segments"),
        producer=producer,
        consumer=consumer,
        allow_empty=allow_empty,
    )
    result = dict(value)
    result["segments"] = segments
    result.setdefault("schema_version", ASR_RESULT_SCHEMA_VERSION)
    result.setdefault("result_type", "ASRResult")
    result.setdefault("metadata", {})
    result.setdefault("provenance", {"producer": producer})
    return result


def canonical_result_from_segments(
    value: Any,
    *,
    producer: str,
    consumer: str,
    backend: str,
    language: str = "zh",
    allow_empty: bool = False,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap an already-flat adapter result in the one pipeline ASR schema."""
    segments = validate_flat_segments(
        value,
        producer=producer,
        consumer=consumer,
        allow_empty=allow_empty,
    )
    return {
        "schema_version": ASR_RESULT_SCHEMA_VERSION,
        "result_type": "ASRResult",
        "segments": segments,
        "language": str(language or "zh"),
        "metadata": {"backend": str(backend), "segment_count": len(segments)},
        "provenance": {
            "producer": producer,
            "normalization": "flat_segments_to_asr_result",
            **(dict(provenance) if isinstance(provenance, Mapping) else {}),
        },
    }


def normalize_moss_result(
    value: Any,
    *,
    producer: str = "moss_worker",
    consumer: str = "moss_pipeline",
) -> dict[str, Any]:
    """Normalize a merged MOSS payload once, after chunk merging is complete."""
    if not isinstance(value, Mapping):
        _raise_contract(producer, consumer, value, "MOSS ASRResult dict with flat segments")
    result = dict(value)
    result["segments"] = validate_flat_segments(
        result.get("segments"),
        producer=producer,
        consumer=consumer,
        allow_empty=False,
    )
    result.update(
        {
            "schema_version": ASR_RESULT_SCHEMA_VERSION,
            "result_type": "ASRResult",
            "metadata": {
                **(result.get("metadata") if isinstance(result.get("metadata"), Mapping) else {}),
                "backend": "moss",
                "segment_count": len(result["segments"]),
            },
            "provenance": {
                **(result.get("provenance") if isinstance(result.get("provenance"), Mapping) else {}),
                "producer": producer,
                "normalization": "merged_chunks_to_flat_segments",
            },
        }
    )
    return result


def normalize_firered_worker_result(
    value: Any,
    jobs: Sequence[Mapping[str, Any]],
    *,
    producer: str = "firered_aed_worker",
    consumer: str = "firered_adapter",
) -> dict[str, Any]:
    """Convert FireRed's per-job ``results`` wrapper to flat timed segments."""
    if not isinstance(value, Mapping):
        _raise_contract(producer, consumer, value, "FireRed worker dict with results list")
    rows = value.get("results")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        _raise_contract(producer, consumer, value, "FireRed worker results: list[dict]")
    segments: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _raise_contract(producer, consumer, row, "FireRed result dict")
        job = jobs[index] if index < len(jobs) else {}
        timestamps = row.get("timestamp") or []
        starts: list[float] = []
        ends: list[float] = []
        token_rows: list[dict[str, Any]] = []
        for timestamp in timestamps:
            if isinstance(timestamp, Mapping):
                token = timestamp.get("text", "")
                start = timestamp.get("start", 0.0)
                end = timestamp.get("end", 0.0)
            elif isinstance(timestamp, Sequence) and not isinstance(timestamp, (str, bytes, bytearray)) and len(timestamp) >= 3:
                token, start, end = timestamp[0], timestamp[1], timestamp[2]
            else:
                _raise_contract(producer, consumer, timestamp, "FireRed timestamp dict or [text,start,end]")
            try:
                local_start = float(start)
                local_end = float(end)
            except (TypeError, ValueError):
                _raise_contract(producer, consumer, timestamp, "FireRed timestamp numeric bounds")
            if local_end <= local_start or not str(token or "").strip():
                continue
            offset = float(job.get("offset", 0.0) or 0.0)
            global_start = offset + local_start
            global_end = offset + local_end
            starts.append(global_start)
            ends.append(global_end)
            token_rows.append({"text": str(token), "start": global_start, "end": global_end})
        text = str(row.get("text") or "").strip()
        if not text and token_rows:
            text = "".join(item["text"] for item in token_rows).strip()
        if not text:
            _raise_contract(
                producer,
                consumer,
                row,
                "FireRed result contains non-empty text or timestamp tokens",
            )
        offset = float(job.get("offset", 0.0) or 0.0)
        fallback_start = offset
        fallback_end = offset + float(job.get("duration", 0.01) or 0.01)
        segment = {
            "segment_id": int(row.get("segment_id", job.get("segment_id", index + 1))),
            "start": min(starts) if starts else fallback_start,
            "end": max(ends) if ends else max(fallback_start + 0.01, fallback_end),
            "text": text,
            "confidence": float(row.get("confidence", 0.0) or 0.0),
        }
        if token_rows:
            segment["tokens"] = token_rows
        segments.append(_validate_segment(segment, producer=producer, consumer=consumer))
    if not segments:
        _raise_contract(producer, consumer, value, "non-empty FireRed ASRResult")
    return {
        "schema_version": ASR_RESULT_SCHEMA_VERSION,
        "result_type": "ASRResult",
        "segments": segments,
        "language": "zh",
        "metadata": {"backend": "firered", "segment_count": len(segments)},
        "provenance": {
            "producer": producer,
            "normalization": "results_wrapper_to_flat_segments",
        },
    }


def flatten_segment_tokens(
    result: Mapping[str, Any],
    *,
    producer: str = "firered_adapter",
    consumer: str = "firered_timeline",
) -> list[dict[str, Any]]:
    """Expose the optional token timing nested in canonical FireRed segments."""
    canonical = validate_canonical_result(
        result,
        producer=producer,
        consumer=consumer,
        allow_empty=False,
    )
    tokens: list[dict[str, Any]] = []
    for segment in canonical["segments"]:
        nested = segment.get("tokens")
        rows = nested if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)) else [segment]
        for row in rows:
            token = _validate_segment(row, producer=producer, consumer=consumer)
            if "confidence" not in token and "confidence" in segment:
                token["confidence"] = segment["confidence"]
            tokens.append(token)
    return tokens
