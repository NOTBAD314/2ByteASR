"""Video track editing, transform panel, multitrack preview, and mpv
compositor sync for Subtitle Studio."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import time as _time
from PySide6.QtCore import QThread
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QCursor, QPixmap
from PySide6.QtWidgets import (QInputDialog)
from .audio_playback_graph import solo_track_ids
from .studio_edit_commands import (delete_video_segments_command, razor_video_command, set_video_lock_command)
from .studio_edit_sequence import (sequence_of, timeline_duration_ms)
from .studio_project import SubtitleProject
from .studio_sequence_mapper import timeline_to_source
from .studio_theme import create_studio_menu
from .studio_widgets import _icon
from .visual_runtime import VisualOwner
from .studio_analysis_request import begin_request, current_request, retain_worker

from .i18n import bind_text

from .i18n import tr

class StudioVideoFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _commit_clip_edit(self, track_id, action, **values):
        from .studio_clip_edit import clip_edit_command
        if self.project is None:
            return False
        try:
            command = clip_edit_command(self.project, track_id, action, page=self, **values)
        except (ValueError, KeyError) as exc:
            self.save_state.setText(str(exc))
            self.save_state.setToolTip(str(exc))
            return False
        self.undo_stack.push(command)
        self._last_clip_edit_skipped_captions=bool(getattr(command,"skipped_caption_speakers",()))
        return True

    def _razor_video_at(self, milliseconds: int) -> None:
        """Legacy callers use the active video lane; mouse supplies exact hit."""
        if self.project is None:
            return
        from .studio_media_pool import primary_video_track_id
        track_id = self.timeline.selected_video_track_id or primary_video_track_id(self.project)
        track = next((t for t in self.project.video_tracks if t.id == track_id), None)
        clip = next((c for c in track.clips if c.timeline_in_ms < milliseconds < c.timeline_out_ms), None) if track else None
        if clip is None:
            bind_text(self.save_state, '播放头不在视频片段内部，未分割')
            return
        self._razor_video_clip_at(track_id, clip.id, milliseconds)

    def _razor_video_clip_at(self, track_id, clip_id, milliseconds):
        self._commit_clip_edit(track_id, 'split', clip_id=clip_id, time_ms=milliseconds)

    def _split_video_at_playhead(self) -> None:
        self._commit_playhead_edit('split')

    def _commit_playhead_edit(self, action):
        if self.project is None:
            return
        from .studio_clip_edit import playhead_edit_command
        try:
            command = playhead_edit_command(self.project, action, self.timeline.playhead_ms, page=self)
        except (ValueError, KeyError) as exc:
            self.save_state.setText(str(exc))
            return
        self.undo_stack.push(command)

    def _ripple_video_to_playhead(self, edge):
        self._commit_playhead_edit('ripple_start' if edge == 'start' else 'ripple_end')

    def _delete_timeline_gap(self):
        gap = self.timeline.selected_gap
        if gap and self._commit_clip_edit(gap[0], 'gap', start=gap[1], end=gap[2]):
            if not getattr(self,'_last_clip_edit_skipped_captions',False):
                bind_text(self.save_state, '已闭合空白，参与波纹的轨道与字幕已同步')

    # -------------------------------------------- 自动剪口播气口（四十四轮）

    def _detect_autocut_silence(self, min_silence_s: float, padding_s: float) -> None:
        """Analyze a detached, edited audio graph; applying is a separate action."""
        project = self.project
        panel = getattr(self, "highlight_panel", None)
        if project is None or panel is None:
            return
        player = getattr(self, '_autocut_player', None)
        if player is not None:player.stop()
        import copy, tempfile
        snapshot = copy.deepcopy(project)
        mode = panel.autocut_mode.currentData()
        audio_track = panel.autocut_audio_track.currentData()
        work = Path(tempfile.mkdtemp(prefix='2byte-autocut-'))
        request = begin_request(self, "autocut")
        self._autocut_preview_request = None
        self._autocut_preview_ranges = ()
        panel.show_autocut_result("正在检测…")
        panel.set_autocut_busy(True, "准备分析当前时间轴音频…")

        class _AutocutWorker(QThread):
            finished_ok = Signal(object)
            failed = Signal(str)
            progress = Signal(str, float, float)

            def run(self):
                try:
                    from .studio_speech_cut import analyze_speech_pauses
                    ranges = analyze_speech_pauses(snapshot, work, mode=mode,
                        minimum_s=min_silence_s,padding_s=padding_s,audio_track_id=audio_track,
                        request=request,progress=self.progress.emit)
                    if not request.is_cancelled:
                        self.finished_ok.emit(ranges)
                except Exception as exc:  # noqa: BLE001 - 线程必须回报可读错误
                    self.failed.emit(" ".join(str(exc).split())[:200])

        worker = _AutocutWorker()

        def _accepted():
            if current_request(self, "autocut", request):
                return True
            if getattr(self, "_autocut_request", None) is request:
                self._autocut_request = None
                if self.project is request.project and not getattr(self, "_close_requested", False):
                    panel.set_autocut_busy(False)
                    panel.show_autocut_result("工程已修改，已丢弃过期检测，请重新检测。")
            return False

        def _ok(analysis):
            if not _accepted():
                return
            timeline_ranges = [(c['start_ms'],c['end_ms']) for c in analysis['candidates']]
            self._autocut_preview_request = request
            self._autocut_preview_ranges = tuple(timeline_ranges)
            total = sum(b - a for a, b in timeline_ranges)
            self._autocut_analysis = analysis
            panel.set_autocut_busy(False)
            panel.show_autocut_preview(timeline_ranges, total, analysis['duration_ms'],analysis=analysis)

        def _fail(message):
            if not _accepted():
                return
            self._autocut_request = None
            panel.show_autocut_result(f"检测失败：{message}")
            panel.set_autocut_busy(False)

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.progress.connect(lambda stage,done,total: panel.set_autocut_busy(True,
            f'{stage} · {done:.1f} / {total:.1f} 秒 · 可取消') if current_request(self,'autocut',request) else None)
        self._autocut_worker = worker
        retain_worker(self, worker)
        worker.start()

    def _apply_autocut(self, timeline_ranges) -> None:
        """应用气口剪切（波纹删除+字幕位移，可撤销）。"""
        project = self.project
        panel = getattr(self, "highlight_panel", None)
        if project is None or panel is None:
            return
        request = getattr(self, "_autocut_preview_request", None)
        if not current_request(self, "autocut", request):
            panel.show_autocut_result("检测已过期，请在当前工程重新检测。")
            return
        ranges = [(int(a), int(b)) for a, b in (timeline_ranges or []) if int(b) > int(a)]
        if not ranges or not set(ranges) <= set(getattr(self, "_autocut_preview_ranges", ())):
            return
        from .studio_clip_edit import ripple_ranges_command

        count = len(ranges)
        try:
            command = ripple_ranges_command(project, ranges, page=self)
        except (ValueError,KeyError) as exc:
            panel.autocut_status.setText(str(exc))
            return
        before = timeline_duration_ms(project)
        self._autocut_preview_request = self._autocut_request = None
        self.undo_stack.push(command)
        after = timeline_duration_ms(project)
        panel.show_autocut_result(
            f"已应用 {count} 处停顿，剪辑区间共 {sum(b-a for a,b in ranges)/1000:.2f} 秒；"
            f"工程实际缩短 {(before-after)/1000:.2f} 秒，当前 {after/1000:.2f} 秒。Ctrl+Z 一次撤销整批。"
        )

    def _cancel_autocut(self):
        player = getattr(self, '_autocut_player', None)
        if player is not None:player.stop()
        from .studio_analysis_request import cancel_request
        cancel_request(self,'autocut')
        self._autocut_preview_request = None
        self._autocut_preview_ranges = ()
        self.highlight_panel.set_autocut_busy(False)
        self.highlight_panel.show_autocut_result('检测已取消，时间轴未修改。')

    def _preview_autocut_seam(self, start, end):
        """Audition original and post-cut PCM, without changing project transport."""
        if not current_request(self, 'autocut', getattr(self, '_autocut_preview_request', None)):
            bind_text(self.highlight_panel.autocut_status, '检测已过期，请重新检测后试听。')
            return
        from .studio_speech_cut import make_seam_preview
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtCore import QUrl
        try:
            path = make_seam_preview(self._autocut_analysis['audio_path'],start,end)
        except (OSError,ValueError,KeyError) as exc:
            bind_text(self.highlight_panel.autocut_status, '试听不可用：{exc}', exc=exc)
            return
        self.video.set_paused(True)
        if not hasattr(self,'_autocut_player'):
            self._autocut_player=QMediaPlayer(self)
            self._autocut_audio=QAudioOutput(self)
            self._autocut_player.setAudioOutput(self._autocut_audio)
        self._autocut_player.setSource(QUrl.fromLocalFile(str(path)))
        self._autocut_player.play()
        bind_text(self.highlight_panel.autocut_status, '正在试听：原剪口两侧 → 短间隔 → 压缩后剪口。时间轴未应用。再次检测或切换工程会停止试听。')

    def _toggle_video_lock(self) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        with self._interaction_runtime_audit.measure("Lock"):
            self.undo_stack.push(
                set_video_lock_command(project, not sequence.video_track_locked, self._sequence_changed)
            )
            self.timeline.update()

    def _selected_video_clip(self):
        project = self.project
        if project is None:
            return None, None
        track_id = str(self.timeline.selected_video_track_id or "")
        clip_id = str(self.timeline.selected_video_clip_id or "")
        track = next((item for item in project.video_tracks if item.id == track_id), None)
        clip = next(
            (item for item in (track.clips if track is not None else ()) if item.id == clip_id),
            None,
        )
        return track, clip

    def _video_clip_move_committed(self, track_id: str, clip_id: str, timeline_in_ms: int) -> None:
        self._commit_clip_edit(track_id, 'move', clip_id=clip_id, start=int(timeline_in_ms),
                               clip_ids=self.timeline.selected_segment_ids)

    def _video_clip_reassign_committed(
        self, source_track_id: str, target_track_id: str, clip_id: str, timeline_in_ms: int
    ) -> None:
        project = self.project
        if project is None:
            return
        from .studio_clip_edit import reassign_clips_command
        ids = self.timeline.selected_segment_ids | {clip_id}
        source = next(t for t in project.video_tracks if t.id == source_track_id)
        ids &= {c.id for c in source.clips}
        anchor = next(c for c in source.clips if c.id == clip_id)
        earliest = min(c.timeline_in_ms for c in source.clips if c.id in ids)
        try:
            command = reassign_clips_command(project, source_track_id, target_track_id, ids,
                start=int(timeline_in_ms) - (anchor.timeline_in_ms - earliest), page=self)
            self.undo_stack.push(command)
        except (ValueError, KeyError) as exc:
            bind_text(self.save_state, '换轨未完成：{exc}', exc=exc)
            self.save_state.setToolTip(str(exc))
            return
        if hasattr(self, "timeline"):
            self.timeline.refresh_media_graph()
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))

    def _append_video_clips_to_primary(self, source_track_id, clip_id):
        from .studio_clip_edit import reassign_clips_command
        from .studio_media_pool import primary_video_track_id, track_by_id
        ids = (self.timeline.selected_segment_ids | {clip_id}) & {
            c.id for c in track_by_id(self.project, source_track_id).clips}
        try:
            self.undo_stack.push(reassign_clips_command(self.project, source_track_id,
                primary_video_track_id(self.project), ids, append=True, page=self))
        except (ValueError, KeyError) as exc:
            self.save_state.setText(str(exc))

    def _video_track_swap_requested(self, source_track_id: str, target_track_id: str) -> None:
        """四十八轮：拖片段到主轨泳道松手 = 两条轨层级对调。

        复用四十六轮的轨道换序命令（z_index+泳道同步、可撤销）。用户语义
        （agy 判定）：要的是"谁当主画面/谁盖谁"的层级支配权，不是把片段
        嵌进主轨剪辑时间轴。
        """

        self._video_track_reorder_to(source_track_id, target_track_id)
        if hasattr(self, "save_state"):
            bind_text(self.save_state, '已交换 {source_track_id}/{target_track_id} 层级（可撤销）', source_track_id=source_track_id, target_track_id=target_track_id)

    def _video_segment_lift_requested(self, segment_id: str, target_track_id: str) -> None:
        """主轨 segment 纵向拖上叠加轨：提取为独立片段（序列 ripple 删除原段）。

        2026-09-06（四图反馈·图二）：EditSequence 是连续时间轴（无空洞），
        提取后主轨尾部左移补位（与既有波纹删除语义一致）；新片段落在叠加轨
        的原时间位。单命令可撤销。
        """

        project = self.project
        if project is None:
            return
        from .studio_edit_commands import EditSequenceCommand
        from .studio_edit_sequence import delete_segments, remap_cues, sequence_of
        from .studio_media_commands import CompositeMediaCommand, media_graph_command
        from .studio_media_pool import add_video_clip, track_by_id

        before_sequence = sequence_of(project)
        if before_sequence.video_track_locked:
            bind_text(self.save_state, '上移未完成：主轨已锁定')
            return
        segment = next(
            (item for item in before_sequence.segments if item.id == str(segment_id)),
            None,
        )
        if segment is None:
            return
        try:
            track_by_id(project, target_track_id)
        except KeyError:
            return
        source = str(segment.source_path or "")
        asset = next(
            (
                item for item in project.media_pool
                if str(Path(item.canonical_source).resolve() if item.canonical_source else "")
                == (str(Path(source).resolve()) if source else "")
            ),
            None,
        )
        if asset is None:
            bind_text(self.save_state, '上移未完成：该段素材不在媒体池')
            self.save_state.setToolTip(source)
            return
        after_sequence = delete_segments(before_sequence, [str(segment_id)])
        # 2026-09-19 P0：非破坏式——上移叠加轨不改写字幕全集（投影视图
        # 随序列自动正确）。
        timeline_in = int(segment.timeline_in_ms)

        def mutate(working):
            target = track_by_id(working, target_track_id)
            if target.locked:
                raise ValueError(f"track {target_track_id} is locked")
            duration = int(segment.source_out_ms) - int(segment.source_in_ms)
            overlaps = [
                item for item in target.clips
                if int(item.timeline_in_ms) < timeline_in + duration
                and int(item.timeline_out_ms) > timeline_in
            ]
            if overlaps:
                raise ValueError(
                    f"target track {target_track_id} already contains a clip at {timeline_in}..{timeline_in + duration}"
                )
            add_video_clip(
                working,
                target_track_id,
                asset.asset_id,
                timeline_in_ms=timeline_in,
                source_in_ms=int(segment.source_in_ms),
                source_out_ms=int(segment.source_out_ms),
            )

        try:
            graph_command = media_graph_command(project, "片段上移到叠加轨", mutate)
        except ValueError as exc:
            bind_text(self.save_state, '上移未完成：{exc}', exc=exc)
            self.save_state.setToolTip(str(exc))
            return
        sequence_command = EditSequenceCommand(
            project, after_sequence, None, "片段上移到叠加轨", self._sequence_changed
        )
        self.undo_stack.push(
            CompositeMediaCommand("片段上移到叠加轨", [graph_command, sequence_command])
        )
        if hasattr(self, "timeline"):
            self.timeline.refresh_media_graph()
            self.timeline.selected_video_clip_id = ""
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))

    def _video_clip_trim_committed(
        self,
        track_id: str,
        clip_id: str,
        timeline_in_ms: int,
        timeline_out_ms: int,
    ) -> None:
        self._commit_clip_edit(track_id, 'trim', clip_id=clip_id,
                               start=int(timeline_in_ms), end=int(timeline_out_ms))

    def _video_clip_selected(self, track_id: str, clip_id: str) -> None:
        self.timeline.selected_gap = None
        self.timeline.selected_video_track_id = str(track_id)
        self.timeline.selected_video_clip_id = str(clip_id)
        if self.project:
            self.project.studio_state["selected_video_track_id"] = str(track_id)
        self.select_cue("")
        if hasattr(self, "position_overlay"):
            self.position_overlay.hide()
        if hasattr(self, "video_compositor"):
            self.video_compositor.set_selected_clip(str(clip_id))
            # 五十轮：选中主轨片段时 compositor 可能处于 suspend（无叠加层时
            # 整体隐藏）——重发一次合成，让主轨变换框出现/消失即时生效。
            self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
        self._video_effects_preview_overrides.pop(str(clip_id), None)
        self._refresh_video_transform_panel()
        self._show_context_panel()
        if hasattr(self, "video_transform_tab_index"):
            self.context_drawer.setCurrentIndex(self.video_transform_tab_index)

    def _video_transform_values_from_controls(self) -> dict[str, object]:
        return {
            "position_x": self.video_position_x.value() / 100.0,
            "position_y": self.video_position_y.value() / 100.0,
            "scale_x": self.video_scale_x.value() / 100.0,
            "scale_y": self.video_scale_y.value() / 100.0,
            "rotation": self.video_rotation.value(),
            "opacity": self.video_opacity.value() / 100.0,
            "anchor_x": self.video_anchor_x.value() / 100.0,
            "anchor_y": self.video_anchor_y.value() / 100.0,
            "fit_mode": str(self.video_fit_mode.currentData() or "contain"),
        }

    def _set_video_transform_controls(self, values: Mapping[str, object]) -> None:
        self._updating_video_transform_ui = True
        controls = [
            self.video_position_x, self.video_position_y, self.video_scale_x,
            self.video_scale_y, self.video_rotation, self.video_opacity,
            self.video_anchor_x, self.video_anchor_y, self.video_fit_mode,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            self.video_position_x.setValue(float(values.get("position_x", 0.5)) * 100.0)
            self.video_position_y.setValue(float(values.get("position_y", 0.5)) * 100.0)
            self.video_scale_x.setValue(float(values.get("scale_x", 1.0)) * 100.0)
            self.video_scale_y.setValue(float(values.get("scale_y", 1.0)) * 100.0)
            self.video_rotation.setValue(float(values.get("rotation", 0.0)))
            self.video_opacity.setValue(float(values.get("opacity", 1.0)) * 100.0)
            self.video_anchor_x.setValue(float(values.get("anchor_x", 0.5)) * 100.0)
            self.video_anchor_y.setValue(float(values.get("anchor_y", 0.5)) * 100.0)
            index = self.video_fit_mode.findData(str(values.get("fit_mode") or "contain"))
            self.video_fit_mode.setCurrentIndex(max(0, index))
        finally:
            for control in controls:
                control.blockSignals(False)
            self._updating_video_transform_ui = False

    # ------------------------------------- 素材效果（ADR-0005，四十五轮）

    def _video_effects_values_from_controls(self) -> dict[str, object]:
        from .studio_project import normalize_clip_effects

        return normalize_clip_effects({
            "blendMode": str(self.video_blend_mode.currentData() or "normal"),
            "chromaKey": {
                "enabled": self.video_key_enabled.isChecked(),
                "color": str(self.video_key_color_hex.text() or "#00FF00"),
                "similarity": self.video_key_similarity.value() / 100.0,
                "smoothness": self.video_key_smoothness.value() / 100.0,
                "spillSuppression": self.video_key_spill.isChecked(),
            },
        })

    def _set_video_effects_controls(self, effects: Mapping[str, object]) -> None:
        self._updating_video_transform_ui = True
        controls = [
            self.video_blend_mode, self.video_key_enabled, self.video_key_similarity,
            self.video_key_smoothness, self.video_key_spill,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            chroma = effects.get("chromaKey") if isinstance(effects, Mapping) else {}
            chroma = chroma if isinstance(chroma, Mapping) else {}
            index = self.video_blend_mode.findData(str(effects.get("blendMode") or "normal") if isinstance(effects, Mapping) else "normal")
            self.video_blend_mode.setCurrentIndex(max(0, index))
            self.video_key_enabled.setChecked(bool(chroma.get("enabled")))
            color = QColor(str(chroma.get("color") or "#00FF00"))
            if not color.isValid():
                color = QColor("#00FF00")
            self.video_key_color_hex.setText(color.name().upper())
            self.video_key_color.setStyleSheet(
                f"background: {color.name()}; border: 1px solid rgba(255,255,255,0.35); border-radius: 4px;"
            )
            self.video_key_similarity.setValue(round(float(chroma.get("similarity", 0.32) or 0.0) * 100))
            self.video_key_smoothness.setValue(round(float(chroma.get("smoothness", 0.10) or 0.0) * 100))
            self.video_key_spill.setChecked(bool(chroma.get("spillSuppression", True)))
        finally:
            for control in controls:
                control.blockSignals(False)
            self._updating_video_transform_ui = False

    def _video_effects_control_preview(self, *_args) -> None:
        if getattr(self, "_updating_video_transform_ui", False):
            return
        _track, clip = self._selected_video_clip()
        if clip is None or _track.locked:
            return
        self._video_effects_preview_overrides[clip.id] = self._video_effects_values_from_controls()
        self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _video_effects_control_committed(self, *_args) -> None:
        if getattr(self, "_updating_video_transform_ui", False):
            return
        track, clip = self._selected_video_clip()
        if track is None or clip is None:
            return
        if track.locked:
            bind_text(self.save_state, '轨道已锁定，请先解锁')
            return
        effects = self._video_effects_values_from_controls()
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import set_video_clip_effects

        self._video_effects_preview_overrides.pop(clip.id, None)
        self.undo_stack.push(
            media_graph_command(
                self.project,
                "调整素材效果",
                lambda working: set_video_clip_effects(working, track.id, clip.id, effects),
            )
        )
        self._refresh_video_transform_panel()
        self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _video_key_color_clicked(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        current = QColor(str(self.video_key_color_hex.text() or "#00FF00"))
        if not current.isValid():
            current = QColor("#00FF00")
        color = QColorDialog.getColor(current, self, "选择键控颜色（要抠掉的颜色）")
        if not color.isValid():
            return
        self.video_key_color_hex.setText(color.name().upper())
        self.video_key_color.setStyleSheet(
            f"background: {color.name()}; border: 1px solid rgba(255,255,255,0.35); border-radius: 4px;"
        )
        self._video_effects_control_committed()

    def _refresh_video_transform_panel(self) -> None:
        if getattr(self,"_transition_defaults_project",None) is not self.project:
            self._transition_defaults_project=self.project
            for media,fallback in (("video",500),("audio",300)):
                spin=getattr(self,"default_"+media+"_transition_duration",None)
                if spin is not None:
                    spin.setValue(int(self.project.studio_state.get("default_"+media+"_transition_ms",fallback)) if self.project else fallback)
        if not hasattr(self, "video_transform_controls"):
            return
        track, clip = self._selected_video_clip()
        enabled = clip is not None and not track.locked
        for control in [
            *self.video_transform_controls, self.video_fit_mode, self.video_audio_enabled,
            self.video_blend_mode, self.video_key_enabled, self.video_key_color,
            self.video_key_similarity, self.video_key_smoothness, self.video_key_spill,
        ]:
            control.setEnabled(enabled and not bool(track.locked if track else False))
        self.video_audio_solo.setEnabled(track is not None)
        # 四十五轮（agy 评审）：选中标签显示素材文件名与时间范围，不裸露
        # 内部 clip hash（用户无从核对）。
        if track is not None and clip is not None:
            asset_name = ""
            if self.project:
                from .studio_media_pool import asset_by_id

                try:
                    asset = asset_by_id(self.project, clip.asset_id)
                    asset_name = Path(str(asset.canonical_source)).stem
                except (KeyError, OSError, ValueError):
                    asset_name = ""
            bind_text(self.video_transform_selection_label, f"{track.id} · {asset_name or '素材'} · {clip.timeline_in_ms / 1000:.1f}s–{clip.timeline_out_ms / 1000:.1f}s")
        else:
            bind_text(self.video_transform_selection_label, '在时间线选择一个视频片段')
        self._show_video_transform_placeholders(clip is None)
        if clip is not None:
            values = dict(vars(clip.transform))
            values.update(self._video_transform_preview_overrides.get(clip.id, {}))
            self._set_video_transform_controls(values)
            effects = dict(getattr(clip, "effects", {}) or {})
            effects.update(self._video_effects_preview_overrides.get(clip.id, {}))
            self._set_video_effects_controls(effects)
            self.video_audio_enabled.blockSignals(True)
            self.video_audio_enabled.setChecked(bool(clip.audio_enabled))
            self.video_audio_enabled.blockSignals(False)
        self.video_audio_solo.blockSignals(True)
        self.video_audio_solo.setChecked(bool(getattr(track, "soloed", False)))
        self.video_audio_solo.blockSignals(False)
        self.video_audio_master.blockSignals(True)
        self.video_audio_mode.blockSignals(True)
        self.video_audio_master.clear()
        if self.project:
            from .studio_media_pool import audio_master_mode, audio_master_track_id

            master_id = audio_master_track_id(self.project)
            mode = audio_master_mode(self.project)
            mode_index = self.video_audio_mode.findData(mode)
            self.video_audio_mode.setCurrentIndex(max(0, mode_index))
            for item in self.project.video_tracks:
                self.video_audio_master.addItem(f"{item.id} · {item.name}", item.id)
            index = self.video_audio_master.findData(master_id)
            self.video_audio_master.setCurrentIndex(max(0, index))
            self.video_audio_master.setEnabled(mode == "manual" and bool(self.project.video_tracks))
            self.video_audio_mode.setEnabled(bool(self.project.video_tracks))
            master = next((item for item in self.project.video_tracks if item.id == master_id), None)
            from .audio_playback_graph import solo_track_ids
            solos = solo_track_ids(self.project)
            if solos:
                from .audio_graph import capture_audio_graph, preview_audio_layers
                audible = preview_audio_layers(capture_audio_graph(self.project), int(self.timeline.playhead_ms))
                bind_text(self.video_audio_owner_label, 'Solo / 独听：{value0}{value1}', value0=', '.join(sorted(solos)), value1=tr(' · 当前无可用声音，请检查脱机、静音或片段范围') if not audible else tr(' · Mute优先'))
            elif mode == "mix_all":
                bind_text(self.video_audio_owner_label, '当前声音：所有可用、未静音音轨混音')
            else:
                bind_text(self.video_audio_owner_label, '旧工程指定声音：{value0}（兼容保留）；选择全轨混音可取消，S独听优先。', value0=master_id or '-')
        else:
            self.video_audio_master.setEnabled(False)
            self.video_audio_mode.setEnabled(False)
        self.video_audio_master.blockSignals(False)
        self.video_audio_mode.blockSignals(False)

    def _video_transform_control_preview(self, *_args) -> None:
        if getattr(self, "_updating_video_transform_ui", False):
            return
        _track, clip = self._selected_video_clip()
        if clip is None or _track.locked:
            return
        self._video_transform_preview_overrides[clip.id] = self._video_transform_values_from_controls()
        self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _show_video_transform_placeholders(self, empty: bool) -> None:
        """No selected clip: blank fields instead of misleading 1% / 0% values.

        QDoubleSpinBox clamps its initial 0 to each range's minimum, so an
        empty panel used to read "缩放 1.00%" and "不透明度 0.00%" (or keep the
        last clip's numbers). Nothing is written to any clip here.
        """
        spins = [*getattr(self, "video_transform_controls", ()),
                 getattr(self, "video_key_similarity", None), getattr(self, "video_key_smoothness", None)]
        combos = [getattr(self, "video_fit_mode", None), getattr(self, "video_blend_mode", None)]
        self._updating_video_transform_ui = True
        try:
            for control in [*spins, *combos]:
                if control is not None:
                    control.blockSignals(True)
            for control in spins:
                if control is None:
                    continue
                control.setSpecialValueText("—" if empty else "")
                if empty:
                    control.setValue(control.minimum())
            if empty:
                for combo in combos:
                    if combo is not None:
                        combo.setCurrentIndex(-1)
        finally:
            for control in [*spins, *combos]:
                if control is not None:
                    control.blockSignals(False)
            self._updating_video_transform_ui = False

    def _video_transform_control_committed(self, *_args) -> None:
        if getattr(self, "_updating_video_transform_ui", False):
            return
        track, clip = self._selected_video_clip()
        if track is None or clip is None:
            return
        values = self._video_transform_values_from_controls()
        current = vars(clip.transform)
        # Fields show two decimals (percent / degrees): an untouched field
        # differs from the stored value by at most half a display step.
        unchanged = all(
            abs(float(values[key]) - float(current.get(key, values[key])))
            <= (0.0051 if key == "rotation" else 0.000051)
            for key in values if key != "fit_mode"
        ) and values.get("fit_mode") == current.get("fit_mode", values.get("fit_mode"))
        if unchanged:
            # editingFinished also fires on focus-out without an edit: drop the
            # preview override, but never push an empty undo step.
            if self._video_transform_preview_overrides.pop(str(clip.id), None) is not None:
                self._sync_video_compositor(int(self.timeline.playhead_ms))
            return
        self._video_transform_committed(track.id, clip.id, values)

    def _video_fit_mode_committed(self, *_args) -> None:
        """Apply fit as a canvas preset, even after a manual resize/move."""
        if getattr(self, "_updating_video_transform_ui", False):
            return
        track, clip = self._selected_video_clip()
        if track is None or clip is None or track.locked:
            return
        values = self._video_transform_values_from_controls()
        values.update(position_x=.5, position_y=.5, scale_x=1., scale_y=1.,
                      anchor_x=.5, anchor_y=.5, rotation=0.)
        self._video_transform_committed(track.id, clip.id, values)
        self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _video_transform_previewed(
        self, track_id: str, clip_id: str, values: Mapping[str, object]
    ) -> None:
        if self.project is None or any(t.locked for t in self.project.video_tracks if t.id == track_id):
            return
        self._video_transform_preview_overrides[str(clip_id)] = dict(values)
        if str(clip_id) == str(self.timeline.selected_video_clip_id):
            self._set_video_transform_controls(values)

    def _video_transform_committed(
        self, track_id: str, clip_id: str, values: Mapping[str, object]
    ) -> None:
        project = self.project
        if project is None:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import update_video_clip_transform

        if any(t.locked for t in project.video_tracks if t.id == track_id):
            bind_text(self.save_state, '轨道已锁定，请先解锁')
            return

        self._video_transform_preview_overrides.pop(str(clip_id), None)
        self.undo_stack.push(
            media_graph_command(
                project,
                "调整视频 Transform",
                lambda working: update_video_clip_transform(
                    working, str(track_id), str(clip_id), dict(values)
                ),
            )
        )
        self._refresh_video_transform_panel()

    def _video_clip_audio_toggled(self, enabled: bool) -> None:
        if getattr(self, "_updating_video_transform_ui", False):
            return
        project = self.project
        track, clip = self._selected_video_clip()
        if project is None or track is None or clip is None:
            return
        if track.locked:
            bind_text(self.save_state, '轨道已锁定，请先解锁')
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import set_video_clip_audio_enabled

        self.undo_stack.push(
            media_graph_command(
                project,
                "切换片段音频",
                lambda working: set_video_clip_audio_enabled(
                    working, track.id, clip.id, bool(enabled)
                ),
            )
        )

    def _video_audio_master_changed(self, *_args) -> None:
        if not self.project:
            return
        track_id = str(self.video_audio_master.currentData() or "")
        if not track_id:
            return
        from .studio_media_commands import AudioMasterCommand

        self.undo_stack.push(AudioMasterCommand(self.project, track_id))
        self._refresh_video_transform_panel()

    def _video_audio_mode_changed(self, *_args) -> None:
        if not self.project:
            return
        from .studio_media_pool import set_audio_master_mode

        set_audio_master_mode(
            self.project,
            str(self.video_audio_mode.currentData() or "follow_active_video"),
        )
        self._changed()
        self._refresh_video_transform_panel()
        self._sync_video_compositor(int(self.timeline.playhead_ms))

    def _video_audio_solo_toggled(self, enabled: bool) -> None:
        track, _clip = self._selected_video_clip()
        if track is None or bool(getattr(track, "soloed", False)) == bool(enabled):
            return
        self._video_track_action(track.id, "solo")

    def _ensure_timeline_lane_space(self) -> None:
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return
        timeline.refresh_media_graph()
        timeline.update()
        needed_widget = int(timeline.minimumHeight())
        host = timeline.parentWidget()
        needed_host = needed_widget + 48
        if host is not None:
            host.setMinimumHeight(max(260, needed_host))
        splitter = getattr(self, "workspace_splitter", None)
        if splitter is None:
            return
        sizes = list(splitter.sizes())
        if len(sizes) < 2:
            return
        if sizes[1] < needed_host:
            extra = needed_host - sizes[1]
            sizes[0] = max(240, sizes[0] - extra)
            sizes[1] = needed_host
            splitter.setSizes(sizes)

    def _add_video_track(self) -> None:
        project = self.project
        if project is None:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import create_video_track

        self.undo_stack.push(
            media_graph_command(
                project,
                "新建视频轨",
                lambda working: create_video_track(working),
            )
        )
        self._ensure_timeline_lane_space()
        if hasattr(self, "media_pool_panel"):
            self.media_pool_panel.refresh(project)
        self._refresh_edit_playback_state()
        self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
        if project.video_tracks:
            self._video_track_action(project.video_tracks[-1].id, "select")

    def _video_track_action(self, track_id: str, action: str) -> None:
        project = self.project
        if project is None:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import (
            rename_video_track,
            set_video_track_state,
            track_by_id,
        )

        try:
            track = track_by_id(project, track_id)
        except KeyError:
            return
        if action == "select":
            project.studio_state["selected_video_track_id"] = track_id
            self.timeline.selected_video_track_id = track_id
            if hasattr(self, "media_pool_panel"):
                self.media_pool_panel.select_track(track_id)
            self.timeline.update(self.timeline._video_tracks_rect().toAlignedRect())
            return
        if action == "more":
            self._show_video_track_menu(track_id, "", QCursor.pos())
            return
        from .studio_clip_edit import video_track_locked
        if action != 'locked' and video_track_locked(project, track):
            bind_text(self.save_state, '{value0} 轨道已锁定，请先解锁', value0=track.name or track.id)
            return
        if action == "rename":
            name, accepted = QInputDialog.getText(
                self,
                tr('重命名视频轨'),
                tr('轨道名称'),
                text=track.name,
            )
            if not accepted or not name.strip() or name.strip() == track.name:
                return
            mutate = lambda working: rename_video_track(working, track_id, name)
            label = "重命名视频轨"
        elif action == "enabled":
            mutate = lambda working: set_video_track_state(
                working, track_id, enabled=not track.enabled
            )
            label = "启用视频轨" if not track.enabled else "停用视频轨"
        elif action == "muted":
            mutate = lambda working: set_video_track_state(
                working, track_id, muted=not track.muted
            )
            label = "恢复视频轨声音" if track.muted else "静音视频轨"
        elif action == "solo":
            mutate = lambda working: set_video_track_state(
                working, track_id, soloed=not bool(getattr(track, "soloed", False))
            )
            label = "取消独奏视频轨" if getattr(track, "soloed", False) else "独奏视频轨"
        elif action == "locked":
            mutate = lambda working: set_video_track_state(
                working, track_id, locked=not track.locked
            )
            label = "解锁视频轨" if track.locked else "锁定视频轨"
        else:
            return
        self.undo_stack.push(media_graph_command(project, label, mutate))
        if hasattr(self,'media_availability'):self.media_availability.refresh()

    def _audio_track_action(self, audio_track_id: str, action: str) -> None:
        project = self.project
        if project is None:
            return
        from .studio_track_gain import audio_track_locked
        if audio_track_locked(project, audio_track_id):
            bind_text(self.save_state, '音轨或关联视频轨已锁定，请先解锁')
            return
        if action == "gain":
            self._show_track_gain(audio_track_id)
            return
        group = next(
            (
                item for item in project.av_track_groups
                if item.audio_track_id == str(audio_track_id)
            ),
            None,
        )
        video_track_id = str(getattr(group, "video_track_id", "") or "")
        if action in {'muted', 'solo'}:
            if video_track_id and group.linked:
                self._video_track_action(video_track_id, action)
            else:
                from .studio_media_commands import media_graph_command
                track = next((t for t in project.audio_tracks if t.id == audio_track_id), None)
                if track is None:return
                field = 'soloed' if action == 'solo' else 'muted'
                value = not getattr(track, field)
                def mutate(working):
                    target = next(t for t in working.audio_tracks if t.id == audio_track_id)
                    setattr(target, field, value)
                    if action == 'solo':
                        working.studio_state['audio_solo_track_ids'] = [key for key in working.studio_state.get('audio_solo_track_ids', []) if key != audio_track_id]
                self.undo_stack.push(media_graph_command(project, 'Solo / 独听音轨' if action == 'solo' else '音轨静音', mutate))
                if hasattr(self,'media_availability'):self.media_availability.refresh()

    def _show_track_gain(self, track_id="") -> None:
        from .studio_track_gain import show_track_gain
        show_track_gain(self, track_id)

    def _video_track_reorder_to(self, track_id: str, target_track_id: str) -> None:
        """四十六轮：拖轨道头换序——把 track 移到 target 的位置（整轨对调泳道
        与渲染层级，可撤销）。"""
        project = self.project
        if project is None or not track_id or not target_track_id or track_id == target_track_id:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import reorder_video_track, track_by_id

        try:
            target_index = [item.id for item in project.video_tracks].index(target_track_id)
        except ValueError:
            return
        try:
            track_by_id(project, track_id)
        except KeyError:
            return
        try:
            self.undo_stack.push(media_graph_command(project, '视频轨换序',
                lambda working: reorder_video_track(working, track_id, target_index)))
        except ValueError as exc:
            self.save_state.setText(str(exc))
            return
        self.timeline.refresh_media_graph()
        self.timeline.update()
        self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))

    def _show_video_track_menu(
        self,
        track_id: str,
        clip_id: str,
        global_pos,
    ) -> None:
        project = self.project
        if project is None:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import (
            move_video_clip,
            primary_video_track_id,
            remove_video_clip,
            reorder_video_track,
            set_video_clip_enabled,
            track_by_id,
        )

        try:
            track = track_by_id(project, track_id)
        except KeyError:
            return
        menu = create_studio_menu(self)
        gap=self.timeline.selected_gap
        if not clip_id and gap and gap[0]==track_id:
            menu.addAction('波纹删除空隙',self._delete_timeline_gap).setEnabled(not track.locked)
            menu.addSeparator()
        from .studio_track_delete import delete_track, delete_clips, delete_label
        menu.addAction(delete_label(project,'video',track_id)+"    Delete",lambda:delete_track(self,'video',track_id)).setEnabled(not track.locked)
        primary_id = primary_video_track_id(project)
        if clip_id:
            clip = next((item for item in track.clips if item.id == clip_id), None)
            if clip is not None:
                append_action = menu.addAction('移到 V1 并接在末尾')
                append_action.setEnabled(not track.locked)
                append_action.triggered.connect(lambda: self._append_video_clips_to_primary(track_id, clip_id))
                asset = next((a for a in project.media_pool if a.asset_id == clip.asset_id), None)
                if asset is not None and asset.offline:
                    menu.addAction('重新链接素材…',
                        lambda asset_id=asset.asset_id: self.media_availability.choose_relink(asset_id))
                    menu.addSeparator()
                if track_id == primary_id:
                    remove = menu.addAction(
                        _icon("fa5s.trash-alt"), "删除主轨片段"
                    )
                    remove.setEnabled(not sequence_of(project).video_track_locked)
                    remove.triggered.connect(
                        lambda: delete_clips(self, track_id, [clip_id])
                    )
                else:
                    toggle_clip = menu.addAction(
                        _icon("fa5s.eye" if not clip.enabled else "fa5s.eye-slash"),
                        "启用片段" if not clip.enabled else "停用片段",
                    )
                    toggle_clip.setEnabled(not track.locked)
                    toggle_clip.triggered.connect(
                        lambda: self.undo_stack.push(
                            media_graph_command(
                                project,
                                "切换视频片段状态",
                                lambda working: set_video_clip_enabled(
                                    working, track_id, clip_id, not clip.enabled
                                ),
                            )
                        )
                    )
                    move_here = menu.addAction(_icon("fa5s.play"), "移动片段到播放头")
                    move_here.setEnabled(not track.locked)
                    move_here.triggered.connect(
                        lambda: self._commit_clip_edit(track_id, 'move', clip_id=clip_id,
                            start=int(self.timeline.playhead_ms))
                    )
                    trim = menu.addAction(_icon("fa5s.crop-alt"), "设置源片段入点/出点…")
                    trim.setEnabled(not track.locked)
                    trim.triggered.connect(
                        lambda: self._trim_video_clip_dialog(track_id, clip_id)
                    )
                    remove = menu.addAction(_icon("fa5s.trash-alt"), "删除视频片段")
                    remove.setEnabled(not track.locked)
                    remove.triggered.connect(
                        lambda: delete_clips(self, track_id, [clip_id])
                    )
                menu.addSeparator()
        rename = menu.addAction(_icon("fa5s.edit"), "重命名轨道")
        rename.setEnabled(not track.locked)
        rename.triggered.connect(lambda: self._video_track_action(track_id, "rename"))
        enabled = menu.addAction(
            _icon("fa5s.eye" if track.enabled else "fa5s.eye-slash"),
            "停用轨道" if track.enabled else "启用轨道",
        )
        enabled.triggered.connect(lambda: self._video_track_action(track_id, "enabled"))
        enabled.setEnabled(not track.locked)
        locked = menu.addAction(
            _icon("fa5s.unlock" if track.locked else "fa5s.lock"),
            "解锁轨道" if track.locked else "锁定轨道",
        )
        locked.triggered.connect(lambda: self._video_track_action(track_id, "locked"))
        menu.addSeparator()
        index = project.video_tracks.index(track)
        move_up = menu.addAction(_icon("fa5s.arrow-up"), "轨道上移")
        move_down = menu.addAction(_icon("fa5s.arrow-down"), "轨道下移")
        move_up.setEnabled(index > 0 and not track.locked and not project.video_tracks[index-1].locked)
        move_down.setEnabled(index + 1 < len(project.video_tracks) and not track.locked
                             and not project.video_tracks[index+1].locked)
        move_up.triggered.connect(
            lambda: self._video_track_reorder_to(track_id, project.video_tracks[max(0,index-1)].id)
        )
        move_down.triggered.connect(
            lambda: self._video_track_reorder_to(track_id, project.video_tracks[min(len(project.video_tracks)-1,index+1)].id)
        )
        menu.addSeparator()
        menu.addAction(_icon("fa5s.plus"), "新建视频轨", self._add_video_track)
        if track_id == primary_id and str(project.media.path or "").lower().endswith(".flv"):
            menu.addAction(_icon("fa5s.sliders-h"), "音画同步校正…", self._av_sync_manual_correction)
        menu.exec(global_pos)

    def _trim_video_clip_dialog(self, track_id: str, clip_id: str) -> None:
        project = self.project
        if project is None:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import track_by_id, trim_video_clip

        try:
            from .studio_clip_edit import _editable
            _editable(project, track_id)
            track = track_by_id(project, track_id)
            clip = next(item for item in track.clips if item.id == clip_id)
        except (KeyError, StopIteration):
            return
        except ValueError as exc:
            self.save_state.setText(str(exc))
            return
        source_in, accepted = QInputDialog.getInt(
            self,
            "设置源片段范围",
            "源入点 (ms)",
            clip.source_in_ms,
            0,
            max(0, clip.source_out_ms - 1),
        )
        if not accepted:
            return
        source_out, accepted = QInputDialog.getInt(
            self,
            "设置源片段范围",
            "源出点 (ms)",
            clip.source_out_ms,
            source_in + 1,
            2_147_483_647,
        )
        if not accepted:
            return
        self.undo_stack.push(
            media_graph_command(
                project,
                "修剪视频片段",
                lambda working: trim_video_clip(
                    working,
                    track_id,
                    clip_id,
                    source_in_ms=source_in,
                    source_out_ms=source_out,
                ),
            )
        )

    def _refresh_edit_playback_state(self) -> None:
        """Update timeline duration/mapping without loading media or EDL."""
        project = self.project
        if project is None:
            self.timeline.reindex_project()
            return
        sequence = sequence_of(project)
        from .studio_media_pool import media_graph_duration_ms

        graph_duration = media_graph_duration_ms(project)
        # A reachable media file means the timeline contract is merely broken
        # (zero-duration legacy graph), not intentionally empty; clearing the
        # media here would black out a project the open path just attached.
        media_reachable = bool(
            project.media.path and Path(project.media.path).is_file()
        )
        empty_timeline = bool(
            sequence.empty_timeline
            and not sequence.segments
            and graph_duration <= 0
            and not media_reachable
        )
        if empty_timeline:
            self._enter_empty_playback_state()
        else:
            self._restore_nonempty_playback_state()
        duration = max(0.0, timeline_duration_ms(project) / 1000.0)
        linear = bool(sequence.is_linear_source())
        if linear:
            # Source mode: timeline == source, so the timeline total is also
            # the mpv media duration used by clamp/EOF.
            self.video._duration_override = duration
            self.video._duration = duration
        else:
            # Mapped sequence: the mpv canvas clock, seeks and EOF judgement
            # stay in SOURCE time (project_time_mapping is only enabled for
            # secondary-track playback). Overriding the canvas duration with
            # the timeline total would clamp every seek into a retained tail
            # segment down to the timeline length, stranding mpv inside the
            # deleted head and raising false EOF flags.
            self.video._duration_override = 0.0
            if int(sequence.source_duration_ms) > 0:
                self.video._duration = int(sequence.source_duration_ms) / 1000.0
        self._playback_mode = "source" if linear else "mapped"

    def _multitrack_preview_target(self, timeline_ms: int) -> dict[str, object] | None:
        """Resolve the bottom composition layer used as the mpv clock/base."""

        layers = self._multitrack_preview_layers(timeline_ms)
        if layers:
            return layers[0]
        # Audio-only projects may retain a disabled legacy V1 clip after a
        # project is migrated from the recognition flow. Treat both that
        # linked A/V audio layer and a standalone A-track as a first-class
        # ProjectClock source; otherwise the graph reports no audible owner
        # and a valid 20-minute audio project is suspended at open.
        audio_layers = self._multitrack_audio_layers(timeline_ms)
        # Prefer an explicit standalone A-track when a migrated project also
        # carries a disabled linked V1 copy of the same asset.
        audio_layer = next(
            (layer for layer in audio_layers if layer.get("audio_only_source")),
            None,
        ) or next(
            (layer for layer in audio_layers if layer.get("audio_only")),
            None,
        )
        if audio_layer is not None:
            return {
                "key": f"audio-only:{audio_layer.get('clip_id') or audio_layer.get('track_id')}",
                "track_id": str(audio_layer.get("track_id") or ""),
                "track_name": str(audio_layer.get("track_name") or "Audio"),
                "clip_id": str(audio_layer.get("clip_id") or ""),
                "asset_id": str(audio_layer.get("asset_id") or ""),
                "source_path": str(audio_layer.get("source_path") or ""),
                "source_ms": int(audio_layer.get("source_ms") or 0),
                "source_in_ms": int(audio_layer.get("source_in_ms") or 0),
                "timeline_in_ms": int(audio_layer.get("timeline_in_ms") or 0),
                "timeline_out_ms": int(audio_layer.get("timeline_out_ms") or 0),
                "mode": "audio_only",
                "audio_enabled": bool(audio_layer.get("audio_enabled", True)),
                "track_muted": bool(audio_layer.get("track_muted", False)),
                "audio_only_source": True,
            }
        return None

    def _degenerate_primary_layer(
        self,
        project: SubtitleProject,
        timeline_ms: int,
    ) -> dict[str, object] | None:
        """Single-source fallback when the video graph can never resolve.

        A recognition-era project whose probe failed everywhere keeps a
        zero-duration graph. Suspending on the first tick would stop mpv and
        black out both the video and the subtitles. Keep mpv on the primary
        source instead — the same single-video path a healthy V1 uses.
        """

        from .studio_media_pool import (
            media_graph_duration_ms,
            primary_video_track_id,
        )

        if not project.media.path or not Path(project.media.path).is_file():
            return None
        if not project.video_tracks:
            return None
        if media_graph_duration_ms(project) > 0:
            # A healthy graph may legitimately have a gap at this playhead.
            return None
        try:
            source_path = str(Path(project.media.path).resolve())
        except (OSError, ValueError):
            source_path = str(project.media.path)
        track_id = primary_video_track_id(project)
        track = next(
            (item for item in project.video_tracks if item.id == track_id),
            None,
        )
        clip = track.clips[0] if track and track.clips else None
        if clip is not None:
            asset = next((item for item in project.media_pool if item.asset_id == clip.asset_id), None)
            if asset is not None and (asset.video_metadata or {}).get("has_video") is False:
                return None
        return {
            "key": "primary-salvage",
            "track_id": track_id,
            "track_name": track.name if track is not None else track_id,
            "clip_id": clip.id if clip is not None else "",
            "asset_id": clip.asset_id if clip is not None else "",
            "source_path": source_path,
            "source_ms": max(0, int(timeline_ms)),
            "source_in_ms": 0,
            "timeline_in_ms": 0,
            "timeline_out_ms": 0,
            "mode": "source",
            "transform": {
                "position_x": 0.5,
                "position_y": 0.5,
                "scale_x": 1.0,
                "scale_y": 1.0,
                "rotation": 0.0,
                "opacity": 1.0,
                "anchor_x": 0.5,
                "anchor_y": 0.5,
                "fit_mode": "contain",
            },
            "audio_enabled": True if clip is None else bool(clip.audio_enabled),
            "track_muted": bool(track.muted) if track is not None else False,
        }

    def _overlay_playback_path(self, source_path: str, *, asset=None, force: bool = False) -> str:
        """ffmpeg accepts the original codec/container; proxy creation is optional."""
        return source_path

    def _schedule_overlay_proxy_resync(self) -> None:
        """代理生成期间每 3s 重发一次合成同步，就绪即切代理（上限 ~60s）。"""

        state = getattr(self, "_overlay_proxy_resync", None)
        if state is None:
            state = {"timer": None, "count": 0}
            self._overlay_proxy_resync = state
        if state["count"] >= 20:
            return
        timer = state["timer"]
        if timer is not None and timer.isActive():
            return
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._overlay_proxy_resync_fire)
            state["timer"] = timer
        state["count"] += 1
        timer.start(3000)

    def _overlay_proxy_resync_fire(self) -> None:
        if getattr(self, "project", None) is None:
            return
        playhead = getattr(getattr(self, "timeline", None), "playhead_ms", 0)
        try:
            # 重建合成层（_sync_multitrack_preview_at 只管 mpv seek，不会重建
            # layers——代理切换需要走 _sync_video_compositor）。
            self._sync_video_compositor(int(playhead))
        except Exception:
            pass

    def _preview_media_path(self, path: str) -> str:
        """Resolve source identity once per project/path, never per video frame.

        Windows resolve() opens every path component. On a recording drive it
        can consume the whole frame budget even though the path never changes.
        Relinks use a new key; reopening a project discards the cache.
        """
        if getattr(self, "_preview_path_project", None) is not self.project:
            self._preview_path_project = self.project
            self._preview_resolved_paths = {}
            self._preview_indexed_paths = {}
            self._preview_source_kinds = {}
            self._preview_playback_memo = {}
        cache = getattr(self, "_preview_resolved_paths", None)
        if cache is None:
            cache = self._preview_resolved_paths = {}
        key = str(path)
        if key not in cache:
            try:
                cache[key] = str(Path(key).resolve())
            except (OSError, ValueError):
                cache[key] = key
        resolved = cache[key]
        if not resolved.lower().endswith(".flv"):
            return resolved
        from time import monotonic
        from .indexed_media import GLOBAL_INDEXED_MEDIA
        # playback_source() stats the source, proxy and markers (~10 calls)
        # and this runs several times per playback frame. Re-check each
        # source at most every 250 ms: a finished proxy is still adopted at
        # the next transport boundary, and polling keeps the build chain going.
        memo = getattr(self, "_preview_playback_memo", None)
        if memo is None:
            memo = self._preview_playback_memo = {}
        now = monotonic()
        remembered = memo.get(resolved)
        if remembered is not None and remembered[0] > now:
            playback, kind, indexed = remembered[1:]
        else:
            playback, kind = GLOBAL_INDEXED_MEDIA.playback_source(resolved)
            indexed = str(playback) if playback is not None else GLOBAL_INDEXED_MEDIA.resolve(resolved)
            memo[resolved] = (now + 0.25, playback, kind, indexed)
        if kind == "original":
            indexed = resolved
        active = getattr(self, "_preview_indexed_paths", None)
        if active is None:
            active = self._preview_indexed_paths = {}
        kinds = getattr(self, "_preview_source_kinds", None)
        if kinds is None:
            kinds = self._preview_source_kinds = {}
        video = getattr(self, "video", None)
        clock = getattr(video, "_playback_clock", None)
        paused = bool(getattr(video, "_paused", True))
        exact_seek = bool(getattr(clock, "exact_seek_pending", False))
        # Adopt a completed cache at a transport boundary, never interrupt
        # uninterrupted playback just because a background copy has finished.
        # A continuous proxy may also be adopted just before a known joint-gap
        # boundary — playback would freeze there on the gappy copy anyway, so
        # the switch replaces a multi-second stall with one boundary hop.
        near_gap = False
        if active.get(resolved) != indexed and not paused and not exact_seek:
            playhead_ms = int(getattr(getattr(self, "timeline", None), "playhead_ms", 0) or 0)
            near_gap = GLOBAL_INDEXED_MEDIA.next_gap_after(resolved, playhead_ms, window_ms=2500) is not None
        if resolved not in active or paused or exact_seek or near_gap or (
            kind == "proxy" and kinds.get(resolved) != "proxy"
        ):
            if active.get(resolved) != indexed or kinds.get(resolved) != kind:
                self._studio_trace(
                    "StudioPlaybackSource",
                    original=resolved,
                    optimized=str(playback) if playback is not None else "",
                    optimized_ready=playback is not None,
                    active_source=indexed,
                    kind=kind,
                    reason=("proxy_ready" if kind == "proxy" and kinds.get(resolved) != "proxy" else
                            "near_gap_boundary" if near_gap else
                            "exact_seek" if exact_seek else
                            "paused" if paused else "first_resolve"),
                )
            active[resolved] = indexed
            kinds[resolved] = kind
        video = getattr(self, "video", None)
        if video is not None:
            # §6：original/optimized=源时间域（观测/seek 过 AVSyncMap）；
            # continuous proxy=内容时间域（恒等，绝不过洞映射=防双映射）。
            video._set_playback_time_domain(
                "content" if kinds.get(resolved) == "proxy" else "source"
            )
        return active.get(resolved, resolved)

    def _active_playback_kind(self, path: str) -> str:
        resolved = str(path)
        try:
            resolved = str(Path(path).resolve())
        except (OSError, ValueError):
            pass
        if not resolved.lower().endswith(".flv"):
            return "original"
        return str(getattr(self, "_preview_source_kinds", {}).get(resolved, "original"))

    def _multitrack_preview_layers(self, timeline_ms: int) -> list[dict[str, object]]:
        """Resolve all active clips in stable V1 -> Vn paint order."""

        project = self.project
        if project is None:
            return []
        from .studio_media_pool import (
            active_video_clips,
            asset_by_id,
            primary_video_track_id,
        )

        from .studio_transitions import transition_windows, transition_gain
        windows = transition_windows(project, "video")
        primary_id = primary_video_track_id(project)
        layers: list[dict[str, object]] = []
        for track, clip in active_video_clips(project, timeline_ms):
            try:
                asset = asset_by_id(project, clip.asset_id)
            except KeyError:
                continue
            # An enabled V1 clip can be the legacy projection of an audio
            # source. It must not become a visual mpv layer or clock owner.
            if (asset.video_metadata or {}).get("has_video") is False:
                continue
            from .clip_time_mapper import map_project_time, record_clip_time_trace, ClipTimeTrace

            mapped = map_project_time(clip, int(timeline_ms))
            source_ms = mapped.source_ms if mapped.active else int(clip.source_in_ms)
            record_clip_time_trace(
                ClipTimeTrace(
                    project_target_ms=int(timeline_ms),
                    clip_id=clip.id,
                    track_id=track.id,
                    timeline_in_ms=int(clip.timeline_in_ms),
                    source_in_ms=int(clip.source_in_ms),
                    playback_rate=float(getattr(clip, "playback_rate", 1.0) or 1.0),
                    computed_source_ms=int(source_ms),
                    decoder_requested_ms=int(source_ms),
                    decoder_reported_ms=None,
                    frame_pts_ms=None,
                    presentation_ms=int(timeline_ms),
                    reason="preview_layer",
                )
            )
            source_path = self._preview_media_path(asset.canonical_source)
            primary_path = self._preview_media_path(project.media.path)
            primary_route = track.id == primary_id and source_path == primary_path
            if not primary_route:
                # 与主画面同源的叠加层强制走代理（force），否则 compositor 按
                # "mpv 已服务"跳过该层——V1/V2 放同一个文件时 V2 不显示。
                source_path = self._overlay_playback_path(
                    source_path,
                    asset=asset,
                    force=False,
                )
            if primary_route and (track.id,clip.id) not in windows:
                mapped = timeline_to_source(sequence_of(project), int(timeline_ms))
                if mapped is not None:
                    source_ms = mapped.source_ms
            transform = dict(vars(clip.transform))
            transform.update(
                self._video_transform_preview_overrides.get(clip.id, {})
            )
            envelopes = windows.get((track.id,clip.id),windows.get(clip.id, {})).get("envelopes", [])
            transition_active = any(e["start_ms"] <= timeline_ms < e["end_ms"] for e in envelopes)
            transform["opacity"] = float(transform.get("opacity", 1.)) * transition_gain(envelopes, timeline_ms)
            effects = dict(getattr(clip, "effects", {}) or {})
            effects.update(self._video_effects_preview_overrides.get(clip.id, {}))
            layers.append({
                "key": "primary" if primary_route else f"{track.id}:{clip.id}",
                "track_id": track.id,
                "track_name": track.name,
                "track_locked": bool(getattr(track, "locked", False)),
                "clip_id": clip.id,
                # The playback path may be a continuous proxy, so it cannot
                # identify the original asset or restore its source duration.
                "asset_id": clip.asset_id,
                "source_path": source_path,
                "source_ms": int(source_ms),
                "source_in_ms": int(clip.source_in_ms),
                "source_out_ms": int(clip.source_out_ms),
                "timeline_in_ms": int(clip.timeline_in_ms),
                "timeline_out_ms": int(clip.timeline_out_ms),
                "playback_rate": float(getattr(clip, "playback_rate", 1.0) or 1.0),
                "fps": float((asset.video_metadata or {}).get("fps") or 0.0),
                "source_w": float((asset.video_metadata or {}).get("width") or 0.0),
                "source_h": float((asset.video_metadata or {}).get("height") or 0.0),
                "mode": "primary" if primary_route else "multitrack",
                "primary_media": bool(primary_route),
                "transform": transform,
                "effects": effects,
                "transition_active": transition_active,
                "audio_enabled": bool(clip.audio_enabled),
                "track_muted": bool(track.muted),
            })
        if not layers:
            salvage = self._degenerate_primary_layer(project, int(timeline_ms))
            if salvage is not None:
                layers.append(salvage)
        return layers

    def _multitrack_audio_layers(self, timeline_ms: int) -> list[dict[str, object]]:
        from .audio_graph import audio_graph_signature, capture_audio_graph, preview_audio_layers
        if self.project is None:
            return []
        signature = audio_graph_signature(self.project)
        if signature != getattr(self, '_audio_contract_signature', None):
            self._audio_contract = capture_audio_graph(self.project)
            self._audio_contract_signature = signature
        layers = preview_audio_layers(self._audio_contract, timeline_ms)
        overrides = getattr(self, '_gain_preview_values', {})
        # Reuse only the lossless index already selected by this project's
        # video preview. Audio never creates an index or changes the graph.
        resolved_paths = {}
        indexed_paths = {}
        if getattr(self, '_preview_path_project', None) is self.project:
            resolved_paths = getattr(self, '_preview_resolved_paths', {})
            indexed_paths = getattr(self, '_preview_indexed_paths', {})
        for layer in layers:
            source = str(layer.get('source_path') or '')
            resolved = resolved_paths.get(source)
            if resolved and resolved.lower().endswith('.flv'):
                indexed = indexed_paths.get(resolved)
                if indexed and indexed != resolved:
                    layer['source_path'] = indexed
            if layer['audio_track_id'] in overrides:
                layer['gain_db'] = overrides[layer['audio_track_id']]
        return layers

    def _refresh_audio_mix_only(self):
        if self.project is None:
            return
        layers = self._multitrack_audio_layers(int(self.timeline.playhead_ms))
        args = dict(paused=self.video._paused, transport_rate=float(getattr(self, '_shuttle_speed', 1.) or 1.),
                    volume=self.volume_slider.value()/100.)
        if self.audio_engine._last_payload.get('mix_layers') is not None:
            self.audio_engine.synchronize_mix(layers, **args)
        else:
            self.audio_engine.synchronize(layers[0] if layers else None, audible=bool(layers), **args)

    def _sync_video_compositor(self, timeline_ms: int) -> None:
        scene = getattr(self, "video_compositor", None)
        if scene is not None and self.project is not None:
            from .studio_media_pool import primary_video_track_id
            base_id = primary_video_track_id(self.project)
            assets = {asset.asset_id: asset for asset in self.project.media_pool}
            warm = []
            for track in self.project.video_tracks:
                if not track.enabled or track.id == base_id:
                    continue
                for clip in track.clips:
                    if clip.enabled and 0 < clip.timeline_in_ms - timeline_ms <= 1500:
                        asset = assets.get(clip.asset_id)
                        if asset is not None and not asset.offline:
                            warm.append({'clip_id': clip.id, 'source_ms': clip.source_in_ms,
                                'source_path': self._overlay_playback_path(self._preview_media_path(asset.canonical_source), asset=asset),
                                'seek_token':self.video.playback_position_snapshot().playback_generation})
            scene.prewarm(warm)
        audio_layers = self._multitrack_audio_layers(timeline_ms)
        layers = self._multitrack_preview_layers(timeline_ms)
        if layers and hasattr(self,'media_availability'):
            self.media_availability.clear_gap()
        self._multitrack_composition_active = False
        if scene is None or not layers:
            if scene is not None:
                scene.suspend()
            decision = self._audio_playback_graph.consume_resolved(audio_layers)
            self._audio_playback_decision = decision
            snapshot = self.video.playback_position_snapshot()
            if hasattr(self, "audio_engine"):
                if decision.mix_mode:
                    self.audio_engine.synchronize_mix(decision.secondary_layers,
                        paused=bool(snapshot.paused),
                        transport_rate=float(getattr(self, "_shuttle_speed", 1.0) or 1.0),
                        volume=float(self.volume_slider.value()) / 100.0)
                else:
                    layer = next((x for x in audio_layers if x['track_id'] == decision.audible_track_id), None)
                    self.audio_engine.synchronize(layer, audible=decision.has_owner,
                        paused=bool(snapshot.paused),
                        transport_rate=float(getattr(self, "_shuttle_speed", 1.0) or 1.0),
                        volume=float(self.volume_slider.value()) / 100.0)
            self._silence_mix_audio_engines()
            if hasattr(self, 'media_availability'):
                self.media_availability.show_gap(timeline_ms)
            return
        if hasattr(self, "position_overlay"):
            scene.set_video_size(self.position_overlay.video_width, self.position_overlay.video_height)
        base_track_id = str(layers[0].get("track_id") or "")
        audio_layers = self._multitrack_audio_layers(timeline_ms)
        # Consume the same resolved graph as export. Re-selecting a master
        # from selected_video_clip_id here disagreed with the persisted track
        # selection and silenced the only surviving input when V2 was selected.
        solos = ()
        decision = self._audio_playback_graph.consume_resolved(audio_layers, base_track_id=base_track_id)
        master_track_id = decision.master_track_id
        self._audio_playback_decision = decision
        snapshot = self.video.playback_position_snapshot()
        paused = bool(snapshot.paused)
        rate = float(getattr(self, "_shuttle_speed", 1.0) or 1.0)
        scene.set_selected_clip(self.timeline.selected_video_clip_id)
        controller = getattr(self.video, 'controller', None)
        binding = ('', '', '')
        if controller is not None and getattr(controller, '_subtitle_media_ready', False):
            binding = (str(self._active_video_preview_track_id or ''),
                       str(self._active_video_preview_clip_id or ''),
                       str(self._active_video_preview_source_path or ''))
        scene.set_composition(
            layers,
            paused=paused,
            rate=rate,
            audio_master_track_id=master_track_id,
            base_track_id=base_track_id,
            volume=float(self.volume_slider.value()) / 100.0,
            solo_track_ids=solos,
            audio_decision=decision,
            audio_layers=audio_layers,
            seeking=bool(snapshot.seeking or snapshot.exact_seek_pending),
            seek_generation=snapshot.playback_generation,
            project_ms=int(timeline_ms),
            mpv_path=str(getattr(self.video, "_media_path", "") or ""),
            mpv_binding=binding,
        )
        self._multitrack_composition_active = scene.has_video_overlays
        master_layer = next(
            (
                layer for layer in audio_layers
                if str(layer.get("track_id") or "") == decision.audible_track_id
            ),
            None,
        )
        if hasattr(self, "audio_engine"):
            if decision.mix_mode:
                # One mixed PCM stream and one WASAPI session for every lane.
                self.audio_engine.synchronize_mix(
                    decision.secondary_layers,
                    paused=paused,
                    transport_rate=rate,
                    volume=float(self.volume_slider.value()) / 100.0,
                )
                self._silence_mix_audio_engines()
            else:
                self.audio_engine.synchronize(
                    master_layer,
                    audible=decision.has_owner and not decision.mpv_output_enabled,
                    paused=paused,
                    transport_rate=rate,
                    volume=float(self.volume_slider.value()) / 100.0,
                )
                self._silence_mix_audio_engines()
        # Restack the native overlay windows above the video only when the
        # stack can have changed. Every playback tick used to issue three
        # SetWindowPos calls next to mpv's cross-process video window.
        advanced = getattr(self, "advanced_cue_overlay", None)
        position = getattr(self, "position_overlay", None)
        stack_key = (id(scene), bool(scene.isVisible()),
                     bool(advanced is not None and advanced.isVisible()),
                     bool(position is not None and position.isVisible()),
                     tuple(str(layer.get("clip_id") or "") for layer in layers))
        now = _time.monotonic()
        if stack_key != getattr(self, "_overlay_stack_key", None) or now - getattr(self, "_overlay_stack_at", 0.0) > 2.0:
            self._overlay_stack_key, self._overlay_stack_at = stack_key, now
            scene.raise_()
            if advanced is not None and advanced.isVisible():
                advanced.raise_()
            if position is not None and position.isVisible():
                position.raise_()

    def _resync_compositor_after_keep(self, timeline_ms: int) -> None:
        """keep-mpv 早退路径仍要让合成器退役已结束的叠加层。

        播放头越过 graph 尾部（V3 的 clip 排最尾）时层列表已经为空，但传输层
        保持挂载（EOF 黑屏恢复链）。此前这里直接 return None 跳过了
        `_sync_video_compositor`——合成器 `_layers` 永不刷新，mpv 里最后一次
        发布的 VIDEO_OVERLAY 位图（已结束 clip 的最后一帧）永久残留，用户
        实录"V3 播完后画面钉死，跳转几次才消失"。按 tick 去重：离开 tail/degenerate
        状态（正常 target / gap / 工程会话关闭）后自动复位。
        """
        if getattr(self, "_composition_keep_resynced", False):
            return
        self._composition_keep_resynced = True
        try:
            self._sync_video_compositor(int(timeline_ms))
        except Exception:  # noqa: BLE001 - keep-mpv 兜底路径绝不向上抛
            pass

    def _activate_multitrack_preview(
        self,
        timeline_ms: int,
    ) -> tuple[dict[str, object], bool] | None:
        if self.project is None:
            return None  # A queued playback callback may arrive after returning to Library.
        target = self._multitrack_preview_target(timeline_ms)
        if target is None:
            from .studio_media_pool import media_graph_duration_ms
            if self.project and timeline_ms >= media_graph_duration_ms(self.project) > 0 and bool(getattr(self.video, "_media_attached", False)):
                if not getattr(self, "_composition_keep_resynced", False):
                    self._sync_video_compositor(timeline_ms)
                    self._composition_keep_resynced = True
                return None
            self._audio_only_subtitle_active = True
            self.video.set_external_clock_enabled(False)
            self.video.set_project_time_mapping(enabled=False)
            self.video.set_source_rate_multiplier(1.0)
            scene = getattr(self, "video_compositor", None)
            if scene is not None:
                scene.suspend()
            self._silence_mix_audio_engines()
            if hasattr(self, "audio_engine"):
                self.audio_engine.synchronize(
                    None,
                    audible=False,
                    paused=True,
                    transport_rate=1.0,
                    volume=0.0,
                )
            from .studio_media_pool import media_graph_duration_ms

            media_path = str(self.project.media.path or "") if self.project else ""
            from .media_availability import media_available
            media_exists = media_available(self.project, media_path) if self.project else False
            degenerate = bool(
                self.project is not None and media_graph_duration_ms(self.project) <= 0
            )
            # A reachable primary source must never be cleared just because the
            # graph is a 0→0 Recognition migration artifact. Genuine timeline
            # gaps after a healthy graph still suspend.
            if media_exists and degenerate:
                self._studio_trace(
                    "P74C_PREVIEW_DEGENERATE_KEEP_MPV",
                    media_path=media_path,
                    playhead_ms=int(timeline_ms),
                )
                self._resync_compositor_after_keep(timeline_ms)
                return None
            # Natural EOF / playhead past the graph tail: the clip lookup is
            # half-open ([in, out)), so t == timeline_out_ms resolves to "gap"
            # and used to stop mpv outright — black video, dead audio, and
            # every later seek hit an idle player (2026-09-02 EOF 黑屏根因).
            # Keep the transport attached so the last frame stays visible and
            # seeks keep working; only true mid-timeline gaps suspend.
            graph_end_ms = (
                media_graph_duration_ms(self.project) if self.project is not None else 0
            )
            if (
                graph_end_ms > 0
                and int(timeline_ms) >= graph_end_ms - 1
                and bool(getattr(self.video, "_media_attached", False))
            ):
                self._studio_trace(
                    "P74C_PREVIEW_TAIL_KEEP_MPV",
                    graph_end_ms=int(graph_end_ms),
                    playhead_ms=int(timeline_ms),
                )
                self._resync_compositor_after_keep(timeline_ms)
                return None
            if self._active_video_preview_key != "__gap__":
                self._composition_keep_resynced = False
                previous_key = self._active_video_preview_key
                self._playhead_ui_pending = None
                self._playback_mode = "multitrack"
                self._active_video_preview_key = "__gap__"
                self._active_video_preview_track_id = ""
                self._active_video_preview_clip_id = ""
                self._active_video_preview_source_path = ""
                self._active_video_preview_volume = None
                self.video.enter_timeline_gap(timeline_ms, timeline_duration_ms(self.project))
                self._studio_trace('TIMELINE_GAP_ENTER', project_ms=int(timeline_ms),
                    previous_key=previous_key, generation=self.video._playback_clock.generation,
                    paused=self.video._paused, reason='no_active_media_layer')
                if hasattr(self, 'media_availability'):
                    self.media_availability.show_gap(timeline_ms)
                if hasattr(self, "media_pool_panel"):
                    bind_text(self.media_pool_panel.preview_contract, '预览：当前位置没有可用的启用片段')
            return None
        key = str(target["key"])
        source_path = str(target["source_path"])
        token = getattr(self, '_owned_audio_tail', None)
        tail = bool(token is not None and token.project_identity == id(self.project)
            and token.preview_key == key and token.clip_id == str(target['clip_id'])
            and token.generation == self.video._playback_clock.generation)
        if token is not None and not tail:
            self._invalidate_audio_tail()
        visual_tail = tail or (key == str(self._active_video_preview_key)
            and source_path == str(self._active_video_preview_source_path)
            and str(target['clip_id']) == str(self._active_video_preview_clip_id)
            and self._audio_tail_visual_active())
        self._audio_only_subtitle_active = target.get("mode") == "audio_only" or visual_tail
        # mpv is the primary demux/decode/sync owner for both video and
        # audio-only sources.  AudioEngine is reserved for a non-primary
        # external lane and must never become a second master clock.
        mapping = dict(getattr(self.project, "studio_state", {}).get("media_time_mapping", {}))
        asset = next(
            (item for item in getattr(self.project, "media_pool", ())
             if (str(getattr(item, "asset_id", "")) == str(target.get("asset_id") or "")
                 or str(getattr(item, "canonical_source", "")) == source_path)),
            None,
        )
        if asset is not None:
            video_meta = dict(getattr(asset, "video_metadata", {}) or {})
            audio_meta = dict(getattr(asset, "audio_metadata", {}) or {})
            mapping.update({
                "source_start_ms": video_meta.get(
                    "source_start_ms",
                    audio_meta.get("source_start_ms", mapping.get("source_start_ms", 0.0)),
                ),
                "video_start_ms": video_meta.get("start_time_ms", mapping.get("video_start_ms", 0.0)),
                "audio_start_ms": audio_meta.get("start_time_ms", mapping.get("audio_start_ms", 0.0)),
                "video_timebase": video_meta.get("timebase", mapping.get("video_timebase", "")),
                "audio_timebase": audio_meta.get("timebase", mapping.get("audio_timebase", "")),
                "sample_rate": audio_meta.get("sample_rate", mapping.get("sample_rate", 0)),
                "sample_timeline_origin_ms": audio_meta.get("sample_timeline_origin_ms", mapping.get("sample_timeline_origin_ms", 0.0)),
            })
        self.video.set_media_time_mapping(
            mapping,
            has_video=target.get("mode") != "audio_only",
        )
        self.video.set_external_clock_enabled(target.get("mode") == "audio_only" or tail)
        self.video.set_project_time_mapping(
            enabled=target.get("mode") == "multitrack",
            timeline_in_ms=int(target.get("timeline_in_ms") or 0),
            source_in_ms=int(target.get("source_in_ms") or 0),
            playback_rate=float(target.get("playback_rate") or 1.0),
        )
        self.video.set_source_rate_multiplier(
            float(target.get("playback_rate") or 1.0) if target.get("mode") == "primary" else 1.0)
        if target.get('mode') != 'primary':
            self.video._duration_override = timeline_duration_ms(self.project) / 1000.0
            self.video._duration = self.video._duration_override
        else:
            # Primary clock is source time; another source's short duration
            # must not clamp a retained deep source range after a handoff.
            self.video._duration_override = 0.0
            if asset is not None:
                self.video._duration = asset.duration_ms / 1000.0
        switched = key != self._active_video_preview_key or source_path != self._active_video_preview_source_path
        switch_seek_posted = False
        if switched:
            # 2026-09-18：精确 seek 挂起时，本函数拿到的 timeline_ms 可能是跟随
            # 定时器尚未传播的旧播放头——用它换绑 loadfile 会吞掉刚发出的 seek
            # （真机复现：开工程首 seek 5872s 落回恢复播放头 7061s）。换绑目标
            # 必须采纳时钟的乐观 seek 位置。
            pending_clock = getattr(self.video, "_playback_clock", None)
            if (pending_clock is not None and bool(getattr(pending_clock, "exact_seek_pending", False))
                    and not getattr(self, '_explicit_project_seek', False)):
                # pending 目标以 seek trace 为准；画布尚未绑媒时 visual_position
                # 仍是 0（真机二次复现：采纳 visual 位置把首 seek 换绑到了 0s）。
                pending_trace = getattr(self.video, "_active_seek_trace", None)
                # target_seconds uses the canvas clock domain, which is SOURCE
                # time on V1. Only an explicit project coordinate is safe here.
                pending_s = float(pending_trace.get('requested_project_ms', -1000)) / 1000 if isinstance(pending_trace, dict) else -1.0
                optimistic_ms = int(pending_s * 1000) if pending_s >= 0 else int(timeline_ms)
                if pending_s >= 0 and abs(optimistic_ms - int(timeline_ms)) > 250:
                    remapped = timeline_to_source(sequence_of(self.project), optimistic_ms)
                    adopted = remapped.source_ms if remapped is not None else int(target["source_ms"])
                    self._studio_trace(
                        "VIDEO_REBIND_ADOPTED_PENDING_SEEK",
                        stale_timeline_ms=int(timeline_ms),
                        adopted_project_ms=optimistic_ms,
                        adopted_source_ms=int(adopted),
                    )
                    target["source_ms"] = int(adopted)
                    timeline_ms = optimistic_ms
            self._studio_trace('VIDEO_PREVIEW_REBIND',previous_key=self._active_video_preview_key,
                preview_key=key,source_path=source_path,project_ms=int(timeline_ms),
                playback_generation=self.video.playback_position_snapshot().playback_generation)
            current_path = str(getattr(self.video, "_media_path", "") or "")
            try:
                same_path = Path(current_path).resolve() == Path(source_path).resolve()
            except (OSError, ValueError):
                same_path = current_path == source_path
            # Same path is not enough after a gap suspend: mpv was ``stop``-ed
            # into idle, holds no file, and silently rejects every seek. Rebind
            # through loadfile whenever the canvas believes no media is
            # attached, path change or not (EOF/黑屏恢复链).
            if not same_path or not bool(getattr(self.video, "_media_attached", True)):
                # 换绑风暴门（2026-09-20 黑屏根因）：mpv 正在加载当前文件时，
                # 立刻 replace 成新源（原片→seek代理→continuous代理的连环
                # 切换）会把每次加载都打断，mpv 永远出不了第一帧（用户日志
                # 实录 18s+ 黑屏、observed_media_ms 恒 0）。加载期只登记，
                # 等画布 READY 后由 _retry_deferred_source_rebind 补切；
                # 换切时的 position/pause/rate 继承由 switch_media_at_async
                # 既有逻辑保证。gap/EOF 恢复（_media_attached=False）不走门。
                startup = str(getattr(self.video, "_startup_state", "READY"))
                loading_real_file = (
                    startup == "MEDIA_OPENING"
                    and bool(getattr(self.video, "_startup_play_requested", False))
                    and str(getattr(self.video, "_media_path", "") or "") != ""
                    and not same_path
                )
                if loading_real_file:
                    self._deferred_source_rebind = True
                    self._studio_trace(
                        "VIDEO_REBIND_DEFERRED",
                        desired_source=source_path,
                        current_source=current_path,
                        project_ms=int(timeline_ms),
                        startup=startup,
                    )
                    target["switch_seek_posted"] = False
                    return target, False
                switch_at = getattr(self.video, "switch_media_at_async", None)
                if callable(switch_at):
                    switch_seek_posted = bool(switch_at(
                        source_path,
                        str(self._preview_path or ""),
                        source_seconds=int(target["source_ms"]) / 1000.0,
                        project_ms=int(timeline_ms),
                    ))
                if not switch_seek_posted:
                    switch = getattr(self.video, "switch_media_async", None)
                    if not callable(switch) or not switch(
                        source_path,
                        str(self._preview_path or ""),
                    ):
                        return None
                self._deferred_source_rebind = False
            self._active_video_preview_key = key
            self._active_video_preview_track_id = str(target["track_id"])
            self._active_video_preview_clip_id = str(target["clip_id"])
            self._active_video_preview_source_path = source_path
            self._active_video_preview_source_in_ms = int(target["source_in_ms"])
            self._active_video_preview_timeline_in_ms = int(target["timeline_in_ms"])
            self._playback_mode = (
                "multitrack"
                if target["mode"] == "multitrack"
                else (
                    "source"
                    if sequence_of(self.project).is_linear_source()
                    else "mapped"
                )
            )
            if hasattr(self, "media_pool_panel"):
                from .studio_media_pool import audio_master_track_id

                master_id = audio_master_track_id(self.project)
                bind_text(self.media_pool_panel.preview_contract, '预览：{value0} {value1} · 多轨合成 · 当前声音 {master_id}', value0=target['track_id'], value1=target['track_name'], master_id=master_id)
        # Several edits on V1 share the "primary" transport key. Keep the
        # instance identity current even when no media reload is needed.
        self._active_video_preview_clip_id = str(target["clip_id"])
        self._active_video_preview_source_in_ms = int(target["source_in_ms"])
        self._active_video_preview_timeline_in_ms = int(target["timeline_in_ms"])
        target["switch_seek_posted"] = switch_seek_posted
        self._composition_keep_resynced = False
        self._sync_video_compositor(timeline_ms)
        self._apply_active_video_track_volume(str(target["track_id"]))
        return target, switched

    def _silence_mix_audio_engines(self) -> None:
        pool = getattr(self, "_mix_audio_engines", None)
        if not pool:
            return
        for engine in pool.values():
            engine.unload()
            engine.request_shutdown()
        pool.clear()

    def _apply_active_video_track_volume(self, track_id: str) -> None:
        del track_id
        from .studio_media_pool import audio_master_track_id

        master_id = audio_master_track_id(self.project) if self.project else ""
        decision = self._audio_playback_decision
        base_owns_audio = bool(decision.mpv_output_enabled)
        desired = float(self.volume_slider.value()) if base_owns_audio else 0.0
        if self._active_video_preview_volume == desired:
            volume_current = True
        else:
            volume_current = False
        controller = getattr(self.video, "controller", None)
        post_audio = getattr(controller, "post_set_audio_enabled", None)
        if self._active_mpv_audio_enabled != base_owns_audio:
            if callable(post_audio) and post_audio(base_owns_audio):
                self._active_mpv_audio_enabled = base_owns_audio
        post_volume = getattr(controller, "post_set_volume", None)
        if not volume_current and callable(post_volume) and post_volume(desired):
            self._active_video_preview_volume = desired
        if hasattr(self, "video_audio_owner_label"):
            if decision.mix_mode and decision.mix_track_ids:
                names = "+".join(decision.mix_track_ids)
                telemetry = self.audio_engine.telemetry_snapshot() if hasattr(self, "audio_engine") else {}
                bind_text(self.video_audio_owner_label, '当前声音：{names} · 混音 · {value1}', names=names, value1=telemetry.get('state', 'IDLE'))
                return
            master = next(
                (item for item in self.project.video_tracks if item.id == master_id),
                None,
            ) if self.project else None
            state = "启用" if decision.has_owner else "静音"
            telemetry = self.audio_engine.telemetry_snapshot() if hasattr(self, "audio_engine") else {}
            bind_text(self.video_audio_owner_label, '当前声音：{value0} · {state} · 单一引擎 · {value2}', value0=decision.audible_track_id or master_id or '-', state=state, value2=telemetry.get('state', 'IDLE'))

    def _maybe_apply_av_sync_map(self) -> None:
        """Adopt the AV sync map once the background scan has produced it.

        The project timeline runs in audio-content time regardless; the map
        only translates mpv seeks/observations and the audio engine's input
        seeks. Identity maps (healthy media) never change behaviour.
        """
        project = getattr(self, "project", None)
        if project is None:
            return
        source = str(project.media.path or "")
        if not source.lower().endswith(".flv"):
            return
        from .indexed_media import GLOBAL_INDEXED_MEDIA

        auto = GLOBAL_INDEXED_MEDIA.sync_map(source)
        if auto is None:
            return
        from .avsync import AVSyncMap, SyncOverride

        overrides = [
            SyncOverride(
                at_ms=int(item.get("at_ms", 0) or 0),
                offset_ms=int(item.get("offset_ms", 0) or 0),
            )
            for item in (project.studio_state.get("av_sync_overrides") or [])
            if isinstance(item, dict)
        ]
        # When preview consumers are bound to the continuous proxy, its
        # timestamps already ARE the audio content clock: fold the gap map
        # away (manual corrections still apply on top).
        playback, kind = GLOBAL_INDEXED_MEDIA.playback_source(source)
        if kind == "proxy":
            effective = AVSyncMap(
                (),
                source_duration_ms=int(
                    auto.content_duration_ms or auto.source_duration_ms or 0
                ),
                overrides=overrides,
            )
        else:
            effective = auto.with_overrides(overrides) if overrides else auto
        video = getattr(self, "video", None)
        if video is not None:
            # §6：域与映射同源设置——proxy=内容域（恒等），其余=源域。
            video._set_playback_time_domain(
                "content" if kind == "proxy" else "source"
            )
        identity = effective.to_dict()
        if getattr(self, "_applied_av_sync_map", None) == identity:
            return
        self._applied_av_sync_map = identity
        self.video.set_av_sync_map(effective)
        engine = getattr(self, "audio_engine", None)
        if engine is not None:
            engine.set_av_sync_map(effective)
        content_ms = int(effective.content_duration_ms or 0)
        if 0 < content_ms < int(project.media.duration_ms or 0):
            project.media.duration_ms = content_ms
            for asset in project.media_pool:
                try:
                    same = str(Path(asset.canonical_source).resolve()) == str(Path(source).resolve())
                except (OSError, ValueError):
                    same = False
                if same:
                    asset.duration_ms = content_ms
            timeline = getattr(self, "timeline", None)
            if timeline is not None:
                timeline._rebuild_cue_index()
                timeline._sync_scrollbars()
                timeline.update()
        self._studio_trace(
            "AVSyncMap",
            applied=True,
            gaps=len(effective.gaps),
            total_gap_ms=effective.total_gap_ms,
            content_duration_ms=content_ms,
            overrides=len(overrides),
        )

    def _reset_av_sync_map(self) -> None:
        self._applied_av_sync_map = None
        video = getattr(self, "video", None)
        if video is not None:
            video.set_av_sync_map(None)
        engine = getattr(self, "audio_engine", None)
        if engine is not None:
            engine.set_av_sync_map(None)

    def _av_sync_manual_correction(self) -> None:
        """Manual piecewise correction: shift video from the playhead on.

        Entering 0 clears every manual correction. Corrections apply on top
        of the automatic gap map and persist with the project.
        """
        project = getattr(self, "project", None)
        if project is None:
            return
        from PySide6.QtWidgets import QInputDialog

        playhead_ms = int(getattr(self.timeline, "playhead_ms", 0) or 0)
        existing = [
            f"{item.get('at_ms', 0) / 1000:.1f}s {item.get('offset_ms', 0):+d}ms"
            for item in (project.studio_state.get("av_sync_overrides") or [])
            if isinstance(item, dict)
        ]
        hint = "；".join(existing[-3:]) if existing else "无"
        text, ok = QInputDialog.getText(
            self,
            tr('音画同步校正'),
            tr('偏移毫秒数（正值：画面延后；负值：画面提前）。\n从当前播放头 {value0:.1f}s 起生效；输入 0 清除全部手动校正。\n已有校正：{value1}', value0=playhead_ms / 1000, value1=hint),
        )
        if not ok:
            return
        try:
            value = int(round(float(str(text).strip())))
        except ValueError:
            return
        if value == 0:
            project.studio_state["av_sync_overrides"] = []
        else:
            project.studio_state.setdefault("av_sync_overrides", []).append(
                {"at_ms": playhead_ms, "offset_ms": value}
            )
        self._applied_av_sync_map = None
        self._maybe_apply_av_sync_map()
        changed = getattr(self, "_changed", None)
        if callable(changed):
            changed()
        self._studio_trace(
            "AVSyncMap",
            manual_correction=True,
            at_ms=playhead_ms,
            offset_ms=value,
            overrides=len(project.studio_state.get("av_sync_overrides") or []),
        )

    def _retry_deferred_source_rebind(self) -> None:
        """画布就绪后补一次被换绑风暴门延迟的源切换。"""
        if not getattr(self, "_deferred_source_rebind", False):
            return
        self._deferred_source_rebind = False
        self._studio_trace(
            "VIDEO_REBIND_RETRY_AFTER_READY",
            project_ms=int(self.timeline.playhead_ms),
        )
        self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))

    def _sync_multitrack_preview_at(self, timeline_ms: int) -> None:
        self._maybe_apply_av_sync_map()
        intended = getattr(self.video, 'playback_intended', None)
        if intended is None:
            intended = not self.video._paused or bool(getattr(self.video, '_buffered_play_pending', False))
        paused = not intended
        if getattr(self.video, '_startup_state', 'READY') != 'READY' and getattr(self.video, '_startup_play_requested', False):
            paused = False
        preview = self._activate_multitrack_preview(timeline_ms)
        if preview is None:
            return
        target, switched = preview
        if not switched:
            return
        try:
            if not bool(target.get("switch_seek_posted")):
                self.video.seek(
                    int(target["source_ms"]) / 1000.0,
                    accurate=True,
                    project_ms=int(timeline_ms),
                )
            self.video.set_paused(paused)
        except RuntimeError:
            return

    def _enter_empty_playback_state(self) -> None:
        if getattr(self, "_empty_playback_state", False):
            self._sync_video_empty_state()
            return
        self._empty_playback_state = True
        self.video.enter_empty_playback_state()
        self._advanced_preview_state.generation += 1
        self._advanced_preview_state.identity = None
        self._advanced_preview_state.fallback()
        self._advanced_preview_expected_key = ""
        self._advanced_preview_snapshot = None
        self._advanced_preview_pending_payload: dict[str, object] | None = None
        self._advanced_preview_pending_force = False
        self._advanced_cue_pixmap = QPixmap()
        self._visual_ownership.commit(VisualOwner.NONE)
        self.video.set_native_subtitle_visible(False)
        if hasattr(self, "advanced_cue_overlay"):
            self.advanced_cue_overlay.hide()
        if hasattr(self, "position_overlay"):
            self.position_overlay.hide()
        if hasattr(self, "play_button"):
            self.play_button.setEnabled(False)
            self._sync_play_button(True)
        self._sync_video_empty_state()

    def _restore_nonempty_playback_state(self) -> None:
        was_empty = bool(getattr(self, "_empty_playback_state", False))
        self._empty_playback_state = False
        if was_empty and self.project:
            self.video.restore_after_empty(
                self.project.media.path,
                str(self._preview_path or ""),
            )
        if hasattr(self, "play_button"):
            self.play_button.setEnabled(bool(self.video.controller))
        self._sync_video_empty_state()

    def _reload_edit_playback(self) -> None:
        """Compatibility wrapper retained for callers; deliberately process-free."""
        self._refresh_edit_playback_state()
