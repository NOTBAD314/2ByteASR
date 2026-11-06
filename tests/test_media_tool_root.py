"""The metadata worker must probe using the same installed tools as exports."""
from twobyteasr.media.media_service import MediaService
from twobyteasr.system.platform_media import executable_name


def test_metadata_honours_install_root_and_explicit_override(tmp_path, monkeypatch):
    installed = tmp_path/'installed'
    tools = installed/'tools/ffmpeg/bin'; tools.mkdir(parents=True)
    probe = tools/executable_name('ffprobe'); probe.write_bytes(b'probe fixture')
    monkeypatch.setenv('2BYTEASR_INSTALL_ROOT', str(installed))
    from twobyteasr import runtime_paths
    monkeypatch.setattr(runtime_paths, '_CACHE', None)
    service = MediaService(cache_root=tmp_path/'cache')
    assert service.ffprobe_path == probe
    assert service.ffmpeg_path == tools/executable_name('ffmpeg')
    override = tmp_path/'explicit-probe'
    explicit = MediaService(ffprobe_path=override, ffmpeg_path=tmp_path/'explicit-ffmpeg', cache_root=tmp_path/'cache2')
    assert explicit.ffprobe_path == override
    assert explicit.ffmpeg_path == tmp_path/'explicit-ffmpeg'
