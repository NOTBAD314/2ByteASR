"""剪辑往返真机审计（2026-09-19 P0）：完整录播 → 生成剪辑 → 返回完整。

复用 --playback-audit 的全页脚手架（真实工程副本 + 真实 mpv）：
- 剪辑模式下 mpv sub-text 探针验证视频字幕实际可见（source 域投影）。
- 返回完整录播后全集恢复、时长/时间轴/画面一致。
- 10 次往返稳定性、保存重开、导出域一致性。

用法：.venv/Scripts/python.exe scripts/verify_clip_roundtrip_headed.py [--project <.2byteproj>] --out <report.json>
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tmp" / "clip-round-20260919"
DEFAULT_PROJECT = Path(os.environ["LOCALAPPDATA"]) / r"2ByteASR\Projects\未命名工程\未命名工程.2byteproj"
CLIP_IN, CLIP_OUT = 120_000, 300_000


def _pump(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from twobyteasr.studio_ui import SubtitleStudioPage
    from twobyteasr.studio_edit_commands import generate_edit_command, restore_full_sequence_command
    from twobyteasr.studio_edit_sequence import (
        HighlightCandidate, projected_cues, sequence_of, timeline_duration_ms,
    )

    report: dict = {"checks": [], "failures": []}

    def check(name, ok, detail=""):
        report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
        print(("[PASS] " if ok else "[FAIL] ") + name + (f" :: {detail}" if detail else ""), flush=True)
        if not ok:
            report["failures"].append(name)
        return bool(ok)

    project_copy = OUT / "audit-project.2byteproj"
    shutil.copyfile(DEFAULT_PROJECT, project_copy)
    page = SubtitleStudioPage()
    page.show()
    ready = {"done": False}
    page.open_project(str(project_copy), on_ready=lambda: ready.__setitem__("done", True))
    for _ in range(120):
        if ready["done"]:
            break
        _pump(app, 1.0)
    if not check("project_open_ready", ready["done"]):
        page.close_page()
        (OUT / "clip-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    project = page.project
    baseline_n = len(project.cues)
    baseline_first = min(c.start_ms for c in project.cues)
    check("baseline_full_cues", baseline_n == 496, f"n={baseline_n}")

    # 选一条剪辑区间内、时长足够的 cue 作为字幕可见性探针目标。
    probe_cue = next(
        (c for c in project.cues
         if CLIP_IN + 4_000 < (c.start_ms + c.end_ms) / 2 < CLIP_OUT - 4_000
         and c.end_ms - c.start_ms >= 2500 and len(c.text.strip()) >= 4),
        None,
    )
    check("probe_cue_picked", probe_cue is not None, f"cue={probe_cue.id if probe_cue else None}")
    probe_mid_s = (probe_cue.start_ms + 500) / 1000.0  # 段内前部即命中事件窗口

    def mpv_sub_text() -> str:
        try:
            controller = page.video.controller
            if controller is None or not controller.running:
                return ""
            return str(controller.get_property("sub-text", "") or "")
        except Exception:
            return ""

    def seek_and_probe(seconds: float, label: str, expect_text: str, budget: float = 12.0):
        page._seek(seconds)
        _pump(app, 1.2)
        deadline = time.monotonic() + budget
        best = ""
        while time.monotonic() < deadline:
            text = mpv_sub_text()
            if text:
                best = text
                if expect_text[:4] in text:
                    break
            _pump(app, 0.5)
        report.setdefault("sub_text_probes", {})[label] = best[:80]
        return best

    # ---------- 完整录播基线：字幕在视频上可见 ----------
    full_text = seek_and_probe(probe_mid_s, "full_baseline", probe_cue.text)
    check("A_full_mode_sub_visible", probe_cue.text[:4] in full_text,
          f"expect={probe_cue.text[:12]!r} got={full_text[:24]!r}")

    # ---------- 生成剪辑（走页面同款命令路径） ----------
    sequence_of(project).clip_candidates = [
        HighlightCandidate(id="audit", title="审计", source_in_ms=CLIP_IN,
                           source_out_ms=CLIP_OUT, status="accepted")
    ]
    page.undo_stack.push(generate_edit_command(project, changed=page._sequence_changed))
    _pump(app, 4.0)

    check("A_generate_keeps_full", len(project.cues) == baseline_n, f"n={len(project.cues)}")
    view = projected_cues(project, domain="timeline")
    check("A_clip_view_subset", 0 < len(view) < baseline_n, f"view={len(view)}")
    first_view = min(view, key=lambda c: c.start_ms)
    expected_first_source = min((c for c in project.cues if c.end_ms > CLIP_IN), key=lambda c: c.start_ms)
    check("A_local_time_mapping", first_view.start_ms == expected_first_source.start_ms - CLIP_IN,
          f"view_first={first_view.start_ms} source_first={expected_first_source.start_ms}")
    check("A_timeline_duration_clip", timeline_duration_ms(project) == CLIP_OUT - CLIP_IN,
          f"tdm={timeline_duration_ms(project)}")

    # 剪辑模式下视频字幕可见（关键：mpv 时钟在源域，ASS=source 域投影）。
    # page._seek 在 mapped 模式收时间轴秒（transport 内部映射回源）。
    probe_view_cue = next(c for c in view if c.id.startswith(f"{probe_cue.id}#"))
    clip_text = seek_and_probe(
        (probe_view_cue.start_ms + 500) / 1000.0, "clip_mode", probe_cue.text
    )
    check("A_clip_mode_sub_visible", probe_cue.text[:4] in clip_text,
          f"expect={probe_cue.text[:12]!r} got={clip_text[:24]!r}")
    # mpv 实际落在源位置（时间域换算正确性）。
    try:
        source_pos = float(page.video.controller.get_property("time-pos", 0.0) or 0.0) * 1000.0
    except Exception:
        source_pos = -1.0
    expected_source = probe_cue.start_ms + 500
    check("A_seek_domain_source_ms",
          abs(source_pos - expected_source) <= 1500,
          f"mpv_pos={source_pos:.0f}ms expect≈{expected_source}ms")
    # 列表/时间轴显示 15 条左右的局部时间。
    check("A_list_shows_view", len(page.timeline._cues_by_start) == len(view),
          f"timeline_index={len(page.timeline._cues_by_start)}")

    # ---------- 返回完整录播 ----------
    page.undo_stack.push(restore_full_sequence_command(project, changed=page._sequence_changed))
    _pump(app, 4.0)
    check("B_restore_full_cues", len(project.cues) == baseline_n, f"n={len(project.cues)}")
    check("B_restore_source_times", min(c.start_ms for c in project.cues) == baseline_first)
    check("B_timeline_duration_full", timeline_duration_ms(project) >= 5_300_000,
          f"tdm={timeline_duration_ms(project)}")
    after_text = seek_and_probe(probe_mid_s, "after_restore", probe_cue.text)
    check("B_sub_visible_after_restore", probe_cue.text[:4] in after_text,
          f"got={after_text[:24]!r}")
    view_after = projected_cues(project, domain="timeline")
    check("B_view_is_full", view_after is project.cues)

    # ---------- C. 10 次往返稳定性 ----------
    stable = True
    for cycle in range(10):
        page.undo_stack.push(generate_edit_command(project, changed=page._sequence_changed))
        page.undo_stack.push(restore_full_sequence_command(project, changed=page._sequence_changed))
        if len(project.cues) != baseline_n or min(c.start_ms for c in project.cues) != baseline_first:
            stable = False
            break
        _pump(app, 0.05)
    check("C_ten_roundtrips_stable", stable, f"cycle={cycle + 1} n={len(project.cues)}")

    # ---------- D. 剪辑态保存 → 重开 → 返回 ----------
    from twobyteasr.studio_project import load_project, save_project
    page.undo_stack.push(generate_edit_command(project, changed=page._sequence_changed))
    _pump(app, 1.0)
    saved = OUT / "saved-in-clip.2byteproj"
    save_project(project, saved)
    loaded = load_project(saved)
    check("D_saved_full_cues", len(loaded.cues) == baseline_n, f"n={len(loaded.cues)}")
    check("D_saved_sequence_clip", len(projected_cues(loaded, domain="timeline")) < baseline_n)
    restore_full_sequence_command(loaded).redo()
    check("D_return_after_reload", projected_cues(loaded, domain="timeline") is loaded.cues)
    page.undo_stack.push(restore_full_sequence_command(project, changed=page._sequence_changed))

    # ---------- F. 导出域一致性 ----------
    from twobyteasr.studio_subtitle_export import _compile_format
    page.undo_stack.push(generate_edit_command(project, changed=page._sequence_changed))
    _pump(app, 0.5)
    srt_clip = _compile_format(project, "srt")
    first_ts = next(line for line in srt_clip.splitlines() if "-->" in line)
    clip_blocks = srt_clip.count("-->")
    page.undo_stack.push(restore_full_sequence_command(project, changed=page._sequence_changed))
    srt_full = _compile_format(project, "srt")
    check("F_export_clip_domain", first_ts.startswith("00:00:0") and clip_blocks == len(view),
          f"first={first_ts.split(' -->')[0]} blocks={clip_blocks}")
    check("F_export_full_domain", srt_full.count("-->") == baseline_n,
          f"blocks={srt_full.count('-->')}")

    # 截图证据
    page.timeline.grab().save(str(OUT / "audit_final_full.png"))
    report["counts"] = {"baseline": baseline_n, "clip_view": len(view)}
    page.close_page()
    (OUT / "clip-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'ALL PASS' if not report['failures'] else 'FAILURES: ' + ', '.join(report['failures'])}")
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
