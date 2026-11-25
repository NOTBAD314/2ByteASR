"""Align known lyrics to the Studio in/out range and preview an independent track."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QProgressDialog, QVBoxLayout,
)

from ..i18n import tr
from ..projects.project_range import clock_text
from ..recognition.range_recognition import requested_range


@dataclass(frozen=True)
class LyricsRequest:
    project: object
    points: tuple[int, int]
    playback_revision: int
    lines: tuple[str, ...]
    enhance_voice: bool
    draft_language: str = ""
    scene_probe: bool = False


def _model_dir():
    from ..runtime_paths import get_runtime_paths

    return get_runtime_paths().model_root / "Sylla-600M"


def _draft_model_dir():
    from ..recognition.asr import resolve_whisper_local_source

    selected = resolve_whisper_local_source()
    return Path(selected) if selected else None


def _scene_model_dir():
    from ..runtime_paths import get_runtime_paths

    return get_runtime_paths().model_root / "YAMNet"


def _render_region(points, mix, ffmpeg, directory, enhance_voice, cancel):
    from ..media.vocal_enhancement import _run, enhance_studio_clip
    from ..playback.cue_audio_preview import preview_command

    plan = SimpleNamespace(play_range_ms=points, layers=mix)
    command, _ = preview_command(plan, ffmpeg, cancelled=cancel.is_set)
    command = list(command)
    original = directory / "original.wav"
    command[command.index("-ac") + 1] = "2" if enhance_voice else "1"
    command[command.index("-ar") + 1] = "44100" if enhance_voice else "16000"
    command[-2:] = ["wav", str(original)]
    _run(command, "Render local lyric input", cancel.is_set, cwd=str(directory), timeout=60)
    if not enhance_voice:
        return original
    target = directory / "enhanced.wav"
    return enhance_studio_clip(original, target, ffmpeg, cancel_check=cancel.is_set).path


def _run_job(request, layers, ffmpeg, cancel):
    from ..media.vocal_enhancement import _run
    from ..runtime_paths import get_runtime_paths
    from ..system.processes import main_python_executable
    from ..system.runtime_registry import resolve_runtime_python

    paths = get_runtime_paths()
    paths.temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="studio-lyrics-", dir=paths.temp_root) as tmp:
        directory = Path(tmp)
        audio = _render_region(request.points, layers, ffmpeg, directory,
                               request.enhance_voice and not request.scene_probe, cancel)
        input_path, output_path = directory / "request.json", directory / "receipt.json"
        input_path.write_text(json.dumps(request.lines, ensure_ascii=False), encoding="utf-8")
        worker = paths.install_root / "scripts" / "lyrics_alignment_worker.py"
        python = resolve_runtime_python("main") or main_python_executable(paths.install_root)
        if not python:
            raise ValueError("请先准备本机识别运行环境")
        draft = not request.lines and not request.scene_probe
        model_dir = _scene_model_dir() if request.scene_probe else _draft_model_dir() if draft else _model_dir()
        if model_dir is None:
            raise ValueError("请先准备本机 Whisper 识别模型")
        command = [python, "-X", "utf8", "-B", str(worker), "--audio", str(audio),
                   "--request", str(input_path), "--model-dir", str(model_dir), "--output", str(output_path)]
        if draft:
            command.extend(("--draft", "--language", request.draft_language))
        if request.scene_probe:
            from ..recognition.lyric_scene import managed_runtime_directory

            command.extend(("--scene", "--scene-runtime", str(managed_runtime_directory(paths))))
        _run(command, "Align local song lyrics", cancel.is_set, cwd=str(paths.install_root), timeout=180)
        if output_path.stat().st_size > 1024 * 1024:
            raise ValueError("歌词时间记录过大")
        result = json.loads(output_path.read_bytes())
        if result.get("error"):
            raise ValueError(result["error"])
        return result["scene" if request.scene_probe else "draft" if draft else "lines"]


def _import_plan(project, request, rows):
    from ..projects.studio_project import StudioCue, StudioSpeaker
    from ..projects.subtitle_import import SubtitleImportPlan

    lo, hi = request.points
    if [row.get("text") for row in rows] != list(request.lines):
        raise ValueError("歌词回执与输入不一致")
    track = "lyrics-" + uuid4().hex
    instance = uuid4().hex
    names = {speaker.name for speaker in project.speakers}
    prefix = tr("对齐歌词")
    label, suffix = prefix, 2
    while label in names:
        label, suffix = f"{prefix} {suffix}", suffix + 1
    source = "htdemucs" if request.enhance_voice else "original"
    plan = SubtitleImportPlan(speakers=[StudioSpeaker(track, label)])
    plan.tracks[track] = dict(instance_id=instance, role="lyrics", timing_source="Sylla-600M",
                              audio_source=source)
    plan.instances[instance] = dict(kind="local_lyrics_alignment", range_ms=[lo, hi],
                                    model="Sylla-600M", timing_resolution_ms=20)
    previous = 0
    for row in rows:
        start, end = int(row["start_ms"]), int(row["end_ms"])
        if not previous <= start < end <= hi - lo:
            raise ValueError("歌词时间越界或交叠")
        words = []
        earlier = start
        for word in row.get("words", ()):
            a, b = int(word["start_ms"]), int(word["end_ms"])
            if not earlier <= a < b <= end or not 0 <= float(word["posterior"]) <= 1:
                raise ValueError("歌词词级时间回执无效")
            words.append(dict(start_ms=lo + a, end_ms=lo + b, posterior=word["posterior"]))
            earlier = b
        if not words or words[0]["start_ms"] != lo + start or words[-1]["end_ms"] != lo + end:
            raise ValueError("歌词缺少可靠的行边界")
        cue_id = "lyrics-cue-" + uuid4().hex
        plan.cues.append(StudioCue(cue_id, lo + start, lo + end, row["text"], speaker_id=track,
                                   original_text=row["text"], transform={"subtitle_role": "lyrics"}))
        plan.cue_sources[cue_id] = dict(instance_id=instance, role="lyrics", audio_source=source,
                                       start_basis="local_singing_alignment", end_basis="local_singing_alignment",
                                       words=words)
        previous = end
    return plan


def _preview(page, plan):
    dialog = QDialog(page)
    dialog.setWindowTitle(tr("核对歌词时间"))
    layout = QVBoxLayout(dialog)
    output = QPlainTextEdit(dialog)
    output.setReadOnly(True)
    output.setPlainText("\n".join(f"{clock_text(cue.start_ms)} – {clock_text(cue.end_ms)}   {cue.text}"
                                 for cue in plan.cues))
    layout.addWidget(output)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
    apply = buttons.addButton(tr("新增歌词轨道"), QDialogButtonBox.ButtonRole.AcceptRole)
    apply.clicked.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(680, 420)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _current(page, request):
    from ..projects.studio_runtime_state import state_for

    return (page.project is request.project and requested_range(page.project) == request.points
            and state_for(page.project).playback_revision == request.playback_revision)


def show(page, *, draft_text="", enhanced=False, scene_hint=""):
    project = page.project
    if project is None or getattr(page, "_local_lyrics_busy", False):
        return
    points = requested_range(project)
    if points is None or not 0 < points[1] - points[0] <= 30000:
        page._show_studio_hint(tr("请先设置 30 秒以内的入点和出点"))
        return
    can_align = (_model_dir() / "model.safetensors").is_file()
    can_draft = _draft_model_dir() is not None
    can_probe = (_scene_model_dir() / "yamnet.tflite").is_file()
    if not can_align and not can_draft and not can_probe:
        page._show_studio_hint(tr("请先准备本机 Sylla-600M 或 Whisper 歌词模型"))
        return
    from ..media.vocal_enhancement import assets_present
    from ..projects.studio_runtime_state import state_for

    dialog = QDialog(page)
    dialog.setWindowTitle(tr("对齐选区歌词"))
    form = QVBoxLayout(dialog)
    text = QPlainTextEdit(dialog)
    text.setPlaceholderText(tr("每行输入一句歌词，重复副歌按实际顺序保留"))
    text.setPlainText(draft_text)
    form.addWidget(QLabel(f"{clock_text(points[0])} – {clock_text(points[1])}", dialog))
    if scene_hint:
        form.addWidget(QLabel(scene_hint, dialog))
    form.addWidget(text)
    separate = QCheckBox(tr("先增强人声"), dialog)
    separate.setVisible(assets_present())
    separate.setChecked(enhanced and not separate.isHidden())
    form.addWidget(separate)
    language = QComboBox(dialog)
    language.setAccessibleName(tr("歌詞語言"))
    for key, label in (("", "自动判断语言"), ("en", "英语"), ("zh", "中文"), ("ja", "日语"),
                       ("es", "西班牙语"), ("fr", "法语"), ("de", "德语")):
        language.addItem(tr(label), key)
    language.setVisible(can_draft)
    form.addWidget(language)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
    start = buttons.addButton(tr("开始对齐"), QDialogButtonBox.ButtonRole.AcceptRole)
    draft = buttons.addButton(tr("生成歌词草稿"), QDialogButtonBox.ButtonRole.ActionRole)
    scene = buttons.addButton(tr("判断选区是否有歌唱"), QDialogButtonBox.ButtonRole.ActionRole)
    scene.setVisible(can_probe)
    scene_requested = False

    def update_buttons():
        has_text = bool(text.toPlainText().strip())
        start.setEnabled(can_align and has_text)
        draft.setEnabled(can_draft and not has_text)
        scene.setEnabled(can_probe and not has_text and points[1] - points[0] >= 1000)

    text.textChanged.connect(update_buttons)
    update_buttons()
    start.clicked.connect(dialog.accept)
    draft.clicked.connect(dialog.accept)

    def accept_scene():
        nonlocal scene_requested
        scene_requested = True
        dialog.accept()

    scene.clicked.connect(accept_scene)
    buttons.rejected.connect(dialog.reject)
    form.addWidget(buttons)
    dialog.resize(610, 368)
    if dialog.exec() != QDialog.DialogCode.Accepted or page.project is not project:
        return
    lines = tuple(line.strip() for line in text.toPlainText().splitlines() if line.strip())
    if len("".join(lines)) > 1500:
        page._show_studio_hint(tr("歌词超出局部音频可对齐范围"))
        return
    from ..exports.audio_export import capture_audio_mix
    from ..playback.audio_engine import studio_ffmpeg_path

    request = LyricsRequest(project, points, state_for(project).playback_revision, lines, separate.isChecked(),
                            str(language.currentData() or ""), scene_requested)
    if not _current(page, request):
        return
    mix = capture_audio_mix(project)
    ffmpeg = studio_ffmpeg_path()
    cancel = threading.Event()
    finished = threading.Event()
    received = {}
    page._local_lyrics_busy = True

    def work():
        try:
            received["result"] = _run_job(request, mix, ffmpeg, cancel)
        except Exception as error:
            received["error"] = str(error)[:240] if isinstance(error, ValueError) else type(error).__name__
        finally:
            finished.set()

    progress_text = ("正在判断选区声音…" if request.scene_probe else
                     "正在对齐选区歌词…" if lines else "正在生成歌词草稿…")
    progress = QProgressDialog(tr(progress_text), tr("取消"), 0, 0, page)
    progress.setWindowModality(Qt.WindowModality.NonModal)
    progress.canceled.connect(cancel.set)
    page.destroyed.connect(lambda *_: cancel.set())
    timer = QTimer(progress, interval=100)

    def collect():
        if not finished.is_set():
            return
        timer.stop()
        progress.deleteLater()
        page._local_lyrics_busy = False
        if cancel.is_set():
            if request.scene_probe:
                from ..storage.project_stage_history import record_stage

                record_stage(project.project_id, "song_presence", "cancelled", source="yamnet")
            return
        if not _current(page, request):
            page._show_studio_hint(tr("工程或选区已变化，请重新对齐歌词"))
            return
        try:
            if "error" in received:
                raise ValueError(received["error"])
            if request.scene_probe:
                from ..storage.project_stage_history import record_stage

                value = received["result"]
                possible_song = isinstance(value, dict) and value.get("result") == "possible_song"
                record_stage(project.project_id, "song_presence", "suggestion" if possible_song else "unchanged",
                             source="yamnet")
                show(page, enhanced=request.enhance_voice,
                     scene_hint=tr("这段可能有歌唱" if possible_song else "这段的歌唱证据不足"))
                return
            if not lines:
                from ..storage.project_stage_history import record_stage

                value = received["result"]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("没有可用的歌词草稿")
                record_stage(project.project_id, "lyrics_draft", "suggestion", source="whisper", drafts=1)
                show(page, draft_text=value, enhanced=request.enhance_voice)
                return
            plan = _import_plan(project, request, received["result"])
        except (ValueError, KeyError, TypeError) as error:
            if request.scene_probe:
                from ..storage.project_stage_history import record_stage

                record_stage(project.project_id, "song_presence", "failed", source="yamnet")
            page._show_studio_hint(tr("歌词对齐未完成：{error}", error=str(error)[:180]))
            return
        if _preview(page, plan) and _current(page, request):
            from ..timeline.subtitle_import_command import ImportSubtitlesCommand
            from ..storage.project_stage_history import record_stage

            command = ImportSubtitlesCommand(project, plan, page._changed, page._populate_speakers)
            command.setText(tr("新增歌词轨道"))
            page.undo_stack.push(command)
            record_stage(project.project_id, "alignment", "completed", source="sylla", lyrics_cues=len(plan.cues))

    timer.timeout.connect(collect)
    progress.show()
    timer.start()
    threading.Thread(target=work, daemon=True, name="studio-song-alignment").start()
