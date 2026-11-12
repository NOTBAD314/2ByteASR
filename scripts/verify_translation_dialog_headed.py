"""Headed check of the translation dialog (2026-11-11 方案 A).

Opens SubtitleTranslationDialog in a real window on a synthetic Italian
project (most lines translated, 23 failed), for each theme, and saves the
idle / advanced-open / running / finished faces as PNG. Also measures that
the three step badges share one x and samples the checked range card's
border colour. Nothing is sent to any service; no user data is touched.

    python -X utf8 scripts/verify_translation_dialog_headed.py --output tmp/<dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IT = ["anche con dei test in Formula 4", "che Russell ci ha provato", "cioè cosa ti aspetti",
      "e poi ha fatto il giro veloce", "guarda la curva parabolica"]


class _OfflineProvider:
    """Answers every line locally; no network."""
    provider_id = "offline-fixture"
    model = "offline-fixture"

    def structured_complete(self, messages, schema, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        return {"items": [{"id": line["id"], "translation": "这是第 " + line["id"][1:] + " 句译文"}
                          for line in payload["lines"] if line["translate"]]}


def _project(total: int, failed: int):
    from PySide6.QtGui import QUndoStack  # noqa: F401 - Qt first
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
    from twobyteasr.subtitle_rules import subtitle_translation as st
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=total * 1000 + 1000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, f"{IT[index % len(IT)]} {index}",
                        speaker_id="S01" if index % 2 else "S00") for index in range(total)],
        speakers=[StudioSpeaker("S00", "Matteo"), StudioSpeaker("S01", "Federico")])
    project.validate()
    project.generation_metadata["language"] = {"code": "it"}
    sources = {cue.id: cue.text for cue in project.cues}
    st.apply_translation_result(project, st.translate(project, [cue.id for cue in project.cues[failed:]],
                                                      _OfflineProvider(), target="zh-Hans",
                                                      retry_wait=lambda _seconds: True))
    st.apply_translation_result(project, st.TranslationResult(
        target="zh-Hans", model="fixture", provider="fixture",
        failed={cue.id: "number_mismatch" for cue in project.cues[:failed]}, sources=sources))
    return project


def _page(project):
    from PySide6.QtGui import QUndoStack
    order = list(project.cues)
    return SimpleNamespace(project=project, selected_cue_ids=lambda: [order[5].id], undo_stack=QUndoStack(),
                           _cue_jump_order=order, _cue_jump_index={cue.id: i for i, cue in enumerate(order)},
                           _review_mode=False, _go_to_listed_cue=lambda cue: None,
                           cue_model=SimpleNamespace(filter_status="all", row_for_cue_id=lambda _cue_id: -1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--total", type=int, default=240)
    parser.add_argument("--failed", type=int, default=23)
    parser.add_argument("--language", default="zh", help="UI language, e.g. zh / en / ja")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    if args.language != "zh":
        import twobyteasr.i18n as i18n
        i18n._CURRENT_LANGUAGE_CACHE = args.language  # this process only; settings untouched
    import twobyteasr.design.theme_manager as theme_manager
    from twobyteasr.design.ui_theme import theme_definition
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    from twobyteasr.subtitle_rules import subtitle_translation as st
    report = {"platform": app.platformName(), "themes": {}}
    ok = True
    for key in ("grape", "warm"):
        theme_manager.theme_key = lambda key=key: key
        theme = theme_definition(key)
        project = _project(args.total, args.failed)
        dialog = SubtitleTranslationDialog(_page(project))
        dialog.show()
        for _ in range(5):
            app.processEvents()

        def shot(name):
            dialog._fit_height()
            for _ in range(5):
                app.processEvents()
            path = out / f"{args.language}-{key}-{name}.png"
            dialog.grab().save(str(path))
            return str(path)

        entry = {"shots": {}}
        entry["shots"]["idle"] = shot("idle")
        badges = [widget for widget in dialog.findChildren(type(dialog.result_title))
                  if widget.objectName() == "translationStep"]
        xs = sorted({widget.mapTo(dialog, QPoint(0, 0)).x() for widget in badges})
        entry["step_badges"] = len(badges)
        entry["step_x"] = xs
        cards = dialog.scope_buttons
        entry["cards"] = {name: dict(count=card.count(), checked=card.isChecked(), enabled=card.isEnabled())
                          for name, card in cards.items()}
        samples = {}
        for name, expected in (("pending", theme.danger), ("all", theme.success), ("selected", theme.accent)):
            cards[name].setChecked(True)
            app.processEvents()
            image = cards[name].grab().toImage()
            pixel = QColor(image.pixelColor(image.width() // 2, int(image.devicePixelRatio())))
            samples[name] = dict(border=pixel.name(), expected=QColor(expected).name(),
                                 start=dialog.start_button.text())
        cards["pending"].setChecked(True)
        entry["card_border"] = samples
        dialog.advanced_toggle.click()
        entry["shots"]["advanced"] = shot("advanced")
        dialog.advanced_toggle.click()
        dialog._run_total = args.failed
        dialog.run_detail.setText("正在把 23 条翻成简体中文")
        dialog._set_phase("run")
        dialog._on_progress(13, args.failed, "")
        entry["shots"]["run"] = shot("run")
        sources = {cue.id: cue.text for cue in project.cues}
        result = st.TranslationResult(target="zh-Hans", model="fixture", provider="fixture",
                                      failed={project.cues[0].id: "number_mismatch"}, sources=sources)
        dialog._on_finished(result)
        dialog.log_toggle.click()
        entry["shots"]["done"] = shot("done")
        entry["status"] = dialog.status.text()
        entry["result_title"] = dialog.result_title.text()
        entry["size"] = [dialog.width(), dialog.height()]
        aligned = len(badges) == 3 and len(xs) == 1
        colours = all(abs(QColor(v["border"]).red() - QColor(v["expected"]).red()) < 24
                      and abs(QColor(v["border"]).green() - QColor(v["expected"]).green()) < 24
                      and abs(QColor(v["border"]).blue() - QColor(v["expected"]).blue()) < 24
                      for v in samples.values())
        entry["checks"] = dict(steps_aligned=aligned, card_colours=colours)
        ok = ok and aligned and colours
        report["themes"][key] = entry
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
    report["ok"] = ok
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value["checks"] for key, value in report["themes"].items()}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
