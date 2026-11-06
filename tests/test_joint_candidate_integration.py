"""Auto routing must retain the video-pipeline's native partition/recovery path."""
import pytest
from twobyteasr.exports.studio_render import RenderJob,RenderSettings
from twobyteasr.exports import parallel_video_export as parallel

def test_auto_selected_two_sessions_reaches_native_partitioner(monkeypatch,tmp_path):
    source=tmp_path/'source.mp4';source.write_bytes(b'owned fixture')
    job=RenderJob(str(source),'',str(tmp_path/'out.mp4'),
        RenderSettings(encoder='h264_nvenc',fps=60),duration_seconds=180,
        export_context={'parallel_segments':0,'parallel_decision':{'segments':2,'reason':'automatic verified route'},'expected_output_audio':False})
    observed=[]
    class ReachedPartitioner(Exception):pass
    def partition(duration,rate,segments):
        observed.append((duration,float(rate),segments));raise ReachedPartitioner
    monkeypatch.setattr(parallel,'frame_partitions',partition)
    with pytest.raises(ReachedPartitioner):parallel.render_parallel_native('ffmpeg',job)
    assert observed==[(180,60.,2)]
