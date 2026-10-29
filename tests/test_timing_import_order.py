"""Regression test for the launcher import-order NameError.

``timing.py`` uses three symbols that are only published onto
``subtitle_core`` by the *tail backfill* of ``segmentation.py`` /
``segmentation_alignment.py`` (``firered_token_start``,
``segment_content_timeline``, ``locally_repair_resegmented_cue``).

Under the launcher entry order (``import moss_firered_pipeline`` first),
``twobyteasr.subtitle_rules.timing`` is imported before that backfill runs, so a plain
``from subtitle_core import *`` leak is missing and the first call raises
``NameError``.  The module now resolves them via deferred imports; these
tests exercise the real call paths in an isolated process so the module
import order cannot be polluted by earlier tests.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHECK_SCRIPT = (
    "import moss_firered_pipeline\n"
    "from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue\n"
    "import twobyteasr.subtitle_rules.timing as timing\n"
    "seg = SpeechSegment(segment_id=1, start=1.0, end=2.0, text='测试',"
    " confidence=0.9, words=[])\n"
    "tokens = [{'start': 1.1, 'end': 1.9, 'text': '测试'}]\n"
    "assert timing.firered_anchor_coverage(seg, tokens)\n"
    "# 超限素材强制走 segment_content_timeline / locally_repair_resegmented_cue 分支\n"
    "long_seg = SpeechSegment(segment_id=2, start=1.0, end=30.0,"
    " text='这是一句非常长的超限测试字幕内容' * 4, confidence=0.9, words=[])\n"
    "cues = timing.build_local_source_cues([long_seg], tokens)\n"
    "assert cues, '超限素材应触发本地重建路径'\n"
    "cue = SubtitleCue(cue_id=1, start=1.0, end=30.0,"
    " text='这是一句非常长的超限测试字幕内容' * 4)\n"
    "repaired = timing.repair_overlong_cues_from_source([cue], [long_seg], tokens)\n"
    "assert repaired\n"
    "print('TIMING_IMPORT_ORDER_OK')\n"
)


def test_timing_symbols_resolve_under_launcher_import_order():
    completed = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "TIMING_IMPORT_ORDER_OK" in completed.stdout
