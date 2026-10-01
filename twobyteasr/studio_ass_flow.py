"""ASS preview pipeline, render diagnostics, and subtitle export flow for
Subtitle Studio."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from PySide6.QtCore import (QTimer)
from PySide6.QtWidgets import (QDialog, QMessageBox)
from .ass_compile_actor import (AssCompileActor, AssCompileResult)
from .ass_compiler import compile_ass
from .studio_export_ui import SubtitleExportDialog
from .studio_project import (SubtitleProject, studio_data_root)
from .studio_revisions import (StudioRevisionStore, preview_render_revision, thaw_json)
from .studio_subtitle_export import export_subtitle_artifacts
from .studio_theme import studio_message_box
from .style_recipe import (recipe_payload_for_style, route_recipe)

from .i18n import bind_text

from .i18n import tr


def _ass_text_forms(text: str) -> tuple[str, str]:
    """Cue text as (ass_payload_form, plain_form) for ASS correspondence checks.

    r"\\N" (raw string) is the two-character backslash+N ASS line-break token;
    a bare "\\N" inside a normal string literal would be a malformed unicode
    escape.
    """
    source = str(text)
    return source.replace("\n", r"\N"), source.replace("\n", " ").replace(r"\N", " ").strip()


class StudioAssFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _preview_target(
        self,
        project: SubtitleProject,
        project_path: Path | None,
        generation: int | None = None,
    ) -> Path:
        archive_preview = project_path.parent / "preview" if project_path else None
        directory = archive_preview if archive_preview and archive_preview.parent.joinpath("autosave").is_dir() else studio_data_root() / "preview"
        directory.mkdir(parents=True, exist_ok=True)
        suffix = f"-{generation}" if generation is not None else ""
        return directory / f"{project.project_id}{suffix}.ass"

    @staticmethod
    def _write_ass_content(target: Path, content: str) -> None:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".preview.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    def _ass_preview_snapshot(self, project: SubtitleProject) -> SubtitleProject:
        """Return the ASS-owned view; Advanced cues never enter Native foreground."""
        snapshot = copy.deepcopy(project)
        overrides = dict(self._live_edit_text_overrides)
        transform_overrides = copy.deepcopy(self._live_transform_overrides)
        kept = []
        advanced_hidden: set[str] = set()
        hidden_speakers = {
            speaker_id
            for speaker_id, visible in self._subtitle_track_visibility.items()
            if not visible
        }
        hidden_speakers.update(
            str(speaker_id)
            for speaker_id in getattr(self.timeline, "hidden_speakers", set())
        )
        for cue in snapshot.cues:
            if cue.speaker_id in hidden_speakers:
                continue
            if cue.id in overrides:
                cue.text = overrides[cue.id]
            transform = transform_overrides.get(cue.id)
            if transform:
                source_style_id = cue.style_id
                source_style = next((item for item in snapshot.styles if item.id == source_style_id), None)
                if source_style is not None:
                    live_style = copy.deepcopy(source_style)
                    live_style.id = f"{source_style_id}-live-transform"
                    if "position_x" in transform:
                        live_style.position_x = int(transform["position_x"])
                    if "position_y" in transform:
                        live_style.position_y = int(transform["position_y"])
                    if "font_size" in transform:
                        live_style.font_size = float(transform["font_size"])
                    snapshot.styles = [item for item in snapshot.styles if item.id != live_style.id] + [live_style]
                    source_recipe = snapshot.style_recipes.get(source_style_id)
                    if isinstance(source_recipe, Mapping):
                        live_recipe = copy.deepcopy(source_recipe)
                        layout = live_recipe.setdefault("layout", {})
                        typography = live_recipe.setdefault("typography", {})
                        if isinstance(layout, dict):
                            if "position_x" in transform:
                                layout["positionX"] = int(transform["position_x"])
                            if "position_y" in transform:
                                layout["positionY"] = int(transform["position_y"])
                        if isinstance(typography, dict) and "font_size" in transform:
                            typography["fontSize"] = float(transform["font_size"])
                        snapshot.style_recipes[live_style.id] = live_recipe
                    cue.style_id = live_style.id
            payload = recipe_payload_for_style(snapshot.style_recipes, cue.style_id)
            advanced = bool(payload) and isinstance(payload, Mapping) and route_recipe(payload).engine == "remotion"
            if advanced:
                advanced_hidden.add(cue.id)
                continue
            kept.append(cue)
        for cue_id in sorted(advanced_hidden - self._advanced_ass_hidden):
            self._studio_trace("ASS_ADVANCED_SUPPRESS", cue_id=cue_id, reason="route_advanced")
        for cue_id in sorted(self._advanced_ass_hidden - advanced_hidden):
            self._studio_trace("ASS_NATIVE_RESTORE", cue_id=cue_id, reason="route_native")
        self._advanced_ass_hidden = advanced_hidden
        snapshot.cues = kept
        return snapshot

    def _refresh_ass_preview(self) -> None:
        if not self.project:
            return
        self._ass_generation += 1
        self._start_ass_worker(self._ass_generation)

    def _ass_preview_revision(self):
        if not self.project:
            return None
        if self._revision_store is None:
            self._revision_store = StudioRevisionStore(self.project)
        revision = self._revision_store.render
        hidden: set[str] = set()
        # Authored cues have no ordinary ASS stand-in. Filtering the timed
        # events also closes the PTS/GUI-tick race at adjacent cue boundaries.
        # Preparation still warms the actual theme before its first frame.
        recipes=thaw_json(revision.style_recipes)
        for cue in revision.cues:
            payload=recipe_payload_for_style(recipes,cue.style_id)
            if payload and (payload.get('webTheme') or payload.get('engine')=='remotion' or route_recipe(payload).engine=='remotion'):
                hidden.add(cue.id)
        # A subtitle-track eye action is a render-state change, not merely a
        # timeline decoration. Remove cues from the generated ASS revision so
        # native libass cannot keep painting a hidden speaker while the global
        # mpv sub-visibility flag is restored for another visible track.
        hidden_speakers = {
            speaker_id
            for speaker_id, visible in self._subtitle_track_visibility.items()
            if not visible
        }
        hidden_speakers.update(
            str(speaker_id)
            for speaker_id in getattr(self.timeline, "hidden_speakers", set())
        )
        if hidden_speakers:
            hidden.update(
                cue.id for cue in revision.cues
                if cue.speaker_id in hidden_speakers
            )
        for cue_id in sorted(hidden - self._advanced_ass_hidden):
            self._studio_trace("ASS_ADVANCED_SUPPRESS", cue_id=cue_id, reason="authored_or_speaker_hidden")
        for cue_id in sorted(self._advanced_ass_hidden - hidden):
            self._studio_trace("ASS_NATIVE_RESTORE", cue_id=cue_id, reason="speaker_restored")
        self._advanced_ass_hidden = set(hidden)
        return preview_render_revision(
            revision,
            text_overrides=self._live_edit_text_overrides,
            transform_overrides=self._live_transform_overrides,
            hidden_cue_ids=hidden,
        )

    def _start_ass_worker(self, generation: int) -> None:
        if self._close_requested or not self.project:
            return
        snapshot_started = perf_counter()
        revision = self._ass_preview_revision()
        if revision is None:
            return
        self._ass_snapshot_ms[generation] = (perf_counter() - snapshot_started) * 1000.0
        self._ass_worker_running = True
        if self._ass_actor is None:
            self._ass_actor = AssCompileActor(self._ass_actor_ready, self._ass_actor_failed)
        self._ass_actor.submit(generation, revision)

    def _ass_actor_ready(self, result: AssCompileResult) -> None:
        if self._close_requested or self.project is None or result.generation != self._ass_generation:
            return
        try:
            target = self._preview_target(result.revision, self.project_path, result.generation)
            write_started = perf_counter()
            self._write_ass_content(target, result.content)
            write_ms = (perf_counter() - write_started) * 1000.0
            self._ass_profile.append({
                "generation": int(result.generation),
                "revision": list(result.revision.compile_key),
                "snapshot_ms": round(self._ass_snapshot_ms.pop(result.generation, 0.0), 3),
                "compile_ms": round(result.compile_ms, 3),
                "write_ms": round(write_ms, 3),
                "bytes": len(result.content.encode("utf-8")),
                "cache_hit": bool(result.cache_hit),
                "process_id": int(result.process_id),
                "thread": threading.current_thread().name,
            })
            self.ass_ready_signal.emit(result.generation, str(target))
        except Exception as exc:
            self._ass_actor_failed(result.generation, str(exc))

    def _ass_actor_failed(self, generation: int, message: str) -> None:
        self._ass_snapshot_ms.pop(generation, None)
        if self._close_requested:
            return
        try:
            self.ass_failed_signal.emit(generation, str(message))
        except RuntimeError:
            pass

    def _ass_ready(self, generation: int, path: str) -> None:
        self._ass_worker_running = False
        if self._close_requested:
            return
        if generation != self._ass_generation:
            return
        previous = self._preview_path
        self._preview_path = Path(path)
        self.video.reload_subtitle(path)
        if getattr(self, "_subtitle_transform_handoff_cue_id", ""):
            cue = self._cue_lookup.get(self._subtitle_transform_handoff_cue_id)
            payload = recipe_payload_for_style(self.project.style_recipes, cue.style_id) if self.project and cue else {}
            if not payload or route_recipe(payload).engine != "remotion":
                if not getattr(self, "_multitrack_composition_active", False):
                    self._subtitle_transform_handoff_cue_id = ""
                    self.ensure_active_subtitle_renderer(reason="transform_ass_ready")
        if os.environ.get("TWOBYTEASR_DEBUG_SUBTITLES") == "1":
            try:
                log_path = studio_data_root() / "logs" / "subtitle-render-diagnostics.jsonl"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(self.subtitle_render_diagnostics(), ensure_ascii=False) + "\n")
            except OSError:
                pass
        replay_cue_id = self._pending_motion_replay_cue_id
        self._pending_motion_replay_cue_id = ""
        if replay_cue_id:
            QTimer.singleShot(120, lambda cue_id=replay_cue_id: self._replay_motion(cue_id))
        if previous and previous != self._preview_path:
            QTimer.singleShot(
                1_000, lambda stale=previous: stale.unlink(missing_ok=True)
            )

    def _replay_motion(self, cue_id: str = "") -> None:
        cue = self._cue_lookup.get(cue_id or self.selected_cue_id)
        if cue is None or not self.video.controller:
            return
        was_paused = bool(getattr(self.video, "_paused", True))
        try:
            # Motion replay is still a user-visible seek. Route it through the
            # page coordinator so visual ownership and T0-T9 settlement use
            # the same semantics as timeline input.
            self._seek(max(0, cue.start_ms - 80) / 1000.0)
            self.video.set_paused(False)
            self._sync_play_button(False)
        except RuntimeError as exc:
            self._show_video_error(str(exc))
            return
        if was_paused:
            generation = getattr(self, "_motion_replay_generation", 0) + 1
            self._motion_replay_generation = generation
            duration = max(450, cue.end_ms - max(0, cue.start_ms - 80) + 120)
            QTimer.singleShot(duration, lambda token=generation: self._finish_motion_replay(token))

    def _finish_motion_replay(self, generation: int) -> None:
        if generation != getattr(self, "_motion_replay_generation", 0):
            return
        try:
            self.video.set_paused(True)
            self._sync_play_button(True)
        except RuntimeError:
            pass

    def subtitle_render_diagnostics(self) -> dict[str, object]:
        """Debug-only snapshot for tracing Cue -> ASS -> mpv -> Overlay.

        This is the Render Truth Probe. It is intentionally verbose and must
        be the single source of truth when investigating transform misalignment.
        The automatic JSONL log is still gated by TWOBYTEASR_DEBUG_SUBTITLES=1,
        but the method itself can be called explicitly for ad-hoc inspection.
        """
        if os.environ.get("TWOBYTEASR_DEBUG_SUBTITLES") != "1":
            return {}
        return self.render_truth_probe(force=True)

    def render_truth_probe(self, *, force: bool = False) -> dict[str, object]:
        """Return a comprehensive snapshot of the authoritative state.

        Sections:
        - project: ids, selected cue, timing, style, raw position/alignment/scale
        - effective_style: the style actually bound to the cue at selection time
        - ass: PlayRes, the exact Dialogue line(s) that should render this cue,
               plus the override tags that were emitted (including any \\pos/\\move)
        - mpv: sid, track-list (full), external/internal, video-out-params, dw/dh,
               panscan/zoom/crop, sub-text if available
        - overlay: what the Transform box currently believes (source rect, anchor, final preview rect, scales, offsets)
        - correspondence: proof that the visible glyph text matches a specific ASS event
        """
        if (not force) and os.environ.get("TWOBYTEASR_DEBUG_SUBTITLES") != "1":
            return {}

        result: dict[str, object] = {
            "timestamp": __import__("time").time(),
            "project": {},
            "effective_style": {},
            "ass": {},
            "mpv": {},
            "overlay": {},
            "correspondence": {},
        }

        proj = self.project
        cue = self._cue_lookup.get(self.selected_cue_id) if self.selected_cue_id else None

        # --- Project ---
        if proj:
            result["project"] = {
                "project_id": getattr(proj, "project_id", ""),
                "selected_cue_id": self.selected_cue_id,
                "cue_start_ms": cue.start_ms if cue else None,
                "cue_end_ms": cue.end_ms if cue else None,
                "cue_text": cue.text if cue else "",
                "cue_style_id": cue.style_id if cue else "",
                "cue_effect_id": cue.effect_id if cue else "",
                "cue_position": (getattr(cue, "position_x", None), getattr(cue, "position_y", None)) if cue else None,
                "cue_alignment": None,
                "cue_scale": None,
                "play_res": (
                    int(proj.render_settings.get("play_res_x", 1920)),
                    int(proj.render_settings.get("play_res_y", 1080)),
                ),
                "media": {
                    "path": proj.media.path,
                    "width": proj.media.width,
                    "height": proj.media.height,
                },
            }
            # Effective alignment/scale come from the style, not the cue
            try:
                style = next((s for s in proj.styles if s.id == (cue.style_id if cue else "")), None)
                if style:
                    result["project"]["cue_alignment"] = style.alignment
                    result["project"]["cue_scale"] = (style.scale_x, style.scale_y)
            except Exception:
                pass

        # --- Effective Style (what the cue should be using) ---
        if proj and cue:
            try:
                src = next((s for s in proj.styles if s.id == cue.style_id), None)
                if src:
                    result["effective_style"] = {
                        "id": src.id,
                        "font": src.font_family,
                        "size": src.font_size,
                        "fill": src.primary_color,
                        "outline": src.outline_color,
                        "outline_width": src.outline_width,
                        "shadow": src.shadow,
                        "alignment": src.alignment,
                        "position": (src.position_x, src.position_y),
                        "scale": (src.scale_x, src.scale_y),
                        "margin": (src.margin_l, src.margin_r, src.margin_v),
                    }
            except Exception:
                pass

        # --- ASS ---
        ass_path = str(self._preview_path or "")
        play_res = (1920, 1080)
        dialogue_lines: list[str] = []
        matching_events: list[str] = []
        if proj:
            play_res = (
                int(proj.render_settings.get("play_res_x", 1920)),
                int(proj.render_settings.get("play_res_y", 1080)),
            )
            try:
                # 三十八轮：隐藏的说话人轨不进预览/压制 ASS（与导出一致）。
                from .studio_subtitle_export import _project_for_cues

                compiled = compile_ass(_project_for_cues(proj, proj.visible_cues()))
                dialogue_lines = [ln for ln in compiled.splitlines() if ln.startswith("Dialogue:")]
                if cue:
                    # Find events whose text payload contains the cue text in
                    # either ASS-payload form or flattened plain form.
                    needle, plain_needle = _ass_text_forms(cue.text)
                    for ln in dialogue_lines:
                        if needle and (needle in ln or plain_needle in ln):
                            matching_events.append(ln)
            except Exception as exc:
                matching_events.append(f"<compile error: {exc}>")
        result["ass"] = {
            "preview_path": ass_path,
            "play_res": play_res,
            "dialogue_count": len(dialogue_lines),
            "matching_dialogue_for_cue": matching_events[:4],  # limit noise
            "first_few_dialogue": dialogue_lines[:3],
        }

        # --- mpv state ---
        ctrl = self.video.controller if hasattr(self, "video") else None
        mpv_block: dict[str, object] = {}
        if ctrl and hasattr(ctrl, "running") and ctrl.running:
            for key in ("sid", "track-list", "video-out-params", "panscan", "zoom", "crop",
                        "sub-text", "sub-visibility", "osd-dimensions", "display-fps"):
                try:
                    mpv_block[key] = ctrl.get_property(key)
                except Exception as e:
                    mpv_block[key] = f"error:{e}"
            # Explicit studio track tracking
            if hasattr(ctrl, "subtitle_diagnostics"):
                try:
                    mpv_block["studio_subtitle"] = ctrl.subtitle_diagnostics()
                except Exception:
                    pass
        result["mpv"] = mpv_block

        # --- Overlay (Transform box) ---
        ov = {}
        if hasattr(self, "position_overlay"):
            po = self.position_overlay
            try:
                mapper = po._mapper()
                content = mapper.video_content_rect
                ov = {
                    "overlay_cue_id": self._overlay_cue_id,
                    "source_rect": tuple(po._subtitle_rect().getRect()),
                    "ass_anchor": (po.position_x, po.position_y),
                    "video_content_rect": tuple(content.getRect()),
                    "scale_x": mapper.scale_x,
                    "scale_y": mapper.scale_y,
                    "offset_from_content": (
                        (po.position_x * mapper.scale_x) - (content.left() if hasattr(content, 'left') else 0),
                        (po.position_y * mapper.scale_y) - (content.top() if hasattr(content, 'top') else 0),
                    ),
                    "play_res": (po.play_res_x, po.play_res_y),
                    "video_size": (po.video_width, po.video_height),
                }
            except Exception as exc:
                ov["error"] = str(exc)
        result["overlay"] = ov

        # --- Correspondence proof ---
        # The critical question: is the glyph the user sees the ASS event for this cue?
        ass_form, plain_form = _ass_text_forms(cue.text if cue else "")
        corr: dict[str, object] = {
            "cue_text_normalized": plain_form,
            "mpv_sub_text": None,
            "ass_events_containing_text": [],
            "warning": None,
        }
        try:
            if mpv_block.get("sub-text"):
                corr["mpv_sub_text"] = str(mpv_block["sub-text"])
        except Exception:
            pass
        # Find Dialogue lines whose rendered text payload matches the cue
        if cue and dialogue_lines:
            escaped = re.escape(ass_form)
            for ln in dialogue_lines:
                # The text is after the 9th comma in Dialogue line
                try:
                    payload = ln.split(",", 9)[-1]
                    if re.search(escaped, payload) or (plain_form and plain_form in payload.replace(r"\N", " ")):
                        corr["ass_events_containing_text"].append(ln)
                except Exception:
                    pass
        if cue and not corr["ass_events_containing_text"]:
            corr["warning"] = "NO ASS EVENT FOUND CONTAINING THIS CUE TEXT — possible stale track or text mismatch"
        result["correspondence"] = corr
        result.update({
            "project_cue": cue.id if cue else "",
            "selected_cue": self.selected_cue_id,
            "overlay_cue": self._overlay_cue_id,
            "ass_event": matching_events[0] if matching_events else "",
        })

        return result

    def dump_render_truth_probe(self) -> None:
        """Convenience: print a pretty JSON probe to console for the current selection.
        Call from a debug menu or from an external Python snippet that has a reference
        to the SubtitleStudioPage instance.
        """
        import json as _json
        probe = self.render_truth_probe(force=True)
        try:
            print(_json.dumps(probe, ensure_ascii=False, indent=2))
        except Exception as e:
            print("Probe dump failed:", e)

    def _dump_selection_render_truth_probe(self) -> None:
        try:
            probe = self.render_truth_probe(force=True)
            import json as _json, time as _time
            from pathlib import Path as _Path
            log_dir = _Path("tmp") / "studio_debug"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = int(_time.time() * 1000)
            (log_dir / f"probe_{stamp}.json").write_text(_json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _ass_failed(self, generation: int, message: str) -> None:
        self._ass_worker_running = False
        if generation != self._ass_generation:
            self._preview_timer.start()
        else:
            bind_text(self.save_state, '预览更新失败: {message}', message=message)

    def export_subtitles(self) -> None:
        if not self.project:
            return
        dialog = SubtitleExportDialog(self.project, self.project_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            directory, reason = dialog.selected_destination()
            base_name = Path(self.project.media.path).stem or "subtitles"
            artifacts = export_subtitle_artifacts(
                self.project, directory, base_name, dialog.selected_options()
            )
        except Exception as exc:
            studio_message_box(self, QMessageBox.Icon.Warning, tr('导出字幕失败'), str(exc))
            return
        studio_message_box(
            self, QMessageBox.Icon.Information, tr('导出字幕'),
            tr('已导出并验证 {value0} 个文件。\n{value1}', value0=len(artifacts), value1=reason),
        )
