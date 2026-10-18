"""Per-run translation logs: final answers and request metadata, never credentials or thoughts."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..provider_diagnostics import redact_diagnostics


def provider_evidence(provider, error=None) -> dict:
    """Select public fields; raw adapter traces can contain private reasoning."""
    getter = getattr(provider, "invocation_trace", None)
    try:
        trace = getter() if callable(getter) else getattr(provider, "last_invocation_trace", {})
        trace = trace or {}
        boundary = getattr(error, "diagnostics", None) or trace.get("response_boundary") or {}
        fields = ("endpoint", "http_status", "finish_reason", "max_tokens", "thinking_mode", "response_format_sent",
                  "response_format_fallback", "reasoning_parameters_sent", "final_content_preview",
                  "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")
        return redact_diagnostics({"request_id": trace.get("request_id"),
            "usage": trace.get("reported_usage"),
            "response_metadata": {key: boundary[key] for key in fields if key in boundary}})
    except Exception:
        return {}


class TranslationLog:
    """Append each event immediately so failures/cancellation retain evidence.

    Contains the submitted subtitle prompt and final answer. File access errors
    are exposed to the UI, but do not interrupt the translation.
    """
    def __init__(self, directory: Path | None = None):
        if directory is None:
            from ..runtime_paths import user_data_root
            directory = user_data_root() / "logs" / "subtitle-translation"
        self.path = Path(directory) / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.jsonl"
        self.error = ""

    def __call__(self, event: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(redact_diagnostics(event), ensure_ascii=False) + "\n")
        except OSError as exc:
            self.error = str(redact_diagnostics(str(exc)))
