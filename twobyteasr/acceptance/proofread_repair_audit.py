"""Opt-in UI audit: real project copy, explicit benchmark proposals, actual SRTs."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture

    result = {"passed": False, "checks": [], "samples": [], "evidence": "source normal-entry Qt click/paint; private Windows desktop"}
    source_root = Path(__file__).resolve().parents[2]
    source_files = ["glossary/glossary_proofread.py", "glossary/proofread_rules.py", "glossary/proofread_decisions.py",
                    "glossary/studio_glossary_service.py", "glossary/terminology.py", "projects/studio_project.py",
                    "projects/studio_runtime_state.py", "studio/gui_thread_handoff.py", "exports/studio_subtitle_export.py",
                    "exports/studio_export_ui.py", "timeline/studio_commands.py"]
    def hashes():
        return {name: hashlib.sha256((source_root / "twobyteasr" / name).read_bytes()).hexdigest() for name in source_files}
    result["source_sha256"] = hashes()

    def save():
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def check(name, value, detail=None):
        result["checks"].append(dict(name=name, passed=bool(value), detail=detail))
        save()
        if not value:
            raise AssertionError(name)

    def pump(seconds=.03):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            QApplication.processEvents()
            time.sleep(.002)

    def wait(predicate, seconds=90):
        until = time.perf_counter() + seconds
        while not predicate() and time.perf_counter() < until:
            pump()
        return predicate()

    def run():
        review = None
        try:
            baseline = os.environ.get("TWOBYTEASR_PROOFREAD_BASELINE")
            if baseline:
                for name in ("timeline.studio_commands", "glossary.glossary_proofread"):
                    full = "twobyteasr." + name
                    path = Path(baseline) / "twobyteasr" / (name.replace(".", "/") + ".py")
                    spec = importlib.util.spec_from_file_location(full, path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[full] = module
                    spec.loader.exec_module(module)
            from ..projects.studio_project import load_project, save_project, SubtitleProject, StudioMedia, StudioCue
            from ..glossary.glossary_proofread import _issue
            from ..diagnostics.build_identity import load_build_identity
            result['build'] = load_build_identity().to_dict()
            if not baseline:
                import importlib, marshal, types
                def normalized(code):
                    return code.replace(co_filename='<source>', co_consts=tuple(
                        normalized(c) if isinstance(c, types.CodeType) else c for c in code.co_consts))
                symbols = {'glossary.glossary_proofread': ['GlossaryProofreadPage._dismiss_group', 'GlossaryProofreadPage._apply_filter', '_SaveThread.run'],
                           'glossary.proofread_rules': ['normalize_occurrence'],
                           'glossary.proofread_decisions': ['IgnoreProofreadRowCommand._apply'],
                           'exports.studio_subtitle_export': ['export_language_layers']}
                result['runtime_symbols'] = []
                for name, paths in symbols.items():
                    module = importlib.import_module('twobyteasr.' + name)
                    raw = (source_root / 'twobyteasr' / (name.replace('.', '/') + '.py'))
                    compiled = compile(raw.read_bytes(), str(raw), 'exec', optimize=1 if getattr(sys, 'frozen', False) else sys.flags.optimize)
                    for path in paths:
                        actual, expected = module, compiled
                        for part in path.split('.'):
                            actual = getattr(actual, part)
                            expected = next(c for c in expected.co_consts if isinstance(c, types.CodeType) and c.co_name == part)
                        match = normalized(actual.__code__) == normalized(expected)
                        result['runtime_symbols'].append(dict(module=name, symbol=path, matches=match,
                            actual_sha256=hashlib.sha256(marshal.dumps(normalized(actual.__code__))).hexdigest()))
                check('runtime Build Truth symbols match shipped sources', all(s['matches'] for s in result['runtime_symbols']))
            project = load_project(out / "work.2byteproj")
            window._show_glossary_proofread(str(out / "work.2byteproj"), project)
            review = window.glossary_proofread_page
            check("normal application shows the copied project", review.isVisible() and len(review._rows) >= 1500)
            check("initial background checks finish", wait(lambda: not review.checks_running(), 150))
            result["actual_initial_counts"] = review.proposal_counts()
            result["initial_status"] = review.status_label.text()
            _capture(window, out / "01-initial.png")
            # Benchmark proposals are explicit test data on real project text.
            # They measure interaction, never name-correction/model quality.
            rows = [r for r in review._rows if len(r["base"]) >= 4][:320]
            for row in review._rows:
                row["issues"] = []
            for row in rows:
                row["issues"] = [_issue("near", (0, 2), row["base"][:2], "验收词", checked=False)]
            review._apply_filter()
            result["benchmark"] = {"cues": len(project.cues), "proposals": len(rows), "proposals_injected": True,
                "full_review_receipt": bool(review._receipt), "project_bytes": (out / "work.2byteproj").stat().st_size}
            paints = []
            original_paint = review.list.paintEvent
            def paint(event):
                original_paint(event)
                paints.append(time.perf_counter())
            review.list.paintEvent = paint

            # Start the production local checker, then perform a burst of edits.
            review._start_stutter(project)
            for index in range(3):
                for action, row in (("adopt", rows[index*3]), ("ignore", rows[index*3+1]), ("edit", rows[index*3+2])):
                    cue_id = row["cue_id"]
                    review.list.ensure_visible(cue_id)
                    pump(.02)
                    review.list.repaint()
                    kind = {"adopt": "check", "ignore": "ignore", "edit": "edit"}[action]
                    boxes = [rect for rect, name, identity, _ in review.list._hit_boxes if name == kind and identity == cue_id]
                    check("click target exists: " + action, bool(boxes))
                    if action == "edit":
                        QTest.mouseClick(review.list, Qt.LeftButton, Qt.NoModifier, boxes[0].center().toPoint())
                        review.list.editor.setText("验收改字" + row["base"])
                    paints.clear()
                    background_before = review.checks_running()
                    started = time.perf_counter()
                    if action == "edit":
                        QTest.keyClick(review.list.editor, Qt.Key_Return)
                    else:
                        QTest.mouseClick(review.list, Qt.LeftButton, Qt.NoModifier, boxes[0].center().toPoint())
                    call_end = time.perf_counter()
                    wait(lambda: bool(paints), 10)
                    sample = dict(action=action, call_ms=(call_end-started)*1000,
                        paint_ms=(paints[0]-started)*1000 if paints else None,
                        background_before=background_before, background_running=review.checks_running())
                    result["samples"].append(sample)
                    save()
            check("all measured actions paint", len(result["samples"]) == 9 and all(r["paint_ms"] is not None for r in result["samples"]))
            check("background checks settle after edits", wait(lambda: not review.checks_running(), 150))
            # Think-time between clicks lets the 700 ms autosave actually run.
            # Report this separately from the burst; it must not hide a new
            # stall caused by sharing Python with serialization.
            for row in rows[24:27]:
                pump(.85)
                review.list.ensure_visible(row["cue_id"])
                pump(.02)
                review.list.repaint()
                boxes = [r for r, action, c, _ in review.list._hit_boxes if action == "check" and c == row["cue_id"]]
                if not boxes:
                    continue
                paints.clear()
                saving = review._save_thread is not None
                profiler = None
                if os.environ.get("TWOBYTEASR_PROOFREAD_PROFILE") == "1":
                    import cProfile
                    profiler = cProfile.Profile()
                    profiler.enable()
                started = time.perf_counter()
                QTest.mouseClick(review.list, Qt.LeftButton, Qt.NoModifier, boxes[0].center().toPoint())
                ended = time.perf_counter()
                if profiler is not None:
                    profiler.disable()
                    import pstats
                    with (out / ("paced-" + str(len(result.get("paced_samples", ()))) + ".profile.txt")).open("w", encoding="utf-8") as stream:
                        pstats.Stats(profiler, stream=stream).sort_stats("cumtime").print_stats(30)
                wait(lambda: bool(paints), 10)
                result.setdefault("paced_samples", []).append(dict(action="adopt", saving_before=saving,
                    call_ms=(ended-started)*1000, paint_ms=(paints[0]-started)*1000 if paints else None))
                save()
            if not baseline:
                row = rows[12]
                row["issues"] = [_issue("term", (0, 2), row["base"][:2], "测试甲", checked=False),
                                 _issue("near", (2, 4), row["base"][2:4], "测试乙", checked=False)]
                unchanged = copy.deepcopy((project.cues, project.generation_metadata.get("translations")))
                review.filter_buttons["suggested"].click()
                review._apply_filter()
                review.list.ensure_visible(row["cue_id"])
                pump(.05)
                review.list.repaint()
                boxes = [r for r, action, c, _ in review.list._hit_boxes if action == "ignore" and c == row["cue_id"]]
                check("one row ignore button for multiple proposals", len(boxes) == 1)
                QTest.mouseClick(review.list, Qt.LeftButton, Qt.NoModifier, boxes[0].center().toPoint())
                pump()
                check("ignored row leaves suggestions immediately", row["cue_id"] not in [review._rows[i]["cue_id"] for i in review.list.visible])
                check("ignoring does not mutate text or translation", (project.cues, project.generation_metadata.get("translations")) == unchanged)
                review.filter_buttons["changed"].click()
                pump()
                check("ignored row joins changed group", row["cue_id"] in [review._rows[i]["cue_id"] for i in review.list.visible])
                review.list.ensure_visible(row["cue_id"])
                pump(.05)
                _capture(window, out / "02-ignored.png")
                review.undo_button.click()
                check("undo restores unresolved proposals", not any(i.get("ignored") for i in row["issues"]))
                review.redo_button.click()
                check("redo restores ignored metadata", all(i.get("ignored") for i in row["issues"]))
                saving = time.perf_counter()
                check("flush save succeeds", review._flush_save())
                result["save_ms"] = (time.perf_counter()-saving)*1000
                reopened = load_project(out / "work.2byteproj")
                check("ignore persists in reopened project", bool(reopened.studio_state.get("glossary_proofread_decisions", {}).get(row["cue_id"])))
                # Dialog path, current manual translation, canonical records
                # without the legacy render cache, then real parser read-back.
                from ..subtitle_rules import subtitle_translation as st
                from ..exports.studio_export_ui import SubtitleExportDialog
                from ..exports.srt_codec import parse_srt
                translated = SubtitleProject(StudioMedia("", duration_ms=6000), cues=[
                    StudioCue("stable-90", 1000, 2000, "原文一"), StudioCue("stable-3", 3000, 4500, "原文二")],
                    generation_metadata={"language": {"code": "zh"}})
                translated.validate()
                translated.generation_metadata[st.RECORDS_KEY] = st._empty_container("ja")
                st.set_manual(translated, "stable-90", "日本語の訳", target="ja")
                st.set_manual(translated, "stable-3", "今変更した訳", target="ja")
                translated.generation_metadata.pop("translations", None)
                translated_path = out / "中文 空格" / "字幕.2byteproj"
                translated_path.parent.mkdir()
                save_project(translated, translated_path)
                dialog = SubtitleExportDialog(translated, translated_path, window, export_on_accept=True, base_name="字幕")
                dialog.show()
                pump(.1)
                check("record-only translation controls visible", dialog.language_row.isVisible())
                QTest.mouseClick(dialog.export_button, Qt.LeftButton)
                pump(.1)
                artifacts = dialog.artifacts
                check("export dialog produces files", bool(artifacts))
                for artifact in artifacts:
                    if artifact.format != "srt":
                        continue
                    content = artifact.path.read_text(encoding="utf-8")
                    parsed, errors = parse_srt(content)
                    check("SRT parser accepts " + artifact.path.name, bool(parsed) and not errors)
                    if getattr(artifact, "layer", "") == "translation":
                        check("actual translated SRT contains latest Japanese", [r.text for r in parsed] == ["日本語の訳", "今変更した訳"])
                        result["translation_srt"] = str(artifact.path)
                check("translated artifact verified", bool(result.get("translation_srt")))
                _capture(dialog, out / "03-export.png")
                dialog.close()
                from ..exports.studio_subtitle_export import export_language_layers
                from ..caption_style.bilingual_layout import translation_for_cue
                from ..subtitle_rules.punctuation_style import style_translation, project_mode, math_enabled
                def real_export(p, label, marker=None):
                    receipt = export_language_layers(p, out / 'real-srt' / label, '字幕')
                    views = st.translation_view(p)
                    expected = []
                    for cue in sorted(p.visible_cues(), key=lambda c:(c.start_ms,c.end_ms,c.id)):
                        info = translation_for_cue(views, cue.id) or {}
                        if str(info.get('text') or '').strip():
                            expected.append((cue.start_ms, cue.end_ms, style_translation(info['text'],project_mode(p),math=math_enabled(p))))
                    files = []
                    for artifact in receipt.artifacts:
                        rows, errors = parse_srt(artifact.path.read_text(encoding='utf-8'))
                        check('real SRT parses: '+label+'/'+artifact.layer, bool(rows) and not errors)
                        if artifact.layer == 'translation':
                            check('real translation text and time match: '+label, [(r.start_ms,r.end_ms,r.text) for r in rows] == expected)
                            if marker:check('latest manual text survives: '+label, marker in [r.text for r in rows])
                        files.append(dict(layer=artifact.layer,path=str(artifact.path),count=len(rows)))
                    result.setdefault('real_srt',[]).append(dict(case=label,files=files,missing=list(receipt.missing_translation_ids)))
                complete_path = os.environ.get('TWOBYTEASR_QA_TRANSLATED_PROJECT')
                if complete_path:
                    p = load_project(complete_path)
                    real_export(p,'complete')
                    marker = '验收副本最新译文'
                    st.set_manual(p,p.cues[0].id,marker,target=st.container_target(p))
                    real_export(p,'latest',marker)
                    saved = out/'latest-real-translation.2byteproj'
                    save_project(p,saved,compact=True)
                    real_export(load_project(saved),'reopened',marker)
                partial_path = os.environ.get('TWOBYTEASR_QA_PARTIAL_PROJECT')
                if partial_path:real_export(load_project(partial_path),'partial')
            result["passed"] = all(r["passed"] for r in result["checks"])
        except BaseException:
            result["error"] = traceback.format_exc()
        finally:
            if review is not None:
                review.shutdown()
            result["source_unchanged_during_audit"] = result["source_sha256"] == hashes()
            result["passed"] = result["passed"] and result["source_unchanged_during_audit"]
            save()
            window.close()
            result["gui_shutdown"] = True
            save()
            QApplication.quit()
    QTimer.singleShot(1800, run)
