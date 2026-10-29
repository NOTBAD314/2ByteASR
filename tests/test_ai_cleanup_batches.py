"""AI 清理 on a long project (2026-10-26, user: 全工程 stopped with "模型结构化输出
达到长度上限"): the whole scope goes out in small batches, an overflowing batch is
halved and asked again, and a failure keeps what earlier batches found."""
import json
import threading

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.providers.llm_adapter import LLMRequestError
from twobyteasr.studio import studio_text_tools as tools


def project(count):
    cues = [StudioCue(f"c{i}", i * 2000, i * 2000 + 1500, f"um this is line {i} um", original_text="",
                      speaker_id="S01") for i in range(count)]
    value = SubtitleProject(media=StudioMedia(path="isolated.mp4"), cues=cues)
    value.validate()
    return value


class Provider:
    """Answers every caption with "um" removed; overflows above ``limit`` captions."""

    def __init__(self, limit=None, fail_on=None):
        self.limit, self.fail_on = limit, fail_on
        self.sizes = []
        self.lock = threading.Lock()

    def complete(self, messages, **_kwargs):
        cues = json.loads(messages[1]["content"])["cues"]
        with self.lock:
            self.sizes.append(len(cues))
        if self.fail_on and any(cue["cue_id"] == self.fail_on for cue in cues):
            raise LLMRequestError("服务暂时不可用", category="server_error")
        if self.limit and len(cues) > self.limit:
            raise LLMRequestError("模型结构化输出达到长度上限，当前结果不完整。", category="structured_output_truncated")
        return json.dumps({"changes": [{"cue_id": cue["cue_id"], "original": cue["text"],
                                        "replacement": cue["text"].replace("um ", "").replace(" um", ""),
                                        "reason": "口癖"} for cue in cues]})


def use(monkeypatch, provider):
    import twobyteasr.providers.ai_providers as providers
    monkeypatch.setattr(providers, "provider_for_stage", lambda *_a, **_k: provider)


def test_every_caption_is_covered_in_small_batches(monkeypatch):
    value = project(100)
    provider = Provider()
    use(monkeypatch, provider)
    seen = []
    result = tools.request_text_cleanup(value, [c.id for c in value.cues], ["fillers"], {"models": {"polish": {}}},
                                        progress=seen.append)
    assert [hit.cue_id for hit in result] == [c.id for c in value.cues]       # all 100, in order
    assert max(provider.sizes) <= tools.CLEANUP_BATCH_CUES and result.batches == len(provider.sizes)
    assert seen[-1] == dict(done=result.batches, total=result.batches, found=100)
    assert not result.error


def test_an_overflowing_batch_is_halved_and_asked_again(monkeypatch):
    value = project(30)
    provider = Provider(limit=5)
    use(monkeypatch, provider)
    result = tools.request_text_cleanup(value, [c.id for c in value.cues], ["fillers"], {"models": {"polish": {}}})
    assert len(result) == 30 and not result.error and result.skipped == 0
    # Overflowing batches were asked again in halves; the answered calls cover each caption once.
    assert any(size > 5 for size in provider.sizes)
    assert sum(size for size in provider.sizes if size <= 5) == 30


def test_a_failed_batch_keeps_the_suggestions_already_found(monkeypatch):
    value = project(60)
    provider = Provider(fail_on="c55")
    use(monkeypatch, provider)
    result = tools.request_text_cleanup(value, [c.id for c in value.cues], ["fillers"], {"models": {"polish": {}}},
                                        parallel=1)
    assert result.error and "服务暂时不可用" in result.error
    assert 0 < len(result) < 60 and result.done < result.batches
    assert all(hit.replacement.startswith("this is line") for hit in result)


def test_batches_follow_caption_count_and_length():
    long = [StudioCue(f"l{i}", i * 1000, i * 1000 + 900, "字" * 500) for i in range(5)]
    assert [len(batch) for batch in tools.cleanup_batches(long)] == [2, 2, 1]
    short = [StudioCue(f"s{i}", i * 1000, i * 1000 + 900, "hi") for i in range(50)]
    assert [len(batch) for batch in tools.cleanup_batches(short)] == [24, 24, 2]
