"""The metadata worker must probe using the same installed tools as exports."""
import ast
import copy
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize('windows', [False, True])
def test_waveform_worker_uses_installed_platform_tool(tmp_path, monkeypatch, windows):
    from twobyteasr.system import platform_media
    from twobyteasr.system.resource_governor import ResourceKind
    installed = tmp_path/'installed'
    monkeypatch.setenv('2BYTEASR_INSTALL_ROOT', str(installed))
    monkeypatch.setattr(platform_media, 'executable_name',
                        lambda name: executable_name(name, windows=windows))
    code = Path(__file__).parents[1]/'twobyteasr/studio/studio_media_flow.py'
    tree = ast.parse(code.read_text('utf8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == 'StudioMediaFlowMixin')
    method = copy.deepcopy(next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                                and node.name == '_generate_waveform'))
    method.decorator_list = []
    calls, failures, active = [], [], [None]

    class Worker:
        def __init__(self, *, target, **kwargs):
            self.target = target
            active[0] = self

        def start(self):
            self.target()

    namespace = dict(__package__='twobyteasr.studio', __file__=str(tmp_path/'unrelated/twobyteasr/studio/media.py'),
        Path=Path, ResourceKind=ResourceKind,
        threading=SimpleNamespace(Event=threading.Event, Thread=Worker, current_thread=lambda: active[0]),
        split_waveform_job=lambda path: (path, 0), waveform_job=lambda path, stream: path,
        stream_time_mapping=lambda *args: {},
        generate_progressive_waveform_cache=lambda media, tool, **kwargs: calls.append(Path(tool)))
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        ast.ClassDef(name='Harness', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(code), 'exec'), namespace)
    page = namespace['Harness']()
    page.timeline = SimpleNamespace(waveform_cache_for_source=lambda *args: None,
                                    set_waveform_state=lambda *args: None)
    page.project = None
    page._waveform_inflight_lock = threading.Lock()
    page._waveform_inflight, page._waveform_threads = set(), set()
    page._waveform_cancel_event = threading.Event()
    page._waveform_generation = 0
    page._studio_mark_startup_milestone = lambda *args, **kwargs: None
    page._queue_startup_milestone = lambda *args, **kwargs: None
    page._resource_governor = SimpleNamespace(wait_until_allowed=lambda *args, **kwargs: True)
    page.waveform_failed_signal = SimpleNamespace(emit=lambda *args: failures.append(args))
    page._generate_waveform(str(tmp_path/'source.mp4'))
    assert not failures
    assert calls == [installed/'tools/ffmpeg/bin'/executable_name('ffmpeg', windows=windows)]
    assert not page._waveform_inflight and not page._waveform_threads
