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


# ---- the tutorial project (2026-10-14) ----------------------------------------------------
# What the first-run tutorial works on: the same silent video, with lines that
# have something to teach. Three 原神 spellings the built-in library confirms
# (至东→至冬, 凯瑞亚→坎瑞亚, 阿雷奇诺→阿蕾奇诺), a name only the (pretend) AI
# check finds (派门→派蒙, twice, also good for batch replace), and a first line
# on which the three recognizers disagree, so review mode shows three choices.
TUTORIAL_VERSION = 1
TUTORIAL_NAME = '兔白字幕教学'
TUTORIAL_LIBRARY = '原神'
TUTORIAL_AI_FIXES = (('派门', '派蒙'),)


def tutorial_root() -> Path:
    from .runtime_paths import user_data_root
    return Path(user_data_root()) / 'samples' / f'tutorial-v{TUTORIAL_VERSION}'


def tutorial_project_path() -> Path:
    from .studio_project import PROJECT_SUFFIX
    return tutorial_root() / f'{TUTORIAL_NAME}{PROJECT_SUFFIX}'


def _tutorial_rows() -> list[tuple[float, float, str, str, str, str]]:
    """(start, end, speaker, MOSS text, FireRed text, Qwen text); the MOSS text is the subtitle."""
    same = lambda text: (text, text, text)  # noqa: E731
    return [
        (0.4, 3.0, 'S00', '虚迷的风景真好看', '须弥的风景真好看', '须迷的风景真好看'),
        (3.2, 6.0, 'S01', *same('听说至东那边下了很大的雪')),
        (6.2, 9.0, 'S00', *same('凯瑞亚的故事我还没看完')),
        (9.2, 12.0, 'S01', *same('阿雷奇诺这次登场好帅')),
        (12.2, 15.0, 'S00', *same('派门又在旁边说个不停')),
        (15.2, 18.0, 'S01', *same('这期纪行的奖励还挺划算')),
        (18.2, 21.0, 'S00', *same('下次带派门一起去探险')),
        (21.2, 23.6, 'S01', *same('好啊，记得叫上我')),
    ]


def ensure_tutorial_project() -> Path:
    """A fresh tutorial project every time (what the last tutorial changed never sticks)."""
    from .studio_project import project_from_runtime_cues, save_project
    root = tutorial_root()
    root.mkdir(parents=True, exist_ok=True)
    media = root / '教学影片.mp4'
    if not media.is_file():
        example = sample_root() / '范例影片.mp4'
        if example.is_file():
            import shutil
            shutil.copyfile(example, media)
        else:
            _make_video(media)
    rows = _tutorial_rows()
    cues = [SimpleNamespace(cue_id=f'tutorial-{index}', start=start, end=end, speaker=speaker, text=moss)
            for index, (start, end, speaker, moss, _firered, _qwen) in enumerate(rows, 1)]
    evidence = {f'segment:{index}': {
        'start_ms': round(start * 1000), 'end_ms': round(end * 1000), 'text': moss, 'speaker_id': speaker,
        'primary_source': 'moss', 'moss_text': moss, 'firered_text': firered, 'qwen_asr_text': qwen, 'qwen_text': qwen,
        'final_text': moss, 'final_text_owner': 'MOSS', 'final_timing_owner': 'MOSS',
    } for index, (start, end, speaker, moss, firered, qwen) in enumerate(rows, 1)}
    project = project_from_runtime_cues(media, cues, asr_evidence=evidence, generation_metadata={
        'sample_project': {'version': TUTORIAL_VERSION, 'tutorial': True,
                           'note': '新手教学用的示意工程：没有真实对白，三份识别结果是为演示写好的。'},
        'language': {'code': 'zh', 'requested': 'zh', 'evidence': {}},
    })
    names = {'S00': '主播', 'S01': '嘉宾'}
    for speaker in project.speakers:
        speaker.name = names.get(speaker.id, speaker.name)
    project.media.display_name = TUTORIAL_NAME
    if not project.media.duration_ms:
        project.media.duration_ms = SAMPLE_SECONDS * 1000
    project.validate()
    path = tutorial_project_path()
    discard_tutorial_autosave()   # an autosave of the last tutorial would offer to "recover" demo edits
    for file in (path, path.with_name(path.name + '.bak')):
        try:
            file.unlink()
        except FileNotFoundError:
            pass
    return save_project(project, path)


def discard_tutorial_autosave() -> int:
    """Remove the workbench's autosaves of the tutorial project (demo edits are never recovered)."""
    removed = 0
    try:
        from .studio_project import _autosave_path_for_identity
        autosave = _autosave_path_for_identity('', tutorial_project_path())
        for file in autosave.parent.glob(autosave.stem + '*'):
            try:
                file.unlink()
                removed += 1
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return removed


def tutorial_ai_preview(project, cue_ids, snapshot, settings, *, cancel_token=None, progress=None):
    """'AI 校对' in the tutorial: the real offline check plus the names an AI would catch.

    Nothing is sent anywhere; the extra suggestions are marked as AI results so
    the page shows them the way a real AI answer looks.
    """
    import time
    from .studio_glossary_service import GlossaryReviewPreview, preview_glossary_correction
    from .studio_text_tools import TextOccurrence
    local = preview_glossary_correction(project, cue_ids, snapshot, settings, cancel_token=cancel_token, use_ai=False)
    wanted = set(cue_ids or ())
    extra = []
    for cue in project.cues:
        if wanted and cue.id not in wanted:
            continue
        for wrong, right in TUTORIAL_AI_FIXES:
            at = cue.text.find(wrong)
            if at >= 0:
                extra.append(TextOccurrence(cue.id, cue.start_ms, wrong, right, (at, at + len(wrong)),
                                            reason='AI 校对建议（新手教学演示）', confidence=0.9,
                                            default_selected=True, source='ai_accepted'))
    time.sleep(0.6)  # the moment a real request would take; nothing is uploaded
    receipt = dict(local.receipt)
    receipt.update(successful_cues=len(wanted or project.cues), fallback_cues=0, tutorial=True)
    return GlossaryReviewPreview(tuple(local.hits) + tuple(extra), receipt)


def is_sample_project(project) -> bool:
    metadata = getattr(project, 'generation_metadata', None) or {}
    return isinstance(metadata, dict) and isinstance(metadata.get('sample_project'), dict)
