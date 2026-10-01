"""Construct and capture the scoped P22.6/P22.7/P22.3/Speaker acceptance flows."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
DATA_ROOT = ROOT / "tmp" / "p22-acceptance"
DATA = DATA_ROOT / f"run-{os.getpid()}"
LOCAL = DATA / "local"
os.environ["LOCALAPPDATA"] = str(LOCAL)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.glossary_learning import GlossaryLearningStore  # noqa: E402
from twobyteasr.project_profiles import ProjectProfileStore  # noqa: E402
from twobyteasr.studio_commands import MergeSpeakerCommand, SetSpeakerCommand  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio_ui import SpeakerManagerDialog  # noqa: E402
from twobyteasr.teach_hints import TeachHintStore  # noqa: E402


def pump(app, rounds=3):
    for _ in range(rounds):
        app.processEvents()


def timed(action, app, cycles=1):
    values = []
    for index in range(cycles):
        started = time.perf_counter()
        action(index)
        pump(app, 1)
        values.append((time.perf_counter() - started) * 1000)
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))], 3),
        "max_ms": round(max(values), 3),
    }


def capture(widget, path: Path, app):
    path.parent.mkdir(parents=True, exist_ok=True)
    widget.repaint()
    pump(app)
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path)):
        raise RuntimeError(f"could not save screenshot: {path}")


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    screenshots = ROOT / "screenshots" / "p22"
    screenshots.mkdir(parents=True, exist_ok=True)
    report = {"acceptance": {}, "performance": {}, "screenshots": {}}

    # A: three independent manual corrections, explicit acceptance into 原神.
    learning = GlossaryLearningStore(DATA / "glossary-learning.json")
    for index in range(3):
        learning.record_manual_edit(
            f"第{index + 1}次遇到那维来特",
            f"第{index + 1}次遇到那维莱特",
            project=f"原神-{index + 1}.2byteproj",
            speaker="S01",
            context="主播提到那维莱特",
        )
    suggestion = learning.pending()[0]
    accepted = learning.accept([suggestion["id"]], "原神", add_mapping=subtitle_core.add_learned_mapping)
    saved_mapping = next(
        item for item in subtitle_core.learned_mappings_for_game("原神")
        if item.get("from") == "那维来特" and item.get("to") == "那维莱特"
    )
    report["acceptance"]["A"] = {
        "occurrence_count": suggestion["occurrence_count"],
        "pending_before_accept": suggestion["status"] == "pending",
        "accepted": accepted == 1,
        "destination_glossary": "原神",
        "mapping_origin": saved_mapping.get("origin"),
    }

    # Keep another pending suggestion for the real term-library screenshot.
    ui_learning = GlossaryLearningStore()
    for index in range(3):
        ui_learning.record_manual_edit(
            f"片段{index}中的枫丹廷",
            f"片段{index}中的枫丹庭",
            project="原神验收.2byteproj",
            speaker="S01",
            context="正在前往枫丹庭",
        )
    subtitle_core.ensure_learned_content("原神")

    # B: create, restart the store, then compare all reusable references.
    profile_path = DATA / "profiles.json"
    profiles = ProjectProfileStore(profile_path)
    created = profiles.create(
        "原神",
        recognition_plan="quality",
        primary_asr="moss",
        timestamp_model="local",
        evidence_model="qwen_local",
        llm_enabled=True,
        llm_config_ref="deepseek-default",
        glossary_ids=["原神"],
        language="zh",
        subtitle_mode="bilingual",
        subtitle_style_preset="game-default",
        render_preset="1080p-default",
        export_format="ass",
        review_threshold=0.72,
        review_strategy="risk_first",
    )
    restarted = ProjectProfileStore(profile_path).get(created.id)
    report["acceptance"]["B"] = {
        "profile": restarted.name,
        "survived_restart": restarted is not None,
        "references": {
            "recognition_plan": restarted.recognition_plan,
            "models": [restarted.primary_asr, restarted.timestamp_model, restarted.evidence_model],
            "glossaries": restarted.glossary_ids,
            "style": restarted.subtitle_style_preset,
            "render": restarted.render_preset,
            "export": restarted.export_format,
            "review": [restarted.review_strategy, restarted.review_threshold],
        },
    }

    # D: first show -> marked -> hidden after restart -> reset -> visible again.
    teach_path = DATA / "teach-hints.json"
    teach = TeachHintStore(teach_path)
    first_show = teach.should_show("studio")
    teach.mark_shown("studio")
    second_show = TeachHintStore(teach_path).should_show("studio")
    teach.reset()
    reset_show = TeachHintStore(teach_path).should_show("studio")
    report["acceptance"]["D"] = {
        "first_show": first_show,
        "second_show": second_show,
        "after_reset": reset_show,
    }

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    cold_started = time.perf_counter()
    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
    report["performance"]["cold_start"] = {
        "ms": round((time.perf_counter() - cold_started) * 1000, 3),
        "guard_ms": 3000,
    }
    window.resize(1600, 920)
    window.show()
    pump(app)
    window.profile_store = ProjectProfileStore(profile_path)
    window.current_project_profile = restarted
    window._refresh_project_profile_combo(restarted.id)
    profile_shot = screenshots / "p22-profile.png"
    capture(window, profile_shot, app)
    report["screenshots"]["profile"] = str(profile_shot)

    page_switches = [window.settings_scroll, window.workshop_page, window.history_page, window.term_library_page]
    report["performance"]["page_switch"] = timed(
        lambda index: window.pages.setCurrentWidget(page_switches[index % len(page_switches)]), app, 16
    )

    window.history_page.report_root = DATA / "empty-reports"
    window.history_page.refresh()
    window.pages.setCurrentWidget(window.history_page)
    pump(app)
    history_shot = screenshots / "p22-history-empty.png"
    capture(window, history_shot, app)
    report["screenshots"]["history_empty"] = str(history_shot)

    window.term_library_page.prepare_for_show()
    window.pages.setCurrentWidget(window.term_library_page)
    library = window.term_library_page.library
    for index in range(library.game_list.count()):
        item = library.game_list.item(index)
        if library._game_identity(item.data(Qt.ItemDataRole.UserRole)) == library._game_identity("原神"):
            library.game_list.setCurrentItem(item)
            break
    library.refresh_learning_suggestions()
    pump(app)
    term_shot = screenshots / "p22-glossary-learning.png"
    capture(window, term_shot, app)
    report["screenshots"]["glossary_learning"] = str(term_shot)

    window.pages.setCurrentWidget(window.studio_page)
    window.app_header.hide()
    window.studio_page._refresh_studio_empty_state()
    window.studio_page._show_teach_hint("studio")
    pump(app)
    empty_shot = screenshots / "p22-studio-empty-teach.png"
    capture(window, empty_shot, app)
    report["screenshots"]["studio_empty_teach"] = str(empty_shot)
    report["acceptance"]["C"] = {
        "studio_empty_visible": window.studio_page.studio_empty.isVisible(),
        "term_empty_copy": library.listing_empty_title.text(),
        "history_empty_visible": not window.history_page.records and not window.history_page.empty.isHidden(),
        "recent_project_copy": window.studio_page.recent_empty_label.text(),
    }

    # E: real Studio page, command callbacks, save/reload, then Undo.
    project = SubtitleProject(
        media=StudioMedia(path=str(DATA / "speaker-demo.mp4"), duration_ms=30_000),
        speakers=[
            StudioSpeaker("S01", "S01", "default", "#477f59"),
            StudioSpeaker("S03", "S03", "default", "#9a6f55"),
        ],
        cues=[
            StudioCue("a", 0, 1_300, "第一句", speaker_id="S01"),
            StudioCue("b", 1_500, 3_200, "第二句", speaker_id="S03"),
            StudioCue("c", 3_500, 5_500, "第三句", speaker_id="S01"),
        ],
    )
    project_path = save_project(project, DATA / "speaker-demo.2byteproj")
    studio = window.studio_page
    studio.video.load = lambda *_args, **_kwargs: None
    studio._generate_waveform = lambda *_args, **_kwargs: None
    report["performance"]["studio_open"] = timed(lambda _index: studio.open_project(project_path), app, 3)
    studio.undo_stack.push(SetSpeakerCommand(
        studio.project, "S01", {"name": "主播"}, changed=studio._speaker_structure_changed
    ))
    studio.undo_stack.push(MergeSpeakerCommand(
        studio.project, "S03", "S01", changed=studio._speaker_structure_changed
    ))
    studio.save()
    reloaded = load_project(project_path)
    merged_state = {
        "timeline": studio.timeline.speaker_ids(),
        "list": [studio.cue_model.data(studio.cue_model.index(row, 2)) for row in range(studio.cue_model.rowCount())],
        "saved_cue_speakers": [cue.speaker_id for cue in reloaded.cues],
        "saved_speakers": [speaker.id for speaker in reloaded.speakers],
    }
    manager = SpeakerManagerDialog(studio)
    manager.show()
    pump(app)
    speaker_shot = screenshots / "p22-speaker-manager.png"
    capture(manager, speaker_shot, app)
    report["screenshots"]["speaker_manager"] = str(speaker_shot)
    manager.close()
    studio.undo_stack.undo()
    report["acceptance"]["E"] = {
        "merged": merged_state,
        "undo_cue_speakers": [cue.speaker_id for cue in studio.project.cues],
        "undo_speakers": [speaker.id for speaker in studio.project.speakers],
        "undo_timeline": studio.timeline.speaker_ids(),
    }
    cue_ids = [cue.id for cue in studio.project.cues]
    report["performance"]["cue_select"] = timed(
        lambda index: studio.select_cue(cue_ids[index % len(cue_ids)]), app, 40
    )
    report["performance"]["timeline_playback"] = timed(
        lambda index: (
            studio.timeline.set_playhead(index * 250),
            studio.timeline.reveal_playhead(index * 250),
        ),
        app,
        60,
    )
    guards = {
        "cold_start": report["performance"]["cold_start"]["ms"] < 3000,
        "page_switch": report["performance"]["page_switch"]["p95_ms"] < 100,
        "studio_open": report["performance"]["studio_open"]["p95_ms"] < 500,
        "cue_select": report["performance"]["cue_select"]["p95_ms"] < 20,
        "timeline_playback": report["performance"]["timeline_playback"]["p95_ms"] < 20,
    }
    report["performance"]["guards"] = guards
    report["performance"]["obvious_regression"] = not all(guards.values())
    report_path = DATA_ROOT / "acceptance-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    studio.close_page()
    window.close()
    app.quit()
    return 0 if all(guards.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
