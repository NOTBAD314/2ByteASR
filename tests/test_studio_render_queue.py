import time

from twobyteasr.exports.studio_render import RenderJob, RenderSettings
from twobyteasr.exports.studio_render_queue import (
    QueuedRenderJob,
    RenderQueueStore,
    StudioRenderQueue,
)


def _job(tmp_path, name="out.mp4"):
    return RenderJob(
        str(tmp_path / "source.mp4"),
        str(tmp_path / "subtitles.ass"),
        str(tmp_path / name),
        RenderSettings(encoder="libx264"),
    )


def test_queue_store_recovers_interrupted_render(tmp_path):
    store = RenderQueueStore(tmp_path / "queue.json")
    item = QueuedRenderJob(_job(tmp_path), status="Rendering")
    store.save([item])
    recovered = store.load()
    assert recovered[0].status == "Queued"
    assert "Recovered" in recovered[0].error


def test_queue_runs_jobs_in_order_and_persists_status(tmp_path):
    seen = []

    def runner(_ffmpeg, job, *, progress, cancelled):
        assert not cancelled()
        seen.append(job.output_path)
        progress({"out_time": "00:00:01.000000"})

    store = RenderQueueStore(tmp_path / "queue.json")
    queue = StudioRenderQueue(tmp_path / "ffmpeg.exe", store=store, runner=runner)
    first = queue.enqueue(_job(tmp_path, "one.mp4"))
    second = queue.enqueue(_job(tmp_path, "two.mp4"))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        jobs = queue.jobs()
        if all(item.status == "Completed" for item in jobs):
            break
        time.sleep(0.01)
    queue.stop()
    jobs = store.load()
    assert [item.status for item in jobs] == ["Completed", "Completed"]
    assert [item.id for item in jobs] == [first.id, second.id]
    assert seen == [str(tmp_path / "one.mp4"), str(tmp_path / "two.mp4")]
    assert jobs[0].progress["out_time"] == "00:00:01.000000"


def test_queue_records_failure_and_continues(tmp_path):
    def runner(_ffmpeg, job, **_kwargs):
        if job.output_path.endswith("bad.mp4"):
            raise RuntimeError("encoder failed")

    store = RenderQueueStore(tmp_path / "queue.json")
    queue = StudioRenderQueue(tmp_path / "ffmpeg.exe", store=store, runner=runner)
    queue.enqueue(_job(tmp_path, "bad.mp4"))
    queue.enqueue(_job(tmp_path, "good.mp4"))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        jobs = queue.jobs()
        if not any(item.status in {"Queued", "Rendering"} for item in jobs):
            break
        time.sleep(0.01)
    queue.stop()
    jobs = store.load()
    assert jobs[0].status == "Failed"
    assert jobs[0].error == "encoder failed"
    assert jobs[1].status == "Completed"
