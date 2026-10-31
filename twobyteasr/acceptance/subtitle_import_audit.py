"""Normal-entry, offline Windows UI acceptance for independent subtitle imports."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QMimeData, QObject, QPointF, QTimer, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from ..projects.studio_project import StudioCue, load_project, save_project
    from ..projects.subtitle_import import imported_track
    from ..projects.studio_runtime_state import state_for
    from ..timeline.studio_commands import SetSpeakersVisibilityCommand
    from ..timeline.studio_track_delete import DeleteTrackCommand
    from ..exports.studio_subtitle_export import compile_srt, export_subtitle_artifacts, SubtitleExportOptions
    from ..design.theme_manager import apply_theme
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(), executable=os.sys.executable,
                               entry="quick_start.py normal MainWindow / Studio", theme=os.environ.get("TWOBYTEASR_SRT_AUDIT_THEME", "grape"))
            import sys
            from ..projects import subtitle_import
            from ..timeline import subtitle_import_command
            from ..exports import subtitle_metadata
            self.result['runtime'] = dict(frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable,
                exe_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                build=load_build_identity().to_dict(), modules={m.__name__:m.__file__
                    for m in (subtitle_import, subtitle_import_command, subtitle_metadata)})
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic() + 90
            self.timer = QTimer(self)
            self.timer.setInterval(100)
            self.timer.timeout.connect(self.advance)
            self.timer.start()

        def check(self, name, value, detail=None):
            self.result["checks"].append(dict(name=name, passed=bool(value), detail=detail))
            if not value:
                raise AssertionError(name + " " + str(detail))

        def shot(self, name):
            _capture(window, output / (name + ".png"))
            self.result["screenshots"].append(name + ".png")

        def ready(self):
            p = self.page
            return p.project is not None and p._readiness.ready and not p._readiness.active

        def content(self, project):
            return sorted((imported_track(project, c.speaker_id).get("speaker", ""),
                           imported_track(project, c.speaker_id).get("language", ""),
                           c.start_ms, c.end_ms, c.text) for c in project.cues)

        def run(self):
            p = self.page
            apply_theme(self.result["theme"])
            window.showNormal()
            window.resize(1500, 950)
            window.open_studio_project(output / "projects/existing-zero/existing-zero.2byteproj", mode="edit", source="srt_import_audit")
            yield self.ready
            yield .3
            self.check("blank project", not p.project.cues)
            fixture_dir = output / "srt"
            fixture_dir.mkdir()
            paths = {}
            for name, count in (("S00zh", 1), ("s01IT", 2), ("S00it", 2), ("S01zh", 1)):
                path = fixture_dir / (name + ".srt")
                path.write_text(compile_srt([StudioCue(str(i), 100 + i * 2200, 2000 + i * 2200,
                    name + f" 台词 {i} S00 / IT（括号保留）\n第二行") for i in range(count)]), "utf-8")
                paths[name] = path
            choose = QFileDialog.getOpenFileNames
            QFileDialog.getOpenFileNames = staticmethod(lambda *a: ([str(paths["S00zh"]), str(paths["s01IT"])], ""))
            try:
                self.check("import button visible", p.cue_import_subtitles_button.isVisible())
                QTest.mouseClick(p.cue_import_subtitles_button, Qt.LeftButton)
            finally:
                QFileDialog.getOpenFileNames = choose
            yield .3
            self.check("file dialog selection routes batch", len(p.project.cues) == p.cue_model.rowCount() == 3)
            self.check("expected initial track labels", {s.name for s in p.project.speakers} == {"S00 · 中文", "S01 · 意大利语"})
            self.check("one commit for first batch", state_for(p.project).commit_count == 1)
            self.shot("01-two-language-speaker-tracks")
            window._desktop_intake.submit([str(paths["S00it"]), str(paths["S01zh"])])
            yield lambda: not window._desktop_intake.requests and not window._desktop_intake.active
            yield .3
            self.check("desktop batch retained first files", len(p.project.cues) == 6 and len(p.project.speakers) == 4)
            self.check("four visible timeline tracks", len(p.timeline._track_layout()[0]) == 4)
            self.shot("02-four-independent-tracks")
            edited = p.project.cues[0]
            p.select_cue(edited.id)
            p._timeline_text_edited(edited.id, False, "人工编辑 S00 / IT（保留）\n第二行")
            yield .2
            self.check("independent imported cue editable", p.project.cues[0].text.startswith("人工编辑"))
            before = copy.deepcopy(p.project.cues)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(paths["S00zh"]))])
            event = QDropEvent(QPointF(700, 700), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            p.dropEvent(event)
            yield .2
            self.check("repeat drop is additive", len(p.project.cues) == 7 and p.project.cues[:6] == before)
            self.check("repeat name suffix", p.project.speakers[-1].name == "S00 · 中文（2）")
            self.check("unique internal IDs", len({c.id for c in p.project.cues}) == 7)
            p._undo_interactive()
            yield .2
            self.check("undo import only", p.project.cues == before and p.cue_model.rowCount() == 6 and p.speaker.count() == 4)
            p._redo_interactive()
            yield .2
            self.check("redo import", p.cue_model.rowCount() == 7 and p.speaker.count() == 5)
            target = p.project.speakers[-1].id
            preserved = copy.deepcopy(p.project.cues)
            other_ids = {c.id for c in p.project.cues if c.speaker_id != target}
            p._import_subtitle_files([paths['s01IT']], replace_track_id=target)
            yield .2
            self.check('explicit replacement only changes target', len(p.project.cues) == 8
                       and other_ids <= {c.id for c in p.project.cues})
            self.check('replacement updates source language and speaker',
                       imported_track(p.project, target).get('speaker') == 'S01'
                       and imported_track(p.project, target).get('language') == 'it'
                       and next(s.name for s in p.project.speakers if s.id == target).startswith('S01 · 意大利语'))
            p._undo_interactive()
            yield .2
            self.check('replacement undo restores old content and labels', p.project.cues == preserved
                       and next(s.name for s in p.project.speakers if s.id == target) == 'S00 · 中文（2）')
            unknown = fixture_dir / 'ordinary.srt'
            unknown.write_text(compile_srt([StudioCue('1', 100, 2000, '正文 IT、S00（保留）')]), 'utf-8')
            malformed = fixture_dir / 'malformed.srt'
            malformed.write_text('invalid subtitle file', 'utf-8')
            plan = p._import_subtitle_files([unknown, malformed])
            yield .2
            self.check('partial failure retains successful file and all existing content',
                       plan is not None and len(plan.failures) == 1 and len(p.project.cues) == 8
                       and p.project.cues[:7] == preserved)
            self.check('unlabelled file gets independent unknown track and intact body',
                       p.project.speakers[-1].name == 'ordinary · 未指定语言'
                       and p.project.cues[-1].text == '正文 IT、S00（保留）')
            p._undo_interactive()
            yield .2
            self.check('undo partial batch affects only this import', p.project.cues == preserved)
            p.undo_stack.push(SetSpeakersVisibilityCommand(p.project, {target}, p._changed))
            yield .2
            self.check("track output visibility independent", len(p.project.visible_cues()) == 6 and len(p.project.cues) == 7)
            p._undo_interactive()
            p.undo_stack.push(DeleteTrackCommand(p.project, "subtitle", target, p))
            yield .2
            self.check("independent track deletion", len(p.project.cues) == 6)
            p._undo_interactive()
            yield .2
            self.check("track deletion reversible", len(p.project.cues) == 7)
            self.shot("03-duplicate-undo-redo")
            expected = self.content(p.project)
            QTest.mouseClick(p.save_button, Qt.LeftButton)
            yield .4
            self.check("normal save persisted all metadata", self.content(load_project(p.project_path)) == expected)
            project_path = p.project_path
            p.open_project(project_path, skip_dirty_guard=True)
            yield self.ready
            yield .2
            self.check("normal reopen keeps five tracks", len(p.project.speakers) == 5 and self.content(p.project) == expected)
            exported = export_subtitle_artifacts(p.project, output / "exports", "实窗字幕", SubtitleExportOptions(speaker_mode="per_speaker"))
            self.check("per-track SRT files", len(exported) == 5)
            from ..projects.subtitle_import import prepare_import
            from ..timeline.subtitle_import_command import ImportSubtitlesCommand
            from ..projects.studio_project import StudioMedia, SubtitleProject
            q = SubtitleProject(StudioMedia(""), render_settings={"_cue_domain": "timeline"})
            plan = prepare_import(q, [a.path for a in exported])
            command = ImportSubtitlesCommand(q, plan)
            command.redo()
            self.check("UI project export reimport text/time/language/speaker", self.content(q) == expected)
            again = export_subtitle_artifacts(q, output / "reexports", "再导出", SubtitleExportOptions())
            self.check("combined export includes all rows", sum(a.cue_count for a in again) == 7)
            self.shot("04-saved-reopened")
            self.result["track_names"] = [s.name for s in p.project.speakers]
            self.result["cue_count"] = len(p.project.cues)
            from .packaged_srt_roundtrip import verify_real_samples
            self.result['real_samples'] = verify_real_samples(output)
            self.check('existing real SRT and project roundtrips',
                       not self.result['real_samples'].get('supplied') or self.result['real_samples'].get('passed'))

        def advance(self):
            try:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    raise RuntimeError(modal.text())
                if callable(self.waiting):
                    if not self.waiting():
                        if time.monotonic() > self.deadline:
                            raise TimeoutError("UI readiness timed out")
                        return
                elif time.monotonic() < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else time.monotonic() + step
                self.deadline = time.monotonic() + 60
            except StopIteration:
                self.result["passed"] = True
                self.finish()
            except Exception:
                self.result["error"] = traceback.format_exc()
                try: self.shot("failure")
                except Exception: pass
                self.finish()

        def finish(self):
            self.timer.stop()
            self.page.undo_stack.setClean()
            window.result_exit_code = 0 if self.result["passed"] else 1
            def write():
                (output / "result.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf-8")
            write()
            def stopped():
                self.result["gui_shutdown"] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.close()

    window._subtitle_import_audit = Audit()
