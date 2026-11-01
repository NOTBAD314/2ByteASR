"""The independent production tools; no replacement of legacy MCP tools."""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Context


def register_production_tools(server, call):
    read = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    write = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
    text_ai = {**write, "openWorldHint": True}

    @server.tool(annotations=write)
    def create_media_project(ctx: Context, media_path: str, name: str = "") -> dict:
        """Create a new native project for one local media file, without recognition.
        Requires existing MCP edit permission and library scope. Never discards unsaved edits or overwrites a project.
        Query returned job_id until terminal before starting another operation."""
        return call("create_media_project", ctx, media_path=media_path, name=name)

    @server.tool(annotations=write)
    def open_project(ctx: Context, project_path: str) -> dict:
        """Open an existing native project; refuse unsaved edits or concurrent work.
        Current scope can only reopen the current path; library scope can open projects in that library.
        Wait for the returned job to finish and re-read get_status before editing."""
        return call("open_project", ctx, project_path=project_path)

    @server.tool(annotations=write)
    def save_project(ctx: Context, project_id: str, revision: int) -> dict:
        """Save the current project through the native controller and verify disk contents.
        project_id/revision must match get_status. Returns the saved content fingerprint."""
        return call("save_project", ctx, project_id=project_id, revision=revision)

    @server.tool(annotations=text_ai)
    def start_recognition(ctx: Context, project_id: str, revision: int) -> dict:
        """Start native recognition using the app's saved model/service configuration.
        May use configured cloud services; check actual job stages, errors and outputs.
        Configuration errors are actionable and never trigger an automatic retry."""
        return call("start_recognition", ctx, project_id=project_id, revision=revision)

    @server.tool(annotations=text_ai)
    def start_glossary_proofread(ctx: Context, project_id: str, revision: int,
                                cue_ids: list[str] | None = None, library_ids: list[str] | None = None,
                                action: Literal["preview", "apply"] = "preview", job_id: str | None = None) -> dict:
        """Independently proofread existing subtitles using the saved native text-AI service.
        preview makes suggestions; apply with that completed job_id uses the same result, without
        another AI request. Do not supply new cue/library selections when applying a job.
        No recognition or media cutting is implicitly started. Stale results remain queryable."""
        return call("start_glossary_proofread", ctx, project_id=project_id, revision=revision,
                    cue_ids=cue_ids, library_ids=library_ids, action=action, job_id=job_id)

    @server.tool(annotations=text_ai)
    def start_sentence_refine(ctx: Context, project_id: str, revision: int,
                              cue_ids: list[str] | None = None,
                              action: Literal["preview", "apply"] = "preview", job_id: str | None = None) -> dict:
        """Independently refine existing subtitle segmentation with the native text-AI service.
        preview returns suggestions; apply the completed job_id without a new cue selection to
        reuse those results as one undoable edit. Does not rerun recognition or alter the media."""
        return call("start_sentence_refine", ctx, project_id=project_id, revision=revision,
                    cue_ids=cue_ids, action=action, job_id=job_id)

    @server.tool(annotations=write)
    def cleanup_stutter(ctx: Context, project_id: str, revision: int,
                        cue_ids: list[str] | None = None,
                        action: Literal["preview", "apply"] = "preview", job_id: str | None = None) -> dict:
        """Preview local subtitle stutter cleanup, or apply a completed preview job_id.
        No AI request; only subtitle text changes, never audio/video. Applying a job forbids a
        new cue selection and refuses changed or locked subtitles."""
        return call("cleanup_stutter", ctx, project_id=project_id, revision=revision,
                    cue_ids=cue_ids, action=action, job_id=job_id)

    @server.tool(annotations=read)
    def detect_speech_pauses(ctx: Context, project_id: str, revision: int,
                             mode: Literal["smart", "silence"] = "smart", minimum_s: float = 1.0,
                             padding_s: float = 0.2, audio_track_id: str = "") -> dict:
        """Analyze pauses using the native detector. Returns a job with candidate IDs; no cuts.
        Candidates are bound to the source project snapshot. Select explicit IDs for apply_pause_cuts."""
        return call("detect_speech_pauses", ctx, project_id=project_id, revision=revision,
                    mode=mode, minimum_s=minimum_s, padding_s=padding_s, audio_track_id=audio_track_id)

    @server.tool(annotations=write)
    def apply_pause_cuts(ctx: Context, project_id: str, revision: int,
                         job_id: str, candidate_ids: list[str]) -> dict:
        """Apply only the selected candidates from a completed pause-detection job.
        Uses the native undoable ripple-cut command. Refuses changed projects and locked tracks.
        This is direct execution under existing MCP edit permission, without an extra approval plan."""
        return call("apply_pause_cuts", ctx, project_id=project_id, revision=revision,
                    job_id=job_id, candidate_ids=candidate_ids)

    @server.tool(annotations=write)
    def export_video(ctx: Context, project_id: str, revision: int,
                     name: str = "", destination: str = "") -> dict:
        """Export a captioned video through the native renderer; query the returned job.
        Uses the project or configured authorized export folder and never overwrites files.
        A started job is not a successful video: check terminal state and verified output evidence."""
        return call("export_video", ctx, project_id=project_id, revision=revision,
                    name=name, destination=destination)

    @server.tool(annotations=read)
    def get_review_summary(ctx: Context, project_id: str, revision: int) -> dict:
        """Read review evidence and its freshness without starting AI or switching pages.
        Missing/not-ready counts are null, never zero. Does not imply a human review."""
        return call("get_review_summary", ctx, project_id=project_id, revision=revision)

    @server.tool(annotations=read)
    def get_job(ctx: Context, job_id: str) -> dict:
        """Read a production job's real state, progress, errors and outputs.
        Interrupted jobs after restart require checking prior results; never blindly repeat them."""
        return call("get_job", ctx, job_id=job_id)

    @server.tool(annotations=write)
    def cancel_job(ctx: Context, job_id: str) -> dict:
        """Request native cancellation of this MCP-owned job only; keep other work and outputs.
        cancelling is not terminal. Read get_job until cancellation or completion is confirmed."""
        return call("cancel_job", ctx, job_id=job_id)
