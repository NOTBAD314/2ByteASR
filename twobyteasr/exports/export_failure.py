"""Small, bounded failure evidence, separate from FFmpeg progress and full logs."""
from collections import deque
import re


_ERROR = re.compile(
    r'error|failed|invalid|no space left|permission denied|access is denied|'
    r'cannot |could not |out of memory|not supported|no capable devices|'
    r'device lost|device removed|broken pipe|non.monoton', re.I)
_GENERIC = re.compile(r'^(conversion failed!?|error while processing the decoded data.*)$', re.I)
_PROGRESS = re.compile(r'^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time_us|'
                       r'out_time_ms|out_time|dup_frames|drop_frames|speed|progress)=')


class ProcessEvidence(str):
    """Preserve the runner's tuple/string API while carrying structured evidence."""
    def __new__(cls, text, *, errors=(), progress=None, termination=None):
        value = super().__new__(cls, text)
        value.errors = list(errors)
        value.progress = dict(progress or {})
        value.termination = termination
        return value


class ErrorEvidence:
    def __init__(self):
        self.tail = deque(maxlen=120)
        self.errors = []
        self.progress = {}

    def feed(self, channel, line):
        if channel == 'stdout' and _PROGRESS.match(line):
            key, _, value = line.partition('=')
            if value not in ('N/A', ''):
                self.progress[key] = value
            return
        if channel == 'stderr' and line:
            self.tail.append(line[:4096])
            severity=re.search(r'\[(fatal|error|warning|info|verbose|debug|trace)\]',line,re.I)
            content=re.sub(r'^(?:\[[^\]]+\]\s*)+','',line)
            fatal=severity.group(1).lower() in {'error','fatal'} if severity else bool(_ERROR.search(line))
            header=line.startswith(('Input #','Output #','  Metadata:','  Stream #'))
            if fatal and not header and not _GENERIC.match(content) and len(self.errors)<24:
                self.errors.append(line[:4096])

    def result(self, termination=None):
        return ProcessEvidence('\n'.join(self.tail), errors=self.errors,
                               progress=self.progress, termination=termination)


class ExportFailure(RuntimeError):
    def __init__(self, reason, *, stage, category, encoder=None, returncode=None,
                 progress=None, suggestion=None, retry_cpu=False, **context):
        super().__init__(reason)
        self.evidence = dict(reason=reason, stage=stage, category=category,
            encoder=encoder, returncode=returncode, progress=dict(progress or {}),
            suggestion=suggestion, retry_cpu=retry_cpu, **context)

    def __str__(self):
        data = self.evidence
        fields = [data['reason']]
        if data['returncode'] is not None:
            fields.append(f"FFmpeg 退出码：{data['returncode']}")
        if data.get('renderer_exitcode') is not None:
            fields.append(f"字幕渲染器退出码：{data['renderer_exitcode']}")
        if data['encoder']:
            fields.append(f"编码器：{data['encoder']}")
        progress = data['progress']
        raw = progress.get('out_time_us') or progress.get('out_time_ms')
        if raw:
            try:
                fields.append(f'最近成功输出：{int(raw)/1000000:.3f} 秒；帧 {progress.get("frame", "未知")}')
            except (TypeError, ValueError):
                pass
        if data.get('video_time_seconds') is not None:
            fields.append(f"视频进度：{data['video_time_seconds']:.3f} 秒")
        if data.get('suggestion'):
            fields.append(data['suggestion'])
        return '\n'.join(fields)


def ffmpeg_failure(code, output, *, encoder, stage='encode', fps=None):
    errors = getattr(output, 'errors', [])
    if not errors:
        fallback=ErrorEvidence()
        for line in str(output).splitlines():fallback.feed('stderr',line)
        errors=fallback.errors
    reason = next(iter(errors), None)
    reason = reason or 'FFmpeg 中途退出，未返回具体错误；请查看完整 stderr 和进程日志。'
    text = '\n'.join(errors or [str(output)]).lower()
    category, advice, retry = 'ffmpeg', '查看完整诊断日志，核对输入媒体和输出磁盘后重新导出。', False
    if any(x in text for x in ('no space left', 'disk full', 'permission denied', 'access is denied', 'read-only file system')):
        category, advice = 'output_io', '检查输出磁盘剩余空间、目录权限和文件占用后重试。'
    elif any(x in text for x in ('could not find tag', 'codec not currently supported', 'muxer does not support')):
        category, advice, stage = 'audio_mux', '源流与容器不兼容；如错误指向音频，可返回设置选择 AAC 后重试。', 'mux'
    elif (str(encoder).endswith('_nvenc') and any(x in text for x in (
            'nvenc', 'cuda_error', 'device lost', 'device removed', 'no capable devices', 'cannot load nvcuda'))):
        category, advice, retry = 'nvenc', '检查 NVIDIA 驱动和 GPU 占用，或选择“改用 CPU 编码重试”。', True
    elif any(x in text for x in ('error submitting packet to decoder', 'invalid data found', 'error during demuxing', 'corrupt decoded frame')):
        category, advice = 'input_media', '检查对应时间附近的源视频是否可完整解码，再重新导出。'
    progress=getattr(output,'progress',{})
    try:
        video_time=int(progress['frame'])/float(fps) if fps else None
    except (KeyError,ValueError,TypeError,ZeroDivisionError):
        video_time=None
    return ExportFailure(reason, stage=stage, category=category, encoder=encoder,
        video_time_seconds=video_time,
        returncode=code, progress=getattr(output, 'progress', {}), suggestion=advice,
        retry_cpu=retry, stderr_tail=str(output), first_errors=errors,
        termination=getattr(output, 'termination', None))


def renderer_failure(code, output):
    errors=getattr(output,'errors',[])
    primary=next((line for line in errors if re.match(r'^(?:[A-Za-z]*Error|Error):',line)),None)
    primary=primary or next((line for line in str(output).splitlines() if re.match(r'^(?:[A-Za-z]*Error|Error):',line)),None)
    return ExportFailure(primary or '字幕渲染器退出，未生成完整覆盖层；请查看完整渲染日志。',
        stage='advanced_render',category='subtitle_renderer',renderer_exitcode=code,
        first_errors=errors,renderer_tail=str(output),
        suggestion='视频编码尚未开始；请查看字幕渲染日志并重试。')
