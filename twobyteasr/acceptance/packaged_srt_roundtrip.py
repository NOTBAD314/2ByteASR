"""Read owned, hash-bound copies through the packaged SRT production paths."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def verify_real_samples(output):
    from PySide6.QtGui import QUndoStack
    from ..projects.studio_project import StudioMedia, SubtitleProject, load_project, save_project
    from ..projects.subtitle_import import prepare_import, read_subtitles, imported_track
    from ..timeline.subtitle_import_command import ImportSubtitlesCommand
    from ..exports.studio_subtitle_export import (export_subtitle_artifacts, export_language_layers,
                                                SubtitleExportOptions)
    output = Path(output).resolve()
    manifest = output / "real-inputs.json"
    if not manifest.is_file():
        return dict(cases=[], supplied=False)
    spec = json.loads(manifest.read_text("utf-8"))

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def source(relative):
        path = (output / relative).resolve()
        if not path.is_relative_to(output) or digest(path) != spec["hashes"][relative]:
            raise ValueError("Real sample escaped the audit or changed: " + relative)
        return path

    def empty():
        return SubtitleProject(StudioMedia(""), render_settings={"_cue_domain": "timeline"})

    def content(project):
        return sorted((imported_track(project, c.speaker_id).get("speaker", ""),
                       imported_track(project, c.speaker_id).get("language", ""),
                       imported_track(project, c.speaker_id).get("role", "independent"),
                       c.start_ms, c.end_ms, c.text) for c in project.cues)

    def check(value, message):
        if not value:
            raise AssertionError(message)

    cases = []
    for case in spec["cases"]:
        paths = [source(path) for path in case["files"]]
        expected = sorted((row.speaker, row.language, row.role, row.start_ms, row.end_ms, row.text)
                          for path in paths for row in read_subtitles(path).rows)
        project = empty()
        stack = QUndoStack()
        plan = prepare_import(project, paths)
        check(not plan.failures, str(plan.failures))
        stack.push(ImportSubtitlesCommand(project, plan))
        check(content(project) == expected, "Existing SRT manuscript/time/ownership changed")
        first_ids = {c.id for c in project.cues}
        duplicate = prepare_import(project, [paths[0]])
        stack.push(ImportSubtitlesCommand(project, duplicate))
        check(len(project.cues) == len(expected) + len(duplicate.cues), "Repeat import lost cues")
        check(len({c.id for c in project.cues}) == len(project.cues), "Repeat IDs collided")
        stack.undo()
        check(content(project) == expected and {c.id for c in project.cues} == first_ids, "Undo changed old cues")
        stack.redo()
        stack.undo()
        folder = output / "real-roundtrip" / case["name"]
        folder.mkdir(parents=True)
        saved = folder / "imported.2byteproj"
        save_project(project, saved)
        project = load_project(saved)
        check(content(project) == expected, "Save/reopen changed cues")
        artifacts = export_subtitle_artifacts(project, folder / "export", "字幕",
                                              SubtitleExportOptions(speaker_mode="per_speaker"))
        restored = empty()
        ImportSubtitlesCommand(restored, prepare_import(restored, [a.path for a in artifacts])).redo()
        check(content(restored) == expected, "Actual SRT export/reimport changed cues")
        cases.append(dict(name=case["name"], cues=len(restored.cues), tracks=len(restored.speakers), passed=True))

    source_project = load_project(source(spec["project"]))
    generated = export_language_layers(source_project, output / "real-roundtrip/project-export", "实际工程",
                                      ("original", "translation"), speaker_mode="per_speaker")
    restored = empty()
    plan = prepare_import(restored, [a.path for a in reversed(generated.artifacts)])
    check(not plan.failures, str(plan.failures))
    ImportSubtitlesCommand(restored, plan).redo()
    expected = content(restored)
    check(len(restored.cues) == sum(a.cue_count for a in generated.artifacts), "Original/translation counts lost")
    again = export_subtitle_artifacts(restored, output / "real-roundtrip/project-reexport", "再次导出",
                                     SubtitleExportOptions(speaker_mode="per_speaker"))
    second = empty()
    ImportSubtitlesCommand(second, prepare_import(second, [a.path for a in again])).redo()
    check(content(second) == expected, "Real project's second roundtrip changed ownership/time/text")
    cases.append(dict(name="actual-project", source_cues=len(source_project.cues), files=len(generated.artifacts),
                      cues=len(second.cues), tracks=len(second.speakers), passed=True))
    check(all(digest(source(path)) == value for path, value in spec["hashes"].items()), "Copied inputs changed")
    return dict(supplied=True, passed=True, cases=cases, input_hashes=spec["hashes"])
