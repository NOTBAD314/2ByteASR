import subtitle_core as core
import pytest

from twobyteasr.recognition.grouping_checkpoint import load, save
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.service import RunOptions
from twobyteasr.recognition.task_journal import TaskJournal
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules.grouping_contract import GroupingContractError, attach_grouping_spans
from twobyteasr.subtitle_rules.grouping_quality import cues_from_quality
from twobyteasr.subtitle_rules.text_rules import display_length


def sources():
    return [
        SpeechSegment(37, 1.0, 2.0, "不够差了5", 1.0, [], "S00"),
        SpeechSegment(38, 2.2, 3.5, "<sil>看它是", 1.0, [], "S01"),
        SpeechSegment(39, 3.7, 4.9, "<正文>还是这边", 1.0, [], "S01"),
    ]


def test_source_local_angle_brackets_and_exact_raw_spans():
    rows = sources()
    offsets = [sum(display_length(row.text) for row in rows[:i]) for i in range(1, 4)]
    with activate_runtime_context(RuntimeContext(task_language="zh"), legacy=core):
        cues, _, _ = cues_from_quality(rows, offsets, repair=False)
        attach_grouping_spans(rows, cues)
        assert [(c.text, c.speaker) for c in cues] == [(r.text, r.speaker) for r in rows]
        assert [c.source_spans[0]["source_id"] for c in cues] == [37, 38, 39]
        assert [c.source_spans[0]["raw_text"] for c in cues] == [r.text for r in rows]
        assert all(row.start <= cue.start < cue.end <= row.end for row, cue in zip(rows, cues))
        with pytest.raises(GroupingContractError, match="递增"):
            cues_from_quality(rows, [0, offsets[-1]], repair=False)


def test_checkpoint_atomic_write_keeps_previous_draft(tmp_path, monkeypatch):
    from pathlib import Path

    journal = TaskJournal("grouping-recovery", tmp_path).create([], RunOptions())
    ctx = RuntimeContext(job_id=journal.job_id, task_language="zh", resume=True,
                         task_journal=journal, media_identity={"fingerprint": "input"})
    cache = {"identity": ctx.media_identity}
    rows = sources()
    options = dict(seconds=5, fps=30, stage=9, use_ai=True, cache_context=cache)
    save(ctx, core, rows, [], [], **options)
    original = load(ctx, cache_context=cache)
    assert original["state"] == "pre_grouping_draft"
    replace = Path.replace

    def fail_artifact(path, target):
        if Path(target).parent.name == "artifacts":
            raise OSError("injected interrupted save")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_artifact)
    rows[0].text = "不能提交的草稿"
    with pytest.raises(OSError, match="interrupted save"):
        save(ctx, core, rows, [], [], **options)
    assert load(ctx, cache_context=cache) == original
    with pytest.raises(ValueError, match="不相符"):
        load(ctx, cache_context={"identity": {"fingerprint": "other input"}})
