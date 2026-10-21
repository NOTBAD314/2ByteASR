from twobyteasr.exports.studio_render import RenderJob, RenderSettings
from twobyteasr.exports.studio_render_queue import StudioRenderQueue, RenderQueueStore, QueuedRenderJob


def test_enqueued_settings_graph_context_and_project_are_owned_copies(tmp_path, monkeypatch):
    queue = StudioRenderQueue(str(tmp_path/'ffmpeg.exe'), store=RenderQueueStore(tmp_path/'queue.json'))
    monkeypatch.setattr(queue, '_ensure_worker_locked', lambda:None)
    job = RenderJob('', '', 'out.mp4', RenderSettings(quality_mode='target', bitrate_kbps=10000),
        video_graph={'clips':[{'path':'first.mp4'}]}, export_project_data={'cues':[{'text':'first'}]},
        export_context={'job_id':'frozen', 'project_revision':'sha256:first', 'requested_encoder':'auto'})
    queued = queue.enqueue(job)
    job.settings.bitrate_kbps = 5000
    job.video_graph['clips'][0]['path'] = 'changed.mp4'
    job.export_project_data['cues'][0]['text'] = 'changed'
    job.export_context['project_revision'] = 'changed'
    saved = queue.jobs()[0]
    assert saved.job.settings.bitrate_kbps == queued.job.settings.bitrate_kbps == 10000
    assert saved.job.video_graph['clips'][0]['path'] == 'first.mp4'
    assert saved.job.export_project_data['cues'][0]['text'] == 'first'
    assert saved.job.export_context['project_revision'] == 'sha256:first'
    assert queue.store.load()[0].job.export_context['job_id'] == 'frozen'


def test_old_queue_payload_has_default_optional_export_context():
    queued = QueuedRenderJob.from_dict({'job':dict(media_path='',ass_path='',output_path='',settings={})})
    assert queued.job.export_context == {}


def test_queue_discards_qobject_bound_preview_before_copying_owned_fields(tmp_path, monkeypatch):
    from PySide6.QtCore import QObject
    class PreviewOwner(QObject):
        def receive(self, *args): pass
    owner = PreviewOwner()
    queue = StudioRenderQueue(str(tmp_path/'ffmpeg.exe'), store=RenderQueueStore(tmp_path/'queue.json'))
    monkeypatch.setattr(queue, '_ensure_worker_locked', lambda:None)
    job = RenderJob('', '', 'out.mp4', preview_callback=owner.receive, preview_url='tcp://preview',
        completion_metadata={'stale':True})
    frozen = queue.enqueue(job)
    assert frozen.job.preview_callback is None
    assert frozen.job.preview_url == ''
    assert frozen.job.completion_metadata == {}
    assert job.preview_callback.__self__ is owner
