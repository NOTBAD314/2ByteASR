"""P0-1 回归测试：旧分轨清理不得误删用户文件（ownership 证明制）。

安全不变量：只有同时满足"程序产物命名格式"且"最近一次成功任务报告
证明为本程序生成"的文件才允许在下次生成时被自动清理；无法证明
ownership 的文件一律保留（宁可留下程序旧分轨，不可误删用户文件）。
"""

import json

import pytest

import subtitle_core
from twobyteasr.subtitle_rules import output as output_module
from twobyteasr.recognition import reporting as task_reporting


@pytest.fixture(autouse=True)
def _isolated_project(tmp_path, monkeypatch):
    """把 SCRIPT_DIR 与报告目录都隔离到临时目录，不触碰真实项目数据。"""
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(output_module, "SCRIPT_DIR", str(project_root))
    monkeypatch.setattr(task_reporting, "REPORT_ROOT", project_root / "reports")
    subtitle_core.reset_review_items()


def _write_report(media_stem, speaker_paths, status="success"):
    report_root = task_reporting.REPORT_ROOT
    report_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "result": {
            "outputs": {
                "txt": "",
                "srt": "",
                "speaker_outputs": [
                    ["S01", str(path), 1] for path in speaker_paths
                ],
                "review_path": "",
            }
        },
    }
    (report_root / f"{media_stem}_字幕任务报告.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _run_generation(tmp_path, media_stem="demo", speakers=("S01",)):
    txt_path = str(tmp_path / f"{media_stem}_剪映文稿.txt")
    srt_path = str(tmp_path / f"{media_stem}_剪映文稿.srt")
    cues = [
        subtitle_core.SubtitleCue(index, float(index - 1), float(index), f"内容{index}", speaker=speaker)
        for index, speaker in enumerate(speakers, 1)
    ]
    output_module.write_all_outputs_transactional(
        cues, txt_path, srt_path, include_srt=True
    )
    return srt_path


def test_user_note_without_track_index_is_never_deleted(tmp_path):
    """用户笔记（无数字 index 段）即使前缀匹配也绝不能被清理。"""
    note = tmp_path / "demo_剪映文稿_主播笔记.srt"
    note.write_text("用户笔记", encoding="utf-8")
    _run_generation(tmp_path, speakers=("S01",))
    assert note.is_file(), "用户笔记文件被误删"


def test_user_note_that_mimics_program_format_without_proof_is_kept(tmp_path):
    """用户文件恰好符合程序命名格式但无任务报告证明 → 必须保留。"""
    fake = tmp_path / "demo_剪映文稿_主播1_我的笔记.srt"
    fake.write_text("用户标注", encoding="utf-8")
    _run_generation(tmp_path, speakers=("S01",))
    assert fake.is_file(), "伪装成程序格式的用户文件被误删"


def test_old_program_track_proven_by_report_is_cleaned(tmp_path):
    """最近一次成功报告证明的程序旧分轨 → 仍可被自动清理（功能保留）。"""
    old_track = tmp_path / "demo_剪映文稿_主播1_主播甲.srt"
    old_track.write_text("旧程序产物", encoding="utf-8")
    _write_report("demo", [old_track])
    _run_generation(tmp_path, speakers=("S00",))
    assert not old_track.is_file(), "报告证明的程序旧分轨应被清理"


def test_old_program_track_without_report_is_kept(tmp_path):
    """无任务报告证明的旧分轨 → 宁可留下，不清理。"""
    old_track = tmp_path / "demo_剪映文稿_主播1_主播甲.srt"
    old_track.write_text("旧程序产物", encoding="utf-8")
    _run_generation(tmp_path, speakers=("S02",))
    assert old_track.is_file(), "无 ownership 证明的旧分轨不应被清理"


def test_corrupt_report_disables_cleanup(tmp_path):
    """报告损坏（无法解析）→ 视为无证明，不清理任何旧分轨。"""
    old_track = tmp_path / "demo_剪映文稿_主播1_主播甲.srt"
    old_track.write_text("旧程序产物", encoding="utf-8")
    report_root = tmp_path / "project" / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "demo_字幕任务报告.json").write_text(
        "{corrupt json!!!", encoding="utf-8"
    )
    _run_generation(tmp_path, speakers=("S02",))
    assert old_track.is_file(), "报告损坏时不得清理"


def test_failed_report_does_not_authorize_cleanup(tmp_path):
    """最近一次报告不是 success → 无 ownership 证明，不清理。"""
    old_track = tmp_path / "demo_剪映文稿_主播1_主播甲.srt"
    old_track.write_text("旧程序产物", encoding="utf-8")
    _write_report("demo", [old_track], status="failed")
    _run_generation(tmp_path, speakers=("S02",))
    assert old_track.is_file(), "失败任务的报告不能作为清理依据"


def test_current_run_tracks_are_never_deleted(tmp_path):
    """本次生成的分轨必须保留；上次产物（报告证明）仍被清理。"""
    _run_generation(tmp_path, speakers=("S01", "S02"))
    _write_report(
        "demo",
        [
            tmp_path / "demo_剪映文稿_主播1_S00.srt",
            tmp_path / "demo_剪映文稿_主播2_S01.srt",
        ],
    )
    # New task numbering starts at S00; a migration must retain old exports.
    _run_generation(tmp_path, speakers=("S02",))
    assert (tmp_path / "demo_剪映文稿_主播1_S00.srt").is_file(), "本次分轨被误删"
    assert (tmp_path / "demo_剪映文稿_主播2_S01.srt").is_file(), "命名迁移不应删除旧分轨"


def test_backend_name_migration_retains_existing_export(tmp_path):
    old = tmp_path / 'demo_剪映文稿_主播1_NEMO_01.srt'
    old.write_text('用户旧字幕20 20', encoding='utf8')
    _write_report('demo',[old])
    _run_generation(tmp_path,speakers=('NEMO_01',))
    assert old.read_text('utf8') == '用户旧字幕20 20'
    assert (tmp_path/'demo_剪映文稿_主播1_S00.srt').is_file()
