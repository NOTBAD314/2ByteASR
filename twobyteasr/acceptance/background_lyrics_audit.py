"""Exercise the background lyrics speaker, Studio and completion export."""
import json
import traceback
from types import SimpleNamespace


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ..exports.completion_export import CompletionExportDialog, QFileDialog
    from ..exports.studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts
    from ..projects.studio_project import load_project, project_from_runtime_cues, save_project
    from ..recognition.background_lyrics import METADATA_KEY, SPEAKER_ID
    from ..rendering.ass_compiler import compile_ass
    from ..storage.settings import load_runtime_settings, save_runtime_settings
    from ..studio.studio_speaker_manager import SpeakerManagerDialog

    lyric = "夜色落在遠方"
    speech = "我們現在回城"
    result = {"checks": [], "passed": False}
    path = output / "recognition.2byteproj"
    state = {"remaining": 45}

    def check(name, passed):
        result["checks"].append({"name": name, "passed": bool(passed)})

    def write_result():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def finish():
        result["passed"] = not result.get("error") and bool(result["checks"]) and all(
            item["passed"] for item in result["checks"]
        )
        write_result()
        window.close()
        QTimer.singleShot(100, QApplication.instance().quit)

    def later(delay, action):
        def guarded():
            try:
                action()
            except Exception:
                result["error"] = traceback.format_exc()
                dialog = QApplication.activeModalWidget()
                if dialog is not None:
                    dialog.reject()
                finish()
        QTimer.singleShot(delay, guarded)

    def begin():
        settings, _, _ = load_runtime_settings(output)
        check("grouping second pass is off and lyrics are on by default",
              settings["switches"]["grouping_ai_editor"] is False
              and settings["switches"]["background_lyrics"] is True)
        settings["switches"].update(grouping_ai_editor=True, background_lyrics=False)
        save_runtime_settings(settings, output)
        loaded, _, _ = load_runtime_settings(output)
        check("both options survive the normal settings save and reload",
              loaded["switches"]["grouping_ai_editor"] is True
              and loaded["switches"]["background_lyrics"] is False)
        cues = [SimpleNamespace(start=0.2, end=1.5, text=speech, speaker="S00"),
                SimpleNamespace(start=2.0, end=3.0, text=lyric, speaker="S00")]
        metadata = {METADATA_KEY: {"lines": [{"start_ms": 2000, "end_ms": 3000, "text": lyric}]}}
        project = project_from_runtime_cues(output / "lyrics-fixture.mp4", cues, generation_metadata=metadata)
        save_project(project, path)
        check("project keeps both lines and hides only lyrics", len(project.cues) == 2
              and project.hidden_speaker_ids() == {SPEAKER_ID})
        window.open_studio_project(str(path), mode="edit", source="background_lyrics_audit")
        later(400, studio_ready)

    def studio_ready():
        page = window.built_page("studio")
        if page is None or page.project is None or not page._readiness.ready:
            state["remaining"] -= 1
            if state["remaining"] <= 0:
                raise RuntimeError("Studio did not open the generated project")
            later(400, studio_ready)
            return
        state["page"] = page
        check("Studio reopens with the lyrics speaker hidden", SPEAKER_ID in page.project.hidden_speaker_ids())
        ass = compile_ass(page.project)
        check("preview subtitle stream omits lyrics", speech in ass and lyric not in ass)
        complete = CompletionExportDialog(page.project, "completion", window)
        state["complete"] = complete
        QFileDialog.getExistingDirectory = staticmethod(lambda *_args, **_kwargs: str(output))
        complete.show()
        later(300, export_completion)

    def export_completion():
        dialog = state["complete"]
        chip = dialog.speaker_chips.get(SPEAKER_ID)
        check("completion lyrics chip is available and unchecked",
              chip is not None and not chip.isChecked())
        check("all speakers chip reflects exclusion", not dialog.all_speakers.isChecked())
        dialog.grab().save(str(output / "completion.png"))
        dialog.export_button.click()
        later(250, export_ready)

    def export_ready():
        dialog = state["complete"]
        target = output / "completion.srt"
        if not target.is_file() and getattr(dialog, "_subtitle_task", None) is not None:
            later(250, export_ready)
            return
        text = target.read_text("utf-8-sig") if target.is_file() else ""
        check("completion SRT contains speech and excludes lyrics", speech in text and lyric not in text)
        dialog.close()
        page = state["page"]
        later(600, show_lyrics)
        page.speaker_manager_button.click()
        later(200, verify_restored)

    def show_lyrics():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, SpeakerManagerDialog):
            raise RuntimeError("Speaker manager dialog is unavailable")
        check("lyrics speaker is visible in the manager", SPEAKER_ID in dialog.cards)
        dialog.grab().save(str(output / "lyrics-speaker.png"))
        button = dialog.cards[SPEAKER_ID].visible_button
        check("the lyrics visibility control is off", not button.isChecked())
        button.click()
        dialog.done_button.click()

    def verify_restored():
        page = state["page"]
        check("show speaker restores preview lyrics", lyric in compile_ass(page.project))
        options = SubtitleExportOptions(frozenset({"srt"}), "combined")
        artifacts = export_subtitle_artifacts(page.project, output, "restored", options)
        check("restored SRT includes both lines", len(artifacts) == 1 and all(
            text in artifacts[0].path.read_text("utf-8-sig") for text in (speech, lyric)
        ))
        page.save(on_finished=lambda saved, error: later(0, lambda: verify_saved(saved, error)))

    def verify_saved(saved, error):
        check("saved project remembers the visible lyrics speaker", error is None and saved is not None
              and SPEAKER_ID not in load_project(saved).hidden_speaker_ids())
        finish()

    def shutdown():
        result["gui_shutdown"] = True
        write_result()

    QApplication.instance().aboutToQuit.connect(shutdown)
    later(2000, begin)
