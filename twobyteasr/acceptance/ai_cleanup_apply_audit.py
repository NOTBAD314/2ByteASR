"""Fixed provider replay through the real cleanup dialog on an isolated project."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project, save_project
    from ..projects.studio_runtime_state import state_for
    from ..studio.ai_cleanup_dialog import AiCleanupDialog
    from ..studio.studio_text_tools import parse_cleanup_payload
    from ..projects.link_cleanup_validation import validate_cleanup_response
    from ..studio import link_caption_cleanup
    from ..app import api_key_explainer
    from .blank_project_audit import _capture

    output = Path(output)
    config = json.loads((output / "config.json").read_text("utf-8"))
    api_key_explainer.ask_for_key_if_missing = lambda *a, **k: False

    def fingerprint(project):
        from ..subtitle_rules.subtitle_translation import snapshot
        payload = ([asdict(c) for c in project.cues],
                   project.studio_state.get("caption_timeline", {}), snapshot(project))
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def fixed_result(project, ids, options, settings=None, **kwargs):
        cue = next(c for c in project.cues if c.id in set(ids) and c.text.strip())
        payload = {"changes": [dict(cue_id=cue.id, original=cue.text,
                                    replacement=cue.text + ".", reason="标点", confidence=.99)]}
        return parse_cleanup_payload(validate_cleanup_response(payload, project.cues), project)

    link_caption_cleanup.request_text_cleanup = fixed_result

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=False, checks=[], trials=[], pid=os.getpid(),
                               frozen=bool(getattr(sys, "frozen", False)), executable=sys.executable,
                               identity=load_build_identity().to_dict(),
                               scope="fixed provider result; actual dialog buttons; isolated project copy",
                               native_crash_reproduced=False)
            self.dialog = None
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic() + 120
            self.timer = QTimer(self)
            self.timer.setInterval(40)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def write(self):
            (output / "ai-cleanup.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf-8")

        def check(self, name, value, detail=None):
            self.result["checks"].append(dict(name=name, passed=bool(value), detail=detail))
            self.write()
            if not value:
                raise AssertionError(name)

        def tick(self):
            try:
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError("AI cleanup acceptance timed out")
                        return
                elif now < self.waiting:
                    return
                value = next(self.steps)
                self.waiting = value if callable(value) else now + float(value)
                self.deadline = now + 120
            except StopIteration:
                self.result["passed"] = True
                self.finish()
            except Exception:
                self.result["error"] = traceback.format_exc()
                try:
                    from ..studio.studio_readiness import player_wait_snapshot
                    from .caption_layout_audit import scene_sample_receipt
                    page = window.built_page('studio')
                    modal = QApplication.activeModalWidget()
                    self.result['failure_context'] = dict(
                        modal_class=type(modal).__name__ if modal is not None else None,
                        modal_title=modal.windowTitle() if modal is not None else None,
                        project_path=str(page.project_path) if page is not None else None,
                        playhead_ms=page.timeline.playhead_ms if page is not None else None,
                        player=player_wait_snapshot(page) if page is not None else None,
                        scene=scene_sample_receipt(page) if page is not None else None)
                except Exception as diagnostic_error:
                    self.result['failure_context_error'] = repr(diagnostic_error)
                self.finish()

        def run(self):
            window.open_studio_project(str(output / "entry.2byteproj"))
            yield lambda: (window.built_page("studio") is not None
                           and window.studio_page.project is not None
                           and window.studio_page._project_view_state == "open")
            page = window.studio_page
            window.resize(1440, 900)
            yield .8
            self.check("project has the expected subtitle count", len(page.project.cues) == config["cue_count"])
            self.check("original-language display", not page.project.studio_state.get("bilingual_mode"))
            self.result["fixture_sha256"] = config["sha256"]
            initial = fingerprint(page.project)
            self.result["initial_fingerprint"] = initial
            runtime = state_for(page.project)
            for trial in range(config.get("repeat", 3)):
                playing = trial % 2 == 1
                page.video.set_paused(True)
                page._seek(min(380., max(0., config.get("duration_ms", 0) / 2000.)))
                yield .5
                if playing:
                    page._toggle_playback()
                    start = page.timeline.playhead_ms
                    yield lambda: page.timeline.playhead_ms > start + 100
                self.dialog = AiCleanupDialog(page, page)
                self.dialog.show()
                yield .2
                QTest.mouseClick(self.dialog.ai_run_button, Qt.LeftButton)
                yield lambda: not self.dialog._cleanup_running
                # The mailbox just updated the list in this timer turn. Let the
                # normal Qt paint run before taking native window pixels.
                yield .2
                self.check(f"trial {trial}: fixed AI result reached preview", len(self.dialog._preview_hits) == 1)
                splices = len(self.dialog._local_splices)
                if config.get("expect_local"):
                    self.check(f"trial {trial}: local rebreak is present", splices > 0)
                self.check(f"trial {trial}: preview has not edited the project", fingerprint(page.project) == initial)
                if trial == 0:
                    _capture(self.dialog, output / "cleanup-preview.png")
                before_revision = runtime.revision
                before_stack = page.undo_stack.count()
                started = time.perf_counter()
                QTest.mouseClick(self.dialog.all_button, Qt.LeftButton)
                elapsed = (time.perf_counter() - started) * 1000
                committed_revision = runtime.revision
                QTest.mouseClick(self.dialog.all_button, Qt.LeftButton)
                self.check(f"trial {trial}: exactly one published edit", committed_revision == before_revision + 1,
                           dict(before=before_revision, after=committed_revision))
                self.check(f"trial {trial}: exactly one undo entry", page.undo_stack.count() == before_stack + 1)
                self.check(f"trial {trial}: cleared consumed results", self.dialog.preview.count() == 0)
                edited = fingerprint(page.project)
                self.check(f"trial {trial}: edit changed content", edited != initial)
                self.result["trials"].append(dict(trial=trial, playing=playing, apply_ms=elapsed,
                                                   ai_changes=1, local_changes=splices,
                                                   revision_delta=committed_revision - before_revision,
                                                   cues_after=len(page.project.cues)))
                yield .3
                page.video.set_paused(True)
                self.dialog.reject()
                self.dialog = None
                if trial == 0:
                    _capture(window, output / "cleanup-applied.png")
                page.undo_stack.undo()
                self.check(f"trial {trial}: one undo restores all content", fingerprint(page.project) == initial)
                page.undo_stack.redo()
                self.check(f"trial {trial}: redo is identical", fingerprint(page.project) == edited)
                saved = save_project(page.project, output / f"applied-{trial}.2byteproj")
                self.check(f"trial {trial}: saved result reopens unchanged", fingerprint(load_project(saved)) == edited)
                page.undo_stack.undo()
                page.undo_stack.clear()
                yield .3

            # Translation is the existing flow, with exactly this range and the
            # chosen language; opening it must not send a request or replace text.
            self.dialog = AiCleanupDialog(page, page)
            self.dialog.show()
            self.dialog.translation_target.setCurrentIndex(self.dialog.translation_target.findData("zh-Hant"))
            QTest.mouseClick(self.dialog.translation_button, Qt.LeftButton)
            yield lambda: getattr(page, "_translation_dialog", None) is not None
            translation = page._translation_dialog
            self.check("translation opens with chosen target and complete range",
                       translation._target() == "zh-Hant" and len(translation._scope_ids()) == len(page.project.cues))
            self.check("translation navigation preserves original", fingerprint(page.project) == initial)
            _capture(translation, output / "translation-entry.png")
            from types import SimpleNamespace
            from ..caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
            from ..providers import ai_providers, llm_config
            from ..studio import studio_translation_dialog
            from ..subtitle_rules.subtitle_translation import snapshot as translation_snapshot
            from ..caption_style.bilingual_layout import settings_from_state
            class FixedTranslationProvider:
                provider_id, model = "fixed-local-replay", "fixed-translation"
                calls = 0
                def structured_complete(self, messages, schema=None, **kwargs):
                    self.calls += 1
                    payload = json.loads(messages[-1]["content"])
                    return {"items": [dict(id=cue_id, translation="固定回放譯文")
                                      for cue_id in payload["output_ids"]]}
            provider = FixedTranslationProvider()
            ai_providers.provider_for_stage = lambda *a, **k: provider
            llm_config.text_ai_key_missing = lambda *a, **k: False
            GLOBAL_PROVIDER_REGISTRY.selection = lambda *a, **k: SimpleNamespace(
                service="fixed-local-replay", provider=provider.provider_id, model=provider.model,
                transport="fixture", credential_ready=True, credential_source="fixture")
            studio_translation_dialog.load_cache = lambda: {}
            studio_translation_dialog.save_cache = lambda _: None
            translation._provider_ready = translation._describe_service()
            source_cues = [asdict(c) for c in page.project.cues]
            translation_before = translation_snapshot(page.project)
            translation_revision = runtime.revision
            QTest.mouseClick(translation.start_button, Qt.LeftButton)
            yield lambda: translation._thread is None
            self.check("fixed translation provider was called", provider.calls > 0)
            self.check("all requested translations applied", len(page.project.generation_metadata.get("translations", {})) == len(source_cues))
            self.check("translation preserves original text timing and speakers", [asdict(c) for c in page.project.cues] == source_cues)
            self.check("translation plus display is one history entry", page.undo_stack.count() == 1
                       and runtime.revision == translation_revision + 1)
            self.check("translation enables bilingual display", settings_from_state(page.project.studio_state).mode == "bilingual")
            translated = translation_snapshot(page.project)
            yield .3
            _capture(translation, output / "translation-completed.png")
            translation.close()
            self.dialog = None
            yield .2
            _capture(window, output / "translation-applied.png")
            page.undo_stack.undo()
            self.check("one translation undo restores records and original display",
                       translation_snapshot(page.project) == translation_before
                       and settings_from_state(page.project.studio_state).mode == "original")
            page.undo_stack.redo()
            self.check("one translation redo restores records and bilingual display",
                       translation_snapshot(page.project) == translated
                       and settings_from_state(page.project.studio_state).mode == "bilingual")
            saved = save_project(page.project, output / "translated.2byteproj")
            reopened = load_project(saved)
            self.check("translated project reopens with preserved source and target",
                       [asdict(c) for c in reopened.cues] == source_cues
                       and translation_snapshot(reopened) == translated
                       and settings_from_state(reopened.studio_state).mode == "bilingual")
            page.undo_stack.setClean()
            if config.get("extended_cases"):
                from .ai_cleanup_extended_audit import run_extended
                yield from run_extended(self, window, output, config["extended_cases"])

        def finish(self):
            self.timer.stop()
            try:
                self.steps.close()  # Restore observers/provider replay if waiting times out.
            except Exception:
                self.result.setdefault('cleanup_errors', []).append(traceback.format_exc())
                self.result['passed'] = False
            if self.dialog is not None:
                self.dialog.reject()
            self.write()
            def closed():
                self.result["gui_shutdown"] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(closed)
            page = window.built_page("studio")
            if page is not None:
                page.undo_stack.setClean()
            window.result_exit_code = 0 if self.result["passed"] else 1
            window.close()

    window._ai_cleanup_apply_audit = Audit()
