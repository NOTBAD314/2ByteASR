"""Background-music lyrics recognized as subtitles go to a hidden speaker (2026-11-22).

User (1 h 洛克王国 stream): the recognizer wrote the songs playing behind the
streamer into the subtitles (今晚可将你未来交给我么, 最美的相遇, 像雨滴 渗入我,
feel it in my body …), and they had to be deleted by hand.

After the final caption text is fixed, the grouping model reads the captions
with their start times and lists the lines sung by a song rather than spoken.
It reads twice, the second time with batches shifted by half, and a line is
lyrics when both readings say so, or when one does and it sits next to a line
both chose. Paid run on that job: 38 lines chosen by both readings, all of
them song lyrics; a few lyric lines were missed, no speech was taken.

Nothing is deleted. The new project puts those captions on their own speaker
「背景歌词」, hidden: the editor still shows them, preview and every export leave
them out, and showing the speaker again brings them back.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

PROMPT_VERSION = 'background-lyrics-v1'
SPEAKER_ID = 'BACKGROUND_LYRICS'
SPEAKER_NAME = '背景歌词'
METADATA_KEY = 'background_lyrics'
BATCH = 80
NEIGHBOUR_SECONDS = 8.

SYSTEM = (
    "下面是一段直播视频的字幕，每行带开始秒数。直播时常放背景音乐，语音识别会把歌曲的歌词也写成字幕。"
    "找出哪些行是背景音乐里的歌词：是歌手在唱，不是主播或连麦的人在说话。"
    "歌词的特点：书面、抒情或押韵的句子，和前后的对话、游戏内容无关，常常几行连在一起，也可能是外语。"
    "主播说话、念游戏里的技能或角色名、读弹幕、跟着哼一两个字都不算歌词。不确定就不要选。"
    '只输出JSON对象{"lyrics":[行号,...]}，没有就给空数组；无Markdown或解释。')
SCHEMA = {'type': 'object', 'properties': {'lyrics': {'type': 'array', 'items': {'type': 'integer'}}},
          'required': ['lyrics']}


def _ask(provider, snapshot, rows, cancel_check):
    body = dict(prompt_version=PROMPT_VERSION, lines=[dict(id=i, t=round(start, 1), text=text)
                                                      for i, start, text in rows])
    messages = [dict(role='system', content=SYSTEM),
                dict(role='user', content=json.dumps(body, ensure_ascii=False, separators=(',', ':')))]
    response = provider.complete(messages, stage='grouped', operation_kind='group', batch_index='lyrics',
                                 max_tokens=2048, temperature=0., timeout=snapshot.timeout_policy.total,
                                 _timeout_policy=snapshot.timeout_policy, cancel_check=cancel_check,
                                 enable_thinking=False, thinking_protocol=snapshot.thinking_protocol,
                                 response_format={'type': 'json_object'}, json_schema=SCHEMA,
                                 structured_retry_system_prompt=None, structured_retry_max_tokens=())
    raw = str(response or '').strip()
    if raw.startswith('```'):
        raw = '\n'.join(raw.splitlines()[1:-1])
    ids = {i for i, _s, _t in rows}
    return {int(x) for x in json.loads(raw).get('lyrics', ()) if str(x).isdigit() and int(x) in ids}


def classify(lines, snapshot, *, provider, cancel_check=lambda: False):
    """Indices of lyric lines among ``lines`` = [(start_seconds, text)]; None when a request failed."""
    rows = [(i, float(start), str(text).strip()) for i, (start, text) in enumerate(lines)]
    if not rows:
        return set()

    def reading(offset):
        starts = range(-offset, len(rows), BATCH)
        chunks = [rows[max(0, s):s+BATCH] for s in starts if rows[max(0, s):s+BATCH]]
        with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as pool:
            found = set()
            for got in pool.map(lambda chunk: _ask(provider, snapshot, chunk, cancel_check), chunks):
                found |= got
        return found

    first, second = reading(0), reading(BATCH // 2)
    both = first & second
    single = (first | second) - both
    chosen = set(both)
    for i in single:
        if any(j in both and abs(rows[j][1]-rows[i][1]) <= NEIGHBOUR_SECONDS for j in (i-1, i+1)):
            chosen.add(i)
    return chosen


def mark_background_lyrics(cues, runtime_context, legacy):
    """Classify the delivered cues; the result goes into the new project's metadata."""
    from .service import CancelledError

    snapshot = getattr(runtime_context, 'provider_snapshot', None)
    language = str(getattr(runtime_context, 'task_language', '') or '')
    switches = (getattr(runtime_context, 'asr_settings_snapshot', None) or {}).get('switches') or {}
    if (snapshot is None or not cues or language.split('-')[0] != 'zh'
            or not switches.get('use_ai_grouping', False) or switches.get('background_lyrics') is False
            or str(getattr(runtime_context, 'recognition_purpose', 'final') or 'final') == 'analysis'):
        return None
    from ..providers.ai_providers import provider_for_stage
    from ..providers.llm_adapter import post_chat_completion
    try:
        provider = provider_for_stage(snapshot.execution_settings(), 'group', sender=post_chat_completion)
        token = getattr(runtime_context, 'cancellation_token', None)
        chosen = classify([(c.start, c.text) for c in cues], snapshot, provider=provider,
                          cancel_check=lambda: bool(getattr(token, 'is_cancelled', False)))
    except CancelledError:
        raise
    except Exception as exc:  # captions stay where they are
        legacy.record_run_event('background_lyrics_failed', error=str(exc)[:200])
        return None
    lines = [dict(start_ms=round(float(cues[i].start)*1000), end_ms=round(float(cues[i].end)*1000),
                  text=str(cues[i].text)) for i in sorted(chosen)]
    metadata = dict(version=PROMPT_VERSION, speaker_id=SPEAKER_ID, lines=lines)
    legacy.record_run_event('background_lyrics', prompt_version=PROMPT_VERSION, cues=len(cues), lyrics=len(lines))
    if lines:
        legacy.add_review_item(lines[0]['start_ms']/1000, '背景歌词已隐藏',
                               f'{len(lines)} 行判断为背景音乐歌词，放在隐藏的「{SPEAKER_NAME}」说话人里；'
                               '工作台的说话人管理里显示它就会回到字幕。',
                               priority=1, severity='info')
    return metadata


def apply_to_project(project):
    """Move the classified captions of a new project to the hidden lyrics speaker."""
    metadata = (project.generation_metadata or {}).get(METADATA_KEY) or {}
    wanted = {(row.get('start_ms'), row.get('end_ms'), row.get('text')) for row in metadata.get('lines', ())}
    if not wanted:
        return 0
    from ..projects.studio_project import StudioSpeaker
    moved = 0
    for cue in project.cues:
        if (cue.start_ms, cue.end_ms, cue.text) in wanted and cue.speaker_id != SPEAKER_ID:
            cue.speaker_id = SPEAKER_ID
            moved += 1
    if moved and SPEAKER_ID not in {s.id for s in project.speakers}:
        style = project.speakers[0].style_id if project.speakers else 'default'
        project.speakers.append(StudioSpeaker(SPEAKER_ID, name=SPEAKER_NAME, style_id=style, hidden=True))
    metadata['moved_cues'] = moved
    return moved
