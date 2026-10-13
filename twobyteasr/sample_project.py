"""A small example project to try the workbench without models or API keys (2026-10-13).

The example is generated on first use into the user data folder: a 24-second
illustration video made by the bundled FFmpeg (a colour field with a moving
light, silent audio; no speech) and eight subtitles from two speakers that
explain what to try. Nothing is recognized, uploaded or billed; opening it
never starts a model or a cloud service. Deleting the folder is safe, it is
recreated on demand.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

SAMPLE_VERSION = 1
SAMPLE_SECONDS = 24
PROJECT_NAME = '兔白字幕范例'


def sample_root() -> Path:
    from .runtime_paths import user_data_root
    return Path(user_data_root()) / 'samples' / f'example-v{SAMPLE_VERSION}'


def sample_project_path() -> Path:
    from .studio_project import PROJECT_SUFFIX
    return sample_root() / f'{PROJECT_NAME}{PROJECT_SUFFIX}'


def _cue_rows(keys: dict) -> list[tuple[float, float, str, str]]:
    def key(action_id, fallback):
        return keys.get(action_id) or fallback

    return [
        (0.4, 3.0, 'S00', '这是兔白字幕的范例工程：画面是示意影片，没有真实对白。'),
        (3.2, 6.0, 'S00', '在左侧字幕列表里直接改字，改错了按 {undo} 撤销。'.format(undo=key('undo', 'Ctrl+Z'))),
        (6.2, 9.0, 'S01', '拖动时间轴上字幕块的边缘，可以调整出现和消失的时间。'),
        (9.2, 12.0, 'S00', '按 {play} 播放；{q} / {w} 把字幕起点或终点对齐到播放头。'.format(
            play=key('play_pause', 'Space'), q=key('trim_start', 'Q'), w=key('trim_end', 'W'))),
        (12.2, 15.0, 'S01', '不同说话人用不同颜色，在“说话人管理”里可以改名字。'),
        (15.2, 18.0, 'S00', '工具栏的“标点”可以切换添加标点或不加标点，导出会跟着变。'),
        (18.2, 21.0, 'S01', '试试“导出字幕”：SRT、ASS、TXT 都在本机完成，不上传任何东西。'),
        (21.2, 23.6, 'S00', '准备好了就回到首页，选择你自己的影片开始生成字幕。'),
    ]


def _make_video(target: Path) -> None:
    """Silent illustration video (no speech, no third-party footage)."""
    from .studio_video_track import ffmpeg_executable
    ffmpeg = ffmpeg_executable()
    if not ffmpeg.is_file():
        import shutil
        found = shutil.which('ffmpeg')
        if not found:
            raise RuntimeError('找不到随程序附带的 FFmpeg，无法生成范例影片。')
        ffmpeg = Path(found)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + '.part' + target.suffix)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    # A slowly moving colour gradient; a plain colour field if this FFmpeg
    # build lacks the gradients source.
    sources = (f'gradients=s=1280x720:r=30:d={SAMPLE_SECONDS}:c0=0x1d2b45:c1=0x3a5a8c:c2=0x24324f:'
               'n=3:speed=0.015,format=yuv420p',
               f'color=c=0x1d2b45:s=1280x720:r=30:d={SAMPLE_SECONDS},format=yuv420p')
    result = None
    for video in sources:
        command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y',
                   '-f', 'lavfi', '-i', video,
                   '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={SAMPLE_SECONDS}',
                   '-shortest', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', '-b:a', '48k', '-movflags', '+faststart', str(temporary)]
        result = subprocess.run(command, capture_output=True, timeout=120, creationflags=flags)
        if result.returncode == 0 and temporary.is_file():
            temporary.replace(target)
            return
    detail = result.stderr.decode('utf-8', 'replace')[-300:] if result is not None else ''
    raise RuntimeError(f'生成范例影片失败：{detail}')


def ensure_sample_project(*, rebuild: bool = False) -> Path:
    """Path of the example project, creating it (and its video) when missing."""
    from .studio_project import load_project, project_from_runtime_cues, save_project
    path = sample_project_path()
    if path.is_file() and not rebuild:
        try:
            load_project(path)
            return path
        except Exception:
            pass  # damaged: rebuild below
    root = sample_root()
    root.mkdir(parents=True, exist_ok=True)
    media = root / '范例影片.mp4'
    if rebuild or not media.is_file():
        _make_video(media)
    try:
        from .shortcut_registry import current_values, display
        keys = {key: display(value) for key, value in current_values().items() if value}
    except Exception:
        keys = {}
    cues = [SimpleNamespace(cue_id=f'sample-{index}', start=start, end=end, speaker=speaker, text=text)
            for index, (start, end, speaker, text) in enumerate(_cue_rows(keys), 1)]
    project = project_from_runtime_cues(media, cues, generation_metadata={
        'sample_project': {'version': SAMPLE_VERSION, 'note': '范例工程：示意影片与说明字幕，未经识别，不含真实对白。'},
        'language': {'code': 'zh', 'requested': 'zh', 'evidence': {}},
    })
    names = {'S00': '旁白', 'S01': '嘉宾'}
    for speaker in project.speakers:
        speaker.name = names.get(speaker.id, speaker.name)
    project.media.display_name = PROJECT_NAME
    if not project.media.duration_ms:
        project.media.duration_ms = SAMPLE_SECONDS * 1000  # our own video; a missing probe cannot hide its length
    project.validate()
    return save_project(project, path)


def is_sample_project(project) -> bool:
    metadata = getattr(project, 'generation_metadata', None) or {}
    return isinstance(metadata, dict) and isinstance(metadata.get('sample_project'), dict)
