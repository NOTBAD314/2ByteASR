# -*- coding: utf-8 -*-
"""Headed verification: clip assistant recall quality + usability (round 29).

Checks on a synthetic 36-minute stream (5-30min highlight arc + quiet tail):
  1. Local recall clusters the 25-minute arc into ONE long candidate (not
     dozens of 30s fragments) and the reason carries concrete evidence.
  2. candidates_from_local keeps the long span when max_seconds=1800.
  3. After candidates land in the panel the settings area auto-collapses to
     the candidates view; a later set_project_status does not stack it back.
  4. Candidate card evidence (danmaku/subtitle quotes) is visible by default.
  5. Length cap allows 3600s; AI service/model selectors are present.
  6. Screenshots for agy visual review (re-show + isVisible assert first).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.studio_danmaku import parse_danmaku_xml
from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_highlight_analyzer import (
    candidates_from_local,
    discover_local_candidates,
    highlight_transcript_project,
)
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio_ui import SubtitleStudioPage

OUT = ROOT / "tmp" / "verify-round29-clip"
OUT.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[ROUND29-CLIP] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def build_project() -> SubtitleProject:
    """36-min stream: neutral chatter, one 25-min highlight arc, quiet praise."""
    cues: list[StudioCue] = []
    texts = {
        "neutral": "我们就正常推进一下这边的进度啊，大家不要着急。",
        "arc": "这一波打完就直接翻盘了，你们敢信？卧槽居然真的成功了。",
        "praise": "这一段真的好强，没想到最后是这样处理的。",
    }
    kinds: list[tuple[int, int, str]] = []
    for minute in range(36):
        if 5 <= minute < 30:
            kinds.append((minute, 60, "arc"))
        elif minute == 32:
            kinds.append((minute, 20, "praise"))
        else:
            kinds.append((minute, 30, "neutral"))
    index = 0
    for minute, chars, kind in kinds:
        for offset in range(0, 60, 10):
            text = texts[kind]
            start = minute * 60_000 + offset * 1000
            cues.append(StudioCue(f"c{index}", start, start + 6_000, text, speaker_id="S01"))
            index += 1
    return SubtitleProject(
        media=StudioMedia(path="D:/synthetic36m.mp4", duration_ms=36 * 60_000),
        cues=cues,
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )


def build_danmaku_xml(path: Path) -> Path:
    rows: list[tuple[float, str]] = []
    plain = "普通弹幕"
    hype_pool = ("哈哈哈哈", "笑死我了", "牛！太强了", "卧槽", "这波可以", "名场面", "泪目", "绝了")
    for window in range(0, 36 * 60, 30):
        base = plain
        count = 2
        if 5 * 60 <= window < 30 * 60:
            count = 8
        for i in range(count):
            text = hype_pool[i % len(hype_pool)] if 5 * 60 <= window < 30 * 60 else base
            rows.append((window + i * 3 + 0.5, text))
    body = "".join(f'<d p="{t},1,25,1,0,0,0,0">{text}</d>' for t, text in rows)
    path.write_text(f"<i>{body}</i>", encoding="utf-8")
    return path


def grab_visible(widget, name: str):
    widget.show()
    if not widget.isVisible():
        raise RuntimeError(f"{name} not visible before grab")
    return widget.grab()


def main() -> int:
    app = QApplication.instance() or QApplication([])

    project = build_project()
    xml_path = build_danmaku_xml(OUT / "danmaku.xml")
    danmaku = parse_danmaku_xml(str(xml_path))
    view = highlight_transcript_project(project)
    locals_ = discover_local_candidates(view, danmaku, window_ms=30_000)
    candidates = candidates_from_local(view, locals_, limit=20, max_seconds=1800)

    # ---- 1. cluster span ---------------------------------------------------
    danmaku_backed = [item for item in candidates if item.danmaku_signal.get("peak")]
    spans = [(item.source_out_ms - item.source_in_ms) // 1000 for item in danmaku_backed]
    longest = max(spans, default=0)
    check("long arc recalled as one long candidate", longest >= 20 * 60,
          f"longest span {longest}s over {len(danmaku_backed)} danmaku candidates")
    check("no fragment storm", len(danmaku_backed) <= 3, f"danmaku candidates: {len(danmaku_backed)}")
    top = danmaku_backed[0] if danmaku_backed else None
    check("reason carries concrete cluster evidence",
          top is not None and "弹幕高峰" in top.reason and "条" in top.reason,
          f"reason: {top.reason[:60] if top else 'NONE'}")
    check("quiet praise segment recalled via subtitles",
          any("强情绪" in item.reason for item in candidates),
          "semantic candidates present")

    # ---- studio page with the panel ---------------------------------------
    page = SubtitleStudioPage()
    page.video.load = lambda *a, **k: None
    page._generate_waveform = lambda *a, **k: None
    page.open_project(save_project(project, OUT / "studio.2byteproj"))
    page.resize(1680, 1000)
    page.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)

    sequence = sequence_of(page.project)
    sequence.danmaku_path = str(xml_path)
    sequence.clip_candidates = candidates
    panel = page.highlight_panel
    panel.set_xml_discovery((str(xml_path),), str(xml_path), automatic=False)
    panel.set_project_status(page.project, str(xml_path))
    for _ in range(10):
        app.processEvents()

    # ---- 2. auto-collapse --------------------------------------------------
    check("settings auto-collapsed after candidates", not panel.config_body.isVisibleTo(panel),
          f"stage={panel.active_stage()}")
    check("candidates view visible", panel.candidates_body.isVisibleTo(panel))
    check("candidate cards rendered", panel.results.count() >= 1, f"{panel.results.count()} cards")
    panel.set_project_status(page.project, str(xml_path))
    for _ in range(10):
        app.processEvents()
    check("later set_project_status keeps settings collapsed",
          not panel.config_body.isVisibleTo(panel) and panel.candidates_body.isVisibleTo(panel))

    # ---- 3. card evidence visible by default -------------------------------
    card = panel.results.itemWidget(panel.results.item(0))
    evidence = card.findChild(QLabel, "highlightEvidence") if card else None
    check("card evidence visible by default",
          evidence is not None and not evidence.isHidden() and bool(evidence.text()),
          f"evidence: {evidence.text()[:40] if evidence else 'NONE'}")

    # ---- 4. settings widgets ------------------------------------------------
    check("length cap reaches 3600s", panel.max_box.maximum() >= 3600,
          f"max={panel.max_box.maximum()}")
    check("AI service selector populated", panel.ai_service_combo.count() >= 3,
          f"{panel.ai_service_combo.count()} entries")
    service_index = panel.ai_service_combo.findData("deepseek")
    panel.ai_service_combo.setCurrentIndex(max(0, service_index))
    app.processEvents()
    check("model selector follows service", panel.ai_model_combo.count() >= 2,
          f"{panel.ai_model_combo.count()} models")

    # ---- 5. screenshots for review -----------------------------------------
    tab_index = getattr(page, "highlight_tab_index", None)
    if tab_index is not None:
        page.context_drawer.setCurrentIndex(int(tab_index))
        app.processEvents()
    shot = grab_visible(panel, "highlight panel")
    shot.save(str(OUT / "panel_candidates.png"))

    panel._show_stage("settings")
    app.processEvents()
    shot_settings = grab_visible(panel, "highlight settings")
    shot_settings.save(str(OUT / "panel_settings.png"))

    failed = [item for item in RESULTS if not item[1]]
    print(f"[ROUND29-CLIP] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed", flush=True)
    page.close_page()
    page.deleteLater()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
