"""Offline grouping -> actual Studio editing -> save/reopen -> production exports.

Only runs in explicit isolated acceptance mode. The IME events are synthetic Qt
events, not a claim about a particular installed Chinese/Japanese IME.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

from .studio_acceptance_audit import require


def run(output, *, window):
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..test_isolation import install, install_pytest_network_guard
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import project_from_runtime_cues, save_project, load_project
    from ..projects.subtitle_consistency import validate_project, validate_export_view
    from ..exports.studio_subtitle_export import (
        SubtitleExportOptions, export_subtitle_artifacts, verify_subtitle_artifact)
    from ..exports.srt_codec import parse_srt
    from ..subtitle_rules.grouping_contract import (
        GroupingContractError, parse_grouping_response, validate_grouping_result)
    from .grouping_contract_audit import run_offline
    from . import blank_project_audit
    import subtitle_core as core

    install()
    install_pytest_network_guard()
    output = Path(output).resolve()
    require(os.environ.get("TWOBYTEASR_ACCEPTANCE_SCENARIO") == "editor-workflow",
            "editor-workflow requires its explicit isolated scenario")
    require(Path(os.environ["TWOBYTEASR_ACCEPTANCE_DIR"]).resolve() == output,
            "acceptance output differs from isolated directory")
    require(os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER") == "1",
            "workflow acceptance must run with no player")
    page = window.studio_page
    window.resize(1440, 900)
    window.show()
    result = {
        "passed": False, "checks": [], "cases": [], "artifacts": [],
        "frozen": bool(getattr(sys, "frozen", False)), "pid": os.getpid(),
        "executable": sys.executable, "identity": load_build_identity().to_dict(),
        "entry": "normal-window", "platform": QApplication.platformName(),
        "scope": "synthetic offline response; actual Studio card, save/reopen, production SRT/JSON",
        "ime_scope": "Qt preedit/commit events; installed native IME hardware is not covered",
        "export_scope": "production export service and readback; file-selection dialog is not exercised",
    }
    network_attempts = []

    def deny_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            network_attempts.append(event)
            raise RuntimeError("Network prohibited in editor workflow acceptance")

    # Process-local permanent hook. The acceptance process closes after this run.
    sys.addaudithook(deny_network)

    def receipt():
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def check(name, condition, detail=None):
        result["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
        receipt()
        require(condition, name + (": " + str(detail) if detail is not None else ""))

    def wait(predicate, label, seconds=25):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError(label)
            QTest.qWait(20)

    def capture(name):
        target = output / (name + ".png")
        blank_project_audit._capture(window, target)
        check("capture_" + name, target.is_file() and target.stat().st_size > 0)
        return str(target)

    def open_project(path):
        previous = page.project
        window.open_studio_project(str(path), mode="edit", source="editor_workflow_audit")
        wait(lambda: page.project is not None and page.project is not previous
             and page.project_path is not None
             and Path(page.project_path).resolve() == path.resolve()
             and getattr(page, "_readiness", None) is not None and page._readiness.ready,
             "normal Studio open/reload did not complete")
        check("no_player_" + path.stem, page.video.controller is None)

    def rejected(name, operation):
        failed_safely = False
        try:
            operation()
        except GroupingContractError:
            failed_safely = True
        check(name, failed_safely)

    try:
        replay = run_offline()
        result["checks"].extend(replay["checks"])
        check("offline_replay_all_guards", replay["passed"])
        (output / "grouping-replay.json").write_text(
            json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        source_rows = core.deserialize_segments(replay["source_segments"])
        runtime_cues = core.deserialize_cues(replay["runtime_cues"])
        source_text = "".join(row.text for row in source_rows)
        rejected("reject_truncated_cue", lambda: validate_grouping_result(source_rows, [
            core.SubtitleCue(1, 0, 2, source_text[:-1], speaker="S01")]))
        rejected("reject_duplicate_cue", lambda: validate_grouping_result(source_rows, runtime_cues * 2))
        rejected("reject_omitted_cue", lambda: validate_grouping_result(source_rows, []))
        rejected("reject_unknown_source_id_payload", lambda: parse_grouping_response(
            '{"boundaries":[8],"source_ids":[999]}', source_text))
        interrupted = [
            core.SpeechSegment(1, 0, 1, "甲", .9, [], speaker="S01"),
            core.SpeechSegment(2, 1, 2, "乙", .9, [], speaker="S02"),
        ]
        rejected("reject_cross_speaker_merge", lambda: validate_grouping_result(interrupted, [
            core.SubtitleCue(1, 0, 2, "甲乙", speaker="S01")]))

        evidence = {}
        for segment in replay["source_segments"]:
            evidence["segment:" + str(segment["segment_id"])] = {
                "text": segment["text"], "speaker_id": segment["speaker"],
                "start_ms": round(segment["start"] * 1000),
                "end_ms": round(segment["end"] * 1000),
                "words": [{"text": word["text"], "start_ms": round(word["start"] * 1000),
                           "end_ms": round(word["end"] * 1000)}
                          for word in segment["words"]],
            }
        project = project_from_runtime_cues(
            output / "unused-synthetic-media.mp4", runtime_cues,
            asr_evidence=evidence, initialize_layout=False,
            media_identity={"duration_ms": 2000, "width": 640, "height": 360,
                            "has_video": False, "has_audio": False})
        # The acceptance has a sentence timeline but intentionally no media.
        project.media.path = ""
        project.render_settings["_cue_domain"] = "timeline"
        for cue in project.cues:
            cue.evidence_refs = [key for key, row in evidence.items()
                                 if row["start_ms"] < cue.end_ms and row["end_ms"] > cue.start_ms]
        check("one_real_fallback_cue", len(project.cues) == 1)
        cue = project.cues[0]
        cue_id = cue.id
        original_identity = (cue.id, cue.start_ms, cue.end_ms, cue.speaker_id)
        # A synthetic *valid at import* direct word receipt makes the stale-data
        # case reproducible. Editing must never treat it as updated alignment.
        aligned_words = []
        cursor = 0
        for word in evidence["segment:1"]["words"]:
            lo = cue.text.index(word["text"], cursor)
            hi = lo + len(word["text"])
            aligned_words.append(dict(word, char_start=lo, char_end=hi,
                                      evidence_ref="segment:1"))
            cursor = hi
        alignment_ref = "cue-align:" + cue_id
        project.asr_evidence[alignment_ref] = {
            "cue_alignment": {}, "text": cue.text, "words": aligned_words}
        source_evidence = copy.deepcopy(project.asr_evidence)
        check("fallback_project_contract", validate_project(project).ok)
        initial = save_project(project, output / "fallback-import.2byteproj")
        initial_hash = hashlib.sha256(initial.read_bytes()).hexdigest()
        open_project(initial)
        check("import_exact_source", page.project.cues[0].text == source_text)
        check("initial_alignment_not_stale",
              not any("stale" in issue.code for issue in validate_project(page.project).warnings))
        capture("fallback-open")

        cases = [
            ("chinese", "确认字幕，保留中文人工编辑。", "que ren zi mu"),
            ("japanese", "日本語の字幕を編集して保存します。", "にほんご"),
            ("multiline", "中文第一行\n日本語の第二行\n123\n", "zhong wen"),
        ]
        for name, target, preedit in cases:
            page.select_cue(cue_id)
            page._begin_canvas_inline_edit()
            wait(lambda: page._canvas_editor is page.subtitle_edit_input
                 and page.subtitle_edit_input.isVisible(), "edit card not visible")
            editor = page.subtitle_edit_input
            QTest.qWait(180)  # Let the queued activation/focus reset settle before preedit.
            wait(lambda: QApplication.focusWidget() is editor, "edit card did not receive focus", 5)
            before_text = page._cue_lookup[cue_id].text
            editor.selectAll()
            QCoreApplication.sendEvent(editor, QInputMethodEvent(preedit, []))
            QTest.keyClick(editor, Qt.Key.Key_Return)
            check(name + "_ime_candidate_does_not_commit",
                  page._canvas_editor is editor and page._cue_lookup[cue_id].text == before_text,
                  {"editor_active": page._canvas_editor is editor,
                   "preediting": getattr(editor, "_preediting", None),
                   "model_text": page._cue_lookup[cue_id].text, "before": before_text})
            for index, line in enumerate(target.split("\n")):
                if index:
                    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
                commit = QInputMethodEvent()
                commit.setCommitString(line)
                QCoreApplication.sendEvent(editor, commit)
            check(name + "_draft_exact", editor.toPlainText() == target, editor.toPlainText())
            check(name + "_draft_not_committed", page._cue_lookup[cue_id].text == before_text)
            QTest.qWait(180)
            if name == "multiline":
                capture("multiline-editing")
            QTest.keyClick(editor, Qt.Key.Key_Return)
            wait(lambda: page._canvas_editor is None, "Enter did not commit")
            check(name + "_commit_exact", page._cue_lookup[cue_id].text == target)
            page.undo_stack.undo()
            check(name + "_undo_exact", page._cue_lookup[cue_id].text == before_text)
            page.undo_stack.redo()
            check(name + "_redo_exact", page._cue_lookup[cue_id].text == target)

            saved = output / (name + "-saved.2byteproj")
            page.project_path = saved
            page.save()  # Real manual-save transaction, including state capture.
            check(name + "_save_completed", saved.is_file() and page.undo_stack.isClean())
            disk = load_project(saved)
            current = disk.cues[0]
            check(name + "_disk_text", current.text == target)
            check(name + "_disk_identity", (current.id, current.start_ms, current.end_ms,
                  current.speaker_id) == original_identity)
            check(name + "_source_evidence_unchanged", disk.asr_evidence == source_evidence)
            open_project(saved)
            current = page.project.cues[0]
            check(name + "_reopened_text", current.text == target)
            check(name + "_reopened_identity", (current.id, current.start_ms, current.end_ms,
                  current.speaker_id) == original_identity)
            consistency = validate_export_view(page.project, page.project.cues, stage="workflow")
            warnings = [issue.to_dict() for issue in consistency.warnings]
            check(name + "_manual_edit_not_grouping_error", consistency.ok)
            check(name + "_stale_words_explicit",
                  any(item["code"] in {"stale_word_alignment", "source_word_alignment_stale"}
                      and item["cue_id"] == cue_id for item in warnings), warnings)
            check(name + "_word_warning_visible", "字级" in page.save_state.text(), page.save_state.text())

            artifacts = export_subtitle_artifacts(
                page.project, output / ("exports-" + name), name,
                SubtitleExportOptions(frozenset({"srt", "json"}), "per_speaker"))
            check(name + "_both_real_exports", {artifact.format for artifact in artifacts} == {"srt", "json"})
            for artifact in artifacts:
                verified = verify_subtitle_artifact(artifact, page.project)
                check(name + "_" + artifact.format + "_production_readback", verified.valid,
                      verified.first_mismatch)
                check(name + "_" + artifact.format + "_speaker_scope",
                      artifact.speaker_id == original_identity[3] and artifact.cue_count == 1)
                result["artifacts"].append({
                    "case": name, "format": artifact.format, "path": str(artifact.path),
                    "sha256": hashlib.sha256(artifact.path.read_bytes()).hexdigest(),
                    "speaker_id": artifact.speaker_id, "readback_valid": verified.valid,
                })
                if artifact.format == "srt":
                    rows, errors = parse_srt(artifact.path.read_text(encoding="utf-8"))
                    check(name + "_srt_exact", not errors and
                          [(row.start_ms, row.end_ms, row.text) for row in rows]
                          == [(original_identity[1], original_identity[2], target)], errors)
                else:
                    data = json.loads(artifact.path.read_text(encoding="utf-8"))["cues"]
                    check(name + "_json_exact", len(data) == 1 and
                          (data[0]["id"], data[0]["start_ms"], data[0]["end_ms"], data[0]["speaker_id"])
                          == original_identity and data[0]["text"] == data[0]["original_text"] == target)
                    check(name + "_json_stale_words_unavailable",
                          not data[0]["word_timing"]["pieces"]
                          and "stale" in data[0]["word_timing"]["basis"],
                          data[0]["word_timing"])
            result["cases"].append({"name": name, "text": target, "project": str(saved),
                                    "source_identity": original_identity, "warnings": warnings})
            receipt()
        capture("saved-reopened")
        check("original_import_file_untouched",
              hashlib.sha256(initial.read_bytes()).hexdigest() == initial_hash)
        check("no_network_attempts", not network_attempts, network_attempts)
        check("no_provider_calls", blank_project_audit._provider_calls == 0)
        check("no_external_connections", not blank_project_audit._blocked_external_connections)
        result["passed"] = all(item["passed"] for item in result["checks"])
    except Exception:
        result["error"] = traceback.format_exc()
        try:
            capture("failure")
        except Exception:
            result["capture_error"] = traceback.format_exc()
    finally:
        page.undo_stack.setClean()
        result["shutdown"] = not bool(
            getattr(page, "_close_thread", None) and page._close_thread.is_alive())
        receipt()
    return 0 if result["passed"] and result["shutdown"] else 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    output = Path(output)

    def execute():
        try:
            code = run(output, window=window)
        except Exception:
            (output / "result.json").write_text(json.dumps(
                {"passed": False, "error": traceback.format_exc()}, ensure_ascii=False), encoding="utf-8")
            code = 1
        window.result_exit_code = code

        def stopped():
            path = output / "result.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["gui_shutdown"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()

    QTimer.singleShot(100, execute)
