"""Per-run translation metadata; prompts, final answers and credentials are excluded."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..providers.provider_diagnostics import redact_diagnostics


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

    Contains technical metadata and counts, never subtitle prompts or answers. File access errors
    are exposed to the UI, but do not interrupt the translation.
    """
    def __init__(self, directory: Path | None = None):
        if directory is None:
            from ..runtime_paths import user_data_root
            directory = user_data_root() / "logs" / "subtitle-translation"
        self.path = Path(directory) / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.jsonl"
        self.error = ""
        self._retention_done=False

    def __call__(self, event: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self._retention_done:
                import time
                files=sorted(self.path.parent.glob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)
                used=0
                for old in files:
                    used+=old.stat().st_size
                    if old!=self.path and (time.time()-old.stat().st_mtime>14*86400 or used>16*1024*1024):old.unlink(missing_ok=True)
                self._retention_done=True
            if self.path.exists() and self.path.stat().st_size>2*1024*1024:
                self.path.replace(self.path.with_suffix('.previous.jsonl'))
            with self.path.open("a", encoding="utf-8") as stream:
                from ..diagnostics.event_bridge import technical, legacy_event
                from ..diagnostics.editor_diagnostics import safe
                legacy_event("translation."+str(event.get("event","event")), event, module="translation")
                stream.write(json.dumps(safe(technical(event)), ensure_ascii=False) + "\n")
        except OSError as exc:
            self.error = str(redact_diagnostics(str(exc)))
